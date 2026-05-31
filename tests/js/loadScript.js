const vm   = require('vm');
const fs   = require('fs');
const path = require('path');

/**
 * Load a browser script into Jest's jsdom window context so that:
 *   (a) `document`, `window`, etc. are available (jsdom globals)
 *   (b) function declarations land on `global` (= jsdom window)
 *   (c) V8 coverage can track the code
 *
 * Strategy: use vm.runInContext with a context that wraps globalThis
 * (Jest's patched global which IS the jsdom window).  We create the context
 * once from globalThis so the code sees the same `document`, `fetch`, etc.
 *
 * Because vm.createContext() shallow-copies properties, we instead use
 * vm.runInThisContext but bridge it by first setting all necessary globals.
 * For V8 coverage to pick up the files, the code must go through vm (not eval
 * or new Function), and the filename must match the collectCoverageFrom glob.
 *
 * The only remaining issue is that `document` / `window` etc. are properties
 * of Jest's `global` object but are NOT in the vm's "this context" unless we
 * explicitly bridge them.  We solve this by wrapping the code in a with-block
 * that delegates to globalThis.
 */

// Create a vm context that proxies globalThis so everything is visible.
// This means var declarations and function declarations land on globalThis.
// let/const declarations stay in script scope (not accessible from tests),
// so we post-process them into var declarations to expose them globally.
const _ctx = vm.createContext(
    new Proxy(globalThis, {
        has() { return true; },
        get(t, p) { return t[p]; },
        set(t, p, v) { t[p] = v; return true; },
    })
);

/**
 * Rewrite top-level `const X` and `let X` declarations into `var X` so that
 * they land on globalThis (= the vm context sandbox) and are accessible from
 * test files.  We only target lines that start with `const ` or `let ` (after
 * optional whitespace), which is a reliable proxy for top-level declarations in
 * these specific, well-formatted source files.
 *
 * This is intentionally minimal — we don't parse ASTs, we just rewrite the
 * declaration keyword.  The only observable difference is hoisting (var is
 * hoisted to the function/global scope, let/const are block-scoped), which
 * is fine for top-level script declarations.
 */
function _promoteDeclarations(code) {
    // Replace top-level `const ` and `let ` with `var `
    // We avoid replacing inside strings/comments by only matching at the start
    // of a line (possibly preceded by whitespace).
    return code.replace(/^(\s*)(const|let)(\s)/gm, '$1var$3');
}

function loadScript(filename) {
    const fullPath = path.resolve(__dirname, '../../src/minimost/static', filename);
    let code = fs.readFileSync(fullPath, 'utf8');

    // audio-processor.js uses `class Foo extends AudioWorkletProcessor` —
    // class extends clauses need the base class as a lexical variable.
    // Prepend a shim that binds the name from globalThis.
    const preamble = filename === 'audio-processor.js'
        ? 'var AudioWorkletProcessor = globalThis.AudioWorkletProcessor;\n' +
          'var registerProcessor     = globalThis.registerProcessor;\n'
        : '';

    code = _promoteDeclarations(code);

    const script = new vm.Script(preamble + code, {
        filename: fullPath,
        displayErrors: true,
    });
    script.runInContext(_ctx);
}

module.exports = { loadScript };

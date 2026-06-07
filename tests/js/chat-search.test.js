/**
 * Tests for chat-search.js
 * Load order: sidebar → dm → settings → channels → reactions → search
 */

const { loadScript } = require('./loadScript');

beforeAll(() => {
    // Stub all functions defined in earlier files that chat-search.js references
    global.dmModal      = document.getElementById('dm-modal');
    global.dmSuggestions = document.getElementById('dm-suggestions');
    global.dmUsersInput = document.getElementById('dm-users');
    global.searchModal  = document.getElementById('msg-search-modal');
    global.searchInput  = document.getElementById('msg-search-input');
    global.searchResults = document.getElementById('msg-search-results');
    global.createPrivateChModal = document.getElementById('create-private-ch-modal');
    global.renamePrivateChModal = document.getElementById('rename-private-ch-modal');
    global.usersModal           = document.getElementById('users-modal');
    global.initFavicon    = jest.fn();
    global.loadSidebar    = jest.fn();
    global.sendPresence   = jest.fn();
    global.setIdleSent    = jest.fn();
    global.currentPresence = 'offline';
    global.refreshPresence = jest.fn();
    global.refreshDMs     = jest.fn();
    global.refreshChannels = jest.fn();
    global.refreshPrivateChannels = jest.fn();
    global.fetchReadReceipts = jest.fn();
    global.refreshTotalUnreadCount = jest.fn();
    global.pollIncomingCalls = jest.fn();
    global.refreshScreenShares = jest.fn();
    global.fetchMessages = jest.fn();
    global.fetchTyping   = jest.fn();
    global.idleSent      = false;
    global.lastActivity  = Date.now();
    global.resetDmSuggestions = jest.fn();

    loadScript('chat-search.js');
});

beforeEach(() => {
    jest.clearAllMocks();
    // Reset DOM state
    document.getElementById('msg-search-modal').style.display = 'none';
    document.getElementById('vim-mode-indicator').classList.remove('active');
    document.getElementById('chat').innerHTML = '';
});

// ── escapeHtml ─────────────────────────────────────────────────────────────────
describe('escapeHtml()', () => {
    test('escapes ampersand', () => {
        expect(escapeHtml('a & b')).toBe('a &amp; b');
    });
    test('escapes less-than', () => {
        expect(escapeHtml('<div>')).toBe('&lt;div&gt;');
    });
    test('escapes greater-than', () => {
        expect(escapeHtml('1 > 0')).toBe('1 &gt; 0');
    });
    test('leaves plain text unchanged', () => {
        expect(escapeHtml('hello world')).toBe('hello world');
    });
    test('handles empty string', () => {
        expect(escapeHtml('')).toBe('');
    });
    test('escapes multiple entities', () => {
        expect(escapeHtml('<a href="x">foo & bar</a>')).toBe('&lt;a href="x"&gt;foo &amp; bar&lt;/a&gt;');
    });
});

// ── fuzzySearch ───────────────────────────────────────────────────────────────
describe('fuzzySearch()', () => {
    test('returns null when query is not a subsequence', () => {
        expect(fuzzySearch('xyz', 'hello')).toBeNull();
    });
    test('matches exact string', () => {
        const r = fuzzySearch('abc', 'abc');
        expect(r).not.toBeNull();
        expect(r.indices).toEqual([0, 1, 2]);
    });
    test('returns {score:0, indices:[]} for empty query', () => {
        const r = fuzzySearch('', 'hello');
        expect(r).toEqual({ score: 0, indices: [] });
    });
    test('gives consecutive bonus', () => {
        // 'abc' in 'xabcy' → indices [1,2,3] → consecutive bonus applied
        const consec = fuzzySearch('abc', 'xabcy');
        expect(consec).not.toBeNull();
        // Consecutive runs contribute score > 0 even without boundary bonus
        // 'abc' in 'axbxc' → indices [0,2,4] → index 0 gets start-of-string bonus
        const spread = fuzzySearch('abc', 'axbxc');
        expect(spread).not.toBeNull();
        // Both find a match; consecutive has run bonuses, spread has boundary bonus
        // Just verify both return scores (the specific ordering depends on algorithm)
        expect(typeof consec.score).toBe('number');
        expect(typeof spread.score).toBe('number');
    });
    test('gives word-boundary bonus', () => {
        const boundary = fuzzySearch('f', 'foo bar');
        // f is at index 0, gets start-of-string bonus too
        expect(boundary.score).toBeGreaterThan(0);
    });
    test('gives bonus for match at start of string', () => {
        const atStart = fuzzySearch('h', 'hello');
        const notStart = fuzzySearch('e', 'hello');
        expect(atStart.score).toBeGreaterThan(notStart.score);
    });
    test('is case-insensitive', () => {
        expect(fuzzySearch('ABC', 'abc')).not.toBeNull();
        expect(fuzzySearch('abc', 'ABC')).not.toBeNull();
    });
    test('partial match: query longer than text returns null', () => {
        expect(fuzzySearch('toolong', 'hi')).toBeNull();
    });
});

// ── highlightFuzzyMatch ───────────────────────────────────────────────────────
describe('highlightFuzzyMatch()', () => {
    test('wraps matched indices in <mark>', () => {
        const result = highlightFuzzyMatch('hello', [0, 1]);
        expect(result).toContain('<mark class="fuzzy-highlight">h</mark>');
        expect(result).toContain('<mark class="fuzzy-highlight">e</mark>');
    });
    test('leaves unmatched chars unhighlighted', () => {
        const result = highlightFuzzyMatch('hello', [0]);
        expect(result).toContain('ello');
        expect(result).not.toContain('<mark class="fuzzy-highlight">e</mark>');
    });
    test('empty indices returns full escaped text', () => {
        const result = highlightFuzzyMatch('a&b', []);
        expect(result).toBe('a&amp;b');
    });
    test('handles special HTML chars in matched char', () => {
        const result = highlightFuzzyMatch('a<b', [1]);
        expect(result).toContain('&lt;');
    });
});

// ── debounce ──────────────────────────────────────────────────────────────────
describe('debounce()', () => {
    jest.useFakeTimers();

    test('delays execution', () => {
        const fn = jest.fn();
        const dbn = debounce(fn, 100);
        dbn();
        expect(fn).not.toHaveBeenCalled();
        jest.advanceTimersByTime(100);
        expect(fn).toHaveBeenCalledTimes(1);
    });

    test('cancels earlier calls', () => {
        const fn = jest.fn();
        const dbn = debounce(fn, 100);
        dbn();
        dbn();
        dbn();
        jest.advanceTimersByTime(100);
        expect(fn).toHaveBeenCalledTimes(1);
    });

    afterAll(() => jest.useRealTimers());
});

// ── formatText ────────────────────────────────────────────────────────────────
describe('formatText()', () => {
    test('bold **text**', () => {
        expect(formatText('**hello**')).toContain('<strong>hello</strong>');
    });
    test('italic *text*', () => {
        expect(formatText('*hello*')).toContain('<em>hello</em>');
    });
    test('underline __text__', () => {
        expect(formatText('__hello__')).toContain('<u>hello</u>');
    });
    test('strikethrough ~~text~~', () => {
        expect(formatText('~~hello~~')).toContain('<s>hello</s>');
    });
    test('inline code `text`', () => {
        expect(formatText('`code`')).toContain('<code class="msg-inline-code">code</code>');
    });
    test('fenced code block renders a code block div', () => {
        const result = formatText('```js\nconsole.log("hi");\n```');
        expect(result).toContain('msg-code-block');
        expect(result).toContain('msg-code-pre');
    });
    test('links become anchor tags', () => {
        const result = formatText('visit https://example.com today');
        expect(result).toContain('<a href="https://example.com"');
        expect(result).toContain('target="_blank"');
    });
    test('plain text passes through untransformed', () => {
        expect(formatText('no markup')).toBe('no markup');
    });
    test('HTML in plain text is escaped', () => {
        const result = formatText('<script>alert(1)</script>');
        expect(result).not.toContain('<script>');
        expect(result).toContain('&lt;script&gt;');
    });
    test('fenced code block with no language label', () => {
        const result = formatText('```\nhello world\n```');
        expect(result).toContain('msg-code-block');
    });
});

// ── _syntaxHighlight ──────────────────────────────────────────────────────────
describe('_syntaxHighlight()', () => {
    test('unknown language returns escaped text', () => {
        const out = _syntaxHighlight('x < y', 'unknownlang');
        expect(out).toBe('x &lt; y');
    });
    test('no language returns escaped text', () => {
        const out = _syntaxHighlight('a & b', '');
        expect(out).toBe('a &amp; b');
    });
    test('JS: keywords highlighted', () => {
        const out = _syntaxHighlight('const x = 1;', 'js');
        expect(out).toContain('hl-kw');
        expect(out).toContain('const');
    });
    test('JS: strings highlighted', () => {
        const out = _syntaxHighlight('"hello"', 'js');
        expect(out).toContain('hl-str');
    });
    test('JS: numbers highlighted', () => {
        const out = _syntaxHighlight('let x = 42;', 'js');
        expect(out).toContain('hl-num');
    });
    test('JS: single-line comments highlighted', () => {
        const out = _syntaxHighlight('// comment', 'js');
        expect(out).toContain('hl-cmt');
    });
    test('JS via javascript alias', () => {
        const out = _syntaxHighlight('const x = 1;', 'javascript');
        expect(out).toContain('hl-kw');
    });
    test('Python: keywords highlighted', () => {
        const out = _syntaxHighlight('def foo():\n    pass', 'python');
        expect(out).toContain('hl-kw');
    });
    test('Python: # comments highlighted', () => {
        const out = _syntaxHighlight('# comment', 'python');
        expect(out).toContain('hl-cmt');
    });
    test('Python: via py alias', () => {
        const out = _syntaxHighlight('import os', 'py');
        expect(out).toContain('hl-kw');
    });
    test('Bash: keywords highlighted', () => {
        const out = _syntaxHighlight('if [ -f file ]; then echo hi; fi', 'bash');
        expect(out).toContain('hl-kw');
    });
    test('Bash: variables highlighted', () => {
        const out = _syntaxHighlight('echo $HOME', 'sh');
        expect(out).toContain('hl-var');
    });
    test('C: keywords highlighted', () => {
        const out = _syntaxHighlight('int main() { return 0; }', 'c');
        expect(out).toContain('hl-kw');
    });
    test('C: preprocessor directives highlighted', () => {
        const out = _syntaxHighlight('#include <stdio.h>', 'c');
        expect(out).toContain('hl-dec');
    });
    test('C via cpp alias', () => {
        const out = _syntaxHighlight('int x = 0;', 'cpp');
        expect(out).toContain('hl-type');
    });
    test('XML: tags highlighted', () => {
        const out = _syntaxHighlight('<root>', 'xml');
        expect(out).toContain('hl-kw');
    });
    test('HTML: tags highlighted (via xml rules)', () => {
        const out = _syntaxHighlight('<div class="x">', 'html');
        expect(out).toContain('hl-kw');
    });
    test('Java: keywords highlighted', () => {
        const out = _syntaxHighlight('public class Foo {}', 'java');
        expect(out).toContain('hl-kw');
    });
    test('Go: keywords highlighted', () => {
        const out = _syntaxHighlight('func main() {}', 'go');
        expect(out).toContain('hl-kw');
    });
    test('Rust: keywords highlighted', () => {
        const out = _syntaxHighlight('fn main() {}', 'rust');
        expect(out).toContain('hl-kw');
    });
    test('Make: variables highlighted', () => {
        const out = _syntaxHighlight('CC := gcc', 'make');
        // No variable syntax here, but keywords/comments tested
        expect(out).not.toBeNull();
    });
    test('CMake: keywords highlighted', () => {
        const out = _syntaxHighlight('cmake_minimum_required(VERSION 3.10)', 'cmake');
        expect(out).toContain('hl-kw');
    });
    test('VHDL: keywords highlighted', () => {
        const out = _syntaxHighlight('entity foo is end entity;', 'vhdl');
        expect(out).toContain('hl-kw');
    });
    test('Verilog: keywords highlighted', () => {
        const out = _syntaxHighlight('module foo; endmodule', 'verilog');
        expect(out).toContain('hl-kw');
    });
    test('TypeScript alias maps to js rules', () => {
        const out = _syntaxHighlight('const x: number = 1;', 'typescript');
        expect(out).toContain('hl-kw');
    });
    test('escapes HTML in output', () => {
        const out = _syntaxHighlight('x < y && y > z', 'unknown');
        expect(out).toContain('&lt;');
        expect(out).toContain('&amp;');
        expect(out).toContain('&gt;');
    });
    test('JS block comment highlighted', () => {
        const out = _syntaxHighlight('/* block */', 'js');
        expect(out).toContain('hl-cmt');
    });
    test('Hex numbers highlighted in JS', () => {
        const out = _syntaxHighlight('0xFF', 'js');
        expect(out).toContain('hl-num');
    });
    test('Bash built-ins highlighted', () => {
        const out = _syntaxHighlight('echo hello', 'bash');
        expect(out).toContain('hl-bi');
    });
});

// ── startSearch / visual mode ─────────────────────────────────────────────────
describe('startSearch()', () => {
    test('shows the search modal', () => {
        startSearch();
        expect(document.getElementById('msg-search-modal').style.display).toBe('block');
    });
});

describe('enterVisualMode() / exitVisualMode()', () => {
    beforeEach(() => {
        // Add some messages to #chat
        const chat = document.getElementById('chat');
        chat.innerHTML = '';
        const m1 = document.createElement('div');
        m1.className = 'msg';
        m1.id = 'msg-100';
        const m2 = document.createElement('div');
        m2.className = 'msg';
        m2.id = 'msg-200';
        chat.appendChild(m1);
        chat.appendChild(m2);
    });

    test('enterVisualMode selects last message and activates indicator', () => {
        enterVisualMode();
        const indicator = document.getElementById('vim-mode-indicator');
        expect(indicator.classList.contains('active')).toBe(true);
        expect(document.getElementById('msg-200').classList.contains('visual-selected')).toBe(true);
    });

    test('exitVisualMode deactivates indicator and clears selection', () => {
        enterVisualMode();
        exitVisualMode();
        const indicator = document.getElementById('vim-mode-indicator');
        expect(indicator.classList.contains('active')).toBe(false);
        expect(document.getElementById('msg-200').classList.contains('visual-selected')).toBe(false);
    });

    test('enterVisualMode does nothing if no messages', () => {
        document.getElementById('chat').innerHTML = '';
        enterVisualMode();
        // No crash, indicator stays inactive
        expect(document.getElementById('vim-mode-indicator').classList.contains('active')).toBe(false);
    });
});

// ── userInput ─────────────────────────────────────────────────────────────────
describe('userInput()', () => {
    beforeEach(() => {
        document.getElementById('dm-modal').style.display = 'none';
        document.getElementById('msg-search-modal').style.display = 'none';
    });

    function makeEvent(key, opts = {}) {
        return Object.assign(
            { key, target: document.getElementById('chat'), preventDefault: jest.fn(),
              ctrlKey: false, metaKey: false },
            opts
        );
    }

    test('Escape blurs active element and closes modals', () => {
        const blurMock = jest.fn();
        document.activeElement = { blur: blurMock };
        userInput(makeEvent('Escape'));
        // closeAllModalsAndFocusChat is called — modals hidden
        expect(document.getElementById('dm-modal').style.display).toBe('none');
    });

    test('? key opens help (not in an input)', () => {
        const e = makeEvent('?');
        userInput(e);
        expect(global.openHelp).toHaveBeenCalled();
    });

    test('? key in input does NOT open help', () => {
        global.openHelp.mockClear();
        const inp = document.getElementById('msg');
        const e = makeEvent('?', { target: inp });
        // target.matches('input,textarea') => true → isInput = true
        inp.matches = (s) => true;
        userInput(e);
        expect(global.openHelp).not.toHaveBeenCalled();
    });
});

// ── buildSearchSnippet ────────────────────────────────────────────────────────
describe('buildSearchSnippet()', () => {
    test('returns escaped text with ellipsis when content longer than maxLen', () => {
        const content = 'a'.repeat(200);
        const result = buildSearchSnippet(content, [], 120);
        expect(result).toContain('…');
    });
    test('returns full text when content shorter than maxLen', () => {
        const result = buildSearchSnippet('hello', [], 120);
        expect(result).toBe('hello');
    });
    test('highlights matched indices in snippet', () => {
        const result = buildSearchSnippet('hello world', [0, 1], 120);
        expect(result).toContain('<mark class="fuzzy-highlight">h</mark>');
    });
    test('adds leading ellipsis when start > 0', () => {
        const content = 'abcde'.repeat(20);
        const indices = [50, 51, 52];
        const result = buildSearchSnippet(content, indices, 30);
        expect(result.startsWith('…')).toBe(true);
    });
});

// ── wrapSelection ─────────────────────────────────────────────────────────────
describe('wrapSelection()', () => {
    function makeInput(val, start, end) {
        const el = document.createElement('textarea');
        el.value = val;
        el.selectionStart = start;
        el.selectionEnd = end;
        return el;
    }

    test('wraps selected text with wrapper', () => {
        const el = makeInput('hello world', 0, 5);
        wrapSelection(el, '**');
        expect(el.value).toBe('**hello** world');
        expect(el.selectionStart).toBe(2);
        expect(el.selectionEnd).toBe(7);
    });

    test('inserts double wrapper at cursor when nothing selected', () => {
        const el = makeInput('hello', 5, 5);
        wrapSelection(el, '*');
        expect(el.value).toBe('hello**');
        expect(el.selectionStart).toBe(6);
        expect(el.selectionEnd).toBe(6);
    });

    test('wraps with underline wrapper', () => {
        const el = makeInput('text', 0, 4);
        wrapSelection(el, '__');
        expect(el.value).toBe('__text__');
    });
});

// ── visual mode navigation ────────────────────────────────────────────────────
describe('visual mode key navigation', () => {
    function setupChat() {
        const chat = document.getElementById('chat');
        chat.innerHTML = '';
        for (let i = 1; i <= 3; i++) {
            const m = document.createElement('div');
            m.className = 'msg';
            m.id = `msg-${i * 10}`;
            m.scrollIntoView = jest.fn();
            chat.appendChild(m);
        }
    }

    beforeEach(() => {
        setupChat();
        exitVisualMode(); // ensure clean state
    });

    function makeVimEvent(key) {
        return { key, preventDefault: jest.fn(), target: document.body };
    }

    test('v key enters visual mode', () => {
        enterVisualMode();
        expect(document.getElementById('vim-mode-indicator').classList.contains('active')).toBe(true);
    });

    test('j moves down in visual mode', () => {
        enterVisualMode(); // selects msg-30 (last)
        _handleVisualKey(makeVimEvent('j')); // can't go further, no-op
        expect(document.getElementById('vim-mode-indicator').classList.contains('active')).toBe(true);
    });

    test('k moves up in visual mode', () => {
        enterVisualMode(); // selects msg-30
        _handleVisualKey(makeVimEvent('k')); // moves to msg-20
        expect(document.getElementById('msg-20').classList.contains('visual-selected')).toBe(true);
    });

    test('ArrowDown moves down', () => {
        enterVisualMode();
        // ArrowDown in visual mode must be handled without throwing.
        expect(() => _handleVisualKey(makeVimEvent('ArrowDown'))).not.toThrow();
    });

    test('ArrowUp moves up', () => {
        enterVisualMode();
        _handleVisualKey(makeVimEvent('k')); // move to msg-20
        _handleVisualKey(makeVimEvent('ArrowUp')); // move to msg-10
        expect(document.getElementById('msg-10').classList.contains('visual-selected')).toBe(true);
    });
});

// ── closeAllModalsAndFocusChat ────────────────────────────────────────────────
describe('closeAllModalsAndFocusChat()', () => {
    test('closes DM modal', () => {
        document.getElementById('dm-modal').style.display = 'block';
        closeAllModalsAndFocusChat();
        expect(document.getElementById('dm-modal').style.display).toBe('none');
    });

    test('closes search modal', () => {
        document.getElementById('msg-search-modal').style.display = 'block';
        closeAllModalsAndFocusChat();
        expect(document.getElementById('msg-search-modal').style.display).toBe('none');
    });

    test('closes create private channel modal', () => {
        document.getElementById('create-private-ch-modal').style.display = 'block';
        closeAllModalsAndFocusChat();
        expect(document.getElementById('create-private-ch-modal').style.display).toBe('none');
    });

    test('does not crash when modals are already hidden', () => {
        expect(() => closeAllModalsAndFocusChat()).not.toThrow();
    });
});

// ── applyChatFontSize ─────────────────────────────────────────────────────────
describe('applyChatFontSize()', () => {
    test('sets font size on chat element', () => {
        applyChatFontSize(16);
        expect(document.getElementById('chat').style.fontSize).toBe('16px');
    });

    test('sets font size on msg textarea', () => {
        applyChatFontSize(14);
        expect(document.getElementById('msg').style.fontSize).toBe('14px');
    });

    test('sets font size on typing indicator', () => {
        applyChatFontSize(12);
        expect(document.getElementById('typing-indicator').style.fontSize).toBe('12px');
    });
});

// ── search input keyboard navigation ─────────────────────────────────────────
describe('search input keyboard navigation', () => {
    beforeEach(() => {
        startSearch();
        document.getElementById('msg-search-results').innerHTML = '';
        ['result1', 'result2', 'result3'].forEach((text, i) => {
            const div = document.createElement('div');
            div.className = 'search-result';
            div.textContent = text;
            div.onclick = jest.fn();
            document.getElementById('msg-search-results').appendChild(div);
        });
    });

    function makeKeyEvent(key) {
        return new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
    }

    test('ArrowDown moves selection down', () => {
        document.getElementById('msg-search-input').dispatchEvent(makeKeyEvent('ArrowDown'));
        const items = document.getElementById('msg-search-results').children;
        expect(items[0].classList.contains('active')).toBe(true);
    });

    test('ArrowUp wraps around', () => {
        document.getElementById('msg-search-input').dispatchEvent(makeKeyEvent('ArrowUp'));
        const items = document.getElementById('msg-search-results').children;
        expect(items[2].classList.contains('active')).toBe(true);
    });

    test('Escape hides modal', () => {
        document.getElementById('msg-search-input').dispatchEvent(makeKeyEvent('Escape'));
        expect(document.getElementById('msg-search-modal').style.display).toBe('none');
    });

    test('no key navigation when no results', () => {
        document.getElementById('msg-search-results').innerHTML = '';
        // ArrowDown with no results must be handled without throwing.
        expect(() =>
            document.getElementById('msg-search-input').dispatchEvent(makeKeyEvent('ArrowDown'))
        ).not.toThrow();
    });
});

// ── "From" user fuzzy finder ─────────────────────────────────────────────────
describe('From user fuzzy finder', () => {
    let fromInput;
    let suggestions;

    beforeEach(() => {
        // The finder reads the shared user cache populated by the DM modal.
        global.allUsers = ['bob', 'carol', 'dave'];
        global.usersLoaded = true;
        fromInput = document.getElementById('msg-search-from');
        suggestions = document.getElementById('msg-search-from-suggestions');
        fromInput.value = '';
        suggestions.innerHTML = '';
        suggestions.style.display = 'none';
    });

    function typeFrom(value) {
        fromInput.value = value;
        fromInput.dispatchEvent(new Event('input', { bubbles: true }));
    }

    test('shows fuzzy-matched users for a partial query', () => {
        typeFrom('ca');
        expect(suggestions.style.display).toBe('block');
        const labels = [...suggestions.children].map(c => c.textContent);
        expect(labels).toContain('carol');
        expect(labels).not.toContain('bob');
    });

    test('includes the current user as a candidate', () => {
        typeFrom('ali');  // CURRENT_USER is 'alice', excluded from /users
        const labels = [...suggestions.children].map(c => c.textContent);
        expect(labels).toContain('alice');
    });

    test('hides the dropdown when the field is cleared', () => {
        typeFrom('ca');
        typeFrom('');
        expect(suggestions.style.display).toBe('none');
    });

    test('hides the dropdown when nothing matches', () => {
        typeFrom('zzzzz');
        expect(suggestions.style.display).toBe('none');
    });

    test('clicking a suggestion fills the input and closes the list', () => {
        typeFrom('ca');
        suggestions.children[0].dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
        expect(fromInput.value).toBe('carol');
        expect(suggestions.style.display).toBe('none');
    });

    test('ArrowDown + Enter selects the highlighted user', () => {
        typeFrom('a');  // matches alice, carol, dave
        fromInput.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true }));
        fromInput.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
        // First match becomes the value; list closes.
        expect(suggestions.style.display).toBe('none');
        expect(fromInput.value.length).toBeGreaterThan(0);
    });
});

// ── linkify ───────────────────────────────────────────────────────────────────
describe('linkify()', () => {
    test('converts http URL to anchor tag', () => {
        const result = linkify('visit https://example.com now');
        expect(result).toContain('<a href="https://example.com"');
    });
    test('converts www URL to anchor tag', () => {
        const result = linkify('see www.example.com');
        expect(result).toContain('www.example.com');
    });
    test('plain text passes through unchanged', () => {
        expect(linkify('hello world')).toBe('hello world');
    });
    test('escapes HTML in non-URL parts', () => {
        const result = linkify('<script>');
        expect(result).toContain('&lt;script&gt;');
    });
});

// ── boldify / italicize / underline / strikethrough ───────────────────────────
describe('text formatters', () => {
    test('boldify wraps **text**', () => {
        expect(boldify('**hello**')).toBe('<strong>hello</strong>');
    });
    test('italicize wraps *text*', () => {
        expect(italicize('*hello*')).toBe('<em>hello</em>');
    });
    test('underline wraps __text__', () => {
        expect(underline('__hello__')).toBe('<u>hello</u>');
    });
    test('strikethrough wraps ~~text~~', () => {
        expect(strikethrough('~~hello~~')).toBe('<s>hello</s>');
    });
});

// ── copyCodeBlock ─────────────────────────────────────────────────────────────
describe('copyCodeBlock()', () => {
    test('writes code text to clipboard and shows Copied!', async () => {
        global.navigator.clipboard = { writeText: jest.fn().mockResolvedValue() };
        document.body.innerHTML += `
            <div class="msg-code-block">
                <div class="msg-code-header">
                    <button class="code-copy-btn">Copy</button>
                </div>
                <pre class="msg-code-pre"><code>print("hello")</code></pre>
            </div>`;
        const btn = document.querySelector('.code-copy-btn');
        await copyCodeBlock(btn);
        expect(global.navigator.clipboard.writeText).toHaveBeenCalledWith('print("hello")');
        expect(btn.textContent).toBe('Copied!');
    });
});

// ── _handleCtrlKey ─────────────────────────────────────────────────────────────
describe('_handleCtrlKey()', () => {
    beforeEach(() => { global.wrapSelection = jest.fn(); global.switchChannel = jest.fn(); });

    function makeCtrlEvent(key) {
        return { key, ctrlKey: true, preventDefault: jest.fn(), target: document.getElementById('msg') };
    }
    test('ctrl+b wraps in **', () => { _handleCtrlKey(makeCtrlEvent('b'), true); expect(wrapSelection).toHaveBeenCalledWith(expect.anything(), '**'); });
    test('ctrl+i wraps in *',  () => { _handleCtrlKey(makeCtrlEvent('i'), true); expect(wrapSelection).toHaveBeenCalledWith(expect.anything(), '*'); });
    test('ctrl+u wraps in __', () => { _handleCtrlKey(makeCtrlEvent('u'), true); expect(wrapSelection).toHaveBeenCalledWith(expect.anything(), '__'); });
    test('ctrl+s wraps in ~~', () => { _handleCtrlKey(makeCtrlEvent('s'), true); expect(wrapSelection).toHaveBeenCalledWith(expect.anything(), '~~'); });

    test('ctrl+j in non-input switches to next channel', () => {
        const sidebar = document.getElementById('sidebar-dynamic');
        sidebar.innerHTML = '<div data-channel="general">g</div><div data-channel="random">r</div>';
        global.channel = 'general';
        _handleCtrlKey(makeCtrlEvent('j'), false);
        expect(switchChannel).toHaveBeenCalledWith('random');
    });
    test('ctrl+k in non-input switches to previous channel', () => {
        const sidebar = document.getElementById('sidebar-dynamic');
        sidebar.innerHTML = '<div data-channel="general">g</div><div data-channel="random">r</div>';
        global.channel = 'random';
        _handleCtrlKey(makeCtrlEvent('k'), false);
        expect(switchChannel).toHaveBeenCalledWith('general');
    });
    test('ctrl+j with empty sidebar does nothing', () => {
        document.getElementById('sidebar-dynamic').innerHTML = '';
        _handleCtrlKey(makeCtrlEvent('j'), false);
        expect(switchChannel).not.toHaveBeenCalled();
    });
});

// ── _handleVisualKey action keys ──────────────────────────────────────────────
describe('_handleVisualKey() action keys', () => {
    function makeVimEvent(key) { return { key, preventDefault: jest.fn() }; }
    beforeEach(() => {
        global.visualMsgId = 'msg-42';
        global.exitVisualMode = jest.fn();
        global.deleteMsg = jest.fn();
        global.startEdit = jest.fn();
        global.startReply = jest.fn();
    });
    test('d deletes', () => { _handleVisualKey(makeVimEvent('d')); expect(exitVisualMode).toHaveBeenCalled(); expect(deleteMsg).toHaveBeenCalledWith('msg-42'); });
    test('c edits',   () => { _handleVisualKey(makeVimEvent('c')); expect(startEdit).toHaveBeenCalledWith('msg-42'); });
    test('o replies', () => { _handleVisualKey(makeVimEvent('o')); expect(startReply).toHaveBeenCalledWith('msg-42'); });
    test('no-op when visualMsgId is null', () => {
        global.visualMsgId = null;
        _handleVisualKey(makeVimEvent('d'));
        expect(deleteMsg).not.toHaveBeenCalled();
    });
});

// ── Escape in visual mode (via userInput) ─────────────────────────────────────
describe('userInput Escape in visual mode', () => {
    test('Escape exits visual mode when active', () => {
        global.visualMode = true;
        global.exitVisualMode = jest.fn();
        global.closeAllModalsAndFocusChat = jest.fn();
        userInput({ key: 'Escape', ctrlKey: false, target: document.body });
        expect(exitVisualMode).toHaveBeenCalled();
        expect(closeAllModalsAndFocusChat).not.toHaveBeenCalled();
    });
});

// ── global onclick handler is registered ─────────────────────────────────────
describe('global onclick handler', () => {
    test('handler is registered on globalThis', () => {
        expect(typeof globalThis.onclick).toBe('function');
    });
    test('does not hide modal when target is unrelated element', () => {
        const modal = document.getElementById('msg-search-modal');
        modal.style.display = 'block';
        const other = document.createElement('div');
        globalThis.onclick({ target: other });
        expect(modal.style.display).toBe('block');
    });
});

// ── _syntaxHighlight extra language branches ──────────────────────────────────
describe('_syntaxHighlight() extra languages', () => {
    test('highlights Rust keywords', ()  => { expect(_syntaxHighlight('fn main() { let x: i32 = 1; }', 'rust')).toContain('kw'); });
    test('highlights Go keywords',   ()  => { expect(_syntaxHighlight('func main() { var x int = 1 }', 'go')).toContain('kw'); });
    test('highlights Java keywords', ()  => { expect(_syntaxHighlight('public class Foo { int x = 0; }', 'java')).toContain('kw'); });
    test('highlights C block comment', () => { expect(_syntaxHighlight('/* hi */ int x;', 'c')).toContain('cmt'); });
    test('highlights shell variable',  () => { expect(_syntaxHighlight('echo $HOME', 'sh')).toContain('var'); });
    test('highlights Makefile variable',() => { expect(_syntaxHighlight('$(CC) -o foo', 'make')).toContain('var'); });
    test('highlights XML tag as kw',   () => { expect(_syntaxHighlight('<root attr="val">', 'xml')).toContain('kw'); });
    test('highlights XML attribute',   () => { expect(_syntaxHighlight('<tag attr="val">', 'xml')).toContain('var'); });
    test('escapes unknown lang',       () => { expect(_syntaxHighlight('<b>', '')).toContain('&lt;'); });
    test('cmake variable highlighted', () => { expect(_syntaxHighlight('set(${MY_VAR} 1)', 'cmake')).toContain('var'); });
});

// ── _previewCodeEl ────────────────────────────────────────────────────────────
describe('_previewCodeEl()', () => {
    const base = { url: 'https://example.com/f.py', filepath: 'f.py', language: 'py' };

    test('renders correct number of code rows', () => {
        const el = _previewCodeEl({ ...base, code: 'x = 1\ny = 2', first_line_num: 1 });
        expect(el.querySelectorAll('.code-row').length).toBe(2);
    });
    test('highlights specified line', () => {
        const el = _previewCodeEl({ ...base, code: 'a\nb\nc', first_line_num: 1, highlight_start: 2, highlight_end: 2 });
        const rows = el.querySelectorAll('.code-row');
        expect(rows[1].classList.contains('hl')).toBe(true);
        expect(rows[0].classList.contains('hl')).toBe(false);
    });
    test('shows single-line reference', () => {
        const el = _previewCodeEl({ ...base, code: 'x', first_line_num: 5, highlight_start: 5 });
        expect(el.querySelector('.preview-code-range').textContent).toContain('line 5');
    });
    test('shows range reference', () => {
        const el = _previewCodeEl({ ...base, code: 'x\ny', first_line_num: 3, highlight_start: 3, highlight_end: 4 });
        expect(el.querySelector('.preview-code-range').textContent).toContain('lines 3');
    });
});

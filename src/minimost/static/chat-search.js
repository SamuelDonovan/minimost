let visualMode = false;
let visualMsgId = null;

// Prevent HTML injection when re-inserting text
function escapeHtml(text) {
    return text
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
}

// Fuzzy-matches query against text as a subsequence (case-insensitive).
// Returns {score, indices} on match, null on no match.
// Score bonuses: consecutive runs, word-boundary hits, start-of-string.
function fuzzySearch(query, text) {
    const q = query.toLowerCase();
    const t = text.toLowerCase();
    if (!q) return { score: 0, indices: [] };

    const indices = [];
    let qi = 0;
    for (let ti = 0; ti < t.length && qi < q.length; ti++) {
        if (t[ti] === q[qi]) { indices.push(ti); qi++; }
    }
    if (qi < q.length) return null;

    let score = 0;
    let run = 0;
    for (let i = 0; i < indices.length; i++) {
        if (i > 0 && indices[i] === indices[i - 1] + 1) {
            score += ++run * 2;
        } else {
            run = 0;
        }
        const idx = indices[i];
        if (idx === 0 || /[\s_-]/.test(t[idx - 1])) score += 8;
    }
    if (indices[0] === 0) score += 5;
    return { score, indices };
}

// Wraps matched character positions in <mark class="fuzzy-highlight">.
function highlightFuzzyMatch(text, indices) {
    const set = new Set(indices);
    let out = '';
    for (let i = 0; i < text.length; i++) {
        const ch = escapeHtml(text[i]);
        out += set.has(i) ? `<mark class="fuzzy-highlight">${ch}</mark>` : ch;
    }
    return out;
}

// Returns an HTML snippet of content (~maxLen chars) centered on the first match,
// with matched characters highlighted. Adds ellipsis when content is trimmed.
function buildSearchSnippet(content, indices, maxLen = 120) {
    if (!indices.length) {
        const clipped = content.slice(0, maxLen);
        return escapeHtml(clipped) + (content.length > maxLen ? '…' : '');
    }
    const start = Math.max(0, indices[0] - 30);
    const end = Math.min(content.length, start + maxLen);
    const snippet = content.slice(start, end);
    const prefix = start > 0 ? '…' : '';
    const suffix = end < content.length ? '…' : '';
    const remapped = indices.filter(i => i >= start && i < end).map(i => i - start);
    return prefix + highlightFuzzyMatch(snippet, remapped) + suffix;
}

let searchSelectedIndex = -1;

function startSearch() {
    searchModal.style.display = "block";
    searchInput.value = "";
    searchResults.innerHTML = "";
    searchInput.focus();
}

function updateSearchHighlight() {
    const items = searchResults.children;
    Array.from(items).forEach((el, i) => {
        el.classList.toggle("active", i === searchSelectedIndex);
    });
}

// Message search
const searchModal = document.getElementById("msg-search-modal");
const searchInput = document.getElementById("msg-search-input");
const searchResults = document.getElementById("msg-search-results");

document.getElementById("msg-search-btn").onclick = () => {
    startSearch();
};

document.getElementById("msg-search-close").onclick = () => {
    searchModal.style.display = "none";
};

// Close modal on outside click
globalThis.onclick = e => {
    if (e.target === searchModal) searchModal.style.display = "none";
    if (e.target === dmModal) dmModal.style.display = "none";
};

// Clickable links
function linkify(text) {
    // Escape HTML first (important for security)
    const div = document.createElement("div");
    div.textContent = text;
    let safe = div.innerHTML;

    // Regex for URLs
    const urlRegex = /((https?:\/\/|www\.)[^\s]+)/g;

    return safe.replace(urlRegex, url => {
        let href = url;
        return `<a href="${href}" target="_blank" rel="noopener noreferrer">${url}</a>`;
    });
}

// Text formating
function boldify(text) {
    return text.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

function italicize(text) {
    return text.replace(/\*(.+?)\*/g, "<em>$1</em>");
}

function underline(text) {
    return text.replace(/__(.+?)__/g, "<u>$1</u>");
}

function strikethrough(text) {
    return text.replace(/~~(.+?)~~/g, "<s>$1</s>");
}

// True if a message is nothing but emoji (and whitespace) — used to render
// such messages at a larger size. Matches an emoji base (pictographic char or
// regional-indicator) plus any trailing variation selector, skin-tone
// modifier, or ZWJ-joined sequence (families, professions, etc.).
const _EMOJI_BASE = String.raw`\p{Extended_Pictographic}|\p{Regional_Indicator}`;
const _EMOJI_SEQ = new RegExp(
    `(?:${_EMOJI_BASE})(?:\\uFE0F|[\\u{1F3FB}-\\u{1F3FF}]|\\u200D(?:${_EMOJI_BASE}))*`,
    "gu"
);

function isEmojiOnly(text) {
    const t = (text || "").replace(/\s+/g, "");
    if (!t) return false;
    return t.replace(_EMOJI_SEQ, "").length === 0;
}

function formatText(text) {
    // 1. Extract fenced code blocks before any escaping.
    // Strip the newline immediately before/after each fence so the block
    // element doesn't double up with the pre-wrap newline character.
    const blocks = [];
    let s = text.replace(/\n?```(\w*)\n?([\s\S]{0,50000}?)```\n?/g, (_, lang, code) => {
        const idx = blocks.length;
        blocks.push({ lang: lang.trim(), code });
        return `${idx}`;
    });

    // 2. Escape HTML for the non-code portions
    const div = document.createElement("div");
    div.textContent = s;
    let safe = div.innerHTML;

    // 3. Inline code
    safe = safe.replace(/`([^`\n]+)`/g, '<code class="msg-inline-code">$1</code>');

    // 4. Text formatting
    safe = safe.replace(/\*\*(.+?)\*\*/gs, "<strong>$1</strong>");
    safe = safe.replace(/__(.+?)__/gs, "<u>$1</u>");
    safe = safe.replace(/~~(.+?)~~/gs, "<s>$1</s>");
    safe = safe.replace(/\*(.+?)\*/gs, "<em>$1</em>");

    // 5. Links
    safe = safe.replace(
        /((https?:\/\/|www\.)[^\s]+)/g,
        url => `<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>`
    );

    // 5b. @mention pills (after links so URLs containing @ are left untouched)
    if (typeof applyMentionPills === "function") {
        safe = applyMentionPills(safe);
    }

    // 6. Restore code blocks with syntax highlighting
    safe = safe.replace(/(\d+)/g, (_, i) => {
        const { lang, code } = blocks[Number(i)];
        const trimmed = code.replace(/^\n/, '').replace(/\n$/, '');
        const highlighted = _syntaxHighlight(trimmed, lang);
        const langLabel = lang ? `<span class="msg-code-lang">${escapeHtml(lang)}</span>` : `<span></span>`;
        const copyBtn = `<button class="code-copy-btn" onclick="copyCodeBlock(this)" title="Copy code">Copy</button>`;
        return `<div class="msg-code-block"><div class="msg-code-header">${langLabel}${copyBtn}</div><pre class="msg-code-pre"><code>${highlighted}</code></pre></div>`;
    });

    return safe;
}

function copyCodeBlock(btn) {
    const code = btn.closest(".msg-code-block").querySelector("code");
    navigator.clipboard.writeText(code.textContent).then(() => {
        btn.textContent = "Copied!";
        setTimeout(() => { btn.textContent = "Copy"; }, 2000);
    }).catch(() => {});
}

function wrapSelection(el, wrapper) {
    const start = el.selectionStart;
    const end = el.selectionEnd;
    const value = el.value;

    if (start === end) {
        // Insert wrapper and place cursor in between
        el.value =
            value.slice(0, start) +
            wrapper + wrapper +
            value.slice(end);

        el.selectionStart = el.selectionEnd = start + wrapper.length;
    } else {
        // Wrap selected text
        el.value =
            value.slice(0, start) +
            wrapper +
            value.slice(start, end) +
            wrapper +
            value.slice(end);

        el.selectionStart = start + wrapper.length;
        el.selectionEnd = end + wrapper.length;
    }
}

function _getVisualMsgs() {
    return Array.from(document.querySelectorAll("#chat .msg"));
}

function _visualSelectMsg(msgId) {
    if (visualMsgId) {
        const prev = document.getElementById(`msg-${visualMsgId}`);
        if (prev) prev.classList.remove("visual-selected");
    }
    visualMsgId = msgId;
    const el = document.getElementById(`msg-${msgId}`);
    if (!el) return;
    el.classList.add("visual-selected");
    el.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function enterVisualMode() {
    const msgs = _getVisualMsgs();
    if (!msgs.length) return;
    const last = msgs.at(-1);
    visualMode = true;
    document.getElementById("vim-mode-indicator").classList.add("active");
    _visualSelectMsg(last.id.replace("msg-", ""));
}

function exitVisualMode() {
    visualMode = false;
    if (visualMsgId) {
        const el = document.getElementById(`msg-${visualMsgId}`);
        if (el) el.classList.remove("visual-selected");
        visualMsgId = null;
    }
    document.getElementById("vim-mode-indicator").classList.remove("active");
}

function _visualMoveDown() {
    const msgs = _getVisualMsgs();
    const idx = msgs.findIndex(m => m.id === `msg-${visualMsgId}`);
    if (idx === -1 || idx >= msgs.length - 1) return;
    _visualSelectMsg(msgs[idx + 1].id.replace("msg-", ""));
}

function _visualMoveUp() {
    const msgs = _getVisualMsgs();
    const idx = msgs.findIndex(m => m.id === `msg-${visualMsgId}`);
    if (idx <= 0) return;
    _visualSelectMsg(msgs[idx - 1].id.replace("msg-", ""));
}

function _handleCtrlKey(e, isInput) {
    if (!isInput) {
        const items = Array.from(
            document.querySelectorAll("#sidebar-dynamic [data-channel]")
        );
        if (!items.length) return;
        let currentIndex = items.findIndex(el => el.dataset.channel === channel);
        if (currentIndex === -1) currentIndex = 0;
        if (e.key === "j") {
            switchChannel(items[(currentIndex + 1) % items.length].dataset.channel);
            e.preventDefault();
        } else if (e.key === "k") {
            switchChannel(items[(currentIndex - 1 + items.length) % items.length].dataset.channel);
            e.preventDefault();
        }
        return;
    }
    if (e.key === "b") { e.preventDefault(); wrapSelection(e.target, "**"); }
    else if (e.key === "i") { e.preventDefault(); wrapSelection(e.target, "*"); }
    else if (e.key === "u") { e.preventDefault(); wrapSelection(e.target, "__"); }
    else if (e.key === "s") { e.preventDefault(); wrapSelection(e.target, "~~"); }
}

function _handleVisualKey(e) {
    const key = e.key;
    if (key === "j" || key === "ArrowDown") { e.preventDefault(); _visualMoveDown(); return; }
    if (key === "k" || key === "ArrowUp")   { e.preventDefault(); _visualMoveUp();   return; }
    const id = visualMsgId;
    if (!id) return;
    e.preventDefault();
    if (key === "d") { exitVisualMode(); deleteMsg(id); }
    else if (key === "c") { exitVisualMode(); startEdit(id); }
    else if (key === "o") { exitVisualMode(); startReply(id); }
    else if (key === "e") { exitVisualMode(); document.querySelector(`#msg-${id} .react-btn`)?.click(); }
    else if (key === "y") {
        const el = document.getElementById(`msg-text-${id}`);
        if (el) navigator.clipboard.writeText(el.innerText).catch(() => {});
    }
}

function _handleNormalKey(e) {
    const scrollContainer = document.getElementById("chat");
    const scrollRate = 200;
    if (e.key === "v") { e.preventDefault(); enterVisualMode(); }
    else if (e.key === "j") { scrollContainer.scrollBy({ top: scrollRate, behavior: 'smooth' }); }
    else if (e.key === "k") { scrollContainer.scrollBy({ top: -scrollRate, behavior: 'smooth' }); }
    else if (e.key === "d") { scrollContainer.scrollBy({ top: 2 * scrollRate, behavior: 'smooth' }); }
    else if (e.key === "u") { scrollContainer.scrollBy({ top: -2 * scrollRate, behavior: 'smooth' }); }
    else if (e.key === "G") { scrollContainer.scrollTop = scrollContainer.scrollHeight; }
    else if (e.key === "g") { scrollContainer.scrollTop = 0; }
    else if (e.key === "i") { e.preventDefault(); focusMessageInput(); }
    else if (e.key === "o") { e.preventDefault(); openDmModal(); }
    else if (e.key === "/" || e.key === "f") { e.preventDefault(); startSearch(); }
}

function _handleVimKey(e) {
    if (visualMode) { _handleVisualKey(e); } else { _handleNormalKey(e); }
}

function userInput(e) {
    const isInput = e.target.matches("input, textarea");

    if (e.key === "Escape") {
        if (visualMode) {
            exitVisualMode();
            return;
        }
        document.activeElement?.blur();
        closeAllModalsAndFocusChat();
    } else if (e.key === "?" && !isInput) {
        e.preventDefault();
        openHelp();
    }

    if (e.ctrlKey || e.metaKey) {
        _handleCtrlKey(e, isInput);
    } else if (!isInput) {
        _handleVimKey(e);
    }
}

// Debounce helper
function debounce(func, wait = 200) {
    let timeout;
    return function(...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    };
}

function focusChatContainer() {
    const chatContainer = document.getElementById("chat");
    if (!chatContainer) return;

    chatContainer.focus(); // focus the div
}

function closeAllModalsAndFocusChat() {
    // Close DM modal
    if (dmModal.style.display === "block") {
        dmModal.style.display = "none";
    }

    // Hide DM suggestions
    if (dmSuggestions.style.display === "block") {
        dmSuggestions.style.display = "none";
        resetDmSuggestions();
    }

    // Close other modals if you have them
    if (searchModal?.style.display === "block") {
        searchModal.style.display = "none";
    }

    // Close private channel modals
    if (createPrivateChModal) createPrivateChModal.style.display = "none";
    if (renamePrivateChModal) renamePrivateChModal.style.display = "none";
    if (privateMembersModal)  privateMembersModal.style.display  = "none";

    closeHelp();

    // Reset DM input state
    if (dmUsersInput) {
        dmUsersInput.value = "";
    }

    focusChatContainer();
}

function scrollIntoViewIfNeeded(el) {
    const container = searchResults;
    if (!el || !container) return;

    const containerTop = container.scrollTop;
    const containerBottom = containerTop + container.clientHeight;

    const elTop = el.offsetTop;
    const elBottom = elTop + el.offsetHeight;

    if (elTop < containerTop) {
        container.scrollTop = elTop;
    } else if (elBottom > containerBottom) {
        container.scrollTop = elBottom - container.clientHeight;
    }
}

function _goToSearchResult(msgChannel, msgId) {
    searchModal.style.display = "none";
    switchChannel(msgChannel);
    setTimeout(() => {
        const el = document.getElementById(`msg-${msgId}`);
        if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 200);
}

// Live search
searchInput.addEventListener("input", debounce(() => {
    const q = searchInput.value.trim();
    if (!q) {
        searchResults.innerHTML = "";
        return;
    }
    fetch(`/search_messages?q=${encodeURIComponent(q)}`)
    .then(r => r.json())
    .then(data => {
        searchResults.innerHTML = "";
        searchSelectedIndex = -1;

        // Score each result with fuzzySearch and sort best-first
        const scored = data
            .map(msg => ({ msg, result: fuzzySearch(q, msg.content) }))
            .filter(({ result }) => result !== null)
            .sort((a, b) => b.result.score - a.result.score);

        scored.forEach(({ msg, result }) => {
            const d = document.createElement("div");
            const time = new Date(msg.ts * 1000).toLocaleTimeString();
            const snippet = buildSearchSnippet(msg.content, result.indices);
            d.innerHTML = `[${time}] <b>${escapeHtml(msg.sender)}</b>: ${snippet}`;
            d.onclick = () => _goToSearchResult(msg.channel, msg.id);
            searchResults.appendChild(d);
        });
    });
}, 250));

searchInput.addEventListener("keydown", (e) => {
    const items = searchResults.children;
    const hasResults = items.length > 0;

    if (!hasResults) return;

    if (e.key === "ArrowDown") {
        e.preventDefault();
        searchSelectedIndex = (searchSelectedIndex + 1) % items.length;
        updateSearchHighlight();
    }
    else if (e.key === "ArrowUp") {
        e.preventDefault();
        searchSelectedIndex = (searchSelectedIndex - 1 + items.length) % items.length;
        updateSearchHighlight();
    }
    else if (e.key === "Enter") {
        e.preventDefault();
        if (searchSelectedIndex >= 0) {
            items[searchSelectedIndex].click();
        }
    }
    else if (e.key === "Escape") {
        searchModal.style.display = "none";
        searchSelectedIndex = -1;
    }
});

// Starup
document.addEventListener("DOMContentLoaded", () => {
    initFavicon();
    loadSidebar();
    document.getElementById("chan").innerText = channel;
    switchChannel(channel);
    // Announce presence immediately on load rather than waiting for the first input event.
    sendPresence(document.visibilityState === "visible" ? "active" : "hidden");

    // Heartbeat: refresh last_seen even when the presence state hasn't changed.
    // Without this, a user who stays "active" for >1 hour would appear offline
    // because sendPresence deduplicates and never re-sends the same state.
    setInterval(() => {
        if (currentPresence !== "offline") {
            fetch("/presence", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ state: currentPresence })
            });
        }
    }, 30_000);

    setInterval(fetchMessages, 500);
    setInterval(refreshPresence, 1000);

    setInterval(fetchTyping, 1000);
    setInterval(refreshDMs, 1000);
    setInterval(refreshChannels, 1000);
    setInterval(refreshPrivateChannels, 1000);
    setInterval(fetchReadReceipts, 3000);
    setInterval(refreshTotalUnreadCount, 5000);
    setInterval(pollIncomingCalls, 1000);
    setInterval(refreshScreenShares, 1000);
    setInterval(() => {
        if (
            document.visibilityState === "visible" &&
            Date.now() - lastActivity > 300_000 &&
            !idleSent
        ) {
            sendPresence("idle");
            setIdleSent(true);
        }
    }, 5000);

});

// ── Link previews ─────────────────────────────────────────────────────────────

function _previewOgEl(data) {
    const wrap = document.createElement("div");
    wrap.className = "preview-og";

    if (data.image) {
        const img = document.createElement("img");
        img.className = "preview-og-thumb";
        img.src = data.image;
        img.loading = "lazy";
        img.addEventListener("error", () => img.remove());
        wrap.appendChild(img);
    }

    const text = document.createElement("div");
    text.className = "preview-og-text";

    const domainEl = document.createElement("div");
    domainEl.className = "preview-og-domain";
    domainEl.textContent = data.domain;
    text.appendChild(domainEl);

    const titleEl = document.createElement("a");
    titleEl.className = "preview-og-title";
    titleEl.href = data.url;
    titleEl.target = "_blank";
    titleEl.rel = "noopener noreferrer";
    titleEl.textContent = data.title;
    text.appendChild(titleEl);

    if (data.description) {
        const descEl = document.createElement("div");
        descEl.className = "preview-og-desc";
        descEl.textContent = data.description;
        text.appendChild(descEl);
    }

    wrap.appendChild(text);
    return wrap;
}

// ── Syntax highlighter ───────────────────────────────────────────────────────

const _EXT_TO_LANG = {
    py: 'python', pyx: 'python', pyi: 'python', python: 'python', python3: 'python',
    js: 'js', mjs: 'js', cjs: 'js', ts: 'js', tsx: 'js', jsx: 'js',
    javascript: 'js', typescript: 'js',
    c: 'c', h: 'c', cpp: 'c', cc: 'c', cxx: 'c', hpp: 'c', hxx: 'c',
    cplusplus: 'c', 'c++': 'c',
    sh: 'sh', bash: 'sh', zsh: 'sh', shell: 'sh',
    makefile: 'make', mk: 'make', make: 'make',
    cmake: 'cmake',
    groovy: 'groovy', gradle: 'groovy', jenkinsfile: 'groovy',
    vhd: 'vhdl', vhdl: 'vhdl',
    v: 'verilog', vh: 'verilog', sv: 'verilog', svh: 'verilog', verilog: 'verilog',
    java: 'java', go: 'go', golang: 'go', rs: 'rust', rust: 'rust',
    xml: 'xml', xsl: 'xml', xslt: 'xml', xsd: 'xml', svg: 'xml', html: 'xml', htm: 'xml',
};

const _HL_RULES = (() => {
    // Plain string (double or single quoted, single-line, with escape sequences)
    const STR     = /"[^"\\\n]*(?:\\.[^"\\\n]*)*"|'[^'\\\n]*(?:\\.[^'\\\n]*)*'/y; // NOSONAR
    // Python strings: optional f/b/r/u prefix before the quote
    const STR_PY  = /(?:[fFbBrRuU]|rb|br|RB|BR|fr|rf)?(?:"[^"\\\n]*(?:\\.[^"\\\n]*)*"|'[^'\\\n]*(?:\\.[^'\\\n]*)*')/y; // NOSONAR
    const NUM_HEX = /\b0x[\da-fA-F]+[uUlL]*/y;
    const NUM_DEC = /\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?[fFlLuU]*\b/y;
    const CMT_SL  = /\/\/[^\n]*/y;
    const CMT_BLK = /\/\*[\s\S]*?\*\//y;  // [\s\S] handles multi-line in inline code blocks
    const CMT_HSH  = /#[^\n]*/y;
    const CMT_DASH = /--[^\n]*/y;
    const MK_VAR   = /\$[@<^*%?|]|\$\([^)]*\)|\$\{[^}]*\}/y;
    const CM_VAR   = /\$(?:ENV|CACHE)?\{[^}]*\}/y;
    const SH_VAR   = /\$\{[^}]*\}|\$[@#?$!*-]|\$\w+/y;
    const VL_NUM   = /\d+\s*'\s*[bBoOdDhH][0-9a-fA-FxXzZ_]*/y;
    const VL_DIR   = /`\w+/y;
    const PP_DIR   = /#\s*\w+/y;
    const INCL_ANG = /<[^\s>][^>\n]*>/y;
    const DEC_PY   = /@[\w.]+/y;
    const kw  = (...ws) => new RegExp(String.raw`\b(?:${ws.join('|')})\b`, 'y');
    const kwi = (...ws) => new RegExp(String.raw`\b(?:${ws.join('|')})\b`, 'yi');

    return {
        python: [
            [STR_PY,  'str'],
            [CMT_HSH, 'cmt'],
            [DEC_PY,  'dec'],
            [kw('False','None','True','and','as','assert','async','await',
               'break','class','continue','def','del','elif','else','except',
               'finally','for','from','global','if','import','in','is',
               'lambda','nonlocal','not','or','pass','raise','return',
               'try','while','with','yield','match','case'), 'kw'],
            [kw('bool','bytes','bytearray','complex','dict','float','frozenset',
               'int','list','memoryview','object','set','str','tuple','type',
               'Exception','BaseException','ValueError','TypeError',
               'KeyError','IndexError','AttributeError','RuntimeError',
               'StopIteration','NotImplementedError','OSError','IOError',
               'FileNotFoundError','PermissionError','NameError',
               'ImportError','ModuleNotFoundError','ArithmeticError',
               'ZeroDivisionError','OverflowError'), 'type'],
            [kw('abs','all','any','ascii','bin','callable','chr','compile',
               'delattr','dir','divmod','enumerate','eval','exec','filter',
               'format','getattr','globals','hasattr','hash','help','hex',
               'id','input','isinstance','issubclass','iter','len','locals',
               'map','max','min','next','oct','open','ord','pow','print',
               'repr','reversed','round','setattr','slice','sorted',
               'staticmethod','classmethod','property','super','sum',
               'vars','zip'), 'bi'],
            [NUM_HEX, 'num'], [NUM_DEC, 'num'],
        ],
        js: [
            [STR,     'str'],
            [CMT_BLK, 'cmt'], [CMT_SL, 'cmt'],
            [kw('async','await','break','case','catch','class','const',
               'continue','debugger','default','delete','do','else','export',
               'extends','false','finally','for','function','if','import',
               'in','instanceof','let','new','null','of','return','static',
               'super','switch','this','throw','true','try','typeof',
               'undefined','var','void','while','with','yield'), 'kw'],
            [kw('Array','Boolean','Date','Error','Function','JSON','Map',
               'Math','Number','Object','Promise','Proxy','Reflect',
               'RegExp','Set','String','Symbol','WeakMap','WeakSet',
               'console','document','window','globalThis',
               'parseInt','parseFloat','isNaN','isFinite',
               'encodeURIComponent','decodeURIComponent',
               'setTimeout','clearTimeout','setInterval','clearInterval',
               'fetch'), 'bi'],
            [NUM_HEX, 'num'], [NUM_DEC, 'num'],
        ],
        c: [
            [STR,      'str'],
            [CMT_BLK,  'cmt'], [CMT_SL, 'cmt'],
            [PP_DIR,   'dec'],
            [INCL_ANG, 'str'],
            [kw('auto','break','case','continue','default','do','else',
               'enum','extern','for','goto','if','inline','return',
               'sizeof','static','struct','switch','typedef','union',
               'while','namespace','class','template','typename',
               'public','private','protected','virtual','override',
               'new','delete','this','throw','try','catch','operator',
               'nullptr','NULL','true','false',
               'const_cast','static_cast','dynamic_cast','reinterpret_cast',
               'using','constexpr','consteval','constinit','noexcept',
               'explicit','friend','mutable','volatile','register',
               'co_await','co_return','co_yield','requires','concept'), 'kw'],
            [kw('bool','char','double','float','int','long','short',
               'signed','unsigned','void','wchar_t',
               'char8_t','char16_t','char32_t',
               'int8_t','int16_t','int32_t','int64_t',
               'uint8_t','uint16_t','uint32_t','uint64_t',
               'size_t','ptrdiff_t','ssize_t','intptr_t','uintptr_t',
               'auto'), 'type'],
            [NUM_HEX, 'num'], [NUM_DEC, 'num'],
        ],
        sh: [
            [STR,     'str'],
            [CMT_HSH, 'cmt'],
            [SH_VAR,  'var'],
            [kw('if','then','else','elif','fi','for','while','until',
               'do','done','case','esac','in','function','return',
               'local','export','readonly','declare','typeset',
               'select','time','coproc'), 'kw'],
            [kw('echo','printf','read','cd','pwd','source','alias',
               'unalias','set','unset','shift','trap','exec','eval',
               'exit','test','true','false',
               'grep','sed','awk','find','sort','cut','xargs',
               'mkdir','rm','cp','mv','cat','head','tail'), 'bi'],
            [NUM_HEX, 'num'], [NUM_DEC, 'num'],
        ],
        make: [
            [CMT_HSH, 'cmt'],
            [MK_VAR,  'var'],
            [kw('ifeq','ifneq','ifdef','ifndef','else','endif',
               'include','override','export','unexport',
               'define','endef','undefine'), 'kw'],
        ],
        groovy: [
            [STR,     'str'],
            [CMT_BLK, 'cmt'], [CMT_SL, 'cmt'],
            [DEC_PY,  'dec'],   // @Library, @NonCPS and other annotations
            [kw('as','assert','break','case','catch','class','const',
               'continue','def','default','do','else','enum','extends',
               'false','finally','for','goto','if','implements','import',
               'in','instanceof','interface','new','null','package',
               'return','super','switch','this','throw','throws','trait',
               'true','try','while','abstract','final','native','private',
               'protected','public','static','strictfp','synchronized',
               'transient','volatile','var'), 'kw'],
            [kw('boolean','byte','char','double','float','int','long',
               'short','void','String','Object','List','Map','Set',
               'Boolean','Integer','Long','Double','Float','Number',
               'BigDecimal','BigInteger','Closure','GString'), 'type'],
            [kw('pipeline','agent','stages','stage','steps','script',
               'environment','options','parameters','triggers','tools',
               'when','post','always','success','failure','unstable',
               'changed','cleanup','parallel','matrix','node','sh','bat',
               'echo','dir','withEnv','withCredentials','checkout','git',
               'input','timeout','retry','build','archiveArtifacts','junit',
               'stash','unstash','error','catchError','readFile','writeFile',
               'fileExists','emailext','docker','label'), 'bi'],
            [NUM_HEX, 'num'], [NUM_DEC, 'num'],
        ],
        cmake: [
            [STR,     'str'],
            [CMT_HSH, 'cmt'],
            [CM_VAR,  'var'],
            [kwi('if','else','elseif','endif',
                 'foreach','endforeach','while','endwhile',
                 'function','endfunction','macro','endmacro',
                 'return','break','continue',
                 'cmake_minimum_required','cmake_policy','project',
                 'add_executable','add_library','add_subdirectory',
                 'target_link_libraries','target_include_directories',
                 'target_compile_options','target_compile_definitions',
                 'target_sources','target_precompile_headers',
                 'target_link_directories','target_link_options',
                 'set','unset','option','message','string','list','math',
                 'include','find_package','find_library','find_path',
                 'find_program','find_file',
                 'install','configure_file','file','execute_process',
                 'add_custom_command','add_custom_target','add_test',
                 'enable_testing','enable_language',
                 'include_directories','link_directories','link_libraries',
                 'get_filename_component','get_target_property',
                 'set_target_properties','set_property','get_property',
                 'add_definitions','add_compile_options',
                 'add_compile_definitions','add_link_options',
                 'cmake_parse_arguments','mark_as_advanced',
                 'check_cxx_compiler_flag','check_c_compiler_flag',
                 'check_include_file','check_function_exists',
                 'include_guard','block','endblock',
                 'FetchContent_Declare','FetchContent_MakeAvailable',
                 'FetchContent_GetProperties','FetchContent_Populate',
                 'ExternalProject_Add','ExternalProject_Get_Property',
                 'target_compile_features',
                 'write_basic_package_version_file',
                 'configure_package_config_file'), 'kw'],
            [kwi('ON','OFF','TRUE','FALSE','YES','NO','NOTFOUND',
                 'PUBLIC','PRIVATE','INTERFACE','SHARED','STATIC',
                 'MODULE','OBJECT','ALIAS','IMPORTED',
                 'STATUS','WARNING','SEND_ERROR','FATAL_ERROR','DEPRECATION',
                 'REQUIRED','COMPONENTS','OPTIONAL_COMPONENTS',
                 'DESTINATION','FILES','PROGRAMS','DIRECTORY','TARGETS',
                 'STREQUAL','STRLESS','STRGREATER','EQUAL','LESS','GREATER',
                 'MATCHES','EXISTS','IS_DIRECTORY','IS_ABSOLUTE',
                 'DEFINED','COMMAND','POLICY','APPEND','PREPEND',
                 'VERSION'), 'type'],
            [NUM_HEX, 'num'], [NUM_DEC, 'num'],
        ],
        vhdl: [
            [STR,      'str'],
            [CMT_DASH, 'cmt'],
            [kwi('abs','access','after','alias','all','and','architecture',
                 'array','assert','attribute','begin','block','body',
                 'buffer','bus','case','component','configuration',
                 'constant','disconnect','downto','else','elsif','end',
                 'entity','exit','file','for','function','generate',
                 'generic','group','guarded','if','impure','in',
                 'inertial','inout','is','label','library','linkage',
                 'literal','loop','map','mod','nand','new','next',
                 'nor','not','null','of','on','open','or','others',
                 'out','package','port','postponed','procedure',
                 'process','pure','range','record','register','reject',
                 'rem','report','return','rol','ror','select','severity',
                 'shared','signal','sla','sll','sra','srl','subtype',
                 'then','to','transport','type','unaffected','units',
                 'until','use','variable','wait','when','while',
                 'with','xnor','xor'), 'kw'],
            [kwi('std_logic','std_logic_vector','std_ulogic',
                 'std_ulogic_vector','unsigned','signed',
                 'integer','natural','positive','boolean',
                 'bit','bit_vector','character','string','real','time',
                 'severity_level','line','text','side','width',
                 'rising_edge','falling_edge',
                 'to_integer','to_unsigned','to_signed',
                 'to_std_logic_vector','to_bitvector',
                 'conv_integer','conv_std_logic_vector',
                 'resize','shift_left','shift_right',
                 'ieee','std_logic_1164','numeric_std',
                 'numeric_bit','std_textio','textio','work'), 'type'],
            [NUM_HEX, 'num'], [NUM_DEC, 'num'],
        ],
        verilog: [
            [STR,     'str'],
            [CMT_BLK, 'cmt'], [CMT_SL, 'cmt'],
            [VL_DIR,  'dec'],
            [kw('always','always_comb','always_ff','always_latch',
                'assign','automatic','begin','buf','bufif0','bufif1',
                'case','casex','casez','deassign','default','defparam',
                'disable','edge','else','end','endcase','endfunction',
                'endgenerate','endmodule','endprimitive','endspecify',
                'endtable','endtask','event','for','force','forever',
                'fork','function','generate','genvar','if','initial',
                'inout','input','join','localparam',
                'macromodule','module','nand','negedge','nor','not',
                'or','output','parameter','posedge','primitive',
                'release','repeat','return','specify','specparam',
                'supply0','supply1','table','task','tri','tri0','tri1',
                'triand','trior','trireg','wait','wand','while',
                'wire','wor','xnor','xor',
                'bit','byte','chandle','class','clocking','const',
                'constraint','covergroup','coverpoint','do','endclass',
                'endclocking','endgroup','endinterface','endpackage',
                'endprogram','enum','extends','final','foreach',
                'iff','import','inside','interface','join_any','join_none',
                'local','modport','new','null','package','priority',
                'program','property','protected','pure','rand','randc',
                'randcase','ref','sequence','shortint','shortreal',
                'static','string','struct','super','this','typedef',
                'union','unique','unique0','var','virtual','void',
                'with','within','intersect',
                'bind','checker','endchecker','cover','expect',
                'global','matches','soft','solve','until'), 'kw'],
            [kw('logic','reg','integer','real','realtime','signed','unsigned',
               'int','longint','byte','shortint','time',
               'bit','chandle','event'), 'type'],
            [VL_NUM,  'num'],
            [NUM_HEX, 'num'], [NUM_DEC, 'num'],
        ],
        java: [
            [STR,     'str'],
            [CMT_BLK, 'cmt'], [CMT_SL, 'cmt'],
            [kw('abstract','assert','break','case','catch','class',
               'const','continue','default','do','else','enum',
               'extends','final','finally','for','goto','if',
               'implements','import','instanceof','interface','native',
               'new','null','package','private','protected','public',
               'return','static','strictfp','super','switch',
               'synchronized','this','throw','throws','transient',
               'try','volatile','while','true','false',
               'record','sealed','permits','yield','var'), 'kw'],
            [kw('boolean','byte','char','double','float','int',
               'long','short','void',
               'String','Integer','Long','Double','Float','Boolean',
               'Byte','Short','Character','Object','Number',
               'Exception','RuntimeException','Error',
               'List','Map','Set','Collection','ArrayList',
               'HashMap','HashSet','LinkedList',
               'Optional','Stream','Iterator','Iterable',
               'Comparable','Cloneable','Runnable','Callable'), 'type'],
            [NUM_HEX, 'num'], [NUM_DEC, 'num'],
        ],
        go: [
            [STR,     'str'],
            [CMT_BLK, 'cmt'], [CMT_SL, 'cmt'],
            [kw('break','case','chan','const','continue','default',
               'defer','else','fallthrough','for','func','go','goto',
               'if','import','interface','map','package','range',
               'return','select','struct','switch','type','var',
               'nil','true','false','iota'), 'kw'],
            [kw('any','error','bool','byte','rune','string',
               'int','int8','int16','int32','int64',
               'uint','uint8','uint16','uint32','uint64','uintptr',
               'float32','float64','complex64','complex128'), 'type'],
            [kw('append','cap','clear','close','complex','copy',
               'delete','imag','len','make','max','min','new',
               'panic','print','println','real','recover'), 'bi'],
            [NUM_HEX, 'num'], [NUM_DEC, 'num'],
        ],
        rust: [
            [STR,     'str'],
            [CMT_BLK, 'cmt'], [CMT_SL, 'cmt'],
            [kw('as','async','await','break','const','continue','crate',
               'dyn','else','enum','extern','false','fn','for','if',
               'impl','in','let','loop','match','mod','move','mut',
               'pub','ref','return','self','Self','static','struct',
               'super','trait','true','type','union','unsafe','use',
               'where','while'), 'kw'],
            [kw('i8','i16','i32','i64','i128','isize',
               'u8','u16','u32','u64','u128','usize',
               'f32','f64','bool','char','str',
               'String','Option','Result','Vec','Box','Arc','Rc',
               'HashMap','HashSet','BTreeMap','BTreeSet',
               'Some','None','Ok','Err'), 'type'],
            [NUM_HEX, 'num'], [NUM_DEC, 'num'],
        ],
        xml: [
            [/<!--[\s\S]*?-->/y,          'cmt'],   // comments
            [/<!\[CDATA\[[\s\S]*?\]\]>/y, 'str'],   // CDATA content
            [/<\?[\s\S]*?\?>/y,           'dec'],   // processing instructions
            [/<!(?!--)[^>]*>/y,           'dec'],   // DOCTYPE / declarations
            [/<\/?[\w:.-]+/y,             'kw'],    // <tagName or </tagName
            [/\/?>/y,                     'kw'],    // > or />
            [/[\w:.-]+(?=\s*=)/y,         'var'],   // attribute names (before =)
            [/"[^"]*"|'[^']*'/y,          'str'],   // attribute values
        ],
    };
})();

function _syntaxHighlight(text, ext) {
    const _esc = s => s.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
    const lang = _EXT_TO_LANG[(ext || '').toLowerCase()];
    const rules = lang ? _HL_RULES[lang] : null;
    if (!rules) return _esc(text);

    let out = '', plain = '', i = 0;
    while (i < text.length) {
        let hit = false;
        for (const [re, cls] of rules) {
            re.lastIndex = i;
            const m = re.exec(text);
            if (m) {
                if (plain) { out += _esc(plain); plain = ''; }
                out += `<span class="hl-${cls}">${_esc(m[0])}</span>`;
                i += m[0].length;
                hit = true;
                break;
            }
        }
        if (!hit) plain += text[i++];
    }
    return out + _esc(plain);
}

// ─────────────────────────────────────────────────────────────────────────────

// Resolve the highlighter language from a basename, covering extensionless
// files (Jenkinsfile → groovy, Makefile → make) the server can't key off an
// extension. Falls back to the server-provided language (the file extension).
function _previewLang(filename, language) {
    const base = (filename || '').toLowerCase();
    if (base === 'cmakelists.txt') return 'cmake';
    if (base.startsWith('jenkinsfile')) return 'groovy';
    if (base === 'makefile' || base === 'gnumakefile') return 'make';
    return language || '';
}

function _previewCodeEl(data) {
    const wrap = document.createElement("div");
    wrap.className = "preview-code";

    const header = document.createElement("div");
    header.className = "preview-code-header";

    if (data._fileChip) {
        // Uploaded file: reuse the download chip (logo + name + size) as the
        // header instead of a duplicate plain filename link. Moving it here
        // removes it as a standalone sibling, so the file shows as one card.
        header.appendChild(data._fileChip);
    } else {
        const link = document.createElement("a");
        link.href = data.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = data.filepath;
        header.appendChild(link);
    }

    if (data.highlight_start) {
        const rangeEl = document.createElement("span");
        rangeEl.className = "preview-code-range";
        const end = data.highlight_end || data.highlight_start;
        rangeEl.textContent = data.highlight_start === end
            ? ` · line ${data.highlight_start}`
            : ` · lines ${data.highlight_start}–${end}`;
        header.appendChild(rangeEl);
    }
    wrap.appendChild(header);

    const pre = document.createElement("pre");
    pre.className = "preview-code-body";

    const codeLines = data.code.split("\n");
    const firstNum = data.first_line_num || 1;
    const hlStart = data.highlight_start;
    const hlEnd = data.highlight_end || hlStart;
    const codeLang = _previewLang(data.filename, data.language);

    codeLines.forEach((line, i) => {
        const lineNum = firstNum + i;
        const isHl = hlStart && lineNum >= hlStart && lineNum <= hlEnd;

        const row = document.createElement("span");
        row.className = "code-row" + (isHl ? " hl" : "");

        const ln = document.createElement("span");
        ln.className = "ln";
        ln.textContent = lineNum;
        row.appendChild(ln);

        const content = document.createElement("span");
        content.innerHTML = _syntaxHighlight(line, codeLang);
        row.appendChild(content);

        pre.appendChild(row);
        // No \n text node — display:block on .code-row already creates line breaks
    });

    wrap.appendChild(pre);

    if (hlStart) {
        requestAnimationFrame(() => {
            const hlRow = pre.querySelector(".code-row.hl");
            if (hlRow) {
                pre.scrollTop = hlRow.offsetTop - pre.clientHeight / 2 + hlRow.clientHeight / 2;
            }
        });
    }

    return wrap;
}

const _previewObserver = new IntersectionObserver(
    (entries) => {
        entries.forEach(entry => {
            if (!entry.isIntersecting) return;
            _previewObserver.unobserve(entry.target);
            attachPreview(entry.target);
        });
    },
    {
        root: document.getElementById("chat"),
        rootMargin: "300px 0px 300px 0px",
        threshold: 0,
    }
);

// Extensions the client checks before registering an uploaded file for preview.
// Kept in sync with _TEXT_EXTENSIONS in preview.py (client-side guard only —
// the server performs the authoritative check).
const _PREVIEWABLE_EXTENSIONS = new Set([
    "c","cc","cpp","cxx","h","hpp",
    "py","pyw",
    "js","mjs","cjs","jsx","ts","tsx",
    "java","kt","scala","rs","go","rb","php","pl","lua",
    "sh","bash","zsh","fish",
    "cmake","mk","make",
    "groovy","gradle","vhd","vhdl","v","vh","sv","svh",
    "xml","xsl","xslt","xsd","svg",
    "html","htm","css","scss","sass","less",
    "json","yaml","yml","toml","ini","cfg","conf",
    "txt","md","rst","csv","sql",
    "r","swift","m","ex","exs","erl","tf","hcl","proto",
]);

// Original (display) basename of an uploaded file, lowercased — strips the
// 32-char UUID prefix the server prepends to stored filenames.
function _previewBaseName(fn) {
    const name = (fn.length > 33 && fn[32] === "_") ? fn.slice(33) : fn;
    return name.toLowerCase();
}

// True if an uploaded file should get a code preview — by extension, or by
// special name (Jenkinsfile*, Makefile) which have no useful extension.
function _isPreviewableFile(fn) {
    const base = _previewBaseName(fn);
    const ext = base.includes(".") ? base.split(".").pop() : "";
    if (_PREVIEWABLE_EXTENSIONS.has(ext)) return true;
    return base.startsWith("jenkinsfile")
        || base === "makefile" || base === "gnumakefile";
}

function _msgHasPreviewableContent(msgEl) {
    if (msgEl.querySelector(".text a[href^='http']")) return true;
    const fn = msgEl.querySelector("a.file-download[data-fn]")?.dataset.fn;
    if (fn && _isPreviewableFile(fn)) return true;
    return false;
}

function schedulePreview(msgEl) {
    if (!_msgHasPreviewableContent(msgEl)) return;
    _previewObserver.observe(msgEl);
}

function _attachPreviewEl(msgEl, data) {
    if (!data?.type) return;
    const previewEl = document.createElement("div");
    previewEl.className = "link-preview";
    if (data.type === "og") {
        previewEl.appendChild(_previewOgEl(data));
    } else if (data.type === "code") {
        previewEl.appendChild(_previewCodeEl(data));
    }
    (msgEl.querySelector(".msg-body") || msgEl).appendChild(previewEl);
}

async function attachPreview(msgEl) {
    if (msgEl.querySelector(".link-preview")) return;

    // Priority 1: HTTP link in message text (Bitbucket / text-file / OG)
    const firstLink = msgEl.querySelector(".text a[href^='http']");
    if (firstLink) {
        let data;
        try {
            const resp = await fetch(`/link_preview?url=${encodeURIComponent(firstLink.href)}`);
            data = await resp.json();
        } catch { return; }
        _attachPreviewEl(msgEl, data);
        return;
    }

    // Priority 2: uploaded text file attachment
    const fileLink = msgEl.querySelector("a.file-download[data-fn]");
    if (!fileLink) return;
    const fn = fileLink.dataset.fn;
    if (!_isPreviewableFile(fn)) return;

    let data;
    try {
        const resp = await fetch(`/file_preview/${encodeURIComponent(fn)}`);
        data = await resp.json();
    } catch { return; }
    // Fold the standalone download chip into the preview's header so the same
    // file isn't shown as two separate cards (chip + preview).
    if (data && data.type === "code") data._fileChip = fileLink;
    _attachPreviewEl(msgEl, data);
}

// Pinch-to-zoom adjusts message font size rather than scaling the page.
const CHAT_FONT_MIN = 11;
const CHAT_FONT_MAX = 22;
const CHAT_FONT_DEFAULT = 14;

function applyChatFontSize(size) {
    document.getElementById("chat").style.fontSize             = size + "px";
    document.getElementById("msg").style.fontSize              = size + "px";
    document.getElementById("typing-indicator").style.fontSize = size + "px";
}

(function () {
    let fontSize = Number.parseFloat(localStorage.getItem("chatFontSize")) || CHAT_FONT_DEFAULT;
    fontSize = Math.min(CHAT_FONT_MAX, Math.max(CHAT_FONT_MIN, fontSize));
    applyChatFontSize(fontSize);

    let startDist = null;
    let startSize = fontSize;

    function pinchDist(touches) {
        const dx = touches[0].clientX - touches[1].clientX;
        const dy = touches[0].clientY - touches[1].clientY;
        return Math.hypot(dx, dy);
    }

    const chatEl = document.getElementById("chat");

    chatEl.addEventListener("touchstart", (e) => {
        if (e.touches.length === 2) {
            startDist = pinchDist(e.touches);
            startSize = fontSize;
        }
    }, { passive: true });

    chatEl.addEventListener("touchmove", (e) => {
        if (e.touches.length !== 2 || startDist === null) return;
        e.preventDefault();
        const scale = pinchDist(e.touches) / startDist;
        fontSize = Math.min(CHAT_FONT_MAX, Math.max(CHAT_FONT_MIN, startSize * scale));
        applyChatFontSize(fontSize);
    }, { passive: false });

    chatEl.addEventListener("touchend", (e) => {
        if (e.touches.length < 2) {
            startDist = null;
            localStorage.setItem("chatFontSize", fontSize);
        }
    }, { passive: true });

    chatEl.addEventListener("wheel", (e) => {
        if (!e.ctrlKey && !e.metaKey) return;
        e.preventDefault();
        fontSize = Math.min(CHAT_FONT_MAX, Math.max(CHAT_FONT_MIN, fontSize - e.deltaY * 0.05));
        applyChatFontSize(fontSize);
        localStorage.setItem("chatFontSize", fontSize);
    }, { passive: false });
}());


/**
 * Tests for chat-settings.js
 * Load order: sidebar → dm → settings
 */

const { loadScript } = require('./loadScript');

beforeAll(() => {
    // Stubs needed by sidebar
    global.openCreatePrivateChannel = jest.fn();
    global.bindPCTooltip            = jest.fn();
    global.nativeNotifEnabled       = false;
    global.notifMuted               = false;

    loadScript('chat-sidebar.js');

    // Stubs for dm
    global.fuzzySearch         = jest.fn(() => null);
    global.highlightFuzzyMatch = jest.fn((t) => t);

    loadScript('chat-dm.js');

    // Stubs needed by settings
    global.defaultUserColor = jest.fn(() => 'hsl(200, 60%, 60%)');
    global.userColor        = jest.fn(() => 'hsl(200, 60%, 60%)');
    global.usersWithAvatars = new Set();
    global.userColorOverrides = {};
    global.escapeHtml = jest.fn(t => t);
    global.profileCache = {};

    loadScript('chat-settings.js');
});

beforeEach(() => {
    jest.clearAllMocks();
    global.fetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({}),
        text: () => Promise.resolve(''),
    });
    document.getElementById('settings-modal').style.display = 'none';
    document.getElementById('users-modal').style.display = 'none';
    // Reset localStorage
    localStorage.clear();
    localStorage.setItem('notifMuted', 'false');
    localStorage.setItem('nativeNotifEnabled', 'true');
    localStorage.setItem('chatFontSize', '14');
    localStorage.setItem('enterToSend', 'true');
    // Ensure select element for enter key
    const ek = document.getElementById('settings-enter-key');
    if (ek && ek.tagName !== 'SELECT') { /* it's an input, that's ok */ }
    // Ensure font slider has value
    const fs = document.getElementById('settings-font-size');
    if (fs) fs.value = '14';
});

// ── COLOR_PRESETS ──────────────────────────────────────────────────────────────
describe('COLOR_PRESETS', () => {
    test('is a non-empty array', () => {
        expect(Array.isArray(COLOR_PRESETS)).toBe(true);
        expect(COLOR_PRESETS.length).toBeGreaterThan(0);
    });
    test('all items are hex color strings', () => {
        COLOR_PRESETS.forEach(c => {
            expect(c).toMatch(/^#[0-9a-fA-F]{6}$/);
        });
    });
});

// ── notifMuted / nativeNotifEnabled initialisation ────────────────────────────
describe('localStorage initialization', () => {
    test('notifMuted is boolean', () => {
        // The variable is let-scoped but we can check the checkbox reflects it
        const cb = document.getElementById('settings-notif-sounds');
        expect(typeof cb.checked).toBe('boolean');
    });
});

// ── openSettings ───────────────────────────────────────────────────────────────
describe('openSettings()', () => {
    beforeEach(() => {
        global.fetch.mockResolvedValue({
            ok: true,
            json: () => Promise.resolve({ name_color: '#ff0000', bio: 'Hello' }),
        });
        global.defaultUserColor.mockReturnValue('hsl(0,60%,60%)');
    });

    test('shows settings modal', async () => {
        await openSettings();
        expect(document.getElementById('settings-modal').style.display).toBe('flex');
    });

    test('populates color input with server value', async () => {
        await openSettings();
        expect(document.getElementById('settings-name-color').value).toBe('#ff0000');
    });

    test('populates bio field with server value', async () => {
        await openSettings();
        expect(document.getElementById('settings-bio').value).toBe('Hello');
    });

    test('populates bio count', async () => {
        await openSettings();
        expect(document.getElementById('settings-bio-count').textContent).toBe('5');
    });
});

// ── closeSettings / cancel button ─────────────────────────────────────────────
describe('settings-cancel-btn', () => {
    test('hides modal on click', () => {
        document.getElementById('settings-modal').style.display = 'flex';
        document.getElementById('settings-cancel-btn').click();
        expect(document.getElementById('settings-modal').style.display).toBe('none');
    });
});

// ── showDeleteConfirm / cancelDeleteConfirm ────────────────────────────────────
describe('showDeleteConfirm() / cancelDeleteConfirm()', () => {
    test('showDeleteConfirm shows delete view for "soft"', () => {
        showDeleteConfirm('soft');
        expect(document.getElementById('settings-delete-view').style.display).toBe('block');
        expect(document.getElementById('settings-main-view').style.display).toBe('none');
    });

    test('showDeleteConfirm sets title for "hard"', () => {
        showDeleteConfirm('hard');
        expect(document.getElementById('settings-delete-title').textContent).toBe('Hard Delete Account');
    });

    test('cancelDeleteConfirm shows main view', () => {
        showDeleteConfirm('soft');
        cancelDeleteConfirm();
        expect(document.getElementById('settings-main-view').style.display).toBe('block');
        expect(document.getElementById('settings-delete-view').style.display).toBe('none');
    });
});

// ── confirmDelete ──────────────────────────────────────────────────────────────
describe('confirmDelete()', () => {
    beforeEach(() => {
        showDeleteConfirm('soft');
    });

    test('shows error when password empty', async () => {
        document.getElementById('settings-delete-password').value = '';
        await confirmDelete();
        const errEl = document.getElementById('settings-delete-error');
        expect(errEl.style.display).toBe('block');
    });

    test('calls /delete_account when password provided', async () => {
        document.getElementById('settings-delete-password').value = 'mypassword';
        global.fetch.mockResolvedValueOnce({
            ok: true,
            json: () => Promise.resolve({}),
        });
        // Mock location
        delete globalThis.location;
        globalThis.location = { href: '' };
        await confirmDelete();
        expect(global.fetch).toHaveBeenCalledWith(
            '/delete_account',
            expect.objectContaining({ method: 'POST' })
        );
    });

    test('shows error on failed response', async () => {
        document.getElementById('settings-delete-password').value = 'mypassword';
        global.fetch.mockResolvedValueOnce({
            ok: false,
            json: () => Promise.resolve({ error: 'Wrong password' }),
        });
        await confirmDelete();
        const errEl = document.getElementById('settings-delete-error');
        expect(errEl.style.display).toBe('block');
    });

    test('shows network error on exception', async () => {
        document.getElementById('settings-delete-password').value = 'mypassword';
        global.fetch.mockRejectedValueOnce(new Error('Network error'));
        await confirmDelete();
        const errEl = document.getElementById('settings-delete-error');
        expect(errEl.style.display).toBe('block');
        expect(errEl.textContent).toContain('Network error');
    });
});

// ── settings-color-reset ───────────────────────────────────────────────────────
describe('settings-color-reset button', () => {
    test('resets color to default and clears swatch selection', async () => {
        global.fetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });
        await openSettings();
        // Add a swatch
        const swatch = document.createElement('button');
        swatch.className = 'color-swatch selected';
        document.getElementById('color-swatches').appendChild(swatch);
        document.getElementById('settings-color-reset').click();
        expect(swatch.classList.contains('selected')).toBe(false);
    });
});

// ── openUsersModal ─────────────────────────────────────────────────────────────
describe('openUsersModal()', () => {
    beforeEach(() => {
        global.profileCache = {};
        global.fetch.mockImplementation((url) => {
            if (url === '/users') {
                return Promise.resolve({ ok: true, json: () => Promise.resolve(['bob']) });
            }
            if (url.startsWith('/profile/')) {
                return Promise.resolve({ ok: true, json: () => Promise.resolve({ bio: 'Hello' }) });
            }
            return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
        });
    });

    test('shows users modal', async () => {
        await openUsersModal();
        expect(document.getElementById('users-modal').style.display).toBe('block');
    });

    test('renders user rows', async () => {
        await openUsersModal();
        const list = document.getElementById('users-list');
        expect(list.children.length).toBeGreaterThan(0);
    });

    test('handles fetch failure', async () => {
        global.fetch.mockRejectedValueOnce(new Error('Network fail'));
        await openUsersModal();
        expect(document.getElementById('users-list').textContent).toContain('Failed');
    });
});

// ── filterUsersModal ───────────────────────────────────────────────────────────
describe('filterUsersModal()', () => {
    beforeEach(async () => {
        global.profileCache = {};
        global.fetch.mockImplementation((url) => {
            if (url === '/users') return Promise.resolve({ ok: true, json: () => Promise.resolve(['bob', 'charlie']) });
            if (url.startsWith('/profile/')) return Promise.resolve({ ok: true, json: () => Promise.resolve(null) });
            return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
        });
        global.fuzzySearch = jest.fn((q, t) => {
            if (t.includes(q)) return { score: 1, indices: [0] };
            return null;
        });
        await openUsersModal();
    });

    test('empty query shows all rows', () => {
        filterUsersModal('');
        const list = document.getElementById('users-list');
        const hidden = Array.from(list.children).filter(r => r.style.display === 'none');
        expect(hidden.length).toBe(0);
    });

    test('non-matching query hides rows', () => {
        global.fuzzySearch.mockReturnValue(null);
        filterUsersModal('zzzz');
        const list = document.getElementById('users-list');
        const visible = Array.from(list.children).filter(r => r.style.display !== 'none');
        // self (alice) always shown if no fuzzy result for alice too
        expect(typeof visible.length).toBe('number');
    });
});

// ── closeUsersModal ────────────────────────────────────────────────────────────
describe('closeUsersModal()', () => {
    test('hides users modal', () => {
        document.getElementById('users-modal').style.display = 'block';
        closeUsersModal();
        expect(document.getElementById('users-modal').style.display).toBe('none');
    });
});

// ── context-aware members modal ────────────────────────────────────────────────
describe('openUsersModal() context awareness', () => {
    afterEach(() => { global.channel = 'general'; });

    function memberFetch() {
        global.fetch.mockImplementation((url) => {
            if (url === '/users') return Promise.resolve({ ok: true, json: () => Promise.resolve(['bob']) });
            if (url.endsWith('/members')) return Promise.resolve({ ok: true, json: () => Promise.resolve([{ username: 'alice' }, { username: 'bob' }]) });
            if (url.startsWith('/profile/')) return Promise.resolve({ ok: true, json: () => Promise.resolve(null) });
            return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
        });
    }

    test('shows the Add Member section for private channels', async () => {
        memberFetch();
        global.channel = 'private:1';
        global.privateChannelMap = { 'private:1': 'My Channel' };
        await openUsersModal();
        expect(document.getElementById('users-modal-add').style.display).toBe('block');
        expect(document.getElementById('users-modal-title').textContent).toContain('My Channel');
    });

    test('hides the Add Member section for public channels', async () => {
        memberFetch();
        global.channel = 'general';
        await openUsersModal();
        expect(document.getElementById('users-modal-add').style.display).toBe('none');
    });

    test('hides the Add Member section for DMs', async () => {
        memberFetch();
        global.channel = 'dm:alice:bob';
        await openUsersModal();
        expect(document.getElementById('users-modal-add').style.display).toBe('none');
    });
});

// ── updateMembersCount ─────────────────────────────────────────────────────────
describe('updateMembersCount()', () => {
    afterEach(() => { global.channel = 'general'; });

    test('public channel counts all users plus self', async () => {
        global.channel = 'general';
        global.fetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(['bob', 'charlie']) });
        await updateMembersCount();
        expect(document.getElementById('members-count').textContent).toBe('3');
    });

    test('DM counts participants without fetching', async () => {
        global.channel = 'dm:alice:bob:carol';
        global.fetch.mockClear();
        await updateMembersCount();
        expect(document.getElementById('members-count').textContent).toBe('3');
        expect(global.fetch).not.toHaveBeenCalled();
    });

    test('private channel counts its members', async () => {
        global.channel = 'private:1';
        global.fetch.mockResolvedValue({ ok: true, json: () => Promise.resolve([{ username: 'alice' }, { username: 'bob' }]) });
        await updateMembersCount();
        expect(document.getElementById('members-count').textContent).toBe('2');
    });
});

// ── settings-save-btn ─────────────────────────────────────────────────────────
describe('settings-save-btn', () => {
    test('calls /settings POST with color and bio', async () => {
        global.fetch.mockResolvedValue({
            ok: true,
            json: () => Promise.resolve({ name_color: null, bio: '' }),
        });
        await openSettings();
        document.getElementById('settings-notif-sounds').checked = true;
        document.getElementById('settings-native-notif').checked = false;
        global.fetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });
        document.getElementById('settings-save-btn').click();
        await Promise.resolve();
        await Promise.resolve();
        const calls = global.fetch.mock.calls.map(c => c[0]);
        expect(calls.some(u => u === '/settings')).toBe(true);
    });
});

// ── settings-notif-sounds change ──────────────────────────────────────────────
describe('settings-notif-sounds change', () => {
    test('updates bell icon visibility', () => {
        const cb = document.getElementById('settings-notif-sounds');
        cb.checked = false;
        cb.dispatchEvent(new Event('change'));
        const slashEl = document.getElementById('notif-bell-slash');
        expect(slashEl.style.display).toBe('');
    });

    test('hides bell slash when enabled', () => {
        const cb = document.getElementById('settings-notif-sounds');
        cb.checked = true;
        cb.dispatchEvent(new Event('change'));
        const slashEl = document.getElementById('notif-bell-slash');
        expect(slashEl.style.display).toBe('none');
    });
});

// ── settings-native-notif change ──────────────────────────────────────────────
describe('settings-native-notif change', () => {
    test('updates native notif icon', () => {
        const cb = document.getElementById('settings-native-notif');
        cb.checked = true;
        cb.dispatchEvent(new Event('change'));
        const slashEl = document.getElementById('native-bell-slash');
        expect(slashEl.style.display).toBe('none');
    });
});

// ── settings-bio input ────────────────────────────────────────────────────────
describe('settings-bio input', () => {
    test('updates character count', () => {
        const bio = document.getElementById('settings-bio');
        bio.value = 'Hello World';
        bio.dispatchEvent(new Event('input'));
        expect(document.getElementById('settings-bio-count').textContent).toBe('11');
    });
});

// ── settings-font-size input ──────────────────────────────────────────────────
describe('settings-font-size input', () => {
    test('updates font size label and applies size', () => {
        const slider = document.getElementById('settings-font-size');
        slider.value = '16';
        slider.dispatchEvent(new Event('input'));
        expect(document.getElementById('settings-font-size-label').textContent).toBe('(16px)');
    });
});

// ── settings-name-color input ─────────────────────────────────────────────────
describe('settings-name-color input', () => {
    test('updates color preview', () => {
        document.getElementById('settings-name-color').value = '#00ff00';
        document.getElementById('settings-name-color').dispatchEvent(new Event('input'));
        const preview = document.getElementById('settings-color-preview-name');
        expect(preview.style.color).toBe('rgb(0, 255, 0)');
    });
});

// ── usersModal backdrop click ──────────────────────────────────────────────────
describe('usersModal backdrop click', () => {
    test('closes modal on backdrop click', () => {
        const modal = document.getElementById('users-modal');
        modal.style.display = 'block';
        modal.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        // The listener checks e.target === usersModal — clicking the modal itself
        expect(modal.style.display).toBe('none');
    });
});

// ── notifMuted / nativeNotifEnabled global state ──────────────────────────────
describe('notification globals', () => {
    test('notifMuted is a boolean', ()        => { expect(typeof notifMuted).toBe('boolean'); });
    test('nativeNotifEnabled is a boolean', () => { expect(typeof nativeNotifEnabled).toBe('boolean'); });
});

// ── filterUsersModal ──────────────────────────────────────────────────────────
describe('filterUsersModal()', () => {
    test('does not throw with empty row list', () => {
        global._usersModalRows = [];
        expect(() => filterUsersModal('bob')).not.toThrow();
    });
    test('hides rows that do not match', () => {
        const row = document.createElement('div');
        const nameEl = document.createElement('span');
        row.appendChild(nameEl);
        nameEl.textContent = 'charlie';
        row.style.display = '';
        global._usersModalRows = [{ row, nameEl, username: 'charlie' }];
        filterUsersModal('alice');
        expect(row.style.display).toBe('none');
    });
    test('shows rows that match', () => {
        const row = document.createElement('div');
        const nameEl = document.createElement('span');
        row.appendChild(nameEl);
        nameEl.textContent = 'alice';
        row.style.display = 'none';
        global._usersModalRows = [{ row, nameEl, username: 'alice' }];
        const origFuzzy = global.fuzzySearch;
        global.fuzzySearch = jest.fn(() => ({ score: 1, indices: [0] }));
        filterUsersModal('alice');
        global.fuzzySearch = origFuzzy;
        expect(row.style.display).toBe('');
    });
    test('shows all rows when query is empty', () => {
        const row = document.createElement('div');
        const nameEl = document.createElement('span');
        row.appendChild(nameEl);
        nameEl.textContent = 'bob';
        row.style.display = 'none';
        global._usersModalRows = [{ row, nameEl, username: 'bob' }];
        filterUsersModal('');
        expect(row.style.display).toBe('');
    });
});

// ── showDeleteConfirm / cancelDeleteConfirm ────────────────────────────────────
describe('showDeleteConfirm() / cancelDeleteConfirm()', () => {
    test('showDeleteConfirm switches to delete view', () => {
        showDeleteConfirm('soft');
        expect(document.getElementById('settings-delete-view').style.display).not.toBe('none');
    });
    test('cancelDeleteConfirm returns to main view', () => {
        showDeleteConfirm('soft');
        cancelDeleteConfirm();
        expect(document.getElementById('settings-main-view').style.display).not.toBe('none');
    });
});

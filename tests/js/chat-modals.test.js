/**
 * Tests for chat-modals.js — shared overlay focus handling and the help dialog.
 *
 * chat-modals.js reads the help elements at load time, so the markup has to be
 * in place before loadScript.
 */

const { loadScript } = require("./loadScript");

function buildHelpMarkup() {
  const host = document.createElement("div");
  host.innerHTML = `
    <button id="help-btn">?</button>
    <div id="help-overlay" class="hidden">
      <dialog id="help-modal" open>
        <div id="help-head">
          <button id="help-close">&times;</button>
          <h2 id="help-title">MiniMost</h2>
          <input type="search" id="help-filter">
          <nav id="help-toc"></nav>
        </div>
        <div id="help-body">
          <section class="help-sect">
            <h3 class="help-section">Messaging</h3>
            <ul><li>Enter sends the message</li><li>Shift Enter makes a new line</li></ul>
          </section>
          <section class="help-sect">
            <h3 class="help-section">Calls</h3>
            <ul><li>Click the phone icon to ring someone</li></ul>
          </section>
          <p id="help-empty" hidden>Nothing matches that.</p>
        </div>
      </dialog>
    </div>`;
  document.body.appendChild(host);
}

beforeAll(() => {
  buildHelpMarkup();
  loadScript("chat-modals.js");
});

// A throwaway dialog with two focusables, for the generic openModal tests.
function makeModal(id = "test-modal") {
  document.getElementById(id)?.remove();
  const el = document.createElement("div");
  el.id = id;
  el.style.display = "none";
  el.innerHTML = `<input id="${id}-first"><button id="${id}-last">Go</button>`;
  document.body.appendChild(el);
  return el;
}

describe("openModal()", () => {
  test("shows the element and announces it as a dialog", () => {
    const el = makeModal();
    openModal(el, { label: "Test dialog" });
    expect(el.style.display).toBe("block");
    expect(el.getAttribute("role")).toBe("dialog");
    expect(el.getAttribute("aria-modal")).toBe("true");
    expect(el.getAttribute("aria-label")).toBe("Test dialog");
    closeModal(el);
  });

  test("honours a caller-supplied display value", () => {
    const el = makeModal();
    openModal(el, { display: "flex" });
    expect(el.style.display).toBe("flex");
    closeModal(el);
  });

  test("moves focus into the dialog", () => {
    const el = makeModal();
    openModal(el);
    expect(document.activeElement.id).toBe("test-modal-first");
    closeModal(el);
  });

  test("prefers the close button over whatever comes first in the markup", () => {
    // Account leads with "Sign out"; landing there means one stray Enter signs
    // the user out.
    const el = makeModal();
    el.insertAdjacentHTML(
      "afterbegin",
      '<button id="danger">Sign out</button><button class="modal-close-x" id="x">x</button>',
    );
    openModal(el);
    expect(document.activeElement.id).toBe("x");
    closeModal(el);
  });

  test("lands on an explicitly requested element", () => {
    const el = makeModal();
    openModal(el, { focus: document.getElementById("test-modal-last") });
    expect(document.activeElement.id).toBe("test-modal-last");
    closeModal(el);
  });

  test("re-opening an open dialog does not stack a second entry", () => {
    const el = makeModal();
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    opener.focus();
    openModal(el);
    openModal(el);
    closeModal(el);
    // One close is enough to unwind it and hand focus back.
    expect(document.activeElement).toBe(opener);
  });
});

describe("closeModal()", () => {
  test("hides the element and drops aria-modal", () => {
    const el = makeModal();
    openModal(el);
    closeModal(el);
    expect(el.style.display).toBe("none");
    expect(el.hasAttribute("aria-modal")).toBe(false);
  });

  test("returns focus to whatever opened the dialog", () => {
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    opener.focus();
    const el = makeModal();
    openModal(el);
    expect(document.activeElement.id).toBe("test-modal-first");
    closeModal(el);
    expect(document.activeElement).toBe(opener);
  });

  test("leaves focus alone when the user has already moved on", () => {
    const opener = document.createElement("button");
    const elsewhere = document.createElement("input");
    document.body.append(opener, elsewhere);
    opener.focus();
    const el = makeModal();
    openModal(el);
    elsewhere.focus();
    closeModal(el);
    expect(document.activeElement).toBe(elsewhere);
  });

  test("is a no-op on a dialog that was never opened", () => {
    const el = makeModal();
    expect(() => closeModal(el)).not.toThrow();
  });

  test("falls back to the message list when nothing held focus", () => {
    const chat = document.getElementById("chat");
    chat.tabIndex = -1;
    document.activeElement.blur();
    const el = makeModal();
    openModal(el);
    closeModal(el);
    expect(document.activeElement.id).toBe("chat");
  });

  test("falls back to the message list when the opener is gone", () => {
    const chat =
      document.getElementById("chat") ||
      document.body.appendChild(
        Object.assign(document.createElement("div"), { id: "chat" }),
      );
    chat.tabIndex = -1;
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    opener.focus();
    const el = makeModal();
    openModal(el);
    opener.remove();
    closeModal(el);
    expect(document.activeElement.id).toBe("chat");
  });
});

describe("anyModalOpen()", () => {
  test("tracks whether an overlay is up", () => {
    const el = makeModal();
    expect(anyModalOpen()).toBe(false);
    openModal(el);
    expect(anyModalOpen()).toBe(true);
    closeModal(el);
    expect(anyModalOpen()).toBe(false);
  });
});

describe("Tab containment", () => {
  function tab({ shift = false } = {}) {
    const e = new window.KeyboardEvent("keydown", {
      key: "Tab",
      bubbles: true,
      cancelable: true,
      shiftKey: shift,
    });
    document.dispatchEvent(e);
    return e;
  }

  test("Tab off the last control wraps to the first", () => {
    const el = makeModal();
    openModal(el, { focus: document.getElementById("test-modal-last") });
    const e = tab();
    expect(e.defaultPrevented).toBe(true);
    expect(document.activeElement.id).toBe("test-modal-first");
    closeModal(el);
  });

  test("Shift+Tab off the first control wraps to the last", () => {
    const el = makeModal();
    openModal(el);
    const e = tab({ shift: true });
    expect(e.defaultPrevented).toBe(true);
    expect(document.activeElement.id).toBe("test-modal-last");
    closeModal(el);
  });

  test("Tab from outside the dialog is pulled back inside", () => {
    const el = makeModal();
    const outside = document.createElement("input");
    document.body.appendChild(outside);
    openModal(el);
    outside.focus();
    tab();
    expect(document.activeElement.id).toBe("test-modal-first");
    closeModal(el);
  });

  test("Tab is left alone when no dialog is open", () => {
    const e = tab();
    expect(e.defaultPrevented).toBe(false);
  });

  test("an open suggestion list keeps Tab for accepting the suggestion", () => {
    const el = makeModal();
    el.insertAdjacentHTML(
      "beforeend",
      '<div class="autocomplete-suggestions" style="display:block"></div>',
    );
    openModal(el, { focus: document.getElementById("test-modal-last") });
    const e = tab();
    expect(e.defaultPrevented).toBe(false);
    expect(document.activeElement.id).toBe("test-modal-last");
    closeModal(el);
  });
});

describe("help dialog", () => {
  afterEach(() => closeHelp());

  test("openHelp reveals the overlay and focuses the filter box", () => {
    openHelp();
    expect(
      document.getElementById("help-overlay").classList.contains("hidden"),
    ).toBe(false);
    expect(document.activeElement.id).toBe("help-filter");
  });

  test("the jump list is built from the section headings", () => {
    openHelp();
    const labels = [
      ...document.querySelectorAll("#help-toc .help-toc-btn"),
    ].map((b) => b.textContent);
    expect(labels).toEqual(["Messaging", "Calls"]);
  });

  test("a jump-list pill scrolls its section to the top of the body", () => {
    openHelp();
    const body = document.getElementById("help-body");
    const calls = document.querySelectorAll("#help-body .help-sect")[1];
    Object.defineProperty(body, "offsetTop", { value: 40, configurable: true });
    Object.defineProperty(calls, "offsetTop", {
      value: 640,
      configurable: true,
    });
    document.querySelectorAll("#help-toc .help-toc-btn")[1].click();
    expect(body.scrollTop).toBe(600);
  });

  test("the jump list is built only once", () => {
    openHelp();
    closeHelp();
    openHelp();
    expect(document.querySelectorAll("#help-toc .help-toc-btn")).toHaveLength(
      2,
    );
  });

  test("closeHelp hides the overlay", () => {
    openHelp();
    closeHelp();
    expect(
      document.getElementById("help-overlay").classList.contains("hidden"),
    ).toBe(true);
  });

  test("the help button opens the dialog", () => {
    document.getElementById("help-btn").click();
    expect(
      document.getElementById("help-overlay").classList.contains("hidden"),
    ).toBe(false);
  });

  test("clicking the backdrop closes it, clicking the dialog does not", () => {
    openHelp();
    document
      .getElementById("help-modal")
      .dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    expect(
      document.getElementById("help-overlay").classList.contains("hidden"),
    ).toBe(false);
    document
      .getElementById("help-overlay")
      .dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    expect(
      document.getElementById("help-overlay").classList.contains("hidden"),
    ).toBe(true);
  });
});

describe("filterHelp()", () => {
  const items = () => [...document.querySelectorAll("#help-body li")];
  const visible = () =>
    items()
      .filter((li) => !li.hidden)
      .map((li) => li.textContent);

  test("keeps only the entries that match", () => {
    filterHelp("new line");
    expect(visible()).toEqual(["Shift Enter makes a new line"]);
  });

  test("hides sections left with nothing in them", () => {
    filterHelp("phone");
    const sections = [...document.querySelectorAll("#help-body .help-sect")];
    expect(sections.map((s) => s.hidden)).toEqual([true, false]);
  });

  test("a heading match keeps that whole section", () => {
    filterHelp("calls");
    expect(visible()).toEqual(["Click the phone icon to ring someone"]);
  });

  test("matching is case-insensitive", () => {
    filterHelp("ENTER SENDS");
    expect(visible()).toEqual(["Enter sends the message"]);
  });

  test("shows an empty state when nothing matches", () => {
    filterHelp("zzzznope");
    expect(visible()).toEqual([]);
    expect(document.getElementById("help-empty").hidden).toBe(false);
  });

  test("an empty query restores everything and brings the jump list back", () => {
    filterHelp("phone");
    filterHelp("");
    expect(visible()).toHaveLength(3);
    expect(document.getElementById("help-empty").hidden).toBe(true);
    expect(document.getElementById("help-toc").hidden).toBe(false);
  });

  test("the jump list is hidden while a filter is active", () => {
    filterHelp("phone");
    expect(document.getElementById("help-toc").hidden).toBe(true);
  });

  test("typing in the filter box drives the filter", () => {
    const box = document.getElementById("help-filter");
    box.value = "phone";
    box.dispatchEvent(new window.Event("input", { bubbles: true }));
    expect(visible()).toEqual(["Click the phone icon to ring someone"]);
    box.value = "";
    box.dispatchEvent(new window.Event("input", { bubbles: true }));
  });
});

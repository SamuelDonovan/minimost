// Shared overlay behaviour: focus, Tab containment, and the ARIA plumbing that
// tells assistive tech a dialog is up.
//
// Every overlay used to roll its own: the DM, channel and members dialogs
// focused a field, Account / Settings / Help focused nothing at all, none of
// them announced themselves as dialogs, none put focus back where it came
// from, and Tab always walked straight out into the page behind. Pressing `?`
// for help was the worst of it — the dialog opened but focus stayed on the
// message list, so a keyboard user had to Tab through the whole app to reach
// it. Routing every open/close through here makes all of them behave the same.

// What counts as reachable by Tab. Deliberately narrow: anything with a
// negative tabindex is skipped, as the browser would skip it.
const MODAL_FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

// A stack, not one value: Account opens sub-views over itself and a call can
// raise its own overlay while a dialog is already up, so closing the top one
// has to hand focus back to whatever was beneath it.
const openModalStack = [];

// Whether an element is actually rendered. checkVisibility() accounts for
// display:none anywhere up the tree — offsetParent does not, since it is also
// null for anything position:fixed, which is most of these overlays.
function _isRendered(node) {
  return typeof node.checkVisibility === "function"
    ? node.checkVisibility()
    : true;
}

// Tab order follows what is actually on screen, so filter out anything hidden
// (a collapsed sub-view, the "Add member" block on a public channel).
function _modalFocusables(el) {
  return [...el.querySelectorAll(MODAL_FOCUSABLE)].filter(_isRendered);
}

// Show *el* as a modal dialog and move focus into it.
//
// opts.display  — the display value the overlay needs ("block" / "flex").
// opts.label    — accessible name, when the markup has no heading to point at.
// opts.focus    — element to land on; defaults to the first focusable thing.
function openModal(el, opts = {}) {
  if (!el) return;
  const { display = "block", label, focus } = opts;

  el.setAttribute("role", "dialog");
  el.setAttribute("aria-modal", "true");
  if (label && !el.hasAttribute("aria-labelledby")) {
    el.setAttribute("aria-label", label);
  }
  el.style.display = display;

  // Re-opening an already-open dialog must not stack a second entry, or the
  // first close would leave a phantom on the stack and trap Tab forever.
  if (!openModalStack.some((entry) => entry.el === el)) {
    openModalStack.push({ el, returnFocus: document.activeElement });
  }

  // Fall back to the close button rather than whatever happens to come first
  // in the markup: in Account that is "Sign out", and landing a keyboard user
  // on it means one stray Enter signs them out of the app.
  const target =
    focus || el.querySelector(".modal-close-x") || _modalFocusables(el)[0];
  target?.focus();
}

// Hide *el* and give focus back to whatever opened it.
//
// Safe to call on a dialog that is already closed — several paths (Escape,
// backdrop click, a Cancel button) can race to close the same overlay.
function closeModal(el) {
  if (!el) return;
  el.style.display = "none";
  el.removeAttribute("aria-modal");

  const idx = openModalStack.findIndex((entry) => entry.el === el);
  if (idx === -1) return;
  const [entry] = openModalStack.splice(idx, 1);

  // Only restore focus if it is still inside the dialog we just hid. If the
  // user clicked elsewhere first, yanking focus back would be the surprise.
  if (!el.contains(document.activeElement)) return;
  const back = entry.returnFocus;
  // <body> means nothing held focus when the dialog opened (a shortcut rather
  // than a click). Focusing it is a no-op, which would strand focus on the
  // control we just hid, so send it to the message list instead.
  if (back && back !== document.body && back.isConnected && _isRendered(back)) {
    back.focus();
  } else {
    document.getElementById("chat")?.focus();
  }
}

// True while any overlay is up — lets other handlers stand down.
function anyModalOpen() {
  return openModalStack.length > 0;
}

// True while a suggestion list is open inside *el*. Those fields use Tab to
// accept the highlighted suggestion (the DM picker, private-channel members,
// add-member), and a list is only ever shown while its own field has focus —
// so an open list means Tab belongs to that field, not to focus containment.
function _autocompleteOpenIn(el) {
  return [...el.querySelectorAll(".autocomplete-suggestions")].some(
    (list) => list.style.display === "block",
  );
}

// Keep Tab inside the top-most dialog. Capture phase, so containment is decided
// before a field's own handler can stop the event from propagating.
document.addEventListener(
  "keydown",
  (e) => {
    if (e.key !== "Tab" || !openModalStack.length) return;
    const { el } = openModalStack.at(-1);
    if (_autocompleteOpenIn(el)) return;
    const items = _modalFocusables(el);
    if (!items.length) return;
    const first = items[0];
    const last = items.at(-1);
    const active = document.activeElement;

    if (!el.contains(active)) {
      e.preventDefault();
      (e.shiftKey ? last : first).focus();
    } else if (e.shiftKey && active === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && active === last) {
      e.preventDefault();
      first.focus();
    }
  },
  true,
);

// ── Help ─────────────────────────────────────────────────────────────────────
// The help dialog outgrew a single scroll: it is nine sections of reference
// material, so it gets a filter box and a jump list built from its own
// headings. Building the jump list from the DOM means adding a section to the
// markup is all it takes — there is no second list to keep in step.

const helpOverlay = document.getElementById("help-overlay");
const helpModal = document.getElementById("help-modal");
const helpFilter = document.getElementById("help-filter");

function _helpSections() {
  return [...document.querySelectorAll("#help-body .help-sect")];
}

// Build the jump list once, from the section headings themselves.
function _buildHelpToc() {
  const toc = document.getElementById("help-toc");
  if (!toc || toc.childElementCount) return;
  for (const section of _helpSections()) {
    const heading = section.querySelector(".help-section");
    if (!heading) continue;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "help-toc-btn";
    btn.textContent = heading.textContent;
    // Scroll the container by hand rather than with scrollIntoView: inside a
    // <dialog> Chrome ignores the call outright, smooth or not, and the pills
    // did nothing at all.
    btn.addEventListener("click", () => {
      const body = document.getElementById("help-body");
      if (body) body.scrollTop = section.offsetTop - body.offsetTop;
    });
    toc.appendChild(btn);
  }
}

// Hide every entry that does not match *query*, then hide any section left
// with nothing in it. A section whose heading matches keeps all its entries,
// so typing "calls" gives you the whole Calls section rather than a lone line.
function filterHelp(query) {
  const q = (query || "").trim().toLowerCase();
  const empty = document.getElementById("help-empty");
  const toc = document.getElementById("help-toc");
  let anyVisible = false;

  for (const section of _helpSections()) {
    const heading =
      section.querySelector(".help-section")?.textContent.toLowerCase() || "";
    const headingHit = !!q && heading.includes(q);
    let hits = 0;
    for (const li of section.querySelectorAll("li")) {
      const match =
        !q || headingHit || li.textContent.toLowerCase().includes(q);
      li.hidden = !match;
      if (match) hits++;
    }
    section.hidden = hits === 0;
    if (hits) anyVisible = true;
  }

  if (empty) empty.hidden = anyVisible;
  // The jump list is noise once a filter has already narrowed the page.
  if (toc) toc.hidden = !!q;
}

function openHelp() {
  _buildHelpToc();
  if (helpFilter) helpFilter.value = "";
  filterHelp("");
  helpOverlay.classList.remove("hidden");
  // Land on the filter box: `?` then typing is the fastest way to a topic, and
  // it is the first thing in the dialog for anyone tabbing through.
  openModal(helpModal, { display: "flex", focus: helpFilter });
  helpModal.scrollTop = 0;
  document.getElementById("help-body").scrollTop = 0;
}

function closeHelp() {
  helpOverlay.classList.add("hidden");
  closeModal(helpModal);
}

document.getElementById("help-btn")?.addEventListener("click", openHelp);
document.getElementById("help-close")?.addEventListener("click", closeHelp);
helpFilter?.addEventListener("input", () => filterHelp(helpFilter.value));

// Close by clicking the backdrop.
helpOverlay?.addEventListener("click", (e) => {
  if (!helpModal.contains(e.target)) closeHelp();
});

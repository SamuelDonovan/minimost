// Password-field enhancements for the auth pages: a Show/Hide reveal toggle and
// a Caps Lock warning.  Applied to every <input type="password"> on the page.
// Pure vanilla JS, no dependencies — loaded on the login, signup, and reset
// pages.
(function () {
  "use strict";

  function addReveal(wrap, input) {
    const reveal = document.createElement("button");
    reveal.type = "button";
    reveal.className = "pw-reveal";
    reveal.textContent = "Show";
    reveal.setAttribute("aria-label", "Show password");
    reveal.setAttribute("aria-pressed", "false");
    wrap.appendChild(reveal);

    reveal.addEventListener("click", function () {
      const hidden = input.type === "password";
      input.type = hidden ? "text" : "password";
      reveal.textContent = hidden ? "Hide" : "Show";
      reveal.setAttribute(
        "aria-label",
        hidden ? "Hide password" : "Show password",
      );
      reveal.setAttribute("aria-pressed", String(hidden));
      input.focus();
    });
  }

  function addCapsWarning(wrap, input) {
    const warning = document.createElement("div");
    warning.className = "caps-warning";
    warning.setAttribute("role", "alert");
    warning.hidden = true;
    warning.textContent = "Caps Lock is on";
    wrap.after(warning);

    function refresh(event) {
      // getModifierState lives on KeyboardEvent; a FocusEvent lacks it, so
      // the state is resolved as soon as the user presses a key.
      const on =
        typeof event.getModifierState === "function" &&
        event.getModifierState("CapsLock");
      warning.hidden = !(on && document.activeElement === input);
    }

    input.addEventListener("keydown", refresh);
    input.addEventListener("keyup", refresh);
    input.addEventListener("blur", function () {
      warning.hidden = true;
    });
  }

  function enhance(input) {
    if (input.dataset.pwEnhanced) return;
    input.dataset.pwEnhanced = "1";

    // Wrap the input so the reveal button can sit inside the field and the
    // caps warning can be placed directly beneath it.
    const wrap = document.createElement("div");
    wrap.className = "pw-wrap";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);

    addReveal(wrap, input);
    addCapsWarning(wrap, input);
  }

  document.addEventListener("DOMContentLoaded", function () {
    const fields = document.querySelectorAll('input[type="password"]');
    Array.prototype.forEach.call(fields, enhance);
  });
})();

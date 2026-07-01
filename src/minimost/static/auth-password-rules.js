// Live password-rule feedback shared by the signup and reset-password pages.
//
// Shows which strength requirements are met as the user types and whether the
// two password fields match, and enables the submit button only when both pass.
// The server re-validates everything in minimost.auth, so this is purely a UX
// aid.  No-ops on pages without the expected fields (e.g. login).
(function () {
  "use strict";

  // Keep this character class in sync with minimost.auth._validate_password.
  const SPECIAL = /[!@#$%^&*()\-_=+[\]{};':"\\|,.<>/?`~]/;
  // Keep in sync with password_min_length in settings.json (the server is the
  // authoritative check; this is the default for immediate UX feedback).
  const MIN_LENGTH = 15;

  function setReq(id, met, active) {
    const el = document.getElementById(id);
    if (!el) return;
    let icon;
    if (met)
      icon = "✓"; // ✓
    else if (active)
      icon = "✗"; // ✗
    else icon = "•"; // •
    el.querySelector(".req-icon").textContent = icon;
    if (met) el.className = "req-met";
    else if (active) el.className = "req-unmet";
    else el.className = "";
  }

  function makeChecker(password, confirm, message, button, reqs) {
    return function check() {
      const pw = password.value;
      const active = pw.length > 0;
      reqs.hidden = !active;

      const hasLength = pw.length >= MIN_LENGTH;
      const hasUpper = /[A-Z]/.test(pw);
      const hasLower = /[a-z]/.test(pw);
      const hasNumber = /\d/.test(pw);
      const hasSpecial = SPECIAL.test(pw);

      setReq("req-length", hasLength, active);
      setReq("req-upper", hasUpper, active);
      setReq("req-lower", hasLower, active);
      setReq("req-number", hasNumber, active);
      setReq("req-special", hasSpecial, active);

      const requirementsMet =
        hasLength && hasUpper && hasLower && hasNumber && hasSpecial;

      if (!active && !confirm.value) {
        message.textContent = "";
        message.className = "";
        button.disabled = true;
        return false;
      }

      const passwordsMatch = confirm.value.length > 0 && pw === confirm.value;

      if (confirm.value.length > 0) {
        message.textContent = passwordsMatch
          ? "✓ Passwords match"
          : "✗ Passwords do not match";
        message.className = passwordsMatch ? "match" : "no-match";
      } else {
        message.textContent = "";
        message.className = "";
      }

      button.disabled = !(requirementsMet && passwordsMatch);
      return requirementsMet && passwordsMatch;
    };
  }

  document.addEventListener("DOMContentLoaded", function () {
    const password = document.getElementById("password");
    const confirm = document.getElementById("confirm_password");
    const message = document.getElementById("password-message");
    const reqs = document.getElementById("password-requirements");
    if (!password || !confirm || !message || !reqs) return; // not this page
    const form = password.closest("form");
    const button = form ? form.querySelector('button[type="submit"]') : null;
    if (!form || !button) return;

    const check = makeChecker(password, confirm, message, button, reqs);
    password.addEventListener("input", check);
    confirm.addEventListener("input", check);
    form.addEventListener("submit", function (event) {
      if (!check()) event.preventDefault();
    });
    check();
  });
})();

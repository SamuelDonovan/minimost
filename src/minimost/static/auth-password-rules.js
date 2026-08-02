// Live credential feedback shared by the signup and reset-password pages.
//
// Shows which password strength requirements are met as the user types, whether
// the two password fields match, and whether the username is well formed —
// enabling the submit button only when all of them pass.  The server
// re-validates everything in minimost.auth, so this is purely a UX aid.
// No-ops on pages without the expected fields (e.g. login).
(function () {
  "use strict";

  // Keep this character class in sync with minimost.auth._validate_password.
  const SPECIAL = /[!@#$%^&*()\-_=+[\]{};':"\\|,.<>/?`~]/;
  // Keep in sync with password_min_length in settings.json (the server is the
  // authoritative check; this is the default for immediate UX feedback).
  const MIN_LENGTH = 15;
  // Keep in sync with minimost.auth._USERNAME_RE. Validated here as well as on
  // the server because a server-side rejection re-renders the page with both
  // password fields blank, forcing the user to retype a 15-character password
  // to fix a typo in a different field.
  const USERNAME_RE = /^[A-Za-z0-9_-]{1,32}$/;
  const USERNAME_ERROR =
    "✗ Letters, numbers, hyphens and underscores only (no spaces)";

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

  // Report on the username field, returning whether it is acceptable. Pages
  // without a username field (reset-password) pass trivially.
  function checkUsername(username, usernameMessage) {
    if (!username) return true;
    const value = username.value;
    const valid = USERNAME_RE.test(value);
    if (usernameMessage) {
      // Stay quiet until there is something to complain about.
      usernameMessage.textContent =
        value.length > 0 && !valid ? USERNAME_ERROR : "";
      usernameMessage.className = value.length > 0 && !valid ? "no-match" : "";
    }
    return valid;
  }

  function makeChecker(
    password,
    confirm,
    message,
    button,
    reqs,
    username,
    usernameMessage,
  ) {
    return function check() {
      const usernameOk = checkUsername(username, usernameMessage);
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

      const ok = requirementsMet && passwordsMatch && usernameOk;
      button.disabled = !ok;
      return ok;
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

    // Only present on signup; reset-password has no username field.
    const username = document.getElementById("username");
    const usernameMessage = document.getElementById("username-message");

    const check = makeChecker(
      password,
      confirm,
      message,
      button,
      reqs,
      username,
      usernameMessage,
    );
    password.addEventListener("input", check);
    confirm.addEventListener("input", check);
    if (username) username.addEventListener("input", check);
    form.addEventListener("submit", function (event) {
      if (!check()) event.preventDefault();
    });
    check();
  });
})();

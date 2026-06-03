// Live password-rule feedback shared by the signup and reset-password pages.
//
// Shows which strength requirements are met as the user types and whether the
// two password fields match, and enables the submit button only when both pass.
// The server re-validates everything in minimost.auth, so this is purely a UX
// aid.  No-ops on pages without the expected fields (e.g. login).
(function () {
    "use strict";

    // Keep this character class in sync with minimost.auth._validate_password.
    var SPECIAL = /[!@#$%^&*()\-_=+[\]{};':"\\|,.<>/?`~]/;
    var MIN_LENGTH = 8;

    function setReq(id, met, active) {
        var el = document.getElementById(id);
        if (!el) return;
        var icon;
        if (met) icon = "✓"; // ✓
        else if (active) icon = "✗"; // ✗
        else icon = "•"; // •
        el.querySelector(".req-icon").textContent = icon;
        if (met) el.className = "req-met";
        else if (active) el.className = "req-unmet";
        else el.className = "";
    }

    function makeChecker(password, confirm, message, button, reqs) {
        return function check() {
            var pw = password.value;
            var active = pw.length > 0;
            reqs.hidden = !active;

            var hasLength = pw.length >= MIN_LENGTH;
            var hasUpper = /[A-Z]/.test(pw);
            var hasNumber = /\d/.test(pw);
            var hasSpecial = SPECIAL.test(pw);

            setReq("req-length", hasLength, active);
            setReq("req-upper", hasUpper, active);
            setReq("req-number", hasNumber, active);
            setReq("req-special", hasSpecial, active);

            var requirementsMet = hasLength && hasUpper && hasNumber && hasSpecial;

            if (!active && !confirm.value) {
                message.textContent = "";
                message.className = "";
                button.disabled = true;
                return false;
            }

            var passwordsMatch = confirm.value.length > 0 && pw === confirm.value;

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
        var password = document.getElementById("password");
        var confirm = document.getElementById("confirm_password");
        var message = document.getElementById("password-message");
        var reqs = document.getElementById("password-requirements");
        if (!password || !confirm || !message || !reqs) return; // not this page
        var form = password.closest("form");
        var button = form ? form.querySelector('button[type="submit"]') : null;
        if (!form || !button) return;

        var check = makeChecker(password, confirm, message, button, reqs);
        password.addEventListener("input", check);
        confirm.addEventListener("input", check);
        form.addEventListener("submit", function (event) {
            if (!check()) event.preventDefault();
        });
        check();
    });
})();

const fs = require("fs");
const path = require("path");
const CODE = fs.readFileSync(
    path.resolve(__dirname, "../../src/minimost/static/auth-password-rules.js"),
    "utf8"
);

const FORM = `
<form>
  <input id="password" type="password">
  <ul id="password-requirements" hidden>
    <li id="req-length"><span class="req-icon">•</span></li>
    <li id="req-upper"><span class="req-icon">•</span></li>
    <li id="req-number"><span class="req-icon">•</span></li>
    <li id="req-special"><span class="req-icon">•</span></li>
  </ul>
  <input id="confirm_password" type="password">
  <p id="password-message"></p>
  <button type="submit" disabled>Submit</button>
</form>`;

function boot(html) {
    document.body.innerHTML = html;
    // eslint-disable-next-line no-eval
    eval(CODE);
    document.dispatchEvent(new Event("DOMContentLoaded"));
}

function type(el, value) {
    el.value = value;
    el.dispatchEvent(new Event("input", { bubbles: true }));
}

test("submit stays disabled until rules pass and passwords match", () => {
    boot(FORM);
    const pw = document.getElementById("password");
    const confirm = document.getElementById("confirm_password");
    const btn = document.querySelector('button[type="submit"]');
    const msg = document.getElementById("password-message");
    const reqs = document.getElementById("password-requirements");

    expect(btn.disabled).toBe(true);

    // weak password: requirements visible, still disabled
    type(pw, "weak");
    expect(reqs.hidden).toBe(false);
    expect(document.getElementById("req-length").className).toBe("req-unmet");
    expect(btn.disabled).toBe(true);

    // strong password, no confirm yet -> still disabled
    type(pw, "Strong1!");
    expect(document.getElementById("req-length").className).toBe("req-met");
    expect(document.getElementById("req-special").className).toBe("req-met");
    expect(btn.disabled).toBe(true);

    // mismatched confirm
    type(confirm, "Different1!");
    expect(msg.className).toBe("no-match");
    expect(btn.disabled).toBe(true);

    // matching confirm -> enabled
    type(confirm, "Strong1!");
    expect(msg.className).toBe("match");
    expect(btn.disabled).toBe(false);
});

test("submit is blocked while invalid", () => {
    boot(FORM);
    const form = document.querySelector("form");
    const e = new Event("submit", { cancelable: true, bubbles: true });
    form.dispatchEvent(e);
    expect(e.defaultPrevented).toBe(true);
});

test("no-ops on a page without the password-rule fields (e.g. login)", () => {
    expect(() =>
        boot('<form><input type="password" id="only"></form>')
    ).not.toThrow();
});

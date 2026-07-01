const fs = require("fs");
const path = require("path");
const CODE = fs.readFileSync(
  path.resolve(__dirname, "../../src/minimost/static/auth-password-field.js"),
  "utf8",
);

function boot(html) {
  document.body.innerHTML = html;
  // eslint-disable-next-line no-eval
  eval(CODE);
  document.dispatchEvent(new Event("DOMContentLoaded"));
}

function key(type, capsOn) {
  const e = new KeyboardEvent(type, { bubbles: true });
  e.getModifierState = () => capsOn;
  return e;
}

describe("reveal toggle", () => {
  test("wraps the field and toggles type/label on click", () => {
    boot('<form><input type="password" id="p"></form>');
    const input = document.getElementById("p");
    const wrap = input.closest(".pw-wrap");
    const btn = wrap.querySelector(".pw-reveal");

    expect(wrap).not.toBeNull();
    expect(btn).not.toBeNull();
    expect(input.type).toBe("password");
    expect(btn.getAttribute("aria-pressed")).toBe("false");

    btn.click();
    expect(input.type).toBe("text");
    expect(btn.textContent).toBe("Hide");
    expect(btn.getAttribute("aria-pressed")).toBe("true");

    btn.click();
    expect(input.type).toBe("password");
    expect(btn.textContent).toBe("Show");
    expect(btn.getAttribute("aria-pressed")).toBe("false");
  });

  test("reveal button does not submit the form (type=button)", () => {
    boot('<form><input type="password" id="p"></form>');
    const btn = document.querySelector(".pw-reveal");
    expect(btn.type).toBe("button");
  });
});

describe("caps lock warning", () => {
  test("toggles with caps lock state and hides on blur", () => {
    boot('<form><input type="password" id="p"></form>');
    const input = document.getElementById("p");
    const warn = document.querySelector(".caps-warning");

    expect(warn).not.toBeNull();
    expect(warn.hidden).toBe(true);

    input.focus();
    input.dispatchEvent(key("keydown", true));
    expect(warn.hidden).toBe(false);

    input.dispatchEvent(key("keyup", false));
    expect(warn.hidden).toBe(true);

    input.dispatchEvent(key("keydown", true));
    expect(warn.hidden).toBe(false);
    input.dispatchEvent(new FocusEvent("blur"));
    expect(warn.hidden).toBe(true);
  });
});

test("enhances every password field (e.g. password + confirm)", () => {
  boot(
    '<form><input type="password" id="a"><input type="password" id="b"><input type="text" id="u"></form>',
  );
  expect(document.querySelectorAll(".pw-wrap")).toHaveLength(2);
  expect(document.querySelectorAll(".pw-reveal")).toHaveLength(2);
  expect(document.querySelectorAll(".caps-warning")).toHaveLength(2);
});

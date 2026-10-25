// Edits that meet the 150 ms debounce: undo, switching generator, download after a failed render.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { assertClean, openPage, load, rerender } from "./helpers.mjs";

let browser, page;
before(async () => ({ browser, page } = await openPage()));
after(async () => {
  await browser?.close();
});

const renders = () => page.evaluate(() => Number(document.body.dataset.renders ?? 0));

/** Types `value` into the field of `arg` without waiting (the change stays in its debounce). */
const typeNow = (arg, value) => `{
  const el = document.querySelector("#arg-${arg}");
  el.value = ${JSON.stringify(value)};
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.blur();
}`;

test("undo right after an edit takes that edit back", async () => {
  await load(page, "#ABox");
  const x = await page.inputValue("#arg-x");
  await rerender(page, () => page.evaluate(`${typeNow("x", "123")}
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "z", ctrlKey: true }));`));
  assert.equal(await page.inputValue("#arg-x"), x);
  assert.equal(await page.evaluate(() => location.hash), "#ABox");
  await assertClean(page);
});

test("switching generator right after an edit drops the edit", async () => {
  await load(page, "#ABox");
  const before = await renders();
  await page.evaluate(`${typeNow("x", "123")}
    const picker = document.querySelector("#generator");
    picker.value = "ClosedBox";
    picker.dispatchEvent(new Event("change"));`);
  await page.waitForFunction((b) => Number(document.body.dataset.renders) > b, before);
  await page.waitForTimeout(500); // past the debounce: the dropped edit must not render
  assert.equal(await renders(), before + 1, "one render, for ClosedBox");
  assert.equal(await page.evaluate(() => location.hash), "#ClosedBox");
  await assertClean(page);
});

test("no download while the preview shows an error", async () => {
  await load(page, "#ABox");
  await rerender(page, () => page.fill("#arg-x", "abc"));
  assert.ok(await page.$eval("#error", (e) => !e.hidden), "error shown");
  assert.ok(await page.$eval("#download", (b) => b.disabled), "download disabled");
  await rerender(page, () => page.fill("#arg-x", "120"));
  assert.ok(await page.$eval("#download", (b) => !b.disabled), "download enabled again");
  // Not assertClean: the bad value's traceback is logged to the console on purpose.
  assert.ok(await page.$eval("#error", (e) => e.hidden), "error gone");
});

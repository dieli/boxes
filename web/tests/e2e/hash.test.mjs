// URL hash handling: broken or unknown generator names fall back to the default generator,
// invalid values to defaults or warnings.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { assertClean, openPage, load } from "./helpers.mjs";

let browser, page;
before(async () => ({ browser, page } = await openPage()));
after(async () => {
  await browser?.close();
});

for (const hash of ["#%E0", "#NoSuchGenerator?x=100"]) {
  test(`falls back to the default generator for ${hash}`, async () => {
    await load(page, hash);
    assert.ok(await page.$eval("#generator", (e) => e.value), "a generator is selected");
    assert.ok(await page.$("#preview svg"), "the preview is rendered");
    await assertClean(page);
  });
}

test("an invalid choice in the URL falls back to the default", async () => {
  await load(page, "#ABox?bottom_edge=nope");
  assert.equal(await page.inputValue("#arg-bottom_edge"), "h"); // ABox default
  assert.ok(await page.$("#preview svg"), "the preview is rendered");
  await assertClean(page);
});

test("a bad ramp value leaves 2D and 3D working with a warning", async () => {
  await load(page, "#TypeTray?ramp=1&ramp_height=nan");
  assert.ok(await page.$("#preview svg"), "the preview is rendered");
  assert.match(await page.textContent("#assembly-error"), /Ramps left out/);
  await assertClean(page);
  await assert.rejects(assertClean(page, { warnings: false }), /unexpected warning/);
});

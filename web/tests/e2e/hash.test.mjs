// URL hash handling: broken or unknown generator names fall back to the default generator.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { openPage, load } from "./helpers.mjs";

let browser, page, errors;
before(async () => ({ browser, page, errors } = await openPage()));
after(async () => {
  await browser?.close();
});

for (const hash of ["#%E0", "#NoSuchGenerator?x=100"]) {
  test(`falls back to the default generator for ${hash}`, async () => {
    await load(page, hash);
    assert.ok(await page.$eval("#generator", (e) => e.value), "a generator is selected");
    assert.ok(await page.$("#preview svg"), "the preview is rendered");
    assert.deepEqual(errors, []);
  });
}

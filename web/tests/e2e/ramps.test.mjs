// Card ramps (3D printed parts) for TypeTray and TrayLayout.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { openPage, load, rerender, download, zipEntries, stlInfo, printedParts } from "./helpers.mjs";

let browser, page, errors;
before(async () => ({ browser, page, errors } = await openPage()));
after(async () => {
  await browser?.close();
});

test("TypeTray ramps: parts list, STL zip, turning them off", async () => {
  await load(page, "#TypeTray?sx=50*2&sy=50:70&h=40&ramp=1");
  assert.ok(await page.$eval("#arg-ramp", (e) => e.checked));
  const ramps = await printedParts(page);
  assert.ok(ramps.length > 0 && ramps.every((r) => r.name.startsWith("card ramp")), JSON.stringify(ramps));

  const stls = zipEntries((await download(page, "stl-zip")).buf).filter((e) => e.name.includes("ramp"));
  assert.equal(stls.length, ramps.length, "one STL per ramp");
  assert.ok(stls.every((e) => stlInfo(e.data).ok));
  // Printed parts are not on the sheet.
  const svgParts = zipEntries((await download(page, "svg-parts")).buf);
  assert.ok(!svgParts.some((e) => e.name.includes("ramp")), "no ramp in the SVG parts");

  await rerender(page, () => page.$eval("#arg-ramp", (e) => {
    e.checked = false;
    e.dispatchEvent(new Event("change", { bubbles: true }));
  }));
  assert.deepEqual(await printedParts(page), []);
  assert.deepEqual(errors, []);
});

test("TrayLayout ramps on the left side", async () => {
  await load(page, "#TrayLayout?sx=50*2&sy=50:70&h=40&ramp=1&ramp_side=left");
  assert.ok((await printedParts(page)).length > 0);
  assert.deepEqual(errors, []);
});

test("generators without ramp support have no ramp field", async () => {
  await load(page, "#ABox");
  assert.equal(await page.$("#arg-ramp"), null);
  assert.deepEqual(errors, []);
});

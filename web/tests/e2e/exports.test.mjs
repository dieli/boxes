// STL and SVG exports for a plain box, a TrayLayout with sliding lid and a flex box.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { openPage, load, download, stlInfo, zipEntries } from "./helpers.mjs";

let browser, page, errors;
before(async () => ({ browser, page, errors } = await openPage()));
after(async () => {
  await browser?.close();
});

for (const hash of ["#ABox?burn=0.1", "#TrayLayout?Lid_style=sliding", "#FlexBox"]) {
  test(`exports ${hash}`, async () => {
    await load(page, hash);
    await page.selectOption("#export-format", "svg");
    assert.ok(await page.$eval("#print-clearance-row", (e) => e.hidden), "no print clearance for SVG");

    const svg = await download(page, "svg");
    assert.match(svg.buf.toString("utf8", 0, 2000), /<svg/);

    const asm = stlInfo((await download(page, "stl-assembly")).buf);
    assert.ok(asm.ok && asm.tris > 0, `assembly STL is valid: ${JSON.stringify(asm)}`);

    const parts = zipEntries((await download(page, "stl-zip")).buf);
    assert.ok(parts.length > 1, "zip has one STL per part");
    for (const { name, data } of parts) {
      assert.match(name, /\.stl$/);
      assert.ok(stlInfo(data).ok, `${name} is a valid STL`);
    }

    const svgParts = zipEntries((await download(page, "svg-parts")).buf);
    assert.ok(svgParts.length > 1 && svgParts.every((e) => e.name.endsWith(".svg")), "zip has one SVG per part");

    await page.selectOption("#export-format", "stl-part");
    assert.ok(await page.$eval("#export-part", (e) => !e.hidden), "part select shown");
    assert.ok(await page.$eval("#print-clearance-row", (e) => !e.hidden), "print clearance shown");
    const one = stlInfo((await download(page, "stl-part")).buf);
    assert.ok(one.ok && one.tris > 0, "single part STL is valid");
    assert.deepEqual(errors, []);
  });
}

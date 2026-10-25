// TrayLayout: 0 mm rows/columns at the edge of the layout become liners.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { assertClean, openPage, load, rerender, partNames } from "./helpers.mjs";

let browser, page;
before(async () => ({ browser, page } = await openPage()));
after(async () => {
  await browser?.close();
});

const liners = async () => (await partNames(page)).filter((n) => n.startsWith("liner"));
const sizeLine = async (marker) => (await page.inputValue("#arg-layout")).split("\n").filter((l) => l.includes(marker));

// 0 mm first column and first row: liners along the left and the back wall.
const BACK_LEFT = ` ,> 0mm
 | ,> 50mm
 | | ,> 40mm
+-+-+-+
| | | |  0mm
+-+-+-+
| | | |  60mm
+-+-+-+
| |   |  30mm
+-+-+-+
`;

test("liners from a layout in the URL", async () => {
  await load(page, "#TrayLayout?h=50&fingerholes=inside-only&layout=" + encodeURIComponent(BACK_LEFT));
  const names = await liners();
  assert.ok(names.some((n) => n.startsWith("liner x")), `back liner: ${names}`);
  assert.ok(names.some((n) => n.startsWith("liner y")), `left liner: ${names}`);
  assert.equal((await page.textContent("#assembly-error")).trim(), "");
  await assertClean(page);
});

test("editing sizes to 0 in the 3D editor", async () => {
  await load(page, "#TrayLayout?sx=50*3&sy=50*2&h=50");
  assert.deepEqual(await liners(), []);

  // Typing 0 for the first row makes a back liner.
  await rerender(page, async () => {
    const y0 = await page.$('input[data-key="layout:y0"]');
    await y0.fill("0");
    await y0.press("Enter");
  });
  assert.ok((await liners()).some((n) => n.startsWith("liner x")), "back liner");
  assert.ok((await sizeLine("mm")).some((l) => /\b0mm/.test(l)), "layout has a 0mm row");

  // The last column goes down to 0 with the arrow key.
  await rerender(page, async () => {
    const x2 = await page.$('input[data-key="layout:x2"]');
    await x2.fill("1");
    await x2.press("Enter");
  });
  await rerender(page, () => page.press('input[data-key="layout:x2"]', "ArrowDown"));
  assert.ok((await liners()).some((n) => n.startsWith("liner y")), "right liner");

  // A middle column refuses 0.
  const before = await sizeLine(",>");
  const x1 = await page.$('input[data-key="layout:x1"]');
  await x1.fill("0");
  await x1.press("Enter");
  await page.waitForTimeout(1500);
  assert.deepEqual(await sizeLine(",>"), before, "middle column unchanged");
  await assertClean(page);
});

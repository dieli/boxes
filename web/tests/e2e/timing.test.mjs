// Phase 1 target: ABox, ClosedBox, UniversalBox and TypeTray regenerate in under ~300 ms after
// the first load (render request to updated 2D and 3D view; the 150 ms debounce is not counted).
// PERF_LIMIT_MS sets the limit (CI runners are slower and share their CPU).
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { assertClean, openPage, load, rerender } from "./helpers.mjs";

const LIMIT = Number(process.env.PERF_LIMIT_MS ?? 300);

let browser, page;
before(async () => ({ browser, page } = await openPage()));
after(async () => {
  await browser?.close();
});

for (const name of ["ABox", "ClosedBox", "UniversalBox", "TypeTray"]) {
  test(`${name} regenerates in under ${LIMIT} ms`, async () => {
    await load(page, `#${name}`);
    const times = [];
    for (const h of [50, 60, 70, 80, 90]) {
      await rerender(page, () => page.fill("#arg-h", String(h)));
      times.push(Number.parseFloat(await page.textContent("#timing")));
    }
    times.sort((a, b) => a - b);
    const median = times[2];
    console.log(`${name}: median ${median} ms (${times.join(", ")})`);
    assert.ok(median < LIMIT, `${name}: median ${median} ms`);
    await assertClean(page);
  });
}

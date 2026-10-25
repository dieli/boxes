// Shared helpers for the browser smoke tests. They drive the built app (npm run build, then
// npm run preview) in Microsoft Edge or Chrome through playwright-core; no browser download needed.
import { chromium } from "playwright-core";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export const BASE = process.env.BASE_URL ?? "http://localhost:4173/";
const CHANNEL = process.env.BROWSER_CHANNEL ?? "msedge";
const OUT = fs.mkdtempSync(path.join(os.tmpdir(), "boxes-e2e-"));

/** Opens a browser page and collects page errors and console errors in `errors`. */
export async function openPage() {
  const browser = await chromium.launch({
    channel: CHANNEL,
    // Software WebGL, so the 3D view also works on machines without a GPU (CI).
    args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
  });
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 }, acceptDownloads: true });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  return { browser, page, errors };
}

/** Loads a generator URL hash ("#ABox?x=100") from scratch and waits for its first render. */
export async function load(page, hash) {
  await page.goto(BASE + hash);
  await page.reload(); // a hash-only change does not reload the app
  await waitRender(page, "");
}

/** Waits until the render time shown differs from `prev` (a new render finished). */
export async function waitRender(page, prev) {
  await page.waitForFunction(
    (p) => { const t = document.querySelector("#timing").textContent; return t && t !== p; },
    prev, { timeout: 120000 });
  await page.waitForTimeout(500); // let the 3D view and the parts list catch up
}

/** Runs `action` and waits for the render it triggers. */
export async function rerender(page, action) {
  const prev = await page.textContent("#timing");
  await action();
  await waitRender(page, prev);
}

/** Downloads the current design in export format `fmt`; returns its name and bytes. */
export async function download(page, fmt) {
  await page.selectOption("#export-format", fmt);
  const [d] = await Promise.all([page.waitForEvent("download", { timeout: 60000 }), page.click("#download")]);
  const file = path.join(OUT, d.suggestedFilename());
  await d.saveAs(file);
  return { name: d.suggestedFilename(), buf: fs.readFileSync(file) };
}

/** Triangle count and bounding box size of a binary STL; ok = the length matches the count. */
export function stlInfo(buf) {
  const n = buf.readUInt32LE(80);
  const mn = [Infinity, Infinity, Infinity], mx = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < n; i++) for (let v = 0; v < 3; v++) for (let k = 0; k < 3; k++) {
    const x = buf.readFloatLE(84 + i * 50 + 12 + v * 12 + k * 4);
    mn[k] = Math.min(mn[k], x); mx[k] = Math.max(mx[k], x);
  }
  return { tris: n, size: mx.map((m, k) => +(m - mn[k]).toFixed(2)), ok: buf.length === 84 + n * 50 };
}

/** Entries of a stored (uncompressed) zip as { name, data }. */
export function zipEntries(buf) {
  const entries = [];
  let off = 0;
  while (off + 30 <= buf.length && buf.readUInt32LE(off) === 0x04034b50) {
    const size = buf.readUInt32LE(off + 18), nl = buf.readUInt16LE(off + 26), xl = buf.readUInt16LE(off + 28);
    const name = buf.toString("utf8", off + 30, off + 30 + nl);
    const start = off + 30 + nl + xl;
    entries.push({ name, data: buf.subarray(start, start + size) });
    off = start + size;
  }
  return entries;
}

/** Name and size text of the parts list entries marked as 3D printed. */
export function printedParts(page) {
  return page.$$eval("#parts-list li", (ls) => ls
    .filter((l) => l.querySelector(".note")?.textContent === "print")
    .map((l) => ({ name: l.querySelector(".name").textContent, size: l.querySelector(".size").textContent })));
}

/** Names of all parts in the parts list. */
export function partNames(page) {
  return page.$$eval("#parts-list li .name", (ls) => ls.map((l) => l.textContent));
}

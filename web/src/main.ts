import "./style.css";
import { BoxesClient, BoxesError, type RenderResult } from "./boxesClient";
import { ParamForm } from "./form";
import type { ArgValues, Dimension, GeneratorInfo, Placement, Point2, RecordedPart } from "./protocol";
import type { AssemblyView } from "./view3d";

const DEBOUNCE_MS = 150;
const DEFAULT_GENERATOR = "ABox";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const statusEl = $("status");
const picker = $<HTMLSelectElement>("generator");
const docEl = $("doc");
const views = $("views");
const preview = $("preview");
const partsList = $("parts-list");
const partsCount = $("parts-count");
const assemblyErrorEl = $("assembly-error");
const explodeInput = $<HTMLInputElement>("explode");
const showDimsInput = $<HTMLInputElement>("show-dims");
const panel3d = $("panel3d");
const no3dEl = $("no3d");
const timingEl = $("timing");
const errorEl = $("error");
const downloadBtn = $<HTMLButtonElement>("download");

const client = new BoxesClient(new URL("wheels/", document.baseURI).href);
client.onStatus = (text) => (statusEl.textContent = text);

let generators = new Map<string, GeneratorInfo>();
let current = "";
let lastSvg = "";
let lastParts: RecordedPart[] = [];
let zoom = 1;
let debounce: number | undefined;
/** Selected part, as the index of its `<g id="p-N">` in the SVG. */
let selected: number | null = null;
let view3d: AssemblyView | null = null;
let view3dLoading: Promise<AssemblyView> | null = null;
/** Generator the 3D camera was last fitted to. */
let fittedFor = "";
/** Parts hidden in 3D, by partKeys(); kept across parameter changes, reset per generator. */
let hiddenKeys = new Set<string>();
/** SVG part index -> key in hiddenKeys, for the current render. */
let keyOfPart = new Map<number, string>();

const form = new ParamForm($("form"), () => {
  clearTimeout(debounce);
  debounce = window.setTimeout(() => {
    writeHash();
    void render();
  }, DEBOUNCE_MS);
});

// --- URL state: #Generator?arg=value&… (only non-default args) ---

function readHash(): { name: string; args: ArgValues } {
  const [name, query = ""] = decodeURIComponent(location.hash.slice(1)).split("?", 2);
  return { name, args: Object.fromEntries(new URLSearchParams(query)) };
}

function writeHash() {
  const query = new URLSearchParams(form.changedValues()).toString();
  history.replaceState(null, "", `#${current}${query ? "?" + query : ""}`);
}

// --- Generator loading & rendering ---

async function loadGenerator(name: string, initial: ArgValues = {}) {
  if (!generators.has(name)) name = DEFAULT_GENERATOR;
  if (name !== current) {
    selected = null;
    hiddenKeys = new Set();
  }
  current = name;
  picker.value = name;
  const schema = await client.schema(name);
  if (current !== name) return;
  docEl.textContent = schema.doc;
  form.build(schema, initial);
  writeHash();
  await render();
}

async function render() {
  const name = current;
  const t0 = performance.now();
  try {
    const result = await client.render(name, form.values());
    if (!result || name !== current) return; // superseded by a newer request
    lastSvg = result.svg;
    lastParts = result.parts;
    preview.innerHTML = result.svg;
    applyZoom();
    if (selected !== null && !preview.querySelector(`#p-${selected}`)) selected = null;
    applySelection2d();
    await update3d(name, result);
    const total = performance.now() - t0;
    timingEl.textContent = `${total.toFixed(0)} ms (Python ${result.ms.toFixed(0)} ms)`;
    showError(null);
    downloadBtn.disabled = false;
  } catch (e) {
    showError(e);
  }
}

function showError(e: unknown) {
  if (!e) {
    errorEl.hidden = true;
    views.classList.remove("stale");
    return;
  }
  errorEl.hidden = false;
  errorEl.textContent = e instanceof Error ? e.message : String(e);
  errorEl.title = e instanceof BoxesError ? e.detail : "";
  views.classList.add("stale");
  if (e instanceof BoxesError) console.error(e.detail);
}

function applyZoom() {
  const svg = preview.querySelector("svg");
  if (svg) svg.style.width = `${zoom * 100}%`;
}

// --- 3D view (Three.js is only loaded for generators with a placement map) ---

function getView3d(): Promise<AssemblyView> {
  view3dLoading ??= import("./view3d").then(({ AssemblyView }) => {
    view3d = new AssemblyView($("canvas3d"), (part) => select(part), setDimension);
    view3d.setExplode(Number(explodeInput.value));
    view3d.setDimensionsVisible(showDimsInput.checked);
    return view3d;
  });
  return view3dLoading;
}

/** A dimension edited in 3D: write it into the form, which re-renders as for any edit. */
function setDimension(dim: Dimension, value: number) {
  const v = Math.round(value * 100) / 100;
  if (dim.index === null || !dim.values) {
    form.set(dim.arg, String(v));
    return;
  }
  const values = dim.values.map((x, i) => (i === dim.index ? v : x));
  form.set(dim.arg, values.map((x) => String(Math.round(x * 100) / 100)).join(":"));
}

async function update3d(name: string, result: RenderResult) {
  // Placements come from Python (src/py/placements.py). A generator without a placement
  // map shows a placeholder next to the 2D sheet; a failing one shows the error instead of
  // a broken model.
  const placements = new Map<number, Placement>();
  result.parts.forEach((p, i) => p.place && placements.set(i, p.place));
  const failed = typeof result.assembly === "string";
  const none = !failed && !placements.size;
  panel3d.classList.toggle("none", none);
  no3dEl.hidden = !none;
  $("no3d-name").textContent = name;
  if (none) {
    assemblyErrorEl.hidden = true;
    return;
  }
  assemblyErrorEl.hidden = !failed;
  assemblyErrorEl.textContent = failed ? `3D placement failed: ${result.assembly}` : "";
  const view = await getView3d();
  if (name !== current) return;
  view.update(result.parts, placements, result.thickness, fittedFor !== name);
  view.setDimensions(result.dims);
  fittedFor = name;
  view.setSelected(selected);
  buildPartsList(result.parts);
  applyHidden();
}

// --- Parts list with per-part visibility in 3D ---

/** Name for each part that stays stable across parameter changes: label (numbered if repeated) or index. */
function partKeys(parts: RecordedPart[]): string[] {
  const seen = new Map<string, number>();
  return parts.map((p, i) => {
    if (!p.label) return `#${i}`;
    const n = (seen.get(p.label) ?? 0) + 1;
    seen.set(p.label, n);
    return n > 1 ? `${p.label} ${n}` : p.label;
  });
}

function buildPartsList(parts: RecordedPart[]) {
  const keys = partKeys(parts);
  keyOfPart = new Map(parts.map((p, i) => [p.part, keys[i]]));
  const rows = parts.map((p, i) => {
    const key = keys[i];
    const li = document.createElement("li");
    li.dataset.part = String(p.part);
    const box = Object.assign(document.createElement("input"), {
      type: "checkbox",
      checked: !hiddenKeys.has(key),
      disabled: !p.place,
      title: "Show in 3D",
    });
    box.addEventListener("click", (ev) => ev.stopPropagation());
    box.addEventListener("change", () => {
      if (box.checked) hiddenKeys.delete(key);
      else hiddenKeys.add(key);
      applyHidden();
    });
    const label = key.startsWith("#") ? p.place?.name || `part ${i + 1}` : key;
    li.append(
      box,
      Object.assign(document.createElement("span"), { className: "name", textContent: label, title: label }),
      Object.assign(document.createElement("span"), { className: "size", textContent: `${fmt(p.x)}×${fmt(p.y)}` }),
    );
    if (!p.place) {
      li.classList.add("unplaced");
      li.title = "Shown in the 2D sheet only";
      li.append(Object.assign(document.createElement("span"), { className: "note", textContent: "2D" }));
    }
    li.addEventListener("click", () => select(p.part === selected ? null : p.part));
    return li;
  });
  partsList.replaceChildren(...rows);
  const placed = parts.filter((p) => p.place).length;
  partsCount.textContent = placed === parts.length ? `(${placed})` : `(${placed} of ${parts.length} in 3D)`;
  applySelectionList();
}

const fmt = (v: number) => String(Math.round(v * 10) / 10);

function applyHidden() {
  view3d?.setHidden([...keyOfPart].filter(([, key]) => hiddenKeys.has(key)).map(([part]) => part));
}

function setAllHidden(hide: boolean) {
  hiddenKeys = hide ? new Set(keyOfPart.values()) : new Set();
  for (const box of partsList.querySelectorAll<HTMLInputElement>("input:not(:disabled)")) box.checked = !hide;
  applyHidden();
}

// --- Selection, shared between the 2D sheet and the 3D view ---

function select(part: number | null) {
  selected = part;
  applySelection2d();
  applySelectionList();
  view3d?.setSelected(part);
}

function applySelectionList() {
  for (const li of partsList.children as HTMLCollectionOf<HTMLElement>) {
    li.classList.toggle("selected", li.dataset.part === String(selected));
  }
  partsList.querySelector("li.selected")?.scrollIntoView({ block: "nearest" });
}

function applySelection2d() {
  preview.querySelector("g.selected")?.classList.remove("selected");
  if (selected !== null) preview.querySelector(`#p-${selected}`)?.classList.add("selected");
}

/** Recorded part whose outline contains the point (SVG user units), or null. */
function partAt(x: number, y: number): number | null {
  for (const p of lastParts) {
    const [a, b, c, d, e, f] = p.matrix;
    // Invert X = a*x + b*y + c, Y = d*x + e*y + f.
    const det = a * e - b * d;
    const dx = x - c;
    const dy = y - f;
    const lx = (e * dx - b * dy) / det;
    const ly = (a * dy - d * dx) / det;
    const inside = p.outline
      ? pointInPolygon(lx, ly, p.outline.outer)
      : lx >= 0 && lx <= p.x && ly >= 0 && ly <= p.y;
    if (inside) return p.part;
  }
  return null;
}

function pointInPolygon(x: number, y: number, poly: Point2[]): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

preview.addEventListener("click", (ev) => {
  const svg = preview.querySelector("svg");
  const ctm = svg?.getScreenCTM();
  if (!svg || !ctm) return;
  const pt = new DOMPoint(ev.clientX, ev.clientY).matrixTransform(ctm.inverse());
  let part = partAt(pt.x, pt.y);
  // Parts not drawn by a recorded wall helper: fall back to clicking their strokes.
  if (part === null) {
    const g = (ev.target as Element).closest?.("g[id^='p-']");
    if (g) part = Number(g.id.slice(2));
  }
  select(part);
});

// --- Wiring ---

picker.addEventListener("change", () => void loadGenerator(picker.value));
window.addEventListener("hashchange", () => {
  const { name, args } = readHash();
  void loadGenerator(name, args);
});
$("reset").addEventListener("click", () => form.reset());
$("zoom-in").addEventListener("click", () => ((zoom *= 1.25), applyZoom()));
$("zoom-out").addEventListener("click", () => ((zoom /= 1.25), applyZoom()));
$("zoom-fit").addEventListener("click", () => ((zoom = 1), applyZoom()));
explodeInput.addEventListener("input", () => view3d?.setExplode(Number(explodeInput.value)));
$("reset-camera").addEventListener("click", () => view3d?.resetCamera());
showDimsInput.addEventListener("change", () => view3d?.setDimensionsVisible(showDimsInput.checked));
$("show-all").addEventListener("click", () => setAllHidden(false));
$("hide-all").addEventListener("click", () => setAllHidden(true));
downloadBtn.addEventListener("click", () => {
  const url = URL.createObjectURL(new Blob([lastSvg], { type: "image/svg+xml" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: `${current}.svg` });
  a.click();
  URL.revokeObjectURL(url);
});

client.ready.then(
  async ({ groups, generators: list, loadMs }) => {
    generators = new Map(list.map((g) => [g.name, g]));
    for (const group of groups) {
      const members = list.filter((g) => g.group === group.name);
      if (!members.length) continue;
      const og = document.createElement("optgroup");
      og.label = group.title;
      for (const g of members) og.append(new Option(g.name, g.name));
      picker.append(og);
    }
    picker.disabled = false;
    statusEl.textContent = `Ready in ${(loadMs / 1000).toFixed(1)} s`;
    const { name, args } = readHash();
    await loadGenerator(name || DEFAULT_GENERATOR, args);
  },
  (e) => {
    statusEl.textContent = "Failed to load";
    showError(e);
  },
);

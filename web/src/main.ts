import "./style.css";
import { BoxesClient, BoxesError, type RenderResult } from "./boxesClient";
import { ParamForm } from "./form";
import { defaultLayout, mergeLayout, mergePair, mergeSizes, setLayoutSize, splitLayout, splitSizes, toggleLayout } from "./layout";
import type { ArgValues, Dimension, GeneratorGroup, GeneratorInfo, GridLine, Handle, Placement, Point2, RecordedPart } from "./protocol";
import { parseSvg } from "./svg";
import type { AssemblyView } from "./view3d";

const DEBOUNCE_MS = 150;
const DEFAULT_GENERATOR = "ABox";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const statusEl = $("status");
const picker = $<HTMLSelectElement>("generator");
const filterInput = $<HTMLInputElement>("generator-filter");
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
const flatNote = $("flat-note");
const sheetSizeEl = $("sheet-size");
const timingEl = $("timing");
const errorEl = $("error");
const downloadBtn = $<HTMLButtonElement>("download");
const exportFormatSelect = $<HTMLSelectElement>("export-format");
const exportPartSelect = $<HTMLSelectElement>("export-part");
const clearanceRow = $("print-clearance-row");
const clearanceInput = $<HTMLInputElement>("print-clearance");

const client = new BoxesClient(new URL("wheels/", document.baseURI).href, new URL("pyodide/", document.baseURI).href);
client.onStatus = (text) => (statusEl.textContent = text);
client.onRestart = (reason) => {
  statusEl.textContent = "Restarting Python…";
  console.warn(reason);
};
client.onRestartFailed = (e) => {
  statusEl.textContent = "Python could not restart: reload the page";
  showError(e);
};

let generatorGroups: GeneratorGroup[] = [];
let generatorList: GeneratorInfo[] = [];
let generators = new Map<string, GeneratorInfo>();
let current = "";
let lastParts: RecordedPart[] = [];
let lastThickness = 3;
let zoom = 1;
let debounce: number | undefined;
/** A form change waits for the debounce (not in the undo stack, URL or preview yet). */
let changePending = false;
/** Render requests in order; the newest one shown so far (an older result arriving later is dropped). */
let renderSeq = 0;
let shownSeq = 0;
/** The render started last, and whether the last one shown failed (its sheet is stale). */
let lastRender: Promise<void> = Promise.resolve();
let renderFailed = false;
/** loadGenerator calls in order: an older one still loading its schema gives way. */
let loadSeq = 0;
/** Selected part, as the index of its `<g id="p-N">` in the SVG. */
let selected: number | null = null;
let view3d: AssemblyView | null = null;
let view3dLoading: Promise<AssemblyView> | null = null;
/** Generator the 3D camera was last fitted to. */
let fittedFor = "";
/** Whether the camera was fitted to a flat view. */
let fittedFlat = false;
/** Parts hidden in 3D, by partKeys(); kept across parameter changes, reset per generator. */
let hiddenKeys = new Set<string>();
/** SVG part index -> key in hiddenKeys, for the current render. */
let keyOfPart = new Map<number, string>();

const form = new ParamForm($("form"), () => {
  syncLayout();
  clearTimeout(debounce);
  changePending = true;
  debounce = window.setTimeout(flushChange, DEBOUNCE_MS);
});

function flushChange() {
  clearTimeout(debounce);
  if (!changePending) return;
  changePending = false;
  recordUndo();
  writeHash();
  void startRender();
}

// --- Undo / redo of parameter changes (per generator) ---

const undoBtn = $<HTMLButtonElement>("undo");
const redoBtn = $<HTMLButtonElement>("redo");
/** Steps changing the same parameters within this time become one (typing, arrow keys). */
const UNDO_MERGE_MS = 1000;
let undoStack: ArgValues[] = [];
let undoPos = -1;
let undoLast = { keys: "", at: 0 };
/** What made the pending change, if more specific than the changed parameters (a dimension). */
let undoSource = "";

function resetUndo() {
  undoStack = [form.values()];
  undoPos = 0;
  undoLast = { keys: "", at: 0 };
  updateUndoButtons();
}

function recordUndo() {
  const values = form.values();
  const top = undoStack[undoPos];
  const changed = Object.keys(values).filter((k) => values[k] !== top?.[k]).join(",");
  const keys = `${changed}|${undoSource}`;
  undoSource = "";
  if (!changed) return;
  const now = performance.now();
  const merge = keys === undoLast.keys && now - undoLast.at < UNDO_MERGE_MS && undoPos > 0 && undoPos === undoStack.length - 1;
  undoLast = { keys, at: now };
  if (merge) {
    undoStack[undoPos] = values;
  } else {
    undoStack.splice(undoPos + 1);
    undoStack.push(values);
    undoPos++;
  }
  updateUndoButtons();
}

function stepUndo(delta: number) {
  // An edit still in its debounce is a step of its own: undo takes that one back.
  if (changePending) {
    clearTimeout(debounce);
    changePending = false;
    recordUndo();
    undoLast = { keys: "", at: 0 };
  }
  const pos = undoPos + delta;
  if (pos < 0 || pos >= undoStack.length) return;
  undoPos = pos;
  undoLast = { keys: "", at: 0 };
  const values = undoStack[pos];
  form.setAll(values);
  // A layout that was the default grid for its sx/sy follows them again.
  if (current === "TrayLayout" && values.layout === defaultLayout(values.sx ?? "", values.sy ?? "")) {
    lastDefaultLayout = values.layout;
  }
  updateUndoButtons();
  writeHash();
  void startRender();
}

function updateUndoButtons() {
  undoBtn.disabled = undoPos <= 0;
  redoBtn.disabled = undoPos >= undoStack.length - 1;
}

// --- URL state: #Generator?arg=value&… (only non-default args) ---

function readHash(): { name: string; args: ArgValues } {
  // Only the name is decoded here: URLSearchParams decodes the query itself ("+" is a space,
  // "%2B" a plus, as in TrayLayout's layout).
  const [raw, query = ""] = location.hash.slice(1).split("?", 2);
  let name = "";
  try {
    name = decodeURIComponent(raw);
  } catch {
    // A broken escape ("#%E0"): fall back to the default generator.
  }
  return { name, args: Object.fromEntries(new URLSearchParams(query)) };
}

function writeHash() {
  // A layout that is still the default grid follows sx/sy and is left out.
  const values = layoutIsDefault() ? form.changedValuesExcept("layout") : form.changedValues();
  const query = new URLSearchParams(values).toString();
  history.replaceState(null, "", `#${current}${query ? "?" + query : ""}`);
}

// --- TrayLayout: the layout text starts as the full sx x sy grid ---

/** The default layout last put into the form; null if none. */
let lastDefaultLayout: string | null = null;

function layoutIsDefault(): boolean {
  return current === "TrayLayout" && lastDefaultLayout !== null && form.get("layout") === lastDefaultLayout;
}

/** Fills the layout from sx/sy while it is empty or untouched (edited layouts are kept). */
function syncLayout() {
  if (current !== "TrayLayout") return;
  const layout = form.get("layout") ?? "";
  if (layout.trim() && layout !== lastDefaultLayout) return;
  lastDefaultLayout = defaultLayout(form.get("sx") ?? "", form.get("sy") ?? "");
  form.set("layout", lastDefaultLayout, false);
}

function populatePicker(filter = "") {
  const q = filter.trim().toLowerCase();
  picker.replaceChildren();
  for (const group of generatorGroups) {
    const members = generatorList.filter(
      (g) => g.group === group.name && (!q || g.name.toLowerCase().includes(q) || g.doc.toLowerCase().includes(q)),
    );
    if (!members.length) continue;
    const og = document.createElement("optgroup");
    og.label = group.title;
    for (const g of members) og.append(new Option(g.name, g.name));
    picker.append(og);
  }
  if (current && [...picker.options].some((o) => o.value === current)) picker.value = current;
}

// --- Generator loading & rendering ---

async function loadGenerator(name: string, initial: ArgValues = {}) {
  // An edit still in its debounce belongs to the form that is being replaced.
  clearTimeout(debounce);
  changePending = false;
  const seq = ++loadSeq;
  if (!generators.has(name)) name = DEFAULT_GENERATOR;
  if (name !== current) {
    selected = null;
    hiddenKeys = new Set();
  }
  current = name;
  if (filterInput.value && ![...picker.options].some((o) => o.value === name)) {
    filterInput.value = "";
    populatePicker();
  }
  picker.value = name;
  const schema = await client.schema(name);
  if (seq !== loadSeq) return;
  docEl.textContent = schema.doc;
  form.build(schema, initial);
  lastDefaultLayout = null;
  syncLayout();
  resetUndo();
  writeHash();
  await startRender();
}

function startRender(): Promise<void> {
  lastRender = render();
  return lastRender;
}

/** Waits until the newest render (also one started meanwhile) is done. */
async function renderSettled() {
  let r: Promise<void>;
  do {
    r = lastRender;
    await r;
  } while (r !== lastRender);
}

async function render() {
  const name = current;
  const seq = ++renderSeq;
  const t0 = performance.now();
  try {
    const result = await client.render(name, form.values());
    // Superseded: by a newer request (null), another generator or a newer result already shown.
    if (!result || name !== current || seq < shownSeq) return;
    shownSeq = seq;
    lastParts = result.parts;
    lastThickness = result.thickness;
    const svgEl = parseSvg(result.svg);
    preview.replaceChildren(svgEl);
    const wAttr = Number.parseFloat(svgEl.getAttribute("width") ?? "");
    const hAttr = Number.parseFloat(svgEl.getAttribute("height") ?? "");
    sheetSizeEl.textContent = Number.isFinite(wAttr) && Number.isFinite(hAttr)
      ? `Sheet ${Math.round(wAttr)} × ${Math.round(hAttr)} mm`
      : "";
    applyZoom();
    if (selected !== null && !preview.querySelector(`#p-${selected}`)) selected = null;
    applySelection2d();
    updateExportOptions(result.parts, result.assembly === true);
    await update3d(name, result, seq);
    if (seq !== shownSeq) return;
    const total = performance.now() - t0;
    timingEl.textContent = `${total.toFixed(0)} ms (Python ${result.ms.toFixed(0)} ms)`;
    showError(null);
    renderFailed = false;
    exportFormatSelect.disabled = false;
    downloadBtn.disabled = false;
  } catch (e) {
    if (seq < shownSeq) return;
    shownSeq = seq;
    showError(e);
    // The sheet shown is from older values: no download until a render works again.
    renderFailed = true;
    downloadBtn.disabled = true;
  }
  // Renders shown so far, with or without an error: the browser tests wait for this.
  document.body.dataset.renders = String(Number(document.body.dataset.renders ?? 0) + 1);
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
    view3d = new AssemblyView($("canvas3d"), (part) => select(part), setDimension, toggleHandle, changeChain, moveGridLine);
    view3d.setSnap(Number(snapInput.value));
    view3d.setExplode(Number(explodeInput.value));
    view3d.setDimensionsVisible(showDimsInput.checked);
    return view3d;
  });
  return view3dLoading;
}

// --- View / Edit mode of the 3D panel ---

const modeViewBtn = $<HTMLButtonElement>("mode-view");
const modeEditBtn = $<HTMLButtonElement>("mode-edit");
const editHint = $("edit-hint");
const convertBtn = $<HTMLButtonElement>("convert-tray");
const snapInput = $<HTMLSelectElement>("snap");
const snapCtl = $("snap-ctl");
let hasLines = false;
try {
  const saved = localStorage.getItem("boxes-live.snap");
  if (saved && [...snapInput.options].some((o) => o.value === saved)) snapInput.value = saved;
} catch {
  // storage unavailable: keep the default
}
let editMode = false;

function setEditMode(on: boolean) {
  editMode = on && !modeEditBtn.disabled;
  modeViewBtn.classList.toggle("active", !editMode);
  modeEditBtn.classList.toggle("active", editMode);
  modeViewBtn.setAttribute("aria-pressed", String(!editMode));
  modeEditBtn.setAttribute("aria-pressed", String(editMode));
  editHint.hidden = !editMode;
  convertBtn.hidden = !editMode || current !== "TypeTray";
  snapCtl.hidden = !editMode || !hasLines;
  // Handles sit where the parts are assembled.
  if (editMode) {
    explodeInput.value = "0";
    view3d?.setExplode(0);
  }
  explodeInput.disabled = editMode || !flatNote.hidden;
  view3d?.setEditing(editMode);
}

/** A wall piece or floor clicked in edit mode (TrayLayout): toggle it in the layout text. */
function toggleHandle(handle: Handle) {
  if (current !== "TrayLayout") return;
  const layout = toggleLayout(form.get("layout") ?? "", handle.kind, handle.i, handle.j);
  if (layout === null) return;
  undoSource = `handle:${performance.now()}`; // every click is its own undo step
  form.set("layout", layout);
}

/** "+"/"×" on a compartment size: split it in two or merge it with its neighbour, keeping the total. */
function changeChain(dim: Dimension, op: "split" | "merge") {
  if (dim.index === null || !dim.values) return;
  // Outside measurements already include the walls between compartments.
  const t = form.get("outside") === "1" ? 0 : lastThickness;
  const m = mergePair(dim.index, dim.values.length);
  const sizes = op === "split" ? splitSizes(dim.values, dim.index, t) : mergeSizes(dim.values, m, t);
  if (!sizes) return;
  undoSource = `chain:${performance.now()}`;
  if (dim.arg === "layout" && dim.axis) {
    const layout = op === "split"
      ? splitLayout(form.get("layout") ?? "", dim.axis, dim.index, sizes)
      : mergeLayout(form.get("layout") ?? "", dim.axis, m, sizes);
    if (layout !== null) form.set("layout", layout);
    return;
  }
  form.set(dim.arg, sizes.map((x) => String(Math.round(x * 100) / 100)).join(":"));
}

/** Inner walls dragged in 3D: the two compartments on either side get the new sizes. */
function moveGridLine(line: GridLine, values: number[]) {
  undoSource = `line:${performance.now()}`;
  if (line.arg === "layout" && line.axis) {
    let layout: string | null = form.get("layout") ?? "";
    for (const k of [line.index, line.index + 1]) {
      if (layout !== null) layout = setLayoutSize(layout, line.axis, k, values[k]);
    }
    if (layout !== null) form.set("layout", layout);
    return;
  }
  form.set(line.arg, values.map((x) => String(Math.round(x * 100) / 100)).join(":"));
}

/** A part lying as on the sheet: SVG user units (y down) seen from above (y up). */
function flatPlacement(p: RecordedPart): Placement {
  const [a, b, c, d, e, f] = p.matrix;
  return { origin: [c, -f, 0], ux: [a, -d, 0], uy: [b, -e, 0], n: [0, 0, 1], name: "" };
}

/** TypeTray -> TrayLayout with the same grid and the settings both share; Back returns. */
async function convertToTrayLayout() {
  const schema = await client.schema("TrayLayout");
  const names = new Set(schema.groups.flatMap((g) => g.args.map((a) => a.name)));
  const all = form.values();
  const values: ArgValues = { ...form.changedValues() };
  for (const name of ["sx", "sy", "h", "hi"]) values[name] = all[name];
  const shared = Object.entries(values).filter(([name]) => names.has(name) && name !== "layout");
  location.hash = `TrayLayout?${new URLSearchParams(shared).toString()}`;
}

/** A dimension edited in 3D: write it into the form, which re-renders as for any edit. */
function setDimension(dim: Dimension, value: number) {
  const v = Math.round(value * 100) / 100;
  undoSource = `dim:${dim.arg}:${dim.axis ?? ""}${dim.index ?? ""}`;
  if (dim.arg === "layout" && dim.axis && dim.index !== null) {
    const layout = setLayoutSize(form.get("layout") ?? "", dim.axis, dim.index, v);
    if (layout !== null) form.set("layout", layout);
    return;
  }
  if (dim.index === null || !dim.values) {
    form.set(dim.arg, String(v));
    return;
  }
  const values = dim.values.map((x, i) => (i === dim.index ? v : x));
  form.set(dim.arg, values.map((x) => String(Math.round(x * 100) / 100)).join(":"));
}

async function update3d(name: string, result: RenderResult, seq: number) {
  // Placements come from Python (src/py/placements.py). A generator without a placement
  // map shows a placeholder next to the 2D sheet; a failing one shows the error instead of
  // a broken model.
  const placements = new Map<number, Placement>();
  result.parts.forEach((p, i) => p.place && placements.set(i, p.place));
  const failed = typeof result.assembly === "string";
  // No assembly (or a failed one): the parts lie flat, as on the sheet.
  const flat = !placements.size;
  if (flat) {
    // Only for the view: the parts stay unplaced (parts list, STL export).
    result.parts.forEach((p, i) => p.outline && placements.set(i, flatPlacement(p)));
  }
  const none = !placements.size;
  panel3d.classList.toggle("none", none);
  no3dEl.hidden = !none;
  $("no3d-name").textContent = name;
  if (none) {
    buildPartsList([]);
    assemblyErrorEl.hidden = true;
    modeEditBtn.disabled = true;
    hasLines = false;
    setEditMode(false);
    return;
  }
  const warnings = result.warnings ?? [];
  assemblyErrorEl.hidden = !failed && !warnings.length;
  assemblyErrorEl.textContent = failed ? `3D placement failed: ${result.assembly}` : warnings.join(" ");
  assemblyErrorEl.classList.toggle("warning", !failed);
  flatNote.hidden = !flat || failed;
  flatNote.textContent = `Flat view: no assembly for ${name} yet.`;
  explodeInput.disabled = flat || editMode;
  const view = await getView3d();
  if (name !== current || seq !== shownSeq) return;
  view.update(result.parts, placements, result.thickness, fittedFor !== name || flat !== fittedFlat, flat);
  fittedFlat = flat;
  if (flat && explodeInput.value !== "0") {
    explodeInput.value = "0";
    view.setExplode(0);
  }
  view.setDimensions(result.dims);
  view.setHandles(result.handles);
  view.setLines(result.lines);
  hasLines = result.lines.length > 0;
  modeEditBtn.disabled = !result.handles.length && !result.dims.some((d) => d.index !== null && d.values);
  editHint.textContent = [
    result.handles.length ? "Click a wall piece to remove it, a green ghost to put it back, a floor to toggle it." : "",
    hasLines ? "Drag an inner wall to move it (Shift: no snapping)." : "",
    "+ / × on a size splits or merges compartments.",
    name === "TypeTray" ? "Single wall pieces: convert to TrayLayout." : "",
  ].filter(Boolean).join(" ");
  setEditMode(editMode);
  fittedFor = name;
  view.setSelected(selected);
  buildPartsList(result.parts);
  applyHidden();
}

// --- Parts list with per-part visibility & STL export ---

/** Name for each part that stays stable across parameter changes: label or placement name (numbered if repeated) or index. */
function partKeys(parts: RecordedPart[]): string[] {
  const seen = new Map<string, number>();
  return parts.map((p, i) => {
    const base = p.label || p.place?.name;
    if (!base) return `#${i}`;
    const n = (seen.get(base) ?? 0) + 1;
    seen.set(base, n);
    return n > 1 ? `${base} ${n}` : base;
  });
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  a.click();
  // Revoking right away can cancel the download in some browsers.
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

/** Size of the cut piece (with edges sticking out, e.g. a lid's "E" edges); printed parts with their width. */
function partSize(p: RecordedPart): string {
  const [w, h] = p.size ?? [p.x, p.y];
  return p.helper === "printed" && p.place?.t ? `${fmt(w)}×${fmt(h)}×${fmt(p.place.t)}` : `${fmt(w)}×${fmt(h)}`;
}

function partDisplayLabel(p: RecordedPart, i: number, key: string): string {
  return key.startsWith("#") ? p.place?.name || `part ${i + 1}` : key;
}

function updateExportOptions(parts: RecordedPart[], assembled: boolean) {
  const keys = partKeys(parts);
  const prevIdx = exportPartSelect.value;
  exportPartSelect.replaceChildren();
  parts.forEach((p, i) => {
    if (!p.outline) return;
    const label = partDisplayLabel(p, i, keys[i]);
    exportPartSelect.append(new Option(`${label} (${partSize(p)} mm)`, String(i)));
  });
  const hasOutlines = exportPartSelect.options.length > 0;
  for (const opt of exportFormatSelect.options) {
    if (opt.value.startsWith("stl-")) opt.disabled = !hasOutlines || (opt.value === "stl-assembly" && !assembled);
  }
  if (exportFormatSelect.selectedOptions[0]?.disabled) {
    exportFormatSelect.value = "svg";
  }
  syncExportPartSelection(prevIdx);
  syncExportControls();
}

function syncExportControls() {
  const format = exportFormatSelect.value;
  exportPartSelect.hidden = format !== "stl-part" || !exportPartSelect.options.length;
  clearanceRow.hidden = !format.startsWith("stl-");
}

function syncExportPartSelection(fallbackIdx = "") {
  if (selected !== null) {
    const idx = lastParts.findIndex((p) => p.part === selected && p.outline);
    if (idx >= 0) {
      exportPartSelect.value = String(idx);
      return;
    }
  }
  if (fallbackIdx && [...exportPartSelect.options].some((o) => o.value === fallbackIdx)) {
    exportPartSelect.value = fallbackIdx;
  }
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
    const label = partDisplayLabel(p, i, key);
    const printed = p.helper === "printed";
    const size = partSize(p);
    li.append(
      box,
      Object.assign(document.createElement("span"), { className: "name", textContent: label, title: label }),
      Object.assign(document.createElement("span"), { className: "size", textContent: size }),
    );
    if (printed) {
      li.title = "3D printed: in the 3D view and STL exports, not in the 2D sheet";
      li.append(Object.assign(document.createElement("span"), { className: "note", textContent: "print" }));
    } else if (!p.place) {
      li.classList.add("unplaced");
      li.title = "Shown in the 2D sheet only";
      li.append(Object.assign(document.createElement("span"), { className: "note", textContent: "2D" }));
    }
    li.addEventListener("click", () => select(p.part === selected ? null : p.part));
    // Keyboard: Tab to a part, Enter or Space selects it (as a click).
    li.tabIndex = 0;
    li.addEventListener("keydown", (ev) => {
      if (ev.target !== li || (ev.key !== "Enter" && ev.key !== " ")) return;
      ev.preventDefault();
      li.click();
    });
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
  syncExportPartSelection(exportPartSelect.value);
  view3d?.setSelected(part);
}

function applySelectionList() {
  for (const li of partsList.children as HTMLCollectionOf<HTMLElement>) {
    li.classList.toggle("selected", li.dataset.part === String(selected));
    li.setAttribute("aria-current", String(li.dataset.part === String(selected)));
  }
  partsList.querySelector("li.selected")?.scrollIntoView({ block: "nearest" });
}

function applySelection2d() {
  preview.querySelector("g.selected")?.classList.remove("selected");
  if (selected !== null) preview.querySelector(`#p-${selected}`)?.classList.add("selected");
}

/**
 * Recorded part whose outline contains the point (SVG user units) and is not inside one of its
 * holes. When a smaller piece is nested inside another part's bounding box, picks the smallest.
 */
function partAt(x: number, y: number): number | null {
  let bestPart: number | null = null;
  let bestArea = Infinity;
  for (const p of lastParts) {
    const [a, b, c, d, e, f] = p.matrix;
    // Invert X = a*x + b*y + c, Y = d*x + e*y + f.
    const det = a * e - b * d;
    if (Math.abs(det) < 1e-12) continue;
    const dx = x - c;
    const dy = y - f;
    const lx = (e * dx - b * dy) / det;
    const ly = (a * dy - d * dx) / det;
    const inside = p.outline
      ? pointInPolygon(lx, ly, p.outline.outer) && !p.outline.holes.some((h) => pointInPolygon(lx, ly, h))
      : lx >= 0 && lx <= p.x && ly >= 0 && ly <= p.y;
    const area = p.x * p.y;
    if (inside && area < bestArea) {
      bestArea = area;
      bestPart = p.part;
    }
  }
  return bestPart;
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
filterInput.addEventListener("input", () => populatePicker(filterInput.value));
filterInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && picker.value && picker.value !== current) {
    void loadGenerator(picker.value);
  } else if (e.key === "ArrowDown" && picker.options.length) {
    e.preventDefault();
    picker.focus();
  }
});
exportFormatSelect.addEventListener("change", syncExportControls);
try {
  const saved = localStorage.getItem("boxes-live.clearance");
  if (saved !== null && Number.isFinite(Number(saved))) clearanceInput.value = saved;
} catch {
  // storage unavailable: keep the default
}
clearanceInput.addEventListener("change", () => {
  try {
    localStorage.setItem("boxes-live.clearance", clearanceInput.value);
  } catch {
    // storage unavailable: the setting just isn't kept
  }
});
exportPartSelect.addEventListener("change", () => {
  const p = lastParts[Number(exportPartSelect.value)];
  if (p) select(p.part);
});
window.addEventListener("hashchange", () => {
  const { name, args } = readHash();
  loadGenerator(name, args).catch(showError);
});
$("reset").addEventListener("click", () => form.reset());
$("zoom-in").addEventListener("click", () => ((zoom *= 1.25), applyZoom()));
undoBtn.addEventListener("click", () => stepUndo(-1));
modeViewBtn.addEventListener("click", () => setEditMode(false));
modeEditBtn.addEventListener("click", () => setEditMode(true));
convertBtn.addEventListener("click", () => void convertToTrayLayout());
snapInput.addEventListener("change", () => {
  view3d?.setSnap(Number(snapInput.value));
  try {
    localStorage.setItem("boxes-live.snap", snapInput.value);
  } catch {
    // storage unavailable: the setting just isn't kept
  }
});
redoBtn.addEventListener("click", () => stepUndo(1));
window.addEventListener("keydown", (e) => {
  if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
  // Text fields in the form keep their own undo; the dimension inputs in 3D don't.
  const el = document.activeElement;
  const textField = el instanceof HTMLTextAreaElement || (el instanceof HTMLInputElement && el.type !== "checkbox" && el.type !== "range");
  if (textField && !el.closest(".labels3d")) return;
  const key = e.key.toLowerCase();
  if (key === "z" || key === "y") {
    e.preventDefault();
    stepUndo(key === "y" || e.shiftKey ? 1 : -1);
  }
});
$("zoom-out").addEventListener("click", () => ((zoom /= 1.25), applyZoom()));
$("zoom-fit").addEventListener("click", () => ((zoom = 1), applyZoom()));
explodeInput.addEventListener("input", () => view3d?.setExplode(Number(explodeInput.value)));
$("reset-camera").addEventListener("click", () => view3d?.resetCamera());
showDimsInput.addEventListener("change", () => view3d?.setDimensionsVisible(showDimsInput.checked));
$("show-all").addEventListener("click", () => setAllHidden(false));
$("hide-all").addEventListener("click", () => setAllHidden(true));
downloadBtn.addEventListener("click", async () => {
  downloadBtn.disabled = true;
  try {
    // The file is made from what the preview shows: an edit still in its debounce is rendered first.
    flushChange();
    await renderSettled();
    if (!renderFailed) await exportCurrent(exportFormatSelect.value);
  } catch (e) {
    showError(e);
  } finally {
    downloadBtn.disabled = renderFailed;
  }
});

async function exportCurrent(format: string) {
  if (format === "svg-parts") return exportSvgParts();
  // Rendered again (not the preview's SVG): the bridge joins each contour into one path.
  if (format === "svg" || format === "lbrn2" || format === "ps" || format === "svg_Ponoko") {
    const content = await client.exportFormat(current, form.values(), format);
    const ext = format === "svg_Ponoko" ? "-ponoko.svg" : `.${format}`;
    const mime = format === "ps" ? "application/postscript" : format === "lbrn2" ? "application/xml" : "image/svg+xml";
    downloadBlob(new Blob([content], { type: mime }), `${current}${ext}`);
    return;
  }
  return exportStl(format);
}

/** A ZIP with one SVG per part, named after the parts, for cutter software that loses the groups. */
async function exportSvgParts() {
  const [files, { zipStore }, { safeName }] = await Promise.all([
    client.exportParts(current, form.values(), "svg"),
    import("./zip"),
    import("./names"),
  ]);
  const keys = partKeys(lastParts);
  const labels = new Map<number, string[]>();
  lastParts.forEach((p, i) => {
    const names = labels.get(p.part) ?? [];
    const label = partDisplayLabel(p, i, keys[i]);
    if (!names.includes(label)) names.push(label);
    labels.set(p.part, names);
  });
  const enc = new TextEncoder();
  const used = new Set<string>();
  const entries = files.map((f, n) => {
    const base = safeName(f.reference ? "reference" : (labels.get(f.part) ?? [`part ${n + 1}`]).join("+"));
    let name = base;
    for (let k = 2; used.has(name); k++) name = `${base}_${k}`;
    used.add(name);
    return { name: `${String(n + 1).padStart(2, "0")}-${name}.svg`, data: enc.encode(f.content) };
  });
  if (entries.length) downloadBlob(zipStore(entries), `${current}-svg-parts.zip`);
}

/** STL for 3D printing, from a render without the laser's burn and with the print clearance. */
async function exportStl(format: string) {
  const clearance = Math.max(0, Number(clearanceInput.value) || 0);
  const [{ assemblyStl, partStl, partsZip }, { safeName }, { parts, thickness }] = await Promise.all([
    import("./stl"),
    import("./names"),
    client.printParts(current, form.values(), clearance),
  ]);
  // Matched to the preview's parts by their keys (label or placement name), not by position.
  const keys = partKeys(parts);
  const names = parts.map((p, i) => partDisplayLabel(p, i, keys[i]));
  const stl = (data: ArrayBuffer | null, name: string) => {
    if (data) downloadBlob(new Blob([data], { type: "model/stl" }), `${current}-${name}.stl`);
  };
  if (format === "stl-assembly") {
    const hidden = new Set(parts.flatMap((p, i) => (hiddenKeys.has(keys[i]) ? [p.part] : [])));
    const data = assemblyStl(parts, thickness, hidden);
    if (!data) throw new Error("STL (3D assembly): no part is shown in 3D. Show some in the parts list.");
    stl(data, "assembly");
  } else if (format === "stl-zip") {
    const zip = partsZip(parts, names, thickness);
    if (zip) downloadBlob(zip, `${current}-parts.zip`);
  } else if (format === "stl-part") {
    const idx = keys.indexOf(partKeys(lastParts)[Number(exportPartSelect.value)]);
    if (idx < 0) throw new Error("STL (one part): that part is gone. Pick it again.");
    stl(partStl(parts[idx], thickness), safeName(names[idx]));
  }
}

client.ready.then(
  async ({ groups, generators: list, loadMs }) => {
    generatorGroups = groups;
    generatorList = list;
    generators = new Map(list.map((g) => [g.name, g]));
    populatePicker();
    picker.disabled = false;
    filterInput.disabled = false;
    statusEl.textContent = `Ready in ${(loadMs / 1000).toFixed(1)} s`;
    const { name, args } = readHash();
    await loadGenerator(name || DEFAULT_GENERATOR, args);
  },
  (e) => {
    statusEl.textContent = "Failed to load";
    showError(e);
  },
).catch(showError);

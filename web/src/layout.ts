// TrayLayout's layout text (see boxes/generators/traylayout.py).

/** Parses a sections argument like "50*3", "100/2:30" or "20:30:40" as boxes does. */
export function parseSections(s: string): number[] {
  const out: number[] = [];
  for (const section of s.split(":")) {
    const [value, count] = section.includes("/") ? section.split("/") : section.split("*");
    if (count === undefined) out.push(Number(value));
    else {
      const n = Number(count);
      for (let i = 0; i < n; i++) out.push(section.includes("/") ? Number(value) / n : Number(value));
    }
  }
  return out.filter((v) => Number.isFinite(v) && v > 0);
}

/** The layout for a full sx x sy grid: all walls, all floors (like the server UI's JavaScript). */
export function defaultLayout(sx: string, sy: string): string {
  const xs = parseSections(sx);
  const ys = parseSections(sy);
  if (!xs.length || !ys.length) return "";
  let out = "";
  xs.forEach((x, i) => (out += ` |`.repeat(i) + ` ,> ${mm(x)}mm\n`));
  for (const y of ys) {
    out += "+-".repeat(xs.length) + "+\n";
    out += "| ".repeat(xs.length) + `|  ${mm(y)}mm\n`;
  }
  return out + "+-".repeat(xs.length) + "+\n";
}

function mm(v: number): string {
  return String(Math.round(v * 100) / 100);
}

const X_LINE = /^((?: \|)* ,>\s*)(\d*\.?\d+)(\s*mm)/;
const Y_LINE = /^((?:[ |][ xX])+[ |]\s*)(\d*\.?\d+)(\s*mm)/;

/**
 * Sets the size of column (axis "x") or row ("y") `index` in a layout text, leaving the rest
 * of the text as it is. Returns null if the layout has no such column or row.
 */
export function setLayoutSize(layout: string, axis: "x" | "y", index: number, value: number): string | null {
  let k = 0;
  const lines = layout.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (!line || line[0] === "#") continue;
    const isX = X_LINE.test(line);
    const m = isX ? null : Y_LINE.exec(line);
    if ((axis === "x" && isX) || (axis === "y" && m)) {
      if (k++ === index) {
        lines[i] = line.replace(axis === "x" ? X_LINE : Y_LINE, (_, pre, _v, post) => `${pre}${mm(value)}${post}`);
        return lines.join("\n");
      }
    }
  }
  return null;
}

/**
 * Toggles a wall piece or a floor cell in a layout text: "hwall" (i, j) is wall i on the
 * "+-+" line j, "vwall" (i, j) the "|" before column i in row j, "floor" (i, j) the floor of
 * column i in row j (" " or "X"). Returns null if the layout has no such position.
 */
export function toggleLayout(layout: string, kind: "hwall" | "vwall" | "floor", i: number, j: number): string | null {
  const lines = layout.split("\n");
  let wallLine = 0;
  let row = 0;
  for (let n = 0; n < lines.length; n++) {
    const line = lines[n];
    if (!line || line[0] === "#" || X_LINE.test(line)) continue;
    let pos = -1;
    if (line[0] === "+") {
      if (kind === "hwall" && wallLine === j) pos = 2 * i + 1;
      wallLine++;
    } else if (line[0] === " " || line[0] === "|") {
      if (kind !== "hwall" && row === j) pos = kind === "vwall" ? 2 * i : 2 * i + 1;
      row++;
    }
    if (pos < 0) continue;
    if (pos >= line.length) return null;
    const c = line[pos];
    const next = kind === "hwall" ? (c === "-" ? " " : "-") : kind === "vwall" ? (c === "|" ? " " : "|") : /[xX]/.test(c) ? " " : "X";
    lines[n] = line.slice(0, pos) + next + line.slice(pos + 1);
    return lines.join("\n");
  }
  return null;
}

/** A layout text as data: column/row sizes and the walls/floors grid (see toggleLayout). */
export interface Layout {
  x: number[];
  y: number[];
  /** hwalls[j][i]: wall i on "+-+" line j (0 = back), y.length + 1 lines of x.length. */
  hwalls: boolean[][];
  /** vwalls[j][i]: wall before column i in row j, y.length rows of x.length + 1. */
  vwalls: boolean[][];
  /** floors[j][i]: column i in row j has a floor. */
  floors: boolean[][];
  /** Comment lines ("#..."), kept at the top. */
  comments: string[];
}

/** Parses a layout text; null if it is not a complete grid. */
export function parseLayout(text: string): Layout | null {
  const l: Layout = { x: [], y: [], hwalls: [], vwalls: [], floors: [], comments: [] };
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    if (!line) continue;
    if (line[0] === "#") {
      l.comments.push(line);
      continue;
    }
    const xm = X_LINE.exec(line);
    if (xm) {
      l.x.push(Number(xm[2]));
      continue;
    }
    const n = l.x.length;
    if (line[0] === "+") {
      l.hwalls.push(Array.from({ length: n }, (_, i) => line[2 * i + 1] === "-"));
      continue;
    }
    const ym = Y_LINE.exec(line);
    if (!ym) return null;
    l.y.push(Number(ym[2]));
    const grid = line.padEnd(2 * n + 1).slice(0, 2 * n + 1);
    l.vwalls.push(Array.from({ length: n + 1 }, (_, i) => grid[2 * i] === "|"));
    l.floors.push(Array.from({ length: n }, (_, i) => !/[xX]/.test(grid[2 * i + 1])));
  }
  const ok = l.x.length > 0 && l.y.length > 0 && l.hwalls.length === l.y.length + 1;
  return ok ? l : null;
}

/** The text for a layout, in the format TrayLayoutFile writes. */
export function formatLayout(l: Layout): string {
  let out = l.comments.map((c) => c + "\n").join("");
  l.x.forEach((x, i) => (out += ` |`.repeat(i) + ` ,> ${mm(x)}mm\n`));
  const wallLine = (h: boolean[]) => h.map((on) => "+" + (on ? "-" : " ")).join("") + "+\n";
  l.y.forEach((y, j) => {
    out += wallLine(l.hwalls[j]);
    out += l.floors[j].map((f, i) => (l.vwalls[j][i] ? "|" : " ") + (f ? " " : "X")).join("");
    out += (l.vwalls[j][l.x.length] ? "|" : " ") + `  ${mm(y)}mm\n`;
  });
  return out + wallLine(l.hwalls[l.y.length]);
}

/**
 * Splits compartment k of a list of sizes into two equal ones separated by a wall of
 * thickness t (0 if the sizes are outside measurements), keeping the total. Null if too small.
 */
export function splitSizes(sizes: number[], k: number, t: number): number[] | null {
  const half = Math.round(((sizes[k] - t) / 2) * 100) / 100;
  return half >= 1 ? [...sizes.slice(0, k), half, half, ...sizes.slice(k + 1)] : null;
}

/** First of the two compartments merged when removing k: k and the next one, or the previous one for the last. */
export function mergePair(k: number, count: number): number {
  return k < count - 1 ? k : k - 1;
}

/** Merges compartments m and m + 1 (removing the wall of thickness t between them), keeping the total. */
export function mergeSizes(sizes: number[], m: number, t: number): number[] {
  return [...sizes.slice(0, m), sizes[m] + t + sizes[m + 1], ...sizes.slice(m + 2)];
}

/**
 * Splits column (axis "x") or row ("y") k of a layout text in two with a full wall between
 * them; the new one copies the walls and floors of k. sizes: the new sizes along that axis.
 */
export function splitLayout(text: string, axis: "x" | "y", k: number, sizes: number[]): string | null {
  const l = parseLayout(text);
  if (!l) return null;
  if (axis === "x") {
    for (const row of l.hwalls) row.splice(k + 1, 0, row[k]);
    for (const row of l.vwalls) row.splice(k + 1, 0, true);
    for (const row of l.floors) row.splice(k + 1, 0, row[k]);
    l.x = sizes;
  } else {
    l.hwalls.splice(k + 1, 0, l.x.map(() => true));
    l.vwalls.splice(k + 1, 0, [...l.vwalls[k]]);
    l.floors.splice(k + 1, 0, [...l.floors[k]]);
    l.y = sizes;
  }
  return formatLayout(l);
}

/** Merges columns/rows m and m + 1 of a layout text: the wall between goes, walls and floors of either stay. */
export function mergeLayout(text: string, axis: "x" | "y", m: number, sizes: number[]): string | null {
  const l = parseLayout(text);
  if (!l) return null;
  const or = (a: boolean[], b: boolean[]) => a.map((v, i) => v || b[i]);
  if (axis === "x") {
    for (const row of l.hwalls) row.splice(m, 2, row[m] || row[m + 1]);
    for (const row of l.vwalls) row.splice(m + 1, 1);
    for (const row of l.floors) row.splice(m, 2, row[m] || row[m + 1]);
    l.x = sizes;
  } else {
    l.hwalls.splice(m + 1, 1);
    l.vwalls.splice(m, 2, or(l.vwalls[m], l.vwalls[m + 1]));
    l.floors.splice(m, 2, or(l.floors[m], l.floors[m + 1]));
    l.y = sizes;
  }
  return formatLayout(l);
}

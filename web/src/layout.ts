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

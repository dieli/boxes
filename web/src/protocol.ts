// Messages between the UI thread and the Pyodide worker.

export interface GeneratorGroup {
  name: string;
  title: string;
}

export interface GeneratorInfo {
  name: string;
  group: string;
  doc: string;
}

interface ArgBase {
  name: string;
  label: string;
  help: string;
}

export type ArgSchema =
  | (ArgBase & { kind: "bool"; default: boolean })
  | (ArgBase & { kind: "select"; default: string; options: [value: string, label: string][] })
  | (ArgBase & { kind: "text" | "textarea"; default: string });

export interface GeneratorSchema {
  name: string;
  doc: string;
  groups: { title: string; collapsed: boolean; args: ArgSchema[] }[];
}

export interface EdgeInfo {
  /** Edge letter (e.g. "f", "F", "h"); null for composite/custom edges. */
  char: string | null;
  type: string;
  startWidth: number;
  endWidth: number;
  margin: number;
  spacing: number;
}

/** [x, y] in a wall's local frame (mm). */
export type Point2 = [number, number];

/**
 * One wall recorded while rendering. Local frame: +x along the bottom edge, +y towards
 * the top edge; the inner rectangle is (0,0)-(x,y). Each edge's cut line lies
 * `startWidth` outside it.
 */
export interface RecordedPart {
  /** Index of the `<g id="p-N">` group in the SVG. */
  part: number;
  helper: string;
  x: number;
  y: number;
  edges: EdgeInfo[];
  label: string;
  move: string;
  /** Local frame → SVG user units: X = a*x + b*y + c, Y = d*x + e*y + f. */
  matrix: [a: number, b: number, c: number, d: number, e: number, f: number];
  /** Drawn reflected (move="mirror"/"upsidedown"): the cut piece is the mirror image of its local frame. */
  mirrored: boolean;
  /** Functions between render() and the helper, innermost first, e.g. ["Lid.__call__"]. */
  callers: string[];
  outline: { outer: Point2[]; holes: Point2[][] } | null;
  /** Where the part goes in the 3D assembly; null if it is shown in 2D only. */
  place: Placement | null;
}

export type Vec3 = [number, number, number];

/**
 * World frame (mm, Z up): local (x, y) -> origin + x*ux + y*uy, material extruded from
 * that face along n by the thickness. Computed in Python (src/py/placements.py).
 */
export interface Placement {
  origin: Vec3;
  ux: Vec3;
  uy: Vec3;
  n: Vec3;
  /** Name from the placement (e.g. "lid front"), shown for parts without a label. */
  name: string;
}

/** true: generator has a placement map; string: it failed (error message); false: none. */
export type AssemblyStatus = boolean | string;

/** Argument values as sent to boxes (`--name=value`). */
export type ArgValues = Record<string, string>;

export type ToWorker =
  | { type: "init"; wheelBase: string }
  | { type: "schema"; id: number; generator: string }
  | { type: "render"; id: number; generator: string; args: ArgValues };

export type FromWorker =
  | { type: "status"; text: string }
  | { type: "ready"; groups: GeneratorGroup[]; generators: GeneratorInfo[]; loadMs: number }
  | { type: "schema"; id: number; schema: GeneratorSchema }
  | {
      type: "rendered";
      id: number;
      svg: string;
      parts: RecordedPart[];
      assembly: AssemblyStatus;
      thickness: number;
      ms: number;
    }
  | { type: "error"; id: number | null; message: string; detail: string };

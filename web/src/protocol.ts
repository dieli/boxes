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
  /** Joint angle of finger joints (90 is square); null for other edges. */
  angle: number | null;
}

/** [x, y] in a wall's local frame (mm). */
export type Point2 = [number, number];

/**
 * One wall recorded while rendering. Local frame: +x along the bottom edge, +y towards
 * the top edge; the inner rectangle is (0,0)-(x,y). Each edge's cut line lies
 * `startWidth` outside it.
 */
export interface RecordedPart {
  /** Index of the `<g id="p-N">` group in the SVG; negative for parts not in it (helper "printed": 3D printed inserts like card ramps). */
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
  /** Width and height of the cut piece (outline bounds without the burn); null without outline. */
  size: [number, number] | null;
  /** Where the part goes in the 3D assembly; null if it is shown in 2D only. */
  place: Placement | null;
}

export type Vec3 = [number, number, number];

/**
 * A bend of a flex part: from local x = x0 it follows an arc of radius r (at its face z = 0)
 * through angle degrees, turning towards -n for positive angles. The flex stretches by the
 * optional factor (arc length / length of the part used), 1 if absent.
 */
export type Bend = [x0: number, angle: number, r: number, stretch?: number];

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
  /** Thickness of parts made of other material; the box's thickness if absent. */
  t?: number;
  /** Flex parts: bends along local x (see bend.ts). */
  bend?: Bend[];
}

/**
 * An editable dimension in the 3D view: parameter `arg` (element `index` of a list parameter
 * such as sx, whose current elements are `values`) measured from a to b in world space,
 * drawn offset along the unit vector `out`. For TrayLayout, arg is "layout" and `axis` says
 * whether index is a column ("x") or a row ("y") of the layout text.
 */
export interface Dimension {
  arg: string;
  index: number | null;
  values: number[] | null;
  value: number;
  a: Vec3;
  b: Vec3;
  out: Vec3;
  /** Shown name if not arg / arg[index]. */
  label: string | null;
  axis: "x" | "y" | null;
}

/**
 * Inner walls the 3D editor can drag: those between compartments `index` and `index + 1` of
 * list parameter `arg` (`values`; TrayLayout: arg "layout" with `axis`, as in Dimension). They
 * fill the world box min..max; moving them by 1 mm along `dir` makes compartment `index`
 * `scale` mm larger (in parameter units) and the next one as much smaller.
 */
export interface GridLine {
  arg: string;
  index: number;
  values: number[];
  min: Vec3;
  max: Vec3;
  dir: Vec3;
  scale: number;
  label: string;
  axis: "x" | "y" | null;
}

/**
 * Something the 3D editor can toggle at grid position (i, j): a wall piece along x ("hwall",
 * on grid line j) or along y ("vwall", on line i), or a floor cell. `on`: present now.
 * Fills the world box min..max (where it would be, if not present).
 */
export interface Handle {
  kind: "hwall" | "vwall" | "floor";
  i: number;
  j: number;
  on: boolean;
  min: Vec3;
  max: Vec3;
}

/** true: generator has a placement map; string: it failed (error message); false: none. */
export type AssemblyStatus = boolean | string;

/** Argument values as sent to boxes (`--name=value`). */
export type ArgValues = Record<string, string>;

export type ToWorker =
  | { type: "init"; wheelBase: string }
  | { type: "schema"; id: number; generator: string }
  | { type: "render"; id: number; generator: string; args: ArgValues }
  | { type: "export"; id: number; generator: string; args: ArgValues; format: string }
  | { type: "printParts"; id: number; generator: string; args: ArgValues; clearance: number };

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
      dims: Dimension[];
      handles: Handle[];
      lines: GridLine[];
      thickness: number;
      ms: number;
    }
  | { type: "exported"; id: number; content: string }
  | { type: "printParts"; id: number; parts: RecordedPart[]; thickness: number }
  | { type: "error"; id: number | null; message: string; detail: string };

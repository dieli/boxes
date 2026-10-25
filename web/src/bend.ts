import * as THREE from "three";
import { toCreasedNormals } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import type { Bend } from "./protocol";

/**
 * Bending of flex parts in their local x-z plane (see Placement.bend): the face z = 0 runs
 * along a path of straight pieces and arcs, and local x is the length along that path.
 * Arcs turn towards -z (positive angle) or +z, with radius r at z = 0.
 */
interface Arc {
  x0: number;
  x1: number;
  /** Signed curvature per length of the part (not of the arc): positive turns towards -z. */
  k: number;
  /** Arc length per length of the part. */
  s: number;
}

interface PathState {
  px: number;
  pz: number;
  tx: number;
  tz: number;
}

/** Maps local (x, z) to the bent position. */
export class BendPath {
  private arcs: Arc[];
  /** Path state at the start and at the end of each arc. */
  private states: { start: PathState; end: PathState }[] = [];

  constructor(bends: Bend[]) {
    this.arcs = bends
      .map(([x0, angle, r, s = 1]) => ({
        x0,
        x1: x0 + (r * Math.abs(angle) * Math.PI) / 180 / s,
        k: (Math.sign(angle) * s) / r,
        s,
      }))
      .sort((a, b) => a.x0 - b.x0);
    let s: PathState = { px: 0, pz: 0, tx: 1, tz: 0 };
    let x = 0;
    for (const arc of this.arcs) {
      const start = straight(s, arc.x0 - x);
      s = along(start, arc.k, arc.s, arc.x1 - arc.x0);
      this.states.push({ start, end: s });
      x = arc.x1;
    }
  }

  map(x: number, z: number): [number, number] {
    let i = this.arcs.length - 1;
    while (i >= 0 && x <= this.arcs[i].x0) i--;
    let s: PathState;
    if (i < 0) s = straight({ px: 0, pz: 0, tx: 1, tz: 0 }, x);
    else if (x < this.arcs[i].x1) s = along(this.states[i].start, this.arcs[i].k, this.arcs[i].s, x - this.arcs[i].x0);
    else s = straight(this.states[i].end, x - this.arcs[i].x1);
    // The normal (-tz, tx) is +z at the start.
    return [s.px - s.tz * z, s.pz + s.tx * z];
  }

  /** Slice positions: at most every 2 mm (less on tight arcs) inside each arc. */
  cuts(): number[] {
    const out: number[] = [];
    for (const arc of this.arcs) {
      const step = Math.min(2, (0.15 * arc.s) / Math.abs(arc.k));
      const n = Math.max(1, Math.ceil((arc.x1 - arc.x0) / step));
      for (let j = 0; j <= n; j++) out.push(arc.x0 + ((arc.x1 - arc.x0) * j) / n);
    }
    return out.sort((a, b) => a - b);
  }
}

function straight(s: PathState, l: number): PathState {
  return { ...s, px: s.px + s.tx * l, pz: s.pz + s.tz * l };
}

/**
 * Moves along an arc for part length l (arc length l * stretch); k is the turn per part
 * length, positive turns away from the normal.
 */
function along(s: PathState, k: number, stretch: number, l: number): PathState {
  const nx = -s.tz;
  const nz = s.tx;
  const c = Math.cos(k * l);
  const sn = Math.sin(k * l);
  return {
    px: s.px + ((s.tx * sn + nx * (c - 1)) * stretch) / k,
    pz: s.pz + ((s.tz * sn + nz * (c - 1)) * stretch) / k,
    tx: s.tx * c - nx * sn,
    tz: s.tz * c - nz * sn,
  };
}

type V3 = [number, number, number];

/** Clips a convex polygon to lo <= x <= hi. */
export function clipX(poly: V3[], lo: number, hi: number): V3[] {
  const half = (pts: V3[], keep: (p: V3) => number): V3[] => {
    const out: V3[] = [];
    for (let i = 0; i < pts.length; i++) {
      const a = pts[i];
      const b = pts[(i + 1) % pts.length];
      const da = keep(a);
      const db = keep(b);
      if (da >= 0) out.push(a);
      // Strict crossing only: a vertex on the plane is kept once, not doubled.
      if ((da > 0 && db < 0) || (da < 0 && db > 0)) {
        const t = da / (da - db);
        out.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]);
      }
    }
    return out;
  };
  return half(half(poly, (p) => p[0] - lo), (p) => hi - p[0]);
}

/**
 * Bent copy of an extruded part's geometry (local coordinates). Triangles are first sliced at
 * the same x positions everywhere, so neighbours share their new vertices (no cracks).
 */
export function bendGeometry(geometry: THREE.BufferGeometry, bends: Bend[]): THREE.BufferGeometry {
  const path = new BendPath(bends);
  const cuts = path.cuts();
  const src = (geometry.index ? geometry.toNonIndexed() : geometry).getAttribute("position");
  const out: number[] = [];
  const push = (p: V3) => {
    const [x, z] = path.map(p[0], p[2]);
    out.push(x, p[1], z);
  };
  for (let i = 0; i < src.count; i += 3) {
    const tri: V3[] = [0, 1, 2].map((j) => [src.getX(i + j), src.getY(i + j), src.getZ(i + j)] as V3);
    const minx = Math.min(tri[0][0], tri[1][0], tri[2][0]);
    const maxx = Math.max(tri[0][0], tri[1][0], tri[2][0]);
    const inside = cuts.filter((c) => c > minx && c < maxx);
    if (!inside.length) {
      tri.forEach(push);
      continue;
    }
    const bounds = [minx, ...inside, maxx];
    for (let j = 0; j + 1 < bounds.length; j++) {
      const poly = clipX(tri, bounds[j], bounds[j + 1]);
      for (let k = 1; k + 1 < poly.length; k++) {
        push(poly[0]);
        push(poly[k]);
        push(poly[k + 1]);
      }
    }
  }
  const bent = new THREE.BufferGeometry();
  bent.setAttribute("position", new THREE.Float32BufferAttribute(out, 3));
  // Smooth across the slices of a bend, sharp at the part's own edges.
  const smooth = toCreasedNormals(bent, Math.PI / 6);
  if (smooth !== bent) bent.dispose();
  return smooth;
}

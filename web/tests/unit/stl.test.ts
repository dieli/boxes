import * as THREE from "three";
import { describe, expect, test } from "vitest";
import type { Placement, RecordedPart, Vec3 } from "../../src/protocol";
import { assemblyStl, partStl, partsZip } from "../../src/stl";

function square(size: number, place: Placement | null, part = 0): RecordedPart {
  return {
    part, helper: "rectangularWall", x: size, y: size, edges: [], label: "", move: "",
    matrix: [1, 0, 0, 0, 1, 0], mirrored: false, callers: [],
    outline: { outer: [[0, 0], [size, 0], [size, size], [0, size]], holes: [] },
    size: [size, size], place,
  };
}

function place(origin: Vec3, ux: Vec3, uy: Vec3, n: Vec3): Placement {
  return { origin, ux, uy, n, name: "" };
}

/** Triangles of a binary STL: normal and the three vertices. */
function triangles(buf: ArrayBuffer) {
  const v = new DataView(buf);
  const count = v.getUint32(80, true);
  expect(buf.byteLength).toBe(84 + 50 * count);
  const out = [];
  for (let i = 0; i < count; i++) {
    const o = 84 + 50 * i;
    const f = (k: number) => v.getFloat32(o + 4 * k, true);
    out.push({
      n: new THREE.Vector3(f(0), f(1), f(2)),
      p: [1, 2, 3].map((k) => new THREE.Vector3(f(3 * k), f(3 * k + 1), f(3 * k + 2))),
    });
  }
  return out;
}

/** Every normal points away from the centre of the (convex) solid. */
function expectOutward(buf: ArrayBuffer, centre: THREE.Vector3) {
  const tris = triangles(buf);
  expect(tris.length).toBe(12); // a box: 2 triangles per face
  for (const { n, p } of tris) {
    const c = p[0].clone().add(p[1]).add(p[2]).divideScalar(3);
    expect(n.dot(c.sub(centre))).toBeGreaterThan(0);
  }
}

describe("assemblyStl", () => {
  test("normals point outwards", () => {
    const part = square(10, place([0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]));
    expectOutward(assemblyStl([part], 3, new Set())!, new THREE.Vector3(5, 5, 1.5));
  });

  test("normals point outwards for reflected placements", () => {
    // ux = -x: the part is mirrored (determinant -1).
    const part = square(10, place([10, 0, 0], [-1, 0, 0], [0, 1, 0], [0, 0, 1]));
    expectOutward(assemblyStl([part], 3, new Set())!, new THREE.Vector3(5, 5, 1.5));
  });

  test("leaves out hidden and unplaced parts; null if nothing is left", () => {
    const placed = square(10, place([0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]), 1);
    const unplaced = square(10, null, 2);
    expect(assemblyStl([placed, unplaced], 3, new Set([1]))).toBeNull();
    expect(triangles(assemblyStl([placed, unplaced], 3, new Set())!).length).toBe(12);
  });

  test("uses the part's own thickness", () => {
    const part = square(10, { ...place([0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]), t: 5 });
    const zs = triangles(assemblyStl([part], 3, new Set())!).flatMap((t) => t.p.map((q) => q.z));
    expect(Math.max(...zs)).toBeCloseTo(5, 5);
  });
});

describe("partStl / partsZip", () => {
  test("a part lies flat at the origin, whatever its placement", () => {
    const part = square(10, place([50, 50, 50], [0, 1, 0], [0, 0, 1], [1, 0, 0]));
    const pts = triangles(partStl(part, 3)!).flatMap((t) => t.p);
    expect(Math.min(...pts.map((q) => q.z))).toBeCloseTo(0, 5);
    expect(Math.max(...pts.map((q) => q.z))).toBeCloseTo(3, 5);
    expect(Math.max(...pts.map((q) => q.x))).toBeCloseTo(10, 5);
  });

  test("ZIP of parts with unique names; null without outlines", () => {
    const zip = partsZip([square(10, null), square(20, null)], ["side", "side"], 3);
    expect(zip).not.toBeNull();
    expect(partsZip([{ ...square(10, null), outline: null }], ["x"], 3)).toBeNull();
  });
});

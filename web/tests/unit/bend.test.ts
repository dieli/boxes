import * as THREE from "three";
import { describe, expect, test } from "vitest";
import { BendPath, bendGeometry, clipX } from "../../src/bend";

type V3 = [number, number, number];

function area(tri: V3[]): number {
  const [a, b, c] = tri.map((p) => new THREE.Vector3(...p));
  return new THREE.Vector3().subVectors(b, a).cross(new THREE.Vector3().subVectors(c, a)).length() / 2;
}

describe("clipX", () => {
  test("keeps a vertex on a slice plane once", () => {
    // Vertex (2, 0, 0) lies on x = 2; vertex (4, 2, 0) on neither.
    const poly = clipX([[0, 0, 0], [2, 0, 0], [4, 2, 0]], 2, 10);
    const keys = poly.map((p) => p.join(","));
    expect(new Set(keys).size).toBe(keys.length);
  });

  test("slices a triangle into pieces of the same total area", () => {
    const tri: V3[] = [[0, 0, 0], [6, 0, 0], [0, 3, 0]];
    let total = 0;
    for (const [lo, hi] of [[0, 2], [2, 4], [4, 6]]) {
      const poly = clipX(tri, lo, hi);
      for (let k = 1; k + 1 < poly.length; k++) total += area([poly[0], poly[k], poly[k + 1]]);
    }
    expect(total).toBeCloseTo(area(tri), 9);
  });
});

describe("BendPath", () => {
  test("a 90 degree arc turns the path towards -z and keeps its length", () => {
    // Straight to x = 10, a quarter circle of radius 5, then straight on.
    const path = new BendPath([[10, 90, 5]]);
    const x1 = 10 + (5 * Math.PI) / 2;
    const [ax, az] = path.map(x1, 0);
    expect(ax).toBeCloseTo(15, 9);
    expect(az).toBeCloseTo(-5, 9);
    const [bx, bz] = path.map(x1 + 7, 0);
    expect(bx).toBeCloseTo(15, 9);
    expect(bz).toBeCloseTo(-12, 9);
    // The arc turns away from +z: the face z = t runs on the outside, radius 5 + 3 around
    // the centre (10, -5).
    const [cx, cz] = path.map(10 + (5 * Math.PI) / 4, 3);
    expect(Math.hypot(cx - 10, cz + 5)).toBeCloseTo(8, 9);
  });

  test("stretch shortens the part length of the arc", () => {
    const path = new BendPath([[0, 90, 5, 2]]);
    const [x, z] = path.map((5 * Math.PI) / 2 / 2, 0);
    expect(x).toBeCloseTo(5, 9);
    expect(z).toBeCloseTo(-5, 9);
  });
});

describe("bendGeometry", () => {
  test("no zero-area triangles where slice planes meet vertices", () => {
    const shape = new THREE.Shape([0, 4, 8, 12, 20].map((x, i) => new THREE.Vector2(x, i % 2 ? 1 : 0)));
    shape.lineTo(20, 10);
    shape.lineTo(0, 10);
    const flat = new THREE.ExtrudeGeometry(shape, { depth: 3, bevelEnabled: false, curveSegments: 1 });
    // Arc from x = 4 (a vertex) of radius 10 through 45 degrees.
    const bent = bendGeometry(flat, [[4, 45, 10]]);
    const pos = bent.getAttribute("position");
    for (let i = 0; i < pos.count; i += 3) {
      const tri = [0, 1, 2].map((j) => [pos.getX(i + j), pos.getY(i + j), pos.getZ(i + j)] as V3);
      expect(area(tri)).toBeGreaterThan(1e-9);
    }
  });
});

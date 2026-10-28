// STL export for 3D printing: parts extruded by the material thickness, either as one
// assembled model or each part lying flat on the print bed (a ZIP of one STL per part).
import * as THREE from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { bendGeometry } from "./bend";
import type { Placement, RecordedPart, Vec3 } from "./protocol";
import { safeName } from "./names";
import { zipStore } from "./zip";

interface Item {
  geometry: THREE.BufferGeometry;
  matrix: THREE.Matrix4;
}

/** The parts that are placed and not hidden, at their assembled positions. */
export function assemblyStl(parts: RecordedPart[], thickness: number, hidden: Set<number>): ArrayBuffer | null {
  const items: Item[] = [];
  for (const part of parts) {
    const p = part.place;
    if (!p || !part.outline || hidden.has(part.part)) continue;
    items.push({ geometry: buildPartGeometry(part, p, thickness), matrix: basis(p.origin, p.ux, p.uy, p.n) });
  }
  return toStl(items);
}

/** One part lying flat on the bed (z = 0..t), unbent, at the origin. */
export function partStl(part: RecordedPart, thickness: number): ArrayBuffer | null {
  if (!part.outline) return null;
  return toStl([{ geometry: buildPartGeometry(part, null, part.place?.t ?? thickness), matrix: new THREE.Matrix4() }]);
}

/** A ZIP with one flat STL per part (each fits the bed on its own, unlike the whole sheet). */
export function partsZip(parts: RecordedPart[], names: string[], thickness: number): Blob | null {
  const files: { name: string; data: Uint8Array<ArrayBuffer> }[] = [];
  const used = new Set<string>();
  parts.forEach((part, i) => {
    const stl = partStl(part, thickness);
    if (!stl) return;
    let name = safeName(names[i]);
    for (let n = 2; used.has(name); n++) name = `${safeName(names[i])}_${n}`;
    used.add(name);
    files.push({ name: `${name}.stl`, data: new Uint8Array(stl) });
  });
  return files.length ? zipStore(files) : null;
}

function toStl(items: Item[]): ArrayBuffer | null {
  if (!items.length) return null;
  const stl = geometriesToBinaryStl(items);
  for (const { geometry } of items) geometry.dispose();
  return stl;
}

/** Matrix with columns ux, uy, n and translation origin (may be a reflection). */
export function basis(origin: Vec3, ux: Vec3, uy: Vec3, n: Vec3): THREE.Matrix4 {
  return new THREE.Matrix4().set(
    ux[0], uy[0], n[0], origin[0],
    ux[1], uy[1], n[1], origin[1],
    ux[2], uy[2], n[2], origin[2],
    0, 0, 0, 1,
  );
}

export function buildPartGeometry(part: RecordedPart, p: Placement | null, thickness: number): THREE.BufferGeometry {
  const { outer, holes } = part.outline!;
  const shape = new THREE.Shape(outer.map(([x, y]) => new THREE.Vector2(x, y)));
  shape.holes = holes.map((h) => new THREE.Path(h.map(([x, y]) => new THREE.Vector2(x, y))));
  const flat = new THREE.ExtrudeGeometry(shape, { depth: p?.t ?? thickness, bevelEnabled: false, curveSegments: 1 });
  const geometry = p?.bend?.length ? bendGeometry(flat, p.bend) : flat;
  if (geometry !== flat) flat.dispose();
  if (!part.bodies?.length) return geometry;
  // One piece: the extra bodies overlap it a little, so slicers merge them.
  const pieces = [geometry, ...part.bodies.map((b) => {
    const g = new THREE.ExtrudeGeometry(new THREE.Shape(b.outline.map(([x, y]) => new THREE.Vector2(x, y))),
      { depth: b.t, bevelEnabled: false, curveSegments: 1 });
    return g.applyMatrix4(basis(b.origin, b.ux, b.uy, b.n));
  })];
  const merged = mergeGeometries(pieces);
  for (const g of pieces) g.dispose();
  return merged;
}

/**
 * Serializes one or more transformed BufferGeometries into a binary STL buffer.
 * Reverses triangle winding when a transform matrix has negative determinant (reflected parts)
 * so exported meshes always have outward-pointing normals in 3D slicers.
 */
function geometriesToBinaryStl(items: { geometry: THREE.BufferGeometry; matrix: THREE.Matrix4 }[]): ArrayBuffer {
  let totalTris = 0;
  for (const { geometry } of items) {
    const count = geometry.index ? geometry.index.count : geometry.getAttribute("position").count;
    totalTris += Math.floor(count / 3);
  }
  const buf = new ArrayBuffer(84 + totalTris * 50);
  const view = new DataView(buf);
  const header = "Boxes.py Live binary STL";
  for (let i = 0; i < header.length; i++) view.setUint8(i, header.charCodeAt(i));
  view.setUint32(80, totalTris, true);

  const vA = new THREE.Vector3();
  const vB = new THREE.Vector3();
  const vC = new THREE.Vector3();
  const cb = new THREE.Vector3();
  const ab = new THREE.Vector3();
  let offset = 84;

  for (const { geometry, matrix } of items) {
    const pos = geometry.getAttribute("position");
    const idx = geometry.index;
    const count = idx ? idx.count : pos.count;
    const flipWinding = matrix.determinant() < 0;
    for (let i = 0; i + 2 < count; i += 3) {
      const i0 = idx ? idx.getX(i) : i;
      const i1 = idx ? idx.getX(i + (flipWinding ? 2 : 1)) : i + (flipWinding ? 2 : 1);
      const i2 = idx ? idx.getX(i + (flipWinding ? 1 : 2)) : i + (flipWinding ? 1 : 2);
      vA.fromBufferAttribute(pos, i0).applyMatrix4(matrix);
      vB.fromBufferAttribute(pos, i1).applyMatrix4(matrix);
      vC.fromBufferAttribute(pos, i2).applyMatrix4(matrix);
      cb.subVectors(vC, vB);
      ab.subVectors(vA, vB);
      cb.cross(ab).normalize();

      view.setFloat32(offset, cb.x, true);
      view.setFloat32(offset + 4, cb.y, true);
      view.setFloat32(offset + 8, cb.z, true);
      view.setFloat32(offset + 12, vA.x, true);
      view.setFloat32(offset + 16, vA.y, true);
      view.setFloat32(offset + 20, vA.z, true);
      view.setFloat32(offset + 24, vB.x, true);
      view.setFloat32(offset + 28, vB.y, true);
      view.setFloat32(offset + 32, vB.z, true);
      view.setFloat32(offset + 36, vC.x, true);
      view.setFloat32(offset + 40, vC.y, true);
      view.setFloat32(offset + 44, vC.z, true);
      view.setUint16(offset + 48, 0, true);
      offset += 50;
    }
  }
  return buf;
}

import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { CSS2DObject, CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import { basis, buildPartGeometry } from "./stl";
import type { Dimension, GridLine, Handle, Placement, RecordedPart } from "./protocol";

const WOOD = 0xd9b382;
const WOOD_EDGE = 0x6b4f2e;
const SELECTED = 0xf97316;
/** 3D printed parts (helper "printed", e.g. card ramps). */
const PRINTED = 0x7fb3d5;
const DIMENSION = 0x2563eb;
const REMOVE = 0xdc2626;
const ADD = 0x16a34a;
/** How far a click point may lie outside a handle's box (mm): faces of a part lie on it. */
const HANDLE_TOLERANCE = 0.2;
const CLICK_TOLERANCE_PX = 4;

interface PartObject {
  svgPart: number;
  group: THREE.Group;
  mesh: THREE.Mesh;
  material: THREE.Material;
  base: THREE.Matrix4;
  normal: THREE.Vector3;
  /** Unit direction the part moves in the exploded view. */
  explodeDir: THREE.Vector3;
}

/**
 * Smallest size of compartment k of n when dragging or typing: 1 mm, but 0 for the first and
 * last of TrayLayout's layout (dimensions with an axis), where 0 makes a glued liner.
 */
function minSize(axis: "x" | "y" | null, k: number, n: number): number {
  return axis && (k === 0 || k === n - 1) ? 0 : 1;
}

/** Extruded, assembled 3D view of the recorded parts. */
export class AssemblyView {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(35, 1, 1, 10000);
  private controls: OrbitControls;
  private root = new THREE.Group();
  private objects: PartObject[] = [];
  private material = new THREE.MeshStandardMaterial({ color: WOOD, roughness: 0.85, side: THREE.DoubleSide });
  private printedMaterial = new THREE.MeshStandardMaterial({ color: PRINTED, roughness: 0.5, side: THREE.DoubleSide });
  private selectedMaterial = new THREE.MeshStandardMaterial({ color: SELECTED, roughness: 0.7, side: THREE.DoubleSide });
  private edgeMaterial = new THREE.LineBasicMaterial({ color: WOOD_EDGE });
  private sun = new THREE.DirectionalLight(0xffffff, 2.2);
  private explode = 0;
  private explodeDistance = 0;
  private selected: number | null = null;
  private hidden = new Set<number>();
  private needsRender = true;
  private labels = new CSS2DRenderer();
  private dims = new THREE.Group();
  private dimMaterial = new THREE.LineBasicMaterial({ color: DIMENSION, depthTest: false });
  private showDims = true;
  /** Dimension input to focus once the label renderer has put it into the page. */
  private refocus: HTMLInputElement | null = null;
  // Edit mode: handles (toggleable wall pieces, floors), ghosts of the absent ones, hover box.
  private editing = false;
  private handles: { handle: Handle; box: THREE.Box3; ghost: THREE.Mesh | null }[] = [];
  private ghosts = new THREE.Group();
  private ghostMaterial = new THREE.MeshBasicMaterial({ color: ADD, transparent: true, opacity: 0.12, depthWrite: false });
  private ghostEdgeMaterial = new THREE.LineBasicMaterial({ color: ADD, transparent: true, opacity: 0.6 });
  private hoverMaterial = new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.45, depthWrite: false });
  private hover = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), this.hoverMaterial);
  private hovered: Handle | null = null;
  // Edit mode: inner walls that can be dragged, the snap step and the drag in progress.
  private lines: { line: GridLine; box: THREE.Box3 }[] = [];
  private snap = 1;
  private drag: {
    line: GridLine;
    start: THREE.Vector3;
    dir: THREE.Vector3;
    plane: THREE.Plane;
    objects: PartObject[];
    x: number;
    y: number;
    moved: boolean;
    values: number[] | null;
  } | null = null;
  private dragTip = document.createElement("div");

  constructor(
    private container: HTMLElement,
    private onSelect: (svgPart: number | null) => void,
    /** A dimension label was edited: the parameter's new value. */
    private onDimension: (dim: Dimension, value: number) => void,
    /** A handle was clicked in edit mode. */
    private onHandle: (handle: Handle) => void,
    /** "+" or "×" clicked on a compartment size (edit mode): split it or merge it with a neighbour. */
    private onChain: (dim: Dimension, op: "split" | "merge") => void,
    /** Inner walls dragged in edit mode: the list parameter's new values. */
    private onGridLine: (line: GridLine, values: number[]) => void,
  ) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.labels.domElement.className = "labels3d";
    this.dragTip.className = "drag-tip";
    this.dragTip.hidden = true;
    container.append(this.renderer.domElement, this.labels.domElement, this.dragTip);

    this.camera.up.set(0, 0, 1);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.addEventListener("change", () => (this.needsRender = true));

    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x8d7c6a, 1.6));
    this.scene.add(this.sun, this.sun.target);
    this.scene.add(this.root, this.dims, this.ghosts, this.hover);
    this.hover.visible = false;
    this.hover.renderOrder = 2;

    new ResizeObserver(() => this.resize()).observe(container);
    this.installPicking();
    this.renderer.setAnimationLoop(() => {
      if (this.controls.update() || this.needsRender) {
        this.needsRender = false;
        this.renderer.render(this.scene, this.camera);
        this.labels.render(this.scene, this.camera);
        this.declutterLabels();
        this.refocus?.focus();
        this.refocus = null;
      }
    });
  }

  /**
   * Rebuilds the model. Keeps the camera unless `refit` (e.g. a different generator). `flat`:
   * the parts lie as on the sheet (no assembly), seen more from above.
   */
  update(parts: RecordedPart[], placements: Map<number, Placement>, thickness: number, refit: boolean, flat = false) {
    this.flat = flat;
    this.clear();
    placements.forEach((placement, i) => {
      const part = parts[i];
      if (!part.outline) return;
      this.objects.push(this.buildPart(part, placement, thickness));
    });

    const bounds = new THREE.Box3().setFromObject(this.root);
    const center = bounds.getCenter(new THREE.Vector3());
    const size = bounds.getSize(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z, 1);
    this.explodeDistance = maxDim * 0.5;
    for (const o of this.objects) {
      const partCenter = new THREE.Box3().setFromObject(o.group).getCenter(new THREE.Vector3());
      o.explodeDir = partCenter.sub(center);
      if (o.explodeDir.lengthSq() > 1e-6) o.explodeDir.normalize();
      else o.explodeDir.copy(o.normal).normalize();
    }
    this.applyExplode();
    this.applySelection();
    this.applyHidden();

    this.sun.position.set(center.x + maxDim, center.y - 2 * maxDim, center.z + 3 * maxDim);
    this.sun.target.position.copy(center);
    if (refit || !this.hasFit) this.fit(center, maxDim);
    this.needsRender = true;
  }

  setExplode(f: number) {
    this.explode = f;
    this.applyExplode();
  }

  /**
   * Shows editable dimension lines (in the assembled view only). Keeps keyboard focus on
   * the same dimension across rebuilds, so Tab / arrow keys keep working while re-rendering.
   */
  setDimensions(dims: Dimension[]) {
    const focused = document.activeElement instanceof HTMLInputElement && this.labels.domElement.contains(document.activeElement)
      ? document.activeElement.dataset.key
      : undefined;
    for (const c of [...this.dims.children]) {
      this.dims.remove(c);
      if (c instanceof THREE.LineSegments) c.geometry.dispose();
      if (c instanceof CSS2DObject) c.element.remove();
    }
    const size = new THREE.Box3().setFromObject(this.root).getSize(new THREE.Vector3());
    const gap = Math.max(10, 0.12 * Math.max(size.x, size.y, size.z));
    const points: THREE.Vector3[] = [];
    for (const dim of dims) {
      const a = new THREE.Vector3(...dim.a);
      const b = new THREE.Vector3(...dim.b);
      const out = new THREE.Vector3(...dim.out).multiplyScalar(gap);
      const along = b.clone().sub(a).normalize();
      const a1 = a.clone().add(out);
      const b1 = b.clone().add(out);
      const over = out.clone().multiplyScalar(0.15);
      const tick = along.clone().add(out.clone().normalize()).multiplyScalar(gap * 0.12);
      points.push(a, a1.clone().add(over), b, b1.clone().add(over), a1, b1);
      for (const p of [a1, b1]) points.push(p.clone().sub(tick), p.clone().add(tick));
      const label = new CSS2DObject(this.dimLabel(dim, focused));
      label.position.copy(a1).add(b1).multiplyScalar(0.5);
      this.dims.add(label);
    }
    const lines = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(points), this.dimMaterial);
    lines.renderOrder = 1;
    this.dims.add(lines);
    this.applyDimsVisible();
  }

  setDimensionsVisible(show: boolean) {
    this.showDims = show;
    this.applyDimsVisible();
  }

  private applyDimsVisible() {
    this.dims.visible = (this.showDims || this.editing) && this.explode === 0;
    this.ghosts.visible = this.editing && this.explode === 0;
    if (!this.ghosts.visible) this.setHover(null);
    this.needsRender = true;
  }

  /** Edit mode: clicks toggle handles instead of selecting parts (assembled view only). */
  setEditing(on: boolean) {
    this.editing = on;
    this.labels.domElement.classList.toggle("editing", on);
    this.renderer.domElement.style.cursor = "";
    this.applyDimsVisible();
  }

  /** The toggleable things of the current model; absent ones are shown as ghosts in edit mode. */
  setHandles(handles: Handle[]) {
    for (const c of [...this.ghosts.children]) {
      this.ghosts.remove(c);
      if (c instanceof THREE.Mesh || c instanceof THREE.LineSegments) c.geometry.dispose();
    }
    this.handles = handles.map((handle) => {
      const box = new THREE.Box3(new THREE.Vector3(...handle.min), new THREE.Vector3(...handle.max));
      let ghost: THREE.Mesh | null = null;
      if (!handle.on) {
        const size = box.getSize(new THREE.Vector3());
        const geometry = new THREE.BoxGeometry(size.x, size.y, size.z);
        ghost = new THREE.Mesh(geometry, this.ghostMaterial);
        box.getCenter(ghost.position);
        const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geometry), this.ghostEdgeMaterial);
        edges.position.copy(ghost.position);
        this.ghosts.add(ghost, edges);
      }
      return { handle, box, ghost };
    });
    this.setHover(null);
    this.applyDimsVisible();
  }

  /** The draggable inner walls of the current model. */
  setLines(lines: GridLine[]) {
    this.cancelDrag();
    this.lines = lines.map((line) => ({
      line,
      box: new THREE.Box3(new THREE.Vector3(...line.min), new THREE.Vector3(...line.max)),
    }));
  }

  /** Step dragged walls snap to (compartment sizes in mm); Shift while dragging: none. */
  setSnap(mm: number) {
    this.snap = mm > 0 ? mm : 1;
  }

  /** The grid line whose walls are under the pointer (edit mode, assembled view). */
  private pickLine(ray: THREE.Raycaster): GridLine | null {
    if (!this.ghosts.visible || !this.lines.length) return null;
    const meshes = this.objects.filter((o) => o.group.visible).map((o) => o.mesh as THREE.Object3D);
    const hit = ray.intersectObjects(meshes, false)[0];
    if (!hit) return null;
    const p = hit.point.clone().addScaledVector(ray.ray.direction, HANDLE_TOLERANCE / 2);
    const found = this.lines.find((l) => l.box.distanceToPoint(p) < HANDLE_TOLERANCE);
    return found?.line ?? null;
  }

  private startDrag(line: GridLine, ray: THREE.Raycaster, e: PointerEvent) {
    const entry = this.lines.find((l) => l.line === line)!;
    const meshes = this.objects.filter((o) => o.group.visible).map((o) => o.mesh as THREE.Object3D);
    const start = ray.intersectObjects(meshes, false)[0]?.point;
    if (!start) return;
    const dir = new THREE.Vector3(...line.dir).normalize();
    // Drag in the plane through the start point that contains dir and faces the camera most.
    const view = this.camera.getWorldDirection(new THREE.Vector3());
    const normal = view.clone().addScaledVector(dir, -view.dot(dir));
    if (normal.lengthSq() < 1e-6) normal.set(0, 0, 1);
    const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(normal.normalize(), start);
    // The parts lying within the line's slab move with it (not the walls crossing it).
    const axis = [0, 1, 2].reduce((a, b) => (Math.abs(dir.getComponent(b)) > Math.abs(dir.getComponent(a)) ? b : a));
    const lo = entry.box.min.getComponent(axis) - 0.5;
    const hi = entry.box.max.getComponent(axis) + 0.5;
    const objects = this.objects.filter((o) => {
      if (!o.group.visible) return false;
      const b = new THREE.Box3().setFromObject(o.group);
      return b.min.getComponent(axis) >= lo && b.max.getComponent(axis) <= hi;
    });
    this.drag = { line, start, dir, plane, objects, x: e.clientX, y: e.clientY, moved: false, values: null };
    this.controls.enabled = false;
    this.setHover(null);
  }

  private moveDrag(ray: THREE.Raycaster, e: PointerEvent) {
    const d = this.drag!;
    if (!d.moved && Math.hypot(e.clientX - d.x, e.clientY - d.y) <= CLICK_TOLERANCE_PX) return;
    d.moved = true;
    const p = ray.ray.intersectPlane(d.plane, new THREE.Vector3());
    if (!p) return;
    const { values, index: k, scale, label } = d.line;
    const pair = values[k] + values[k + 1];
    let size = values[k] + p.sub(d.start).dot(d.dir) * scale;
    if (!e.shiftKey) size = Math.round(size / this.snap) * this.snap;
    const min = (i: number) => minSize(d.line.axis, i, values.length);
    size = Math.round(Math.min(Math.max(size, min(k)), pair - min(k + 1)) * 100) / 100;
    const next = Math.round((pair - size) * 100) / 100;
    d.values = values.map((v, i) => (i === k ? size : i === k + 1 ? next : v));
    const offset = d.dir.clone().multiplyScalar((size - values[k]) / scale);
    for (const o of d.objects) {
      o.group.matrix.copy(new THREE.Matrix4().makeTranslation(offset).multiply(o.base));
      o.group.matrixWorldNeedsUpdate = true;
    }
    const rect = this.container.getBoundingClientRect();
    this.dragTip.textContent = `${label}[${k + 1}] ${formatMm(size)}  ·  ${label}[${k + 2}] ${formatMm(next)}`;
    this.dragTip.style.left = `${e.clientX - rect.left + 14}px`;
    this.dragTip.style.top = `${e.clientY - rect.top + 14}px`;
    this.dragTip.hidden = false;
    this.renderer.domElement.style.cursor = "grabbing";
    this.needsRender = true;
  }

  /** Ends a drag; returns whether it moved (then it is not a click). */
  private endDrag(): boolean {
    const d = this.drag;
    if (!d) return false;
    this.drag = null;
    this.controls.enabled = true;
    this.dragTip.hidden = true;
    const k = d.line.index;
    if (d.values && d.values[k] !== d.line.values[k]) this.onGridLine(d.line, d.values);
    else this.applyExplode();
    return d.moved;
  }

  private cancelDrag() {
    if (!this.drag) return;
    this.drag = null;
    this.controls.enabled = true;
    this.dragTip.hidden = true;
    this.applyExplode();
  }

  private setHover(handle: Handle | null) {
    if (handle === this.hovered) return;
    this.hovered = handle;
    this.hover.visible = handle !== null;
    this.renderer.domElement.style.cursor = handle ? "pointer" : "";
    if (handle) {
      const entry = this.handles.find((h) => h.handle === handle)!;
      const grow = new THREE.Vector3(0.3, 0.3, 0.3);
      const box = entry.box.clone().expandByVector(grow);
      box.getCenter(this.hover.position);
      box.getSize(this.hover.scale);
      this.hoverMaterial.color.setHex(handle.on ? REMOVE : ADD);
    }
    this.needsRender = true;
  }

  /** The handle under the pointer: a ghost, or the handle whose box holds the point hit on a part. */
  private pickHandle(ray: THREE.Raycaster): Handle | null {
    if (!this.ghosts.visible) return null;
    const meshes = this.objects.filter((o) => o.group.visible).map((o) => o.mesh as THREE.Object3D);
    const ghosts = this.handles.filter((h) => h.ghost).map((h) => h.ghost as THREE.Object3D);
    const hit = ray.intersectObjects([...meshes, ...ghosts], false)[0];
    if (!hit) return null;
    const ghost = this.handles.find((h) => h.ghost === hit.object);
    if (ghost) return ghost.handle;
    // Step a little into the part, so a point on a face falls into the part's own handle.
    const p = hit.point.clone().addScaledVector(ray.ray.direction, HANDLE_TOLERANCE / 2);
    const inside = this.handles.filter((h) => h.handle.on && h.box.containsPoint(p));
    if (inside.length) return inside[0].handle;
    const near = this.handles.filter((h) => h.handle.on && h.box.distanceToPoint(p) < HANDLE_TOLERANCE);
    return near[0]?.handle ?? null;
  }

  /** Moves dimension labels that overlap earlier ones down on screen (narrow compartments). */
  private declutterLabels() {
    if (!this.dims.visible) return;
    const labels = [...this.labels.domElement.querySelectorAll<HTMLElement>(".dim3d")];
    for (const l of labels) l.style.translate = "";
    // Read all bounding boxes in one pass before writing styles to avoid forced layout thrashing.
    const rects = labels.map((l) => l.getBoundingClientRect());
    const placed: DOMRect[] = [];
    const shifts: [HTMLElement, number][] = [];
    const overlaps = (a: DOMRect, b: DOMRect) =>
      a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
    for (let i = 0; i < labels.length; i++) {
      let r = rects[i];
      if (!r.width) continue;
      let dy = 0;
      for (let step = 0; step < 8 && placed.some((p) => overlaps(p, r)); step++) {
        dy += r.height + 2;
        r = new DOMRect(r.x, r.y + r.height + 2, r.width, r.height);
      }
      if (dy) shifts.push([labels[i], dy]);
      placed.push(r);
    }
    for (const [l, dy] of shifts) l.style.translate = `0 ${dy}px`;
  }

  private dimLabel(dim: Dimension, focused: string | undefined): HTMLElement {
    const key = `${dim.arg}:${dim.axis ?? ""}${dim.index ?? ""}`;
    const el = document.createElement("label");
    el.className = "dim3d";
    const name = document.createElement("span");
    name.textContent = dim.label ?? (dim.index === null ? dim.arg : `${dim.arg}[${dim.index + 1}]`);
    const input = document.createElement("input");
    input.type = "text";
    input.inputMode = "decimal";
    input.dataset.key = key;
    input.value = formatMm(dim.value);
    input.size = Math.max(3, input.value.length);
    input.title = "Enter to apply, ↑/↓ to step (Shift: 10)";
    const min = dim.index !== null && dim.values ? minSize(dim.axis, dim.index, dim.values.length) : 1;
    const commit = () => {
      const v = Number(input.value.replace(",", "."));
      if (Number.isFinite(v) && v >= min && (v > 0 || min === 0) && v !== dim.value) this.onDimension(dim, v);
      else input.value = formatMm(dim.value);
    };
    input.addEventListener("change", commit);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") input.blur();
      else if (e.key === "Escape") {
        input.value = formatMm(dim.value);
        input.blur();
      } else if (e.key === "ArrowUp" || e.key === "ArrowDown") {
        e.preventDefault();
        const step = (e.shiftKey ? 10 : 1) * (e.key === "ArrowUp" ? 1 : -1);
        const typed = Number(input.value.replace(",", "."));
        const v = Math.max(min, (Number.isFinite(typed) ? typed : dim.value) + step);
        input.value = formatMm(v);
        this.onDimension(dim, v);
      }
    });
    el.append(name, input);
    if (dim.index !== null && dim.values) {
      const count = dim.values.length;
      const op = (text: string, title: string, kind: "split" | "merge") => {
        const b = Object.assign(document.createElement("button"), { type: "button", textContent: text, title });
        b.className = `chain-op ${kind}`;
        b.addEventListener("click", () => this.onChain(dim, kind));
        return b;
      };
      el.append(op("+", "Split in two (adds a wall)", "split"));
      if (count > 1) {
        const other = dim.index < count - 1 ? "next" : "previous";
        el.append(op("×", `Merge with the ${other} one (removes the wall between)`, "merge"));
      }
    }
    if (key === focused) this.refocus = input;
    return el;
  }

  setSelected(svgPart: number | null) {
    this.selected = svgPart;
    this.applySelection();
  }

  /** Hides the given parts (indices of their `<g id="p-N">` in the SVG). */
  setHidden(svgParts: Iterable<number>) {
    this.hidden = new Set(svgParts);
    this.applyHidden();
  }

  resetCamera() {
    const bounds = new THREE.Box3().setFromObject(this.root);
    const size = bounds.getSize(new THREE.Vector3());
    this.fit(bounds.getCenter(new THREE.Vector3()), Math.max(size.x, size.y, size.z, 1));
  }

  private hasFit = false;
  private flat = false;

  private fit(center: THREE.Vector3, maxDim: number) {
    this.hasFit = true;
    this.resize();
    // Fit the bounding sphere into the narrower of the vertical and horizontal field of view.
    const vHalf = (this.camera.fov * Math.PI) / 360;
    const hHalf = Math.atan(Math.tan(vHalf) * this.camera.aspect);
    // Room for the dimension lines and their labels around the model.
    const radius = ((maxDim * Math.sqrt(3)) / 2) * (this.showDims ? 1.3 : 1);
    const dist = (radius / Math.sin(Math.min(vHalf, hHalf))) * 1.05;
    const dir = (this.flat ? new THREE.Vector3(0.25, -0.9, 2.2) : new THREE.Vector3(0.9, -1.6, 1.1)).normalize();
    this.camera.position.copy(center).addScaledVector(dir, dist);
    this.camera.near = dist / 100;
    this.camera.far = dist * 20;
    this.camera.updateProjectionMatrix();
    this.controls.target.copy(center);
    this.controls.update();
    this.needsRender = true;
  }

  private buildPart(part: RecordedPart, p: Placement, thickness: number): PartObject {
    const geometry = buildPartGeometry(part, p, thickness);
    const material = part.helper === "printed" ? this.printedMaterial : this.material;
    const mesh = new THREE.Mesh(geometry, material);
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 20), this.edgeMaterial);
    const group = new THREE.Group();
    group.add(mesh, edges);
    group.matrixAutoUpdate = false;
    const base = basis(p.origin, p.ux, p.uy, p.n);
    group.matrix.copy(base);
    group.userData.svgPart = part.part;
    this.root.add(group);
    this.root.updateMatrixWorld(true);
    return { svgPart: part.part, group, mesh, material, base, normal: new THREE.Vector3(...p.n), explodeDir: new THREE.Vector3() };
  }

  private applyExplode() {
    this.applyDimsVisible();
    for (const o of this.objects) {
      const offset = o.explodeDir.clone().multiplyScalar(this.explode * this.explodeDistance);
      o.group.matrix.copy(new THREE.Matrix4().makeTranslation(offset).multiply(o.base));
      o.group.matrixWorldNeedsUpdate = true;
    }
    this.needsRender = true;
  }

  private applySelection() {
    for (const o of this.objects) {
      o.mesh.material = o.svgPart === this.selected ? this.selectedMaterial : o.material;
    }
    this.needsRender = true;
  }

  private applyHidden() {
    for (const o of this.objects) o.group.visible = !this.hidden.has(o.svgPart);
    this.needsRender = true;
  }

  private clear() {
    for (const o of this.objects) {
      o.group.traverse((c) => {
        if (c instanceof THREE.Mesh || c instanceof THREE.LineSegments) c.geometry.dispose();
      });
      this.root.remove(o.group);
    }
    this.objects = [];
  }

  private resize() {
    const { clientWidth: w, clientHeight: h } = this.container;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.labels.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.needsRender = true;
  }

  /**
   * Click (not drag) on a part selects it; click on empty space clears the selection.
   * In edit mode a click toggles the handle under the pointer, which is highlighted on hover.
   */
  private installPicking() {
    const el = this.renderer.domElement;
    let down: { x: number; y: number } | null = null;
    const rayAt = (e: PointerEvent) => {
      const rect = el.getBoundingClientRect();
      const ndc = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
      const ray = new THREE.Raycaster();
      ray.setFromCamera(ndc, this.camera);
      return ray;
    };
    el.addEventListener("pointerdown", (e) => (down = { x: e.clientX, y: e.clientY }));
    // Captured on the container, so a drag on an inner wall starts before the orbit controls see it.
    this.container.addEventListener("pointerdown", (e) => {
      if (!this.editing || e.button !== 0 || e.target !== el) return;
      const ray = rayAt(e);
      const line = this.pickLine(ray);
      if (!line) return;
      this.startDrag(line, ray, e);
      el.setPointerCapture(e.pointerId);
    }, true);
    el.addEventListener("pointermove", (e) => {
      if (this.drag) {
        this.moveDrag(rayAt(e), e);
        return;
      }
      if (!this.editing || e.buttons) return;
      const ray = rayAt(e);
      const handle = this.pickHandle(ray);
      this.setHover(handle);
      el.style.cursor = this.pickLine(ray) ? "grab" : handle ? "pointer" : "";
    });
    el.addEventListener("pointerleave", () => this.drag || this.setHover(null));
    el.addEventListener("pointercancel", () => this.cancelDrag());
    window.addEventListener("keydown", (e) => e.key === "Escape" && this.cancelDrag());
    el.addEventListener("pointerup", (e) => {
      if (this.endDrag()) return;
      if (!down || Math.hypot(e.clientX - down.x, e.clientY - down.y) > CLICK_TOLERANCE_PX) return;
      const ray = rayAt(e);
      if (this.editing) {
        const handle = this.pickHandle(ray);
        if (handle) this.onHandle(handle);
        return;
      }
      const visible = this.objects.filter((o) => o.group.visible).map((o) => o.mesh);
      const hit = ray.intersectObjects(visible)[0];
      const svgPart = hit ? (hit.object.parent!.userData.svgPart as number) : null;
      this.setSelected(svgPart);
      this.onSelect(svgPart);
    });
  }
}

function formatMm(v: number): string {
  return String(Math.round(v * 100) / 100);
}

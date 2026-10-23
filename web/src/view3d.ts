import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { Placement, RecordedPart, Vec3 } from "./protocol";

const WOOD = 0xd9b382;
const WOOD_EDGE = 0x6b4f2e;
const SELECTED = 0xf97316;
const CLICK_TOLERANCE_PX = 4;

interface PartObject {
  svgPart: number;
  group: THREE.Group;
  mesh: THREE.Mesh;
  base: THREE.Matrix4;
  /** Unit direction the part moves in the exploded view. */
  explodeDir: THREE.Vector3;
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
  private selectedMaterial = new THREE.MeshStandardMaterial({ color: SELECTED, roughness: 0.7, side: THREE.DoubleSide });
  private edgeMaterial = new THREE.LineBasicMaterial({ color: WOOD_EDGE });
  private sun = new THREE.DirectionalLight(0xffffff, 2.2);
  private explode = 0;
  private explodeDistance = 0;
  private selected: number | null = null;
  private hidden = new Set<number>();
  private needsRender = true;

  constructor(
    private container: HTMLElement,
    private onSelect: (svgPart: number | null) => void,
  ) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(window.devicePixelRatio);
    container.append(this.renderer.domElement);

    this.camera.up.set(0, 0, 1);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.addEventListener("change", () => (this.needsRender = true));

    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x8d7c6a, 1.6));
    this.scene.add(this.sun, this.sun.target);
    this.scene.add(this.root);

    new ResizeObserver(() => this.resize()).observe(container);
    this.installPicking();
    this.renderer.setAnimationLoop(() => {
      if (this.controls.update() || this.needsRender) {
        this.needsRender = false;
        this.renderer.render(this.scene, this.camera);
      }
    });
  }

  /** Rebuilds the model. Keeps the camera unless `refit` (e.g. a different generator). */
  update(parts: RecordedPart[], placements: Map<number, Placement>, thickness: number, refit: boolean) {
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

  private fit(center: THREE.Vector3, maxDim: number) {
    this.hasFit = true;
    this.resize();
    // Fit the bounding sphere into the narrower of the vertical and horizontal field of view.
    const vHalf = (this.camera.fov * Math.PI) / 360;
    const hHalf = Math.atan(Math.tan(vHalf) * this.camera.aspect);
    const radius = (maxDim * Math.sqrt(3)) / 2;
    const dist = (radius / Math.sin(Math.min(vHalf, hHalf))) * 1.05;
    const dir = new THREE.Vector3(0.9, -1.6, 1.1).normalize();
    this.camera.position.copy(center).addScaledVector(dir, dist);
    this.camera.near = dist / 100;
    this.camera.far = dist * 20;
    this.camera.updateProjectionMatrix();
    this.controls.target.copy(center);
    this.controls.update();
    this.needsRender = true;
  }

  private buildPart(part: RecordedPart, p: Placement, thickness: number): PartObject {
    const { outer, holes } = part.outline!;
    const shape = new THREE.Shape(outer.map(([x, y]) => new THREE.Vector2(x, y)));
    shape.holes = holes.map((h) => new THREE.Path(h.map(([x, y]) => new THREE.Vector2(x, y))));
    const geometry = new THREE.ExtrudeGeometry(shape, { depth: thickness, bevelEnabled: false, curveSegments: 1 });

    const mesh = new THREE.Mesh(geometry, this.material);
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 20), this.edgeMaterial);
    const group = new THREE.Group();
    group.add(mesh, edges);
    group.matrixAutoUpdate = false;
    const base = basis(p.origin, p.ux, p.uy, p.n);
    group.matrix.copy(base);
    group.userData.svgPart = part.part;
    this.root.add(group);
    this.root.updateMatrixWorld(true);
    return { svgPart: part.part, group, mesh, base, explodeDir: new THREE.Vector3() };
  }

  private applyExplode() {
    for (const o of this.objects) {
      const offset = o.explodeDir.clone().multiplyScalar(this.explode * this.explodeDistance);
      o.group.matrix.copy(new THREE.Matrix4().makeTranslation(offset).multiply(o.base));
      o.group.matrixWorldNeedsUpdate = true;
    }
    this.needsRender = true;
  }

  private applySelection() {
    for (const o of this.objects) {
      o.mesh.material = o.svgPart === this.selected ? this.selectedMaterial : this.material;
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
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.needsRender = true;
  }

  /** Click (not drag) on a part selects it; click on empty space clears the selection. */
  private installPicking() {
    const el = this.renderer.domElement;
    let down: { x: number; y: number } | null = null;
    el.addEventListener("pointerdown", (e) => (down = { x: e.clientX, y: e.clientY }));
    el.addEventListener("pointerup", (e) => {
      if (!down || Math.hypot(e.clientX - down.x, e.clientY - down.y) > CLICK_TOLERANCE_PX) return;
      const rect = el.getBoundingClientRect();
      const ndc = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
      const ray = new THREE.Raycaster();
      ray.setFromCamera(ndc, this.camera);
      const visible = this.objects.filter((o) => o.group.visible).map((o) => o.mesh);
      const hit = ray.intersectObjects(visible)[0];
      const svgPart = hit ? (hit.object.parent!.userData.svgPart as number) : null;
      this.setSelected(svgPart);
      this.onSelect(svgPart);
    });
  }
}

/** Matrix with columns ux, uy, n and translation origin (may be a reflection). */
function basis(origin: Vec3, ux: Vec3, uy: Vec3, n: Vec3): THREE.Matrix4 {
  return new THREE.Matrix4().set(
    ux[0], uy[0], n[0], origin[0],
    ux[1], uy[1], n[1], origin[1],
    ux[2], uy[2], n[2], origin[2],
    0, 0, 0, 1,
  );
}

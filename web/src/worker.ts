/// <reference lib="webworker" />
import type { PyodideAPI } from "pyodide";
import type { FromWorker, ToWorker } from "./protocol";
// The bridge and the placement modules, written next to each other into the Pyodide FS.
const pySources = import.meta.glob("./py/*.py", { query: "?raw", import: "default", eager: true }) as Record<
  string,
  string
>;

const PYODIDE_VERSION = "314.0.7";
const PYODIDE_URL = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;
// Prebuilt in Pyodide; qrcode comes from PyPI. svgmerge-only deps (rectpack, svgpathtools) are not needed.
const PYODIDE_PACKAGES = ["micropip", "affine", "shapely", "numpy", "typing-extensions"];

interface Bridge {
  list_generators(): string;
  get_schema(name: string): string;
  render_with_parts(name: string, argsJson: string): string;
}

let bridge: Bridge | null = null;

function post(msg: FromWorker) {
  self.postMessage(msg);
}

async function init(wheelBase: string) {
  const t0 = performance.now();
  post({ type: "status", text: "Loading Python runtime…" });
  const { loadPyodide } = (await import(/* @vite-ignore */ `${PYODIDE_URL}pyodide.mjs`)) as {
    loadPyodide: (opts: { indexURL: string }) => Promise<PyodideAPI>;
  };
  const py = await loadPyodide({ indexURL: PYODIDE_URL });

  post({ type: "status", text: "Loading packages…" });
  await py.loadPackage(PYODIDE_PACKAGES);

  post({ type: "status", text: "Installing boxes…" });
  const manifest = (await (await fetch(`${wheelBase}manifest.json`, { cache: "no-cache" })).json()) as {
    wheel: string;
  };
  const wheel = await fetch(`${wheelBase}${manifest.wheel}`, { cache: "no-cache" });
  if (!wheel.ok) throw new Error(`Could not fetch ${manifest.wheel}: ${wheel.status}`);
  py.FS.writeFile(`/tmp/${manifest.wheel}`, new Uint8Array(await wheel.arrayBuffer()));
  await py.runPythonAsync(`
import micropip
await micropip.install("qrcode")
await micropip.install("emfs:/tmp/${manifest.wheel}", deps=False)
`);

  post({ type: "status", text: "Loading generators…" });
  for (const [path, source] of Object.entries(pySources)) {
    py.FS.writeFile(`/home/pyodide/${path.split("/").pop()}`, source);
  }
  bridge = py.pyimport("boxes_bridge") as unknown as Bridge;

  const { groups, generators } = JSON.parse(bridge.list_generators());
  post({ type: "ready", groups, generators, loadMs: performance.now() - t0 });
}

function errorMessage(e: unknown): { message: string; detail: string } {
  const detail = e instanceof Error ? e.message : String(e);
  // Python tracebacks end with "ExceptionType: message".
  const last = detail.trim().split("\n").pop() ?? detail;
  const message = last.replace(/^(\w+\.)*(ArgumentParserError|ValueError): /, "");
  return { message, detail };
}

self.onmessage = async (ev: MessageEvent<ToWorker>) => {
  const msg = ev.data;
  try {
    if (msg.type === "init") {
      await init(msg.wheelBase);
      return;
    }
    if (!bridge) throw new Error("Worker not initialised");
    if (msg.type === "schema") {
      post({ type: "schema", id: msg.id, schema: JSON.parse(bridge.get_schema(msg.generator)) });
    } else if (msg.type === "render") {
      const t = performance.now();
      const { svg, parts, assembly, dims, handles, lines, thickness } = JSON.parse(
        bridge.render_with_parts(msg.generator, JSON.stringify(msg.args)),
      );
      post({ type: "rendered", id: msg.id, svg, parts, assembly, dims, handles, lines, thickness, ms: performance.now() - t });
    }
  } catch (e) {
    post({ type: "error", id: "id" in msg ? msg.id : null, ...errorMessage(e) });
  }
};

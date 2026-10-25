import { readFileSync } from "node:fs";
import { defineConfig, type Plugin } from "vite";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

// The one place the Pyodide version is set: package.json (devDependency "pyodide", copied to
// public/pyodide/ by scripts/copy-pyodide.mjs). The worker loads packages for that version.
const pyodide = JSON.parse(read("node_modules/pyodide/package.json"));

/** dist/THIRD_PARTY_LICENSES.txt: the bundle drops the notices from three.js's source. */
function licenses(): Plugin {
  return {
    name: "third-party-licenses",
    apply: "build",
    generateBundle() {
      const source = [
        "Boxes.py Live bundles or serves the following third-party software.",
        "",
        "== three.js (bundled in assets/) ==",
        "https://github.com/mrdoob/three.js",
        "",
        read("node_modules/three/LICENSE").trim(),
        "",
        `== Pyodide ${pyodide.version} (served unchanged from pyodide/) ==`,
        "https://github.com/pyodide/pyodide",
        "Mozilla Public License 2.0: https://www.mozilla.org/MPL/2.0/",
        "Source: https://github.com/pyodide/pyodide/tree/" + pyodide.version,
        "",
        "Python packages (numpy, shapely, affine, typing-extensions, micropip, qrcode) are",
        "downloaded by the browser at runtime from jsDelivr and PyPI under their own licences.",
        "",
        "Boxes.py itself (wheels/) is GPL-3.0-or-later: https://github.com/florianfesti/boxes",
        "",
      ].join("\n");
      this.emitFile({ type: "asset", fileName: "THIRD_PARTY_LICENSES.txt", source });
    },
  };
}

export default defineConfig({
  // Relative base so the build works from any static host path (e.g. GitHub Pages).
  base: "./",
  worker: { format: "es" },
  define: { __PYODIDE_VERSION__: JSON.stringify(pyodide.version) },
  plugins: [licenses()],
});

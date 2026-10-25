// Copies the Pyodide core (runtime, standard library, lock file) from node_modules/pyodide into
// public/pyodide/, so the app serves it itself. Packages (numpy, shapely, ...) still come from
// the CDN, but Pyodide checks each one against the sha256 in this lock file.
import { copyFileSync, mkdirSync, rmSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const web = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const src = resolve(web, "node_modules", "pyodide");
const out = resolve(web, "public", "pyodide");
const files = ["pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"];

rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });
for (const f of files) copyFileSync(resolve(src, f), resolve(out, f));
console.log(`Copied Pyodide core to public/pyodide/`);

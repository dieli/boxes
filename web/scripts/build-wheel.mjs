// Builds the boxes package (repo root) into public/wheels/ and writes a manifest
// the worker reads to find the current wheel file.
import { execFileSync } from "node:child_process";
import { mkdirSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const web = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repo = resolve(web, "..");
const out = resolve(web, "public", "wheels");

rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });

const attempts = [
  ["uv", ["build", "-q", "--wheel", "--out-dir", out, repo]],
  [process.platform === "win32" ? "py" : "python3", ["-m", "pip", "wheel", "--no-deps", "-w", out, repo]],
];
let built = false;
for (const [cmd, args] of attempts) {
  try {
    execFileSync(cmd, args, { cwd: repo, stdio: ["ignore", "ignore", "inherit"] });
    built = true;
    break;
  } catch (e) {
    console.warn(`${cmd} failed: ${e.message}`);
  }
}
if (!built) process.exit(1);

const wheel = readdirSync(out).find((f) => /^boxes-.*-py3-none-any\.whl$/.test(f));
if (!wheel) {
  console.error("No pure-Python boxes wheel was produced");
  process.exit(1);
}
writeFileSync(resolve(out, "manifest.json"), JSON.stringify({ wheel }) + "\n");
console.log(`Built ${wheel}`);

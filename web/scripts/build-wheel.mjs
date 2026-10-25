// Builds the boxes package (repo root) into public/wheels/<hash>/ and writes a manifest the
// worker reads to find the current wheel file.
//
// The wheel is written directly instead of through setup.py: setup.py's build_py also
// regenerates po/boxes.py.pot, the locale .mo files and the Inkscape extension, which would
// change the working tree (and adds 1 MB of translations the browser never uses). Only the
// package's Python files go in: those git tracks or would track (not ignored), as they are in
// the working tree. The folder name is a hash of the wheel, so it can be cached for good.
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { crc32, deflateRawSync } from "node:zlib";

const web = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repo = resolve(web, "..");
const out = resolve(web, "public", "wheels");

const version = /^version\s*=\s*"([^"]+)"/m.exec(readFileSync(resolve(repo, "pyproject.toml"), "utf8"))?.[1];
if (!version) {
  console.error("No version in pyproject.toml");
  process.exit(1);
}

const files = execFileSync("git", ["ls-files", "--cached", "--others", "--exclude-standard", "-z", "boxes"], {
  cwd: repo,
  encoding: "utf8",
})
  .split("\0")
  .filter((f) => f.endsWith(".py"))
  .filter((f) => {
    try {
      readFileSync(resolve(repo, f));
      return true;
    } catch {
      return false; // deleted in the working tree
    }
  })
  .sort();
if (!files.some((f) => f === "boxes/__init__.py")) {
  console.error("boxes/__init__.py not found");
  process.exit(1);
}

const distInfo = `boxes-${version}.dist-info`;
const entries = files.map((f) => [f, readFileSync(resolve(repo, f))]);
const text = (s) => Buffer.from(s, "utf8");
entries.push(
  [
    `${distInfo}/METADATA`,
    text(
      `Metadata-Version: 2.1\nName: boxes\nVersion: ${version}\n` +
        "Summary: Boxes generator for laser cutters\nLicense: GPL-3.0-or-later\n",
    ),
  ],
  [`${distInfo}/WHEEL`, text("Wheel-Version: 1.0\nGenerator: boxes-live build-wheel.mjs\nRoot-Is-Purelib: true\nTag: py3-none-any\n")],
  [`${distInfo}/top_level.txt`, text("boxes\n")],
);
const digest = (data) => createHash("sha256").update(data).digest("base64url");
const record = entries.map(([name, data]) => `${name},sha256=${digest(data)},${data.length}`);
record.push(`${distInfo}/RECORD,,`);
entries.push([`${distInfo}/RECORD`, text(record.join("\n") + "\n")]);

const wheel = zip(entries);
const hash = createHash("sha256").update(wheel).digest("hex").slice(0, 12);
const name = `boxes-${version}-py3-none-any.whl`;

rmSync(out, { recursive: true, force: true });
mkdirSync(resolve(out, hash), { recursive: true });
writeFileSync(resolve(out, hash, name), wheel);
writeFileSync(resolve(out, "manifest.json"), JSON.stringify({ wheel: `${hash}/${name}` }) + "\n");
console.log(`Built ${hash}/${name} (${files.length} files)`);

/** Deflated ZIP with a fixed date (1980-01-01), so equal input gives an equal wheel. */
function zip(entries) {
  const local = [];
  const central = [];
  let offset = 0;
  for (const [name, data] of entries) {
    const nameBuf = text(name);
    const packed = deflateRawSync(data, { level: 9 });
    const crc = crc32(data);
    const header = Buffer.alloc(30);
    header.writeUInt32LE(0x04034b50, 0);
    header.writeUInt16LE(20, 4); // version needed
    header.writeUInt16LE(0x0800, 6); // UTF-8 names
    header.writeUInt16LE(8, 8); // deflate
    header.writeUInt16LE(0, 10); // time 00:00
    header.writeUInt16LE(0x21, 12); // date 1980-01-01
    header.writeUInt32LE(crc, 14);
    header.writeUInt32LE(packed.length, 18);
    header.writeUInt32LE(data.length, 22);
    header.writeUInt16LE(nameBuf.length, 26);
    const dir = Buffer.alloc(46);
    dir.writeUInt32LE(0x02014b50, 0);
    dir.writeUInt16LE(0x0314, 4); // made by: Unix, 2.0
    header.copy(dir, 6, 4, 30); // version needed .. name length
    dir.writeUInt32LE((0o100644 << 16) >>> 0, 38); // -rw-r--r--
    dir.writeUInt32LE(offset, 42);
    local.push(header, nameBuf, packed);
    central.push(dir, nameBuf);
    offset += header.length + nameBuf.length + packed.length;
  }
  const size = central.reduce((n, b) => n + b.length, 0);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(entries.length, 8);
  end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(size, 12);
  end.writeUInt32LE(offset, 16);
  return Buffer.concat([...local, ...central, end]);
}

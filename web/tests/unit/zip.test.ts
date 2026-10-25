import { describe, expect, test } from "vitest";
import { safeName } from "../../src/names";
import { zipStore } from "../../src/zip";

/** Reads the entries back from the central directory of a stored (uncompressed) ZIP. */
function readZip(buf: ArrayBuffer) {
  const v = new DataView(buf);
  const end = buf.byteLength - 22;
  expect(v.getUint32(end, true)).toBe(0x06054b50);
  const count = v.getUint16(end + 10, true);
  let p = v.getUint32(end + 16, true);
  const dec = new TextDecoder();
  const out = [];
  for (let i = 0; i < count; i++) {
    expect(v.getUint32(p, true)).toBe(0x02014b50);
    const crc = v.getUint32(p + 16, true);
    const size = v.getUint32(p + 24, true);
    const nameLen = v.getUint16(p + 28, true);
    const local = v.getUint32(p + 42, true);
    const name = dec.decode(new Uint8Array(buf, p + 46, nameLen));
    expect(v.getUint32(local, true)).toBe(0x04034b50);
    // A valid DOS date (1980-01-01) in both headers, not 0.
    expect(v.getUint16(p + 14, true)).toBe(0x21);
    expect(v.getUint16(local + 12, true)).toBe(0x21);
    const dataStart = local + 30 + v.getUint16(local + 26, true);
    out.push({ name, crc, data: dec.decode(new Uint8Array(buf, dataStart, size)) });
    p += 46 + nameLen;
  }
  return out;
}

describe("zipStore", () => {
  test("entries, names (UTF-8) and CRC-32 read back", async () => {
    const enc = new TextEncoder();
    const zip = zipStore([
      { name: "hello.txt", data: enc.encode("hello") },
      { name: "wänd.svg", data: enc.encode("<svg/>") },
      { name: "empty", data: new Uint8Array(0) },
    ]);
    expect(zip.type).toBe("application/zip");
    const entries = readZip(await zip.arrayBuffer());
    expect(entries.map((e) => e.name)).toEqual(["hello.txt", "wänd.svg", "empty"]);
    expect(entries[0].crc).toBe(0x3610a686); // crc32("hello")
    expect(entries[1].data).toBe("<svg/>");
    expect(entries[2].crc).toBe(0);
  });

  test("an empty archive is just the end record", async () => {
    expect((await zipStore([]).arrayBuffer()).byteLength).toBe(22);
  });
});

describe("safeName", () => {
  test.each([
    ["left wall", "left_wall"],
    ["  #3 (50x40) ", "3_50x40"],
    ["../etc/passwd", ".._etc_passwd"], // no path separators left
    ["***", "part"],
    ["card ramp.1-a", "card_ramp.1-a"],
  ])("%s", (s, expected) => expect(safeName(s)).toBe(expected));
});

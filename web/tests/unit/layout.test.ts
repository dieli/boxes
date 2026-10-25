import { describe, expect, test } from "vitest";
import {
  defaultLayout,
  formatLayout,
  mergeLayout,
  mergePair,
  mergeSizes,
  parseLayout,
  parseSections,
  setLayoutSize,
  splitLayout,
  splitSizes,
  toggleLayout,
} from "../../src/layout";

describe("parseSections", () => {
  test.each([
    ["50*3", [50, 50, 50]],
    ["100/2:30", [50, 50, 30]],
    ["20:30:40", [20, 30, 40]],
    ["50", [50]],
    ["50:abc:0:-5", [50]],
  ])("%s", (s, expected) => expect(parseSections(s)).toEqual(expected));
});

describe("parseLayout / formatLayout", () => {
  const text = defaultLayout("50*2:30", "40:60");

  test("default layout round trip", () => {
    const l = parseLayout(text);
    expect(l).not.toBeNull();
    expect(l!.x).toEqual([50, 50, 30]);
    expect(l!.y).toEqual([40, 60]);
    expect(l!.hwalls).toEqual([[true, true, true], [true, true, true], [true, true, true]]);
    expect(l!.vwalls).toEqual([[true, true, true, true], [true, true, true, true]]);
    expect(l!.floors).toEqual([[true, true, true], [true, true, true]]);
    expect(formatLayout(l!)).toBe(text);
  });

  test("comments, missing walls and floors survive a round trip", () => {
    let t: string | null = text;
    t = toggleLayout(t, "hwall", 1, 1);
    t = toggleLayout(t!, "vwall", 2, 0);
    t = toggleLayout(t!, "floor", 0, 1);
    const withComment = "# my tray\n" + t;
    const l = parseLayout(withComment)!;
    expect(l.comments).toEqual(["# my tray"]);
    expect(l.hwalls[1]).toEqual([true, false, true]);
    expect(l.vwalls[0]).toEqual([true, true, false, true]);
    expect(l.floors[1]).toEqual([false, true, true]);
    expect(formatLayout(l)).toBe(withComment);
  });

  test("incomplete grids are rejected", () => {
    expect(parseLayout("")).toBeNull();
    expect(parseLayout(text.split("\n").slice(0, -2).join("\n"))).toBeNull(); // last wall line missing
    expect(parseLayout(text.replace("40mm", "fortymm"))).toBeNull();
  });

  test("defaultLayout of empty sizes", () => expect(defaultLayout("", "50")).toBe(""));
});

describe("setLayoutSize", () => {
  const text = defaultLayout("50*2", "40:60");

  test("sets one column or row, leaves the rest", () => {
    expect(parseLayout(setLayoutSize(text, "x", 1, 33.333)!)!.x).toEqual([50, 33.33]);
    expect(parseLayout(setLayoutSize(text, "y", 0, 25)!)!.y).toEqual([25, 60]);
  });

  test("null for a missing index", () => {
    expect(setLayoutSize(text, "x", 2, 10)).toBeNull();
    expect(setLayoutSize(text, "y", 2, 10)).toBeNull();
  });
});

describe("toggleLayout", () => {
  const text = defaultLayout("50*2", "40:60");

  test.each([
    ["hwall", 0, 0],
    ["hwall", 1, 2],
    ["vwall", 0, 0],
    ["vwall", 2, 1],
    ["floor", 1, 1],
  ] as const)("%s %i,%i twice gives the original", (kind, i, j) => {
    const once = toggleLayout(text, kind, i, j);
    expect(once).not.toBeNull();
    expect(once).not.toBe(text);
    expect(toggleLayout(once!, kind, i, j)).toBe(text);
  });

  test("null outside the grid", () => {
    expect(toggleLayout(text, "hwall", 0, 3)).toBeNull();
    expect(toggleLayout(text, "floor", 0, 2)).toBeNull();
    expect(toggleLayout(text, "hwall", 5, 0)).toBeNull();
  });
});

describe("splitSizes / mergeSizes / mergePair", () => {
  test("split keeps the total including the new wall", () => {
    const s = splitSizes([60, 40], 0, 3)!;
    expect(s).toEqual([28.5, 28.5, 40]);
    expect(s.reduce((a, b) => a + b) + 3).toBe(100);
  });

  test("outside measurements: no wall to subtract", () => expect(splitSizes([60], 0, 0)).toEqual([30, 30]));
  test("too small", () => expect(splitSizes([4, 40], 0, 3)).toBeNull());
  test("merge undoes split", () => expect(mergeSizes([28.5, 28.5, 40], 0, 3)).toEqual([60, 40]));

  test("mergePair: next one, or the previous one for the last", () => {
    expect(mergePair(0, 3)).toBe(0);
    expect(mergePair(1, 3)).toBe(1);
    expect(mergePair(2, 3)).toBe(1);
  });
});

describe("splitLayout / mergeLayout", () => {
  const text = defaultLayout("50*3", "40*3");
  const t = 3;

  for (const axis of ["x", "y"] as const) {
    for (const k of [0, 1, 2]) {
      test(`${axis} split at ${k}, then merge back`, () => {
        const sizes = parseLayout(text)![axis];
        const split = splitSizes(sizes, k, t)!;
        const s = splitLayout(text, axis, k, split)!;
        const l = parseLayout(s)!;
        expect(l[axis]).toEqual(split);
        expect(l.x.length * l.y.length).toBe(12);
        expect(mergeLayout(s, axis, k, mergeSizes(split, k, t))).toBe(text);
      });
    }
  }

  test("a split column copies walls and floors of the original", () => {
    let s = toggleLayout(text, "floor", 2, 1)!;
    s = toggleLayout(s, "hwall", 2, 1)!;
    const l = parseLayout(splitLayout(s, "x", 2, [50, 50, 23.5, 23.5])!)!;
    expect(l.floors[1]).toEqual([true, true, false, false]);
    expect(l.hwalls[1]).toEqual([true, true, false, false]);
    expect(l.vwalls[1]).toEqual([true, true, true, true, true]); // full wall between the halves
  });

  test("merging keeps a wall or floor if either side had it", () => {
    const s = toggleLayout(text, "floor", 0, 0)!;
    const l = parseLayout(mergeLayout(s, "x", 0, [103, 50])!)!;
    expect(l.floors[0]).toEqual([true, true]);
    expect(l.vwalls[0]).toEqual([true, true, true]);
  });

  test("null for an invalid layout", () => {
    expect(splitLayout("nonsense", "x", 0, [1])).toBeNull();
    expect(mergeLayout("nonsense", "y", 0, [1])).toBeNull();
  });
});

"""Checks the 3D placements: do finger joints close, and do parts not cut into each other?

For every placed part and every finger-type edge, points are sampled in the strip just
outside the part's inner rectangle (where its fingers and the gaps between them are),
at mid thickness:
  - gap points (not in the part) should be filled by another part  -> "fill"
  - finger points (in the part) should not be inside another part   -> "overlap"
Additionally a coarse grid over each part checks for parts cutting into each other.

Run from the repo root (CPython, needs numpy and shapely):
    uv run --no-project --with affine --with shapely --with qrcode --with typing_extensions \
        --with numpy python web/scripts/check_assembly.py [Generator ...]
"""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "web" / "src" / "py")]

import numpy as np  # noqa: E402
from shapely import Polygon, contains_xy  # noqa: E402

import boxes_bridge  # noqa: E402
from placements import PLACEMENTS  # noqa: E402

# Extra argument sets per generator (defaults are always checked).
CASES: dict[str, list[dict]] = {
    "ABox": [{"bottom_edge": "F"}, {"Lid_style": "flat"}, {"Lid_style": "flatbrim"},
             {"Lid_style": "overthetop"}, {"Lid_style": "ontop"}, {"x": "150", "y": "80"}],
    "UniversalBox": [{"top_edge": "f"}, {"top_edge": "F"}, {"top_edge": "E"},
                     {"vertical_edges": "finger holes"}, {"bottom_edge": "h"},
                     {"Lid_style": "flatfang"}, {"Lid_style": "overthetop"}],
    "TypeTray": [{"sx": "30:50:70", "sy": "20:60"}, {"top_edge": "f"}, {"bottom_edge": "e"}],
    "ClosedBox": [{"x": "60", "y": "120", "h": "40"}],
    "CardBox": [{"openingdirection": "right"}, {"sx": "40:65", "add_lidtopper": "1"}],
    "DiceBox": [{"lidheight": "25"}],
}

FILL_MIN = 0.9
OVERLAP_MAX = 0.05
FINGER_EDGES = set("fFhH")


class Solid:
    def __init__(self, rec: dict, t: float) -> None:
        o = rec["outline"]
        self.rec = rec
        self.name = rec["label"] or f"#{rec['part']} ({rec['x']:g}x{rec['y']:g})"
        self.poly = Polygon(o["outer"], o["holes"])
        p = rec["place"]
        self.o = np.array(p["origin"], float)
        self.R = np.column_stack([p["ux"], p["uy"], p["n"]]).astype(float)
        self.Rinv = np.linalg.inv(self.R)
        self.t = t

    def world(self, x, y, z):
        return self.o + np.column_stack([x, y, z]) @ self.R.T

    def contains(self, w) -> np.ndarray:
        local = (w - self.o) @ self.Rinv.T
        eps = 0.05 * self.t
        inz = (local[:, 2] > eps) & (local[:, 2] < self.t - eps)
        return inz & contains_xy(self.poly, local[:, 0], local[:, 1])


def edge_band(s: Solid, i: int, step: float = 0.25):
    """Local sample points in the strip of width t outside edge i (corners excluded)."""
    px, py, t = s.rec["x"], s.rec["y"], s.t
    length = px if i % 2 == 0 else py
    # Corners are trimmed by ignore_widths etc.; half-step phase keeps samples off finger boundaries.
    along = np.arange(2 * t + step / 2, length - 2 * t, step)
    if along.size == 0:
        return None
    d = np.array([0.2, 0.5, 0.8]) * t
    a, dd = np.meshgrid(along, d)
    a, dd = a.ravel(), dd.ravel()
    x, y = {0: (a, -dd), 1: (px + dd, a), 2: (a, py + dd), 3: (-dd, a)}[i]
    return x, y


def check(name: str, args: dict) -> list[str]:
    with contextlib.redirect_stdout(io.StringIO()):
        r = json.loads(boxes_bridge.render_with_parts(name, json.dumps({"burn": "0", **args})))
    problems = []
    if r["assembly"] is not True:
        return [f"assembly: {r['assembly']}"]
    t = r["thickness"]
    unplaced = [p["label"] or f"#{p['part']}" for p in r["parts"] if not p["place"]]
    if unplaced:
        problems.append(f"unplaced (2D only): {', '.join(unplaced)}")
    solids = [Solid(p, t) for p in r["parts"] if p["place"] and p["outline"]]
    for a in solids:
        others = [b for b in solids if b is not a]

        def hit(w):
            return np.any([b.contains(w) for b in others], axis=0) if others else np.zeros(len(w), bool)

        for i, e in enumerate(a.rec["edges"]):
            if e["char"] not in FINGER_EDGES:
                continue
            band = edge_band(a, i)
            if band is None:
                continue
            x, y = band
            ina = contains_xy(a.poly, x, y)
            filled = hit(a.world(x, y, np.full_like(x, t / 2)))
            gaps, fingers = ~ina, ina
            fill = filled[gaps].mean() if gaps.any() else 1.0
            overlap = filled[fingers].mean() if fingers.any() else 0.0
            if fill < FILL_MIN or overlap > OVERLAP_MAX:
                problems.append(f"{a.name} edge {i} '{e['char']}': fill {fill:.0%}, overlap {overlap:.0%}")
        # Coarse body check: parts cutting into each other.
        minx, miny, maxx, maxy = a.poly.bounds
        step = max(1.0, min(maxx - minx, maxy - miny) / 25)
        gx, gy = np.meshgrid(np.arange(minx, maxx, step), np.arange(miny, maxy, step))
        gx, gy = gx.ravel(), gy.ravel()
        keep = contains_xy(a.poly, gx, gy)
        w = a.world(gx[keep], gy[keep], np.full(keep.sum(), t / 2))
        for b in others:
            frac = b.contains(w).mean() if len(w) else 0.0
            if frac > 0.01 and a.name <= b.name:
                problems.append(f"{a.name} cuts into {b.name}: {frac:.0%} of its area")
    return problems


def main(names: list[str]) -> int:
    failed = 0
    for name in names or sorted(PLACEMENTS):
        for args in [{}] + CASES.get(name, []):
            problems = check(name, args)
            hard = [p for p in problems if not p.startswith("unplaced")]
            failed += bool(hard)
            print(f"{'FAIL' if hard else 'ok  '} {name} {args or ''}")
            for p in problems:
                print(f"       {p}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

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
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "web" / "src" / "py")]

import numpy as np  # noqa: E402
from shapely import Polygon, contains_xy  # noqa: E402

import boxes_bridge  # noqa: E402
from assembly import Part  # noqa: E402
from placements import PLACEMENTS  # noqa: E402

# Extra argument sets per generator (defaults are always checked).
CASES: dict[str, list[dict]] = {
    "TwoPiece": [{"hi": "30"}, {"outside": "1"}, {"play": "0.3"}],
    "SlidingDrawer": [{"hi": "20"}, {"outside": "1"}, {"play": "0.3"}],
    "PenHolderBox": [{"bottom_edge": "h"}, {"plate_gap": "40"}],
    "ElectronicsBox": [{"outsidemounts": "0"}, {"outside": "1"}],
    "DisplayCase": [{"overhang": "5"}, {"outside": "1"}],
    "StorageRack": [{"sh": "40:60:30"}, {"bottom_edge": "e"}, {"top_edge": "e"},
                    {"top_edge": "h"}],
    "SlantedTray": [{"sx": "30:50:20"}, {"front_height": "0.6"}],
    "OpenBox": [{"edgetype": "h"}, {"outside": "1"}],
    "UnevenHeightBox": [{"height0": "30", "height1": "60", "height2": "90", "height3": "40"},
                        {"add_lid": "0"}, {"lid_height": "10"}, {"bottom_edge": "h"}],
    "SlidingLidBox": [{"lid_type": "lip"}, {"lid_type": "none"}, {"bottom_edge": "h"},
                      {"outside": "1"}],
    "WallRack": [{"sh": "80:120"}, {"side_edges": "h"}, {"outside": "1"}, {"top_edge": "E"}],
    "CompartmentBox": [{"sx": "30:50:20", "sy": "20:40"}, {"handle": "hole"}, {"handle": "none"},
                       {"bottom_edge": "F"}],
    "WallHopper": [{"sx": "40:80:30"}, {"label": "0"}, {"slope_angle": "10", "h": "120"}],
    "WallConsole": [{"sx": "40:80:30"}, {"top_depth": "30", "bottom_depth": "60"},
                    {"walltype": "slatwall"}],
    "WallWrenchHolder": [{"x": "150", "depth": "50"}],
    "WallPlaneHolder": [{"length": "200", "hold_length": "50"}],
    "WallTypeTray": [{"sx": "30:50", "sy": "20:40:30"}, {"back_height": "30"},
                     {"back_height": "30", "all_mounts": "1"}, {"hi": "30"},
                     {"walltype": "french cleat"}],
    "StorageShelf": [{"sy": "30:50", "sh": "40:60:30"}, {"bottom_edge": "F", "top_edge": "f"},
                     {"retainer": "15", "sh": "40:60"}, {"top_edge": "E"}],
    "Shadowbox": [{"layers": "3"}, {"back_edge": "f"}, {"back_edge": "E"}, {"back_edge": "h"},
                  {"casejoinery": "0"}],
    "ABox": [{"bottom_edge": "F"}, {"Lid_style": "flat"}, {"Lid_style": "flatbrim"},
             {"Lid_style": "overthetop"}, {"Lid_style": "ontop"}, {"x": "150", "y": "80"}],
    "UniversalBox": [{"top_edge": "f"}, {"top_edge": "F"}, {"top_edge": "E"},
                     {"top_edge": "L"}, {"top_edge": "i"}, {"top_edge": "k"}, {"top_edge": "v"},
                     {"vertical_edges": "finger holes"}, {"bottom_edge": "h"},
                     {"Lid_style": "flatfang"}, {"Lid_style": "overthetop"}],
    "TypeTray": [{"sx": "30:50:70", "sy": "20:60"}, {"top_edge": "f"}, {"bottom_edge": "e"}],
    "ClosedBox": [{"x": "60", "y": "120", "h": "40"}],
    "CardBox": [{"openingdirection": "right"}, {"sx": "40:65", "add_lidtopper": "1"}],
    "DiceBox": [{"lidheight": "25"}],
    "BasedBox": [{"top_edge": "f"}, {"top_edge": "E"}, {"Lid_style": "overthetop"}],
    "DrillBox": [{"bottom_edge": "F"}, {"sh": "5:25:10:20"}, {"Lid_style": "flat"}],
    "GridfinityDrillBox": [{"sh": "5:10:30"}, {"Lid_style": "ontop"}],
    "BeeQueenTransportBox": [{"bottom_edge": "F"}, {"sh": "12:30:40"}],
}

FILL_MIN = 0.9
OVERLAP_MAX = 0.05
FINGER_EDGES = set("fFhH")
# Wall mount joints (b/B fingers, c/C slots) are plain finger joints with the plain wall type.
WALL_EDGES = set("bBcC")


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


def segments(rec: dict) -> list[tuple[np.ndarray, np.ndarray, float]]:
    """(start, direction, length) of each edge, counter-clockwise, in local coordinates."""
    return [(np.array(p0), np.array(d), length) for p0, d, length in Part(0, rec).segments()]


def edge_band(s: Solid, i: int, step: float = 0.25):
    """Local sample points in the joint strip of width t along edge i (corners excluded)."""
    t = s.t
    segs = segments(s.rec)
    if i >= len(segs):
        return None
    p0, d, length = segs[i]
    # Corners are trimmed by ignore_widths etc.; half-step phase keeps samples off finger boundaries.
    along = np.arange(2 * t + step / 2, length - 2 * t, step)
    if along.size == 0:
        return None
    ccw = sum(q[0] * dq[1] * l - q[1] * dq[0] * l for q, dq, l in segs) > 0  # shoelace
    out = np.array([d[1], -d[0]]) * (1 if ccw else -1)
    dist = np.array([0.2, 0.5, 0.8]) * t
    if s.rec["helper"] == "polygonWall":
        # Edges are drawn right on the polygon line (not startWidth outside it like in
        # rectangularWall): F slots go inwards, f fingers outwards.
        dist = dist - s.rec["edges"][i]["startWidth"]
    a, dd = np.meshgrid(along, dist)
    pts = p0 + np.outer(a.ravel(), d) + np.outer(dd.ravel(), out)
    return pts[:, 0], pts[:, 1]


def check(name: str, args: dict) -> list[str]:
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            r = json.loads(boxes_bridge.render_with_parts(name, json.dumps({"burn": "0", **args})))
    except Exception as e:
        return [f"render failed: {type(e).__name__}: {str(e).splitlines()[-1] if str(e) else ''}"]
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
            # Composite edges (slotted, compound, ...): only check that nothing cuts in.
            composite = e["char"] is None
            if not composite and e["char"] not in FINGER_EDGES and not (
                    e["char"] in WALL_EDGES and args.get("walltype", "plain") == "plain"):
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
            if composite:
                fill = 1.0
            if fill < FILL_MIN or overlap > OVERLAP_MAX:
                problems.append(f"{a.name} edge {i} '{e['char'] or '?'}': fill {fill:.0%}, overlap {overlap:.0%}")
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

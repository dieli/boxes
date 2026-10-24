"""Checks the 3D placements: do finger joints close, and do parts not cut into each other?

For every placed part and every finger-type edge, points are sampled in the strip just
outside the part's inner rectangle (where its fingers and the gaps between them are),
at mid thickness:
  - gap points (not in the part) should be filled by another part  -> "fill"
  - finger points (in the part) should not be inside another part   -> "overlap"
Finger holes (holes about t wide) must be filled by another part as well, which also covers
parts drawn by hand without edge info ("free" parts).
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
# Walls removed (a T crossing, an open side) and a compartment without floor.
_LAYOUT = """ ,> 40mm
 | ,> 60mm
 | | ,> 30mm
+-+-+-+
| | | |  50mm
+-+ +-+
| |   |  30mm
+-+-+ +
| |X| |  40mm
+-+-+-+
"""

CASES: dict[str, list[dict]] = {
    "DisplayShelf": [{"sx": "100:150:80"}, {"angle": "-20"}, {"include_back": "1", "include_front": "1", "include_bottom": "1"}, {"front_wall_height": "0"}, {"divider_wall_height": "40"}, {"slope_top": "1"}],
    "CoffeeCapsuleHolder": [{"backplate": "off"}],
    "AirPurifier": [{"split_frames": "off"}, {"filters": "1"}, {"filters": "1", "split_frames": "off", "fan_diameter": "120"}],
    "MakitaPowerSupply": [{"secondary_power": "none"}],
    "PhotoFrame": [{"split_front": "off"}, {"x": "130", "y": "90"}],
    "TrafficLight": [{"n": "2"}, {"upright": "off"}, {"back_edge": "h"}, {"back_edge": "e"}],
    "Matrix": [{"h": "50"}],
    "Dispenser": [{"x": "80", "y": "120"}, {"bottomheight": "40", "sideedges": "h"}, {"viewingwidth": "0"}],
    "HalfBox": [{"sy": "30:60"}, {"Sturdy": "on", "sy": "30:60"}, {"Sturdy": "on", "sy": "50"}],
    "CoinBankSafe": [{"x": "120", "y": "90"}],
    "RollHolder": [{"one_piece": "off"}, {"height": "40", "axle": "30"}],
    "KeyHolder": [{"num_hooks": "3", "mounting": "1"}],
    "DinRailBox": [{"rail_offset": "10"}, {"x": "120", "y": "60", "rail_width": "15"}],
    "WineRack": [{"walls": "minimal"}, {"walls": "no_verticals"}, {"y": "400"}, {"y": "400", "walls": "minimal"}],
    "SpicesRack": [{"numx": "3", "numy": "2"}, {"feet": "1"}, {"in_place_supports": "on"}, {"in_place_supports": "on", "feet": "1"}],
    "HobbyCase": [{"unit_w": "150:215:100", "shelves_n": "1:3:0", "rows": "4"}, {"inset_shelves": "0"}, {"add_rails": "off", "add_cover": "0"}],
    "SmallPartsTray": [{"sx": "30:50:40"}, {"two_sided": "0"}, {"two_sided": "0", "front_panel": "off"}, {"front_panel": "0"}, {"angle": "30", "rampheight": "0.3"}, {"outside": "0"}],
    "GridfinityTrayLayout": [{"nx": "1", "ny": "3"}, {"stacking": "1", "h": "3u"}, {"countx": "0", "county": "0"}],
    "DividerTray": [{"sx": "30:50:40", "sy": "20:60:40"}, {"Slot_angle": "0"}, {"left_wall": "0"}, {"bottom": "1"}, {"bottom": "1", "handle": "1"}, {"outside": "1", "bottom": "1"}, {"sy": "0:40:50:0"}],
    "TrayInsert": [{"sx": "30:50:40", "sy": "20:60"}, {"x": "200", "y": "130"}, {"draft_angle": "5"}],
    "GridfinityBase": [{"bottom_edge": "e"}, {"h": "0"}, {"Lid_style": "flat"}, {"Lid_style": "flatbrim"}],
    "SmallPartsTray2": [{"sx": "30:50:40", "sy": "60:40:50"}, {"back_height": "20"}, {"hi": "20"}, {"outside": "1"}],
    "PaintStorage": [{"drawer": "1"}, {"additional_bottom": "1", "additional_top": "1"}],
    "SBCMicroRack": [{"sbcs": "3"}, {"switch": "1"}],
    "CardHolder": [{"sx": "50:80:60"}, {"angle": "15"}, {"outside": "1"}],
    "DiscRack": [{"sx": "15*5:25*4"}, {"angle": "30"}],
    "HingeBox": [{"splitlid": "30"}, {"outside": "1"}, {"lidheight": "35"}],
    "IntegratedHingeBox": [{"outside": "1"}, {"lidheight": "30", "x": "120"}],
    # top2 1.2: a layer boundary at 1.5 mm would sit right on a fill sample (0.5 t).
    "Keypad": [{"top2_enable": "1", "top2_thickness": "1.2"}, {"h": "50"}],
    "NotesHolder": [{"sx": "40:70:30"}, {"opening": "10"}, {"sx": "40:70:30", "back_openings": "1"}, {"bottom_edge": "f"}],
    "BrickSorter": [{"level": "bottom"}],
    "RackBox": [{"outside": "1"}, {"x": "150", "y": "80", "h": "60"}],
    "Crate": [{"MakeStackable": "0"}, {"x": "150", "y": "220"}],
    "StackableBin": [{"sx": "40:70:30"}, {"outside": "1"}, {"front": "0.6"}],
    "BinTray": [{"sx": "40:70:30", "sh": "30:60:45"}, {"outside": "1"}],
    "Rack19HalfWidth": [{"ru_count": "2", "z": "40"}],
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
    "WallHook": [{"width": "30", "hook_inside_diameter": "30", "hook_thickness": "15"}],
    "WallCaliper": [{"width": "25", "height": "10"}],
    "WallChiselHolder": [{"holediameter": "20"}, {"holediameter": "20", "hooks": "odds"},
                         {"number": "5", "tooldiameter": "40"}],
    "WallSlottedHolder": [{"hooks": "everythird"}, {"slot_depth": "60"}],
    "WallStairs": [{"sx": "60:90:40", "sy": "30:50:40", "sh": "20:60:150"}, {"braceheight": "0"}],
    "WallPinRow": [{"angle": "0"}, {"angle": "35", "hooks": "4"}, {"h": "80", "pins": "5"},
                   {"walltype": "slatwall"}],
    "WallPliersHolder": [{"sx": "60:100:80", "angle": "30"}, {"outside": "0"}],
    "WallRollHolder": [{"width": "200", "diameter": "100", "height": "120", "axle": "30"}],
    # sh must increase front to back (the inner walls are as high as the row behind them).
    "DrillStand": [{"sx": "25*3", "sy": "10:20", "sh": "25:40"}, {"extra_height": "0"},
                   {"sx": "20:40:30", "sy": "30:15:20:25", "sh": "20:30:30:70"}],
    "WallDrillBox": [{"sx": "25*3", "sy": "10:20", "sh": "25:40"}, {"extra_height": "30"},
                     {"sx": "20:40:30", "sy": "30:15:20:25", "sh": "20:30:30:70"}],
    "MagazineFile": [{"x": "80", "y": "150", "h": "120", "hi": "100"}, {"h": "200", "hi": "40"},
                     {"top_edge": "G"}],
    "FlexBox2": [{"y": "40", "radius": "25"}, {"h": "50", "latchsize": "3"}],
    "FlexBox4": [{"y": "40", "radius": "25"}, {"h": "50", "latchsize": "3"}],
    "FlexBox5": [{"top_diameter": "40", "bottom_diameter": "70"}, {"top_diameter": "80", "x": "100"}],
    "UBox": [{"top_edge": "f"}, {"top_edge": "i"}, {"top_edge": "k"}, {"y": "40", "radius": "25"}, {"top_edge": "L"}],
    "RoundedBox": [{"wallpieces": "2"}, {"wallpieces": "3", "sh": "40:50"}, {"wallpieces": "4", "top": "lid"},
                   {"edge_style": "F"}, {"edge_style": "h"}, {"y": "30", "radius": "15"},
                   {"x": "150", "y": "60", "radius": "20", "top": "closed"}],
    "FlexBox3": [{"h": "20", "radius": "10"}, {"h": "8", "radius": "20"}, {"c": "3"}],
    "FlexBox": [{"sx": "40:60:30"}, {"y": "40", "radius": "25"}, {"h": "40", "latchsize": "3"},
                {"sx": "50:50", "outside": "0"}],
    "NightLightBox": [{"BoxStyle": "minimalist"}, {"BoxStyle": "extra customizable face"},
                      {"WoodPlatesCount": "1", "WoodPlateThickness": "3", "InterPlateSpacing": "20"},
                      {"hooks": "1", "Margin": "1"}],
    "WallStackableBin": [{"sx": "40:60:30", "angle": "45"}, {"label": "0"},
                         {"Stackable_bottom_stabilizers": "0", "front": "0.5"}, {"walltype": "slatwall"}],
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
    "TrayLayout": [{"sx": "30:50:70", "sy": "20:60"}, {"outside": "0", "hi": "40"},
                   {"hi": "120"}, {"layout": _LAYOUT}, {"layout": _LAYOUT, "outside": "0"},
                   {"Lid_style": "flat"}, {"Lid_style": "overthetop"}],
    "ClosedBox": [{"x": "60", "y": "120", "h": "40"}],
    "CardBox": [{"openingdirection": "right"}, {"sx": "40:65", "add_lidtopper": "1"}],
    "DiceBox": [{"lidheight": "25"}],
    "BasedBox": [{"top_edge": "f"}, {"top_edge": "E"}, {"Lid_style": "overthetop"}],
    "DrillBox": [{"bottom_edge": "F"}, {"sh": "5:25:10:20"}, {"Lid_style": "flat"}],
    "GridfinityDrillBox": [{"sh": "5:10:30"}, {"Lid_style": "ontop"}],
    "BeeQueenTransportBox": [{"bottom_edge": "F"}, {"sh": "12:30:40"}],
}

# Problems that come from upstream's design, per generator and BoxStyle-like argument value.
EXPECTED = {  # (generator, argument value or None for every case): problems to ignore
    # Front and face have three peg holes, but only two pegs are drawn.
    ("NightLightBox", "extra customizable face"): ("front finger hole", "customizable face finger hole"),
    # The inner vertical walls list sh bottom to top on their back edge (SlottedEdge(self.sh)),
    # the back plate and their own front edge top to bottom: uneven rows miss the holes.
    ("BinTray", "30:60:45"): ("back finger hole", "inner vertical"),
    # With back_height the front wall is h high (holes too), the sides' front edge and the
    # inner walls only hi - t*sqrt(2): it sticks out and its upper holes stay empty.
    # One-sided without front panel: the sides get a plain bottom edge, the floor's finger
    # joints to them have nothing to go into.
    ("SmallPartsTray", "off"): ("edge 1 'f'", "edge 3 'f'"),
    # The back rail is 8 t shorter than the shelf's finger hole line in the back: its end holes
    # stay empty (any case). Without rails, slots without shelves are empty.
    ("HobbyCase", None): ("base plate",),
    ("HobbyCase", "off"): ("finger hole",),
    # Supports cut inside the shelves' can holes are recorded as part of the shelf.
    ("SpicesRack", "on"): ("finger hole",),
    # The slot for the latch (2D) in the rail holder cuts through its middle finger.
    ("DinRailBox", None): ("(70x8) finger hole", "Back finger hole at 32.0"),
    ("SmallPartsTray2", "20"): ("front", "side edge 1", "side finger hole", "inner y"),
    # Without Sturdy the outer supports stand flush with the bottom's edges: their finger holes
    # touch the outline and become notches.
    ("HalfBox", None): ("bottom cuts into support",),
    # Without a back, the inner horizontal walls still have finger joints there.
    ("TrafficLight", "e"): ("edge 0 'f'",),
    # Upstream: the inner frames' bottom edge is F but the bottom has finger holes (fit f), their
    # top edge and the top's are both f, and the bottom's front/back fingers meet the outer
    # frames' plain (E) bottom edge. The outer frames' top finger holes hold nothing.
    ("AirPurifier", None): ("top edge", "bottom edge", "bottom finger hole", "edge 0 'F'",
                            "edge 2 'f'", "edge 2 'h'", "x30) finger hole", "x493) finger hole",
                            "cuts into bottom", "cuts into top"),
}

# Generators whose default arguments are degenerate upstream; only CASES are checked.
SKIP_DEFAULTS = {
    # holediameter == tooldiameter: the tool holes meet at the braces, which then sit on the
    # plate's edges and in the holes (d = min(2t, (wt - rt) / 4) = 0).
    "WallChiselHolder": "braces have no plate to sit on with the default sizes",
}

FILL_MIN = 0.9
OVERLAP_MAX = 0.05
FINGER_EDGES = set("fFhH")
# Generators may define finger joints under other chars (FlexBox3's g/G); square ones only.
FINGER_TYPES = {"FingerJointEdge", "FingerJointEdgeCounterPart", "FingerHoleEdge"}
# Wall mount joints (b/B fingers, c/C slots; edge classes Wall*) are plain finger joints with the
# plain wall type. Other generators use b/B for their own edges.
WALL_EDGES = set("bBcC")


class BendPath:
    """Exact model of a flex part's bend path (Placement.bend, mirrors web/src/bend.ts)."""

    def __init__(self, bends) -> None:
        # Pieces: (x0, x1, k, P, T) with k = 0 for straight pieces; N = (-T[1], T[0]).
        self.pieces = []
        P, T, x = np.zeros(2), np.array([1.0, 0.0]), 0.0
        # Arcs: k is the turn per part length, the radius 1/|k| * s (s: stretch).
        for x0, angle, r, *s in sorted(bends):
            s = s[0] if s else 1.0
            P = self._straight(x, x0, P, T)
            k, x1 = np.sign(angle) * s / r, x0 + r * np.radians(abs(angle)) / s
            self.pieces.append((x0, x1, k, P, T, s))
            P, T = self._arc(P, T, k, s, x1 - x0)
            x = x1
        self.pieces.append((x, np.inf, 0.0, P, T, 1.0))

    def _straight(self, x0, x1, P, T):
        if x1 > x0:
            self.pieces.append((x0, x1, 0.0, P, T, 1.0))
        return P + T * (x1 - x0)

    @staticmethod
    def _arc(P, T, k, st, l):
        N = np.array([-T[1], T[0]])
        c, s = np.cos(k * l), np.sin(k * l)
        return P + (T * s + N * (c - 1)) * st / k, T * c - N * s

    def map(self, x, z):
        """(x, z) -> bent (x, z) for arrays; x before 0 extends the first piece."""
        out = np.zeros((len(x), 2))
        for i, (x0, x1, k, P, T, st) in enumerate(self.pieces):
            sel = (x >= x0 if i else np.ones(len(x), bool)) & (x < x1)
            l = x[sel] - x0
            if k == 0:
                Pl, Tl = P + np.outer(l, T), np.tile(T, (len(l), 1))
            else:
                N = np.array([-T[1], T[0]])
                c, s = np.cos(k * l)[:, None], np.sin(k * l)[:, None]
                Pl, Tl = P + (T * s + N * (c - 1)) * st / k, T * c - N * s
            Nl = np.column_stack([-Tl[:, 1], Tl[:, 0]])
            out[sel] = Pl + Nl * z[sel, None]
        return out

    def inverse(self, X, Z, t):
        """Bent (X, Z) -> list of candidate unbent (x, z, valid) per piece."""
        d0 = np.column_stack([X, Z])
        for x0, x1, k, P, T, st in self.pieces:
            N = np.array([-T[1], T[0]])
            if k == 0:
                d = d0 - P
                l, z = d @ T, d @ N
            else:
                d = d0 - (P - N * st / k)
                s = np.sign(k) * np.hypot(d[:, 0], d[:, 1])
                z = s - st / k
                with np.errstate(invalid="ignore", divide="ignore"):
                    l = np.arctan2((d @ T) / s, (d @ N) / s) / k
            yield x0 + l, z, (l >= -1e-6) & (x0 + l <= x1 + 1e-6)


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
        self.t = p.get("t", t)
        self.bend = BendPath(p["bend"]) if p.get("bend") else None

    def world(self, x, y, z):
        x, y, z = (np.asarray(c, float) for c in (x, y, z))
        if self.bend is not None:
            b = self.bend.map(x, z)
            x, z = b[:, 0], b[:, 1]
        return self.o + np.column_stack([x, y, z]) @ self.R.T

    def contains(self, w) -> np.ndarray:
        local = (w - self.o) @ self.Rinv.T
        eps = 0.05 * self.t
        if self.bend is None:
            inz = (local[:, 2] > eps) & (local[:, 2] < self.t - eps)
            return inz & contains_xy(self.poly, local[:, 0], local[:, 1])
        out = np.zeros(len(w), bool)
        for x, z, ok in self.bend.inverse(local[:, 0], local[:, 2], self.t):
            ok = ok & (z > eps) & (z < self.t - eps)
            if ok.any():
                out[ok] |= contains_xy(self.poly, x[ok], local[ok, 1])
        return out


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


def finger_hole(hole, t: float):
    """Sample points along the middle of an axis-aligned rectangular hole about t wide."""
    if len(hole) > 6:  # rounded slot (air holes etc.)
        return None
    xs, ys = [q[0] for q in hole], [q[1] for q in hole]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    if abs(min(w, h) - t) > 0.15 * t or max(w, h) < 0.9 * t:
        return None
    if abs(Polygon(hole).area - w * h) > 0.02 * w * h:  # not an axis-aligned rectangle
        return None
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    m = 0.2 * min(w, h)
    if w >= h:
        along = np.linspace(min(xs) + m, max(xs) - m, 5)
        return along, np.full_like(along, cy)
    along = np.linspace(min(ys) + m, max(ys) - m, 5)
    return np.full_like(along, cx), along


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
            # A letter of FINGER_EDGES a generator uses for its own edge (KeyHolder's H hook).
            own = e.get("type") and e["type"] not in FINGER_TYPES
            if not composite and (e["char"] not in FINGER_EDGES or own) and not (
                    e.get("type") in FINGER_TYPES and e.get("angle") == 90) and not (
                    e["char"] in WALL_EDGES and e.get("type", "").startswith("Wall")
                    and args.get("walltype", "plain") == "plain"):
                continue
            band = edge_band(a, i)
            if band is None:
                continue
            x, y = band
            ina = contains_xy(a.poly, x, y)
            filled = hit(a.world(x, y, np.full_like(x, a.t / 2)))
            gaps, fingers = ~ina, ina
            fill = filled[gaps].mean() if gaps.any() else 1.0
            overlap = filled[fingers].mean() if fingers.any() else 0.0
            if composite:
                fill = 1.0
            if fill < FILL_MIN or overlap > OVERLAP_MAX:
                problems.append(f"{a.name} edge {i} '{e['char'] or '?'}': fill {fill:.0%}, overlap {overlap:.0%}")
        for hole in a.rec["outline"]["holes"]:
            band = finger_hole(hole, t)
            if band is None:
                continue
            x, y = band
            fill = hit(a.world(x, y, np.full_like(x, a.t / 2))).mean()
            if fill < FILL_MIN:
                xs, ys = [q[0] for q in hole], [q[1] for q in hole]
                problems.append(f"{a.name} finger hole at {min(xs):.1f},{min(ys):.1f}: fill {fill:.0%}")
        # Coarse body check: parts cutting into each other.
        minx, miny, maxx, maxy = a.poly.bounds
        step = max(1.0, min(maxx - minx, maxy - miny) / 25)
        gx, gy = np.meshgrid(np.arange(minx, maxx, step), np.arange(miny, maxy, step))
        gx, gy = gx.ravel(), gy.ravel()
        keep = contains_xy(a.poly, gx, gy)
        w = a.world(gx[keep], gy[keep], np.full(keep.sum(), a.t / 2))
        for b in others:
            frac = b.contains(w).mean() if len(w) else 0.0
            if frac > 0.01 and a.name <= b.name:
                problems.append(f"{a.name} cuts into {b.name}: {frac:.0%} of its area")
    return problems


def main(names: list[str]) -> int:
    failed = 0
    for name in names or sorted(PLACEMENTS):
        for args in ([] if name in SKIP_DEFAULTS else [{}]) + CASES.get(name, []):
            problems = check(name, args)
            soft = ("unplaced",) + (("finger hole",) if any(p.startswith("unplaced") for p in problems) else ())
            soft += sum((v for (n, a), v in EXPECTED.items() if n == name and (a is None or a in args.values())), ())
            hard = [p for p in problems if not any(s in p for s in soft)]
            failed += bool(hard)
            print(f"{'FAIL' if hard else 'ok  '} {name} {args or ''}")
            for p in problems:
                print(f"       {p}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""Placement functions: where each recorded wall of a generator goes in 3D.

Each function gets an Assembly (see assembly.py) after the generator has rendered and
places what it can. Parts left unplaced are shown in 2D only. Lids drawn by the shared
helpers (_TopEdge.drawLid, boxes.lids.Lid) have shared placers, so every generator that
uses them only needs to call place_lids().
"""
from __future__ import annotations

import copy
import math
from types import SimpleNamespace
from collections.abc import Callable

from assembly import Assembly, BoxFrame, add, X, Y, Z, _polygon_segments, neg, positions

PLACEMENTS: dict[str, Callable[[Assembly], None]] = {}


def placement(*names: str):
    def register(func):
        for name in names:
            PLACEMENTS[name] = func
        return func
    return register


def assemble(name: str, box, walls: list[dict]) -> Assembly | None:
    """The placed assembly, or None if the generator has no placement function."""
    func = PLACEMENTS.get(name)
    if func is None:
        return None
    asm = Assembly(box, walls)
    func(asm)
    return asm


# --- Lids -----------------------------------------------------------------------------

def place_lids(a: Assembly, f: BoxFrame, top_edge: str | None,
               inner: float | None = None) -> None:
    """Lids from _TopEdge.drawLid(x, y, top_edge) and box.lid(x, y, top_edge) on frame f.
    inner: height of the inner walls, if the box has any (see _lid)."""
    z = _top_edge_lid(a, f, top_edge) if top_edge is not None else f.h
    # A lid from box.lid sits on whatever closes the top.
    if z == f.h:
        _lid(a, f, inner)
    else:
        _lid(a, f.sub(0, 0, 0, f.x, f.y, z))


def _top_edge_lid(a: Assembly, f: BoxFrame, top_edge: str) -> float:
    """Places the lid parts drawn by drawLid(); returns the height of the box's top."""
    lid = a.parts.drawn_by("_TopEdge.drawLid")
    t = a.t
    if top_edge in "cfFhŠY":
        # Plate held by the walls' top edges.
        top = lid.label("top")
        f.top(top)
        return f.h + t if top else f.h
    if top_edge == "E":
        # Walls stick out by t: a plug fits between them, the cover sits on top.
        f.plate(lid.edges("eeee").first(), f.h)
        f.plate(lid.edges("EEEE").first(), f.h + t)
        return f.h + 2 * t
    if top_edge in "Liv":
        # Sliding lid (L: in grooves of the side walls, its back in the back wall's finger
        # holes) or hinged lids: a plate on top of the walls. Hinge parts stay 2D.
        top = lid.labelled("lid top").first()
        f.top(top)
        return f.h + t if top else f.h
    if top_edge == "k":
        # Two halves hinged at the sides, meeting in the middle.
        f.top(lid.label("lid top left"))
        right = lid.label("lid top right")
        if right is not None:
            f.top(right, du=f.x - right.x, flip=True)
        return f.h + t
    return f.h


def _lid(a: Assembly, f: BoxFrame, inner: float | None = None) -> None:
    """boxes.lids.Lid: the "lid" settings group. inner: height of inner walls; the lower layer
    of a flat lid rests on them if they reach higher than h - t (the lid then sits above the
    outer walls: set the inner height lower to have it sink in)."""
    parts = a.parts.drawn_by("Lid.__call__")
    if not parts:
        return
    s = a.box.lidSettings
    t = a.t
    x, y, h = f.x, f.y, f.h
    bs = s.brim_spacing
    style = s.style
    if style == "flat":
        z = max(h - t, inner or 0.0)
        f.plate(parts.label("lid bottom"), z, x0=bs, y0=bs)
        f.plate(parts.label("lid top"), z + t)
    elif style == "flatbrim":
        f.plate(parts.label("lid top"), h)
        # Brims hang from the lid into the box, held in finger holes; drawn upside down.
        bh = s.brim_height
        brims = parts.labelled("lid brim")
        wx = x - 2 * bs
        wy = y - 2 * bs - 2 * t
        lid_f = f.sub(bs, bs + t, h - bh, wx, wy, bh)
        lid_f.front(brims.where(lambda p: abs(p.x - wx) < 1e-6).first(), rot=180)
        lid_f.back(brims.where(lambda p: abs(p.x - wx) < 1e-6).first(), rot=180)
        side = f.sub(bs + t, bs + t, h - bh, wx - 2 * t, wy, bh)
        side.left(brims.first(), rot=180)
        side.right(brims.first(), rot=180)
    elif style == "flatfang":
        f.plate(parts.label("lid top"), h)
        # Fangs go through slots near the corners and hook below the box's top edge.
        fs = s.fang_size
        z = h + t - (s.brim_height + t)  # bottom of a fang
        fangs = parts.where(lambda p: abs(p.x - fs) < 1e-6)
        corners = [  # (x0, y0, along y?)
            (bs, bs, True), (x - bs - fs, bs, False),
            (bs, y - bs - t, False), (x - bs - t, y - bs - fs, True),
        ]
        for x0, y0, along_y in corners:
            p = fangs.first()
            if along_y:
                a.place(p, f.at(x0, y0, z), Y, Z, X, name="lid fang")
            else:
                a.place(p, f.at(x0, y0 + t, z), X, Z, neg(Y), name="lid fang")
    elif style in ("overthetop", "ontop"):
        if style == "overthetop":
            # Slides over the walls: inner size grows by 2t + play, the top rests on the walls.
            d = t + s.play / 2
            lf = f.sub(-d, -d, h - s.height, x + 2 * d, y + 2 * d, s.height)
        else:
            # Same size as the box, standing on its walls.
            lf = f.sub(0, 0, h, x, y, s.height)
        lf.top(parts.label("lid top"))
        lf.front(parts.label("lid front"))
        lf.back(parts.label("lid back"))
        lf.left(parts.label("lid left"))
        lf.right(parts.label("lid right"))
        if style == "ontop":
            # Locating brims, one in the middle of each side, inside the lid's walls: from
            # the lid top down to 2t into the box.
            brims = parts.labelled("lid\nbrim")
            for (x0, y0), u, n in (((x / 2, t), X, neg(Y)), ((x / 2, y - t), neg(X), Y),
                                   ((0.0, y / 2), Y, X), ((x, y / 2), neg(Y), neg(X))):
                q = brims.first()
                if q is not None:
                    a.place(q, add(f.at(x0, y0, h + s.height - q.y), u, -q.x / 2), u, Z, n,
                            name="lid brim")
        _handle(a, f, parts, (x / 2, y / 2), h + (s.height if style == "ontop" else 0.0))
    elif style == "sliding":
        f.plate(parts.label("lid bottom"), h - t, x0=bs, y0=-t)
        f.plate(parts.label("lid top"), h)
        # Both layers span -t .. y - bs (see TrayLid).
        _handle(a, f, parts, (x / 2, (y - bs - t) / 2), h - t)
    if style == "flat":
        _handle(a, f, parts, (x / 2, y / 2), z)
    # "chest" sides are not drawn with rectangularWall, so they are not recorded yet.
    # flatbrim and flatfang lids draw the handle but no hole for it: it stays 2D only.


def _handle(a: Assembly, f: BoxFrame, parts, centre: tuple[float, float], z: float) -> None:
    """Lid handle (Lid.handleParts) through the lid's hole at centre, its foot below the lowest
    lid layer, which starts at z. A long handle stands along x; the two knob pieces cross."""
    t = a.t
    cx, cy = centre

    def put(q, along_x: bool) -> None:
        # Centred on its own outline: both knob pieces are drawn in one move (one bounding box).
        xs = [p[0] for p in q.rec["outline"]["outer"]]
        ys = [p[1] for p in q.rec["outline"]["outer"]]
        mid, bottom = (min(xs) + max(xs)) / 2, min(ys)
        if along_x:
            a.place(q, f.at(cx - mid, cy + t / 2, z - t - bottom), X, Z, neg(Y), name="lid handle")
        else:
            a.place(q, f.at(cx - t / 2, cy - mid, z - t - bottom), Y, Z, X, name="lid handle")

    long = parts.drawn_by("Lid.longHandle").first()
    if long is not None:
        put(long, True)
    for q, along_x in zip(list(parts.drawn_by("Lid.knobHandle")), (True, False)):
        put(q, along_x)


# --- Simple boxes ---------------------------------------------------------------------

def _outer_walls(a: Assembly, f: BoxFrame, labels: dict[str, str]) -> None:
    for label, face in labels.items():
        getattr(f, face)(a.parts.label(label))


@placement("UniversalBox")
def universal_box(a: Assembly) -> None:
    b = a.box
    f = a.frame(b.x, b.y, b.h)
    f.dims(x="x", y="y", h="h")
    _outer_walls(a, f, {"front": "front", "back": "back", "left": "left",
                        "right": "right", "bottom": "bottom"})
    place_lids(a, f, b.top_edge)
    # top_edge f/F: a frame 2 t wider all round, its hole around the top plate's edge.
    ring = a.parts.label("top hole")
    if ring is not None:
        f.plate(ring, f.h, x0=-2 * a.t, y0=-2 * a.t)


@placement("ABox")
def a_box(a: Assembly) -> None:
    b = a.box
    f = a.frame(b.x, b.y, b.h)
    f.dims(x="x", y="y", h="h")
    own = a.parts.not_drawn_by("Lid.__call__")
    f.bottom(own.edges("ffff").first())
    walls = own.where(lambda p: p.chars != "ffff")
    for face in ("front", "back", "left", "right"):
        getattr(f, face)(walls.first())
    place_lids(a, f, None)


@placement("ClosedBox")
def closed_box(a: Assembly) -> None:
    p = a.parts
    front = p.label("Wall 1")
    side = p.label("Wall 2")
    if front is None or side is None:
        return
    f = a.frame(front.x, side.x, front.y)
    f.dims(x="x", y="y", h="h")
    f.front(front)
    f.right(side)
    _outer_walls(a, f, {"Wall 3": "back", "Wall 4": "left", "Bottom": "bottom", "Top": "top"})


@placement("TypeTray")
def type_tray(a: Assembly) -> None:
    b = a.box
    t = a.t
    x = sum(b.sx) + t * (len(b.sx) - 1)
    y = sum(b.sy) + t * (len(b.sy) - 1)
    f = a.frame(x, y, b.h)
    f.dims(x="sx", y="-sy", h="h")
    _inner_height(f, positions(b.sx, t), [y - y0 - t for y0 in positions(b.sy, t)], b.hi)
    f.walls("sx", "x", positions(b.sx, t), a.arg("sx"), b.sx, b.hi)
    f.walls("sy", "-y", [y - y0 - t for y0 in positions(b.sy, t)], a.arg("sy"), b.sy, b.hi)
    p = a.parts
    _outer_walls(a, f, {"front": "front", "back": "back", "left side": "left",
                        "right side": "right", "bottom": "bottom"})
    top = p.label("top") if b.closedtop and b.hi == b.h else None
    if top is not None:
        f.top(top)
    # Inner walls: "inner x k" between rows of sy, "inner y k" between sx. sy runs back to
    # front (as on the left side wall), so the inner y walls are seen from the left.
    for k, y0 in enumerate(positions(b.sy, t), 1):
        f.inner_x(p.label(f"inner x {k}"), y - y0 - t)
    for k, x0 in enumerate(positions(b.sx, t), 1):
        f.inner_y(p.label(f"inner y {k}"), x0, flip=True)
    if top is not None:
        # The closed top is drawn by render(), not drawLid(): a lid sits on it.
        _lid(a, f.sub(0, 0, 0, x, y, b.h + t))
    else:
        place_lids(a, f, b.top_edge, inner=b.hi if len(b.sx) > 1 or len(b.sy) > 1 else None)
    # Compartment (i, j): sx[i] from the left, sy[j] from the back.
    cx = [0.0] + [x0 + t for x0 in positions(b.sx, t)]
    cy = [y] + [y - y0 - t for y0 in positions(b.sy, t)]
    lx, ly = len(b.sx), len(b.sy)
    outer = {"front": lambda i, j: j == ly - 1, "back": lambda i, j: j == 0,
             "left": lambda i, j: i == 0, "right": lambda i, j: i == lx - 1}
    side = (getattr(b, "_web_ramp", None) or {}).get("side", "front")
    hi = b.hi or b.h
    # Finger holes: inner walls along x always (if any), outer front/back only when chosen.
    # All notches are drawn with wallheight hi (FingerHoleEdgeSettings in render()).
    depth = _notch_depth(b, hi) if side in ("front", "back") and b.fingerholes != "none" else 0.0

    def hole(i: int, j: int) -> float:
        if not depth or not outer[side](i, j):
            return depth
        return depth if not b.closedtop and b.fingerholes in (side, "front-and-back") else 0.0

    # The core raises the back wall by back_height only with top_edge "e".
    bh = b.back_height if b.top_edge == "e" else 0.0

    def wall(i: int, j: int) -> float:
        if not outer[side](i, j):
            return hi
        return b.h + (bh if side == "back" else 0.0)

    _card_ramps(a, [(cx[i], cx[i] + b.sx[i], cy[j] - b.sy[j], cy[j], wall(i, j), hole(i, j))
                    for j in range(ly) for i in range(lx)], _ramp_limit(b, b.h))


#: Ramp height for "auto" at walls without a finger hole (the former default).
RAMP_HEIGHT_NO_HOLE = 15.0


def _notch_depth(box, wallheight: float) -> float:
    """Depth (from the top of the wall) of a finger hole notch (FingerHoleEdge "A") drawn with
    this wallheight setting; 0 without one."""
    s = getattr(getattr(box, "edges", {}).get("A"), "settings", None)
    if s is None or wallheight <= 0:
        return 0.0
    return min(s.absolute_depth + wallheight * s.relative_depth,
               wallheight - min(box.thickness, 0.1 * wallheight))


def _ramp_limit(box, h: float) -> float:
    """Highest a ramp may reach in a box with outer walls h high: below lids that reach into
    the box (the lower layer of flat and sliding lids, the brims of flatbrim). Other lids sit
    on top: the ramp only has to stay below its wall (a raised back wall, inner walls higher
    than h)."""
    s = getattr(box, "lidSettings", None)
    style = getattr(s, "style", "none")
    if style in ("flat", "sliding"):
        return h - box.thickness
    if style == "flatbrim":
        return h - s.brim_height
    return math.inf


def _card_ramps(a: Assembly, cells: list[tuple[float, float, float, float, float, float]],
                limit: float = math.inf) -> None:
    """Printed wedges so cards slide up and out, when the user turned them on (box._web_ramp:
    side, height, angle; see boxes_bridge). cells: (x0, x1, y0, y1, wall height, finger hole
    depth or 0) of each compartment with a floor and a wall on the ramp side. A ramp fills the
    compartment's width, leans against that wall and rises from the floor at the given angle,
    no higher than the wall and limit (see _ramp_limit). Height None ("auto"): up to the
    bottom of the wall's finger hole, so a card lying on the ramp can be gripped through it."""
    r = getattr(a.box, "_web_ramp", None)
    if not r:
        return
    side = r["side"]
    tan = math.tan(math.radians(min(max(r["angle"], 5.0), 85.0)))
    for k, (x0, x1, y0, y1, wall, hole_depth) in enumerate(cells, 1):
        along_y = side in ("front", "back")
        depth, width = (y1 - y0, x1 - x0) if along_y else (x1 - x0, y1 - y0)
        height = r["height"]
        if height is None:
            height = wall - hole_depth if hole_depth > 0 else RAMP_HEIGHT_NO_HOLE
        h = min(height, wall, limit)
        length = h / tan
        if length > depth:
            length, h = depth, depth * tan
        if h < 0.1 or width < 0.1:
            continue
        # Local x runs from the wall into the compartment, y up; extruded across the width.
        origin, u, n = {"front": ((x0, y0, 0.0), Y, X), "back": ((x1, y1, 0.0), neg(Y), neg(X)),
                        "left": ((x0, y1, 0.0), X, neg(Y)), "right": ((x1, y0, 0.0), neg(X), Y)}[side]
        a.place(a.extra(f"card ramp {k}", [(0.0, 0.0), (length, 0.0), (0.0, h)]),
                origin, u, Z, n, thickness=width)


# --- Card and dice boxes --------------------------------------------------------------

@placement("CardBox")
def card_box(a: Assembly) -> None:
    b = a.box
    t = a.t
    p = a.parts
    x, y, h = b.boxwidth, b.boxdepth, b.boxhight
    # Outer walls are h + t high. The lid slides on the inner side walls (top at h)
    # under the lips (from h + t); lips and lid grip end flush at h + 2t.
    f = a.frame(x, y, h + t)
    f.bottom(p.label("Bottom"))
    f.front(p.label("Front"))
    # The back is mounted inside out: its divider holes are drawn as seen from the front.
    f.back(p.label("Back"), flip=True)
    f.left(p.label("Outer Side Left"))
    f.right(p.label("Outer Side Right"))
    # Dividers stand on their side: local x is the height.
    for x0 in positions(b.sx, t, start=t):
        f.inner_y(p.label("Divider"), x0, rot=90)

    if b.openingdirection == "front":
        f.inner_y(p.label("Inner Side Left"), 0, rot=180)
        f.inner_y(p.label("Inner Side Right"), x - t, rot=180)
        # Lid: its F edge (local top) at the front, over the lowered front wall.
        a.place(p.label("Lid"), f.at(x - 0.1 * t, y, h), neg(X), neg(Y), Z)
        a.place(p.label("Lid Lip"), f.at(0.1 * t, 0, h + t), X, Z, neg(Y))
        # Lips lie flat on the side walls, fingers pointing outwards.
        a.place(p.label("Lip Left"), f.at(t, 0, h + t), Y, neg(X), Z)
        a.place(p.label("Lip Right"), f.at(x, 0, h + t), Y, neg(X), Z)
        a.place(p.label("Lid topper (optional)"), f.at(x - 1.1 * t, y, h + t), neg(X), neg(Y), Z)
    else:
        # Opening to the right; inlays on front and back form the rails.
        f.inner_y(p.label("Inner Side Left"), 0, rot=180)
        f.inner_y(p.label("Inner Side Right"), x - t, rot=180)
        for x0 in [t] + [x0 + t for x0 in positions(b.sx, t, start=t)]:
            f.inner_x(p.label("Front inlay"), 0, x0=x0)
            f.inner_x(p.label("Back inlay"), y - t, x0=x0)
        a.place(p.label("Lid"), f.at(0, 0.1 * t, h), X, Y, Z)
        a.place(p.label("Lid Lip"), f.at(x, 0.1 * t, h + t), Y, Z, X)
        a.place(p.label("Lip Front"), f.at(0, 0, h + t), X, Y, Z)
        a.place(p.label("Lip Back"), f.at(0, y - t, h + t), X, Y, Z)
        a.place(p.label("Lid topper"), f.at(0, 1.1 * t, h + t), X, Y, Z)


@placement("DiceBox")
def dice_box(a: Assembly) -> None:
    """Two closed trays joined by a chest hinge at the back; the lid shown closed."""
    walls = list(a.parts)
    if len(walls) != 12:
        return
    (tray, lid_tray, front, back, lid_front, lid_back,
     bottom, top, lid_side_l, side_l, side_r, lid_side_r) = walls
    t = a.t
    x, h, y, hl = front.x, front.y, tray.y, lid_front.y
    # Box: closed by the dice tray on top (finger joints), hinge edges on the side walls.
    f = a.frame(x, y, h)
    f.dims(x="x", y="y", h="h")
    f.bottom(bottom, rot=90)
    f.top(tray)
    f.front(front)
    f.back(back, rot=180)
    f.left(side_l, rot=180)
    f.right(side_r)
    # Lid: same, upside down on top. Its back and sides hang from the lid top.
    lf = a.frame(x, y, hl, origin=(0, 0, h + 2 * t), name="lid")
    lf.bottom(lid_tray, rot=180)  # pin cut-outs at the back, magnets at the front
    lf.top(top, rot=90)
    lf.front(lid_front)
    lf.back(lid_back, rot=180, dv=hl - lid_back.y)
    lf.left(lid_side_l, rot=180, dv=hl - lid_side_l.y)
    lf.right(lid_side_r, dv=hl - lid_side_r.y)
    for tray_part in (tray, lid_tray):
        if tray_part.index in a.placements:
            a.placements[tray_part.index]["name"] = "dice tray"


# --- Boxes with lids from _TopEdge ----------------------------------------------------

def _layers(a: Assembly, f: BoxFrame, sh, plates) -> None:
    """Horizontal layers between sections sh (bottom to top), held in finger holes."""
    z = 0.0
    for d in list(sh)[:-1]:
        z += d
        f.plate(plates.first(), z)
        z += a.t


@placement("BasedBox")
def based_box(a: Assembly) -> None:
    """Walls standing on a larger base plate; "front"/"back" are the walls along y."""
    b = a.box
    p = a.parts
    front, left = p.label("front"), p.label("left")
    if front is None or left is None:
        return
    # Sizes from the parts: render() adjusts x and y for "outside" only locally.
    f = a.frame(left.x, front.x, front.y)
    f.dims(x="x", y="y", h="h")
    f.bottom(p.label("base"))
    f.left(p.label("front"))
    f.right(p.label("back"))
    f.front(p.label("left"))
    f.back(p.label("right"))
    place_lids(a, f, b.top_edge)


@placement("DrillBox")
def drill_box(a: Assembly) -> None:
    """Four walls around (each one's right edge joins the next), a bottom and drill layers."""
    b = a.box
    x, y = sum(b.sx), sum(b.sy)
    h = sum(b.sh) + a.t * (len(b.sh) - 1)
    f = a.frame(x, y, h)
    own = a.parts.not_drawn_by("Lid.__call__")
    walls = own.where(lambda p: p.y == h)
    # Each wall's right edge (f) joins the next one's left edge (F) around the box.
    along_x = walls.where(lambda p: p.x == x)
    f.front(along_x.first())
    f.back(along_x.first())
    along_y = walls.where(lambda p: p.x == y)
    f.right(along_y.first())
    f.left(along_y.first())
    plates = own.where(lambda p: p.y == y)
    if b.bottom_edge != "e":
        f.bottom(plates.first())
    _layers(a, f, b.sh, plates)
    place_lids(a, f, None)


@placement("GridfinityDrillBox")
def gridfinity_drill_box(a: Assembly) -> None:
    b = a.box
    x, y = b.x, b.y
    h = sum(b.sh) + a.t * (len(b.sh) - 1)
    f = a.frame(x, y, h)
    own = a.parts.not_drawn_by("Lid.__call__")
    walls = own.where(lambda p: p.y == h)
    for face in ("front", "right", "left", "back"):
        getattr(f, face)(walls.first())
    plates = own.where(lambda p: p.x == x and p.y == y)
    f.bottom(plates.first())
    _layers(a, f, b.sh, plates)
    place_lids(a, f, None)
    # The small feet (glued under the bottom) stay 2D.


@placement("BeeQueenTransportBox")
def bee_queen_transport_box(a: Assembly) -> None:
    b = a.box
    x, y = sum(b.sx), sum(b.sy)
    h = sum(b.sh) + a.t * (len(b.sh) - 1)
    f = a.frame(x, y, h)
    p = a.parts
    _outer_walls(a, f, {"Back": "back", "Front": "front", "Left": "left", "Right": "right"})
    if b.bottom_edge not in "eš":
        f.bottom(p.label("Bottom Layer"))
    _layers(a, f, b.sh, p.labelled("Layer "))
    place_lids(a, f, None)


@placement("StorageShelf")
def storage_shelf(a: Assembly) -> None:
    """Open at the front (x = 0 here): side walls along x, a back, slotted shelves and dividers."""
    b = a.box
    t = a.t
    p = a.parts
    y = sum(b.sy) + t * (len(b.sy) - 1)
    h = sum(b.sh) + t * (len(b.sh) - 1)
    f = a.frame(b.x, y, h)
    f.front(p.label("left"))
    f.back(p.label("right"))
    f.right(p.label("back"), flip=True)  # drawn as seen from inside
    if b.bottom_edge != "e":
        f.bottom(p.label("bottom"))
    z = 0.0
    for k, d in enumerate(b.sh[:-1], 1):
        z += d
        f.plate(p.label(f"inner horizontal {k}"), z)
        z += t
    # Dividers between the sy sections (counted from y = y); their left edge joins the back.
    for k, y0 in enumerate(positions(b.sy, t), 1):
        f.inner_x(p.label(f"inner vertical {k}"), y - y0 - t, flip=True)
    if b.closedtop:
        f.top(p.label("top"))
    else:
        place_lids(a, f, b.top_edge)
    if b.retainer:
        z = 0.0
        for k, d in enumerate(b.sh, 1):
            f.left(p.label(f"retainer {k}"), dv=z)  # in front, standing on each shelf
            z += d + t


def _bottom_lid(a: Assembly, f: BoxFrame, edge: str) -> None:
    """What _TopEdge.drawLid(x, y, edge) draws, used as the bottom of frame f."""
    lid = a.parts.drawn_by("_TopEdge.drawLid")
    if edge in "cfFhŠY":
        f.bottom(lid.first())
    elif edge == "E":
        f.plate(lid.edges("eeee").first(), 0.0, down=True)
        f.plate(lid.edges("EEEE").first(), -a.t, down=True)


@placement("Shadowbox")
def shadowbox(a: Assembly) -> None:
    """Case with the back at the bottom, the mitred face frame on top and the paper layer
    frames stacked under it."""
    b = a.box
    t = a.t
    p = a.parts
    x, y = b.x, b.y
    h = b.layers * t + b.extraheight
    fw, fh = b.framewidth, b.frameheight
    f = a.frame(x, y, h)
    polys = p.where(lambda q: q.rec["helper"] == "polygonWall")
    bars_x = polys.where(lambda q: q.x == x)
    face_y = polys.where(lambda q: abs(q.x - (y + 2 * t)) < 1e-6)
    face_x = polys.where(lambda q: abs(q.x - (x + 2 * t)) < 1e-6)
    bars_y = p.where(lambda q: q.chars == "eded")
    # Paper layer frames: two bars along x (dovetail sockets inside), two along y, per layer.
    for k in range(b.layers):
        zb = h - (k + 1) * t
        a.place(bars_x.first(), (0, 0, zb), X, Y, Z, name="frame bar")
        a.place(bars_x.first(), (x, y, zb), neg(X), neg(Y), Z, name="frame bar")
        a.place(bars_y.first(), (0, y - fh, zb), neg(Y), X, Z, name="frame bar")
        a.place(bars_y.first(), (x, fh, zb), Y, neg(X), Z, name="frame bar")
    # Face frame: the outer line of each piece lies on the outer faces of the case.
    a.place(face_x.first(), (-t, -t, h), X, Y, Z, name="face frame")
    a.place(face_x.first(), (x + t, y + t, h), neg(X), neg(Y), Z, name="face frame")
    a.place(face_y.first(), (-t, y + t, h), neg(Y), X, Z, name="face frame")
    a.place(face_y.first(), (x + t, -t, h), Y, neg(X), Z, name="face frame")
    walls = p.where(lambda q: q.y == h)
    f.front(walls.where(lambda q: q.x == x).first())
    f.back(walls.where(lambda q: q.x == x).first())
    f.left(walls.where(lambda q: q.x == y).first())
    f.right(walls.where(lambda q: q.x == y).first())
    # LED strip holder: a ring of 10 mm walls just inside the case, on the back.
    led = f.sub(t, t, 0, x - 2 * t, y - 2 * t, 10, name="LED holder")
    led.front(p.edges("efef").first())
    led.back(p.edges("efef").first())
    led.left(p.edges("eFeF").first())
    led.right(p.edges("eFeF").first())
    _bottom_lid(a, f, b.back_edge)


# --- Wall mounted (_WallMountedBox) ---------------------------------------------------
# The wall is at the back (+y). Wall edges b/B are fingers that reach into the back plate
# (c/C edges or d/D slots); a/A edges rest against the wall itself.

def _helper(p, name: str):
    return p.where(lambda q: q.rec["helper"] == name)


@placement("WallConsole")
def wall_console(a: Assembly) -> None:
    """Back plate, a slanted front plate and trapezoid ribs (top depth at the top)."""
    b = a.box
    t = a.t
    p = a.parts
    x = sum(b.sx) + t * (len(b.sx) - 1)
    h, td, bd = b.h, b.top_depth, b.bottom_depth
    d = max(td, bd)
    f = a.frame(x, d, h)
    f.back(p.where(lambda q: q.y == h and q.x == x).first(), flip=True)  # drawn from the front
    # Front plate on the ribs' slanted edge, from (y = d - bd, z = 0) up to (d - td, h).
    length = b.front
    v = (0.0, (bd - td) / length, h / length)
    n = (0.0, -h / length, (bd - td) / length)
    a.place(p.where(lambda q: q.x == x and abs(q.y - length) < 1e-6).first(),
            (0.0, d - bd, 0.0), X, v, n, name="front")
    # Ribs: drawn with the back edge at the bottom, top depth on the left.
    for x0 in [-t] + positions(b.sx, t) + [x]:
        a.place(_helper(p, "trapezoidWall").first(), (x0 + t, d, h), neg(Z), neg(Y), neg(X),
                name="rib")


def _wall_side(a: Assembly, part, x0: float, name: str = "side", face: float | None = None,
               z0: float = 0.0) -> None:
    """A side profile drawn by hand with its wall edge on the left, standing at x0..x0+t.
    face is the local x that touches the wall plate (b edge: t, its fingers fill 0..t) or the
    wall itself (a edge: its margin). The wall plate's front face is y = 0 (it fills y 0..t),
    the profile sticks out towards -y. Mirrored copies are the same shape the other side out."""
    face = a.t if face is None else face
    a.place(part, (x0, face, z0), neg(Y), Z, X, flip=part.mirrored if part else False, name=name)


def _wall_back(a: Assembly, part, z0: float = 0.0, x0: float = 0.0, name: str = "back") -> None:
    """Wall plate (local frame = inner rectangle) with its front face at y = 0."""
    a.place(part, (x0, 0.0, z0), X, Z, Y, name=name)


@placement("WallHook")
def wall_hook(a: Assembly) -> None:
    """Two hook profiles left and right of a flanged back plate, joined by a bottom plate and
    a plate across the hook's tip."""
    b = a.box
    t = a.t
    p = a.parts
    w, ht, hid = b.width, b.hook_thickness, b.hook_inside_diameter
    tl = hid + 2 * ht
    orad = hid / 2 + ht
    sides = _helper(p, "free")
    for x0 in (-t, w):
        _wall_side(a, sides.first(), x0)
    _wall_back(a, _helper(p, "flangedWall").first(), z0=10.0)  # bottom flange 10
    rects = _helper(p, "rectangularWall")
    tip, bottom = rects[0] if rects else None, rects[1] if len(rects) > 1 else None
    a.place(bottom, (0.0, t - 10.0, ht / 2 - t / 2), X, neg(Y), Z, name="bottom")
    a.place(tip, (0.0, t - (tl - ht / 2) + t / 2, orad - ht / 2), X, Z, neg(Y), name="tip")


@placement("WallCaliper")
def wall_caliper(a: Assembly) -> None:
    """Two side profiles left and right of a flanged back plate."""
    b = a.box
    t = a.t
    p = a.parts
    sides = _helper(p, "free")
    for x0 in (-t, b.width):
        _wall_side(a, sides.first(), x0)
    _wall_back(a, _helper(p, "flangedWall").first())


@placement("WallChiselHolder", "WallSlottedHolder")
def wall_slotted_holder(a: Assembly) -> None:
    """Back plate, a top plate with the slots and triangular braces below it, hanging from the
    top plate (local y downwards) with their wall edge on the back plate."""
    b = a.box
    t = a.t
    p = a.parts
    n = b.number
    rects = _helper(p, "rectangularWall")
    if len(rects) < 2:
        return
    back, top = rects[0], rects[1]
    depth = top.y
    if hasattr(b, "tool_width"):  # WallSlottedHolder
        wt = b.tool_width
        d = min(2 * t, (wt - b.slot_width) / 4.0)
        xs = [d, n * wt + d] + [i * wt + d for i in range(1, n) if b.brace(i)]
    else:
        wt = b.tooldiameter
        d = min(2 * t, (wt - b.holediameter) / 4.0)
        xs = [d, n * wt - d] + [i * wt for i in range(1, n) if b.brace(i)]
    _wall_back(a, back)
    a.place(top, (0.0, -depth, b.h), X, Y, Z, name="top")
    for x, tri in zip(xs, _helper(p, "rectangularTriangle")):
        a.place(tri, (x - t / 2, -depth, b.h), Y, neg(Z), X, name="brace")


@placement("WallStairs")
def wall_stairs(a: Assembly) -> None:
    """Stepped side profiles (front at local x 0, wall at x = y) carrying one shelf per step
    and a brace at the wall."""
    b = a.box
    t = a.t
    p = a.parts
    sy, sh = b.sy, b.sh
    y = sum(sy)
    rects = _helper(p, "rectangularWall")
    for k, (w, z) in enumerate(zip(sy, sh)):
        if k < len(rects):
            a.place(rects[k], (0.0, -y + sum(sy[:k]), z), X, Y, Z, name=f"step {k + 1}")
    if b.braceheight and len(rects) > len(sy):
        a.place(rects[len(sy)], (0.0, 0.0, 0.0), X, Z, neg(Y), name="brace")
    for x0 in [-t] + positions(b.sx, t) + [b.x]:
        a.place(_helper(p, "free").first(), (x0, -y, 0.0), Y, Z, X, name="side")


@placement("WallPinRow")
def wall_pin_row(a: Assembly) -> None:
    """Side and support profiles hold a back plate (on the wall) and a front plate, both
    leaning back by angle; the pin plate runs between them at height 2t, pins to the front."""
    b = a.box
    t = a.t
    p = a.parts
    h, x = b.h, b.x
    ar = math.radians(b.angle)
    face = b.edges["a"].margin()
    up = (0.0, math.sin(ar), math.cos(ar))       # along the plates
    out = (0.0, -math.cos(ar), math.sin(ar))     # through the plates, away from the wall
    base = (0.0, -math.sin(ar) * h, 0.0)         # bottom of the back plate's wall side
    sides = p.where(lambda q: "WallPinRow.sideWall" in q.callers)
    supports = p.where(lambda q: "WallPinRow.supportWall" in q.callers)
    for x0 in (-t, x):
        _wall_side(a, sides.first(), x0, face=face)
    z0 = 0.0 if b.angle > 0.001 else h / 2  # upright: the supports only hold the front plate
    for i in range(1, b.hooks - 1):
        _wall_side(a, supports.first(), i * x / (b.hooks - 1) - t / 2, "support", face, z0)
    rects = _helper(p, "rectangularWall")
    if len(rects) < 3:
        return
    pins, front, back = rects[0], rects[1], rects[2]
    a.place(back, base, X, up, out, name="back")
    a.place(front, add(base, out, 4 * t), X, up, out, name="front")
    a.place(pins, add(add(base, out, 4 * t), up, 1.5 * t), X, neg(out), up, name="pins")


@placement("WallPliersHolder")
def wall_pliers_holder(a: Assembly) -> None:
    """Braces (the first two outside the back plate, the others on its holes) carry a front
    bar at their top front."""
    b = a.box
    t = a.t
    p = a.parts
    rects = _helper(p, "rectangularWall")
    if len(rects) < 2:
        return
    front, back = rects[0], rects[1]
    w, d = back.x, b.y
    face = b.edges["b"].spacing() + t  # braces start at b.spacing()
    braces = _helper(p, "free")
    for x0 in (-t, w):
        _wall_side(a, braces.first(), x0, "brace", face)
    for c in positions(b.sx, t):
        _wall_side(a, braces.first(), c - t / 2, "brace", face)
    _wall_back(a, back)
    a.place(front, (0.0, -d + t, b.h_t - b.h), X, Z, neg(Y), name="front")


@placement("WallRollHolder")
def wall_roll_holder(a: Assembly) -> None:
    """Two sides (wall edge B along their local x = height) on a rounded back plate, each
    braced by a horizontal triangle on its outside. The axle rings stay 2D."""
    b = a.box
    t = a.t
    p = a.parts
    w, h, ax = b.width, b.height, b.axle
    m = b.edges["B"].margin()
    for x0 in (h / 4, h / 4 + t + w):
        a.place(_helper(p, "free").first(), (x0, m + t, 0.0), Z, neg(Y), X, name="side")
    _wall_back(a, _helper(p, "roundedPlate").first())
    zc = h - 3 * t - ax / 2
    tris = _helper(p, "rectangularTriangle")
    if len(tris) == 2:
        a.place(tris[0], (0.0, 0.0, zc - t / 2), X, neg(Y), Z, name="brace")
        a.place(tris[1], (w + h / 2 + 2 * t, 0.0, zc - t / 2), neg(X), neg(Y), Z, name="brace")


@placement("DrillStand", "WallDrillBox")
def drill_stand(a: Assembly) -> None:
    """Rows (sy) of compartments (sx) with a bottom sloping down to the right by
    extra_height; the top of each row is level. Inner walls interlock with slots.
    World: inner space x [0, x], y [0, y] (front to back), z from the right side's foot."""
    b = a.box
    t = a.t
    p = a.parts
    x, y, sx, sy, sh, eh = b.x, b.y, b.sx, b.sy, b.sh, b.extra_height
    wall = b.__class__.__name__ == "WallDrillBox"
    ang = math.atan(eh / x)

    def drawn(func):
        return p.where(lambda q: f"DrillStand.{func}" in q.callers)

    # Front and back: inner left at local x = edges[3].spacing(), the bottom cut line at the
    # left at local y = eh + edges[0].margin() (world z = eh).
    outs = drawn("xOutsideWall")
    for part, y0, n, edges in ((outs.first(), 0.0, neg(Y), "hFeF"),
                               (None, y + t, Y, "hCec" if wall else "hfef")):
        part = part or outs.first()
        e0, e3 = b.edges[edges[0]], b.edges[edges[3]]
        a.place(part, (-e3.spacing(), y0 - (t if n == Y else 0.0), -e0.margin()), X, Z, n,
                name="front" if n != Y else "back")
    for nr, part in enumerate(drawn("xWall"), start=1):
        y0 = sum(sy[:nr]) + (nr - 1) * t
        a.place(part, (-t, y0 + t, t), X, Z, neg(Y), name=f"row wall {nr}")
    for nr, part in enumerate(drawn("yWall"), start=1):
        x0 = sum(sx[:nr]) + (nr - 1) * t
        eh_nr = eh * x0 / x
        a.place(part, (x0, -t, eh + 2 * t - eh_nr), Y, Z, X, name=f"column wall {nr}")
    # Sides: the left one stands on a foot of eh + 2t (DrillStand) or 2t, hanging eh higher
    # (WallDrillBox); the right one on 2t. DrillStand's stackable bottom edge adds feet below.
    sides = drawn("sideWall")
    e0 = b.edges["e" if wall else "š"]
    z_left = 0.0 if not wall else eh
    a.place(sides.first(), (-t, -t, z_left - e0.spacing()), Y, Z, X, name="left side")
    a.place(sides.first(), (x, -t, -e0.spacing()), Y, Z, X, name="right side")
    # Bottom: centred 1.5t (vertically) above the slanted cut line, its left end clipped by
    # t * tan(angle).
    d = (math.cos(ang), 0.0, -math.sin(ang))
    up = (math.sin(ang), 0.0, math.cos(ang))
    origin = add(add((0.0, 0.0, eh + 1.5 * t), up, -t / 2), d, t * math.tan(ang))
    a.place(_helper(p, "rectangularWall").first(), origin, d, Y, up, name="bottom")


@placement("WallWrenchHolder")
def wall_wrench_holder(a: Assembly) -> None:
    """Back plate with slots, two sides with the wrench slots at the front."""
    b = a.box
    t = a.t
    p = a.parts
    w = b.x - 2 * t
    sides = p.where(lambda q: q.x == b.depth)
    if not sides:
        return
    h = sides[0].y
    f = a.frame(w, b.depth, h)
    for x0 in (-t, w):
        a.place(sides.first(), (x0, 0.0, 0.0), Y, Z, X, name="side")
    f.back(p.first())


@placement("WallPlaneHolder")
def wall_plane_holder(a: Assembly) -> None:
    """Two sides hanging on the wall (a edges), a floor, two back plates and a front lip."""
    b = a.box
    t = a.t
    p = a.parts
    l, w, h, hl = b.length, b.width, b.height, b.hold_length
    d = h + 4 * t  # side depth; sides run from the wall (y = d) to the front (y = 0)
    sides = p.where(lambda q: q.chars == "eeea")
    a.place(sides.first(), (0.0, d, 0.0), neg(Y), Z, neg(X), name="side")
    a.place(sides.first(), (w, d, 0.0), neg(Y), Z, X, name="side")
    a.place(p.edges("efFf").first(), (0.0, 0.0, t), X, Y, Z, name="floor")
    back = (w, d - 2 * t)
    a.place(p.edges("ffef").first(), (*back, 2 * t), neg(X), Z, Y, name="back")
    a.place(p.where(lambda q: q.chars == "efef" and abs(q.y - 0.25 * l) < 1e-6).first(),
            (*back, 2 * t + 0.75 * l), neg(X), Z, Y, name="back")
    a.place(p.where(lambda q: q.chars == "efef" and abs(q.y - hl) < 1e-6).first(),
            (0.0, 2 * t, 2 * t + l - hl), X, Z, neg(Y), name="lip")


@placement("WallTypeTray")
def wall_type_tray(a: Assembly) -> None:
    """TypeTray hung on the wall: the back is back_height taller and carries the mounts."""
    b = a.box
    t = a.t
    p = a.parts
    x = sum(b.sx) + t * (len(b.sx) - 1)
    y = sum(b.sy) + t * (len(b.sy) - 1)
    f = a.frame(x, y, b.h)
    rects = _helper(p, "rectangularWall")
    sides = _helper(p, "trapezoidSideWall")
    f.front(rects.first())
    f.back(rects.first())
    # sx and sy are counted from the front left, also on the floor (drawn from inside).
    if b.bottom_edge != "e":
        f.bottom(rects.first(), rot=180, flip=True)
    for y0 in positions(b.sy, t):
        f.inner_x(rects.first(), y0)
    f.right(sides.first())  # h edge at the front, B at the back
    f.left(sides.first())
    inner_y = sides if b.all_mounts else rects
    for x0 in positions(b.sx, t):
        f.inner_y(inner_y.first(), x0)


@placement("WallStackableBin")
def wall_stackable_bin(a: Assembly) -> None:
    """Back plate with the front face at y = 0, the bin reaching to -y. The sides' front
    profile (j edge) holds a slope tilted forward by angle and an optional upright label
    panel; the strips under the bottom panel stabilise the bin when stacked."""
    b = a.box
    t = a.t
    p = a.parts
    x = sum(b.sx) + t * (len(b.sx) - 1)
    back = p.label("back")
    if back is None:
        return
    y, h = p.label("bottom").y, back.y
    ang = math.radians(b.angle)
    fh = h * b.front
    w = fh * math.tan(ang)
    _wall_back(a, back)
    a.place(p.label("bottom"), (0.0, 0.0, 0.0), X, neg(Y), neg(Z))
    # Inner faces on the profile: the slope from the front bottom corner up to (-w, fh),
    # the label upright above it.
    up = (0.0, -math.sin(ang), math.cos(ang))
    a.place(p.label("slope"), (0.0, -y, 0.0), X, up, (0.0, -math.cos(ang), -math.sin(ang)))
    a.place(p.label("label"), (0.0, -y - w, fh), X, Z, neg(Y))
    # Sides and dividers are drawn with the front on the left, as seen from +x.
    stabilizers = p.drawn_by("StackableBaseEdge.__call__")
    for x0, label in ((-t, "left side"), (x, "right side")):
        side = p.label(label)
        a.place(side, (x0, -y, 0.0), Y, Z, X, flip=side.mirrored if side else False)
        strip = stabilizers.first()
        if strip is not None:
            a.place(strip, (t if x0 < 0 else x - t, -y, -t - strip.y), Y, Z, X,
                    name="stabilizer")
    for x0 in positions(b.sx, t):
        a.place(p.label("dividers"), (x0, -y, 0.0), Y, Z, X)


@placement("MagazineFile")
def magazine_file(a: Assembly) -> None:
    """Back (h) and front (hi) between two sides drawn without move(): their pieces' local
    frames are their bounding boxes, the outer lines of the F edges, with the back on the
    left. The second side is drawn turned by 180 degrees."""
    b = a.box
    t = a.t
    p = a.parts
    x, y = b.x, b.y
    rects = _helper(p, "rectangularWall")
    if len(rects) < 3:
        return
    back, front, bottom = rects[0], rects[1], rects[2]
    a.place(back, (x, y, 0.0), neg(X), Z, Y, name="back")
    a.place(front, (0.0, 0.0, 0.0), X, Z, neg(Y), name="front")
    a.place(bottom, (0.0, y, 0.0), X, neg(Y), neg(Z), name="bottom")
    for side in _helper(p, "free").where(lambda q: not q.callers):
        # Turned, the bottom edge runs along the top: the top right corner is cut (unturned it
        # is the low front's corner).
        turned = any(px > side.x - 0.5 and py > side.y - 0.5 for px, py in side.rec["outline"]["outer"])
        x0, n = (x, X) if turned else (0.0, neg(X))
        a.place(side, (x0, y + t, -t), neg(Y), Z, n, rot=180 if turned else 0, name="side")


@placement("NightLightBox")
def night_light_box(a: Assembly) -> None:
    """Box with a window in the front; inside, from the front: wood plates hanging in slots
    in the sides' tops, the acrylic diffuser, then the electronics compartment under a cover.
    The plates stand on two rails on the floor. The lid is hinged at the back on top."""
    b = a.box
    t = a.t
    p = a.parts
    m, bd, dpt, wpt, ips, n = (b.Margin, b.BackgroundDepth, b.DiffuserPlateThickness,
                               b.WoodPlateThickness, b.InterPlateSpacing, b.WoodPlatesCount)
    y = bd + dpt + (wpt + ips) * n + ips
    k = 4 if b.BoxStyle == "minimalist" else 8
    x = t * k + b.PlateVisibleWidth + m
    h = b.PlateVisibleHeight + t * k + m
    sw = b.edges["s"].startWidth()
    f = a.frame(x, y, h)
    f.front(p.label("front"))
    f.back(p.label("back"))
    # Optional face plate in front of the front wall, held by two pegs through both (in the
    # two bottom ones of three peg holes, 1.5t in from the corners).
    face = p.label("customizable face")
    if face is not None:
        a.place(face, (0.0, -t, 0.0), X, Z, neg(Y))
        pegs = p.where(lambda q: q.rec["helper"] == "rectangularWall" and not q.label)
        for x0 in (t, x - 2 * t):
            a.place(pegs.first(), (x0, 0.0, t), neg(Y), Z, X, name="peg")
    # The bottom's rail slots start at its local y = 0, the front.
    a.place(p.label("bottom"), (0.0, 0.0, 0.0), X, Y, neg(Z))
    # Sides (left drawn mirrored): front on the left, as seen from +x; the inner floor at sw.
    for left, x0, nx in ((True, 0.0, neg(X)), (False, x, X)):
        sides = p.drawn_by("NightLightBox.side").where(lambda q: q.mirrored == left)
        side = max(sides, key=lambda q: q.x * q.y, default=None)
        a.place(side, (x0, 0.0, -sw), Y, Z, nx, flip=left, name="left" if left else "right")
        for scrap in sides:  # the lid's pin outline drawn inside the hinge eye
            if scrap is not side:
                a.scrap(scrap)
    # Rails on the floor (holes centred 1.5t from the sides), the diffuser slot at their back.
    rail_len = 2 * t + dpt + (ips + wpt) * n
    back = ips - t - m / 2 + rail_len
    for x0, nx in ((2 * t, neg(X)), (x - 2 * t, X)):
        rail = p.drawn_by("NightLightBox.rail").first()
        a.place(rail, (x0, back, 0.0), neg(Y), Z, nx, flip=rail.mirrored if rail else False,
                name="rail")
    # Plates stand on the floor, their bodies M from the sides; centred in their slots.
    c = y - bd - dpt / 2 - m / 2
    a.place(p.drawn_by("NightLightBox.diffuserPlate").first(), (m, c + dpt / 2, 0.0),
            X, Z, neg(Y), name="diffuser", thickness=dpt)
    for i, plate in enumerate(p.drawn_by("NightLightBox.woodPlate")):
        ci = ips - m / 2 + wpt / 2 + i * (wpt + ips)
        # The body starts t + M/2 in; the ears at the top reach into the sides' slots.
        a.place(plate, (m / 2 - t, ci + wpt / 2, 0.0), X, Z, neg(Y),
                name=f"wood plate {i + 1}", thickness=wpt)
    # Guides through the sides' square holes, just in front of the diffuser.
    gy = y - bd - dpt - t - 1.5 * m
    gz = b.PlateVisibleHeight + t * (4 if k == 4 else 8) - sw
    for x0 in (-t, x - t):
        a.place(p.label("guide"), (x0, gy, gz), X, Z, Y)
    # Electronics cover: in the sides' top F edge (BD - 5t - M/2 long, ending 5t before the
    # back), its own f edges 1.5t in from its back edge.
    fc = y - 5 * t - (bd - 5 * t - m / 2) / 2
    yb = fc + 1.5 * t + (bd - 5 * t - m) / 2
    a.place(p.drawn_by("NightLightBox.elecCompartmentTop").first(), (0.0, yb, h - t),
            X, neg(Y), Z, name="electronics cover")
    # Lid on top of the walls, between the hinge eyes; its pins at the back.
    a.place(p.labelled("lid top").first(), (x, 0.0, h), Y, neg(X), Z)


@placement("WallHopper")
def wall_hopper(a: Assembly) -> None:
    """Sides are polygons (wall on the left at x = 0); the panels sit in their h edges."""
    b = a.box
    t = a.t
    p = a.parts
    x = sum(b.sx) + t * (len(b.sx) - 1)
    left = p.label("left")
    if left is None:
        return

    # Side drawing (sx, sy) -> world: the wall is at y = 0, the hopper reaches to -y.
    def world(sx: float, sy: float, x0: float = 0.0):
        return (x0, -sx, sy)

    def vec(dx: float, dy: float):
        return (0.0, -dx, dy)

    start = left.rec["params"]["start"]
    segs = _polygon_segments(left.rec["params"]["borders"], (0.0, 0.0))
    # The drawn edges of the side: segments 1, 2, 3 and 5 hold the panels in finger holes
    # (t to 2t inside the line), segment 7 is the wall edge with the back panel in [0, t].

    def panel(part, k: int, name: str) -> None:
        (sx, sy), (dx, dy), _ = segs[k]
        mx, my = -dy, dx  # inwards (counter-clockwise polygon)
        a.place(part, world(sx + mx * t, sy + my * t), X, vec(dx, dy), vec(mx, my), name=name)

    panel(p.label("bottom"), 1, "bottom")
    panel(p.label("slope"), 2, "slope")
    if b.label:
        panel(p.label("label"), 3, "label")
    panel(p.label("front"), 5, "front")
    wh = a.box.edges["h"].startWidth()
    a.place(p.label("back"), world(0.0, wh), X, Z, neg(Y))
    origin = (-start[0], -start[1])
    a.place(left, world(*origin), vec(1, 0), Z, neg(X))
    a.place(p.label("right"), world(*origin, x), vec(1, 0), Z, X, flip=True)
    # Dividers have f edges right on their lines, which lie on the panels' inner faces:
    # the same polygon without the h edge allowance, wh higher.
    for x0 in positions(b.sx, t):
        div = p.label("divider")
        if div is not None:
            ds = div.rec["params"]["start"]
            a.place(div, world(-ds[0], -ds[1] + wh, x0), vec(1, 0), Z, X)


@placement("WallRack")
def wall_rack(a: Assembly) -> None:
    """Back wall with shelves; each shelf has a front lip and two trapezoid side lips."""
    b = a.box
    t = a.t
    p = a.parts
    shelf, back = p.label("shelf 1"), p.label("back wall")
    if shelf is None or back is None:
        return
    x, y = shelf.x, shelf.y  # render() adjusts the sizes for "outside" only locally
    # The back wall is x + t wide; its holes for the side lips are on its inner edges.
    a.place(back, (x + t / 2, y, 0.0), neg(X), Z, Y)
    z = 0.0
    for k, h in enumerate(b.sh, 1):
        a.place(p.label(f"shelf {k}"), (0.0, 0.0, z), X, Y, Z)
        a.place(p.label(f"front lip {k}"), (0.0, 0.0, z + t), X, Z, neg(Y))
        # Lips: drawn with the front (front_height) on the left.
        a.place(p.label(f"right lip {k}"), (x, 0.0, z + t), Y, Z, X)
        a.place(p.label(f"left lip {k}"), (0.0, 0.0, z + t), Y, Z, neg(X))
        z += h


@placement("CompartmentBox")
def compartment_box(a: Assembly) -> None:
    """TypeTray with a sliding lid that rests on the inner walls, held by lips on the sides."""
    b = a.box
    t = a.t
    p = a.parts
    x = sum(b.sx) + t * (len(b.sx) - 1)
    y = sum(b.sy) + t * (len(b.sy) - 1)
    h = b.h
    f = a.frame(x, y, h)
    f.dims(x="sx", y="-sy", h="h")
    # Unlike in TypeTray, front and back are drawn as seen from inside.
    f.front(p.label("front"), flip=True)
    f.back(p.label("back"), flip=True)
    _outer_walls(a, f, {"left side": "left", "right side": "right", "bottom": "bottom"})
    for k, y0 in enumerate(positions(b.sy, t), 1):
        f.inner_x(p.label(f"inner x {k}"), y - y0 - t)
    for k, x0 in enumerate(positions(b.sx, t), 1):
        f.inner_y(p.label(f"inner y {k}"), x0, flip=True)
    # With split_lip=0 the one-piece lip is drawn by hand (not recorded): 2D only.
    lid = p.label("lid")
    if lid is not None:
        m = (x - lid.x) / 2  # side margin
        if b.handle == "lip":
            a.place(lid, (m, 0.0, h), X, Y, Z)
            a.place(p.label("lid lip"), (m, 0.0, h + t), X, Z, neg(Y))
        else:  # the lid also covers the front wall
            a.place(lid, (m, -t, h), X, Y, Z)
    # Lips on top of the side walls, overhanging the lid by t; their f edge joins the side.
    side = p.label("left side")
    hs = side.y if side is not None else h + t
    a.place(p.label("Lip Left"), (t, 0.0, hs), Y, neg(X), Z)
    a.place(p.label("Lip Right"), (x - t, 0.0, hs), Y, X, Z, flip=True)


# --- More boxes -----------------------------------------------------------------------

@placement("OpenBox")
def open_box(a: Assembly) -> None:
    """A wall at the front, two sides and a bottom; open at the top and the back."""
    p = a.parts
    walls = _helper(p, "rectangularWall")
    if len(walls) < 4:
        return
    front, side = walls[0], walls[1]
    f = a.frame(front.x, side.x, front.y)
    f.dims(x="x", y="y", h="h")
    f.front(walls.first())
    f.right(walls.first())  # f edge (left) at the front
    f.left(walls.first(), flip=True)
    f.bottom(walls.first())  # open (e) edge at the back


@placement("UnevenHeightBox")
def uneven_height_box(a: Assembly) -> None:
    """Four trapezoid walls (height0..3 at the corners, counter-clockwise from front left)
    and a lid whose walls make up the difference to the highest corner."""
    b = a.box
    t = a.t
    p = a.parts
    traps = _helper(p, "trapezoidWall")
    if len(traps) < 4:
        return
    w0, w1 = traps[0], traps[1]
    x, y = w0.x, w1.x
    h = [w0.rec["params"]["h0"], w0.rec["params"]["h1"], w1.rec["params"]["h1"],
         traps[2].rec["params"]["h1"]]
    f = a.frame(x, y, max(h))
    f.dims(x="x", y="y")
    for face in ("front", "right", "back", "left"):
        getattr(f, face)(traps.first())
    if b.bottom_edge != "e":
        f.bottom(_helper(p, "rectangularWall").first())
    if not b.add_lid:
        return
    top = max(h) + b.lid_height
    a.place(_helper(p, "rectangularWall").first(), (0.0, 0.0, top), X, Y, Z, name="lid")
    # Lid walls are drawn upside down: edge 0 joins the lid, local x runs from the corner
    # given here. Walls of zero height are not drawn.
    lh = [top - v for v in h]
    for c0, c1, origin, u, n in ((0, 3, (0.0, 0.0, top), Y, neg(X)),
                                 (3, 2, (0.0, y, top), X, Y),
                                 (2, 1, (x, y, top), neg(Y), X),
                                 (1, 0, (x, 0.0, top), neg(X), neg(Y))):
        if lh[c0] == 0.0 and lh[c1] == 0.0:
            continue
        a.place(traps.first(), origin, u, neg(Z), n, name="lid wall")


@placement("SlidingLidBox")
def sliding_lid_box(a: Assembly) -> None:
    """The lid slides out at the front between lower rails and top rails on the sides."""
    b = a.box
    t = a.t
    p = a.parts
    side = p.label("left side")
    if side is None:
        return
    x, y, h = b.x, b.y, b.h
    hp = side.y  # h + gap
    f = a.frame(x, y, h)
    f.dims(x="x", y="y", h="h")
    _outer_walls(a, f, {"left side": "left", "right side": "right", "back": "back",
                        "front": "front"})
    a.place(p.label("bottom"), (0.0, 0.0, 0.0), Y, X, neg(Z))
    # Rails run from the back (local x = 0) to the front, f edge (local y = 0) at the side.
    # The right ones are drawn mirrored: flip keeps the drawn shape.
    a.place(p.label("bottom left rail"), (0.0, y, h - t), neg(Y), X, Z)
    a.place(p.label("bottom right rail"), (x, y, h - t), neg(Y), neg(X), Z, flip=True)
    a.place(p.label("top left rail"), (0.0, y, hp), neg(Y), X, Z)
    a.place(p.label("top right rail"), (x, y, hp), neg(Y), neg(X), Z, flip=True)
    rail = p.label("back rail")
    if rail is not None:
        rm = (x - rail.x) / 2
        a.place(rail, (x - rm, y, hp), neg(X), neg(Y), Z)
    lid = p.label("lid")
    if lid is not None:
        m = (x - lid.y) / 2
        a.place(lid, (m, y, h), neg(Y), X, Z)  # E edge (and grip hole) at the front
        lip = p.label("lid lip")
        if lip is not None:
            a.place(lip, ((x - lip.x) / 2, 0.0, h + t), X, Z, neg(Y))


@placement("PenHolderBox")
def pen_holder_box(a: Assembly) -> None:
    """Four walls with two hole plates below the top."""
    b = a.box
    t = a.t
    p = a.parts
    f = a.frame(b.x, b.y, b.h)
    f.dims(x="x", y="y", h="h")
    _outer_walls(a, f, {"front_face": "front", "back_face": "back", "left_side": "left",
                        "right_side": "right", "bottom": "bottom"})
    z1 = b.h - b.plate1_offset - t / 2  # centre of the upper plate
    f.plate(p.label("plate_1"), z1 - t / 2)
    f.plate(p.label("plate_2"), z1 - b.plate_gap - t / 2)


@placement("ElectronicsBox")
def electronics_box(a: Assembly) -> None:
    """Walls on a bottom plate (flanged for outside mounts); the top rests on corner
    triangles, fingered into the walls just below it."""
    b = a.box
    t = a.t
    p = a.parts
    f = a.frame(b.x, b.y, b.h)
    f.sub(0, 0, 0, b.x, b.y, b.h - 2 * t).dims(x="x", y="y", h="h")  # h: below the top
    _outer_walls(a, f, {"Wall 1": "front", "Wall 2": "right", "Wall 3": "back",
                        "Wall 4": "left", "Bottom": "bottom"})
    f.plate(p.label("Top"), b.h - t)
    # Right angle (local (tr, 0)) in the corner, legs along the walls (a, b point inwards).
    tr = b.triangle
    corners = [((0, 0), X, Y), ((b.x, 0), Y, neg(X)), ((b.x, b.y), neg(X), neg(Y)),
               ((0, b.y), neg(Y), X)]
    for tri, ((cx, cy), u, v) in zip(_helper(p, "rectangularTriangle"), corners):
        origin = (cx + u[0] * tr, cy + u[1] * tr, b.h - 2 * t)
        a.place(tri, origin, neg(u), v, Z, name="corner triangle")


@placement("DisplayCase")
def display_case(a: Assembly) -> None:
    p = a.parts
    w1, w2 = p.label("Wall 1"), p.label("Wall 2")
    if w1 is None or w2 is None:
        return
    f = a.frame(w1.x, w2.x, w1.y)  # sizes from the parts: "outside" is applied locally
    _outer_walls(a, f, {"Wall 1": "front", "Wall 2": "right", "Wall 3": "back",
                        "Wall 4": "left", "Top": "top", "Bottom": "bottom"})


@placement("StorageRack")
def storage_rack(a: Assembly) -> None:
    """Open at the front: two sides, a back, bottom and top plates and rails for the drawers."""
    b = a.box
    t = a.t
    p = a.parts
    x, d = b.x, b.depth
    h = sum(b.sh) + t * (len(b.sh) - 1)
    f = a.frame(x, d, h)
    walls = p.where(lambda q: q.y == h)
    f.right(walls.first())  # F edge (right) at the back
    f.left(walls.first())
    f.back(walls.first())
    levels = []
    z = 0.0
    for s in b.sh[:-1]:
        z += s
        levels.append(z)
        z += t
    plates = p.where(lambda q: q.chars == "fffE")
    # Plates and rails: local x from the front, local y from the side inwards.
    bottom = -t if b.bottom_edge != "e" else levels.pop(0)
    top = h if b.top_edge != "e" else levels.pop()
    for z in (bottom, top):
        a.place(plates.first(), (x, 0.0, z), Y, neg(X), Z, name="plate")
    for z in levels:
        a.place(p.edges("ffee").first(), (x, 0.0, z), Y, neg(X), Z, name="rail")
        a.place(p.edges("feef").first(), (0.0, d, z), neg(Y), X, Z, name="rail")


@placement("SlantedTray")
def slanted_tray(a: Assembly) -> None:
    """Back wall (drawn upside down), bottom, low front and trapezoid sides/dividers."""
    b = a.box
    t = a.t
    p = a.parts
    x = sum(b.sx) + t * (len(b.sx) - 1)
    f = a.frame(x, b.y, b.h)
    f.dims(x="sx", y="y", h="h")
    rects = _helper(p, "rectangularWall")
    f.back(rects.first(), rot=180)
    f.bottom(rects.first())
    f.front(rects.first())
    # Trapezoids: the high end (left) at the back.
    sides = _helper(p, "trapezoidWall")
    f.left(sides.first())
    for x0 in positions(b.sx, t):
        f.inner_y(sides.first(), x0, flip=True)
    f.right(sides.first(), flip=True)


@placement("TwoPiece")
def two_piece(a: Assembly) -> None:
    """Inner box on a bottom plate with a rim; the outer box slips over it upside down."""
    b = a.box
    t = a.t
    walls = _helper(a.parts, "rectangularWall")
    if len(walls) < 10:
        return
    x, y, hi, h = walls[0].x, walls[1].x, walls[0].y, walls[4].y
    play = b.play * t
    inner = a.frame(x, y, hi)
    for face in ("front", "right", "back", "left"):
        getattr(inner, face)(walls.first())
    o = t + play
    outer = a.frame(x + 2 * o, y + 2 * o, h, origin=(-o, -o, 0.0), name="lid")
    for face in ("front", "right", "back", "left"):
        getattr(outer, face)(walls.first(), rot=180)  # f edge (bottom) at the top
    inner.bottom(walls.first())
    outer.top(walls.first())


@placement("SlidingDrawer")
def sliding_drawer(a: Assembly) -> None:
    """Outer box open at the front (y = 0) with the drawer pushed in."""
    b = a.box
    t = a.t
    p = a.parts
    ob, ow = p.label("out box bottom"), p.label("out box wall")
    if ob is None or ow is None:
        return
    y, x, h = ob.x, ob.y, ow.y
    play = b.play * t
    f = a.frame(x, y, h)
    # Bottom/top and sides run from the front (local x = 0, the open e edge).
    a.place(ob, (0.0, 0.0, 0.0), Y, X, neg(Z))
    a.place(p.label("out box top"), (x, 0.0, h), Y, neg(X), Z)
    f.right(p.label("out box wall"))
    f.left(p.label("out box wall"), flip=True)
    f.back(p.label("out box wall"))
    walls = p.labelled("in box wall")
    if len(walls) < 4:
        return
    back, side, front = walls[0], walls[1], walls[3]
    x2, y2 = back.x, side.x
    d = a.frame(x2, y2, side.y, origin=(t + play, t, t), name="drawer")
    d.back(back)
    d.right(walls.first())
    d.left(walls.first())
    d.front(front)
    d.bottom(p.label("in box bottom"), rot=90)


@placement("FlexBox")
def flex_box(a: Assembly) -> None:
    """Two rounded sides (latch at the top left) with a flex wall wrapped around them,
    starting below the latch and running down, along the bottom, up the back, back over the
    top to the latch. Middle sides are dividers in the wall's finger holes."""
    b = a.box
    t = a.t
    p = a.parts
    x, y, h, l = b.x, b.y, b.h, b.latchsize
    r = max(b.radius, 0.01)
    c4 = math.pi * r / 2
    wall = _helper(p, "free").drawn_by("FlexBox.surroundingWall").first()
    # The wall's lower edge (0.25 t above its frame) is the left side's outer face.
    b1 = h - 2 * r - l
    b2 = b1 + c4 + y - 2 * r
    b3 = b2 + c4 + h - 2 * r
    b4 = b3 + c4 + y - 2 * r
    a.place(wall, (-1.25 * t, 0.0, h - r - l), neg(Z), X, neg(Y), name="flex wall",
            bend=[(x0, 90, r) for x0 in (b1, b2, b3, b4)])
    sides = list(_helper(p, "free").drawn_by("FlexBox.flexBoxSide"))
    if len(sides) < 2:
        return
    # Side frames are their move boxes: the rounded outline starts t in.
    a.place(sides[0], (x, -t, -t), Y, Z, X, name="right side")
    a.place(sides[-1], (0.0, -t, -t), Y, Z, neg(X), flip=sides[-1].mirrored, name="left side")
    # The wall's finger holes (upstream) sit one thickness before the compartment ends.
    for div, x0 in zip(sides[1:-1], positions(b.sx, t)):
        a.place(div, (x0 - t, -t, -t), Y, Z, X, name="divider")


def _flex_sides(a: Assembly, func: str, x: float) -> None:
    """Rounded sides drawn by func, frames are their move boxes with the outline t in: the
    first (unmirrored) on the right, the mirrored one on the left."""
    t = a.t
    sides = list(_helper(a.parts, "free").drawn_by(func))
    if len(sides) < 2:
        return
    a.place(sides[0], (x, -t, -t), Y, Z, X, name="right side")
    a.place(sides[-1], (0.0, -t, -t), Y, Z, neg(X), flip=sides[-1].mirrored, name="left side")


@placement("FlexBox2", "FlexBox4")
def flex_box2(a: Assembly) -> None:
    """Flex wall from the bottom of the back up, over the rounded top and down the front:
    to the latch (FlexBox2, with a front wall below) or all the way (FlexBox4)."""
    b = a.box
    t = a.t
    p = a.parts
    x, y, h = b.x, b.y, b.h
    r = max(b.radius, 0.01)
    c4 = math.pi * r / 2
    wall = _helper(p, "free").drawn_by("surroundingWall").first()
    # Starts t in (its end fingers go into the bottom), lower edge 0.25 t in: the left side's
    # outer face.
    a.place(wall, (-1.25 * t, y, -t), Z, X, Y, name="flex wall",
            bend=[(t + h - r, 90, r), (t + h - r + c4 + y - 2 * r, 90, r)])
    _flex_sides(a, "flexBoxSide", x)
    rects = _helper(p, "rectangularWall")
    # The bottom is drawn y by x; FlexBox4's open edge is at the front (under the latch).
    a.place(rects.first(), (x, y, 0.0), neg(Y), neg(X), neg(Z), name="bottom")
    a.place(rects.first(), (0.0, 0.0, 0.0), X, Z, neg(Y), name="front")


@placement("FlexBox5")
def flex_box5(a: Assembly) -> None:
    """Pill shaped box standing on one of its two sides (top and bottom here) with the
    flex wall around them, starting after the latch."""
    b = a.box
    t = a.t
    p = a.parts
    h, l, ls = b.h, b.l, b.latchsize
    r1, r2 = b.top_diameter / 2, b.bottom_diameter / 2
    th = math.radians(180 + 2 * b.a)
    # Side outline (in its move box): along y = t from (r2, t), around r1, latch, back.
    px, py = r2 + l, t + r1
    px, py = px + r1 * math.sin(th) + ls * math.cos(th), py - r1 * math.cos(th) + ls * math.sin(th)
    u = (math.cos(th), math.sin(th), 0.0)
    n = (math.sin(th), -math.cos(th), 0.0)
    wall = _helper(p, "free").drawn_by("surroundingWall").first()
    a.place(wall, (px, py, -1.25 * t), u, Z, n, name="flex wall",
            bend=[(l - ls, 180 - 2 * b.a, r2), (l - ls + math.radians(180 - 2 * b.a) * r2 + l, 180 + 2 * b.a, r1)])
    sides = list(_helper(p, "free").drawn_by("flexBoxSide"))
    if len(sides) < 2:
        return
    a.place(sides[0], (0.0, 0.0, h), X, Y, Z, name="top")
    a.place(sides[-1], (0.0, 0.0, 0.0), X, Y, neg(Z), flip=sides[-1].mirrored, name="bottom")


@placement("UBox")
def u_box(a: Assembly) -> None:
    """Two U shaped sides with the flex wall around them from the front top, down, along the
    bottom and up the back; lids from _TopEdge."""
    b = a.box
    t = a.t
    p = a.parts
    x, y, h = b.x, b.y, b.h
    r = max(b.radius, 0.01)
    cl = math.pi * r / 2
    wall = p.label("wall")
    if wall is not None:
        # Starts after the front top edge's spacing; the F edges' outer lines are the sides'
        # outer faces.
        back = b.topEdges(b.top_edge)[1]
        e0 = b.edges.get(back, back).spacing()
        a.place(wall, (-t, 0.0, h + e0), neg(Z), X, neg(Y), name="flex wall",
                bend=[(e0 + h - r, 90, r), (e0 + h - r + cl + y - 2 * r, 90, r)])
        # Hinged lids (i, k): the flush hinges' pin slots are drawn inside the wall's eyes.
        for scrap in p.where(lambda q: q.label == "wall"):
            a.scrap(scrap)
    w = b.edges["f"].spacing()
    # The U is symmetric front to back: the left one is turned to be seen from outside.
    a.place(p.label("left"), (0.0, y + w, -w), neg(Y), Z, neg(X))
    a.place(p.label("right"), (x, -w, -w), Y, Z, X)
    place_lids(a, a.frame(x, y, h), b.top_edge)


def _surrounding_wall(a: Assembly, origin, x: float, y: float, r: float, pieces: int,
                      left="D", right="d") -> None:
    """Boxes.surroundingWall(x, y, r, ..., pieces) around a roundedPlate(x, y, r) whose top
    face's corner is at origin; the wall's lower edge line is t below. It starts in the middle
    of the front and runs counter-clockwise. The pieces share the move box frame."""
    b = a.box
    t = a.t
    walls = list(_helper(a.parts, "free").drawn_by("Boxes.surroundingWall"))
    if not walls:
        return
    left, right = b.edges.get(left, left), b.edges.get(right, right)
    c4 = (r + b.burn) * math.pi * 0.5 / b.edges["X"].settings.stretch
    angle = 90
    if pieces <= 2 and y - 2 * r < 1e-3:
        c4 *= 2
        angle = 180
        sides = (x / 2 - r, x - 2 * r, x - 2 * r)
        pieces += 1
    else:
        sides = (x / 2 - r, y - 2 * r, x - 2 * r, y - 2 * r, x - 2 * r)
    rr = max(r, 0.01)
    stretch = rr * math.radians(angle) / c4 if c4 > 1e-6 else 1.0
    # Path position s, sheet x of each piece's start minus its path start.
    s, start, piece_s = 0.0, left.spacing(), 0.0
    starts, offsets, ends, bends = [start], [start], [], []
    for nr, l in enumerate(sides):
        if b._splitWall(pieces, nr) and nr > 0:
            s += l / 2
            ends.append(start + s - piece_s)
            if nr == len(sides) - 1:
                break
            start += s - piece_s + right.margin() + left.margin() + b.spacing
            piece_s = s
            starts.append(start)
            offsets.append(start - s)
            s += l / 2
        else:
            s += l
        bends.append((s, angle, rr, stretch))
        s += c4
    if len(ends) < len(offsets):
        ends.append(start + s - piece_s)
    for wall in walls:
        xs = [q[0] for q in wall.rec["outline"]["outer"]]
        mid = (min(xs) + max(xs)) / 2
        k = min(range(len(starts)), key=lambda i: abs(mid - (starts[i] + ends[i]) / 2))
        o = offsets[k]  # sheet x - path position
        a.place(wall, add(add(origin, X, x / 2 - o), Z, -t), X, Z, neg(Y), name="wall",
                bend=[(s0 + o, *rest) for s0, *rest in bends])


@placement("RoundedBox")
def rounded_box(a: Assembly) -> None:
    """Rounded plates (bottom, floors in the wall's finger holes, top, optional lid) with the
    flex wall around them."""
    b = a.box
    t = a.t
    x, y, r = b.x, b.y, b.radius
    plates = list(_helper(a.parts, "roundedPlate"))
    zs = [-t]
    for dh in b.sh[:-1]:
        zs.append(zs[-1] + t + dh)
    zs.append(sum(b.sh) + t * (len(b.sh) - 1))
    names = ["bottom"] + ["floor"] * (len(b.sh) - 1) + ["top"]
    for plate, z, name in zip(plates, zs, names):
        a.place(plate, (0.0, 0.0, z), X, Y, Z, name=name)
    if len(plates) > len(zs):
        re = b.edges[b.edge_style].spacing()
        a.place(plates[len(zs)], (-re, -re, zs[-1] + t), X, Y, Z, name="lid")
    _surrounding_wall(a, (0.0, 0.0, 0.0), x, y, r, b.wallpieces)


@placement("FlexBox3")
def flex_box3(a: Assembly) -> None:
    """Flex wall up the back, around the top back edge into the lid top, which is wider by
    the clearance d each side; lid sides and a front lip hang from it over the box."""
    b = a.box
    t = a.t
    p = a.parts
    x, y, z, h, d = b.x, b.y, b.z, b.h, b.d
    r = max(b.radius, 0.01)
    wall = _helper(p, "free").drawn_by("FlexBox3.surroundingWall").first()
    # Its flex is 0.95 of the quarter circle; the lower edge is d + t in: the left side's
    # outer face.
    a.place(wall, (-d - 2 * t, y, -t), Z, X, Y, name="flex wall", bend=[(t + z - r, 90, r, 1 / 0.95)])
    _flex_sides(a, "FlexBox3.flexBoxSide", x)
    rects = _helper(p, "rectangularWall")
    bottom, lip, front = (list(rects) + [None] * 3)[:3]
    a.place(bottom, (x, y, 0.0), neg(Y), neg(X), neg(Z), name="bottom")
    a.place(lip, (-d - t, -t, z), neg(Z), X, neg(Y), name="lid front")
    a.place(front, (0.0, 0.0, 0.0), X, Z, neg(Y), name="front")
    if r < h:
        base_l = y + 2 * t
    else:
        ang = math.acos((r - h) / (r + t))
        base_l = y + (r + t) * math.sin(ang) - r + t
    # Lid sides: their top line (h + t up) is the lid top's upper face, the lip's outer face
    # at base_l.
    lid_sides = list(_helper(p, "free").drawn_by("FlexBox3.lidSide"))
    if len(lid_sides) >= 2:
        a.place(lid_sides[0], (x + t + d, base_l - t, z - h), Z, neg(Y), X, name="lid right")
        a.place(lid_sides[-1], (-d - t, base_l - t, z - h), Z, neg(Y), neg(X),
                flip=lid_sides[-1].mirrored, name="lid left")


# --- Tray layouts ---------------------------------------------------------------------

@placement("TrayLayout")
def tray_layout(a: Assembly) -> None:
    _tray_layout(a, editable=True)


@placement("GridfinityTrayLayout")
def gridfinity_tray_layout(a: Assembly) -> None:
    """TrayLayout with a generated layout; the pads (one per cell, up to 4) go under the corner
    grid cells, or spread along a grid one cell wide. Its layout text is not edited from 3D
    (the UI does that for TrayLayout only)."""
    b = a.box
    t = a.t
    _tray_layout(a, editable=False)
    foot = b.opening - b.opening_margin
    p = b.pitch
    c0 = -t - b.margin / 2 + p / 2  # first cell centre, like baseplate_etching
    pads = a.parts.drawn_by("GridfinityTrayLayout.generatePad")
    n = max(b.nx, b.ny)
    if min(b.nx, b.ny) == 1 and len(pads) > 1:
        steps = [round(k * (n - 1) / (len(pads) - 1)) for k in range(len(pads))]
        cells = [(c0 + k * p, c0) if b.nx > 1 else (c0, c0 + k * p) for k in steps]
    else:
        cells = [(c0 + i * p, c0 + j * p) for i in sorted({0, b.nx - 1}) for j in sorted({0, b.ny - 1})]
    for cx, cy in cells:
        a.place(pads.first(), (cx - foot / 2, cy - foot / 2, -t), X, Y, neg(Z), name="pad")


def _tray_layout(a: Assembly, editable: bool) -> None:
    """Walls from the layout grid: box.x/box.y are the column/row sizes, hwalls[j][i] the wall
    pieces on grid line j (0 = back) above row j, vwalls[j][i] those on line i (0 = left) in
    row j. walls() draws one wall per continuous run: lines y = 0..ly, then lines x = 0..lx."""
    b = a.box
    t = a.t
    sx, sy = list(b.x), list(b.y)
    lx, ly = len(sx), len(sy)
    # Grid lines: material of x line i in [xs[i], xs[i] + t], of y line j in [ys[j], ys[j] + t].
    xs = [-t]
    for s in sx:
        xs.append(xs[-1] + t + s)
    ys = [-t] * (ly + 1)
    for j in range(ly - 1, -1, -1):
        ys[j] = ys[j + 1] + t + sy[j]
    x, y = xs[-1], ys[0]
    f = a.frame(x, y, b.h)
    # Grid indices -> layout text indices (they differ with 0 mm rows/columns at the edges).
    ci, ri = b.colIndex, b.rowIndex
    xl, yl = b.xLineIndex, b.yLineIndex
    # Liners (0 mm edge rows/columns, see TrayLayout.removeZeroSizes) against the outer walls'
    # inner faces; drawn by liners(), which walls() calls at the end.
    liners = iter(_helper(a.parts, "rectangularWall").drawn_by("TrayLayout.liners"))
    for p in getattr(b, "liner_pieces", []):
        s, side = p["start"], p["side"]
        if side in ("back", "front"):
            line = yl(0) + 1 if side == "back" else yl(ly) - 1
            a.place(next(liners, None), (xs[s] + t, ys[0] if side == "back" else t, 0.0),
                    X, Z, neg(Y), name=f"liner x {ci(s) + 1}/{line + 1}")
        else:
            line = xl(0) + 1 if side == "left" else xl(lx) - 1
            a.place(next(liners, None), (t if side == "left" else xs[lx], ys[s] - (t if p["cut0"] else 0.0), 0.0),
                    neg(Y), Z, neg(X), name=f"liner y {line + 1}/{ri(s) + 1}")
    walls = iter(_helper(a.parts, "rectangularWall").drawn_by("TrayLayout.walls").not_drawn_by("TrayLayout.liners"))
    for j in range(ly + 1):
        for start, end in _runs(b.hwalls[j][:lx]):
            a.place(next(walls, None), (xs[start] + t, ys[j] + t, 0.0), X, Z, neg(Y),
                    name=f"wall x {ci(start) + 1}/{yl(j) + 1}")
    for i in range(lx + 1):
        for start, end in _runs([row[i] for row in b.vwalls[:ly]]):
            a.place(next(walls, None), (xs[i] + t, ys[start], 0.0), neg(Y), Z, neg(X),
                    name=f"wall y {xl(i) + 1}/{ri(start) + 1}")
    # The base plate is drawn from above with a margin of the F edge's width.
    w = b.edges["F"].startWidth()
    a.place(_helper(a.parts, "free").drawn_by("TrayLayout.base_plate").first(),
            (-w, -w, -t), X, Y, Z, name="bottom")
    inner = (any(any(row) for row in b.hwalls[1:ly]) or any(any(row[1:lx]) for row in b.vwalls)
             or any(any(v) for v in getattr(b, "liner", {}).values()))
    place_lids(a, f, None, inner=(b.hi or b.h) if inner else None)
    _card_ramps(a, _tray_ramp_cells(b, xs, ys), _ramp_limit(b, b.h))
    if not editable:
        return
    f.dims(h="h")
    # Column and row sizes as written in the layout ("outside" scales box.x/box.y down).
    given = SimpleNamespace()
    type(b).parse(given, b.layout.split("\n"))
    f.chain("layout", "x", given.x, label="x", axis="x")
    f.chain("layout", "-y", given.y, label="y", axis="y")
    _inner_height(f, xs[1:-1], ys[1:-1], b.hi)
    # Draggable lines of the layout's grid, including the 0 mm rows/columns.
    lsx, lsy = getattr(b, "layout_x", sx), getattr(b, "layout_y", sy)
    oxs = [-t]
    for s in lsx:
        oxs.append(oxs[-1] + t + s)
    oys = [-t] * (len(lsy) + 1)
    for j in range(len(lsy) - 1, -1, -1):
        oys[j] = oys[j + 1] + t + lsy[j]
    f.walls("layout", "x", oxs[1:-1], given.x, lsx, b.hi, label="x", axis="x")
    f.walls("layout", "-y", oys[1:-1], given.y, lsy, b.hi, label="y", axis="y")
    # Editable in 3D: every wall piece of the grid and every floor cell. On/off as in the layout
    # text (the toggle flips that): next to a liner the built outer wall is outer or liner.
    sliding = getattr(getattr(b, "lidSettings", None), "style", None) == "sliding"
    for j in range(ly + 1):
        h = (b.h + t if sliding else b.h) if j == 0 else ((b.h - t if sliding else b.h) if j == ly else b.hi)
        for i in range(lx):
            a.handle("hwall", ci(i), yl(j), given.hwalls[yl(j)][ci(i)], (xs[i] + t, ys[j], 0.0), (xs[i + 1], ys[j] + t, h))
    for j in range(ly):
        for i in range(lx + 1):
            h = b.h if i in (0, lx) else b.hi
            a.handle("vwall", xl(i), ri(j), given.vwalls[ri(j)][xl(i)], (xs[i], ys[j + 1] + t, 0.0), (xs[i] + t, ys[j], h))
        for i in range(lx):
            a.handle("floor", ci(i), ri(j), b.floors[j][i], (xs[i] + t, ys[j + 1] + t, -t), (xs[i + 1], ys[j], 0.0))
    # Liner pieces, as written in the layout (on the line next to the outer one).
    zs = getattr(b, "zero_sizes", {"x": (0, 0), "y": (0, 0)})
    for side, on in (("back", zs["y"][0]), ("front", zs["y"][1])):
        if not on:
            continue
        line = yl(0) + 1 if side == "back" else yl(ly) - 1
        y0 = ys[0] - t if side == "back" else 0.0
        for i in range(lx):
            a.handle("hwall", ci(i), line, given.hwalls[line][ci(i)], (xs[i] + t, y0, 0.0), (xs[i + 1], y0 + t, b.hi))
    for side, on in (("left", zs["x"][0]), ("right", zs["x"][1])):
        if not on:
            continue
        line = xl(0) + 1 if side == "left" else xl(lx) - 1
        x0 = 0.0 if side == "left" else xs[lx] - t
        for j in range(ly):
            a.handle("vwall", line, ri(j), given.vwalls[ri(j)][line], (x0, ys[j + 1] + t, 0.0), (x0 + t, ys[j], b.hi))


def _tray_ramp_cells(b, xs: list[float], ys: list[float]) -> list[tuple]:
    """Ramp cells (see _card_ramps) of a TrayLayout grid: compartments with a floor and a wall on
    the ramp side; neighbours along that wall with no wall between them share one ramp."""
    r = getattr(b, "_web_ramp", None)
    if not r:
        return []
    t = b.thickness
    lx, ly = len(b.x), len(b.y)
    hi = b.hi or b.h
    sliding = getattr(getattr(b, "lidSettings", None), "style", None) == "sliding"
    liner = getattr(b, "liner", {})

    def has(side: str, k: int) -> bool:
        return bool(liner.get(side) and liner[side][k])

    def cell(i: int, j: int) -> tuple[float, float, float, float]:
        """Free floor of compartment (i, j): without the liners standing in it."""
        return (xs[i] + t + (t if i == 0 and has("left", j) else 0.0),
                xs[i + 1] - (t if i == lx - 1 and has("right", j) else 0.0),
                ys[j + 1] + t + (t if j == ly - 1 and has("front", i) else 0.0),
                ys[j] - (t if j == 0 and has("back", i) else 0.0))

    def run(first, last) -> tuple[float, float, float, float]:
        a, b_ = cell(*first), cell(*last)
        if r["side"] in ("front", "back"):  # along x: shared y range
            return a[0], b_[1], max(a[2], b_[2]), min(a[3], b_[3])
        return max(a[0], b_[0]), min(a[1], b_[1]), b_[2], a[3]

    cells = []
    if r["side"] in ("front", "back"):
        line = (lambda j: j + 1) if r["side"] == "front" else (lambda j: j)
        for j in range(ly):
            ok = [b.floors[j][i] and b.hwalls[line(j)][i] for i in range(lx)]
            outer = line(j) in (0, ly)

            def wall_hole(i: int) -> tuple[float, float]:
                if outer and not has(r["side"], i):
                    # The sliding lid raises the back wall and lowers the front wall by t.
                    wall = b.h + (0.0 if not sliding else t if line(j) == 0 else -t)
                    notch = min(wall, hi)
                    notched = b.hasFingerHoles(line(j))
                else:
                    # An inner wall, or a liner on the outer wall: as high as the inner walls,
                    # and a liner is notched like them (see TrayLayout.liners).
                    wall = notch = hi
                    notched = b.hasFingerHoles(line(j)) if not outer else b.fingerholes != "none"
                return wall, (_notch_depth(b, notch) if notched else 0.0)

            i = 0
            while i < lx:
                if not ok[i]:
                    i += 1
                    continue
                e = i + 1
                while e < lx and ok[e] and not b.vwalls[j][e] and cell(e, j)[2:] == cell(i, j)[2:]:
                    e += 1
                cells.append((*run((i, j), (e - 1, j)), *wall_hole(i)))
                i = e
    else:
        line = (lambda i: i) if r["side"] == "left" else (lambda i: i + 1)
        for i in range(lx):
            ok = [b.floors[j][i] and b.vwalls[j][line(i)] for j in range(ly)]
            outer = line(i) in (0, lx)
            # Walls and liners along y have no finger holes.
            j = 0
            while j < ly:
                if not ok[j]:
                    j += 1
                    continue
                e = j + 1
                while e < ly and ok[e] and not b.hwalls[e][i] and cell(i, e)[:2] == cell(i, j)[:2]:
                    e += 1
                wall = b.h if outer and not has(r["side"], j) else hi
                cells.append((*run((i, j), (i, e - 1)), wall, 0.0))
                j = e
    return cells


def _inner_height(f, xs: list[float], ys: list[float], hi: float) -> None:
    """Dimension "hi" of the inner walls (0 = as high as the outer walls): at the front end of
    the first inner wall along y (material from xs[k]), else at the right end of the first one
    along x (from ys[k]). Without inner walls there is nothing to show."""
    t = f.asm.t
    if xs:
        f.height("hi", xs[0] + t / 2, -t, hi, neg(Y), fallback="h")
    elif ys:
        f.height("hi", f.x + t, ys[0] + t / 2, hi, X, fallback="h")


def _runs(flags) -> list[tuple[int, int]]:
    """(start, end) of each run of True values."""
    out, start = [], None
    for k, on in enumerate(list(flags) + [False]):
        if on and start is None:
            start = k
        elif not on and start is not None:
            out.append((start, k))
            start = None
    return out


# --- Racks, crates, bins --------------------------------------------------------------

def _corner_triangles(a: Assembly, f: BoxFrame, z: float, tr: float) -> None:
    """Flat rectangularTriangle parts in the four inner corners at height z (material above),
    right angle (local (tr, 0)) in the corner, legs along the walls."""
    corners = [((0, 0), X, Y), ((f.x, 0), Y, neg(X)), ((f.x, f.y), neg(X), neg(Y)),
               ((0, f.y), neg(Y), X)]
    for tri, ((cx, cy), u, v) in zip(_helper(a.parts, "rectangularTriangle"), corners):
        a.place(tri, f.at(cx + u[0] * tr, cy + u[1] * tr, z), neg(u), v, Z, name="corner triangle")


def _rack_box(a: Assembly, front, back, sides, bottom, lid, dims: dict) -> None:
    """RackBox/Rack19Box: walls on a bottom plate, the flanged front first; the lid lies
    between the walls' top edges on corner triangles fingered into the walls."""
    b = a.box
    t = a.t
    f = a.frame(b.x, b.y, b.h)
    f.sub(0, 0, 0, b.x, b.y, b.h - 2 * t).dims(**dims)  # h: below the triangles
    f.front(front)
    f.back(back)
    f.right(sides[0] if sides else None)
    f.left(sides[1] if len(sides) > 1 else None)
    f.bottom(bottom, rot=180)  # its f edge meets the front's F
    f.plate(lid, b.h - t)
    _corner_triangles(a, f, b.h - 2 * t, b.triangle)


@placement("RackBox")
def rack_box(a: Assembly) -> None:
    rw = _helper(a.parts, "rectangularWall")
    if len(rw) < 5:
        return
    _rack_box(a, _helper(a.parts, "flangedWall").first(), rw[0], [rw[1], rw[2]], rw[3], rw[4],
              {"x": "x", "y": "y", "h": "h"})


@placement("Rack19Box", "Rack10Box")
def rack19_box(a: Assembly) -> None:
    p = a.parts
    _rack_box(a, p.label("front"), p.label("back"), [p.label("right"), p.label("left")],
              p.label("bottom"), p.label("lid"), {"y": "depth"})


@placement("Rack19HalfWidth")
def rack19_half_width(a: Assembly) -> None:
    """Flanged front plate, trapezoid top and bottom (deep side left), two side walls."""
    b = a.box
    p = a.parts
    f = a.frame(b.x, b.deepz, b.y)
    f.front(_helper(p, "flangedWall").first())
    tops = _helper(p, "trapezoidWall")
    a.place(tops.first(), f.at(0, 0, 0), X, Y, neg(Z), name="bottom")
    a.place(tops.first(), f.at(0, 0, b.y), X, Y, Z, name="top")
    sides = _helper(p, "rectangularWall")
    f.left(sides.first())
    a.place(sides.first(), f.at(b.x, b.z, 0), neg(Y), Z, X, name="right")


_FACES = {  # inner corner, along the wall, inwards
    "front": (lambda f: (0, 0), X, Y), "right": (lambda f: (f.x, 0), Y, neg(X)),
    "back": (lambda f: (f.x, f.y), neg(X), neg(Y)), "left": (lambda f: (0, f.y), neg(Y), X),
}


def _stabilizers(a: Assembly, f: BoxFrame, walls: list[tuple]) -> None:
    """Strips drawn by stackable (s) bottom edges, or the lips of finger hole (h) bottom edges
    (FingerJointSettings bottom_lip), glued to the inside of the wall below the bottom plate,
    centred. walls: (wall part, face); each wall's strip is drawn right after it."""
    strips = sorted([*a.parts.drawn_by("StackableBaseEdge.__call__"),
                     *a.parts.drawn_by("FingerHoleEdge.__call__")], key=lambda s: s.index)
    t = a.t
    for wall, face in walls:
        if wall is None:
            continue
        strip = next((s for s in strips if s.index > wall.index), None)
        if strip is None:
            continue
        strips.remove(strip)
        corner, u, inward = _FACES[face]
        cx, cy = corner(f)
        length = f.x if u[0] else f.y
        o = add(add((cx, cy, -t - strip.y), u, (length - strip.x) / 2), inward, t)
        a.place(strip, f.at(*o), u, Z, neg(inward), name="stabilizer")


@placement("Crate")
def crate(a: Assembly) -> None:
    b = a.box
    p = a.parts
    f = a.frame(b.x, b.y, b.h)
    f.dims(x="x", y="y", h="h")
    walls = [(p.label("front"), "front"), (p.label("side1"), "right"),
             (p.label("back"), "back"), (p.label("side2"), "left")]
    for wall, face in walls:
        getattr(f, face)(wall)
    f.bottom(p.label("Bottom"), rot=90)
    _stabilizers(a, f, walls)


def _retainer(a: Assembly, part, x0: float, z0: float, name: str = "retainer") -> None:
    """Front plate leaning out at 45 deg from its bottom edge at (x0, 0, z0)."""
    s = 0.5 ** 0.5
    a.place(part, (x0, 0.0, z0), X, (0.0, -s, s), (0.0, -s, -s), name=name)


@placement("StackableBin")
def stackable_bin(a: Assembly) -> None:
    """Open at the front: a 45 deg retainer at the bottom front, the sides' front profile
    rising from it. Front at y = 0."""
    b = a.box
    t = a.t
    p = a.parts
    x = sum(b.sx) + t * (len(b.sx) - 1)
    f = a.frame(x, b.d, b.h)
    f.dims(x="sx", y="d", h="h")
    f.bottom(p.label("bottom"))
    back, left, right = p.label("back"), p.label("left"), p.label("right")
    a.place(back, f.at(0, b.d, 0), X, Z, Y)  # divider holes counted from the left
    f.left(left, flip=True)
    f.right(right, flip=True)
    for x0, wall in zip(positions(b.sx, t), p.labelled("divider")):
        f.inner_y(wall, x0)
    _retainer(a, p.label("retainer"), 0.0, 0.0)
    # The optional label strip: glued flat on the retainer's outside along its bottom edge, a
    # ledge for a label card.
    s = 0.5 ** 0.5
    a.place(p.label("for label (optional)"), (0.0, -s * t, -s * t), X, (0.0, -s, s), (0.0, -s, -s),
            name="label ledge")
    _stabilizers(a, f, [(back, "back"), (left, "left"), (right, "right")])


@placement("BinTray")
def bin_tray(a: Assembly) -> None:
    """Hangs on a wall: the "back" plate against it, rows sh[0] (top) .. sh[-1] (bottom)
    on shelves, a 45 deg retainer at the front of each row. Front at y = 0."""
    b = a.box
    t = a.t
    p = a.parts
    x = sum(b.sx) + t * (len(b.sx) - 1)
    h = sum(b.sh) + t * (len(b.sh) - 1)
    y = b.y
    f = a.frame(x, y, h)
    f.dims(x="sx", y="y")
    a.place(p.label("back"), f.at(0, y, h), X, neg(Z), Y)
    f.bottom(p.label("bottom"))
    a.place(p.label("top"), f.at(0, y, h), X, neg(Y), Z)
    a.place(p.label("left"), f.at(0, y, 0), Z, neg(Y), neg(X))
    a.place(p.label("right"), f.at(x, y, 0), Z, neg(Y), X)
    for k, x0 in enumerate(positions(b.sx, t)):
        a.place(p.label(f"inner vertical {k + 1}"), f.at(x0, y, 0), Z, neg(Y), X)
    z = h
    for k, sh in enumerate(b.sh):
        z -= sh  # bottom of row k
        if k < len(b.sh) - 1:
            a.place(p.label(f"inner horizontal {k + 1}"), f.at(0, y, z), X, neg(Y), neg(Z),
                    name="shelf")
        _retainer(a, p.label(f"retainer {k + 1}"), 0.0, z)
        z -= t


@placement("EuroRackSkiff")
def euro_rack_skiff(a: Assembly) -> None:
    """Open box; two rails fingered into the side walls just below their top hold the modules."""
    b = a.box
    t = a.t
    x, y, h = 128.5, b.hp * 5.08, b.h
    f = a.frame(x, y, h)
    f.dims(h="h")
    rw = _helper(a.parts, "rectangularWall")
    if len(rw) < 7:
        return
    rails, (front, right, left, back, bottom) = rw[:2], rw[2:7]
    _outer_walls_parts(f, {"front": front, "right": right, "left": left, "back": back,
                           "bottom": bottom})
    a.place(rails[0], f.at(x, 0, h - 2 * t), Y, neg(X), Z, name="rail")
    a.place(rails[1], f.at(0, y, h - 2 * t), neg(Y), X, Z, name="rail")


def _outer_walls_parts(f: BoxFrame, faces: dict) -> None:
    for face, part in faces.items():
        getattr(f, face)(part)


@placement("Keypad")
def keypad(a: Assembly) -> None:
    """Upside down as drawn: the key plates sit in the walls' deep finger joints on top, the
    screwed-on base rests on corner triangles at the bottom (walls outset below it)."""
    b = a.box
    t = a.t
    x, y = b._get_x_y()
    h = b.h
    f = a.frame(x, y, h)
    f.dims(h="h")
    rw = _helper(a.parts, "rectangularWall")
    walls = rw.where(lambda p: p.chars == "GFEF" or p.chars == "GfEf")
    for face in ("front", "right", "left", "back"):
        getattr(f, face)(walls.first(), rot=180)
    # Plates from the inside out: hotplug layer (if any), support, key plate.
    plates = list(rw.edges("ffff"))
    layers = [(plates[0], t), (plates[1], b.top1_thickness)] if len(plates) > 1 else []
    if b.top2_enable and len(plates) > 2:
        layers.insert(0, (plates[2], b.top2_thickness))
    z = h
    for part, th in layers:
        a.place(part, f.at(0, 0, z), X, Y, Z, name="plate", thickness=th)
        z += th
    f.plate(rw.edges("eeee").first(), 0.0)
    _corner_triangles(a, f, t, b.triangle)


@placement("BrickSorter")
def brick_sorter(a: Assembly) -> None:
    b = a.box
    f = a.frame(b.x, b.y, b.h)
    rw = _helper(a.parts, "rectangularWall")
    if len(rw) < 5:
        return
    front, back, bottom, left, right = rw[:5]
    _outer_walls_parts(f, {"front": front, "back": back, "left": left, "right": right,
                           "bottom": bottom})


@placement("NotesHolder")
def notes_holder(a: Assembly) -> None:
    """Sides, front and back (in pieces around the openings), inner walls, bottom."""
    b = a.box
    t = a.t
    sx = list(b.sx)
    x = sum(sx) + t * (len(sx) - 1)
    f = a.frame(x, b.y, b.h)
    f.dims(x="sx", y="y", h="h")
    rw = iter(list(_helper(a.parts, "rectangularWall")))
    o = max(0.0, min(b.opening, 100.0))
    for side, face, sizes in ((0, "front", sx), (1, "back", sx[::-1])):
        getattr(f, "left" if side == 0 else "right")(next(rw, None))
        place = getattr(f, face)
        if b.opening == 0.0 or (side and not b.back_openings):
            place(next(rw, None))
            continue
        # Pieces between the openings: one at each end, one around each inner wall.
        ws = [s * (1 - o / 100) / 2 for s in sizes]
        place(next(rw, None))
        for start, left in zip(positions(sizes, t), ws[:-1]):
            place(next(rw, None), du=start - left)
        place(next(rw, None), du=x - ws[-1])
    if b.bottom_edge != "e":
        # Seen from inside: the front (U-slotted) edge first, inner wall holes from the left.
        a.place(next(rw, None), f.at(0, 0, 0), X, Y, neg(Z), name="bottom")
    for x0 in positions(sx, t):
        f.inner_y(next(rw, None), x0)


def _box_walls(a: Assembly, f: BoxFrame, rw, faces: list[str]) -> None:
    """Places the next len(faces) parts of iterator rw on the frame faces (None: skip one)."""
    for face in faces:
        part = next(rw, None)
        if face:
            getattr(f, face)(part)


@placement("HingeBox")
def hinge_box(a: Assembly) -> None:
    """Box and lid of height lidheight on top, hinged at the back (or split: two lids hinged
    front and back, meeting at splitlid from the front). Hinge parts stay 2D."""
    b = a.box
    x, y, h, hl = b.x, b.y, b.h, b.lidheight
    s = b.splitlid
    if b.outside:
        x, y, h = b.adjustSize(x), b.adjustSize(y), b.adjustSize(h)
        s = b.adjustSize(s, None)
    if s > x or s < 0.0:
        s = 0.0
    f = a.frame(x, y, h)
    f.dims(x="x", y="y", h="h")
    lid = f.sub(0, 0, h, x, y, hl, name="lid")
    rw = iter(list(_helper(a.parts, "rectangularWall")))
    _box_walls(a, f, rw, ["front", "right", "left", "back"])
    if s:
        lid.front(next(rw, None))
        lid.right(next(rw, None))                   # s, hinged end at the front
        lid.right(next(rw, None), du=s)             # y - s
        lid.left(next(rw, None))                    # y - s, from the back
        lid.left(next(rw, None), du=y - s)          # s
        lid.back(next(rw, None))
        f.bottom(next(rw, None))
        lid.top(next(rw, None))                     # front lid, s deep
        lid.top(next(rw, None), dv=s)
    else:
        _box_walls(a, lid, rw, ["back", "right", "left", "front"])
        f.bottom(next(rw, None))
        lid.top(next(rw, None))


@placement("IntegratedHingeBox")
def integrated_hinge_box(a: Assembly) -> None:
    """Box and lid (lidheight) meeting at h; the side walls of both end in the chest hinge
    at the back (the box sides hy below h, the lid sides hy2 above it)."""
    b = a.box
    x, y, h, hl = b.x, b.y, b.h, b.lidheight
    if b.outside:
        x, y, h = b.adjustSize(x), b.adjustSize(y), b.adjustSize(h)
    hy2 = b.edges["P"].startWidth()
    f = a.frame(x, y, h)
    f.dims(x="x", y="y", h="h")
    lid = f.sub(0, 0, h, x, y, hl, name="lid")
    rw = iter(list(_helper(a.parts, "rectangularWall")))
    # Hinge edges: o at the start of an edge, O at its end; both at the back.
    f.left(next(rw, None))                  # FfOf
    lid.left(next(rw, None), dv=hy2)        # pfFf
    f.right(next(rw, None))                 # Ffof
    lid.right(next(rw, None), dv=hy2)       # PfFf
    f.front(next(rw, None))
    f.back(next(rw, None))
    lid.front(next(rw, None), rot=180)      # its top plate's edge drawn first
    lid.back(next(rw, None), rot=180, dv=hy2)
    f.bottom(next(rw, None), rot=90)
    lid.top(next(rw, None), rot=90)


# --- Shelves --------------------------------------------------------------------------

@placement("DisplayShelf")
def display_shelf(a: Assembly) -> None:
    """Two sides; slanted shelves (low end at the front) in their finger hole lines, a front
    lip on each and dividers standing on them. Front at y = 0."""
    b = a.box
    t = a.t
    p = a.parts
    x, y, h = b.x, b.y, b.h
    ang = b.radians
    c, s = math.cos(ang), math.sin(ang)
    f = a.frame(x, y, h)
    f.dims(x="sx", y="y", h="h")
    # Side coordinates (u back to front, v up) -> 3D.
    def pt(u: float, v: float, x0: float = 0.0):
        return (x0, y - u, v)
    sides = p.where(lambda q: q.label in ("left side", "right side"))
    a.place(sides.first(), pt(0, 0), neg(Y), Z, neg(X), name="left side")
    a.place(sides.first(), pt(0, 0, x), neg(Y), Z, X, name="right side")
    # As DisplayShelf.generate_finger_holes: start of each shelf's centre line.
    hs = (b.sl + t) * s + c * t
    hh = h - b.bottom_distance - b.top_distance
    v0 = b.edges["h"].startWidth() if b.slope_top and b.include_bottom else 0.0
    up = (0.0, -s, c)          # shelf normal (3D)
    back_up = (0.0, c, s)      # along a shelf, front to back
    front = (0.0, -c, -s)      # along a shelf, back to front
    xs = positions(b.sx, t)
    for i in range(b.num):
        pu = abs(0.5 * t * s)
        pv = hs - c * 0.5 * t + i * (hh - abs(hs)) / (b.num - 0.5) + b.bottom_distance + v0
        if ang < 0:
            pv += -s * b.sl
        u1, v1 = pu + b.sl * c, pv - b.sl * s   # front end of the centre line
        a.place(p.label(f"shelf {i + 1}"), pt(u1 - 0.5 * t * s, v1 - 0.5 * t * c), X, back_up,
                up, name="shelf")
        a.place(p.label(f"front lip {i + 1}"), pt(u1 + 0.5 * t * s, v1 + 0.5 * t * c), X, up,
                front, name="front lip")
        for k, x0 in enumerate(xs):
            a.place(p.label(f"divider {k + 1} for shelf {i + 1}"),
                    pt(pu + 0.5 * t * s, pv + 0.5 * t * c, x0 + t), front, up, neg(X),
                    name="divider")
    f.back(p.label("back wall"))
    f.front(p.label("front wall"))
    f.bottom(p.label("bottom wall"))


@placement("PaintStorage")
def paint_storage(a: Assembly) -> None:
    """Long stackable tray: end walls (drawn top down, feet at the bottom), a bottom in their
    stackable joint, plates with can holes in finger hole lines (drawer: front and back)."""
    b = a.box
    t = a.t
    st = b.edges["s"].settings
    h = b.canheight - st.height - st.holedistance + t
    y, d = b.y, b.x - 2 * t
    f = a.frame(y, d, h)
    rw = iter(list(_helper(a.parts, "rectangularWall")))
    a.place(next(rw, None), f.at(0, 0, h), neg(Z), Y, neg(X), name="end")
    a.place(next(rw, None), f.at(y, 0, h), neg(Z), Y, X, name="end")
    next(rw, None), next(rw, None)  # strips, 2D
    a.place(next(rw, None), f.at(0, 0, 0), X, Y, neg(Z), name="bottom")
    if b.drawer:
        f.front(next(rw, None), rot=180)
        f.back(next(rw, None), rot=180)
        return
    # Hole lines measured from the top of the end walls (sidesCb), plates t past the walls.
    levels = [2 * b.canheight / 3 - 2 * t]
    if b.additional_bottom:
        levels.append(b.canheight / 6 - t / 2)
    if b.additional_top:
        levels.append(b.canheight - (b.canheight / 6 + t))
    for lv in levels:
        a.place(next(rw, None), f.at(0, -t, h - lv - t / 2), X, Y, Z, name="plate")


@placement("SBCMicroRack")
def sbc_micro_rack(a: Assembly) -> None:
    """Two stackable sides (drawn top down), a bottom and one plate per board. With switch, a
    third side stands outside the second one, held by the dowel through their stable holes;
    the switch's width is not a parameter, so it gets a board's clearance (clearance_z)."""
    b = a.box
    t = a.t
    hd = b.hole_dist_edge
    hp = b.clearance_z + t
    H = b.sbcs * hp + hp / 2
    w, d = b.y + 2 * hd, b.x + 2 * hd
    f = a.frame(w, d, H)
    rw = list(_helper(a.parts, "rectangularWall"))
    sides = rw[:3 if b.switch else 2]
    plates = rw[len(sides):]
    if len(sides) < 2 or not plates:
        return
    a.place(sides[0], f.at(0, 0, H), neg(Z), Y, neg(X), name="side")
    a.place(sides[1], f.at(w, 0, H), neg(Z), Y, X, name="side")
    if b.switch:
        a.place(sides[2], f.at(w + t + b.clearance_z, 0, H), neg(Z), Y, X, name="switch holder")
    a.place(plates[0], f.at(0, 0, 0), X, Y, neg(Z), name="bottom")
    for i, plate in enumerate(plates[1:]):
        z = H - (hp * i + hp / 2 + 1.5)
        a.place(plate, f.at(0, 0, z - t / 2), X, Y, Z, name="board plate")


@placement("CardHolder")
def card_holder(a: Assembly) -> None:
    """Floor slanting down to the back between two sides, back wall, dividers on the floor.
    Front at y = 0."""
    b = a.box
    t = a.t
    p = a.parts
    y, h = b.y, b.h
    x = b.x
    ang = math.radians(b.angle)
    c, s = math.cos(ang), math.sin(ang)
    f = a.frame(x, y, h)
    f.dims(x="sx", y="y")
    rw = list(_helper(p, "rectangularWall"))
    if len(rw) < 4:
        return
    f.right(rw[0])
    f.left(rw[1])  # drawn mirrored
    # Floor centre line from the back (CardHolder.side), towards the front and up.
    u0, v0 = y - abs(0.5 * t * s), t - c * 0.5 * t
    u1, v1 = u0 - y * c, v0 + y * s
    a.place(rw[2], (0.0, u1 - 0.5 * t * s, v1 - 0.5 * t * c), X, (0.0, c, -s), (0.0, s, c),
            name="floor")
    a.place(rw[3], f.at(0, y, 0), X, Z, Y, name="back")  # divider holes from the left
    for x0, wall in zip(positions(b.sx, t), _helper(p, "free").drawn_by("CardHolder.middleWall")):
        a.place(wall, f.at(x0, y + t, 0), neg(Y), Z, X, name="divider")


@placement("DiscRack")
def disc_rack(a: Assembly) -> None:
    """Square sides; the lower and rear grids at right angles, turned back by angle."""
    b = a.box
    t = a.t
    rw = list(_helper(a.parts, "rectangularWall"))
    if len(rw) < 4:
        return
    o, r = b.outer, b.disc_diameter / 2
    w = sum(b.sx)
    ang = math.radians(b.angle)
    c, s = math.cos(ang), math.sin(ang)
    xr, yr = (0.0, c, -s), (0.0, s, c)   # rotated frame around the disc centre (3D)
    def pt(px: float, py: float):
        return (0.0, o / 2 + px * c + py * s, o / 2 - px * s + py * c)
    a.place(rw[0], (0.0, 0.0, 0.0), Y, Z, neg(X), name="side")
    a.place(rw[1], (w, 0.0, 0.0), Y, Z, X, flip=True, name="side")
    lf, rf = b.lower_factor, b.rear_factor
    a.place(rw[2], pt(-(b.lower_outset + b.lower_halfslit), -r * lf - t), xr, X, yr,
            name="lower grid")
    a.place(rw[3], pt(r * rf, -r * lf), yr, X, xr, name="rear grid")


# --- Trays -------------------------------------------------------------------------------------


@placement("TrayInsert")
def tray_insert(a: Assembly) -> None:
    """Only the inner walls, slotted into each other (sx walls slotted from below)."""
    b = a.box
    t = a.t
    sx, sy = list(b.sx), list(b.sy)
    x = sum(sx) + t * (len(sx) - 1)
    y = sum(sy) + t * (len(sy) - 1)
    f = a.frame(x, y, b.h)
    f.dims(h="h")
    rw = _helper(a.parts, "rectangularWall")
    for x0 in positions(sx, t):
        f.inner_y(rw.first(), x0)
    for y0 in positions(sy, t):
        f.inner_x(rw.first(), y0)


@placement("GridfinityBase")
def gridfinity_base(a: Assembly) -> None:
    """Grid plate on the floor of a tray margin m larger, optional lid."""
    b = a.box
    if b.panel_x and b.panel_y:
        return  # split into panels: flat view
    p = a.parts.not_drawn_by("Lid.__call__")
    m = b.m
    x, y = b.size_x, b.size_y
    rw = list(_helper(p, "rectangularWall"))
    if not rw:
        return
    grid, rw = rw[0], iter(rw[1:])
    if b.h <= 0:
        a.place(grid, (0.0, 0.0, 0.0), X, Y, Z, name="base")
        return
    f = a.frame(x + 2 * m, y + 2 * m, b.h)
    f.dims(h="h")
    _box_walls(a, f, rw, ["front", "right", "left", "back"])
    if b.bottom_edge != "e":
        f.bottom(next(rw, None))
        f.plate(grid, 0.0, x0=m, y0=m)
    else:
        f.plate(grid, -a.t, x0=m, y0=m)
    place_lids(a, f, None)


@placement("SmallPartsTray2")
def small_parts_tray2(a: Assembly) -> None:
    """Compartments sy[0] (back) .. sy[-1] (front), each with a 45 deg slope up to its front
    edge. Mounted inside out (as the description says), so sx[0] is on the left."""
    b = a.box
    p = a.parts
    t = a.t
    s = 0.5 ** 0.5
    sx, sy = list(b.sx), list(b.sy)
    x = sum(sx) + t * (len(sx) - 1)
    y = sum(sy) + t * (len(sy) - 1)
    hi = b.hi
    t2 = t * 2 ** 0.5
    slot = t + t2 / 2
    f = a.frame(x, y, b.h)
    f.dims(x="sx", y="-sy", h="h")
    a.place(p.label("front"), f.at(x, 0, 0), neg(X), Z, neg(Y), name="front")
    a.place(p.label("back"), f.at(0, y, 0), X, Z, Y, name="back")
    f.left(p.label("side"))
    f.right(p.label("side"))
    # Floor boards from the back, with a slot for each slope's foot in between.
    floors = [sy[0] - hi - slot + t2] + [s_ - slot + t for s_ in sy[1:]] + [hi - t2]
    u = 0.0
    for k, length in enumerate(floors):
        label = "floor back side" if k == 0 else "floor front side" if k == len(floors) - 1 else "floor"
        f.bottom(p.label(label), dv=u)
        u += length + slot
    L = hi * 2 ** 0.5 + t / 2
    for k in range(len(sy)):
        uk = sum(sy[:k + 1]) + k * t  # front edge of compartment k, from the back
        a.place(p.label("slope"), f.at(0, y - uk + s * L, hi - s * L), X, (0.0, -s, s),
                (0.0, -s, -s), name="slope")
        if k < len(sy) - 1:
            a.place(p.label(f"inner x {k + 1}"), f.at(0, y - uk - t, 0), X, Z, Y, name="divider")
    for i, x0 in enumerate(positions(sx, t)):
        a.place(p.label(f"inner y {i + 1}"), f.at(x0, y, 0), neg(Y), Z, X, name="divider")


def _divider_tray_slots(b, t: float) -> list[float]:
    """DividerTray: where each slot enters the side walls' top edge (start, along the edge,
    which runs back to front), recomputed like render() does."""
    from boxes.generators.dividertray import SlotDescription, SlotDescriptionsGenerator
    d = SlotDescriptionsGenerator().generate_all_same_angles(
        b.sy, t, b.Slot_extra_slack, b.Slot_depth, b.h, b.Slot_angle, b.Slot_radius)
    if b.outside:
        d.adjust_to_target_length(sum(b.sy) - 2 * t)
    out, pos = [], 0.0
    for desc in d.descriptions:
        if isinstance(desc, SlotDescription):
            out.append(pos + desc.round_edge_start_correction())
        pos += desc.tracing_length()
    return out


@placement("DividerTray")
def divider_tray(a: Assembly) -> None:
    """Front/back walls, side walls with slots leaning back by Slot_angle; the full width
    divider sits in the first slot (the single ones are alternatives and stay 2D)."""
    b = a.box
    p = a.parts.not_drawn_by("Lid.__call__")
    t = a.t
    sx = list(b.sx)
    x = sum(sx) + t * (len(sx) - 1)
    back, front = p.label("Back"), p.label("Front")
    sides = list(p.labelled("Sidepiece"))
    if back is None or front is None or not sides:
        return
    y = sides[0].x
    f = a.frame(x, y, b.h)
    f.dims(x="sx")
    f.front(front)
    a.place(back, f.at(0, y, 0), X, Z, Y, name="back")  # seen from inside, like the front
    outer = sides[:int(b.left_wall) + int(b.right_wall)]
    if b.left_wall:
        a.place(outer.pop(0), f.at(0, 0, 0), Y, Z, neg(X), name="left")
    if b.right_wall:
        f.right(outer.pop(0))
    for part, x0 in zip(sides[int(b.left_wall) + int(b.right_wall):], positions(sx, t)):
        f.inner_y(part, x0)
    if b.bottom:
        f.bottom(p.label("Bottom"))
    # Divider: drawn top down; lowest corner Divider_bottom_margin above the floor.
    slots = _divider_tray_slots(b, t)
    div = a.parts.drawn_by("DividerTray.generate_divider").first()
    if slots and div is not None:
        ang = math.radians(b.Slot_angle)
        s, c = math.sin(ang), math.cos(ang)
        w = (t + b.Slot_extra_slack) / c
        yc = y - slots[0] - w / 2  # slot centre line at the top, Y from the front
        m = b.Divider_bottom_margin
        zt = b.h - t / 2 * s + m * (1 - c)
        yt = yc - (b.h - zt) * s / c
        x0 = -t if b.left_wall else 0.0
        a.place(div, f.at(x0, yt - t / 2 * c, zt + t / 2 * s), X, (0.0, -s, -c), (0.0, c, -s),
                name="divider")
    place_lids(a, f, None)


def _divider_foot(a: Assembly, foot, o: Vec) -> None:
    """A SmallPartsTray divider foot standing in the y-z plane, material in [o.x, o.x + t],
    its long side from o along y. Drawn as a right triangle with that side on the diagonal
    x = y: the apex on one side of it or the other (the two feet of a pair are mirrored)."""
    if foot is None:
        return
    s = 0.5 ** 0.5
    if sum(q[0] - q[1] for q in foot.rec["outline"]["outer"]) > 0:  # apex at x > y
        a.place(foot, add(o, X, a.t), (0.0, s, s), (0.0, s, -s), neg(X), name="divider foot")
    else:
        a.place(foot, o, (0.0, s, -s), (0.0, s, s), X, name="divider foot")


@placement("SmallPartsTray")
def small_parts_tray(a: Assembly) -> None:
    """Ramps up to the side walls' ends (both ends if two_sided, else the front), a floor in
    between, vertical panels above the ramps (front_panel). The sides run along y; sx[0] is
    on the left. Two-sided: one movable divider per compartment in the middle."""
    b = a.box
    t = a.t
    sx, y, h = list(b.sx), b.y, b.h
    x = sum(sx) + (len(sx) - 1) * t
    ramp_h = h * b.rampheight
    ramp_y = ramp_h / math.tan(math.radians(b.angle))
    if b.two_sided and 2 * ramp_y + 3 * t > y:
        ramp_y = (y - 3 * t) / 2
        ramp_h = ramp_y * math.tan(math.radians(b.angle))
    elif ramp_y > y - t:
        ramp_y = y - t
        ramp_h = ramp_y * math.tan(math.radians(b.angle))
    ramp_l = (ramp_h ** 2 + ramp_y ** 2) ** 0.5
    c, s = ramp_y / ramp_l, ramp_h / ramp_l
    f = a.frame(x, y, h)
    f.dims(x="sx", y="y" if b.front_panel else None, h="h")
    p = a.parts.not_drawn_by("Lid.__call__")
    rw = iter(list(_helper(p, "rectangularWall")))
    # Sides run from the front (u = 0) to the back.
    f.right(next(rw, None))
    f.left(next(rw, None))
    for x0, wall in zip(positions(sx, t), _helper(p, "polygonWall")):
        f.inner_y(wall, x0)
    if b.front_panel:
        f.front(next(rw, None), dv=ramp_h)
    # Ramps: upper face from the floor up to the wall end.
    a.place(next(rw, None), f.at(0, ramp_y, 0), X, (0.0, -c, s), (0.0, -s, -c), name="ramp")
    if b.two_sided:
        f.bottom(next(rw, None), dv=ramp_y)
        a.place(next(rw, None), f.at(0, y - ramp_y, 0), X, (0.0, c, s), (0.0, s, -c), name="ramp")
        if b.front_panel:
            a.place(next(rw, None), f.at(0, y, ramp_h), X, Z, Y, name="back panel")
        feet = iter(list(p.drawn_by("SmallPartsTray.render_simple_tray_divider_feet")))
        for x0, div in zip([0.0] + [q + t for q in positions(sx, t)],
                           list(p.drawn_by("SmallPartsTray.render_simple_tray_divider"))):
            a.place(div, f.at(x0, (y + t) / 2, 0), X, Z, neg(Y), name="divider")
            # Two feet per divider, across it under its raised ends: triangles drawn at 45 deg,
            # their long side (5 t) on the floor, the divider in the t wide slot at the top.
            for x1 in (x0, x0 + div.x - t):
                _divider_foot(a, next(feet, None), f.at(x1, y / 2 - 2.5 * t, 0))
    else:
        a.place(next(rw, None), f.at(0, ramp_y, 0), X, Y, neg(Z), name="bottom")
        a.place(next(rw, None), f.at(0, y, 0), X, Z, Y, name="back")
    place_lids(a, f, None)


@placement("HobbyCase")
def hobby_case(a: Assembly) -> None:
    """Cabinet standing on its bottom, the base plate as back wall. Each column has its own
    pair of side walls; shelves fill the lowest slots of a column, rail sets the rest. The
    cover plate goes in front."""
    b = a.box
    t = a.t
    w = list(b.unit_w)
    W, D, H = b.inside_w, b.outside_depth, b.inside_h
    d = b.inside_depth
    p = a.parts
    rw = _helper(p, "rectangularWall")
    f = a.frame(W, D, H)
    a.place(rw.labelled("base plate").first(), f.at(0, D, 0), X, Z, Y, name="back")
    f.bottom(rw.labelled("bottom").first())
    a.place(rw.labelled("top").first(), f.at(0, D, H), X, neg(Y), Z, name="top")
    a.place(rw.labelled("cover plate").first(), f.at(-t, 0, -t), X, Z, neg(Y), name="cover")
    starts = [sum(w[:c]) + 2 * t * c for c in range(len(w))]  # inner left of each column
    # All side walls are drawn from the back (local x = 0).
    f.left(rw.labelled("left").first())
    a.place(rw.labelled("right").first(), f.at(W, D, 0), neg(Y), Z, X, name="right")
    for c in range(1, len(w)):
        for x0 in (starts[c] - 2 * t, starts[c] - t):
            a.place(rw.labelled("vertical wall").first(), f.at(x0, D, 0), neg(Y), Z, X,
                    name="vertical wall")
    rails = rw.drawn_by("HobbyCase.railSet")
    for c, (x0, wc) in enumerate(zip(starts, w)):
        for r in range(1, b.rows):
            z0 = r * b.unit_h + (r - 1) * t  # slot r from the bottom
            if r <= b.shelves_n[c]:
                a.place(rw.labelled(f"shelf (column {c})").first(), f.at(x0, D - d, z0), X, Y,
                        Z, name="shelf")
            elif b.add_rails:
                a.place(rails.first(), f.at(x0, D, z0), neg(Y), X, Z, name="rail")
                a.place(rails.first(), f.at(x0 + 4 * t, D, z0 + t), X, neg(Y), neg(Z),
                        name="rail")
                a.place(rails.first(), f.at(x0 + wc, D, z0 + t), neg(Y), neg(X), neg(Z),
                        name="rail")


# --- Shelves (2) -------------------------------------------------------------------------------


@placement("SpicesRack")
def spices_rack(a: Assembly) -> None:
    """Back plate on the wall (y = 0 its front face, z up), a shelf every h with a support
    below it between each pair of cans. Feet take the place of the lowest supports."""
    b = a.box
    t = a.t
    h = b.h
    p = a.parts
    rw = _helper(p, "rectangularWall")
    back = rw.edges("eeee").first()
    pitch = b.diameter + b.space
    a.place(back, (0.0, 0.0, 0.0), X, Z, Y, name="back")
    supports = p.drawn_by("SpicesRack.support")
    feet = p.drawn_by("SpicesRack.foot")
    sh = (h - t) / 2  # support height
    for i in range(b.numy):
        z = (i + 0.5) * h  # shelf centre
        a.place(rw.first(), (0.0, 0.0, z - t / 2), X, neg(Y), Z, name="shelf")
        for j in range(1, b.numx):
            x0 = j * pitch - t / 2
            if i == 0 and b.feet:
                # Drawn lying: the finger edge along x at y = t, the ground end at x = sh.
                a.place(feet.first(), (x0, t, sh), neg(Z), neg(Y), X, name="foot")
            else:
                a.place(supports.first(), (x0, 0.0, z - t / 2 - sh), neg(Y), Z, X, name="support")


def _wine_rack_segments(b) -> list[tuple[float, float, float]]:
    """WineRack: (x, y, angle) of every comb wall in the middle plate, in wallCB's order."""
    r, dx, dy, cx, cy = b.r, b.dx, b.dy, b.cx, b.cy
    if cy % 2:
        ty = cy // 2 * (2 * dy + 2 * r) + 2 * dy + r
    else:
        ty = cy // 2 * (2 * dy + 2 * r) + dy
    ox, oy = (b.x - dx * 2 * cx) / 2, (b.y - ty) / 2
    allw, wmin = b.walls == "all", b.walls == "minimal"
    out = []
    for i in range(cy // 2 + cy % 2):
        row = (2 * r + 2 * dy) * i
        if allw:
            out.append((0, row + dy, 90))
        for j in range(cx):
            out += [(j * 2 * dx + dx, row, 150), (j * 2 * dx + dx, row, 30)]
            if allw:
                out.append((j * 2 * dx + 2 * dx, row + dy, 90))
            if wmin and i == cy // 2:
                continue
            if j > 0 or not wmin:
                out.append((j * 2 * dx + dx, row + r + 2 * dy, -150))
            if j < cx - 1 or not wmin:
                out.append((j * 2 * dx + dx, row + r + 2 * dy, -30))
        if i < cy // 2 and allw:
            out += [(j * 2 * dx + dx, row + r + 2 * dy, 90) for j in range(cx)]
    if not cy % 2 and not wmin:
        row = (2 * r + 2 * dy) * (cy // 2)
        for j in range(cx):
            if j > 0:
                out.append((j * 2 * dx + dx, row, 150))
            if j < cx - 1:
                out.append((j * 2 * dx + dx, row, 30))
    return [(ox + px, oy + py, ang) for px, py, ang in out]


@placement("WineRack")
def wine_rack(a: Assembly) -> None:
    """Upright: the middle plate (bottle holes and comb finger holes) in front, the comb walls
    (h deep) between it and the back plate; the front plate covers the middle one."""
    b = a.box
    t = a.t
    h = b.h
    rw = list(_helper(a.parts, "rectangularWall"))
    if len(rw) < 3:
        return
    middle, back, front = rw[:3]
    a.place(middle, (0.0, 0.0, 0.0), X, Z, neg(Y), name="middle")
    a.place(back, (0.0, h, 0.0), X, Z, Y, name="back")
    a.place(front, (0.0, -t, 0.0), X, Z, neg(Y), name="front")
    for strip, (px, py, ang) in zip(rw[3:], _wine_rack_segments(b)):
        c, s = math.cos(math.radians(ang)), math.sin(math.radians(ang))
        px, py = px + b.delta * c, py + b.delta * s  # the holes start delta in
        a.place(strip, (px + t / 2 * s, 0.0, py - t / 2 * c), (c, 0.0, s), Y, (-s, 0.0, c),
                name="comb wall")


# --- Wall mounted (2) --------------------------------------------------------------------------


@placement("KeyHolder")
def key_holder(a: Assembly) -> None:
    """Back plate on the wall (front face at y = 0), hooks fingered into it."""
    b = a.box
    t = a.t
    rw = list(_helper(a.parts, "rectangularWall"))
    if not rw:
        return
    a.place(rw[0], (0.0, 0.0, 0.0), X, Z, Y, name="back")
    x0 = b.padding_left_right
    for hook in rw[1:]:
        a.place(hook, (x0, 0.0, b.padding_bot), neg(Y), Z, X, name="hook")
        x0 += b.hook_distance + t


@placement("DinRailBox")
def din_rail_box(a: Assembly) -> None:
    """Lying on its back (on the rail): back plate below, sides along y, "Bottom"/"Top" walls
    in front/behind, the lid on top with its two snap lips inside the walls, and the rail
    holder under the back. The latch (and the slot for it) stays 2D."""
    b = a.box
    t = a.t
    x, y, h = b.x, b.y, b.h
    p = a.parts
    f = a.frame(x, y, h)
    f.dims(x="x", y="y", h="h")
    f.bottom(p.label("Back"))
    f.left(p.label("Left Side upsidedown"))
    f.right(p.label("Right Side"))
    f.front(p.label("Bottom"))
    f.back(p.label("Top"))
    f.plate(p.label("Lid"), h)
    for lip, x0 in zip(p.drawn_by("DinRailBox.lid_lip"), (0.05 * t, x - 1.05 * t)):
        a.place(lip, f.at(x0, 0.05 * t - 1, h + t), Y, neg(Z), X, name="lid lip")
    yb = (y - b.rail_width) / 2 - 0.5 * t + b.rail_offset - 9  # its hole line in the back
    holder = _helper(p, "rectangularWall").edges("feee").first()
    a.place(holder, f.at(0, y - yb - t / 2, -t), X, neg(Z), Y, name="rail holder")


@placement("RollHolder")
def roll_holder(a: Assembly) -> None:
    """Like WallRollHolder, but the sides have a plain finger edge (at their local y = t) and
    the back is one plate or two mirrored ones (one_piece off). The axle rings stay 2D."""
    b = a.box
    t = a.t
    p = a.parts
    w, h, ax = b.width, b.height, b.axle
    sides = list(_helper(p, "free"))[:2]
    for part, x0 in zip(sides, (h / 4, h / 4 + t + w)):
        a.place(part, (x0, t, 0.0), Z, neg(Y), X, name="side")
    plates = list(_helper(p, "roundedPlate"))
    if plates:
        _wall_back(a, plates[0])
    if len(plates) > 1:
        _wall_back(a, plates[1], x0=w + t)
    zc = h - 3 * t - ax / 2
    tris = list(_helper(p, "rectangularTriangle"))
    if len(tris) == 2:
        a.place(tris[0], (0.0, 0.0, zc - t / 2), X, neg(Y), Z, name="brace")
        a.place(tris[1], (w + h / 2 + 2 * t, 0.0, zc - t / 2), neg(X), neg(Y), Z, name="brace")


@placement("CoinBankSafe")
def coin_bank_safe(a: Assembly) -> None:
    """The door (width y) closes the front, inset by 1.25t and turning on pins at the right
    that sit in the top's and bottom's holes; the locking bar stands behind it on the left
    wall. World: x = the y parameter, y = the x parameter. Dials, pins and handle stay 2D."""
    b = a.box
    t = a.t
    p = a.parts
    x, y, h = b.y, b.x, b.h
    f = a.frame(x, y, h)
    f.dims(x="y", y="x", h="h")
    walls = list(_helper(p, "rectangularWall"))
    if len(walls) < 6:
        return
    f.right(walls[0])  # drawn mirrored: its f edge at the back
    f.back(walls[1])
    f.left(walls[2])
    a.place(walls[3], f.at(0, 2.25 * t, 0), X, Z, Y, name="locking bar")
    f.top(p.label("top"))
    f.bottom(p.label("bottom"), rot=180)
    door = _helper(p, "free").where(lambda q: abs(q.y - (h + 2 * t)) < 1).first()
    if door is not None:
        lw = (door.x - (x - 0.2 * t)) / 2  # the frame is the stroke's bounding box
        a.place(door, f.at(0.1 * t - lw, 1.25 * t, -t - lw), X, Z, Y, name="door")


@placement("HalfBox")
def half_box(a: Assembly) -> None:
    """Bottom (x by the sy sections) and an upright back at its right (x = x), joined by
    triangular supports on the bottom's finger holes. Sturdy adds two outer side triangles
    with finger hole edges; without it, sy has empty outer sections, so supports stand at
    the outer edges. World: bottom z [-t, 0], back x [x, x + t]."""
    b = a.box
    t = a.t
    p = a.parts
    x, h = b.x, b.h
    sy = b.sy  # render pads it with 0s when not Sturdy
    width = sum(sy) + (len(sy) - 1) * t
    a.place(p.label("bottom"), (0.0, 0.0, 0.0), X, Y, neg(Z), name="bottom")
    a.place(p.label("back") or p.label("side"), (x, 0.0, 0.0), Z, Y, X, name="back")
    m = b.edges["f"].margin()
    posy = -0.5 * t
    for i, y in enumerate(sy[:-1]):
        posy += y + t
        a.place(p.label(f"support {i}"), (0.0, posy - t / 2, -m), X, Z, Y)
    if b.Sturdy:
        ew = b.edges["h"].startWidth() - t
        x2 = 2 * t / h * x
        for i, y0 in enumerate((0.0, width + t)):
            a.place(p.label(f"side {i}"), (-x2 - (2 * t - ew - t), y0, -ew - t), X, Z, neg(Y))


@placement("Dispenser")
def dispenser(a: Assembly) -> None:
    """Floor in the walls' finger holes (raised by bottomheight on feet), its finger notch at
    the front; the front panels start above the slot. The lid is a plug inside the walls with
    a plate on top. The walls' labels are as seen from behind."""
    b = a.box
    t = a.t
    p = a.parts
    x, y, h, hs = b.x, b.y, b.h, b.slotheight
    hb = max(0.0, b.bottomheight - b.edges["š"].spacing())
    th = h + (hb + t if hb else 0.0)
    f = a.frame(x, y, th)
    f.dims(x="x", y="y", h="h")
    f.plate(p.label("Floor"), hb if hb else -t)
    f.right(p.label("Left wall"))  # drawn mirrored: its f edge at the back
    f.left(p.label("Right wall"))
    f.back(p.label("Back wall"))
    z0 = (hb + t if hb else 0.0) + hs
    f.front(p.label("front"), dv=z0)
    left = p.label("Left front")
    f.front(left, dv=z0)
    if left is not None:
        f.front(p.label("Right front"), du=x - left.x, dv=z0)
    f.plate(p.label("Lid bottom"), th - t)
    f.plate(p.label("Lid top"), th)


@placement("Matrix")
def matrix(a: Assembly) -> None:
    """LED matrix case: the top is the front frame. Inside, from the top down: plexiglass
    (its own thickness), two LED grids, the PCB (not a part), then the mount frame in the
    walls' finger holes."""
    b = a.box
    t = a.t
    p = a.parts
    off = b.matrix_front_frame_border_offset
    x, y, h = b.physical_led_x + 2 * off, b.physical_led_y + 2 * off, b.h
    f = a.frame(x, y, h)
    f.dims(h="h")
    f.front(p.label("Wall 1"))
    f.back(p.label("Wall 3"))
    f.left(p.label("Wall 2"))
    f.right(p.label("Wall 4"))
    f.bottom(p.label("Bottom"))
    f.top(p.label("Top"))
    f.plate(p.labelled("matrix mount frame").first(),
            h - 2 * t - b.plexiglass_thicknes - b.height_pcb - t)
    pt = b.plexiglass_thicknes
    a.place(p.label("Plexiglass"), f.at(0, 0, h - pt), X, Y, Z, thickness=pt)
    for i, grid in enumerate(list(p.labelled("led_grid"))):
        f.plate(grid, h - pt - (i + 1) * t)


@placement("TrafficLight")
def traffic_light(a: Assembly) -> None:
    """n lights of h x h behind fronts at 2t from the front edge, each with a shade of
    depth s on top (upright, stacked in z) or on the right (side by side, along x).
    World: back at y = depth, front edge at y = 0, shades towards -y. Windows stay 2D."""
    b = a.box
    t = a.t
    p = a.parts
    d, h, n = b.depth, b.h, b.n
    th = n * (h + t) - t
    if b.upright:
        a.place(p.label("back"), (0.0, d, 0.0), Z, X, Y)
        # Sides: local x = 0 at the top (the shade profile slants out towards it).
        a.place(p.label("left"), (0.0, d, th), neg(Z), neg(Y), neg(X))
        a.place(p.label("right"), (h, d, th), neg(Z), neg(Y), X)
        for k in range(1, n + 1):
            a.place(p.label(f"horizontal Wall {k}"), (0.0, d, k * (h + t) - t), X, neg(Y), Z)
        a.place(p.label("bottom wall"), (0.0, d, 0.0), X, neg(Y), neg(Z))
        for i in range(n):
            a.place(p.label(f"front {i + 1}"), (0.0, 2.5 * t, i * (h + t)), X, Z, neg(Y))
        a.dim("h", (0.0, 0.0, 0.0), (h, 0.0, 0.0), neg(Y))
    else:
        a.place(p.label("back"), (0.0, d, 0.0), X, Z, Y)
        a.place(p.label("bottom"), (0.0, d, 0.0), X, neg(Y), neg(Z))
        a.place(p.label("top"), (0.0, d, h), X, neg(Y), Z)
        for k in range(1, n):
            a.place(p.label(f"vertical wall {k}"), (k * (h + t) - t, d, 0.0), Z, neg(Y), X)
        a.place(p.label(f"vertical wall {n}"), (th, d, 0.0), Z, neg(Y), X)
        a.place(p.label("vertical wall"), (0.0, d, 0.0), Z, neg(Y), neg(X), flip=True)
        for i in range(n):
            a.place(p.label(f"front {i + 1}"), (i * (h + t), 2.5 * t, 0.0), Z, X, neg(Y))


@placement("PhotoFrame")
def photo_frame(a: Assembly) -> None:
    """Three layers: base, middle (a pocket open at the top, in one piece or a bottom and two
    sides joined by dovetails) and front (one piece or four mitred ones). In the pocket: the
    photo (0.3 mm) and the matting (the rest of the pocket's depth, standing in for mat and
    glass). World: the frame lies flat, front up, its top edge at y = base_y."""
    b = a.box
    t = a.t
    p = a.parts
    d = b.d
    bx, by = d.base_x, d.base_y
    a.place(p.labelled("Base").first(), (0.0, 0.0, 0.0), X, Y, Z, name="base")
    a.place(p.labelled("Middle btm").first(), (0.0, 0.0, t), X, Y, Z)
    sides = list(p.labelled("Middle side"))
    for part, x0 in zip(sides, (0.0, bx - d.guide_w)):
        a.place(part, (x0, by, t), neg(Y), X, Z)
    a.place(p.labelled("Middle").first(), (0.0, 0.0, t), X, Y, Z)  # unsplit
    a.place(p.labelled("Front btm").first(), (0.0, 0.0, 2 * t), X, Y, Z)
    a.place(p.labelled("Front top").first(), (bx, by, 2 * t), neg(X), neg(Y), Z)
    a.place(p.labelled("Front side L").first(), (0.0, by, 2 * t), neg(Y), X, Z)
    a.place(p.labelled("Front side R").first(), (bx, 0.0, 2 * t), Y, neg(X), Z)
    a.place(p.labelled("Front").first(), (0.0, 0.0, 2 * t), X, Y, Z)  # unsplit
    pt = min(0.3, t / 2)
    a.place(p.labelled("Photo").first(), (d.centre_x - d.photo_x / 2, d.centre_y - d.photo_y / 2, t),
            X, Y, Z, thickness=pt)
    a.place(p.labelled("Matting").first(), (d.centre_x - d.mat_x / 2, d.centre_y - d.mat_y / 2, t + pt),
            X, Y, Z, thickness=t - pt)


@placement("MakitaPowerSupply")
def makita_power_supply(a: Assembly) -> None:
    """Fixed 85 x 75 x 35 box; the two battery rails hang under the bottom in its finger
    holes. The rails' inner plates (side2) stay 2D."""
    b = a.box
    t = a.t
    p = a.parts
    x, y, h = b.x, b.y, b.h
    f = a.frame(x, y, h)
    w = list(_helper(p, "rectangularWall"))
    if len(w) < 6:
        return
    f.front(w[0])
    f.left(w[1])
    f.right(w[2])
    f.back(w[3])
    f.bottom(w[4])
    f.top(w[5])
    rails = [q for q in _helper(p, "free") if "MakitaPowerSupply.side" in q.callers][:2]
    for part, s in zip(rails, (-1, 1)):
        xc = x / 2 + s * (30.5 + 0.5 * t)
        a.place(part, (xc - s * t / 2, y - 10, 0.0), neg(Z), neg(Y), (s, 0.0, 0.0),
                flip=part.mirrored, name="rail")


@placement("AirPurifier")
def air_purifier(a: Assembly) -> None:
    """Stands on its bottom with the filters as the large faces, at y = 0 (and y = h with two
    filters); each filter is held by an outer frame on the face and an inner frame in the
    walls' finger holes (split frames: four pieces each, joined by dovetails). The top only
    covers the fans between the filters, so these slide in from above.
    World: x = width, y = through the filters (h), z = the y parameter (height)."""
    b = a.box
    t = a.t
    p = a.parts
    x, H, d = b.x, b.y, b.fan_diameter  # b.y is already shortened by t
    r, fh = b.rim, b.filter_height
    h = d + 2 + b.filters * (fh + t)
    a.place(p.label("bottom"), (0.0, 0.0, 0.0), X, Y, neg(Z))
    a.place(p.label("top"), (0.0, fh + t + 1, H), X, Y, Z)  # centred on the sides' F part (d + 2)
    walls = list(_helper(p, "rectangularWall").where(lambda q: not q.label))
    sides, frames = walls[:2], walls[2:]
    # Sides: local x = 0 at the top, where the top joins them.
    a.place(sides[0] if sides else None, (0.0, 0.0, H), neg(Z), Y, neg(X), name="left")
    a.place(sides[1] if len(sides) > 1 else None, (x, 0.0, H), neg(Z), Y, X, name="right")
    faces = [(0.0, neg(Y)), (h, Y)][:b.filters]  # outer face, material outwards
    inner = [fh, h - fh - t][:b.filters]
    per = 8 if b.split_frames else 2
    for k in range(b.filters):
        group = frames[k * per:(k + 1) * per]
        y_out, n_out = faces[k]
        outer, inside = group[:per // 2], group[per // 2:]
        if not b.split_frames:  # drawn inner plate first
            outer, inside = inside, outer
        for (y0, n), pieces in (((y_out, n_out), outer), ((inner[k], Y), inside)):
            if not b.split_frames:
                a.place(pieces[0] if pieces else None, (0.0, y0, 0.0), X, Z, n, name="frame")
                continue
            if len(pieces) < 4:
                continue
            a.place(pieces[0], (0.0, y0, 0.0), X, Z, n, name="frame bottom")
            a.place(pieces[1], (0.0, y0, r), Z, X, n, name="frame left")
            a.place(pieces[2], (x, y0, r), Z, neg(X), n, name="frame right")
            a.place(pieces[3], (0.0, y0, H - r), X, Z, n, name="frame top")
    if b.filters == 1 and len(frames) > per:
        a.place(frames[per], (0.0, h, 0.0), X, Z, Y, name="back")


@placement("CoffeeCapsuleHolder")
def coffee_capsule_holder(a: Assembly) -> None:
    """Three plates screwed together on the wall: back (optional), middle (capsule bodies)
    and front (lids, opening at the bottom)."""
    plates = list(_helper(a.parts, "free").drawn_by("CoffeeCapsuleHolder.render_plate"))
    n = len(plates)
    for i, (plate, name) in enumerate(zip(plates, ("front", "middle", "back"))):
        a.place(plate, (0.0, (i - n + 1) * a.t, 0.0), X, Z, Y, name=name)


def _ring_walls(a: Assembly, segs, walls, z0: float = 0.0) -> None:
    """Stands walls on the segments ((x, y), (dx, dy), length) of a counter-clockwise
    polygon (world xy), inner face on the segment line, material outwards."""
    for (px, py), (dx, dy), _ in segs:
        if not walls:
            return
        a.place(walls.pop(0), (px, py, z0), (dx, dy, 0.0), Z, (dy, -dx, 0.0))


def _centred_plate(a: Assembly, part, z0: float, down: bool = False, name: str = "") -> None:
    """Lays a plate drawn centred in its move box with its centre on the world z axis."""
    if part is not None:
        a.place(part, (-part.x / 2, -part.y / 2, z0), X, Y, neg(Z) if down else Z, name=name)


@placement("AngledBox")
def angled_box(a: Assembly) -> None:
    """Floor: a (2n+2)-gon stretched to x, walls 1.. around it counter-clockwise from the
    front long side. World: centre of the floor at the origin, floor z [-t, 0]."""
    b = a.box
    t = a.t
    p = a.parts
    x, y, h, n = b.x, b.y, b.h, max(1, b.n)
    if x < y:
        x, y = y, x
    if b.outside:
        x, y = b.adjustSize(x), b.adjustSize(y)
        if b.top == "none":
            h = b.adjustSize(h, False)
        elif "lid" in b.top and b.top != "angled lid":
            h = b.adjustSize(h) - t
        else:
            h = b.adjustSize(h)
    r, hp, side = b.regularPolygon(2 * n + 2, h=y / 2.0)
    lx = x - 2 * hp + side if n % 2 else x - 2 * r + side
    borders = []
    for length in ([lx] + [side] * n) * 2:
        borders += [length, 360.0 / (2 * n + 2)]
    segs = _polygon_segments(borders, (-lx / 2, -y / 2))
    _ring_walls(a, segs, [p.label(f"wall {i + 1}") for i in range(2 * n + 2)])
    floors = list(_helper(p, "free"))  # labels are given after drawing: not recorded
    if b.bottom_edge != "e" and floors:
        _centred_plate(a, floors.pop(0), 0.0, down=True, name="Bottom")
    if b.top == "angled lid":
        _centred_plate(a, floors[0] if floors else None, h - t, name="Lower Lid")
        _centred_plate(a, floors[1] if len(floors) > 1 else None, h, name="Upper Lid")
    elif b.top in ("angled hole", "angled lid2"):
        _centred_plate(a, floors[0] if floors else None, h, name="Top Rim and Lid")
        _centred_plate(a, floors[1] if len(floors) > 1 else None, h + t, name="Upper Lid")
    if b.x < b.y or b.outside:  # the lines would show the other/outer parameter
        return
    a.dim("x", (-x / 2, -y / 2, 0.0), (x / 2, -y / 2, 0.0), neg(Y))
    a.dim("y", (x / 2, -y / 2, 0.0), (x / 2, y / 2, 0.0), X)
    a.dim("h", (-lx / 2, -y / 2, 0.0), (-lx / 2, -y / 2, h), neg(Y))


def _polygon_plate(a: Assembly, part, z0: float, down: bool = False, name: str = "") -> None:
    """Lays a regularPolygonWall with its centre on the world z axis and its first side
    parallel to x, at the front (-y)."""
    if part is None:
        return
    prm = part.rec["params"]
    cx, cy = prm["start"][0] + prm["side"] / 2, prm["start"][1] + prm["h"]
    a.place(part, (-cx, -cy, z0), X, Y, neg(Z) if down else Z, name=name)


def _disc(a: Assembly, part, z0: float, name: str = "") -> None:
    _centred_plate(a, part, z0, name=name)


@placement("RegularBox")
def regular_box(a: Assembly) -> None:
    """A regular n-gon frustum: bottom (radius_bottom) and top (radius_top) polygons, side
    walls leaning between them. World: centre of the bottom at the origin, first side at
    the front, bottom plate z [-t, 0]."""
    b = a.box
    t = a.t
    p = a.parts
    r0, r1, h, n = b.radius_bottom, b.radius_top, b.h, b.n
    if b.outside:
        r0 = r0 - t / math.cos(math.radians(360 / (2 * n)))
        r1 = r1 - t / math.cos(math.radians(360 / (2 * n)))
        if b.top == "none":
            h = b.adjustSize(h, False)
        elif "lid" in b.top and b.top != "angled lid":
            h = b.adjustSize(h) - t
        else:
            h = b.adjustSize(h)
    r0, sh0, side0 = b.regularPolygon(n, radius=r0)
    r1, sh1, side1 = b.regularPolygon(n, radius=r1)
    plates = list(p.where(lambda q: q.rec["helper"] in ("regularPolygonWall", "free")))

    def take(helper):
        if plates and plates[0].rec["helper"] == helper:
            return plates.pop(0)
        return None

    def lids(kind: str, z: float, sign: int) -> None:
        """drawTop's plates for one end; z is the end's edge line, sign +1 outwards up."""
        down = sign < 0
        if kind in ("closed", "hole", "angled hole", "round lid", "angled lid2"):
            _polygon_plate(a, take("regularPolygonWall"), z, down)
            if kind == "angled lid2":
                _polygon_plate(a, take("regularPolygonWall"), z + sign * t, down, "lid")
            if kind == "round lid":
                _disc(a, take("free"), z + t if sign > 0 else z - 2 * t, "round lid")
        elif kind == "angled lid":
            _polygon_plate(a, take("regularPolygonWall"), z - sign * t, down, "lower lid")
            _polygon_plate(a, take("regularPolygonWall"), z, down, "upper lid")

    lids(b.bottom, 0.0, -1)
    if b.top != "bayonet mount":  # its rings stay 2D
        lids(b.top, h, 1)
    walls = list(_helper(p, "polygonWall"))
    for k, wall in enumerate(walls[:n]):
        ang = math.radians(360.0 * k / n)
        d = (math.cos(ang), math.sin(ang), 0.0)
        out = (math.sin(ang), -math.cos(ang), 0.0)
        p0 = add(add((0.0, 0.0, 0.0), d, -side0 / 2), out, sh0)
        lf = math.hypot(sh1 - sh0, h)
        v = add((0.0, 0.0, h / lf), out, (sh1 - sh0) / lf)
        nn = add((0.0, 0.0, -(sh1 - sh0) / lf), out, h / lf)
        sx, sy = wall.rec["params"]["start"]
        a.place(wall, add(add(p0, d, -sx), v, -sy), d, v, nn)
    a.dim("h", add((0.0, 0.0, 0.0), (0.0, -1.0, 0.0), sh0),
          add((0.0, 0.0, h), (0.0, -1.0, 0.0), sh1), (0.0, -1.0, 0.0))


@placement("RegularStarBox")
def regular_star_box(a: Assembly) -> None:
    """Two equal halves (polygon plate + n walls standing on it); the upper one is turned
    over and by 180/n, so the walls cross into a star and their slots interlock. The lowered
    middle of each wall's top runs under the other half's plate. World: centre of the lower
    plate at the origin, lower plate z [-t, 0], upper plate z [h, h + t]."""
    b = a.box
    t = a.t
    p = a.parts
    n = b.n
    h = b.h  # render stores the adjusted height
    plates = list(_helper(p, "regularPolygonWall"))
    walls = list(_helper(p, "rectangularWall"))
    _, sh, side = b.regularPolygon(n, radius=b.r if b.outside else b.radius)
    # turning over already shifts an odd polygon by 180/n
    c, s = (1.0, 0.0) if n % 2 else (math.cos(math.pi / n), math.sin(math.pi / n))

    def turn(v):  # the upper half: over around x, then by 180/n around z
        x, y, z = v[0], -v[1], -v[2]
        return (c * x - s * y, s * x + c * y, z)

    for half in range(2):
        place = _Moved(a, turn, (0.0, 0.0, h)).place if half else a.place
        if len(plates) > half:
            prm = plates[half].rec["params"]
            cx, cy = prm["start"][0] + prm["side"] / 2, prm["start"][1] + prm["h"]
            place(plates[half], (-cx, -cy, 0.0), X, Y, neg(Z), name=("bottom", "top")[half])
        for k, wall in enumerate(walls[half * n:(half + 1) * n]):
            ang = 2 * math.pi * k / n
            d = (math.cos(ang), math.sin(ang), 0.0)
            out = (math.sin(ang), -math.cos(ang), 0.0)
            place(wall, add(add((0.0, 0.0, 0.0), d, -side / 2), out, sh), d, Z, out)
    lo, hi = (-t, h + t) if b.outside else (0.0, h)  # what the h parameter measures
    a.dim("h", (0.0, -sh, lo), (0.0, -sh, hi), neg(Y))


def _polygon_walls(a: Assembly, pieces, borders, origin, h: float, bottom="F",
                   symmetrical: bool = True, U=X, V=Y, W=Z) -> None:
    """Boxes.polygonWalls(borders, h) around a polygonWall(borders) plate whose own frame
    has its origin at origin and x along U, y along V. The walls rise along W from their
    lower edge line through origin, inner face on the plate's outline; rounded corners
    become flex bends.
    pieces: the wall pieces (unrecorded cuts: stroke bbox frames, so not in drawing order;
    polygonWalls draws them left to right)."""
    b = a.box
    t = a.t
    pieces = sorted(pieces, key=lambda q: q.rec["matrix"][2])
    borders = b._closePolygon(list(borders))
    bottom = b.edges.get(bottom, bottom)
    ys = b.burn + bottom.spacing()
    px, py, ang = 0.0, 0.0, 0.0
    prev = borders[-1]
    i = 0
    cnt = 0
    lc = 0.0  # a concave corner shortens the walls on both sides
    while i < len(borders) and pieces:
        start, d0 = (px + math.cos(ang) * lc, py + math.sin(ang) * lc), ang
        if prev == 0:
            left = b.edges["d"]
        else:
            settings = copy.deepcopy(b.edges["f"].settings)
            settings.setValues(b.thickness, angle=prev)
            lf, lF, _ = settings.edgeObjects(b, add=False)
            left = lF if symmetrical and cnt % 2 == 0 else lf
        bends = []
        s = -lc
        while True:
            length, turn = float(borders[i]), borders[i + 1]
            px, py = px + math.cos(ang) * length, py + math.sin(ang) * length
            s += length
            i += 2
            if not isinstance(turn, (list, tuple)):
                break
            ta, r = float(turn[0]), max(float(turn[1]), 0.01)
            bends.append((s, ta, r))
            # around the centre on the inside
            dx, dy = math.cos(ang), math.sin(ang)
            side = 1 if ta > 0 else -1
            cx, cy = px - dy * r * side, py + dx * r * side
            vx, vy = px - cx, py - cy
            q = math.radians(ta)
            px = cx + math.cos(q) * vx - math.sin(q) * vy
            py = cy + math.sin(q) * vx + math.cos(q) * vy
            ang += q
            s += abs(q) * r
        ang += math.radians(float(turn))
        prev = turn
        lc = t * math.tan(math.radians(-turn / 2)) if turn < 0 else 0.0
        part = pieces.pop(0)
        xs = b.burn + left.spacing()
        d = add(add((0.0, 0.0, 0.0), U, math.cos(d0)), V, math.sin(d0))
        out = add(add((0.0, 0.0, 0.0), U, math.sin(d0)), V, -math.cos(d0))
        p0 = add(add(origin, U, start[0]), V, start[1])
        bend = [(xs + s0, ta, r, 1.0) for s0, ta, r in bends] or None
        a.place(part, add(add(p0, d, -xs), W, -ys), d, W, out, bend=bend)
        cnt += 1


@placement("RoundedRegularBox", "RoundedTrapezoidBox")
def rounded_regular_box(a: Assembly) -> None:
    """Rounded polygon bottom and top (or ring + lid, its corners t larger) with the flex
    walls around. World: the bottom plate's frame at the origin, bottom z [-t, 0]."""
    b = a.box
    t = a.t
    p = a.parts
    plates = list(_helper(p, "polygonWall"))
    hole = [q for q in plates if any("holeCB" in c for c in q.callers)]
    for q in hole:
        a.scrap(q)
        plates.remove(q)
    if not plates:
        return
    bottom = plates[0]
    prm = bottom.rec["params"]
    sx, sy = prm["start"]
    a.place(bottom, (0.0, 0.0, 0.0), X, Y, neg(Z), name="bottom")
    if len(plates) > 1:
        a.place(plates[1], (0.0, 0.0, b.h), X, Y, Z, name="top")
    if len(plates) > 2:  # lid: radius + t, edge e, drawn from its own start
        lp = plates[2].rec["params"]
        lx, ly = lp["start"]
        a.place(plates[2], (sx - lx, sy - ly - t, b.h + t), X, Y, Z, name="lid")
    walls = [q for q in _helper(p, "free")]
    _polygon_walls(a, walls, prm["borders"], (sx, sy, 0.0), b.h)


def _plates_and_walls(a: Assembly, h: float, names=("bottom", "lid")) -> None:
    """Two polygonWall plates (the second may be drawn mirrored) with polygonWalls(h)
    between them. World: the bottom's frame at the origin, bottom z [-t, 0]."""
    p = a.parts
    plates = list(_helper(p, "polygonWall"))
    if not plates:
        return
    prm = plates[0].rec["params"]
    sx, sy = prm["start"]
    a.place(plates[0], (0.0, 0.0, 0.0), X, Y, neg(Z), name=names[0])
    if len(plates) > 1:
        a.place(plates[1], (0.0, 0.0, h), X, Y, Z, flip=plates[1].mirrored, name=names[1])
    _polygon_walls(a, _helper(p, "free"), prm["borders"], (sx, sy, 0.0), h)


@placement("Coffin")
def coffin(a: Assembly) -> None:
    """Hexagonal bottom and lid (with the cross) and one wall per side, angled finger joints
    at the corners."""
    _plates_and_walls(a, a.box.h)


@placement("Tetris")
def tetris(a: Assembly) -> None:
    """Block outline bottom and top, walls blocksize - 2t high (all outer sizes are full
    blocks)."""
    _plates_and_walls(a, a.box.blocksize - 2 * a.t, ("bottom", "top"))


@placement("HeartBox")
def heart_box(a: Assembly) -> None:
    """Heart top (first) and bottom (drawn mirrored), flex walls around, optional lid t
    larger all round. World: the top's frame at the origin, bottom z [-t, 0]."""
    b = a.box
    t = a.t
    p = a.parts
    plates = list(_helper(p, "polygonWall"))
    if len(plates) < 2:
        return
    prm = plates[0].rec["params"]
    sx, sy = prm["start"]
    a.place(plates[1], (0.0, 0.0, 0.0), X, Y, neg(Z), flip=True, name="bottom")
    a.place(plates[0], (0.0, 0.0, b.h), X, Y, Z, name="top")
    if len(plates) > 2:  # its tip (start) is t out along both legs
        lx, ly = plates[2].rec["params"]["start"]
        a.place(plates[2], (sx - lx - t, sy - ly - t, b.h + t), X, Y, Z, name="lid")
    _polygon_walls(a, _helper(p, "free"), prm["borders"], (sx, sy, 0.0), b.h)


@placement("Console")
def console(a: Assembly) -> None:
    """Two side profiles (depth along y, height along z) with the walls x wide between
    them. World: left side x [-t, 0], its profile frame's origin at the origin."""
    b = a.box
    p = a.parts
    sides = list(_helper(p, "polygonWall"))
    if not sides:
        return
    prm = sides[0].rec["params"]
    sx, sy = prm["start"]
    a.place(sides[0], (0.0, 0.0, 0.0), Y, Z, neg(X), name="left side")
    if len(sides) > 1:
        a.place(sides[1], (b.x, 0.0, 0.0), Y, Z, X, name="right side")
    _polygon_walls(a, _helper(p, "free"), prm["borders"], (0.0, sx, sy), b.x, U=Y, V=Z, W=X)


@placement("DoubleFlexDoorBox")
def double_flex_door_box(a: Assembly) -> None:
    """Front and back profiles (x by h, rounded, two latches in the middle of the top) with
    the flex wall y deep around them: from the latch at the top middle to the right, down,
    along the bottom, up the left and back to the middle. World: profile's inner corner at
    the origin, front side y [-t, 0]."""
    b = a.box
    t = a.t
    p = a.parts
    x, y, h, l = b.x, b.y, b.h, b.latchsize
    r = max(b.radius, 0.01)
    c4 = math.pi * r / 2
    sides = list(_helper(p, "free").drawn_by("DoubleFlexDoorBox.flexBoxSide"))
    if sides:
        # move box frames: the outline starts t in
        a.place(sides[0], (-t, 0.0, -t), X, Z, neg(Y), name="front")
    if len(sides) > 1:
        a.place(sides[1], (-t, y, -t), X, Z, Y, flip=sides[1].mirrored, name="back")
    wall = _helper(p, "free").drawn_by("DoubleFlexDoorBox.surroundingWall").first()
    # After the first latch (l long) the wall runs along the top from x/2 + l; its lower
    # edge (0.25 t above the frame) is the front's outer face.
    b1 = (x - 2 * r) / 2
    b2 = b1 + c4 + h - 2 * r
    b3 = b2 + c4 + x - 2 * r
    b4 = b3 + c4 + h - 2 * r
    a.place(wall, (x / 2, -1.25 * t, h), X, Y, Z, name="flex wall",
            bend=[(x0, 90, r) for x0 in (b1, b2, b3, b4)])


@placement("Desksign")
def desksign(a: Assembly) -> None:
    """Sign leaning back by angle, a right triangle on each side in its finger holes.
    World: the sign's lower front edge along x at the origin."""
    b = a.box
    t = a.t
    p = a.parts
    ang = math.radians(b.angle)
    v = (0.0, math.cos(ang), math.sin(ang))
    a.place(_helper(p, "rectangularWall").first(), (0.0, 0.0, 0.0), X, v,
            (0.0, -math.sin(ang), math.cos(ang)), name="sign")
    # the h edges' holes lie just outside the sign's frame
    tris = list(_helper(p, "rectangularTriangle"))
    for tri, x0, n in zip(tris, (0.0, b.width), (neg(X), X)):
        a.place(tri, (x0, 0.0, 0.0), Y, Z, n, flip=tri.mirrored, name="stand")
    a.dim("width", (0.0, 0.0, 0.0), (b.width, 0.0, 0.0), neg(Y))
    a.dim("height", (b.width, 0.0, 0.0), add((b.width, 0.0, 0.0), v, b.height), X)


class _Moved:
    """Stands in for an Assembly (e.g. under a BoxFrame) and places everything through
    a rigid motion: p -> m(p - o) + T, m a function on vectors (rotations only)."""

    def __init__(self, a: Assembly, m, T=(0.0, 0.0, 0.0)) -> None:
        self._a, self._m, self._T = a, m, T

    def __getattr__(self, k):
        return getattr(self._a, k)

    def place(self, part, origin, u, v, n, *args, **kw) -> None:
        m = self._m
        self._a.place(part, add(m(origin), self._T), m(u), m(v), m(n), *args, **kw)


@placement("DiceTower")
def dice_tower(a: Assembly) -> None:
    """Tower (inner width x depth x height), front at y = 0 with the exit below the front
    wall, ramps in the sides' finger holes. The tray (an over-the-top lid) lies open side up
    in front."""
    b = a.box
    t = a.t
    p = a.parts
    w, d, h = b.width, b.depth, b.height
    ang = math.radians(b.angle)
    f = a.frame(w, d, h)
    f.dims(x="width", y="depth", h="height")
    sides = list(p.labelled("side"))
    if sides:
        f.right(sides[0])  # drawn mirrored: its front edge (right) comes to y = 0
    if len(sides) > 1:
        f.left(sides[1])
    f.back(p.label("back"))
    gap = d * math.tan(ang)
    f.front(p.label("front"), dv=gap)
    f.bottom(p.label("bottom"), rot=180)  # E edge (the exit) at the front

    def ramp(part, sx, sy, cx, cy):
        """part's centre plane through the side's finger hole line from (sx, sy) along
        (cx, cy), side coordinates (x from the back to the front, y up)."""
        v = (0.0, -cx, cy)
        n = (0.0, cy, cx) if cx > 0 else (0.0, -cy, -cx)  # upwards
        o = add((0.0, d - sx, sy), n, -t / 2)
        a.place(part, o, X, v, n, name="ramp")

    ramps = list(p.labelled("ramp"))
    lc = 0.5 * t * math.sin(ang)
    pos_y = (d - lc) * math.tan(ang)
    if ramps:
        ramp(ramps.pop(0), lc, pos_y, math.cos(ang), -math.sin(ang))
    section = (h - pos_y - 4 * t) / max(1, b.ramps - 1)
    for i in range(b.ramps - 1):
        if not ramps:
            break
        y_i = pos_y + section * (i + 1)
        if i % 2 == 0:
            ramp(ramps.pop(0), d - lc, y_i, -math.cos(ang), -math.sin(ang))
        else:
            ramp(ramps.pop(0), lc, y_i, math.cos(ang), -math.sin(ang))
    lid = p.drawn_by("Lid.__call__")
    top = lid.label("lid top")
    if top is not None:
        dl = (top.x - w) / 2
        ly = h - (t if b.bottom else 2 * t)
        th = b.tray_height * t
        # Built as a lid on a box from z = 0, then turned over around x and moved in front.
        moved = _Moved(a, lambda q: (q[0], -q[1], -q[2]), (0.0, -dl - 2 * t, th))
        lf = BoxFrame(moved, w + 2 * dl, ly + 2 * dl, th, (-dl, -dl, 0.0), "tray")
        lf.top(top)
        lf.front(lid.label("lid front"))
        lf.back(lid.label("lid back"))
        lf.left(lid.label("lid left"))
        lf.right(lid.label("lid right"))


@placement("BookHolder")
def book_holder(a: Assembly) -> None:
    """Two side profiles (front at y = 0, back at y = their width) with the book back and
    book bottom plates on their F edges, the back support in their finger holes and the
    optional ledge below the book bottom's front edge. World: left side x [-t, 0]."""
    b = a.box
    t = a.t
    p = a.parts
    w, r = b.width, b.radius
    al, be = math.radians(b.angle), math.radians(90 - b.angle)
    A = b.book_height * math.sin(al)
    B = b.book_height * math.sin(be)
    C = b.book_depth * math.sin(be)
    D = b.book_depth * math.sin(al)
    hb = A + b.bottom_support + r
    hf = C + b.bottom_support + r
    os_, oc = math.sin(al) * r, math.cos(al) * r
    tw = r + oc + B + D + os_ + r
    # the side's outline, from its lower front corner counter-clockwise (x to the back)
    segs = _polygon_segments([tw, 90, hb - oc - r, [90 + b.angle, r], b.book_height, -90,
                              b.book_depth, [180 - b.angle, r], hf - os_ - r, 90], (0.0, 0.0))

    def world(q):  # side coordinates -> world (x = 0 plane)
        return (0.0, q[0], q[1])

    sides = list(_helper(p, "free").drawn_by("BookHolder.sideWall"))
    for side, x0, n in zip(sides, (0.0, w), (neg(X), X)):
        a.place(side, (x0, 0.0, 0.0), Y, Z, n, name="side")
    (pa, da, la), (pb, db, lb) = segs[2], segs[3]
    end_a = (pa[0] + da[0] * la, pa[1] + da[1] * la)
    end_b = (pb[0] + db[0] * lb, pb[1] + db[1] * lb)

    def inner(d):  # left of travel: into the side
        return (0.0, -d[1], d[0])

    # book back: bottom edge (f) at its lower end, material inside the profile
    a.place(p.label("book back"), world(end_a), X, world((-da[0], -da[1])), inner(da))
    nb = inner(db)
    bottom = p.label("book bottom")
    a.place(bottom, world(end_b), X, world((-db[0], -db[1])), nb)
    if b.back_support > 0:
        a.place(p.label("back support"), (0.0, tw - 1.5 * t, b.bottom_support), X, Z, neg(Y))
    ledge = _helper(p, "free").drawn_by("BookHolder.front_ledge").first()
    if ledge is not None:
        lh = b.ledge_height
        a.place(ledge, add(world(end_b), nb, -lh), X, nb, world(db), name="front ledge")
    a.dim("book_width", (-t, 0.0, 0.0), (w + t, 0.0, 0.0), neg(Y))
    a.dim("book_height", add(world(end_a), X, w + t), add(world(pa), X, w + t), X)


@placement("Display")
def display(a: Assembly) -> None:
    """Upright board (y [0, t]) with the shelf plate pushed through its slot at 0.2 h."""
    b = a.box
    t = a.t
    p = a.parts
    x, h, r = b.x, b.h, b.radius
    board = _helper(p, "free").first()
    a.place(board, (0.0, 0.0, 0.0), X, Z, Y, name="board")
    # board frame = its outline's bbox: the slot is x/2 right of the lower left corner
    oh = 1.2 * h - 2 * r
    hx = x / 2 + (math.sin(math.radians(b.angle)) * oh if b.angle > 0 else 0.0) + b.burn
    a.place(_helper(p, "roundedPlate").first(), (hx - 0.35 * x, t / 2 - x / 2, 0.2 * h - t / 2),
            X, Y, Z, name="shelf")


@placement("CoinDisplay")
def coin_display(a: Assembly) -> None:
    """Closed cube; inside, two sides and a back stand in the bottom's finger holes and hold
    the coin plate (on top, with the hole) and its base on their slanted top edges."""
    b = a.box
    t = a.t
    p = a.parts
    x, y, h = b.x, b.y, b.h
    if b.outside:
        x, y, h = b.adjustSize(x), b.adjustSize(y), b.adjustSize(h)
    f = a.frame(x, y, h)
    f.dims(x="x", y="y", h="h")
    f.front(p.label("Wall 1"))
    f.back(p.label("Wall 3"))
    f.left(p.label("Wall 2"))
    f.right(p.label("Wall 4"))
    f.top(p.label("Top"))
    f.bottom(p.label("Bottom"))
    # bottomHoles (in the bottom's coordinates, from the unadjusted x, y); f.bottom has its
    # local y = 0 at the back
    bx, by = b.x, b.y
    cp, cpx, ang = b.coin_plate, b.coin_plate_x, b.angle  # render made angle radians
    x1 = bx / 2 - 1.5 * t - cp / 2
    x2 = bx / 2 - 0.5 * t + cp / 2
    y0 = y - (by / 2 + cpx / 2 - t)  # the sides' holes start here and run to the back
    y3 = y - (by / 2 - cpx / 2 - 1.5 * t)
    for side, xc in zip(p.labelled("CoinSide").where(lambda q: q.label != "CoinSide3"), (x1, x2)):
        a.place(side, (xc + t / 2, y0, 0.0), Y, Z, neg(X), name="coin side")
    a.place(p.label("CoinSide3"), (bx / 2 - cp / 2 - t, y3 - t / 2, 0.0), X, Z, Y)
    # plates under the sides' slanted top (high at the front end), stacked in its 2t notch
    sh = b.coin_showcase_h
    v = (0.0, -math.cos(ang), math.sin(ang))
    n = (0.0, -math.sin(ang), -math.cos(ang))
    o = (x1 + t / 2, y0 + cpx, sh)
    a.place(p.label("Coin Plate"), o, X, v, n)
    a.place(p.label("Coin Plate Base"), add(o, n, t), X, v, n)


@placement("BirdHouse")
def bird_house(a: Assembly) -> None:
    """Gable ends front and back (x wide), long walls left and right (y), floor in all
    walls' finger holes, two roof halves on the 45 degree gable edges, meeting at the ridge.
    World: inner corner at the origin, floor z [-t, 0]."""
    b = a.box
    t = a.t
    p = a.parts
    x, y, h = b.x, b.y, b.h
    f = a.frame(x, y, h)
    f.dims(x="x", y="y", h="h")
    gables = list(_helper(p, "free").drawn_by("BirdHouse.side"))
    walls = list(_helper(p, "rectangularWall").where(lambda q: q.chars.startswith("h")))
    f.left(walls[0] if walls else None)
    f.right(walls[1] if len(walls) > 1 else None)
    f.bottom(_helper(p, "rectangularWall").first())
    if gables:
        # move box frames: the outline starts t in, its h edge band (ew + t) below z = 0
        hb = gables[0].y - h - x / 2 - 2 * t
        a.place(gables[0], (-t, 0.0, -hb), X, Z, neg(Y), name="front")
        if len(gables) > 1:
            a.place(gables[1], (x + t, y, -hb), neg(X), Z, Y, name="back")
    roofs = list(_helper(p, "free").drawn_by("BirdHouse.roof"))
    roof = 2 ** 0.5 * x / 2
    oh = roof * b.roof_overhang
    ridge = (x / 2, 0.0, h + t + x / 2)
    s = 0.5 ** 0.5
    # the holes start oh + roof + 2t up the frame (below the ridge edge's own width)
    y_top = oh + roof + 2 * t
    for part, side in zip(roofs, (1, -1)):
        v = (-side * s, 0.0, s)
        n = (side * s, 0.0, s)
        o = add(add(ridge, v, -y_top), Y, -(oh + t))
        a.place(part, o, Y, v, n, name="roof")


@placement("Ramp")
def ramp(a: Assembly) -> None:
    """Wedge (inner width x, depth tx, height ty): bottom plate, back wall, triangle sides
    outside x and n braces inside, the diagonal on the hypotenuse running down to the front."""
    b = a.box
    t = a.t
    p = a.parts
    tris = list(_helper(p, "rectangularTriangle"))
    if not tris:
        return
    tx, ty = tris[0].x, tris[0].y
    x = b.x
    ang = math.atan2(ty, tx)
    c, s = math.cos(ang), math.sin(ang)
    f = a.frame(x, tx, ty)
    f.bottom(p.label("Bottom"), rot=180)
    f.back(p.label("Vertical Wall"))
    # Triangles: the right angle (local (tx, 0)) at the back, on the floor.
    for tri, x0, n in zip(p.labelled("Side"), (0.0, x), (neg(X), X)):
        a.place(tri, (x0, 0.0, 0.0), Y, Z, n)
    for k, tri in enumerate(p.labelled("Inside")):
        a.place(tri, (x * (k + 1) / (b.n + 1) - t / 2, 0.0, 0.0), Y, Z, X)
    # Diagonal: local y = 0 at the top, past the back wall by t / cos.
    a.place(p.label("Diagonal"), (x, tx + t, ty + t * s / c), neg(X), (0.0, -c, -s), (0.0, -s, c))


@placement("TriangleLamp")
def triangle_lamp(a: Assembly) -> None:
    """Two lamps, each a right isosceles triangle (legs x along +X and +Y from the right
    angle at the origin): bottom, three walls, corner brackets at h - 1.5t carrying the
    screen flush with the top. The second lamp is turned by 180 degrees, hypotenuses back to
    back, so the pair forms a square."""
    b = a.box
    t = a.t
    p = a.parts
    x, h, c = b.x, b.h, b.cornersize
    tris = list(_helper(p, "rectangularTriangle"))
    walls = list(_helper(p, "rectangularWall"))
    if len(tris) < 10 or len(walls) < 6:
        return
    screens, bottoms, rights, corners = tris[0:2], tris[2:4], tris[4:6], tris[6:10]
    s2 = math.sqrt(0.5)
    m = (x + t * math.sqrt(2)) / 2 + 1.0
    for k in range(2):
        asm = a if k == 0 else _Moved(a, lambda v: (-v[0], -v[1], v[2]), (2 * m, 2 * m, 0.0))
        asm.place(bottoms[k], (x, 0.0, 0.0), neg(X), Y, neg(Z), name="bottom")
        asm.place(screens[k], (0.0, x, h - t), neg(Y), X, Z, name="screen")
        asm.place(walls[2 + k], (0.0, 0.0, 0.0), X, Z, neg(Y), name="wall")       # F at the right angle
        asm.place(walls[k], (0.0, x, 0.0), neg(Y), Z, neg(X), name="wall")        # f at the right angle
        asm.place(walls[4 + k], (x, 0.0, 0.0), (-s2, s2, 0.0), Z, (s2, s2, 0.0), name="wall")
        asm.place(rights[k], (0.0, c, h - 2 * t), neg(Y), X, Z, name="corner")
        asm.place(corners[2 * k], (x, 0.0, h - t), neg(X), Y, neg(Z), name="corner")
        asm.place(corners[2 * k + 1], (0.0, x, h - 2 * t), neg(Y), X, Z, name="corner")


@placement("PhoneHolder")
def phone_holder(a: Assembly) -> None:
    """Stand leaning back by angle: the front plate on the triangles' hypotenuses (bottom at
    the front, y = 0), the back plate behind their vertical legs, both covering the
    triangles outside the phone width. The bottom supports stand in the front plate's finger
    holes and through its bottom slots, the hook in front."""
    b = a.box
    t = a.t
    p = a.parts
    walls = list(_helper(p, "rectangularWall"))
    tris = list(_helper(p, "rectangularTriangle"))
    if len(walls) < 2 or len(tris) < 2:
        return
    w = b.phone_width
    rad = math.radians(b.angle)
    c, s = math.cos(rad), math.sin(rad)
    sd, sh = b.h * s, b.h * c
    a.place(walls[0], (0.0, 0.0, 0.0), X, (0.0, s, c), (0.0, -c, s), name="Front")
    a.place(walls[1], (w, sd, 0.0), neg(X), Z, Y, name="Back")
    for tri, x0 in zip(tris, (-t, w)):
        a.place(tri, (x0, 0.0, 0.0), Y, Z, X, name="Side")
    # Supports: local (fl, 0) on the front plate's foot, local +x to the front.
    margin = (w - b.bottom_support_spacing - t) / 2
    fl = (b.bottom_margin + b.tab_size) * s
    for q, cx in zip(p.where(lambda q: q.rec["helper"] == "free"), (margin, w - margin)):
        a.place(q, (cx + t / 2, fl, 0.0), neg(Y), Z, neg(X), flip=q.mirrored, name="Bottom support")


@placement("FilamentSpool")
def filament_spool(a: Assembly) -> None:
    """Axis along z: left flange z [-t, 0], the core's walls around a polygon (first side at
    the front) up to the polygon plate at h - t, the bayonet's lower disc (both pieces in
    one layer) on it and the right flange outside. The flanges' finger holes are around a
    side at their local +y, so they are turned by 180 degrees."""
    b = a.box
    t = a.t
    p = a.parts
    free = list(_helper(p, "free"))
    plate = next(iter(_helper(p, "regularPolygonWall")), None)
    walls = list(_helper(p, "rectangularWall"))
    if len(free) < 2 or plate is None:
        return
    n, h = b.sides, b.h
    prm = plate.rec["params"]
    side, sh = prm["side"], prm["h"]
    for q, z0, name in ((free[0], -t, "left flange"), (free[1], h + t, "right flange")):
        a.place(q, (-q.x / 2, -q.y / 2, z0), X, Y, Z, rot=180, name=name)
    _ring_walls(a, _polygon_segments([side, 360 / n] * n, (-side / 2, -sh)), walls)
    _polygon_plate(a, plate, h - t)
    for q in free[2:]:
        _disc(a, q, h, "bayonet")


@placement("OrganPipe")
def organ_pipe(a: Assembly) -> None:
    """Pipe along x (foot at x = 0, open or stopped end at x = L), mouth_width W along y,
    pipe_depth D along z: back wall z [-t, 0], sides at y = 0 and W, the front in two pieces
    with the mouth between them, the end cap at the foot and the languid at the foot's end,
    leaving the jet gap under the front."""
    p = a.parts
    walls = list(_helper(p, "rectangularWall"))
    if len(walls) < 7:
        return
    sides, back, upper, lower, cap, languid = walls[0:2], walls[2], walls[3], walls[4], walls[5], walls[6]
    t = a.t
    L, D, W, base = sides[0].x, sides[0].y, back.y, lower.x
    a.place(sides[0], (0.0, 0.0, 0.0), X, Z, neg(Y), name="side")
    a.place(sides[1], (L, W, 0.0), neg(X), Z, Y, flip=True, name="side")
    a.place(back, (0.0, W, 0.0), X, neg(Y), neg(Z), name="back")
    a.place(lower, (0.0, 0.0, D), X, Y, Z, name="front (foot)")
    a.place(upper, (L - upper.x, 0.0, D), X, Y, Z, name="front (resonator)")
    a.place(cap, (0.0, W, 0.0), neg(Y), Z, neg(X), name="foot (air hole)")
    a.place(languid, (base - t, 0.0, 0.0), Y, Z, X, name="languid")


@placement("LaptopStand")
def laptop_stand(a: Assembly) -> None:
    """Two triangles slotted into an X on the diagonals of the laptop's footprint, rear ends
    at the back (+y), crossing at their slots over the origin. Both come from one move box:
    the one with the bottom slot is drawn upright from local (off, 0), the other turned by
    180 degrees from (off + base - spacing, th)."""
    b = a.box
    t = a.t
    tris = sorted(_helper(a.parts, "free"),
                  key=lambda q: sum(pt[1] for pt in q.rec["outline"]["outer"]) / len(q.rec["outline"]["outer"]))
    if len(tris) < 2:
        return
    c = b.perform_calculations()
    base, sb = c["base"], math.sin(math.radians(c["angle"]))
    off = c["base_extra"] + b.spacing + sb * (c["lip_outer"] + 1)
    th = c["height"] + 2 * b.ground_offset + b.spacing
    s2 = math.sqrt(0.5)
    # Lower: local u runs from the rear to the front along fa; slot centre at xa.
    fa, na = (s2, -s2, 0.0), (-s2, -s2, 0.0)
    xa = off + base / 2 + 5 * s2 - 3.5
    a.place(tris[0], add(add((0.0, 0.0, 0.0), fa, -xa), na, -t / 2), fa, Z, na)
    # Upper: upside down, local u from the front to the rear.
    fb, nb = (-s2, -s2, 0.0), (-s2, s2, 0.0)
    a.place(tris[1], add(add((0.0, 0.0, th), fb, off + base / 2 - b.spacing), nb, -t / 2), neg(fb), neg(Z), nb)


@placement("BottleStack")
def bottle_stack(a: Assembly) -> None:
    """Fronts across x at depth t and l (= depth), the long beams along y in their slots at
    r3 + 2 r1 k, half-lapped. With double, the second stack (fronts with the asymmetric
    slots, short beams at 3.5t and 2 r1 k - t/2) sits inside the first, its deep slots over
    the first one's beams, pulled out sideways by its full width."""
    b = a.box
    t = a.t
    free = list(_helper(a.parts, "free"))
    nr, l, r1 = b.number, b.depth, b.diameter / 2
    pieces = 2 if b.double else 1
    fronts, beams = free[:2 * pieces], free[2 * pieces:]
    if len(fronts) < 2 * pieces:
        return
    long_ = [q for q in beams if q.x > l]
    short = [q for q in beams if q.x <= l]
    r3 = 1.5 * t if b.double else 0.5 * t
    tw = fronts[0].x
    # Back fronts flipped, not turned: the second stack's slots are not symmetric.
    stacks = [(0.0, (t, l), [r3 + 2 * r1 * k for k in range(nr + 1)], long_, 0.0)]
    if b.double:
        stacks.append((2 * r1 * nr, (2.5 * t, l - 1.5 * t),
                       [3.5 * t] + [2 * r1 * k - t / 2 for k in range(1, nr + 1)], short, 1.5 * t))
    for k, (dx, ys, xs, bs, dy) in enumerate(stacks):
        f0, f1 = fronts[2 * k:2 * k + 2]
        a.place(f0, (dx, ys[0] + t, 0.0), X, Z, neg(Y), name="Front")
        a.place(f1, (dx + tw, ys[1], 0.0), neg(X), Z, Y, flip=True, name="Front")
        for q, x in zip(bs, xs):
            a.place(q, (dx + x - t / 2, dy, 0.0), Y, Z, X, name="Beam")


@placement("BayonetBox")
def bayonet_box(a: Assembly) -> None:
    """Five disc layers stacked on the z axis in drawing order: bottom, ring, lower lug
    layer, upper lug layer, lid. Pieces cut from one disc share its frame and layer (the lid's
    lug ring sits inside the box's ring of the same layer)."""
    t = a.t
    layers: dict[float, list] = {}
    for q in _helper(a.parts, "free"):
        layers.setdefault(round(q.rec["matrix"][2], 3), []).append(q)
    for k, key in enumerate(sorted(layers)):
        for q in layers[key]:
            _disc(a, q, k * t, "lid" if k == 4 else "")


def _yz(y: float, z: float) -> tuple:
    return (0.0, y, z)


@placement("ShutterBox")
def shutter_box(a: Assembly) -> None:
    """Width x along X, depth y along Y (front at 0), the sides drawn bottom down with the
    rounded top corner(s) at the back (and front with style double). The shutter runs in a
    1.5t track at radius r - 1.5t .. r: rails on the sides' inner faces at the top, the
    panels (inner face at radius r - 2.5t) down the back (front), around the bottom
    corner(s), where the corner fillers are the outer guide, and along under a false floor.
    The door lies closed: from the front (top of the front wall) over the top and down."""
    b = a.box
    t = a.t
    p = a.parts
    x, l, h = b.x, b.y, b.h
    r = b.radius
    double = b.style == "double"
    n = b.n
    s = b.spacing

    def by(name):
        return [q for q in _helper(p, "free") if any(c.endswith("." + name) for c in q.rec["callers"])]

    def min_y(q):
        return min(pt[1] for pt in q.rec["outline"]["outer"])

    walls = list(_helper(p, "rectangularWall"))
    sides = by("side")
    if len(walls) < 5 or len(sides) < 2:
        return
    front, back, bottom, handle, panels = walls[0], walls[1], walls[2], walls[3], walls[4:]

    def on_side(q, right: bool, o, u, v, name=""):
        """Glues a flat piece to a side's inner face; (o, u, v) map its frame to (y, z)."""
        nx = u[1] * v[2] - u[2] * v[1]
        x0 = (x - t if nx > 0 else x) if right else (0.0 if nx > 0 else t)
        a.place(q, (x0, o[1], o[2]), u, v, (nx, 0.0, 0.0), name=name)

    for q, x0 in zip(sides, (-t, x)):
        a.place(q, (x0, -t, -t), Y, Z, X, name="side")
    a.place(bottom, (0.0, 0.0, 0.0), Y, X, neg(Z), name="bottom")
    a.place(front, (0.0, 0.0, 0.0), X, Z, neg(Y), name="front")
    a.place(back, (x, l, 0.0), neg(X), Z, Y, name="back")

    # Panels: straight pieces and chords of the bottom corners, front to back.
    rho, ang = r - 2.5 * t, 90.0 / n
    segs = []

    def chords(cy, th0):
        for k in range(n):
            t0, t1 = math.radians(th0 + k * ang), math.radians(th0 + (k + 1) * ang)
            p0 = (cy + rho * math.cos(t0), r + rho * math.sin(t0))
            p1 = (cy + rho * math.cos(t1), r + rho * math.sin(t1))
            d = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            segs.append((p0, ((p1[0] - p0[0]) / d, (p1[1] - p0[1]) / d)))

    vert = h - 2 * r > 2 * t
    if double:
        if vert:
            segs.append(((2.5 * t, h - r), (0.0, -1.0)))
        chords(r, 180.0)
        segs.append(((r, 2.5 * t), (1.0, 0.0)))
    else:
        segs.append(((0.0, 2.5 * t), (1.0, 0.0)))
    chords(l - r, 270.0)
    if vert:
        segs.append(((l - 2.5 * t, r), (0.0, 1.0)))
    for q, ((py, pz), (dy, dz)) in zip(panels, segs):
        a.place(q, (0.0, py, pz), (0.0, dy, dz), X, (0.0, dz, -dy), name="panel")

    # Corner fillers: square corner in the box corner, concave arc of radius r.
    fill = sorted(by("cornerRadius"), key=lambda q: (q.rec["matrix"][2], min_y(q)))
    corners = [(l - r, l, Y)] if not double else [(r, 0.0, neg(Y)), (l - r, l, Y)]
    for k, (y1, y2, u1) in enumerate(corners):
        pair = fill[2 * k:2 * k + 2]
        if len(pair) == 2:
            on_side(pair[0], False, _yz(y1, 0.0), u1, Z, "corner")
            on_side(pair[1], True, _yz(y2, r + s), neg(u1), neg(Z), "corner")

    # Rails: outer r .. r + t and inner r - 2.5t .. r - 1.5t, their outer edge drawn at y = 0.
    rails = sorted(by("rails2" if double else "rails"), key=min_y)
    if double:
        orgs = [(r + t, 0.0), (r + t, 1.5 * t), (r + t, r + 1.5 * t), (r + t, r + 3 * t)]
        kinds = [(False, True), (False, False), (True, True), (True, False)]
        u0 = r
    else:
        orgs = [(2.5 * t + s, 0.0), (1.5 * t, t + s), (2 * t, 2 * t + 2 * s), (t - s, 3 * t + 3 * s)]
        kinds = [(False, True), (True, True), (False, False), (True, False)]
        u0 = 0.0
    for q, (ox, oy), (right, outer) in zip(rails, orgs, kinds):
        z0 = (h + t if outer else h - 1.5 * t) + oy
        on_side(q, right, _yz(u0 - ox, z0), Y, neg(Z), "rail")

    # Door: inner face on the inner guides (radius r - 1.5t), bent around each corner.
    door = next(iter(by("door")), None)
    rd = r - 1.5 * t
    st = b.edges["X"].settings.stretch
    arc = math.pi / 2 * rd / st
    if double:
        bends = [(0.0, 90, rd, st), (arc + l - 2 * r, 90, rd, st),
                 (2 * arc + l - 2 * r + h - 2 * r, 90, rd, st)]
        a.place(door, (x - 0.1 * t, 1.5 * t, h - r), Z, neg(X), neg(Y), name="door", bend=bends)
        a.place(handle, (1.1 * t, 0.5 * t, h - r + 0.5 * t), neg(Y), X, Z, name="handle")
    else:
        bends = [(l - r, 90, rd, st), (l - r + arc + h - 2 * r, 90, rd, st)]
        a.place(door, (x - 0.1 * t, 0.0, h - 1.5 * t), Y, neg(X), Z, name="door", bend=bends)
        a.place(handle, (1.1 * t, 0.5 * t, h - 0.5 * t), Z, X, Y, name="handle")


@placement("BreadBox")
def bread_box(a: Assembly) -> None:
    """Length x along X, depth y along Y between the two sides, height h. Fixed top over the
    left half, the shutter in a 1.5t track (radius r - 1.5t .. r) over the right half and
    down the open right end; open, it slides back under the top and down the left end wall
    along the inner panels. The door lies closed, its lower end on the floor."""
    b = a.box
    t = a.t
    p = a.parts
    x, y, h, r, n, s = b.x, b.y, b.h, b.radius, b.n, b.spacing

    def by(name):
        return [q for q in _helper(p, "free") if any(c.endswith("." + name) for c in q.rec["callers"])]

    def min_y(q):
        return min(pt[1] for pt in q.rec["outline"]["outer"])

    walls = list(_helper(p, "rectangularWall"))
    sides = by("side")
    if len(walls) < 5 or len(sides) < 2:
        return
    end, bottom, top, handle, panels = walls[0], walls[1], walls[2], walls[3], walls[4:]

    def on_side(q, back: bool, o, u, v, name="", flip=False):
        """Glues a flat piece to a side's inner face; (o, u, v) map its frame to (x, z)."""
        ny = u[2] * v[0] - u[0] * v[2]
        y0 = (y - t if ny > 0 else y) if back else (0.0 if ny > 0 else t)
        a.place(q, (o[0], y0, o[2]), u, v, (0.0, ny, 0.0), name=name, flip=flip)

    for q, y0 in zip(sides, (0.0, y + t)):
        a.place(q, (-t, y0, -t), X, Z, neg(Y), name="side")
    a.place(end, (0.0, y, 0.0), neg(Y), Z, neg(X), name="end")
    a.place(bottom, (0.0, y, 0.0), X, neg(Y), neg(Z), name="bottom")
    a.place(top, (0.0, 0.0, h), X, Y, Z, name="top")

    # Inner panels (inner face at radius r - 2.5t around the top left corner).
    rho, ang = r - 2.5 * t, 90.0 / n
    segs = [((2.5 * t, 0.0), (0.0, 1.0))]
    for k in range(n):
        t0, t1 = math.radians(180 - k * ang), math.radians(180 - (k + 1) * ang)
        p0 = (r + rho * math.cos(t0), h - r + rho * math.sin(t0))
        p1 = (r + rho * math.cos(t1), h - r + rho * math.sin(t1))
        d = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        segs.append((p0, ((p1[0] - p0[0]) / d, (p1[1] - p0[1]) / d)))
    segs.append(((r, h - 2.5 * t), (1.0, 0.0)))
    for q, ((px, pz), (dx, dz)) in zip(panels, segs):
        a.place(q, (px, 0.0, pz), (dx, 0.0, dz), Y, (-dz, 0.0, dx), name="panel")

    # Corner fillers in the top left corner: outer guide of radius r.
    fill = sorted(by("cornerRadius"), key=min_y)
    if len(fill) == 2:
        on_side(fill[0], False, (r, 0.0, h), neg(X), neg(Z), "corner")
        on_side(fill[1], True, (0.0, 0.0, h - r - s), X, Z, "corner")

    # Rails (drawn mirrored): outer edge at y = 0, starting at x / 2 on top.
    rails = sorted(by("rails"), key=min_y)
    orgs = [(2.5 * t + s, 0.0), (1.5 * t, t + s), (2.5 * t - s, 2 * t + 2 * s), (1.5 * t - 2 * s, 3 * t + 3 * s)]
    kinds = [(False, True), (True, True), (False, False), (True, False)]
    for q, (ox, oy), (back, outer) in zip(rails, orgs, kinds):
        z0 = (h + t if outer else h - 1.5 * t) + oy
        on_side(q, back, (x / 2 - ox, 0.0, z0), X, neg(Z), "rail", flip=True)

    # Door: inner face on the inner rails; cut longer than the closed path, so its start
    # goes under the top until the lower end stands on the floor.
    door = next(iter(by("door")), None)
    if door is None:
        return
    rd = r - 1.5 * t
    st = b.edges["X"].settings.stretch
    arc = math.pi / 2 * rd / st
    x0 = x / 2 - max(0.0, door.x - (x / 2 - r) - arc - (h - r))
    a.place(door, (x0, 0.1 * t, h - 1.5 * t), X, Y, Z, name="door", bend=[(x - r - x0, 90, rd, st)])
    a.place(handle, (x0 + 1.5 * t, 1.1 * t, h - 0.5 * t), Z, Y, neg(X), name="handle")


@placement("FatBallDispenser")
def fat_ball_dispenser(a: Assembly) -> None:
    """Polygons centred on the z axis, first side at the front. Cage: floor z [0, t] with
    the balcony walls on its outer band, the ceiling on the (undrawn) poles at 2.5 ball
    diameters. Roof: the bracket under the ceiling's rim, the spacer around the ceiling, the
    roof base plate on top, the tiles as a pyramid on it (lower faces on the pyramid; their
    hips and the walls' corners are chamfered by hand) and the support plate inside under
    the tip."""
    b = a.box
    t = a.t
    p = a.parts
    polys = list(_helper(p, "regularPolygonWall"))

    def by(name):
        return [q for q in _helper(p, "free") if any(c.endswith("." + name) for c in q.rec["callers"])]

    if len(polys) < 3:
        return
    n = b.sides
    ceiling, roof, floor = polys[0], polys[1], polys[2]
    support = polys[3] if len(polys) > 3 else None
    # Same radii as render().
    ar_base = math.radians((180 - 360 / n) / 2)
    r_clearance = b.pole_clearance / math.sin(ar_base)
    r_pole = b.pole_diameter / 2
    r_poles = b.ball_diameter / 2 + max(r_pole, r_clearance) + r_pole
    r_ceiling = r_poles + r_pole + max(r_clearance, r_pole)
    r_outer = r_ceiling + b.slide_clearance + b.spacer_width
    _, h_outer, l_outer = b.regularPolygon(n, radius=r_outer)

    _polygon_plate(a, floor, 0.0, name="floor")
    fp = floor.rec["params"]
    pad = t * math.tan(math.radians(180 / n))
    for q, ((px, py), (dx, dy), _) in zip(by("balcony_wall"),
                                         _polygon_segments([fp["side"], 360 / n] * n, (-fp["side"] / 2, -fp["h"]))):
        a.place(q, (px - dx * pad, py - dy * pad, 0.0), (dx, dy, 0.0), Z, (dy, -dx, 0.0), name="balcony")

    zc = 2.5 * b.ball_diameter
    _polygon_plate(a, ceiling, zc, name="ceiling")
    locks = by("lock_part")
    for q, z0, name in zip(locks, (zc, zc - t), ("spacer", "bracket")):
        a.place(q, (-l_outer / 2, -h_outer, z0), X, Y, Z, name=name)
    zr = zc + 2 * t
    _polygon_plate(a, roof, zc + t, name="roof base")

    rp = roof.rec["params"]
    hf, hr = rp["h"], b.roof_height
    slant = math.hypot(hf, hr)
    cf, sf = hf / slant, hr / slant
    for q, ((px, py), (dx, dy), _) in zip(by("roof_tile"),
                                         _polygon_segments([rp["side"], 360 / n] * n, (-rp["side"] / 2, -hf))):
        nh = (dy, -dx, 0.0)
        v = (-cf * nh[0], -cf * nh[1], sf)
        a.place(q, (px, py, zr), (dx, dy, 0.0), v, (sf * nh[0], sf * nh[1], cf), name="roof tile")
    if support is not None:
        hs = support.rec["params"]["h"]
        _polygon_plate(a, support, zr + hr * (1 - hs / hf) - t, name="roof support")


@placement("SkadisStand")
def skadis_stand(a: Assembly) -> None:
    """One side piece (the generator draws one; a board stands on two) in the XZ plane, the
    foot along +X; with foot_front, the plate under it with the finger holes along its foot."""
    b = a.box
    t = a.t
    p = a.parts
    walls = list(_helper(p, "polygonWall"))
    if not walls:
        return
    sx0, sy0 = walls[0].rec["params"]["start"]  # the foot starts here (a vertical board leans past it)
    a.place(walls[0], (-sx0, t, -sy0), X, Z, (0, -1, 0), name="side")
    plates = list(_helper(p, "roundedPlate"))
    if plates and b.foot_front:
        w = max(b.foot / 10, t)
        # roundedPlate runs its callback from (r, 0), so the holes start at foot_front.
        a.place(plates[0], (-b.foot_front, t / 2 - w, -t), X, Y, Z, name="foot")


@placement("FlexBook")
def flex_book(a: Assembly) -> None:
    """Lying open side down: X from the fore edge to the spine, Y along the book's height (the
    generator's h), Z up, the inside x by y by h (render() swaps y and h). The front cover is
    the floor (inner face z = 0), the two D-shaped sides and the latch wall stand in its
    finger holes, the flex spine wraps the sides' half circles and the back cover closes on
    top, the latch tab through its slot. Latch brackets and pin stay 2D."""
    b = a.box
    t = a.t
    p = a.parts
    x, y, h = b.x, b.y, b.h  # after render(): h is the book's thickness, y its height
    r = b.radius

    def by(name):
        return [q for q in _helper(p, "free") if any(c.endswith("." + name) for c in q.rec["callers"])]

    covers, sides = by("flexBookCover"), by("flexBookSide")
    if covers:
        # The flex is cut 2 c4 + t long (+t "to make it fit"): it wraps the half circle at
        # the inner face, so the back cover's latch slot lands over the latch.
        st = math.pi * r / (math.pi * r + t)
        a.place(covers[0], (0.0, y + 4 * t, 0.0), X, neg(Y), neg(Z), name="cover",
                bend=[(x + 3 * t, 180, r, st)])
    # Side: its x runs down from the back cover (x = 0) to the floor, its y from the latch
    # wall's outer face to the spine; the mirrored one is the same piece turned over.
    for q, y0 in zip(sides, (2 * t, y + 3 * t)):
        a.place(q, (t, y0, h), neg(Z), X, neg(Y), flip=q.mirrored, name="side")
    for q in by("flexBookLatchWall"):
        x_adjust = 0 if b.recess_wall else 3 * t
        a.place(q, (t, t, h + x_adjust), neg(Z), Y, X, name="latch wall")
    for q in by("flexBookRecessedWall"):
        a.place(q, (x + 2 * t, t, h), neg(Z), Y, X, flip=q.mirrored, name="inner wall")

"""Placement functions: where each recorded wall of a generator goes in 3D.

Each function gets an Assembly (see assembly.py) after the generator has rendered and
places what it can. Parts left unplaced are shown in 2D only. Lids drawn by the shared
helpers (_TopEdge.drawLid, boxes.lids.Lid) have shared placers, so every generator that
uses them only needs to call place_lids().
"""
from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Callable

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

def place_lids(a: Assembly, f: BoxFrame, top_edge: str | None) -> None:
    """Lids from _TopEdge.drawLid(x, y, top_edge) and box.lid(x, y, top_edge) on frame f."""
    z = _top_edge_lid(a, f, top_edge) if top_edge is not None else f.h
    # A lid from box.lid sits on whatever closes the top.
    _lid(a, f if z == f.h else f.sub(0, 0, 0, f.x, f.y, z))


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


def _lid(a: Assembly, f: BoxFrame) -> None:
    """boxes.lids.Lid: the "lid" settings group."""
    parts = a.parts.drawn_by("Lid.__call__")
    if not parts:
        return
    s = a.box.lidSettings
    t = a.t
    x, y, h = f.x, f.y, f.h
    bs = s.brim_spacing
    style = s.style
    if style == "flat":
        f.plate(parts.label("lid bottom"), h - t, x0=bs, y0=bs)
        f.plate(parts.label("lid top"), h)
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
    # "chest" sides are not drawn with rectangularWall, so they are not recorded yet.


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
    p = a.parts
    _outer_walls(a, f, {"front": "front", "back": "back", "left side": "left",
                        "right side": "right", "bottom": "bottom"})
    if b.closedtop and b.hi == b.h:
        f.top(p.label("top"))
    # Inner walls: "inner x k" between rows of sy, "inner y k" between sx. sy runs back to
    # front (as on the left side wall), so the inner y walls are seen from the left.
    for k, y0 in enumerate(positions(b.sy, t), 1):
        f.inner_x(p.label(f"inner x {k}"), y - y0 - t)
    for k, x0 in enumerate(positions(b.sx, t), 1):
        f.inner_y(p.label(f"inner y {k}"), x0, flip=True)
    place_lids(a, f, b.top_edge)


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
    f.dims(h="h")
    # Column and row sizes as written in the layout ("outside" scales box.x/box.y down).
    given = SimpleNamespace()
    type(b).parse(given, b.layout.split("\n"))
    f.chain("layout", "x", given.x, label="x", axis="x")
    f.chain("layout", "-y", given.y, label="y", axis="y")
    _inner_height(f, xs[1:-1], ys[1:-1], b.hi)
    walls = iter(_helper(a.parts, "rectangularWall").drawn_by("TrayLayout.walls"))
    for j in range(ly + 1):
        for start, end in _runs(b.hwalls[j][:lx]):
            a.place(next(walls, None), (xs[start] + t, ys[j] + t, 0.0), X, Z, neg(Y),
                    name=f"wall x {start + 1}/{j + 1}")
    for i in range(lx + 1):
        for start, end in _runs([row[i] for row in b.vwalls[:ly]]):
            a.place(next(walls, None), (xs[i] + t, ys[start], 0.0), neg(Y), Z, neg(X),
                    name=f"wall y {i + 1}/{start + 1}")
    # Editable in 3D: every wall piece of the grid and every floor cell.
    for j in range(ly + 1):
        h = b.h if j in (0, ly) else b.hi
        for i in range(lx):
            a.handle("hwall", i, j, b.hwalls[j][i], (xs[i] + t, ys[j], 0.0), (xs[i + 1], ys[j] + t, h))
    for j in range(ly):
        for i in range(lx + 1):
            h = b.h if i in (0, lx) else b.hi
            a.handle("vwall", i, j, b.vwalls[j][i], (xs[i], ys[j + 1] + t, 0.0), (xs[i] + t, ys[j], h))
        for i in range(lx):
            a.handle("floor", i, j, b.floors[j][i], (xs[i] + t, ys[j + 1] + t, -t), (xs[i + 1], ys[j], 0.0))
    # The base plate is drawn from above with a margin of the F edge's width.
    w = b.edges["F"].startWidth()
    a.place(_helper(a.parts, "free").drawn_by("TrayLayout.base_plate").first(),
            (-w, -w, -t), X, Y, Z, name="bottom")
    place_lids(a, f, None)


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

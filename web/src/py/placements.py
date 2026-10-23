"""Placement functions: where each recorded wall of a generator goes in 3D.

Each function gets an Assembly (see assembly.py) after the generator has rendered and
places what it can. Parts left unplaced are shown in 2D only. Lids drawn by the shared
helpers (_TopEdge.drawLid, boxes.lids.Lid) have shared placers, so every generator that
uses them only needs to call place_lids().
"""
from __future__ import annotations

from typing import Callable

from assembly import Assembly, BoxFrame, X, Y, Z, neg, positions

PLACEMENTS: dict[str, Callable[[Assembly], None]] = {}


def placement(*names: str):
    def register(func):
        for name in names:
            PLACEMENTS[name] = func
        return func
    return register


def assemble(name: str, box, walls: list[dict]) -> dict[int, dict] | None:
    """Placements by index into walls, or None if the generator has no placement function."""
    func = PLACEMENTS.get(name)
    if func is None:
        return None
    asm = Assembly(box, walls)
    func(asm)
    return asm.placements


# --- Lids -----------------------------------------------------------------------------

def place_lids(a: Assembly, f: BoxFrame, top_edge: str | None) -> None:
    """Lids from _TopEdge.drawLid(x, y, top_edge) and box.lid(x, y, top_edge) on frame f."""
    if top_edge is not None:
        _top_edge_lid(a, f, top_edge)
    _lid(a, f)


def _top_edge_lid(a: Assembly, f: BoxFrame, top_edge: str) -> None:
    lid = a.parts.drawn_by("_TopEdge.drawLid")
    t = a.t
    if top_edge in "cfFhŠY":
        # Plate held by the walls' top edges.
        f.top(lid.label("top"))
    elif top_edge == "E":
        # Walls stick out by t: a plug fits between them, the cover sits on top.
        f.plate(lid.edges("eeee").first(), f.h)  # labelled "top" by drawLid
        f.plate(lid.edges("EEEE").first(), f.h + t)
    # Sliding/hinged lids (L, i, k, v) are not placed yet.


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
    _outer_walls(a, f, {"front": "front", "back": "back", "left": "left",
                        "right": "right", "bottom": "bottom"})
    place_lids(a, f, b.top_edge)


@placement("ABox")
def a_box(a: Assembly) -> None:
    b = a.box
    f = a.frame(b.x, b.y, b.h)
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

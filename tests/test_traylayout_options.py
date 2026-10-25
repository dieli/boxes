"""TrayLayout options: finger hole notches per wall, 0 mm liner rows/columns, sliding lid."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

try:
    import boxes
except ImportError:
    sys.path.append(Path(__file__).resolve().parent.parent.__str__())
    import boxes

from boxes.generators.traylayout import TrayLayout, TrayLayoutFile, TrayLidSettings


def grid(sx: list[float], sy: list[float]) -> str:
    """The default layout text for these column and row sizes."""
    f = TrayLayoutFile()
    f.fillDefault(sx, sy)
    return str(f)


def kind(edge) -> str:
    """Edge letters; a CompoundEdge as the letters of its parts."""
    if isinstance(edge, str):
        return edge
    if isinstance(edge, boxes.edges.CompoundEdge):
        return "".join(kind(e) for e in edge.types)
    return edge.char or "?"


def build(*args: str):
    """Renders a TrayLayout (inside sizes unless args say otherwise); returns it and its
    rectangular walls in drawing order as dicts (x, y, label, edges as letters, notch: finger
    hole notch depth set when it was drawn)."""
    box = TrayLayout()
    box.parseArgs(["--outside=0", *args])
    box.metadata["reproducible"] = True
    box.open()
    walls = []
    draw = box.rectangularWall

    def record(x, y, edges="eeee", *a, **kw):
        notch = box.edges["A"].settings.wallheight if "A" in box.edges else None
        walls.append({"x": x, "y": y, "label": kw.get("label"), "edges": [kind(e) for e in edges], "notch": notch})
        return draw(x, y, edges, *a, **kw)

    box.rectangularWall = record
    box.render()
    assert b"<svg" in box.close().getvalue()
    return box, walls


def build_holes(*args: str):
    """Renders a TrayLayout; returns it and the holes drawn in the callbacks of rectangular
    walls as dicts (label, kind, x, y: position in the wall's callback frame, length: of a
    finger hole row)."""
    box = TrayLayout()
    box.parseArgs(["--outside=0", "--burn=0", *args])
    box.metadata["reproducible"] = True
    box.open()
    holes: list[dict] = []
    frame: list = []  # (label, inverse matrix of the callback frame) while a callback runs
    draw = box.rectangularWall

    def record(x, y, edges="eeee", *a, callback=None, label=None, **kw):
        def wrap(cb):
            def run():
                frame.append((label, ~box.ctx._m))
                try:
                    cb()
                finally:
                    frame.pop()
            return run if callable(cb) else cb

        if callback is not None:
            callback = [wrap(cb) for cb in callback]
        return draw(x, y, edges, *a, callback=callback, label=label, **kw)

    def note(kind, x, y, **extra):
        if frame:
            label, inv = frame[-1]
            px, py = inv * (box.ctx._m * (x, y))
            holes.append({"label": label, "kind": kind, "x": px, "y": py, **extra})

    hole, rect_hole, finger_holes = box.hole, box.rectangularHole, box.fingerHolesAt

    def hole_(x, y, *a, **kw):
        note("hole", x, y, d=kw.get("d", 0))
        return hole(x, y, *a, **kw)

    def rect_hole_(x, y, dx, dy, *a, **kw):
        note("rect", x, y)
        return rect_hole(x, y, dx, dy, *a, **kw)

    def finger_holes_(x, y, length, angle=90, **kw):
        note("finger", x, y, length=length, angle=angle)
        return finger_holes(x, y, length, angle, **kw)

    box.rectangularWall, box.hole = record, hole_
    box.rectangularHole, box.fingerHolesAt = rect_hole_, finger_holes_
    box.render()
    box.close()
    return box, holes


def labelled(walls, label):
    return [w for w in walls if w["label"] == label]


def hwalls(walls, width):
    """The walls along x of a layout without gaps, back to front (drawn first, one per line)."""
    return [w for w in walls if w["x"] == width and w["label"] is None]


# --- Finger hole notches ------------------------------------------------------------------

def test_notch_depth_follows_each_wall():
    # Outer walls lower than the inner ones: their notches must not cut them in two.
    _, walls = build("--h=40", "--hi=80", "--fingerholes=front-and-back", "--layout=" + grid([50, 50], [50, 50]))
    notched = [w for w in walls if any("A" in e for e in w["edges"])]
    assert {w["y"] for w in notched} == {40, 80}
    for w in notched:
        assert w["notch"] == w["y"], w


def notch(box, wallheight: float, length: float = 50.0) -> float:
    """Depth of the finger hole notch box.edges["A"] draws in a wall this high."""
    edge = box.edges["A"]
    edge.settings.wallheight = wallheight
    drawn = []
    edge.polyline = lambda *p: drawn.append(p)
    edge(length)
    del edge.polyline
    if not drawn:
        return 0.0
    _, _, straight, (_, r), *_ = drawn[0]
    return straight + r


def test_notches_are_as_deep_in_every_wall():
    box, _ = build("--h=50", "--fingerholes=front-and-back", "--layout=" + grid([50], [50]))
    assert notch(box, 50) == notch(box, 30) == 20


def test_notches_leave_some_wall():
    box, _ = build("--h=50", "--FingerHoleEdge_absolute_depth=100", "--layout=" + grid([50], [50]))
    assert notch(box, 50) == pytest.approx(50 - box.thickness)
    assert notch(box, 20) == pytest.approx(18)  # a tenth of a wall lower than ten thicknesses


@pytest.mark.parametrize("fingerholes, outer", [("none", 0), ("inside-only", 0), ("front", 1), ("back", 1),
                                                ("front-and-back", 2)])
def test_outer_walls_get_notches_as_chosen(fingerholes, outer):
    _, walls = build("--h=50", f"--fingerholes={fingerholes}", "--layout=" + grid([50, 50], [50, 50, 50]))
    hwalls = [w for w in walls if w["x"] == 103]  # full width runs along x: 2 * 50 + t
    notched = [w for w in hwalls if "A" in w["edges"][2]]
    inner = 0 if fingerholes == "none" else 2
    assert len(notched) == inner + outer


# --- 0 mm rows and columns: liners ------------------------------------------------------

LINERS = """ ,> 0mm
 | ,> 50mm
 | | ,> 40mm
+-+-+-+
| | | |  0mm
+-+-+-+
| | | |  60mm
+-+-+-+
"""


def test_zero_size_edge_rows_and_columns_become_liners():
    box, walls = build("--h=50", "--layout=" + LINERS)
    assert box.x == [50 + 3, 40] and box.y == [60 + 3]
    assert {p["side"] for p in box.liner_pieces} == {"back", "left"}
    liners = [w for w in walls if w["y"] == box.hi and w["edges"] == ["e", "e", "e", "e"] and w["x"] > 10]
    assert len(liners) == len(box.liner_pieces)


@pytest.mark.parametrize("fingerholes, back_notched", [("none", False), ("inside-only", True), ("front", True),
                                                       ("back", True)])
def test_liners_are_notched_like_inner_walls(fingerholes, back_notched):
    box, walls = build("--h=50", f"--fingerholes={fingerholes}", "--layout=" + LINERS)
    liners = [w for w in walls if w["y"] == box.hi and w["edges"][0] == "e" and w["edges"][1] == "e"
              and w["edges"][3] == "e" and w["x"] > 10]
    assert len(liners) == len(box.liner_pieces)
    # Back liner along x: notched like an inner wall, also where the back wall is not. Left: never.
    for w, piece in zip(liners, box.liner_pieces):
        assert ("A" in w["edges"][2]) == (piece["side"] == "back" and back_notched), piece


def test_zero_size_inside_the_layout_raises():
    layout = grid([50, 50, 50], [50]).replace(" ,> 50.0mm\n | ,> 50.0mm", " ,> 50.0mm\n | ,> 0.0mm")
    with pytest.raises(ValueError, match="Only the first and the last column"):
        build("--layout=" + layout)


def test_outside_sizes_too_small_raise():
    with pytest.raises(ValueError, match="too small"):
        build("--outside=1", "--layout=" + grid([2, 2], [50]))


# --- Sliding lid ------------------------------------------------------------------------

def test_sliding_lid_walls_and_layers():
    t = 3
    box, walls = build("--h=50", "--Lid_style=sliding", "--layout=" + grid([50, 50], [40, 40]))
    back, inner, front = hwalls(walls, 103)
    assert (back["y"], inner["y"], front["y"]) == (50 + t, 50 - t, 50 - t)  # back raised, front lowered
    assert box.hi == 50 - t  # inner walls stay under the lid
    (bottom,) = labelled(walls, "lid bottom")
    (top,) = labelled(walls, "lid top")
    assert bottom["edges"][2] == "f"  # locks into the back wall's finger holes
    assert top["x"] == 103 and bottom["x"] == pytest.approx(103 - 2 * 0.1)


def test_sliding_lid_back_wall_has_no_finger_hole_notch():
    _, walls = build("--h=50", "--Lid_style=sliding", "--fingerholes=front-and-back",
                     "--layout=" + grid([50, 50], [40, 40]))
    back, inner, front = hwalls(walls, 103)
    assert "A" not in back["edges"][2]
    assert "A" in inner["edges"][2] and "A" in front["edges"][2]


def test_sliding_lid_follows_gaps_in_the_back_wall():
    layout = grid([50, 50], [50, 50]).replace("+-+-+\n", "+ +-+\n", 1)
    _, walls = build("--h=50", "--Lid_style=sliding", "--layout=" + layout)
    (bottom,) = labelled(walls, "lid bottom")
    back = bottom["edges"][2]
    assert "f" in back and "e" in back


@pytest.mark.parametrize("handle", ["long_rounded", "knob"])
def test_sliding_lid_with_handle(handle):
    box, walls = build("--Lid_style=sliding", f"--Lid_handle={handle}", "--layout=" + grid([50, 50], [50, 50]))
    assert labelled(walls, "lid bottom") and labelled(walls, "lid top")


def test_sliding_lid_magnets_that_do_not_fit_raise():
    with pytest.raises(ValueError, match="magnet holes do not fit"):
        build("--Lid_style=sliding", "--Lid_magnet_diameter=60", "--layout=" + grid([50], [50]))


def test_sliding_lid_on_too_low_walls_raises():
    with pytest.raises(ValueError, match="no height left"):
        build("--h=3", "--thickness=3", "--Lid_style=sliding", "--layout=" + grid([50], [50]))


def test_lid_settings_show_the_sliding_style_and_magnets():
    box = TrayLayout()
    help_text = box.argparser.format_help()
    assert "--Lid_magnet_diameter" in help_text and "magnet holes" in help_text
    assert "sliding" in TrayLidSettings.absolute_params["style"]
    box.parseArgs(["--Lid_style=sliding", "--layout=" + grid([50], [50])])
    box.open()
    assert type(box.lid).__name__ == "TrayLid" and box.lidSettings.style == "sliding"


def test_other_generators_keep_the_core_lid():
    from boxes.generators.abox import ABox
    box = ABox()
    box.parseArgs(["--Lid_style=flat"])
    box.open()
    assert type(box.lid) is boxes.lids.Lid
    assert type(box.lidSettings) is boxes.lids.LidSettings


# Positions in tray coordinates: x from the inside of the left wall, y from the inside of the
# front wall. The lower lid layer's frame starts at (bs, -t) (between the side walls, from the
# outside of the front wall), the upper layer's at (0, 0).

def to_tray(hole, t, bs):
    if hole["label"] == "lid bottom":
        return hole["x"] + bs, hole["y"] - t
    return hole["x"], hole["y"]


@pytest.mark.parametrize("handle", ["none", "long_rounded"])
def test_sliding_lid_handle_goes_through_both_layers(handle):
    t, bs = 3.0, 0.1
    _, holes = build_holes("--h=50", "--Lid_style=sliding", f"--Lid_handle={handle}",
                           "--layout=" + grid([50, 50], [40, 60]))
    lid = [h for h in holes if h["kind"] == "rect" and h["label"] in ("lid bottom", "lid top")]
    if handle == "none":
        # Only the upper layer has the grip slot, near the front.
        assert [h["label"] for h in lid] == ["lid top"]
        assert to_tray(lid[0], t, bs) == pytest.approx((51.5, 2 * t))
        return
    centres = {h["label"]: to_tray(h, t, bs) for h in lid}
    assert set(centres) == {"lid bottom", "lid top"}
    assert centres["lid bottom"] == pytest.approx(centres["lid top"])
    # Centred on the lid: x across the inside, y between the front wall's outside and y - bs.
    inner_y = 40 + 60 + t
    assert centres["lid top"] == pytest.approx((51.5, (inner_y - bs - t) / 2))


def test_sliding_lid_magnets_sit_behind_the_front_wall():
    t, bs, md = 3.0, 0.1, 6.0
    _, holes = build_holes("--h=50", "--Lid_style=sliding", "--Lid_handle=long_rounded",
                           f"--Lid_magnet_diameter={md:g}", "--layout=" + grid([50, 50], [50]))
    magnets = [to_tray(h, t, bs) for h in holes if h["kind"] == "hole" and h["label"] == "lid bottom"]
    assert len(magnets) == 2
    inner_x = 50 + 50 + t
    for x, y in magnets:
        assert y == pytest.approx(md / 2)  # spans 0 .. md behind the front wall
        assert bs + t - 1e-9 <= x - md / 2 and x + md / 2 <= inner_x - bs - t + 1e-9  # clear of the sides
    assert sorted(x for x, _ in magnets) == pytest.approx([bs + t + md / 2, inner_x - bs - t - md / 2])


def test_sliding_lid_magnets_into_the_grip_slot_raise():
    with pytest.raises(ValueError, match="grip slot"):
        build("--Lid_style=sliding", "--Lid_magnet_diameter=6", "--layout=" + grid([25], [50]))


def test_sliding_lid_fingers_match_the_back_wall_holes():
    # No back wall over the first column: the lid's fingers only where the holes are.
    t, bs = 3.0, 0.1
    layout = grid([40, 60, 30], [50, 40]).replace("+-+-+-+\n", "+ +-+-+\n", 1)
    box, holes = build_holes("--h=50", "--Lid_style=sliding", "--layout=" + layout)
    rows = [h for h in holes if h["kind"] == "finger" and h["angle"] == 0]
    assert len(rows) == 1  # one back wall piece, columns 2 and 3
    start = 40 + t  # the piece starts at the second column
    run = (start + rows[0]["x"], rows[0]["length"])
    assert run == pytest.approx((start + bs, 60 + t + 30 - 2 * bs))
    # The lower layer's back edge, from the left in tray coordinates.
    assert [(s + bs, l) for s, l in box.lid.back_runs] == [pytest.approx(run)]

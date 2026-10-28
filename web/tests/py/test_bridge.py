import argparse
import contextlib
import io
import json

import pytest
from affine import Affine
from boxes.Color import Color
from boxes.drawing import Path
from types import SimpleNamespace

import boxes
import boxes_bridge as bb


def render(name: str, **args) -> dict:
    with contextlib.redirect_stdout(io.StringIO()):
        out = bb.render_with_parts(name, json.dumps({"burn": "0", **args}))
    # Strict JSON: no NaN or Infinity (the browser's JSON.parse rejects them).
    return json.loads(out, parse_constant=lambda c: pytest.fail(f"{c} in JSON"))


def cut(*subpaths) -> Path:
    """One path of subpaths, each a list of points (M, then L)."""
    cmds = []
    for sp in subpaths:
        cmds.append(["M", *sp[0]])
        cmds += [["L", *p] for p in sp[1:]]
    return Path(cmds, {"rgb": Color.OUTER_CUT, "lw": 1})


# --- Arguments -------------------------------------------------------------------------

def test_unknown_and_hidden_parameters_are_rejected():
    for args in ({"input": "/etc/passwd"}, {"output": "x"}, {"thick": "3"}, {"nonsense": "1"}):
        with pytest.raises(ValueError, match="Unknown parameter"):
            render("ABox", **args)


def test_full_option_names_pass():
    assert render("ABox", thickness="4")["thickness"] == 4


def test_web_settings_do_not_leak_into_other_code():
    # The core tests run in the same process (root pytest): TrayLayout must keep --input.
    render("TrayLayout")
    from boxes.generators.traylayout import TrayLayout
    assert TrayLayout.UI == "" and boxes.ArgumentParser is argparse.ArgumentParser
    assert "--input" in TrayLayout().argparser.format_help()
    assert "--input" not in bb.get_schema("TrayLayout")


def test_every_schema_field_passes_the_filter():
    # One name for the form and the filter: the form's defaults are accepted as they are
    # (not rendered, which would take minutes for all generators).
    for name in bb._generators:
        box = bb._new_box(name)
        options = {bb._option_name(a): a for a in box.argparser._actions}
        fields = [f["name"] for g in json.loads(bb.get_schema(name))["groups"] for f in g["args"]]
        assert all(f in options for f in fields if not f.startswith("ramp")), name


def test_option_names_keep_inner_dashes_and_skip_short_flags():
    parser = argparse.ArgumentParser()
    names = [bb._option_name(parser.add_argument(*o)) for o in
             (["--foo-bar"], ["-x", "--xx"], ["-y"], ["pos"])]
    assert names == ["foo-bar", "xx", None, None]


@pytest.mark.parametrize("value", ["nan", "inf", "-Infinity"])
def test_non_finite_numbers_name_the_parameter(value):
    with pytest.raises(ValueError, match=f"^x: {value} is not a finite number"):
        render("ABox", x=value)


@pytest.mark.parametrize("args", [
    {"ramp_angle": "nan"}, {"ramp_height": "inf"}, {"ramp_height": "-5"},
    {"ramp_angle": "90"}, {"ramp_angle": "abc"},
])
def test_bad_ramp_values_leave_2d_and_3d_working(args):
    r = render("TypeTray", ramp="1", **args)
    assert r["svg"].startswith("<?xml") or "<svg" in r["svg"]
    assert r["assembly"] is True
    assert r["warnings"] and r["warnings"][0].startswith("Ramps left out: ramp_")
    assert not any(p["helper"] == "printed" for p in r["parts"])


def test_good_ramp_values_give_ramps_and_no_warning():
    r = render("TypeTray", ramp="1", ramp_height="auto", ramp_angle="30")
    assert r["warnings"] == []
    assert any(p["helper"] == "printed" for p in r["parts"])


def ramp_heights(name: str, **args) -> list[float]:
    """Heights of the card ramps in drawing order (compartments back to front, left to right)."""
    r = render(name, ramp="1", outside="0", **args)
    return [pytest.approx(max(q[1] for q in p["outline"]["outer"]), abs=1e-6)
            for p in r["parts"] if p["helper"] == "printed"]


# A front liner in the left column only (0 mm last row, gap in the line above it).
FRONT_LINER_LEFT = """ ,> 50mm
 | ,> 50mm
+-+-+
| | |  50mm
+-+ +
| | |  0mm
+-+-+
"""


@pytest.mark.parametrize("lid", ["none", "flat"])
def test_ramp_heights_follow_each_compartments_wall(lid):
    # Left: against the liner (as high as the inner walls); right: against the outer wall.
    # The flat lid's lower layer starts at h - t = 47, above both.
    heights = ramp_heights("TrayLayout", layout=FRONT_LINER_LEFT, h="50", hi="30",
                           ramp_side="front", ramp_height="45", Lid_style=lid)
    assert heights == [30.0, 45.0]


def test_auto_ramp_stops_under_the_liners_notch():
    # inside-only notches the liner (left compartment) like an inner wall, as "front" does;
    # the outer front wall (right compartment) stays as without finger holes.
    def auto(fingerholes):
        return [h.expected for h in ramp_heights("TrayLayout", layout=FRONT_LINER_LEFT, h="50", hi="30",
                                                 ramp_side="front", ramp_height="auto",
                                                 fingerholes=fingerholes)]
    left, right = auto("inside-only")
    assert left == auto("front")[0] < auto("none")[0]
    assert right == auto("none")[1]


def test_ramp_stays_under_a_flat_lid():
    assert ramp_heights("TypeTray", h="40", sx="50", sy="100", ramp_side="front",
                        ramp_height="50", Lid_style="flat") == [37.0]


def test_ramp_on_the_raised_back_wall():
    # back_height raises the back wall to 60 (top_edge "e"): no lid, so up to the wall.
    assert ramp_heights("TypeTray", h="30", back_height="30", sx="50", sy="100",
                        ramp_side="back", ramp_height="50") == [50.0]
    # The core ignores back_height with another top edge: the wall stays 40 high.
    assert ramp_heights("TypeTray", h="40", back_height="20", top_edge="h", sx="50", sy="100",
                        ramp_side="back", ramp_height="50") == [40.0]


def test_ramp_on_inner_walls_higher_than_the_outer_ones():
    assert ramp_heights("TrayLayout", h="30", hi="60", sx="50", sy="50*2", ramp_side="front",
                        ramp_height="50") == [50.0, 30.0]


def ramps(name: str, **args) -> list[dict]:
    r = render(name, ramp="1", outside="0", **args)
    return [p for p in r["parts"] if p["helper"] == "printed"]


def bounds(points) -> tuple[float, float, float, float]:
    xs, ys = [q[0] for q in points], [q[1] for q in points]
    return min(xs), min(ys), max(xs), max(ys)


# TrayLayout 2 x 2, ramps against the front walls: the back row leans on the notched inner wall
# (50 high, notch 20 deep: bottom at 30), the front row on the outer wall without holes.
TRAY = dict(h="50", sx="50*2", sy="60*2", fingerholes="inside-only", ramp_side="front")


def test_ramp_has_a_flat_top_then_the_slope():
    back, _, front, _ = ramps("TrayLayout", **TRAY, ramp_flat="10", ramp_hook="0", ramp_angle="45")
    assert back["outline"]["outer"][:4] == [pytest.approx(p) for p in ([0, 0], [40, 0], [10, 30], [0, 30])]
    assert front["outline"]["outer"][:4] == [pytest.approx(p) for p in ([0, 0], [25, 0], [10, 15], [0, 15])]
    assert "bodies" not in back
    # Without a flat top: the plain wedge.
    (plain, *_) = ramps("TrayLayout", **TRAY, ramp_flat="0", ramp_hook="0")
    assert len(plain["outline"]["outer"]) == 4  # triangle, closed


def test_short_compartment_takes_the_flat_top_first():
    (r, *_) = ramps("TypeTray", h="50", sx="50", sy="35", ramp_side="front", ramp_height="30",
                    ramp_flat="10")
    assert bounds(r["outline"]["outer"]) == pytest.approx((0, 0, 35, 30))
    assert r["outline"]["outer"][2] == pytest.approx([5, 30])


def test_hook_reaches_through_the_notch_and_down_the_far_side():
    t = 3.0
    back, _, front, _ = ramps("TrayLayout", **TRAY)  # defaults: hook 2, flat 10
    # auto: notch bottom + 1 mm lift + hook
    assert bounds(back["outline"]["outer"])[3] == pytest.approx(33)
    assert "bodies" not in front  # its wall has no finger hole
    tongue, lip = back["bodies"]
    # The tongue is flat, 1 mm above the bottom of the notch (centred in the 50 mm compartment),
    # up to the ramp's top, and spans the wall; the lip hangs on the far side, 5 mm below the
    # notch, over the whole compartment.
    assert len(tongue["outline"]) == 4
    lo, bottom, hi, top = bounds(tongue["outline"])
    assert (lo + hi) / 2 == pytest.approx(25)
    assert bottom == pytest.approx(31) and top == pytest.approx(33)
    assert hi - lo < 15  # narrower than the notch (0.3 of 50)
    assert tongue["origin"][0] - tongue["t"] == pytest.approx(-(t + 0.3))
    lo2, foot, hi2, top2 = bounds(lip["outline"])
    assert (lo2, hi2, top2) == pytest.approx((0.3, 50 - 0.3, 33)) and foot == pytest.approx(25)
    assert lip["origin"][0] - lip["t"] == pytest.approx(-(t + 0.3 + 2))


def test_no_hook_with_hook_zero():
    assert "bodies" not in ramps("TrayLayout", **TRAY, ramp_hook="0")[0]


@pytest.mark.parametrize("height", ["25", "30"])
def test_a_set_height_at_the_notch_is_raised_for_the_hook(height):
    # Height set to the notch's bottom (30) or below: the tongue still gets its lift and 2 mm.
    back = ramps("TrayLayout", **TRAY, ramp_height=height)[0]
    assert bounds(back["outline"]["outer"])[3] == pytest.approx(33)
    assert len(back["bodies"]) == 2
    # Higher set heights stay.
    assert bounds(ramps("TrayLayout", **TRAY, ramp_height="40")[0]["outline"]["outer"])[3] == pytest.approx(40)


def test_a_shared_ramp_gets_a_hook_per_notch():
    # The back row is one compartment over both columns, its front wall notched per column.
    layout = """ ,> 50mm
 | ,> 50mm
+-+-+
|   |  60mm
+-+-+
| | |  60mm
+-+-+
"""
    back = ramps("TrayLayout", layout=layout, h="50", fingerholes="inside-only", ramp_side="front")[0]
    assert len(back["bodies"]) == 4  # tongue and lip in both columns


def test_double_ramp_joins_the_compartments_on_either_side_of_a_notched_wall():
    t, g = 3.0, 0.3
    parts = ramps("TrayLayout", **TRAY, ramp_double="1")
    # One piece per column; the front row's own ramps (outer wall) give way to the partners.
    assert len(parts) == 2 and all(p["label"].startswith("double card ramp") for p in parts)
    p = parts[0]
    assert bounds(p["outline"]["outer"])[3] == pytest.approx(33)
    other, tongue = p["bodies"]
    assert other["across"] and other["t"] == pytest.approx(50)
    # The mirrored ramp beyond the wall: flat top 10, the same height.
    lo, _, hi, top = bounds(other["outline"])
    assert hi == pytest.approx(-(t + g)) and top == pytest.approx(33)
    assert sorted(q[0] for q in other["outline"] if q[1] == pytest.approx(33)) == [
        pytest.approx(-(t + g + 10)), pytest.approx(-(t + g))]
    assert lo < -(t + g + 10)
    # The tongue reaches into it (no lip).
    assert tongue["origin"][0] - tongue["t"] < -(t + g)


def test_double_ramp_off_or_unpaired_stays_single():
    assert all(p["label"].startswith("card ramp") for p in ramps("TrayLayout", **TRAY))
    # Without finger holes there is nothing to join through.
    parts = ramps("TrayLayout", **{**TRAY, "fingerholes": "none"}, ramp_double="1")
    assert len(parts) == 4 and all(p["label"].startswith("card ramp") for p in parts)


def test_ribbed_ramp_keeps_the_flat_top_and_carries_the_slope_on_ribs():
    back = ramps("TrayLayout", **TRAY, ramp_hook="0", ramp_angle="45", ramp_ribbed="1")[0]
    # A 1 mm floor plate up to where the slope is 1 mm high, the 10 mm flat top solid.
    assert back["outline"]["outer"][:6] == [pytest.approx(p) for p in (
        [0, 0], [40, 0], [39, 1], [10, 1], [10, 30], [0, 30])]
    ribs = back["bodies"]
    # Two at the sides, two between, evenly spread over the 50 mm width; each the full ramp.
    assert [b["origin"][2] for b in ribs] == [pytest.approx(z) for z in (0, 16, 32, 48)]
    assert all(b["t"] == 2 and b["spread"] for b in ribs)
    assert bounds(ribs[0]["outline"]) == pytest.approx((0, 0, 40, 30))


def test_ribbed_ramp_options():
    back = ramps("TrayLayout", **TRAY, ramp_hook="0", ramp_ribbed="1", ramp_ribs="0",
                 ramp_rib_width="3", ramp_flat="0", ramp_angle="45")[0]
    assert [(b["origin"][2], b["t"]) for b in back["bodies"]] == [(0, 3), (pytest.approx(47), 3)]
    # Without a flat top the solid part at the wall is a rib's width.
    assert [3, 1] in back["outline"]["outer"]
    # With a hook the ribs come first, then tongue and lip.
    assert len(ramps("TrayLayout", **TRAY, ramp_ribbed="1")[0]["bodies"]) == 4 + 2


def test_ribbed_double_ramp_has_ribs_on_both_sides():
    p = ramps("TrayLayout", **TRAY, ramp_ribbed="1", ramp_double="1")[0]
    spread = [b for b in p["bodies"] if b.get("spread")]
    assert len(spread) == 8
    assert sum(bounds(b["outline"])[2] < 0 for b in spread) == 4  # mirrored beyond the wall


def test_liner_gets_the_tongue_only():
    # The left compartment leans on a liner with the outer front wall right behind it.
    left, right = ramps("TrayLayout", layout=FRONT_LINER_LEFT, h="50", hi="30", fingerholes="inside-only",
                        ramp_side="front")
    (tongue,) = left["bodies"]
    assert tongue["origin"][0] - tongue["t"] == pytest.approx(-(3.0 - 0.3))
    assert "bodies" not in right


@pytest.mark.parametrize("args", [{"ramp_flat": "-1"}, {"ramp_hook": "abc"}, {"ramp_ribs": "1.5"},
                                  {"ramp_ribs": "-1"}, {"ramp_rib_width": "0"}])
def test_bad_flat_or_hook_values_leave_out_the_ramps(args):
    r = render("TypeTray", ramp="1", **args)
    assert r["warnings"][0].startswith("Ramps left out: ramp_")


# --- STL for printing ------------------------------------------------------------------

@pytest.mark.parametrize("extra", [{}, {**TRAY, "ramp_double": "1"},
                                   {**TRAY, "ramp_double": "1", "ramp_ribbed": "1"}])
def test_printed_parts_keep_their_shape_and_get_play_on_both_sides(extra):
    args = json.dumps({"ramp": "1", **extra})
    with contextlib.redirect_stdout(io.StringIO()):
        plain = json.loads(bb.print_parts("TrayLayout", args, 0.0))["parts"]
        fit = json.loads(bb.print_parts("TrayLayout", args, 0.4))["parts"]
    ramps = [(a, b) for a, b in zip(plain, fit) if a["helper"] == "printed"]
    assert ramps
    for a, b in ramps:
        assert b["outline"] == a["outline"]
        pa, pb = a["place"], b["place"]
        assert pb["t"] == pytest.approx(pa["t"] - 0.4)
        for oa, ob, n in zip(pa["origin"], pb["origin"], pa["n"]):
            assert ob == pytest.approx(oa + 0.2 * n)
        # Hooks stay where they were (their frame moved with the part); a second ramp of a
        # double ramp shrinks like the part.
        for ba, bb_ in zip(a.get("bodies", []), b.get("bodies", [])):
            if ba.get("across"):
                assert bb_["t"] == pytest.approx(ba["t"] - 0.4) and bb_["origin"] == ba["origin"]
            elif ba.get("spread"):  # ribs spread over the narrower width
                w, rw = pa["t"], ba["t"]
                assert bb_["origin"][2] == pytest.approx(ba["origin"][2] * (w - 0.4 - rw) / (w - rw))
            else:
                assert bb_["origin"][2] == pytest.approx(ba["origin"][2] - 0.2)
    # Laser parts are shrunk by half the clearance on every side.
    wall = next((a, b) for a, b in zip(plain, fit) if a["helper"] == "rectangularWall")
    xs = lambda p: [q[0] for q in p["outline"]["outer"]]
    assert max(xs(wall[1])) - min(xs(wall[1])) == pytest.approx(max(xs(wall[0])) - min(xs(wall[0])) - 0.4, abs=1e-6)


# --- Joining path fragments --------------------------------------------------------------

def test_join_paths_across_grid_cells():
    # The endpoints differ by 2e-5 mm, on both sides of a 0.01 mm grid line.
    part = SimpleNamespace(pathes=[cut([(0.0, 0.0), (10.00499, 0.0)]), cut([(10.00501, 0.0), (20.0, 0.0)])])
    bb._join_paths(part)
    assert len(part.pathes) == 1


def test_join_paths_closes_loops_that_miss_their_start_by_a_hair():
    # The loop misses its start by 5e-4 mm (float drift over many edges).
    part = SimpleNamespace(pathes=[
        cut([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0005, 0.0)]),
        cut([(30.0, 0.0), (40.0, 0.0)]),
    ])
    bb._join_paths(part)
    loop = part.pathes[0].path
    assert loop[-1][1:3] == loop[0][1:3]  # exactly closed: the SVG gets its "Z"


def test_join_paths_keeps_separate_contours_apart():
    part = SimpleNamespace(pathes=[cut([(0, 0), (5, 0)]), cut([(5.01, 0), (9, 0)])])
    bb._join_paths(part)
    assert len(part.pathes) == 2


# --- Pieces of free parts ----------------------------------------------------------------

def test_pieces_close_small_gaps():
    # A square missing its start by 0.2 mm (edge lengths that don't quite add up), and an
    # open line elsewhere so it does not take the fast path for closed rings.
    part = SimpleNamespace(pathes=[cut([(0, 0), (20, 0), (20, 20), (0, 20), (0, 0.2)]),
                                   cut([(30, 0), (40, 0)])])
    pieces = bb._pieces(part, Affine.identity())
    assert len(pieces) == 1
    assert len(pieces[0]["holes"]) == 0


def test_pieces_hole_touching_its_outline():
    # The hole's first vertex lies on the outline: still a hole, no StopIteration.
    part = SimpleNamespace(pathes=[
        cut([(0, 0), (20, 0), (20, 20), (0, 20), (0, 0)]),
        cut([(0, 5), (5, 5), (5, 10), (2, 10), (0, 5)]),
    ])
    pieces = bb._pieces(part, Affine.identity())
    assert len(pieces) == 1


# --- Recorder ------------------------------------------------------------------------------

class _IgnoreWidths(boxes.Boxes):
    """Two walls, the second with ignore_widths=[7] (edge 0 covers edge 3's width)."""
    webinterface = True
    ui_group = "Misc"

    def __init__(self):
        super().__init__()
        self.buildArgParser()

    def render(self):
        self.rectangularWall(50, 30, "eFeF", move="right", label="plain")
        self.rectangularWall(50, 30, "eFeF", ignore_widths=[7], move="right", label="ignore")


def test_ignore_widths_7_keeps_the_local_frame(monkeypatch):
    monkeypatch.setitem(bb._generators, "_IgnoreWidths", _IgnoreWidths)
    _IgnoreWidths.UI = "web"
    parts = {p["label"]: p for p in render("_IgnoreWidths")["parts"]}
    xs = lambda p: sorted(q[0] for q in p["outline"]["outer"])
    # Same inner rectangle: the right edge (fingers) ends at the same local x.
    assert xs(parts["ignore"])[-1] == pytest.approx(xs(parts["plain"])[-1], abs=1e-3)


def test_composite_edges_list_their_pieces():
    r = render("TrayLayout", sx="30:50", sy="40")
    pieces = [e["pieces"] for p in r["parts"] for e in p["edges"] if e["pieces"]]
    assert pieces
    for ps in pieces:
        for a, b in zip(ps, ps[1:]):
            assert b["start"] >= a["start"] + a["length"] - 1e-9


# --- TrayLayout editor handles ----------------------------------------------------------

# Back and left liners (0 mm row and column) with the outer back wall behind the first real
# column taken out.
_LINER_GAP = """ ,> 0mm
 | ,> 50mm
 | | ,> 40mm
+-+ +-+
| | | |  0mm
+-+-+-+
| | | |  60mm
+-+-+-+
| | | |  30mm
+-+-+-+
"""


def test_traylayout_handles_follow_the_layout_text():
    r = render("TrayLayout", layout=_LINER_GAP)
    hw = {(h["i"], h["j"]): h["on"] for h in r["handles"] if h["kind"] == "hwall"}
    # The outer wall's toggle shows the outer wall, not "outer or liner".
    assert hw[(1, 0)] is False
    assert hw[(2, 0)] is True
    # The liner's toggle on the next line.
    assert hw[(1, 1)] is True


def test_traylayout_no_dims_or_lines_for_0mm_rows_and_columns():
    r = render("TrayLayout", layout=_LINER_GAP)
    assert all(d["value"] != 0 for d in r["dims"])
    # Columns 0, 50, 40 and rows 0, 60, 30: only the line between the two real ones moves.
    assert [ln["index"] for ln in r["lines"] if ln["axis"] == "x"] == [1]
    assert [ln["index"] for ln in r["lines"] if ln["axis"] == "y"] == [1]


def test_extra_parts_are_closed_and_sized_by_span():
    from assembly import Assembly
    a = Assembly(SimpleNamespace(thickness=3.0), [])
    p = a.extra("ramp", [(5.0, 2.0), (25.0, 2.0), (5.0, 12.0)])
    outer = p.rec["outline"]["outer"]
    assert outer[0] == outer[-1]
    assert (p.rec["x"], p.rec["y"]) == (20.0, 10.0)

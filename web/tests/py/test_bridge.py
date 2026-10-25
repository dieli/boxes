import contextlib
import io
import json
import math

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


# --- STL for printing ------------------------------------------------------------------

def test_printed_parts_keep_their_shape_and_get_play_on_both_sides():
    args = json.dumps({"ramp": "1"})
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

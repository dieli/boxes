"""Glue between the Pyodide worker and the boxes package.

Mirrors what scripts/boxesserver does (same argparse source, same quirks),
but returns JSON-friendly data instead of HTML.
"""
from __future__ import annotations

import argparse
import html
import inspect
import io
from types import SimpleNamespace
import json
import math
import re
import sys

from affine import Affine
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import polygonize, unary_union

import boxes
import boxes.generators
from placements import assemble
from boxes.Color import Color
from boxes.drawing import Surface


class ArgumentParserError(Exception):
    pass


class ThrowingArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ArgumentParserError(message)


# Same trick as boxesserver: raise on bad args instead of calling sys.exit().
boxes.ArgumentParser = ThrowingArgumentParser  # type: ignore

_generators = {cls.__name__: cls
               for cls in boxes.generators.getAllBoxGenerators().values()
               if cls.webinterface}
for _cls in _generators.values():
    _cls.UI = "web"

# Arguments the browser UI controls itself.
_HIDDEN = {"input", "output", "format"}

_OPTION_RE = re.compile(r'<option value="([^"]*)"[^>]*>(.*?)</option>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def list_generators() -> str:
    groups = boxes.generators.ui_groups
    by_name = boxes.generators.ui_groups_by_name
    gens = []
    for name, cls in sorted(_generators.items()):
        group = cls.ui_group if cls.ui_group in by_name else "Misc"
        doc = (cls.__doc__ or "").strip().split("\n")[0]
        gens.append({"name": name, "group": group, "doc": doc})
    return json.dumps({
        "groups": [{"name": g.name, "title": g.title} for g in groups],
        "generators": gens,
    })


def _arg_schema(a: argparse.Action, prefix: str | None) -> dict | None:
    if isinstance(a, argparse._HelpAction) or a.dest in _HIDDEN:
        return None
    name = a.option_strings[0].replace("-", "")
    label = name[len(prefix) + 1:] if prefix and name.startswith(prefix + "_") else name
    default = a.default
    t = a.type
    arg: dict = {"name": name, "label": label, "help": a.help or ""}

    if isinstance(a, argparse._StoreAction) and isinstance(t, boxes.BoolArg):
        arg["kind"] = "bool"
        arg["default"] = t(default) if isinstance(default, str) else bool(default)
    elif isinstance(a, argparse._StoreAction) and hasattr(t, "html"):
        # Custom types (edge types, servos, robot arms) render a <select>; reuse their option list.
        options = _OPTION_RE.findall(t.html(name, default, lambda s: s))
        arg["kind"] = "select"
        arg["options"] = [[v, html.unescape(_TAG_RE.sub("", l)).strip()] for v, l in options]
        arg["default"] = "" if default is None else str(default)
    elif t is str and isinstance(default, str) and "\n" in default:
        arg["kind"] = "textarea"
        arg["default"] = default
    elif a.choices:
        arg["kind"] = "select"
        arg["options"] = [[str(c), str(c)] for c in a.choices]
        arg["default"] = "" if default is None else str(default)
    else:
        arg["kind"] = "text"
        arg["default"] = "" if default is None else str(default)
    return arg


# Card ramps: printed wedges in the compartments so cards slide up and out. They are not
# cut, so they only show in the 3D view and the STL exports (see placements._card_ramps).
_RAMP_GENERATORS = {"TypeTray", "TrayLayout"}
_RAMP_DEFAULTS = {"ramp": "0", "ramp_side": "front", "ramp_height": "auto", "ramp_angle": "45"}
_RAMP_GROUP = {"title": "Card ramps (3D print)", "collapsed": True, "args": [
    {"name": "ramp", "label": "ramp", "kind": "bool", "default": False,
     "help": "add a 3D printed ramp to every compartment so cards slide up and out "
             "(3D view and STL export only, not in the 2D sheet)"},
    {"name": "ramp_side", "label": "side", "kind": "select", "default": "front",
     "options": [[s, s] for s in ("front", "back", "left", "right")],
     "help": "wall the ramps lean against"},
    {"name": "ramp_height", "label": "height", "kind": "text", "default": "auto",
     "help": "height at the wall in mm (at most the wall height); auto: up to the bottom of the "
             "finger hole in that wall, 15 mm for walls without finger holes"},
    {"name": "ramp_angle", "label": "angle", "kind": "text", "default": "45",
     "help": "slope in degrees from the floor (the ramp gets shorter if the compartment is too short)"},
]}


def _ramp_settings(args: dict) -> dict | None:
    """Takes the ramp arguments out of args; the settings if ramps are on."""
    r = {k: str(args.pop(k, v)) for k, v in _RAMP_DEFAULTS.items()}
    if not boxes.boolarg(r["ramp"]):
        return None
    if r["ramp_side"] not in ("front", "back", "left", "right"):
        raise ValueError(f"ramp_side: unknown side {r['ramp_side']!r}")
    out: dict = {"side": r["ramp_side"]}
    for k in ("height", "angle"):
        if k == "height" and r["ramp_height"].strip().lower() == "auto":
            out[k] = None  # placements._card_ramps: the finger hole's bottom
            continue
        try:
            out[k] = float(r["ramp_" + k])
        except ValueError:
            raise ValueError(f"ramp_{k}: {r['ramp_' + k]!r} is not a number") from None
    return out


def get_schema(name: str) -> str:
    box = _generators[name]()
    groups = []
    # The first three groups are positionals, "<Generator> Settings" and "Default Settings".
    # Everything after (edge settings, extras) starts collapsed, like the server UI does.
    for i, group in enumerate(box.argparser._action_groups):
        prefix = getattr(group, "prefix", None)
        args = [s for s in (_arg_schema(a, prefix) for a in group._group_actions) if s]
        if args:
            groups.append({"title": group.title, "collapsed": i >= 3, "args": args})
    if name in _RAMP_GENERATORS:
        groups.append(_RAMP_GROUP)
    return json.dumps({
        "name": name,
        "doc": (box.__doc__ or "").strip(),
        "groups": groups,
    })


def _render_box(name: str, args_json: str, fmt: str = "svg", join: bool = False, split: bool = False):
    box = _generators[name]()
    args = json.loads(args_json)
    box._web_ramp = _ramp_settings(args) if name in _RAMP_GENERATORS else None
    box.parseArgs([f"--{k}={v}" for k, v in args.items()] + [f"--format={fmt}"])
    if name == "TrayLayout" and not box.layout.strip():
        # Like the server UI's JavaScript: without a layout, start from the sx x sy grid
        # (there is no layout file to fall back to in the browser).
        layout_file = boxes.generators.traylayout.TrayLayoutFile()
        layout_file.fillDefault(box.sx, box.sy)
        box.layout = str(layout_file)
    # Parameter values as given: generators with "outside" overwrite e.g. self.x with the inner size.
    box._web_args = {k: (list(v) if isinstance(v, list) else v) for k, v in vars(box).items()
                     if isinstance(v, (int, float, list)) and not isinstance(v, bool)}
    box.open()
    surface = box.surface
    reference = {id(p) for p in surface.parts if p.pathes or p.path}  # drawn by open()
    box.render()
    if join or split:
        finish = surface.finish

        def joined_finish(*a, **kw):
            for part in surface.parts:
                _join_paths(part)
            if not split:
                return finish(*a, **kw)
            # One file per part: finish() moves each part to the origin on its own sheet.
            parts, box._web_files = surface.parts, []
            for i, part in enumerate(parts):
                if part.pathes:
                    surface.parts = [part]
                    box._web_files.append({"part": i, "reference": id(part) in reference,
                                           "content": finish(*a, **kw).getvalue().decode("utf-8")})
            surface.parts = parts
            return io.BytesIO(b"")

        surface.finish = joined_finish
    return box, box.close().getvalue().decode("utf-8")


def render(name: str, args_json: str, fmt: str = "svg") -> str:
    """The file to download: like the preview, but with each contour as one continuous path."""
    return _render_box(name, args_json, fmt, join=True)[1]


def render_parts(name: str, args_json: str, fmt: str = "svg") -> str:
    """One file per part (index of its <g id="p-N"> in the full SVG), for cutter software that
    does not keep a file's groups: each import is then one part with its holes and label."""
    return json.dumps(_render_box(name, args_json, fmt, split=True)[0]._web_files)


# --- Joining path fragments -------------------------------------------------
#
# Boxes appends a path to an earlier one only if it starts where that one ends. Parts drawn
# piece by piece (e.g. TrayLayout's base plate, edge by edge per cell) end up as many short
# open subpaths, which some cutter software (e.g. Falcon Design Space) imports badly, and
# which make the laser jump around. This chains them into continuous contours, reversing
# pieces where needed. Only the order and direction of the cuts change, not their geometry.
# Not used for the preview: the part recorder counts the paths as drawn.

def _pt_key(x: float, y: float) -> tuple[float, float]:
    return (round(x, 2), round(y, 2))


def _reverse_subpath(sub: list) -> list:
    out = [["M", *sub[-1][1:3]]]
    for i in range(len(sub) - 1, 0, -1):
        c, start = sub[i], sub[i - 1][1:3]
        if c[0] == "C":
            out.append(["C", *start, c[5], c[6], c[3], c[4]])
        else:
            out.append([c[0], *start])
    return out


def _join_paths(part) -> None:
    from boxes.drawing import Path, points_equal
    items: list[tuple[int, object]] = []  # (original order, Path kept as is | (group, subpath))
    groups: list[dict] = []
    for path in part.pathes:
        cmds = [list(c) for c in path.path]
        drawn = [c[0] for c in cmds if c[0] != "T"]
        if (drawn and drawn[0] != "M") or any(c not in "MLC" for c in drawn):
            items.append((len(items), path))  # anything unexpected: untouched
            continue
        g = next((i for i, params in enumerate(groups) if params == path.params), None)
        if g is None:
            groups.append(path.params)
            g = len(groups) - 1
        cur: list = []
        for c in cmds:
            if c[0] == "T":  # text sits in the same path but draws nothing: keep it on its own
                items.append((len(items), Path([c], dict(path.params))))
            elif c[0] == "M":
                cur = [c]
                items.append((len(items), (g, cur)))
            else:
                cur.append(c)
    subs = [(n, it) for n, it in items if isinstance(it, tuple) and len(it[1]) > 1]
    if len(subs) < 2:
        return
    closed = lambda sp: points_equal(*sp[0][1:3], *sp[-1][1:3])
    at: dict[tuple, set[int]] = {}
    for k, (_, (g, sp)) in enumerate(subs):
        if not closed(sp):
            for xy in (sp[0][1:3], sp[-1][1:3]):
                at.setdefault((g, *_pt_key(*xy)), set()).add(k)
    used = [False] * len(subs)

    def take(g, xy, want_start: bool):
        """An unused open subpath touching xy, oriented to start (or end) there."""
        for k in sorted(at.get((g, *_pt_key(*xy)), ())):
            if used[k]:
                continue
            sp = subs[k][1][1]
            used[k] = True
            starts_here = _pt_key(*sp[0][1:3]) == _pt_key(*xy)
            return sp if starts_here == want_start else _reverse_subpath(sp)
        return None

    chains: list[tuple[int, Path]] = []
    for k, (n, (g, sp)) in enumerate(subs):
        if used[k]:
            continue
        used[k] = True
        chain = list(sp)
        while not closed(chain) and (nxt := take(g, chain[-1][1:3], True)):
            chain += nxt[1:]
        while not closed(chain) and (prv := take(g, chain[0][1:3], False)):
            chain = prv + chain[1:]
        if closed(chain):  # end exactly on the start so the SVG gets its "Z"
            chain[-1][1:3] = chain[0][1:3]
        chains.append((n, Path(chain, dict(groups[g]))))
    kept = [(n, it) for n, it in items if not isinstance(it, tuple)]
    part.pathes = [p for _, p in sorted(kept + chains, key=lambda e: e[0])]


# --- Part recorder ----------------------------------------------------------
#
# Records every wall drawn through the wall helpers, with the frame its inner
# rectangle lives in, by wrapping Boxes methods at runtime. boxes itself is unchanged.
#
# Local wall frame: +x along the bottom edge, +y towards the top edge, and the wall's
# inner rectangle is (0,0)-(x,y). Each edge's cut line lies edge.startWidth() outside
# that rectangle (e.g. 'h' = holes + bottom panel below the inner space).
# "matrix" maps that frame to SVG user units: (a, b, c, d, e, f) with
# X = a*x + b*y + c, Y = d*x + e*y + f.

class _Recorder:
    def __init__(self) -> None:
        self.walls: list[dict] = []
        self.pending: dict | None = None
        self.surface = None
        self.sheet = None
        self.ignored: set[int] = set()  # SVG parts that are not parts (reference bar)


_recorder: _Recorder | None = None


def _edge_info(box, e) -> dict:
    e = box.edges.get(e, e)
    return {
        "char": getattr(e, "char", None),
        "type": type(e).__name__,
        "startWidth": e.startWidth(),
        "endWidth": e.endWidth(),
        "margin": e.margin(),
        "spacing": e.spacing(),
        # Finger joints between parts at another angle (settings.angle, 90 is square).
        "angle": getattr(getattr(e, "settings", None), "angle", None),
    }


def _callers(frame, limit: int = 12) -> list[str]:
    """Qualified names of the functions between the generator's render() and a wall helper."""
    names = []
    while frame is not None and len(names) < limit and frame.f_code.co_name != "render":
        names.append(frame.f_code.co_qualname)
        frame = frame.f_back
    return names


def _wrap_wall_helper(helper: str, describe):
    """Records each call of a wall helper. describe(box, args) gives the part's size, edges
    and where its local frame lies relative to where the helper calls cc(callback, 0)."""
    orig = getattr(boxes.Boxes, helper)
    sig = inspect.signature(orig)

    def wrapper(self, *args, **kwargs):
        rec = _recorder
        if rec is None:
            return orig(self, *args, **kwargs)
        bound = sig.bind(self, *args, **kwargs)
        bound.apply_defaults()
        a = bound.arguments
        try:
            d = describe(self, a)
        except Exception:  # unusual arguments: draw it, just don't record it
            d = None
        if d is None:
            return orig(self, *args, **kwargs)
        entry = {
            "helper": helper,
            "x": d["x"],
            "y": d["y"],
            "edges": [_edge_info(self, e) for e in d["edges"]],
            "label": a.get("label") or "",
            "move": a.get("move") or "",
            "callers": _callers(sys._getframe(1)),
            "params": d.get("params", {}),
            "_offset": d["offset"],
            "_probe": d.get("probe", (d["x"] / 2, d["y"] / 2)),
            # Smallest outline (share of the bounding box) taken without the probe inside it.
            "_min_area": d.get("min_area", 0.2),
            "_multi": d.get("multi", False),
            # Number of SVG parts and of paths in the last one when the helper returns, shared
            # by all copies of a multi part: a nested move() (e.g. stackable feet drawing their
            # stabilizer) splits the cuts. Later free drawing may go into that last part too.
            "_end": (end := [0, 0]),
        }
        for i, char in d.get("chars", {}).items():
            entry["edges"][i]["char"] = char
        outer, rec.pending = rec.pending, entry
        try:
            return orig(self, *args, **kwargs)
        finally:
            rec.pending = outer
            parts = self.ctx._dwg.parts
            end[:] = [len(parts), len(parts[-1].pathes) if parts else 0]

    setattr(boxes.Boxes, helper, wrapper)


def _edge_objs(box, edges, n: int) -> list:
    """Edge objects for a helper's edges argument (string, list or single edge), n of them."""
    if isinstance(edges, str) and len(edges) == 1 or not hasattr(edges, "__getitem__"):
        edges = [edges]
    edges = [box.edges.get(e, e) for e in edges]
    return [edges[i % len(edges)] for i in range(n)]


def _rect_like(box, a, x, y, n=4, **extra):
    """Helpers that start with edge 0 at the origin, like rectangularWall: the cut line of
    edge 0 lies startWidth below the inner rectangle."""
    edges = _edge_objs(box, a["edges"], n)
    return {"x": x, "y": y, "edges": edges, "offset": (0.0, edges[0].startWidth()), **extra}


def _describe_rectangular_wall(box, a):
    return _rect_like(box, a, a["x"], a["y"])


def _describe_trapezoid(box, a):
    # Inner shape: (0,0)-(w,0)-(w,h1)-(0,h0); edge 2 is the slanted top.
    return _rect_like(box, a, a["w"], max(a["h0"], a["h1"]),
                      params={"h0": a["h0"], "h1": a["h1"]})


def _describe_triangle(box, a):
    # With num > 1 all triangles share one SVG part; each calls cc(callback, 0) in its own
    # frame and is recorded as a part of its own.
    x, y = a["x"], a["y"]
    edges = [box.edges.get(e, e) for e in a["edges"]]
    if len(edges) == 2:
        edges.append(box.edges["e"])
    # Inner shape: (0,0)-(x,0)-(x,y); edge 2 is the hypotenuse.
    return {"x": x, "y": y, "edges": edges, "offset": (0.0, edges[0].startWidth()),
            "probe": (2 * x / 3, y / 3), "params": {"r": a["r"]}, "multi": a["num"] > 1}


def _describe_flanged(box, a):
    x, y = a["x"], a["y"]
    flanges = list(a["flanges"] or []) + [0.0] * 4
    flanges = flanges[:4]
    edges = _edge_objs(box, a["edges"], 4)
    rl = min(a["r"], max(flanges[3], flanges[0]))
    # Flanged sides with F/h edges become finger holes in the flange.
    chars = {i: "h" for i in range(4)
             if flanges[i] and (edges[i] is box.edges["F"] or edges[i] is box.edges["h"])}
    return {"x": x, "y": y, "edges": edges, "chars": chars, "params": {"flanges": flanges},
            "offset": (flanges[3] + edges[3].endWidth() - rl, flanges[0] + edges[0].startWidth())}


def _describe_rounded_plate(box, a):
    edge = box.edges.get(a["edge"], a["edge"])
    # cc(0) is at the start of the straight part of the bottom edge, r in from the corner.
    return {"x": a["x"], "y": a["y"], "edges": [edge] * 4,
            "offset": (-a["r"], edge.startWidth()), "params": {"r": a["r"]}}


def _poly_bbox(points):
    xs = [q[0] for q in points]
    ys = [q[1] for q in points]
    return min(xs), min(ys), max(xs), max(ys)


def _describe_regular_polygon(box, a):
    n = a["corners"]
    _, h, side = box.regularPolygon(n, a["r"], a["h"], a["side"])
    edges = _edge_objs(box, a["edges"], n)
    # Inner polygon: side 0 from (0,0) to (side,0), counter-clockwise.
    pts, px, py, ang = [], 0.0, 0.0, 0.0
    for _ in range(n):
        pts.append((px, py))
        px += side * math.cos(math.radians(ang))
        py += side * math.sin(math.radians(ang))
        ang += 360.0 / n
    minx, miny, maxx, maxy = _poly_bbox(pts)
    return {"x": maxx - minx, "y": maxy - miny, "edges": edges,
            "offset": (minx, edges[0].startWidth() + miny),
            "params": {"corners": n, "side": side, "h": h, "start": [-minx, -miny]}}


def _describe_polygon_wall(box, a):
    borders = box._closePolygon(list(a["borders"]))
    edges = _edge_objs(box, a["edge"], len(borders) // 2)
    # Bounding box of the polygon line itself (no edge margins).
    minx, miny, maxx, maxy = box._polygonWallExtend(borders, [box.edges["e"]])
    return {"x": maxx - minx, "y": maxy - miny, "edges": edges, "offset": (minx, miny),
            # Always draws its own outline, which may be a thin L (e.g. SkadisStand's side).
            "probe": None, "min_area": 0.0,
            "params": {"borders": [list(b) if isinstance(b, (tuple, list)) else b for b in borders],
                       "start": [-minx, -miny]}}


_orig_cc = boxes.Boxes.cc


def _cc(self, callback, number, *args, **kwargs):
    rec = _recorder
    # The wall helpers call cc(callback, 0, ...) at the start of the bottom edge's cut line,
    # callback or not. render_with_parts() shifts this to the local frame ("_offset").
    if rec is not None and rec.pending is not None and number == 0 and (
            "matrix" not in rec.pending or rec.pending["_multi"]):
        entry = rec.pending if "matrix" not in rec.pending else {
            **rec.pending, "edges": [dict(e) for e in rec.pending["edges"]]}
        entry["matrix"] = tuple(self.ctx._m)[:6]
        entry["_part"] = self.ctx._dwg._p
        rec.surface = self.ctx._dwg
        rec.walls.append(entry)
    return _orig_cc(self, callback, number, *args, **kwargs)


_orig_move = boxes.Boxes.move


def _move(self, x, y, where, before=False, label=""):
    """Records parts drawn by hand (between move(..., before=True) and move(...)) without a
    recorded wall helper, e.g. the side profiles of the wall mounted generators. Their local
    frame is the move box [0, x] x [0, y]; they have no edge info, placements go by outline."""
    rec = _recorder
    skip = _orig_move(self, x, y, where, before, label)
    if rec is None or not before or skip or rec.pending is not None:
        return skip
    callers = _callers(sys._getframe(1))
    if any(c.endswith("Boxes.open") for c in callers):  # reference bar
        rec.ignored.add(id(self.ctx._dwg._p))
        return skip
    rec.surface = self.ctx._dwg
    rec.walls.append({
        "helper": "free", "x": float(x), "y": float(y), "edges": [], "label": label or "",
        "move": where or "", "callers": callers, "params": {},
        "matrix": tuple(self.ctx._m)[:6], "_part": self.ctx._dwg._p,
        "_offset": (0.0, 0.0), "_probe": None, "_multi": False, "_free": True,
    })
    return skip


_orig_surface_transform = Surface.transform


def _surface_transform(self, f, m, invert_y=False):
    # Called once from _adjust_coordinates() with the final sheet transform (incl. SVG y flip).
    if _recorder is not None and self is _recorder.surface:
        _recorder.sheet = m
    return _orig_surface_transform(self, f, m, invert_y)


_wrap_wall_helper("rectangularWall", _describe_rectangular_wall)
_wrap_wall_helper("trapezoidWall", _describe_trapezoid)
_wrap_wall_helper("trapezoidSideWall", _describe_trapezoid)
_wrap_wall_helper("rectangularTriangle", _describe_triangle)
_wrap_wall_helper("flangedWall", _describe_flanged)
_wrap_wall_helper("roundedPlate", _describe_rounded_plate)
_wrap_wall_helper("regularPolygonWall", _describe_regular_polygon)
_wrap_wall_helper("polygonWall", _describe_polygon_wall)
boxes.Boxes.cc = _cc
boxes.Boxes.move = _move
Surface.transform = _surface_transform


# --- Part outlines for extrusion ------------------------------------------------

_CUT_COLORS = (Color.OUTER_CUT, Color.INNER_CUT)
_CURVE_STEPS = 8
# inner_corners="loop" (the default) adds tiny loops at inner corners; they are not holes.
_MIN_HOLE_AREA = 0.5  # mm²


# Outlines whose ends are this close count as closed (mm); render_with_parts adds the burn:
# burn compensation can shift a path's start (by up to burn * sqrt(2)) but not its end.
_DEFAULT_CLOSE_TOL = 0.05


def _polylines(part, to_local: Affine, close_tol: float = _DEFAULT_CLOSE_TOL) -> list[list[tuple[float, float]]]:
    """Cut paths of a part as polylines in the wall's local frame (curves flattened)."""
    lines = []
    for path in part.pathes:
        if path.params.get("rgb") not in _CUT_COLORS:
            continue
        cur: list[tuple[float, float]] = []
        for c in path.path:
            op = c[0]
            if op == "M":
                if len(cur) > 1:
                    lines.append(cur)
                cur = [(c[1], c[2])]
            elif op == "L":
                cur.append((c[1], c[2]))
            elif op == "C" and cur:
                # Stored destination first: ["C", x3, y3, x1, y1, x2, y2]
                (x0, y0), (x3, y3), (x1, y1), (x2, y2) = cur[-1], c[1:3], c[3:5], c[5:7]
                if abs(x3 - x0) < 1e-9 and abs(y3 - y0) < 1e-9:
                    continue  # inner_corners="loop" artefact: a curve back to its own start

                for i in range(1, _CURVE_STEPS + 1):
                    t = i / _CURVE_STEPS
                    u = 1 - t
                    cur.append((u**3 * x0 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t**3 * x3,
                                u**3 * y0 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t**3 * y3))
        if len(cur) > 1:
            lines.append(cur)
    # Plain arithmetic: Affine.__mul__ per point dominates the runtime otherwise.
    a, b, c, d, e, f = tuple(to_local)[:6]
    out = [[(round(a * x + b * y + c, 3), round(d * x + e * y + f, 3)) for x, y in line] for line in lines]
    for line in out:
        if len(line) > 3 and line[0] != line[-1] and math.dist(line[0], line[-1]) < close_tol:
            line[-1] = line[0]
    return out


def _area(ring) -> float:
    return 0.5 * sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]))


def _inside(x: float, y: float, ring) -> bool:
    inside = False
    for (x0, y0), (x1, y1) in zip(ring, ring[-1:] + ring[:-1]):
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            inside = not inside
    return inside


def _in_bbox(x: float, y: float, bbox: tuple[float, float, float, float]) -> bool:
    return bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3]


def _outline(part, to_local: Affine, probe=None, min_area: float = 0.0,
             close_tol: float = _DEFAULT_CLOSE_TOL) -> dict | None:
    """Outer contour and holes of a part, or None if its cuts don't form a closed shape.

    The outer contour is the largest ring around probe (a local point inside the part, to
    pick the right piece when one SVG part holds several), else the largest ring if its
    area is at least min_area (e.g. a U-shaped wall whose middle is cut away).
    """
    lines = _polylines(part, to_local, close_tol)
    # Fast path: every cut is a closed ring; rings inside the outline are holes.
    if lines and all(l[0] == l[-1] and len(l) > 3 for l in lines):
        rings = sorted((l[:-1] for l in lines), key=lambda r: abs(_area(r)), reverse=True)
        around = [r for r in rings if _inside(*probe, r)] if probe else []
        outer = (around or rings)[0]
        if not around and abs(_area(outer)) < min_area:
            return None  # only holes: the part's outline was drawn elsewhere
        outer_bbox = _poly_bbox(outer)
        holes = [r for r in rings
                 if r is not outer and abs(_area(r)) >= _MIN_HOLE_AREA
                 and _in_bbox(*r[0], outer_bbox) and _inside(*r[0], outer)]
        return {
            "outer": [list(p) for p in outer],
            "holes": [[list(p) for p in r] for r in _merge_overlapping(holes)],
        }
    return _outline_shapely(lines, probe, min_area)


def _merge_overlapping(holes: list) -> list:
    """Holes that overlap (e.g. KeyHolder's mounting keyhole and a hook's finger hole) as one
    hole each: overlapping holes make an invalid polygon, whose overlap counts as material in
    Three.js and the STL. Only holes whose bounding bbox overlap are joined (sweep over x)."""
    order = sorted(range(len(holes)), key=lambda i: _poly_bbox(holes[i])[0])
    bbox = {i: _poly_bbox(holes[i]) for i in order}
    groups: list[list[int]] = []
    active: list[tuple[float, list[int]]] = []  # (max x of the group, group)
    for i in order:
        x0, y0, x1, y1 = bbox[i]
        active = [(ax, g) for ax, g in active if ax > x0]
        hit = [g for _, g in active if any(bbox[j][1] < y1 and y0 < bbox[j][3]
                                           and bbox[j][0] < x1 for j in g)]
        if not hit:
            groups.append([i])
            active.append((x1, groups[-1]))
            continue
        # Join every group this hole touches into the first one.
        first = hit[0]
        for g in hit[1:]:
            first.extend(g)
            g.clear()
        first.append(i)
        active = [(max(ax, x1) if g is first else ax, g) for ax, g in active if g]
    out = []
    for g in groups:
        if len(g) <= 1:
            out.extend(holes[j] for j in g)
            continue
        union = unary_union([Polygon(holes[j]).buffer(0) for j in g])
        for poly in getattr(union, "geoms", [union]):
            out.append(list(poly.exterior.coords[:-1]))
    return out


_CLOSE_GAP = 0.5  # mm


def _outline_shapely(lines, probe=None, min_area: float = 0.0) -> dict | None:
    """Fallback for cuts split over several open paths: node and polygonize them."""
    # Paths that miss their start by a hair (edges whose lengths don't quite add up, e.g.
    # DinRailBox's rail edge, 0.1 mm short) are closed.
    lines = [l + [l[0]] if 0 < math.dist(l[0], l[-1]) < _CLOSE_GAP else l for l in lines]
    faces = list(polygonize(unary_union([LineString(l) for l in lines]))) if lines else []
    if not faces:
        return None
    # The polygonizer gives the material face with the inner cuts as interior rings.
    around = [f for f in faces if Polygon(f.exterior).contains(Point(probe))] if probe else []
    # By the area inside the outline: a large cut-out is a face too.
    shape = max(around or faces, key=lambda f: Polygon(f.exterior).area)
    if not around and Polygon(shape.exterior).area < min_area:
        return None
    return {
        "outer": [list(p) for p in shape.exterior.coords[:-1]],
        "holes": [[list(p) for p in ring.coords[:-1]]
                  for ring in shape.interiors if Polygon(ring).area >= _MIN_HOLE_AREA],
    }


def _pieces(part, to_local: Affine, close_tol: float = _DEFAULT_CLOSE_TOL) -> list[dict]:
    """All separate pieces cut in a part (outer contour and holes each), e.g. a set of hinge
    eyes drawn as one part. Rings nested an even number of times are outlines."""
    lines = _polylines(part, to_local, close_tol)
    if lines and all(l[0] == l[-1] and len(l) > 3 for l in lines):
        rings = [l[:-1] for l in lines]
    else:
        faces = list(polygonize(unary_union([LineString(l) for l in lines]))) if lines else []
        rings = [list(f.exterior.coords[:-1]) for f in faces]
    rings = [r for r in rings if abs(_area(r)) >= _MIN_HOLE_AREA]
    rings.sort(key=lambda r: abs(_area(r)), reverse=True)
    bboxes = [_poly_bbox(r) for r in rings]
    pieces = []
    for i, r in enumerate(rings):
        x0, y0 = r[0]
        parents = [q for j, q in enumerate(rings[:i]) if _in_bbox(x0, y0, bboxes[j]) and _inside(x0, y0, q)]
        if len(parents) % 2 == 0:
            pieces.append({"outer": [list(p) for p in r], "holes": [], "_bbox": bboxes[i]})
        else:  # a hole of the innermost enclosing piece
            host = next(pc for pc in reversed(pieces)
                        if _in_bbox(x0, y0, pc["_bbox"]) and _inside(x0, y0, pc["outer"]))
            host["holes"].append([list(p) for p in r])
    for pc in pieces:
        del pc["_bbox"]
    return pieces


def _unrecorded(rec: _Recorder, wall_parts: set[int], consumed: dict[int, int],
                close_tol: float = _DEFAULT_CLOSE_TOL) -> list[dict]:
    """Pieces in SVG parts drawn without move() or a wall helper (e.g. MagazineFile's sides).
    Each one's local frame is its bounding box on the sheet, unrotated."""
    if rec.surface is None or rec.sheet is None:
        return []
    out = []
    for i, part in enumerate(rec.surface.parts):
        if id(part) in wall_parts or id(part) in rec.ignored:
            continue
        if id(part) in consumed:  # partly merged into a wall: only what was drawn later
            part = SimpleNamespace(pathes=part.pathes[consumed[id(part)]:])
        for piece in _pieces(part, ~rec.sheet, close_tol):
            minx, miny, maxx, maxy = _poly_bbox(piece["outer"])
            shift = lambda ring: [[px - minx, py - miny] for px, py in ring]
            out.append({
                "helper": "free", "x": maxx - minx, "y": maxy - miny, "edges": [], "label": "",
                "move": "", "callers": [], "params": {},
                "matrix": tuple(rec.sheet * Affine.translation(minx, miny))[:6],
                "part": i, "mirrored": False,
                "outline": {**piece, "outer": shift(piece["outer"]),
                            "holes": [shift(h) for h in piece["holes"]]},
            })
    return out


def render_with_parts(name: str, args_json: str) -> str:
    """Like render(), plus the recorded walls and their 3D placement.

    Returns {"svg", "parts", "assembly", "dims", "handles", "lines", "thickness"}: "assembly" is false when the generator has no
    placement function (2D only), or the error message if placing failed.
    """
    global _recorder
    _recorder = rec = _Recorder()
    try:
        box, svg = _render_box(name, args_json)
    finally:
        _recorder = None
    close_tol = _DEFAULT_CLOSE_TOL + 2 * abs(box.burn)
    parts = []
    helper_parts = {id(w["_part"]) for w in rec.walls if not w.get("_free")}
    wall_parts = {id(w["_part"]) for w in rec.walls}
    consumed: dict[int, int] = {}  # id(SVG part) -> leading paths merged into a wall
    for w in rec.walls:
        part = w.pop("_part")
        end, end_paths = w.pop("_end", [0, 0])
        drawn = Affine(*w["matrix"])
        local = drawn * Affine.translation(*w.pop("_offset"))
        sheet = rec.sheet * local if rec.sheet is not None else local
        w["matrix"] = tuple(sheet)[:6]
        w["part"] = rec.surface.parts.index(part)
        # move="mirror"/"upsidedown" draw the part reflected. The cut piece is flipped over to
        # mount it; placements treat that as a reflection in local x, which keeps every edge
        # in its role (a y reflection is the same plus a 180 degree turn).
        w["mirrored"] = drawn.determinant < 0
        w.pop("_multi")
        if w.pop("_free", False):
            w.pop("_probe")
            w.pop("_min_area", None)
            if id(part) in helper_parts:
                continue  # a wall helper drew into the same SVG part
            for outline in _pieces(part, ~sheet, close_tol):  # each closed piece is a part of its own
                parts.append({**w, "outline": outline})
            continue
        # Cuts that went into later SVG parts (after a nested helper's move()) belong here too.
        later = [q for q in rec.surface.parts[w["part"] + 1:end] if id(q) not in wall_parts]
        if later:
            paths = list(part.pathes)
            for q in later:
                # Of the part current when the helper returned, only the paths drawn so far.
                n = end_paths if q is rec.surface.parts[end - 1] else len(q.pathes)
                paths += q.pathes[:n]
                consumed[id(q)] = max(consumed.get(id(q), 0), n)
            part = SimpleNamespace(pathes=paths)
        w["outline"] = _outline(part, ~sheet, w.pop("_probe"), w.pop("_min_area", 0.2) * w["x"] * w["y"], close_tol)
        parts.append(w)
    parts += _unrecorded(rec, wall_parts, consumed, close_tol)
    try:
        asm = assemble(name, box, parts)
        placements, dims, handles, lines = (asm.placements, asm.dims, asm.handles, asm.lines) if asm else (None, [], [], [])
        parts += [e.rec for e in asm.extras] if asm else []  # placed, so indices follow the walls
        assembly = placements is not None
    except Exception as e:  # a broken placement must not break the 2D preview
        placements, dims, handles, lines, assembly = None, [], [], [], f"{type(e).__name__}: {e}"
    for i, w in enumerate(parts):
        w["place"] = placements.get(i) if placements else None
        # Size of the cut piece: x/y are the inner frame, without edges like "E" or fingers
        # sticking out; the outline is burn compensated (not printed parts, drawn without it).
        o = w["outline"]
        kerf = 0.0 if w["helper"] == "printed" else 2 * abs(box.burn)
        w["size"] = [max(q[k] for q in o["outer"]) - min(q[k] for q in o["outer"]) - kerf
                     for k in (0, 1)] if o else None
    parts = [w for w in parts if not (w["place"] or {}).get("scrap")]
    return json.dumps({"svg": svg, "parts": parts, "assembly": assembly, "dims": dims,
                       "handles": handles,
                       "lines": lines,
                       "thickness": box.thickness})


def _inset(outline: dict, d: float) -> dict | None:
    """The outline shrunk by d on every side (holes grow), sharp corners kept."""
    shape = Polygon(outline["outer"], outline["holes"]).buffer(0).buffer(-d, join_style=2)
    if shape.is_empty:
        return None
    if shape.geom_type != "Polygon":  # thin bridges vanished: keep the main piece
        shape = max(shape.geoms, key=lambda g: g.area)
    return {
        "outer": [list(p) for p in shape.exterior.coords[:-1]],
        "holes": [[list(p) for p in ring.coords[:-1]] for ring in shape.interiors],
    }


def print_parts(name: str, args_json: str, clearance: float = 0.0) -> str:
    """Parts for 3D printing: outlines without the laser's burn compensation, shrunk by
    clearance / 2 on every side so each joint gets `clearance` of play in total.

    (A negative burn does not work for this: Boxes' burn correction assumes it is positive.)
    Returns {"parts", "thickness"} like render_with_parts().
    """
    args = {**json.loads(args_json), "burn": "0"}
    result = json.loads(render_with_parts(name, json.dumps(args)))
    if clearance > 0:
        for p in result["parts"]:
            if p["outline"]:
                p["outline"] = _inset(p["outline"], clearance / 2)
            if p["helper"] == "printed" and (p["place"] or {}).get("t"):  # e.g. ramps: fit between the walls
                p["place"]["t"] = max(p["place"]["t"] - clearance, 0.1)
    return json.dumps({"parts": result["parts"], "thickness": result["thickness"]})

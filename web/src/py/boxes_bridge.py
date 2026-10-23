"""Glue between the Pyodide worker and the boxes package.

Mirrors what scripts/boxesserver does (same argparse source, same quirks),
but returns JSON-friendly data instead of HTML.
"""
from __future__ import annotations

import argparse
import html
import inspect
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
    return json.dumps({
        "name": name,
        "doc": (box.__doc__ or "").strip(),
        "groups": groups,
    })


def _render_box(name: str, args_json: str):
    box = _generators[name]()
    args = json.loads(args_json)
    box.parseArgs([f"--{k}={v}" for k, v in args.items()] + ["--format=svg"])
    box.open()
    box.render()
    return box, box.close().getvalue().decode("utf-8")


def render(name: str, args_json: str) -> str:
    return _render_box(name, args_json)[1]


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
        }
        for i, char in d.get("chars", {}).items():
            entry["edges"][i]["char"] = char
        outer, rec.pending = rec.pending, entry
        try:
            return orig(self, *args, **kwargs)
        finally:
            rec.pending = outer

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
    if a["num"] != 1:
        return None  # several triangles in one part
    x, y = a["x"], a["y"]
    edges = [box.edges.get(e, e) for e in a["edges"]]
    if len(edges) == 2:
        edges.append(box.edges["e"])
    # Inner shape: (0,0)-(x,0)-(x,y); edge 2 is the hypotenuse.
    return {"x": x, "y": y, "edges": edges, "offset": (0.0, edges[0].startWidth()),
            "probe": (2 * x / 3, y / 3), "params": {"r": a["r"]}}


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
            "probe": None,
            "params": {"borders": [list(b) if isinstance(b, (tuple, list)) else b for b in borders],
                       "start": [-minx, -miny]}}


_orig_cc = boxes.Boxes.cc


def _cc(self, callback, number, *args, **kwargs):
    rec = _recorder
    # The wall helpers call cc(callback, 0, ...) at the start of the bottom edge's cut line,
    # callback or not. render_with_parts() shifts this to the local frame ("_offset").
    if rec is not None and rec.pending is not None and number == 0 and "matrix" not in rec.pending:
        rec.pending["matrix"] = tuple(self.ctx._m)[:6]
        rec.pending["_part"] = self.ctx._dwg._p
        rec.surface = self.ctx._dwg
        rec.walls.append(rec.pending)
    return _orig_cc(self, callback, number, *args, **kwargs)


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
Surface.transform = _surface_transform


# --- Part outlines for extrusion ------------------------------------------------

_CUT_COLORS = (Color.OUTER_CUT, Color.INNER_CUT)
_CURVE_STEPS = 8
# inner_corners="loop" (the default) adds tiny loops at inner corners; they are not holes.
_MIN_HOLE_AREA = 0.5  # mm²


def _polylines(part, to_local: Affine) -> list[list[tuple[float, float]]]:
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
    return [[(round(a * x + b * y + c, 3), round(d * x + e * y + f, 3)) for x, y in line] for line in lines]


def _area(ring) -> float:
    return 0.5 * sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]))


def _inside(x: float, y: float, ring) -> bool:
    inside = False
    for (x0, y0), (x1, y1) in zip(ring, ring[-1:] + ring[:-1]):
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            inside = not inside
    return inside


def _outline(part, to_local: Affine, probe=None, min_area: float = 0.0) -> dict | None:
    """Outer contour and holes of a part, or None if its cuts don't form a closed shape.

    The outer contour is the largest ring around probe (a local point inside the part, to
    pick the right piece when one SVG part holds several), else the largest ring if its
    area is at least min_area (e.g. a U-shaped wall whose middle is cut away).
    """
    lines = _polylines(part, to_local)
    # Fast path: every cut is a closed ring; rings inside the outline are holes.
    if lines and all(l[0] == l[-1] and len(l) > 3 for l in lines):
        rings = sorted((l[:-1] for l in lines), key=lambda r: abs(_area(r)), reverse=True)
        around = [r for r in rings if _inside(*probe, r)] if probe else []
        outer = (around or rings)[0]
        if not around and abs(_area(outer)) < min_area:
            return None  # only holes: the part's outline was drawn elsewhere
        return {
            "outer": [list(p) for p in outer],
            "holes": [[list(p) for p in r] for r in rings
                      if r is not outer and abs(_area(r)) >= _MIN_HOLE_AREA and _inside(*r[0], outer)],
        }
    return _outline_shapely(lines, probe, min_area)


def _outline_shapely(lines, probe=None, min_area: float = 0.0) -> dict | None:
    """Fallback for cuts split over several open paths: node and polygonize them."""
    lines = [LineString(l) for l in lines]
    faces = list(polygonize(unary_union(lines))) if lines else []
    if not faces:
        return None
    # The polygonizer gives the material face with the inner cuts as interior rings.
    around = [f for f in faces if Polygon(f.exterior).contains(Point(probe))] if probe else []
    shape = max(around or faces, key=lambda f: f.area)
    if not around and Polygon(shape.exterior).area < min_area:
        return None
    return {
        "outer": [list(p) for p in shape.exterior.coords[:-1]],
        "holes": [[list(p) for p in ring.coords[:-1]]
                  for ring in shape.interiors if Polygon(ring).area >= _MIN_HOLE_AREA],
    }



def render_with_parts(name: str, args_json: str) -> str:
    """Like render(), plus the recorded walls and their 3D placement.

    Returns {"svg", "parts", "assembly", "thickness"}: "assembly" is false when the generator has no
    placement function (2D only), or the error message if placing failed.
    """
    global _recorder
    _recorder = rec = _Recorder()
    try:
        box, svg = _render_box(name, args_json)
    finally:
        _recorder = None
    parts = []
    for w in rec.walls:
        part = w.pop("_part")
        drawn = Affine(*w["matrix"])
        local = drawn * Affine.translation(*w.pop("_offset"))
        sheet = rec.sheet * local if rec.sheet is not None else local
        w["matrix"] = tuple(sheet)[:6]
        w["part"] = rec.surface.parts.index(part)
        # move="mirror"/"upsidedown" draw the part reflected. The cut piece is flipped over to
        # mount it; placements treat that as a reflection in local x, which keeps every edge
        # in its role (a y reflection is the same plus a 180 degree turn).
        w["mirrored"] = drawn.determinant < 0
        w["outline"] = _outline(part, ~sheet, w.pop("_probe"), 0.2 * w["x"] * w["y"])
        parts.append(w)
    try:
        placements = assemble(name, box, parts)
        assembly = placements is not None
    except Exception as e:  # a broken placement must not break the 2D preview
        placements, assembly = None, f"{type(e).__name__}: {e}"
    for i, w in enumerate(parts):
        w["place"] = placements.get(i) if placements else None
    return json.dumps({"svg": svg, "parts": parts, "assembly": assembly, "thickness": box.thickness})

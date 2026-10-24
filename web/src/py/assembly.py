"""Building blocks for placing recorded walls in 3D.

World frame (mm, Z up). A placement maps a wall's local frame into the world:
local (x, y) -> origin + x*ux + y*uy, and the material is extruded from that face
along n by the thickness. Walls are drawn as seen from outside, so for an unmirrored
wall ux x uy = n.

A placement function (see placements.py) gets an Assembly and puts parts into it:

    a = Assembly(box, walls)
    f = a.frame(x, y, h)              # inner space [0,x] x [0,y] x [0,h]
    f.front(a.parts.label("front"))
    f.back(a.parts.label("back"), rot=180)
    f.dims(x="x", y="y", h="h")       # editable dimensions in the 3D view
"""
from __future__ import annotations

import math
from typing import Callable, Iterable

Vec = tuple[float, float, float]

X: Vec = (1.0, 0.0, 0.0)
Y: Vec = (0.0, 1.0, 0.0)
Z: Vec = (0.0, 0.0, 1.0)


def add(a: Vec, b: Vec, s: float = 1.0) -> Vec:
    return (a[0] + b[0] * s, a[1] + b[1] * s, a[2] + b[2] * s)


def neg(a: Vec) -> Vec:
    return (-a[0], -a[1], -a[2])


class Part:
    """A recorded wall (see boxes_bridge._Recorder) as seen by placement code."""

    def __init__(self, index: int, rec: dict) -> None:
        self.index = index
        self.rec = rec
        self.x: float = rec["x"]
        self.y: float = rec["y"]
        self.label: str = rec["label"]
        self.mirrored: bool = rec["mirrored"]
        # Functions that drew this part, innermost first, e.g. ["Lid.__call__"].
        self.callers: list[str] = rec["callers"]
        # Edge letters bottom, right, top, left; "?" for composite edges.
        self.chars = "".join(e["char"] or "?" for e in rec["edges"])
        self.placed = False

    def __repr__(self) -> str:
        return f"<Part {self.index} {self.label!r} {self.x:g}x{self.y:g} {self.chars}>"

    def segments(self) -> list[tuple[tuple[float, float], tuple[float, float], float]]:
        """(start, direction, length) of each edge in local coordinates, in drawing order
        (counter-clockwise). Edges of rectangularWall etc. lie on the inner shape; those of
        polygonWall on the polygon line itself."""
        rec = self.rec
        x, y = self.x, self.y
        if rec["helper"] == "polygonWall":
            return _polygon_segments(rec["params"]["borders"], rec["params"]["start"])
        if rec["helper"] == "roundedPlate":
            # Only the straight parts between the rounded corners.
            r = min(rec["params"]["r"], x / 2, y / 2)
            return [((r, 0.0), (1.0, 0.0), x - 2 * r), ((x, r), (0.0, 1.0), y - 2 * r),
                    ((x - r, y), (-1.0, 0.0), x - 2 * r), ((0.0, y - r), (0.0, -1.0), y - 2 * r)]
        if rec["helper"] in ("trapezoidWall", "trapezoidSideWall"):
            corners = [(0, 0), (x, 0), (x, rec["params"]["h1"]), (0, rec["params"]["h0"])]
        elif rec["helper"] == "rectangularTriangle":
            corners = [(0, 0), (x, 0), (x, y)]
        else:
            corners = [(0, 0), (x, 0), (x, y), (0, y)]
        out = []
        for (ax, ay), (bx, by) in zip(corners, corners[1:] + corners[:1]):
            length = math.hypot(bx - ax, by - ay)
            d = length or 1.0  # e.g. a trapezoid side of height 0
            out.append(((float(ax), float(ay)), ((bx - ax) / d, (by - ay) / d), length))
        return out


def _polygon_segments(borders, start):
    """Walks polygonWall borders [length, turn, length, turn, ...]; a turn may be
    [angle, radius] for a rounded corner."""
    px, py = float(start[0]), float(start[1])
    ang = 0.0
    segs = []
    for k in range(0, len(borders) - 1, 2):
        dx, dy = math.cos(ang), math.sin(ang)
        length = float(borders[k])
        segs.append(((px, py), (dx, dy), length))
        px, py = px + dx * length, py + dy * length
        turn = borders[k + 1]
        a, r = (turn[0], turn[1]) if isinstance(turn, (list, tuple)) else (turn, 0.0)
        a = math.radians(a)
        if r:  # rounded corner: move along the arc around the centre on the inside
            side = 1 if a > 0 else -1
            cx, cy = px - dy * r * side, py + dx * r * side
            vx, vy = px - cx, py - cy
            px = cx + math.cos(a) * vx - math.sin(a) * vy
            py = cy + math.sin(a) * vx + math.cos(a) * vy
        ang += a
    return segs


def _called(part: Part, func: str) -> bool:
    return any(c == func or c.endswith(func) for c in part.callers)


class Parts(list):
    """List of parts with small query helpers. Queries skip parts that are already placed."""

    def where(self, pred: Callable[[Part], bool]) -> "Parts":
        return Parts(p for p in self if not p.placed and pred(p))

    def label(self, name: str) -> Part | None:
        """First unplaced part with exactly this label."""
        return next(iter(self.where(lambda p: p.label == name)), None)

    def labelled(self, prefix: str) -> "Parts":
        return self.where(lambda p: p.label.startswith(prefix))

    def unlabelled(self) -> "Parts":
        return self.where(lambda p: not p.label)

    def drawn_by(self, func: str) -> "Parts":
        """Parts drawn (directly or indirectly) by a function, e.g. "_TopEdge.drawLid".
        Also matches subclasses that keep the method name ("BeeQueenTransportBoxLid.__call__"
        for "Lid.__call__")."""
        return self.where(lambda p: _called(p, func))

    def not_drawn_by(self, *funcs: str) -> "Parts":
        return self.where(lambda p: not any(_called(p, f) for f in funcs))

    def edges(self, chars: str) -> "Parts":
        return self.where(lambda p: p.chars == chars)

    def first(self) -> Part | None:
        return next(iter(self.where(lambda p: True)), None)


class Assembly:
    def __init__(self, box, walls: list[dict]) -> None:
        self.box = box
        self.t: float = box.thickness
        self.parts = Parts(Part(i, w) for i, w in enumerate(walls))
        self.placements: dict[int, dict] = {}
        self.dims: list[dict] = []
        self.handles: list[dict] = []

    def place(self, part: Part | None, origin: Vec, u: Vec, v: Vec, n: Vec,
              rot: int = 0, flip: bool = False, name: str = "",
              thickness: float | None = None, bend: list | None = None) -> None:
        """Places a part on the plane (origin, u, v) with material along n.

        rot turns the part counter-clockwise in that plane (as seen from n), in degrees
        (multiples of 90). The part always covers [0, w] x [0, h] in u/v from origin, where
        (w, h) is its size after rotation. flip mounts it the other side out (reflected in
        its own x), as does drawing it mirrored; both together cancel out.
        name is shown in the UI for parts the generator did not label.
        thickness overrides the box's for parts made of other material (e.g. acrylic inserts).
        bend makes a flex part follow a path: [(x0, angle, r[, stretch]), ...] arcs from local
        x = x0 of radius r (at the face on the plane) through angle degrees, turning towards -n
        for positive angles; straight in between. stretch is the arc length per length of the
        part (flex settings' stretch). Only for parts without rot or reflection.
        """
        if part is None:
            return
        px, py = part.x, part.y
        k = (rot // 90) % 4
        if k == 0:
            o, ux, uy = origin, u, v
        elif k == 1:
            o, ux, uy = add(origin, u, py), v, neg(u)
        elif k == 2:
            o, ux, uy = add(add(origin, u, px), v, py), neg(u), neg(v)
        else:
            o, ux, uy = add(origin, v, px), neg(v), u
        if part.mirrored != flip:
            o, ux = add(o, ux, px), neg(ux)
        part.placed = True
        self.placements[part.index] = {"origin": o, "ux": ux, "uy": uy, "n": n, "name": name}
        if thickness is not None:
            self.placements[part.index]["t"] = thickness
        if bend:
            assert k == 0 and part.mirrored == flip, "bent parts can't be turned or reflected"
            self.placements[part.index]["bend"] = [list(b) for b in bend]

    def scrap(self, part: Part | None) -> None:
        """A recorded piece that is offcut, not a part (e.g. drawn inside a hole): it stays in
        the 2D sheet but is left out of the part list."""
        if part is not None:
            part.placed = True
            self.placements[part.index] = {"scrap": True}

    def arg(self, name: str):
        """A parameter as the user gave it (generators with "outside" overwrite e.g. box.x
        with the inner size)."""
        return getattr(self.box, "_web_args", {}).get(name, getattr(self.box, name))

    def dim(self, arg: str, a: Vec, b: Vec, out: Vec, index: int | None = None,
            sizes: list[float] | None = None, label: str | None = None,
            axis: str | None = None, value: float | None = None) -> None:
        """An editable dimension in the 3D view: parameter arg (element index of a list
        parameter like sx) measured from a to b, drawn offset along the unit vector out.
        sizes are the list's elements if they are not the parameter itself (e.g. the column
        sizes in TrayLayout's layout text, axis "x" or "y"); label overrides the shown name, value
        the shown value."""
        if value is None:
            value = self.arg(arg) if sizes is None else sizes
        values = None
        if index is not None:
            values = [float(v) for v in value]
            value = values[index]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return
        self.dims.append({"arg": arg, "index": index, "values": values, "value": float(value),
                          "a": a, "b": b, "out": out, "label": label, "axis": axis})

    def handle(self, kind: str, i: int, j: int, on: bool, lo: Vec, hi: Vec) -> None:
        """Something the 3D editor can toggle, e.g. a wall piece ("hwall"/"vwall") or a floor
        cell ("floor") at grid position (i, j), present or not (on), filling the box lo..hi."""
        self.handles.append({"kind": kind, "i": i, "j": j, "on": bool(on), "min": lo, "max": hi})

    def frame(self, x: float, y: float, h: float, origin: Vec = (0.0, 0.0, 0.0),
              name: str = "") -> "BoxFrame":
        return BoxFrame(self, x, y, h, origin, name)


class BoxFrame:
    """A cuboid inner space [0,x] x [0,y] x [0,h] (offset by origin) with the walls around it.

    Face methods take a part and optional rot/flip (see Assembly.place) and du/dv to shift
    it within the face (u = right, v = up, as seen from outside the face). Unlabelled parts
    are named after the face, prefixed with the frame's name (e.g. "lid front").
    """

    def __init__(self, asm: Assembly, x: float, y: float, h: float, origin: Vec,
                 name: str = "") -> None:
        self.asm, self.x, self.y, self.h, self.origin = asm, x, y, h, origin
        self.name = name

    def at(self, x: float, y: float, z: float) -> Vec:
        return add(self.origin, (x, y, z))

    def _face(self, part, face: str, o: Vec, u: Vec, v: Vec, n: Vec, rot: int, du: float,
              dv: float, flip: bool = False) -> None:
        name = f"{self.name} {face}".strip()
        self.asm.place(part, add(add(o, u, du), v, dv), u, v, n, rot, flip, name)

    def front(self, part, rot=0, du=0.0, dv=0.0, flip=False):
        self._face(part, "front", self.at(0, 0, 0), X, Z, neg(Y), rot, du, dv, flip)

    def back(self, part, rot=0, du=0.0, dv=0.0, flip=False):
        self._face(part, "back", self.at(self.x, self.y, 0), neg(X), Z, Y, rot, du, dv, flip)

    def left(self, part, rot=0, du=0.0, dv=0.0, flip=False):
        self._face(part, "left", self.at(0, self.y, 0), neg(Y), Z, neg(X), rot, du, dv, flip)

    def right(self, part, rot=0, du=0.0, dv=0.0, flip=False):
        self._face(part, "right", self.at(self.x, 0, 0), Y, Z, X, rot, du, dv, flip)

    def bottom(self, part, rot=0, du=0.0, dv=0.0, flip=False):
        self._face(part, "bottom", self.at(0, self.y, 0), X, neg(Y), neg(Z), rot, du, dv, flip)

    def top(self, part, rot=0, du=0.0, dv=0.0, flip=False):
        self._face(part, "top", self.at(0, 0, self.h), X, Y, Z, rot, du, dv, flip)

    def inner_x(self, part, y0: float, rot=0, x0=0.0, z0=0.0, flip=False):
        """Wall parallel to the front, material in [y0, y0 + t], seen from the front
        (from the back if flip)."""
        self._face(part, "divider", self.at(x0, y0 + self.asm.t, z0), X, Z, neg(Y), rot, 0, 0, flip)

    def inner_y(self, part, x0: float, rot=0, y0=0.0, z0=0.0, flip=False):
        """Wall parallel to the sides, material in [x0, x0 + t], seen from the right
        (from the left if flip)."""
        self._face(part, "divider", self.at(x0, y0, z0), Y, Z, X, rot, 0, 0, flip)

    def plate(self, part, z0: float, rot=0, x0=0.0, y0=0.0, down=False):
        """Horizontal plate with its inner face at z0, material above (or below if down)."""
        if down:
            self._face(part, "plate", self.at(x0, self.y - y0, z0), X, neg(Y), neg(Z), rot, 0, 0)
        else:
            self._face(part, "plate", self.at(x0, y0, z0), X, Y, Z, rot, 0, 0)

    def dims(self, x: str | None = None, y: str | None = None, h: str | None = None) -> None:
        """Dimensions of the frame along x (front), y (right side) and h (front right corner),
        from the named parameters. A parameter may be a list of compartment sizes (sx, sy;
        sy runs back to front if given as "-sy"). With "outside" the parameter is larger than
        the frame; the difference goes to the ends (h: wall below first)."""
        t = self.asm.t
        if x:
            self.chain(x, "x")
        if y:
            self.chain(y[1:], "-y") if y.startswith("-") else self.chain(y, "y")
        if h:
            self.height(h, self.x + t, -t, self.h, (0.7071, -0.7071, 0.0))

    def height(self, arg: str, x: float, y: float, h: float, out: Vec,
               fallback: str | None = None) -> None:
        """Dimension of walls h high standing at (x, y) from parameter arg (if 0: from parameter
        fallback, e.g. hi = 0 meaning "same as h"). With "outside" the parameter is larger than h;
        the difference goes below first (the floor)."""
        value = self.asm.arg(arg)
        if not value and fallback:
            value = self.asm.arg(fallback)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return
        extra = value - h
        below = min(max(extra, 0.0), self.asm.t)
        self.asm.dim(arg, self.at(x, y, -below), self.at(x, y, h + extra - below), out,
                     value=float(value))

    def chain(self, arg: str, side: str, sizes: list[float] | None = None,
              label: str | None = None, axis: str | None = None) -> None:
        """Dimensions along the front (side "x"), the right side ("y") or the right side from
        back to front ("-y"): one per list element (with walls of thickness t in between), or
        one for a single value. sizes/label/axis: see Assembly.dim. With "outside" the sizes
        are larger than the inner space: they then cover it and the outer walls, end to end
        and centred."""
        t = self.asm.t
        start, d, inner, out = {
            "x": (self.at(0, -t, 0), X, self.x, neg(Y)),
            "y": (self.at(self.x + t, 0, 0), Y, self.y, X),
            "-y": (self.at(self.x + t, self.y, 0), neg(Y), self.y, X),
        }[side]
        value = self.asm.arg(arg) if sizes is None else sizes
        is_list = isinstance(value, list)
        sizes = [float(v) for v in value] if is_list else [float(value)]
        if sum(sizes) + t * (len(sizes) - 1) > inner + 1e-6:
            t = 0.0
        pos = (inner - sum(sizes) - t * (len(sizes) - 1)) / 2
        for k, size in enumerate(sizes):
            self.asm.dim(arg, add(start, d, pos), add(start, d, pos + size), out,
                         k if is_list else None, sizes if sizes is not None and is_list else None,
                         f"{label}[{k + 1}]" if label and is_list else label, axis)
            pos += size + t

    def sub(self, x0: float, y0: float, z0: float, x: float, y: float, h: float,
            name: str | None = None) -> "BoxFrame":
        return BoxFrame(self.asm, x, y, h, self.at(x0, y0, z0), self.name if name is None else name)


def positions(sizes: Iterable[float], t: float, start: float = 0.0) -> list[float]:
    """Start of each wall between compartments of the given sizes: sizes[0], then t, ..."""
    out, pos = [], start
    sizes = list(sizes)
    for s in sizes[:-1]:
        pos += s
        out.append(pos)
        pos += t
    return out

# Copyright (C) 2016 Florian Festi
#
#   This program is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program.  If not, see <http://www.gnu.org/licenses/>.
from __future__ import annotations

import io
from pathlib import Path

import boxes
from boxes import *
from boxes import lids
from boxes.generators.typetray import FingerHoleEdge, FingerHoleEdgeSettings


_MAGNET_DOC = " * magnet_diameter : 0.0 : diameter of magnet holes in mm (sliding lid only; 0 to disable)\n"


class TrayLidSettings(lids.LidSettings):
    __doc__ = (lids.LidSettings.__doc__ or "") if "magnet_diameter" in (lids.LidSettings.__doc__ or "") else \
        (lids.LidSettings.__doc__ or "").replace("\n* relative", _MAGNET_DOC + "\n* relative", 1)

    absolute_params = {
        **lids.LidSettings.absolute_params,
        "style": tuple(dict.fromkeys(lids.LidSettings.absolute_params["style"] + ("sliding",))),
        "magnet_diameter": 0.0,
    }


class TrayLid(lids.Lid):
    """Lid with an additional "sliding" style that only works with TrayLayout:
    the front wall is lowered by one thickness so a two layer lid can slide in
    over it; the lower layer locks into finger holes in the raised back wall."""

    def __call__(self, x: float, y: float, edge=None) -> bool:
        if self.settings.style != "sliding":
            return super().__call__(x, y, edge)
        t = self.thickness
        bs = self.brim_spacing
        md = self.magnet_diameter
        w_bot = x - bs * 2
        l_bot = y + t - bs

        def bottomCB() -> None:
            self.handleCB(w_bot, l_bot)()
            if md > 0 and w_bot > 2 * md:
                m = max(md, 1.5 * t)
                self.hole(m, m, d=md)
                self.hole(w_bot - m, m, d=md)

        def topCB() -> None:
            if self.handle != "none":
                self.handleCB(x, y - bs)()
            else:
                grip_w = min(x * 0.35, 30.0)
                if grip_w > 2 * t and y > 4 * t:
                    self.rectangularHole(x / 2, 2 * t, grip_w, t, r=t / 2)

        self.rectangularWall(w_bot, l_bot, "eefe", callback=[bottomCB],
                             move="up", label="lid bottom")
        self.rectangularWall(x, y - bs, "EEeE", callback=[topCB],
                             move="up", label="lid top")
        self.handleParts(x, y)
        return True


class TrayLayoutFile(Boxes):
    """Generate a layout file for a typetray."""
    # This class generates the skeleton text file that can then be edited
    # to describe the actual box

    description = """This is a two step process. This is step 1.
The layout is based on a grid of sizes in x and y direction.
Choose how many distances you need in both directions.
The actual sizes and all other settings can be entered in the second step."""

    webinterface = False

    ui_group = "Tray"

    sx: list[float] = []  # arg input
    sy: list[float] = []  # arg input
    hwalls: list[list[bool]] = []
    vwalls: list[list[bool]] = []
    floors: list[list[bool]] = []

    def __init__(self, input=None, webargs=False) -> None:
        Boxes.__init__(self)
        self.argparser = argparse.ArgumentParser()
        self.buildArgParser("sx", "sy")
        self.argparser.add_argument(
            "--output", action="store", type=str, default="traylayout.txt",
            help="Name of the layout text file.")

    def open(self) -> None:
        # Use empty open and close methods to avoid initializing the whole drawing infrastructure.
        pass

    def close(self):
        # Use empty open and close methods to avoid initializing the whole drawing infrastructure.
        return io.BytesIO(bytes(str(self), 'utf-8'))

    def fillDefault(self, sx: list[float], sy: list[float]) -> None:
        self.sx = sx
        self.sy = sy
        x = len(sx)
        y = len(sy)
        self.hwalls = [[True for _ in range(x)] for _ in range(y + 1)]
        self.vwalls = [[True for _ in range(x + 1)] for _ in range(y)]
        self.floors = [[True for _ in range(x)] for _ in range(y)]

    def __str__(self) -> str:
        r = []

        for i, x in enumerate(self.sx):
            r.append(" |" * i + f" ,> {x:.1f}mm\n")

        for hwalls, vwalls, floors, y in zip(self.hwalls, self.vwalls, self.floors, self.sy):
            r.append("".join("+" + " -"[h] for h in hwalls) + "+\n")
            r.append("".join((" |"[v] + "X "[f] for v, f in zip(vwalls, floors))) + " |"[vwalls[-1]] + f" {y:.1f}mm\n")
        r.append("".join("+" + " -"[h] for h in self.hwalls[-1]) + "+\n")

        return "".join(r)

    def render(self) -> None:
        self.fillDefault(self.sx, self.sy)

class TrayLayout(Boxes):
    """Generate a typetray from a layout file."""

    # This class reads in the layout either from a file (with --input) or
    # as string (with --layout) and turns it into a drawing for a box.

    ui_group = "Tray"

    fingerholes = "none"  # for subclasses with their own arguments

    # Set by parse(): walls on the "+-+" lines, walls before each column, floors per cell.
    hwalls: list[list[bool]]
    vwalls: list[list[bool]]
    floors: list[list[bool]]

    description = """This is a two step process. This is step 2.
Edit the layout text graphics to adjust your tray.
Put in the sizes for each column and row. You can replace the hyphens and
vertical bars representing the walls with a space character to remove the walls.
You can replace the space characters representing the floor by a "X" to remove the floor for this compartment.
"""

    def __init__(self) -> None:
        super().__init__()
        self.addSettingsArgs(boxes.edges.FingerJointSettings)
        self.addSettingsArgs(TrayLidSettings, prefix="Lid")
        self.buildArgParser("h", "hi", "outside", "sx", "sy")
        self.addSettingsArgs(FingerHoleEdgeSettings)
        self.argparser.add_argument(
            "--fingerholes", action="store", type=str, default="none",
            choices=["none", "inside-only", "front", "back", "front-and-back"],
            help="finger holes in the walls along x; decide which outer walls get them, too")
        self.argparser.add_argument(
            "--layout", action="store", type=str, default="\n",
            help="""* Set **sx** and **sy** before editing this!
* You can still change measurements afterwards
* You can replace the hyphens and vertical bars representing the walls
with a space character to remove the walls.
* You can replace the space characters representing the floor by a "X"
to remove the floor for this compartment.
* A size of 0mm for the first or last row or column makes the next wall
a liner glued to the outer wall (no finger joints).
* Resize text area if necessary.""")
        self.description = ""
        if self.UI != "web":
            self.argparser.add_argument(
                "--input", action="store", type=str,
                default="traylayout.txt",
                help="layout file")

    def vWalls(self, x: int, y: int) -> int:
        """Number of vertical walls at a crossing."""
        result = 0
        if y > 0 and self.vwalls[y - 1][x]:
            result += 1
        if y < len(self.y) and self.vwalls[y][x]:
            result += 1
        return result

    def hWalls(self, x: int, y: int) -> int:
        """Number of horizontal walls at a crossing."""
        result = 0
        if x > 0 and self.hwalls[y][x - 1]:
            result += 1
        if x < len(self.x) and self.hwalls[y][x]:
            result += 1
        return result

    def vFloor(self, x: int, y: int) -> bool:
        """Is there floor under vertical wall."""
        if y >= len(self.y):
            return False

        return (x > 0 and self.floors[y][x - 1]) or (x < len(self.x) and self.floors[y][x])

    def hFloor(self, x: int, y: int) -> bool:
        """Is there floor under horizontal wall."""
        if x >= len(self.x):
            return False
        return (y > 0 and self.floors[y - 1][x]) or (y < len(self.y) and self.floors[y][x])

    @restore
    def edgeAt(self, edge, x, y, length, angle=0):
        self.moveTo(x, y, angle)
        edge = self.edges.get(edge, edge)
        edge(length)

    @restore
    def cornerAt(self, x, y, length, angle=0):
        self.moveTo(x, y, angle)
        self.polyline(length, 90, length)

    def prepare(self):
        # --layout defaults to "\n", so treat a blank layout as not given
        # and fall back to the --input file (CLI only) or generate_layout().
        layout_file = getattr(self, "input", None)
        layout = self.layout
        if layout and "\n" not in layout and "\\n" in layout:
            # The "Command line" stored in the SVG writes the layout's newlines
            # as a literal \n (see cliQuote() in boxes/__init__.py); decode them
            # so that command can be run again.
            layout = layout.replace("\\n", "\n")
        if layout and layout.strip():
            self.parse(layout.split('\n'))
        elif layout_file and Path(layout_file).exists():
            with Path(layout_file).open() as input_file:
                self.parse(input_file)
        elif callable(getattr(self, "generate_layout", None)):
            self.parse(self.generate_layout().split('\n'))
        else:
            raise RuntimeError("traylayout requires --layout, --input, or implementation of generate_layout")

        sliding = self.lidSettings.style == "sliding"
        if self.outside:
            self.x = self.adjustSize(self.x)
            self.y = self.adjustSize(self.y)
            self.h = self.adjustSize(self.h, e2=False)
            if sliding:
                self.h -= self.thickness

            if self.hi:
                self.hi = self.adjustSize(self.hi, e2=False)

        self.removeZeroSizes()
        if sliding:
            self.hi = min(self.hi, self.h - self.thickness) if self.hi else self.h - self.thickness
        else:
            self.hi = self.hi or self.h
        self.edges["s"] = boxes.edges.Slot(self, self.hi / 2.0)
        self.edges["C"] = boxes.edges.CrossingFingerHoleEdge(self, self.hi)
        self.edges["D"] = boxes.edges.CrossingFingerHoleEdge(self, self.hi, outset=self.thickness)
        s = FingerHoleEdgeSettings(self.thickness, True,
                **self.edgesettings.get("FingerHoleEdge", {}))
        s.wallheight = 0 if self.fingerholes == "none" else self.hi
        self.addPart(FingerHoleEdge(self, s))

    def removeZeroSizes(self) -> None:
        """Rows and columns of size 0 at the edge of the layout: the wall next to the outer
        wall becomes a liner, a plain plate glued to the outer wall (no finger joints, no holes
        in floor or side walls). They are taken out of the grid; the neighbouring row or column
        grows by the liner's thickness (the liner stands in it, see liners()).

        Sets self.liner: per side ("back", "front": per column; "left", "right": per row) where
        a liner stands, self.liner_pieces (drawn by liners()) and self.zero_sizes (removed
        (first, last) row or column per axis) for colIndex() etc."""
        t = self.thickness
        x, y = list(self.x), list(self.y)
        lx, ly = len(x), len(y)
        self.layout_x, self.layout_y = x, y
        for name, sizes in (("column", x), ("row", y)):
            if any(s == 0 for s in sizes[1:-1]):
                raise ValueError(f"Only the first and the last {name} can have a size of 0 (a liner)")
            if sum(1 for s in sizes if s > 0) == 0:
                raise ValueError(f"Need at least one {name} larger than 0")
        first_x, last_x = x[0] == 0, lx > 1 and x[-1] == 0
        first_y, last_y = y[0] == 0, ly > 1 and y[-1] == 0
        self.zero_sizes = {"x": (int(first_x), int(last_x)), "y": (int(first_y), int(last_y))}
        hw = [list(row[:lx]) for row in self.hwalls]
        vw = [list(row[:lx + 1]) for row in self.vwalls]
        fl = [list(row[:lx]) for row in self.floors[:ly]]
        cols = range(int(first_x), lx - int(last_x))
        rows = range(int(first_y), ly - int(last_y))
        # Where a liner stands: both walls there and floor in front of it (original indices).
        self.liner = {
            "back": [first_y and hw[0][c] and hw[1][c] and fl[1][c] for c in cols],
            "front": [last_y and hw[ly][c] and hw[ly - 1][c] and fl[ly - 2][c] for c in cols],
            "left": [first_x and vw[r][0] and vw[r][1] and fl[r][1] for r in rows],
            "right": [last_x and vw[r][lx] and vw[r][lx - 1] and fl[r][lx - 2] for r in rows],
        }
        if not (first_x or last_x or first_y or last_y):
            self.liner_pieces = []
            return

        def lines(n: int, first: bool, last: bool) -> list[tuple[int, int]]:
            """(line, other) of each remaining grid line: an outer line takes the liner's
            line where its own wall is missing."""
            return ([(0, 1 if first else 0)]
                    + [(k, k) for k in range(1 + first, n - last)]
                    + [(n, n - 1 if last else n)])

        self.hwalls = [[hw[a][c] or hw[b][c] for c in cols] for a, b in lines(ly, first_y, last_y)]
        self.vwalls = [[vw[r][a] or vw[r][b] for a, b in lines(lx, first_x, last_x)] for r in rows]
        self.floors = [[fl[r][c] for c in cols] + [False] for r in rows]
        self.floors.append([False] * (len(cols) + 1))
        self.x = [x[c] for c in cols]
        self.y = [y[r] for r in rows]
        if first_x:
            self.x[0] += t
        if last_x:
            self.x[-1] += t
        if first_y:
            self.y[0] += t
        if last_y:
            self.y[-1] += t
        self.liner_pieces = self._linerPieces()

    def _linerPieces(self) -> list[dict]:
        """Liner plates: runs of liner along each side, split where an inner wall meets it
        (that wall reaches through to the outer wall). Back and front liners run into the
        corners; left and right ones are cut short (cut0 at the back, cut1 at the front) where
        those are taken."""
        t = self.thickness
        lx, ly = len(self.x), len(self.y)
        pieces = []
        for side, row in (("back", 0), ("front", ly - 1)):
            flags = self.liner[side]
            i = 0
            while i < lx:
                if not flags[i]:
                    i += 1
                    continue
                e = i + 1
                while e < lx and flags[e] and not self.vwalls[row][e]:
                    e += 1
                pieces.append({"side": side, "start": i, "end": e, "cut0": False, "cut1": False,
                               "sizes": self.x[i:e]})
                i = e
        for side, col in (("left", 0), ("right", lx - 1)):
            flags = self.liner[side]
            j = 0
            while j < ly:
                if not flags[j]:
                    j += 1
                    continue
                e = j + 1
                while e < ly and flags[e] and not self.hwalls[e][col]:
                    e += 1
                sizes = list(self.y[j:e])
                cut0 = j == 0 and bool(self.liner["back"][col])
                cut1 = e == ly and bool(self.liner["front"][col])
                if cut0:
                    sizes[0] -= t
                if cut1:
                    sizes[-1] -= t
                pieces.append({"side": side, "start": j, "end": e, "cut0": cut0, "cut1": cut1,
                               "sizes": sizes})
                j = e
        return pieces

    def liners(self) -> None:
        """The liner plates (see removeZeroSizes()): as high as the inner walls, plain edges,
        finger holes in the top like the inner walls."""
        pieces = getattr(self, "liner_pieces", [])
        if not pieces:
            return
        t = self.thickness
        self.ctx.save()
        for p in pieces:
            lengths = []
            for s in p["sizes"]:
                lengths += [s, t]
            lengths.pop()
            top: str | boxes.edges.BaseEdge = "e"
            if self.fingerholes != "none":
                top = boxes.edges.CompoundEdge(
                    self, ["Ae"[i % 2] for i in range(len(lengths))], lengths[::-1])
            along_x = p["side"] in ("back", "front")
            line = self.yLineIndex(0 if p["side"] == "back" else len(self.y)) if along_x else \
                self.xLineIndex(0 if p["side"] == "left" else len(self.x))
            # The liner stands on the layout line next to the outer one.
            line += 1 if p["side"] in ("back", "left") else -1

            def label(p=p, line=line, lengths=lengths) -> None:
                if not self.labels:
                    return
                pos = 0.0
                for k in range(p["start"], p["end"]):
                    s = lengths[2 * (k - p["start"])]
                    name = f"x {self.colIndex(k) + 1}/{line + 1}" if along_x else \
                        f"y {line + 1}/{self.rowIndex(k) + 1}"
                    self.text(f"liner {name}", pos + s / 2, 0, color=Color.ANNOTATIONS,
                              align="center", fontsize=2 * t)
                    pos += s + t

            self.rectangularWall(sum(lengths), self.hi, ["e", "e", top, "e"],
                                 callback=[label], move="right")
        self.ctx.restore()
        self.rectangularWall(10, self.hi, "eeee", move="up only")

    def colIndex(self, i: int) -> int:
        """Column of the layout text for column i of the grid (see removeZeroSizes())."""
        return i + getattr(self, "zero_sizes", {"x": (0, 0)})["x"][0]

    def rowIndex(self, j: int) -> int:
        return j + getattr(self, "zero_sizes", {"y": (0, 0)})["y"][0]

    def xLineIndex(self, i: int) -> int:
        """Vertical line of the layout text for vertical grid line i (0 = left)."""
        first, last = getattr(self, "zero_sizes", {"x": (0, 0)})["x"]
        return 0 if i == 0 else (i + first + last if i == len(self.x) else i + first)

    def yLineIndex(self, j: int) -> int:
        """Horizontal line of the layout text for horizontal grid line j (0 = back)."""
        first, last = getattr(self, "zero_sizes", {"y": (0, 0)})["y"]
        return 0 if j == 0 else (j + first + last if j == len(self.y) else j + first)

    def hasFingerHoles(self, y: int) -> bool:
        """Do the walls on horizontal grid line y (0 = back) get finger holes."""
        if self.fingerholes == "none":
            return False
        if y == 0:
            return self.fingerholes in ("back", "front-and-back")
        if y == len(self.y):
            return self.fingerholes in ("front", "front-and-back")
        return True

    def wallLabelsCB(self, start, end, row, x=True):
        if not self.labels:
            return
        sx = self.x if x else self.y
        posx = 0
        for pos in range(start, end):
            posx += sx[pos] / 2
            self.text(f"x {self.colIndex(pos)+1}/{self.yLineIndex(row)+1}" if x else
                      f"y {self.xLineIndex(row)+1}/{self.rowIndex(pos)+1}", posx, 0,
                      color=Color.ANNOTATIONS, align="center", fontsize=2*self.thickness)
            posx += sx[pos] / 2 + self.thickness

    def walls(self, move=None):
        lx = len(self.x)
        ly = len(self.y)
        t = self.thickness
        sliding = self.lidSettings.style == "sliding"

        def hy(y: int) -> float:
            if y == 0:
                return self.h + t if sliding else self.h
            if y == ly:
                return self.h - t if sliding else self.h
            return self.hi

        def hx(x: int) -> float:
            return self.h if x in (0, lx) else self.hi

        def side_edge(h_cur: float, h_other: float, is_outer: bool, ch: str, is_left: bool):
            if h_cur > h_other:
                fill = "E" if is_outer else "e"
                if is_left:
                    return boxes.edges.CompoundEdge(self, fill + ch, [h_cur - h_other, h_other])
                return boxes.edges.CompoundEdge(self, ch + fill, [h_other, h_cur - h_other])
            return ch

        self.ctx.save()

        # Horizontal Walls
        for y in range(ly + 1):
            h = hy(y)
            is_outer = y in (0, ly)
            if is_outer:
                # limit finger holes to outer wall height
                self.edges["C"].height = min(h, self.hi)
                self.edges["D"].height = min(h, self.hi)
            else:
                self.edges["C"].height = self.hi
                self.edges["D"].height = self.hi

            start = 0
            end = 0

            while end < lx:
                lengths = []
                edges = []

                while start < lx and not self.hwalls[y][start]:
                    start += 1

                if start == lx:
                    break

                end = start

                while end < lx and self.hwalls[y][end]:
                    if self.hFloor(end, y):
                        edges.append("f")
                    else:
                        edges.append("E")

                    lengths.append(self.x[end])
                    if self.hFloor(end, y) == 0 and self.hFloor(end + 1, y) == 0:
                        edges.append("EDs"[self.vWalls(end + 1, y)])
                    else:
                        edges.append("eCs"[self.vWalls(end + 1, y)])
                    lengths.append(self.thickness)
                    end += 1

                # remove last "slot"
                lengths.pop()
                edges.pop()
                le = side_edge(h, hx(start), is_outer, "f", True)
                re = side_edge(h, hx(end), is_outer, "f", False)
                top = "e"
                if self.hasFingerHoles(y):
                    # one finger hole per compartment, none over the crossings
                    top = boxes.edges.CompoundEdge(
                        self, ["Ae"[i % 2] for i in range(len(lengths))], lengths[::-1])

                wall_len = sum(lengths)
                bs = self.lidSettings.brim_spacing

                def hwallCB(s=start, e=end, row=y, wl=wall_len) -> None:
                    self.wallLabelsCB(s, e, row)
                    if sliding and row == 0 and wl > 2 * bs:
                        self.fingerHolesAt(bs, self.h - 0.5 * t, wl - 2 * bs, 0)

                self.rectangularWall(wall_len, h, [
                    boxes.edges.CompoundEdge(self, edges, lengths),
                    re if self.vWalls(end, y) else "e",
                    top,
                    le if self.vWalls(start, y) else "e"],
                                     callback=[hwallCB],
                                     move="right")
                start = end

        self.ctx.restore()
        self.rectangularWall(10, max(self.h + (t if sliding else 0), self.hi), "ffef", move="up only")
        self.ctx.save()

        # Vertical Walls
        for x in range(lx + 1):
            h = hx(x)
            is_outer = x in (0, lx)
            if is_outer:
                self.edges["C"].height = min(h, self.hi)
                self.edges["D"].height = min(h, self.hi)
            else:
                self.edges["C"].height = self.hi
                self.edges["D"].height = self.hi
            start = 0
            end = 0

            while end < ly:
                lengths = []
                edges = []
                while start < ly and not self.vwalls[start][x]:
                    start += 1

                if start == ly:
                    break

                end = start

                while end < ly and self.vwalls[end][x]:
                    if self.vFloor(x, end):
                        edges.append("f")
                    else:
                        edges.append("E")

                    lengths.append(self.y[end])
                    if self.vFloor(x, end) == 0 and self.vFloor(x, end + 1) == 0:
                        edges.append("EDS"[self.hWalls(x, end + 1)])
                    else:
                        edges.append("eCs"[self.hWalls(x, end + 1)])
                    lengths.append(self.thickness)
                    end += 1
                # remove last "slot"
                lengths.pop()
                edges.pop()

                upper = [{"f": "e",
                          "s": "s",
                          "S": "s", # abuse for E at bottom
                          "e": "e",
                          "E": "e",
                          "C": "e",
                          "D": "e"}[e] for e in reversed(edges)]
                edges = ["e" if e == "s" else ("E" if e == "S" else e) for e in edges]
                les = ["e", side_edge(h, hy(start), is_outer, "F", True), side_edge(h, hy(start), is_outer, "f", True)]
                res = ["e", side_edge(h, hy(end), is_outer, "F", False), side_edge(h, hy(end), is_outer, "f", False)]
                self.rectangularWall(sum(lengths), h, [
                    boxes.edges.CompoundEdge(self, edges, lengths),
                    res[self.hWalls(x, end)],
                    boxes.edges.CompoundEdge(self, upper, list(reversed(lengths))),
                    les[self.hWalls(x, start)]],
                                     callback=[lambda: self.wallLabelsCB(start, end, x, x=False)],
                                     move="right")
                start = end

        self.ctx.restore()
        self.rectangularWall(10, max(self.h, self.hi), "ffef", move="up only")
        self.liners()

    def base_plate(self, callback=None, move=None):
        lx = len(self.x)
        ly = len(self.y)
        t = self.thickness
        w = self.edges["F"].startWidth()
        b = self.burn
        t2 = self.thickness / 2.0

        tw = sum(self.x) + (lx - 1) * t + 2 * w
        th = sum(self.y) + (ly - 1) * t + 2 * w

        if self.move(tw, th, move, True):
            return

        for i, (x, y, a) in enumerate((
                (w, w + b, 0),
                (tw - w, w + b, 90),
                (tw - w, th - w + b, 180),
                (w, th - w + b, 270))):
            self.cc(callback, i, x, y, a)

        # Horizontal lines
        posy = w - t
        for y in range(ly, -1, -1):
            posx = w
            for x in range(lx):
                if self.hwalls[y][x]:
                    e = "F"
                else:
                    e = "e"
                if self.labels:
                    self.text(
                        f"x {self.colIndex(x)+1}/{self.yLineIndex(y)+1}",
                        posx+self.x[x]/2,
                        posy + (t if y > 0 else 0),
                        color=Color.ANNOTATIONS,
                        align=("center" if y>0 else "center top"),
                        fontsize=2*self.thickness)
                if self.floors[y][x]:
                    if self.floors[y - 1][x]:
                        # Inside Wall
                        if self.hwalls[y][x]:
                            self.fingerHolesAt(posx, posy + t2, self.x[x], angle=0)
                    else:
                        # Top edge
                        self.edgeAt(e, posx + self.x[x],
                                    posy + w + b, self.x[x],
                                    -180)

                        if not self.floors[y - 1][x - 1] and not self.floors[y][x - 1]:
                            self.cornerAt(posx, posy + w + b, w, 180) # top left corner
                        if not self.floors[y - 1][x + 1] and not self.floors[y][x + 1]:
                            self.cornerAt(posx + self.x[x] + w + b, posy, w, 90) # top right corner
                        if not self.floors[y - 1][x - 1] and self.floors[y][x - 1]:
                            self.edgeAt("e", posx - t, posy + w + b, t, 0) # top edge under wall
                elif self.floors[y - 1][x]:
                    # Bottom Edge
                    self.edgeAt(e, posx, posy - b + t - w, self.x[x])
                    if not self.floors[y - 1][x - 1] and not self.floors[y][x - 1]:
                        self.cornerAt(posx - w -b, posy + t , w, -90) # bottom left corner
                    if not self.floors[y - 1][x + 1] and not self.floors[y][x + 1]:
                        self.cornerAt(posx + self.x[x], posy + t - w - b, w, 0) # bottom right corner
                    if self.floors[y - 1][x - 1] and not self.floors[y][x - 1]:
                        self.edgeAt("e", posx - t, posy + t - w - b, t) # bottom edge under wall
                posx += self.x[x] + self.thickness
            posy += self.y[y - 1] + self.thickness

        posx = w - t
        for x in range(lx + 1):
            posy = w
            for y in range(ly - 1, -1, -1):
                if self.vwalls[y][x]:
                    e = "F"
                else:
                    e = "e"
                if self.labels:
                    self.text(
                        f"y {self.xLineIndex(x)+1}/{self.rowIndex(y)+1}",
                        posx+ (t if x < lx else 0),
                        posy+self.y[y]/2,
                        color=Color.ANNOTATIONS,
                        angle=-90,
                        align=("center" if x < lx else "center top"),
                        fontsize=2*self.thickness)
                if self.floors[y][x - 1]:
                    if self.floors[y][x]:
                        # Inside wall
                        if self.vwalls[y][x]:
                            self.fingerHolesAt(posx + t2, posy, self.y[y])
                    else:
                        # Right edge
                        self.edgeAt(e, posx + w + b, posy, self.y[y], 90)
                        if self.floors[y-1][x-1] and not self.floors[y - 1][x]:
                            self.edgeAt("e", posx + w + b, posy + self.y[y], t, 90) # right edge under wall
                elif self.floors[y][x]:
                    # Left edge
                    self.edgeAt(e, posx + t - w - b, posy + self.y[y], self.y[y], -90)
                    if self.floors[y - 1][x] and not self.floors[y - 1][x - 1]:
                        self.edgeAt("e", posx + t - w - b,
                                    posy + self.y[y] + t, t, -90)
                posy += self.y[y] + self.thickness
            if x < lx:
                posx += self.x[x] + self.thickness

        self.move(tw, th, move)

    def parse(self, input):
        x = []
        y = []
        hwalls = []
        vwalls = []
        floors = []
        for nr, line in enumerate(input):
            if not line or line[0] == "#":
                continue
            m = re.match(r"( \|)* ,>\s*(\d*\.?\d+)\s*mm\s*", line)
            if m:
                x.append(float(m.group(2)))
                continue
            if line[0] == '+':
                w = []
                for n, c in enumerate(line[:len(x) * 2 + 1]):
                    if n % 2:
                        if c == ' ':
                            w.append(False)
                        elif c == '-':
                            w.append(True)
                        else:
                            pass
                            # raise ValueError(line)
                    else:
                        if c != '+':
                            pass
                            # raise ValueError(line)

                hwalls.append(w)
            if line[0] in " |":
                w = []
                f = []
                for n, c in enumerate(line[:len(x) * 2 + 1]):
                    if n % 2:
                        if c in 'xX':
                            f.append(False)
                        elif c == ' ':
                            f.append(True)
                        else:
                            raise ValueError(f"""Can't parse line {nr + 1} in layout: expected " ", "x" or "X" for char #{n + 1}""")
                    else:
                        if c == ' ':
                            w.append(False)
                        elif c == '|':
                            w.append(True)
                        else:
                            raise ValueError(f"""Can't parse line {nr + 1} in layout: expected " ", or "|" for char #{n + 1}""")

                floors.append(f)
                vwalls.append(w)
                m = re.match(r"([ |][ xX])+[ |]\s*(\d*\.?\d+)\s*mm\s*", line)
                if not m:
                    raise ValueError(f"""Can't parse line {nr + 1} in layout: Can read height of the row""")
                else:
                    y.append(float(m.group(2)))

        # check sizes
        lx = len(x)
        ly = len(y)

        if lx == 0:
            raise ValueError("Need more than one wall in x direction")
        if ly == 0:
            raise ValueError("Need more than one wall in y direction")
        if len(hwalls) != ly + 1:
            raise ValueError(f"Wrong number of horizontal wall lines: {len(hwalls)} ({ly + 1} expected)")
        for nr, walls in enumerate(hwalls):
            if len(walls) != lx:
                raise ValueError(f"Wrong number of horizontal walls in line {nr}: {len(walls)} ({lx} expected)")
        if len(vwalls) != ly:
            raise ValueError(f"Wrong number of vertical wall lines: {len(vwalls)} ({ly} expected)")
        for nr, walls in enumerate(vwalls):
            if len(walls) != lx + 1:
                raise ValueError(f"Wrong number of vertical walls in line {nr}: {len(walls)} ({lx + 1} expected)")

        self.x = x
        self.y = y
        self.hwalls = hwalls
        self.vwalls = vwalls
        self.floors = floors
        # Add row of no floor to the right and bottom
        # to avoid special casing the borders
        # Will also show up as index -1
        for l in floors:
            l.append(False)
        floors.append([False] * (lx+1))

    def _buildObjects(self) -> None:
        # the core Lid only knows the generic styles and params
        lid = self.edgesettings.get("Lid", {})
        base = lids.LidSettings
        known = {**base.absolute_params, **base.relative_params}
        core = {k: v for k, v in lid.items() if k in known}
        if core.get("style") not in base.absolute_params["style"]:
            core["style"] = "none"
        self.edgesettings["Lid"] = core
        super()._buildObjects()
        self.edgesettings["Lid"] = lid
        self.lidSettings = TrayLidSettings(self.thickness, True, **lid)
        self.lid = TrayLid(self, self.lidSettings)

    def render(self) -> None:
        self.prepare()
        self.walls()
        self.base_plate(move="up")
        self.lid(sum(self.x) + (len(self.x)-1) * self.thickness,
                 sum(self.y) + (len(self.y)-1) * self.thickness)

"""TypeTray: back_height raises the back wall and the back end of the side walls."""
from __future__ import annotations

import sys
from pathlib import Path

try:
    import boxes
except ImportError:
    sys.path.append(Path(__file__).resolve().parent.parent.__str__())
    import boxes

from boxes.generators.typetray import TypeTray


def side_walls(*args: str) -> dict:
    """Renders a TypeTray; returns the trapezoid walls by label as (h0, h1): h0 at the start
    of the wall, h1 at its end."""
    box = TypeTray()
    box.parseArgs(["--outside=0", *args])
    box.metadata["reproducible"] = True
    box.open()
    walls = {}
    draw = box.trapezoidSideWall

    def record(w, h0, h1, *a, **kw):
        walls[kw.get("label")] = (h0, h1)
        return draw(w, h0, h1, *a, **kw)

    box.trapezoidSideWall = record
    box.render()
    box.close()
    return walls


def test_back_height_raises_the_back_end_of_the_side_walls():
    # Walls are drawn as seen from outside, going round the box: the right side starts at the
    # front, the left side at the back.
    walls = side_walls("--h=40", "--back_height=20", "--top_edge=e")
    assert walls["left side"] == (60, 40)
    assert walls["right side"] == (40, 60)


def test_back_height_needs_an_open_top():
    assert side_walls("--h=40", "--back_height=20", "--top_edge=f") == {}

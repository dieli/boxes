"""Generators draw as many loose parts as the holes they go into."""
from __future__ import annotations

import sys
from pathlib import Path

try:
    import boxes
except ImportError:
    sys.path.append(Path(__file__).resolve().parent.parent.__str__())
    import boxes

import pytest

from boxes.generators.spicesrack import SpicesRack
from boxes.generators.winerack import WineRack


def counting(box, *names: str) -> dict:
    """Counts calls of the box's methods while it renders (not partsMatrix's "... only" moves,
    which draw nothing)."""
    n = dict.fromkeys(names, 0)
    for name in names:
        method = getattr(box, name)

        def count(*a, _name=name, _method=method, **kw):
            n[_name] += "only" not in str(kw.get("move"))
            return _method(*a, **kw)

        setattr(box, name, count)
    box.open()
    box.render()
    box.close()
    return n


@pytest.mark.parametrize("numy", [1, 3])
def test_spices_rack_feet_replace_the_lowest_supports(numy):
    box = SpicesRack()
    box.parseArgs(["--numx=4", f"--numy={numy}", "--feet=1"])
    n = counting(box, "support", "foot")
    assert n == {"support": 3 * (numy - 1), "foot": 3}


@pytest.mark.parametrize("walls", ["minimal", "no_verticals", "all"])
@pytest.mark.parametrize("y", ["150", "210", "300"])  # 1, 2 and 3 rows of cells
def test_wine_rack_one_wall_per_pair_of_finger_hole_rows(walls, y):
    box = WineRack()
    box.parseArgs([f"--walls={walls}", "--x=300", f"--y={y}"])
    walls_drawn = []
    matrix = box.partsMatrix
    box.partsMatrix = lambda n, *a, **kw: (walls_drawn.append(n), matrix(n, *a, **kw))[1]
    n = counting(box, "hexFingerHoles")
    # The middle and the back plate have the same finger holes.
    assert walls_drawn == [n["hexFingerHoles"] // 2]

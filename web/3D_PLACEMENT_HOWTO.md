# How to Add 3D Placements & Interactive Controls to Boxes.py Generators

Boxes.py generators emit flat 2D laser-cut drawings without modifying or knowing about 3D space. The `web/` 3D system reconstructs 3D assemblies **without touching generator code** by recording walls as they are drawn (`web/src/py/boxes_bridge.py`) and mapping them into 3D world space using a small, uniform declarative API (`web/src/py/assembly.py` and `web/src/py/placements.py`).

This guide explains the coordinate conventions, the placement API, how to handle living hinges (flex bends) and polygons, how to add interactive 3D dimensions/editing, and how to verify your placement automatically with `web/scripts/check_assembly.py`.

---

## 1. How the Part Recorder Works

While `box.render()` runs, `boxes_bridge.py` wraps Boxes.py's wall helpers at runtime:
- **Standard wall helpers**: `rectangularWall`, `trapezoidWall`, `trapezoidSideWall`, `rectangularTriangle`, `flangedWall`, `roundedPlate`, `regularPolygonWall`, `polygonWall`.
- **Hand-drawn parts (`helper == "free"`)**: Any part drawn inside `move(..., before=True)` / `move(...)` without a wall helper, or unrecorded closed cut contours on the sheet.

For each recorded `Part` (`assembly.Part`):
- **Local 2D coordinate frame**:
  - `+x` runs along edge 0 (the bottom edge, left to right).
  - `+y` runs perpendicular to edge 0 towards the top edge (bottom to top).
  - The wall's nominal inner rectangle is `[0, x] × [0, y]`.
  - Finger joints (`f`, `F`, `h`, etc.) extend `edge.startWidth()` **outside** `[0, x] × [0, y]`.
- **Attributes on `Part`**:
  - `part.x`, `part.y`: nominal width and height (`float`).
  - `part.label`: the `label="..."` string passed to the wall helper (or `""`).
  - `part.chars`: 4-character string of edge letters (`"fFeF"`, `"?"` for compound edges).
  - `part.callers`: list of qualified function names between `render()` and the helper, innermost first (e.g. `["Lid.__call__"]`, `["_TopEdge.drawLid"]`).
  - `part.mirrored`: `True` if drawn reflected on the sheet (`move="mirror"` or `"upsidedown"`).

---

## 2. World Coordinate System & `Assembly.place()`

- **World coordinates** are in millimetres (`mm`) with **`+X` right**, **`+Y` back (depth)**, and **`+Z` up (height)**.
- A placement maps a part's local `(x, y)` plane to a 3D plane starting at `origin` with unit basis vectors `u` (local `+x`) and `v` (local `+y`), and extrudes the material by thickness `t` along the unit normal `n`:
  $$\text{World}(x, y, z) = \text{origin} + x\,\mathbf{u} + y\,\mathbf{v} + z\,\mathbf{n}, \quad z \in [0, t]$$
- Walls in Boxes.py are drawn **as seen from the outside**, so for an unreflected wall:
  $$\mathbf{u} \times \mathbf{v} = \mathbf{n}$$
   points **outwards** (meaning the wall's inner face lies at $z = 0$ and its material occupies $[0, t]$ outwards).

### `a.place(...)` Signature

```python
a.place(
    part,                  # Part | None (None is safely ignored)
    origin=(x0, y0, z0),   # World position of the corner after rotation/flip
    u=X,                   # Unit vector along the plane's horizontal axis
    v=Z,                   # Unit vector along the plane's vertical axis
    n=neg(Y),              # Unit normal vector along which material is extruded [0, t]
    rot=0,                 # Counter-clockwise rotation in the (u, v) plane: 0, 90, 180, 270
    flip=False,            # Mounts the part inside-out (reflected in local x)
    name="front",          # Fallback display name in the UI when part.label is empty
    thickness=None,        # Override thickness (e.g. acrylic window or paper insert)
    bend=None,             # Living-hinge arc list: [(x0, angle_deg, radius[, stretch]), ...]
)
```

> **Note on `rot` and `flip`:**
> - `rot` rotates the part in the `(u, v)` plane **while keeping the lower-left corner at `origin`**, so the rotated part still spans `[0, w] × [0, h]` along `u` and `v` from `origin`.
> - If a generator drew a part with `move="mirror"` (`part.mirrored == True`), `a.place()` automatically flips it back so its edges stay in their drawn roles. Pass `flip=True` when the physical assembly mounts the part with its back face pointing along `n`.

---

## 3. Step-by-Step Examples

### Example 1: Standard Cuboid Box with `BoxFrame`

For any box built around an inner cuboid cavity of size `x × y × h`, create a `BoxFrame` via `f = a.frame(x, y, h)`:
- The inner cavity is `[0, x] × [0, y] × [0, h]`.
- `f.front()`, `f.back()`, `f.left()`, `f.right()`, `f.bottom()`, `f.top()` place the six outer walls with their inner faces on the cavity boundary and their material `[0, t]` extending **outwards**:

```python
@placement("UniversalBox")
def universal_box(a: Assembly) -> None:
    b = a.box
    f = a.frame(b.x, b.y, b.h)
    f.dims(x="x", y="y", h="h")  # Adds interactive 3D dimensions
    f.front(a.parts.label("front"))
    f.back(a.parts.label("back"))
    f.left(a.parts.label("left"))
    f.right(a.parts.label("right"))
    f.bottom(a.parts.label("bottom"))
    place_lids(a, f, b.top_edge)  # Places both _TopEdge.drawLid and boxes.lids.Lid parts!
```

### Example 2: Querying Unlabelled Parts (`a.parts`)

Every query on `a.parts` (`Parts`) automatically skips parts that have already been placed!
- `a.parts.label("front")` — first unplaced part with `label == "front"`.
- `a.parts.labelled("inner x")` — all unplaced parts whose label starts with `"inner x"`.
- `a.parts.edges("ffff")` — all unplaced parts with those 4 edge characters.
- `a.parts.drawn_by("Lid.__call__")` / `a.parts.not_drawn_by("Lid.__call__")` — filter by call stack.
- `_helper(a.parts, "rectangularTriangle")` — filter by wall helper name.
- `.first()` — returns the first matching `Part` (or `None`). Because `a.place()` marks a part as `.placed = True`, calling `walls.first()` repeatedly in a loop pops each wall in drawing order:

```python
@placement("ABox")
def a_box(a: Assembly) -> None:
    b = a.box
    f = a.frame(b.x, b.y, b.h)
    f.dims(x="x", y="y", h="h")
    own = a.parts.not_drawn_by("Lid.__call__")
    f.bottom(own.edges("ffff").first())
    walls = own.where(lambda p: p.chars != "ffff")
    for face in ("front", "back", "left", "right"):
        getattr(f, face)(walls.first())
    place_lids(a, f, None)
```

### Example 3: Inner Dividers, Shelves & Compartments (`sx`, `sy`, `sh`)

`BoxFrame` provides helpers for internal dividers and horizontal plates, and `positions(sizes, t)` returns the starting coordinate of each wall between sections:
- `f.inner_x(part, y0, rot=0, x0=0, z0=0, flip=False)` — wall parallel to `front`, material in `[y0, y0 + t]`.
- `f.inner_y(part, x0, rot=0, y0=0, z0=0, flip=False)` — wall parallel to `right`, material in `[x0, x0 + t]`.
- `f.plate(part, z0, rot=0, x0=0, y0=0, down=False)` — horizontal shelf with material in `[z0, z0 + t]` (or `[z0 - t, z0]` if `down=True`).

```python
for k, y0 in enumerate(positions(b.sy, t), 1):
    f.inner_x(p.label(f"inner x {k}"), y - y0 - t)
for k, x0 in enumerate(positions(b.sx, t), 1):
    f.inner_y(p.label(f"inner y {k}"), x0, flip=True)
```

### Example 4: Living Hinges & Bent Flex Walls (`bend`)

When a wall has living-hinge sections (`X` edge or flex cuts) that wrap around curved side plates, pass `bend=[(x0, angle_deg, radius, stretch), ...]` to `a.place()`:
- Before `x0`, the part runs straight along `u`.
- Starting at local `x = x0`, the face `z = 0` follows a circular arc of radius `r` through `angle_deg` degrees, turning towards **`-n`** for positive angles (or **`+n`** for negative angles).
- `stretch` (optional, defaults to `1.0`) is the ratio of physical arc length to drawn part length (e.g. `b.edges["X"].settings.stretch`).
- For boxes using `Boxes.surroundingWall` around `roundedPlate`s, simply call the shared helper:
  ```python
  _surrounding_wall(a, origin=(0.0, 0.0, 0.0), x=b.x, y=b.y, r=b.radius, pieces=b.wallpieces)
  ```
- For boxes using `Boxes.polygonWalls` around a `polygonWall` border list, call:
  ```python
  _polygon_walls(a, pieces, borders, origin, h=b.h, bottom=b.bottom_edge)
  ```

### Example 5: Interactive 3D Dimensions & Edit Mode

1. **Standard Frame Dimensions (`x`, `y`, `h`, `sx`, `sy`)**:
   ```python
   f.dims(x="sx", y="-sy", h="h")
   ```
   - Single parameters (`"x"`, `"y"`, `"h"`) draw one editable dimension line.
   - Section list parameters (`"sx"`, `"sy"`) draw a chain of dimension inputs (with `+` split and `×` merge buttons in Edit mode!). Prefixing `"y"` with `"-"` (`"-sy"`) runs the chain from back to front (`y` down to `0`), matching how `TypeTray` and `TrayLayout` index rows.
2. **Draggable Inner Walls (`GridLine`)**:
   ```python
   f.walls("sx", "x", positions(b.sx, t), a.arg("sx"), b.sx, b.hi)
   ```
   Enables dragging inner walls live in the 3D view's Edit mode, snapping to 1 mm or 5 mm increments.
3. **Custom Dimension Lines**:
   ```python
   a.dim("angle_height", a=(0, 0, 0), b=(0, 0, h), out=(-1, 0, 0))
   ```

---

## 4. Automated Verification with `check_assembly.py`

Never rely on visual inspection alone—a wall mounted inside-out or shifted by $1t$ can look plausible at a glance while its fingers clash with its neighbours.

Run the automated geometry checker from the repository root:

```sh
uv run --no-project --with affine --with shapely --with qrcode --with typing_extensions \
    --with numpy python web/scripts/check_assembly.py MyGenerator
```

### What `check_assembly.py` Verifies
1. **Finger-joint gap fill (`fill >= 90%`)**: Along every finger-joint edge (`f`, `F`, `h`, `b`/`B`/`c`/`C`), the gaps between fingers must be occupied by the mating part's fingers.
2. **Finger-joint overlap (`overlap <= 5%`)**: The fingers themselves must not intersect another part's solid body. Composite edges (compound and slotted edges) are checked finger piece by finger piece for fill.
3. **Finger-hole occupancy (`fill >= 90%`)**: Every rectangular slot of width $\approx t$ inside a plate or wall must have a mating wall's fingers inside it.
4. **Coarse 3D body intersection (`<= 1%`)**: No two parts may cut through each other. Each pair of parts is checked once, by index (parts with the same label are still compared).
5. **Unplaced parts warning**: Lists any recorded parts that were left in 2D (`place is None`). (If a cut piece is an offcut rather than a real part, call `a.scrap(part)` so it is omitted from the 3D parts list.)

### Adding Test Cases
In `web/scripts/check_assembly.py`, add non-default parameter combinations to `CASES["MyGenerator"]`—especially **asymmetric `sx`/`sy` lists** (e.g. `{"sx": "30:50:70", "sy": "20:60"}`) and **`outside: "1"` / `"0"`**, which immediately catch walls that are rotated $180^\circ$ or flipped inside-out.

### Known upstream problems (`EXPECTED`)
A problem that comes from the generator itself, not from your placement, goes into `EXPECTED`,
keyed by `(generator, (argument, value))` so it is only ignored in the cases that show it (or
`(generator, None)` for every case). Each pattern is a substring of the reported problem, or a
tuple of substrings that must all be in it. Keep the patterns narrow and add a comment saying why
the problem is upstream's. Finger holes for parts that stay 2D on purpose (hinges, latches,
locks) are listed the same way: an unplaced part does not silence the other finger hole checks.


---

## 5. Parts That Are Not on the Sheet & Editable Grid Cells

### Extra parts (`a.extra`)
`a.extra(label, outline)` creates a part that the generator never drew, e.g. the 3D printed card
ramps of `TypeTray`/`TrayLayout`. `outline` is a polygon in local coordinates (closed for you if the last point is not the first; the part's size is the outline's span). Place it
like any other part and give its extrusion as `thickness=`:

```python
ramp = a.extra("card ramp 1", [(0.0, 0.0), (length, 0.0), (0.0, h)])  # a wedge
a.place(ramp, origin, u, Z, n, thickness=width)
```

Extra parts show up in the parts list (marked "print") and in the STL exports, but not in the
SVG, and clicking them does not highlight anything in the 2D sheet.

### Editor handles (`a.handle`)
`a.handle(kind, i, j, on, lo, hi)` registers a box `lo..hi` that the 3D Edit mode can toggle:
`"hwall"` / `"vwall"` wall pieces and `"floor"` cells at grid position `(i, j)`. `i` and `j` are
indices into the generator's own layout (for `TrayLayout`: the layout text, including 0 mm
rows/columns), not into its internal grid.

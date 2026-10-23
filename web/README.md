# Boxes.py Live (web)

Runs Boxes.py fully in the browser via [Pyodide](https://pyodide.org/) with a live SVG preview.

## Run

Needs Node 20+ and [uv](https://docs.astral.sh/uv/) (or Python with `pip`) to build the wheel.

```sh
cd web
npm install
npm run dev      # builds the boxes wheel, then starts Vite on http://localhost:5173
npm run build    # static site in web/dist/
```

`npm run wheel` rebuilds `public/wheels/` from the repo root. Run it again after changing `boxes/`.

## How it works

- `src/worker.ts` loads Pyodide from the jsDelivr CDN, installs the prebuilt packages
  (`affine`, `shapely`, `numpy`, `typing-extensions`), `qrcode` from PyPI, and the local `boxes` wheel.
  `rectpack`/`svgpathtools` are only used by the CLI's `svgmerge` and are not loaded.
- `src/boxes_bridge.py` turns each generator's argparse definition into a JSON schema
  (the same source `scripts/boxesserver` uses) and renders SVG.
- `src/form.ts` builds the form from that schema. Changes are debounced (150 ms) and rendered
  "latest wins", so stale requests never queue up.
- The current generator and non-default arguments live in the URL hash, so links are shareable.

## 3D assembly view

- While rendering, `boxes_bridge.py` wraps the wall helpers (`rectangularWall`, `trapezoidWall`,
  `trapezoidSideWall`, `rectangularTriangle`, `flangedWall`, `roundedPlate`, `regularPolygonWall`,
  `polygonWall`), `Boxes.cc` and `Surface.transform` at runtime (no changes to `boxes/`) to record
  each wall: size, edges, label, the helper's shape parameters and where it ended up on the sheet. The cut paths are mapped back into the wall's local frame to get its outline and holes.
  It also records which functions drew a wall (e.g. `Lid.__call__`, `_TopEdge.drawLid`), so shared
  lid helpers can be recognised in any generator.
- Placements are computed in Python, right after rendering, so they can read the generator's own
  attributes (`sx`, `top_edge`, lid settings, ...):
  - `src/py/assembly.py`: building blocks. `Assembly.place()` puts a wall on a plane, `BoxFrame`
    has `front/back/left/right/bottom/top`, `inner_x/inner_y` and `plate` for a cuboid inner space,
    and `Parts` queries recorded walls by label, edges or drawing function.
  - `src/py/placements.py`: one small function per generator, plus shared placers for the lids
    from `_TopEdge.drawLid` (top edges f/F/h/Š/Y/E, sliding lid L, hinged lids i/k/v; hinge pins
    stay 2D) and `boxes.lids.Lid` (flat, flatbrim, flatfang, overthetop, ontop). Placed so far:
    ABox, BasedBox, BeeQueenTransportBox, CardBox, ClosedBox, CompartmentBox, DiceBox, DisplayCase,
    DrillBox, ElectronicsBox, GridfinityDrillBox, OpenBox, PenHolderBox, Shadowbox, SlantedTray,
    SlidingDrawer, SlidingLidBox, StorageRack, StorageShelf, TwoPiece, TypeTray, UnevenHeightBox,
    UniversalBox, WallConsole, WallHopper, WallPlaneHolder, WallRack, WallTypeTray,
    WallWrenchHolder.
  - Generators without a function show 2D only; walls a function does not place, or that are not
    drawn through a recorded helper (e.g. ElectronicsBox corner triangles, CompartmentBox's
    one-piece lip), are listed as "2D".
- `src/view3d.ts` (Three.js, loaded lazily) extrudes the outlines by the material thickness.
  Clicking a part in either view, or in the parts list, selects it everywhere. The parts list can
  hide single parts in 3D (kept while you edit parameters, reset when you switch generators).

### Checking placements

`scripts/check_assembly.py` renders each placed generator (defaults plus extra cases) in CPython and
checks the assembly: at every finger joint (f/F/h, and the b/B/c/C wall-mount joints with the plain
wall type) the gaps of one part must be filled by another part's fingers, and no two parts may cut
into each other. Edges follow the real part shape (slanted trapezoid tops, triangle hypotenuses,
polygonWall sides); composite edges are only checked for overlap. Generators that are drawn with
uneven sections (`sx`/`sy`) are checked with asymmetric values, which catches parts mounted the
wrong side out. Run it from the repo root after changing a placement:

    uv run --no-project --with affine --with shapely --with qrcode --with typing_extensions \
        --with numpy python web/scripts/check_assembly.py [Generator ...]

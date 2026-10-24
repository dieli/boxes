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
  Paths that miss closing by less than 0.5 mm are closed (e.g. DinRailBox's rail edge is a bit
  short).
  It also records which functions drew a wall (e.g. `Lid.__call__`, `_TopEdge.drawLid`), so shared
  lid helpers can be recognised in any generator.
- Parts drawn by hand are recorded too: every `move()` outside a wall helper is a "free" part
  (local frame = its move box), and cuts in SVG parts nobody recorded become free parts with
  their bounding box as frame. A part whose cuts are split by a nested helper's `move()` is
  merged back together. Pieces that are offcuts rather than parts can be `scrap()`ped.
- Placements are computed in Python, right after rendering, so they can read the generator's own
  attributes (`sx`, `top_edge`, lid settings, ...):
  - `src/py/assembly.py`: building blocks. `Assembly.place()` puts a wall on a plane (optionally
    with its own thickness, e.g. acrylic inserts, or bent along flex sections), `BoxFrame`
    has `front/back/left/right/bottom/top`, `inner_x/inner_y` and `plate` for a cuboid inner space,
    and `Parts` queries recorded walls by label, edges or drawing function.
  - `src/py/placements.py`: one small function per generator, plus shared placers for the lids
    from `_TopEdge.drawLid` (top edges f/F/h/Š/Y/E, sliding lid L, hinged lids i/k/v; hinge pins
    stay 2D), `boxes.lids.Lid` (flat, flatbrim, flatfang, overthetop, ontop) and
    `Boxes.surroundingWall` around `roundedPlate`s (any number of wall pieces), and
    `Boxes.polygonWalls` around a `polygonWall` (straight pieces with angled finger joints, rounded
    corners as flex bends, in any plane). Placed so far (105): ABox, AirPurifier, AngledBox,
    BasedBox, BeeQueenTransportBox, BinTray, BirdHouse, BookHolder, BrickSorter, CardBox,
    CardHolder, ClosedBox, CoffeeCapsuleHolder, Coffin, CoinBankSafe, CoinDisplay, CompartmentBox,
    Console, Crate, Desksign, DiceBox, DiceTower, DinRailBox, DiscRack, Dispenser, Display,
    DisplayCase, DisplayShelf, DividerTray, DoubleFlexDoorBox, DrillBox, DrillStand, ElectronicsBox,
    EuroRackSkiff, FlexBox, FlexBox2, FlexBox3, FlexBox4, FlexBox5, GridfinityBase,
    GridfinityDrillBox, GridfinityTrayLayout, HalfBox, HeartBox, HingeBox, HobbyCase,
    IntegratedHingeBox, KeyHolder, Keypad, MagazineFile, MakitaPowerSupply, Matrix, NightLightBox,
    NotesHolder, OpenBox, PaintStorage, PenHolderBox, PhotoFrame, Rack10Box, Rack19Box,
    Rack19HalfWidth, RackBox, RegularBox, RegularStarBox, RollHolder, RoundedBox, RoundedRegularBox,
    RoundedTrapezoidBox, SBCMicroRack, Shadowbox, SlantedTray, SlidingDrawer, SlidingLidBox,
    SmallPartsTray, SmallPartsTray2, SpicesRack, StackableBin, StorageRack, StorageShelf, Tetris,
    TrafficLight, TrayInsert, TrayLayout, TwoPiece, TypeTray, UBox, UnevenHeightBox, UniversalBox,
    WallCaliper, WallChiselHolder, WallConsole, WallDrillBox, WallHook, WallHopper, WallPinRow,
    WallPlaneHolder, WallPliersHolder, WallRack, WallRollHolder, WallSlottedHolder,
    WallStackableBin, WallStairs, WallTypeTray, WallWrenchHolder, WineRack.
  - Pieces of an assembly that stand upside down or turned (e.g. DiceTower's tray, the upper
    half of RegularStarBox) are placed through `_Moved`, which runs a `BoxFrame` (or plain
    `place` calls) through a rigid motion.
  - Parts' own thickness: `place(..., thickness=)` is also used for layers that are not sheet
    material (PhotoFrame's photo and matting, Matrix's plexiglass).
  - GridfinityTrayLayout shares TrayLayout's placement but has no Edit handles (its layout
    follows the Gridfinity grid).
  - Generators without a function get a flat 3D view: every recorded part extruded and laid out
    as on the sheet, seen from above (no explode, no Edit). Only generators that record no parts
    at all show the "3D view not implemented yet" note. Walls a function does not place, or that are not
    drawn through a recorded helper (e.g. ElectronicsBox corner triangles, CompartmentBox's
    one-piece lip), are listed as "2D".
- `src/view3d.ts` (Three.js, loaded lazily) extrudes the outlines by the material thickness.
  Flex walls carry a bend path (`[x0, angle, r, stretch]` per arc, see `src/bend.ts`): the flat
  extrusion is sliced across the arcs and wrapped around them, so the living hinge follows the
  rounded sides it is fitted to.
  Clicking a part in either view, or in the parts list, selects it everywhere. The parts list can
  hide single parts in 3D (kept while you edit parameters, reset when you switch generators).
- TrayLayout: its `layout` text starts as the full `sx` x `sy` grid and follows them until you
  edit it by hand (`src/layout.ts`, like the server UI's JavaScript); a layout that is still the
  default is left out of the URL. Without a layout, the bridge does the same in Python, since
  there is no layout file to fall back to in the browser.
- Editable dimensions: a placement function can declare which parameters a dimension line shows
  (`BoxFrame.dims(x="x", y="y", h="h")`, list parameters like `sx` give one line per compartment,
  `"-sy"` runs back to front; `Assembly.dim()` for anything else). The 3D view draws them with
  an input on each label: Enter applies, arrow keys step by 1 mm (Shift: 10). The value goes into
  the form field, so the SVG is still made by Boxes.py from parameters only. With `outside` the
  lines span the outer size. Hidden in the exploded view and switchable with "Dimensions".
  TrayLayout's column/row sizes live in its layout text: their lines (`x[k]`, `y[k]`) rewrite
  just that number in the layout (`setLayoutSize` in `src/layout.ts`).
  So far: ABox, BasedBox, ClosedBox, CompartmentBox, DiceBox, ElectronicsBox, OpenBox,
  PenHolderBox, SlantedTray, SlidingLidBox, TrayLayout, TypeTray, UnevenHeightBox (x/y),
  UniversalBox.
- Undo/redo (toolbar, Ctrl+Z, Ctrl+Y / Ctrl+Shift+Z) over all parameter changes, per generator.
  Quick repeated changes to the same parameter or dimension (typing, arrow keys) are one step;
  form text fields keep their own native undo while focused.
- View/Edit switch in the 3D panel. In Edit mode (assembled view only), clicking a wall piece
  removes it, clicking its green ghost puts it back, and clicking a floor cell toggles the floor.
  Each click is one undo step. The placement map reports the toggleable things with
  `Assembly.handle(kind, i, j, on, lo, hi)`; the click rewrites one character of the layout text
  (`toggleLayout` in `src/layout.ts`). Only TrayLayout so far.
- Also in Edit mode, compartment sizes (sx/sy, TrayLayout's columns/rows) get "+" (split in two,
  adding a wall) and "×" (merge with the next one, or the previous for the last), keeping the total
  size: without `outside` the wall's thickness comes out of / goes back into the sizes. TrayLayout
  changes its layout text (`splitLayout`/`mergeLayout`: parsed into a grid and written back in
  TrayLayoutFile's format; a split adds a full wall, a merge keeps walls/floors of either side).
  Generators with neither handles nor compartment lists keep Edit disabled.
- TypeTray's Edit mode has "Convert to TrayLayout": same grid (sx, sy, h, hi) and the shared
  settings, so single wall pieces and floors can be removed. Browser Back returns to the TypeTray.
- TrayLayout has TypeTray's `fingerholes` option (and the `FingerHoleEdge` settings): a notch per
  compartment in the walls along x, outer front/back walls optional. This is a change in
  `boxes/generators/traylayout.py` (default `none` draws the same as before), so it carries over
  when converting a TypeTray.
- Also in Edit mode, inner walls (TypeTray, TrayLayout) can be dragged: the two compartments on
  either side change, their sum stays. The walls on that grid line move live in 3D (a tip shows
  both sizes); Boxes.py re-renders on release. The compartment before the wall snaps to 1 or 5 mm
  ("Snap", kept in localStorage), Shift drags freely, Esc cancels. A click without moving still
  toggles a TrayLayout wall piece. The placement map reports the lines with `BoxFrame.walls()`
  (wall slab, drag direction, and the parameter-per-mm scale that "outside" introduces).
- `hi` (inner wall height, 0 = same as `h`) has its own dimension on the first inner wall
  (TypeTray, TrayLayout), e.g. for low inserts under a rulebook.
- Dimension labels that would overlap on screen (narrow compartments) are moved down a row.

### Checking placements

`scripts/check_assembly.py` renders each placed generator (defaults plus extra cases) in CPython and
checks the assembly: at every finger joint (f/F/h, and the b/B/c/C wall-mount joints with the plain
wall type, and square finger joints a generator defines under other letters) the gaps of one part
must be filled by another part's fingers, finger holes must be filled, and no two parts may cut
into each other. A letter that is a finger joint elsewhere but a
generator's own edge (e.g. KeyHolder's hook rail `H`) is not checked as one. Known upstream
inconsistencies are listed in `EXPECTED`, per generator and argument value (or `None` for every
case). Bent flex walls are modelled exactly (arcs and straight pieces). Parts drawn by
hand have no edge information, so for them only finger holes and overlaps are checked. Edges follow the real part shape (slanted trapezoid tops, triangle hypotenuses,
polygonWall sides); composite edges are only checked for overlap. Generators that are drawn with
uneven sections (`sx`/`sy`) are checked with asymmetric values, which catches parts mounted the
wrong side out. Run it from the repo root after changing a placement:

    uv run --no-project --with affine --with shapely --with qrcode --with typing_extensions \
        --with numpy python web/scripts/check_assembly.py [Generator ...]

# Boxes.py Live (web)

Runs Boxes.py fully in the browser via [Pyodide](https://pyodide.org/) with a live SVG preview.

Experimental and largely written with AI assistants; see [How this was made](#how-this-was-made)
and [Testing](#testing).

## Run

Needs Node 22.2+ (the wheel script uses `zlib.crc32`). No Python is needed to build or run the app.

```sh
cd web
npm install
npm run dev      # builds the boxes wheel and copies the Pyodide core, then starts Vite on http://localhost:5173
npm run build    # typecheck and static site in web/dist/
npm run preview  # serves web/dist/ on http://localhost:4173
```

- `npm run wheel` writes the `boxes` wheel straight from the git-tracked `boxes/**/*.py` files
  (no setup.py, deterministic zip) to `public/wheels/<content hash>/`, plus a manifest the app
  reads. Run it again after changing `boxes/`; `dev` and `build` do it for you. The hash in the
  path means a browser never keeps an old wheel from its cache.
- `npm run pyodide` copies the Pyodide core (runtime, standard library, `pyodide-lock.json`)
  from `node_modules/pyodide` into `public/pyodide/` (git-ignored), so the app serves it itself.
- The build also writes `THIRD_PARTY_LICENSES.txt` (licenses of the bundled JavaScript) next to
  the app.

## How it works

- `src/worker.ts` runs Pyodide in a Web Worker, so the page never blocks. The Pyodide core comes
  from the app itself; the prebuilt packages (`affine`, `shapely`, `numpy`, `typing-extensions`)
  come from jsDelivr for the same Pyodide version and are checked against the sha256 in the
  served lock file. `qrcode` (pinned) comes from PyPI through `micropip`, then the local `boxes`
  wheel. `rectpack`/`svgpathtools` are only used by the CLI's `svgmerge` and are not loaded.
- `src/boxesClient.ts` owns the worker. A request that runs longer than 30 s (counted from when
  the worker gets to it, not while it waits behind another one), or a worker that crashes, rejects
  the open requests and starts a fresh Python (a few seconds); the status line says so. A worker
  that fails while loading is not restarted: the error is shown, and after a failed restart the
  status line says to reload the page.
- Every SVG from Python goes through an allowlist sanitizer (`src/svg.ts`) before it is put into
  the page: only drawing elements are kept, event handler attributes, external links and
  `javascript:` values are dropped. Parameters come from shareable URLs, so the SVG is treated as
  untrusted.
- Renders are numbered; a slow render that finishes after a newer one is never shown over it, and
  the 3D view always belongs to the SVG on screen. Download first renders an edit that is still
  in its debounce, so the file matches the preview; while the preview shows an error, Download is
  disabled. Switching generator drops an edit still in its debounce.
- `src/boxes_bridge.py` turns each generator's argparse definition into a JSON schema
  (the same source `scripts/boxesserver` uses) and renders SVG.
- `src/form.ts` builds the form from that schema. Changes are debounced (150 ms) and rendered
  "latest wins", so stale requests never queue up.
- Generator search filter over names and descriptions (Down arrow moves into the list, Enter loads
  the selected generator).
- The toolbar displays the 2D sheet bounding box (`W × H mm`) alongside render timing.
- The current generator and non-default arguments live in the URL hash, so links are shareable.
  This is also the only way to keep a design for now: bookmark the URL to come back and edit it.
  A select value in a link that no longer exists falls back to the default (or the first option)
  instead of breaking the form.

## Export

- **SVG** is the preview itself. **LightBurn (.lbrn2)**, **PostScript** and **SVG Ponoko** are
  rendered again by Boxes.py with `--format`. DXF, G-code and PLT need `pstoedit`, which is not
  available in the browser, so they are not offered.
- Downloads are rendered again rather than saving the preview: the bridge joins the path
  fragments Boxes leaves behind (parts drawn piece by piece, e.g. TrayLayout's base plate) into
  one continuous path per contour (`_join_paths`). Same cuts, fewer jumps, and cutter software
  like Falcon Design Space imports them correctly.
- **SVG (each part, .zip)**: one SVG per part, moved to the origin and named after the part
  (`render_parts` in `boxes_bridge.py`). For cutter software that drops a file's groups, so each
  import is one part with its holes and labels, to be arranged freely.
- **STL** (for 3D printing the parts instead of cutting them) is made from a separate render with
  `burn` = 0: the laser's kerf compensation would make printed parts too large. Instead every
  part is shrunk by half the **print clearance** (default 0.15 mm, kept in localStorage) on each
  side, so each joint gets that much play in total (`print_parts` in `boxes_bridge.py`, a shapely
  inset of the outlines). The settings are:
  - *3D assembly*: the parts that are shown in 3D, at their assembled positions (flex walls bent).
  - *each part flat, .zip*: one STL per part, lying flat on the bed (z = 0..thickness), unbent.
  - *single part*: one of these. The part selected in 2D or 3D is preselected.

  Only the outline and holes are extruded. Engravings and the flex-hinge cuts (which are lines,
  not areas) are not in the STL. STL code lives in `src/stl.ts` (loaded on demand).

## 3D assembly view

See [3D_PLACEMENT_HOWTO.md](3D_PLACEMENT_HOWTO.md) for a step-by-step tutorial on writing and
verifying 3D placements for new generators.

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
    corners as flex bends, in any plane). Placed so far (118): ABox, AirPurifier, AngledBox,
    BasedBox, BayonetBox, BeeQueenTransportBox, BinTray, BirdHouse, BookHolder, BottleStack,
    BreadBox, BrickSorter, CardBox, CardHolder, ClosedBox, CoffeeCapsuleHolder, Coffin, CoinBankSafe,
    CoinDisplay, CompartmentBox, Console, Crate, Desksign, DiceBox, DiceTower, DinRailBox, DiscRack,
    Dispenser, Display, DisplayCase, DisplayShelf, DividerTray, DoubleFlexDoorBox, DrillBox,
    DrillStand, ElectronicsBox, EuroRackSkiff, FatBallDispenser, FilamentSpool, FlexBook, FlexBox, FlexBox2, FlexBox3, FlexBox4,
    FlexBox5, GridfinityBase, GridfinityDrillBox, GridfinityTrayLayout, HalfBox, HeartBox, HingeBox,
    HobbyCase, IntegratedHingeBox, KeyHolder, Keypad, LaptopStand, MagazineFile, MakitaPowerSupply,
    Matrix, NightLightBox, NotesHolder, OpenBox, OrganPipe, PaintStorage, PenHolderBox, PhoneHolder,
    PhotoFrame, Rack10Box, Rack19Box, Rack19HalfWidth, RackBox, Ramp, RegularBox, RegularStarBox,
    RollHolder, RoundedBox, RoundedRegularBox, RoundedTrapezoidBox, SBCMicroRack, Shadowbox, ShutterBox, SkadisStand,
    SlantedTray, SlidingDrawer, SlidingLidBox, SmallPartsTray, SmallPartsTray2, SpicesRack,
    StackableBin, StorageRack, StorageShelf, Tetris, TrafficLight, TrayInsert, TrayLayout,
    TriangleLamp, TwoPiece, TypeTray, UBox, UnevenHeightBox, UniversalBox, WallCaliper,
    WallChiselHolder, WallConsole, WallDrillBox, WallHook, WallHopper, WallPinRow, WallPlaneHolder,
    WallPliersHolder, WallRack, WallRollHolder, WallSlottedHolder, WallStackableBin, WallStairs,
    WallTypeTray, WallWrenchHolder, WineRack.
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
  hide single parts in 3D (kept while you edit parameters, reset when you switch generators);
  hidden parts are also left out of the STL assembly export.
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
  Each click is one undo step. A typed edit that is still waiting for its debounce is recorded
  before an undo, so Ctrl+Z never skips it. The placement map reports the toggleable things with
  `Assembly.handle(kind, i, j, on, lo, hi)`; the click rewrites one character of the layout text
  (`toggleLayout` in `src/layout.ts`). Only TrayLayout so far.
- Also in Edit mode, compartment sizes (sx/sy, TrayLayout's columns/rows) get "+" (split in two,
  adding a wall) and "×" (merge with the next one, or the previous for the last), keeping the total
  size: without `outside` the wall's thickness comes out of / goes back into the sizes. TrayLayout
  changes its layout text (`splitLayout`/`mergeLayout`: parsed into a grid and written back in
  TrayLayoutFile's format; a split adds a full wall, a merge keeps walls/floors of either side).
  Generators with neither handles nor compartment lists keep Edit disabled.
- Everything the 3D editor does can also be done in the form (the size fields, TrayLayout's
  layout text), which works with the keyboard. Parts list entries take focus; Enter or Space
  selects one.
- TypeTray's Edit mode has "Convert to TrayLayout": same grid (sx, sy, h, hi) and the shared
  settings, so single wall pieces and floors can be removed. Browser Back returns to the TypeTray.
- TrayLayout has TypeTray's `fingerholes` option (and the `FingerHoleEdge` settings): a notch per
  compartment in the walls along x, outer front/back walls optional. This is a change in
  `boxes/generators/traylayout.py` (default `none` draws the same as before), so it carries over
  when converting a TypeTray.
- TrayLayout also has a `sliding` lid style (`TrayLid` in `boxes/generators/traylayout.py`, not
  offered by other generators): the front wall is one thickness lower and the back wall one higher,
  so a two-layer lid slides in from the front over the lowered wall; the lower layer's tab locks
  into finger holes in the back wall (following gaps in the back wall). The back wall gets no
  finger hole notch, it would cut the lock. Optional magnet holes (`Lid_magnet_diameter`) in the lower
  layer sit right behind the front wall in the front corners, for magnets glued to the inside of
  the front wall (top flush with it) to hold the closed lid; holes that do not fit raise an error. Without a handle the top layer gets a grip slot;
  a handle is cut through both layers. TrayLayout plugs these in through a small generic hook in
  core: `Boxes.lid_settings_class` / `Boxes.lid_class` (default `None` = the usual `LidSettings`
  / `Lid`), so other generators keep the core lid.
- TrayLayout: a size of 0 mm for the first or last row or column makes a liner, a second wall
  glued flat to the outer wall. It is a plain plate (no finger joints, no holes for it in the
  floor or side walls), as high as the inner walls and with their finger hole notch. Inner walls
  meeting it run through to the outer wall, so the liner is split between them and they hold it
  in place; back/front liners run into the corners, left/right ones end at them. Liners need a
  floor in front of them. Core change in `boxes/generators/traylayout.py`
  (`TrayLayout.removeZeroSizes()` takes the 0 mm rows/columns out of the grid before drawing,
  `liners()` draws the plates; labels keep the layout text's numbering). 0 mm anywhere else is an
  error. A liner's finger hole notch follows its outer wall: the front/back liner is notched when
  that outer wall is (`fingerholes`), left/right liners never are. No dimension lines or handles
  are drawn for 0 mm rows and columns. Removing the outer wall piece behind a liner removes the
  liner there and keeps the outer wall: the 0 mm row folds its two walls into the outer one, so
  the layout's outer line stands for both (by design, see `TrayLayout.lines()`). In Edit mode the first and last compartment can be dragged or typed down to 0.
- TypeTray and TrayLayout have a "Card ramps (3D print)" group (web only, not in core): a wedge
  per compartment, leaning against the chosen wall (`ramp_side`) and rising from the floor at
  `ramp_angle` up to `ramp_height` (capped by the wall height and compartment length), so cards
  slide up and out. `ramp_height=auto` (the default) ends the ramp at the bottom of the finger
  hole in that wall (wall height minus the `FingerHoleEdge` depth), so a card on the ramp can be
  gripped through the hole; walls without a finger hole get 15 mm. TrayLayout compartments along that wall with no wall between them share one
  ramp; compartments without a floor or without that wall get none. The ramps are extra parts
  (`Assembly.extra`, helper `printed`, negative `part` index) placed by `placements._card_ramps`:
  shown in 3D and the parts list, included in the STL exports (shortened by the print clearance
  to fit between the walls), never in the 2D sheet or SVG downloads. A ramp value that cannot be
  used (e.g. a height of 0 or text) is shown as a warning next to the 3D view and the ramps are
  left out; the 2D sheet still renders. Links from before `ramp_height=auto` existed now get
  auto unless they set a number.
- Also in Edit mode, inner walls (TypeTray, TrayLayout) can be dragged: the two compartments on
  either side change, their sum stays. The walls on that grid line move live in 3D (a tip shows
  both sizes); Boxes.py re-renders on release. The compartment before the wall snaps to 1 or 5 mm
  ("Snap", kept in localStorage), Shift drags freely, Esc cancels. A click without moving still
  toggles a TrayLayout wall piece. The placement map reports the lines with `BoxFrame.walls()`
  (wall slab, drag direction, and the parameter-per-mm scale that "outside" introduces).
- `hi` (inner wall height, 0 = same as `h`) has its own dimension on the first inner wall
  (TypeTray, TrayLayout), e.g. for low inserts under a rulebook. With a flat lid, its lower layer
  sits one thickness inside the box: keep `hi` at most `h - thickness`, otherwise the 3D view
  rests the lid on the inner walls and it does not close flush. With `hi > h`, TrayLayout notches
  each wall by its own height; TypeTray (upstream) still notches the outer walls by `hi`.
- Dimension labels that would overlap on screen (narrow compartments) are moved down a row.

## How this was made

This fork was largely "vibe coded": most of the code in `web/` and the TrayLayout changes in
`boxes/generators/traylayout.py` were written by AI assistants, Claude Code (Claude Opus) and
Google Gemini, under my direction. I set the goals and the design, decided between the
options the assistants offered, and tested the results in the browser and in cutting software.
I did not write most of the code by hand.

To make up for that:

- The code is reviewed by two independent AI reviewers (Claude and Gemini) with the same brief,
  covering correctness, safety, performance, readability, coding style, maintainability, error
  handling, tests, accessibility and licensing ([docs/review/REVIEW_BRIEF.md](docs/review/REVIEW_BRIEF.md)).
  Every finding is checked against the code before it is fixed, and the findings and decisions
  are kept in `docs/review/`. *Status:* one round done (units U1–U5, both reviewers); every
  finding is fixed or deferred with a reason in [docs/review/TRIAGE.md](docs/review/TRIAGE.md).
  A second round checks the fixes ([docs/review/ROUND2_PROMPT.md](docs/review/ROUND2_PROMPT.md)).
- Changes are covered by automated checks (below) and were tested by hand.
- Core changes are kept small so they can be offered upstream, where they would get a human
  review.

Treat it as experimental. Check the parts in the 2D view and the 3D assembly before cutting
expensive material, and report problems in this fork, not to upstream Boxes.py.

The steps still open before publishing are in [docs/PUBLISHING_PLAN.md](docs/PUBLISHING_PLAN.md).

## Testing

All of these run on every push and pull request (`.github/workflows/web.yml`), except upstream's
own `tests/`, which upstream's workflow runs. Commands are for the repo root unless they say
`web/`.

| Suite | What it covers | Command |
|---|---|---|
| Unit tests (Vitest, 62) | `layout.ts` (parse, toggle, split, merge, sizes), `zip.ts` (and part names), `bend.ts`, `stl.ts`, the SVG sanitizer, select fallback, the worker client (timeouts per running request, crashes, restarts and failed restarts, latest-wins renders) | `web/`: `npm test` |
| Typecheck | all of `web/src` | `web/`: `npm run typecheck` (also part of `npm run build`) |
| Bridge tests (pytest, 30) | `boxes_bridge.py` and the placements: path joining, pieces, `ignore_widths`, composite edge pieces, ramp validation and warnings, argument filtering (option names, non-finite numbers), print clearance, TrayLayout handles, extra parts | `uv run --no-project --with affine --with shapely --with qrcode --with typing_extensions --with numpy --with pytest python -m pytest web/tests/py -q` |
| Core tests (pytest) | upstream's tests and reference SVGs, plus this fork's `tests/test_traylayout_options.py` (25: notch depth per wall, outer walls per `fingerholes`, liners, size errors, the sliding lid (walls, layers, back wall gaps, handles, magnets, low walls), the lid class hook), `tests/test_typetray.py` (2: `back_height`) and `tests/test_part_counts.py` (11: SpicesRack supports, WineRack walls) | same, plus `--with lxml --with markdown --with setuptools --with pyyaml`, on `tests` (244 passed, 9 skipped). The three fork test files also run in `web.yml` |
| Assembly checker | `scripts/check_assembly.py`, see below: all placed generators, defaults plus extra cases | see below (about 10 min) |
| Browser tests (21) | the built app in Edge or Chrome, see below | `web/`: `npm run test:e2e` |

### Checking placements

`scripts/check_assembly.py` renders each placed generator (defaults plus extra cases) in CPython and
checks the assembly: at every finger joint (f/F/h, and the b/B/c/C wall-mount joints with the plain
wall type, and square finger joints a generator defines under other letters) the gaps of one part
must be filled by another part's fingers, finger holes must be filled, and no two parts may cut
into each other. Each pair of parts is checked once by index. A letter that is a finger joint
elsewhere but a generator's own edge (e.g. KeyHolder's hook rail `H`) is not checked as one.
Known upstream inconsistencies are listed in `EXPECTED`, keyed by generator, argument and value
(or `None` for every case). Every part must be placed: an unplaced part
(`unplaced (2D only): <label>`, or `#N (WxH)` without a label) and every placement warning fail
the run unless the part is marked `a.scrap(part)` (an offcut) or listed in `EXPECTED` with the
reason (hinges, latches, locks that stay 2D on purpose, with their finger holes). Bent flex walls are
modelled exactly (arcs and straight pieces). Parts drawn by hand have no edge information, so
for them only finger holes and overlaps are checked. Edges follow the real part shape (slanted
trapezoid tops, triangle hypotenuses, polygonWall sides); each finger piece of a composite edge
is checked for fill. Generators that are drawn with uneven sections (`sx`/`sy`) are checked with
asymmetric values, which catches parts mounted the wrong side out. Run it after changing a
placement:

    uv run --no-project --with affine --with shapely --with qrcode --with typing_extensions         --with numpy python web/scripts/check_assembly.py [Generator ...]

### Browser tests

`tests/e2e` drives the built app through `playwright-core` with an installed browser: Microsoft
Edge, or Chrome if Edge does not start (`BROWSER_CHANNEL=chrome` picks one). Build, start the
preview server, then run them in `web/`:

    npm run build
    npm run preview          # in a second terminal, serves http://localhost:4173/
    npm run test:e2e         # BASE_URL=... for another server

They cover the exports (SVG, per-part SVG zip, STL assembly/zip/single part), the card ramps and
TrayLayout liners (from the URL and from the 3D editor), malformed and invalid URL values, a bad
ramp value (a warning, 2D still renders), edits within the debounce (undo, switching generator,
no download after a failed render), linked help texts and the Phase 1 timing target: the median re-render of
ABox, ClosedBox, UniversalBox and TypeTray must stay under `PERF_LIMIT_MS` (300 ms by default,
1000 on CI runners). Every test waits for the app's render counter instead of fixed sleeps and
fails on any console error, a shown render error or a failed 3D placement (except the one that
renders a bad value on purpose).

### By hand

| What | Result |
|---|---|
| TrayLayout in the browser: fingerholes, sliding lid with and without magnets, liners on each side and combined, card ramps on each side, `outside` on and off, missing floors and walls | all fine |
| Per-part SVG zip imported into Creality Falcon Design Space | imports correctly |

Not tested yet:

- No part of this fork has been laser cut or 3D printed yet: not the liners, the sliding lid or
  the card ramps.
- LightBurn import, browsers other than Edge and Chrome, phone-sized screens.
- The CI workflow has not run on GitHub yet (nothing is pushed).

"""Checks the 3D placements: do finger joints close, and do parts not cut into each other?

For every placed part and every finger-type edge, points are sampled in the strip just
outside the part's inner rectangle (where its fingers and the gaps between them are),
at mid thickness:
  - gap points (not in the part) should be filled by another part  -> "fill"
  - finger points (in the part) should not be inside another part   -> "overlap"
Finger holes (holes about t wide) must be filled by another part as well, which also covers
parts drawn by hand without edge info ("free" parts).
Additionally a coarse grid over each part checks for parts cutting into each other.

Run from the repo root (CPython, needs numpy and shapely):
    uv run --no-project --with affine --with shapely --with qrcode --with typing_extensions \
        --with numpy python web/scripts/check_assembly.py [Generator ...]
"""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "web" / "src" / "py")]

import numpy as np  # noqa: E402
from shapely import Polygon, contains_xy  # noqa: E402

import boxes_bridge  # noqa: E402
from assembly import Part  # noqa: E402
from placements import PLACEMENTS  # noqa: E402

# Extra argument sets per generator (defaults are always checked).
# Walls removed (a T crossing, an open side) and a compartment without floor.
_LAYOUT = """ ,> 40mm
 | ,> 60mm
 | | ,> 30mm
+-+-+-+
| | | |  50mm
+-+ +-+
| |   |  30mm
+-+-+ +
| |X| |  40mm
+-+-+-+
"""

# A gap in the back wall (sliding lid: the back finger holes follow the wall's runs).
_BACK_GAP = """ ,> 40mm
 | ,> 60mm
 | | ,> 30mm
+-+ +-+
| | | |  50mm
+-+-+-+
| | | |  40mm
+-+-+-+
"""

# 0 mm edge rows/columns: liners glued to the outer walls (back and left; front and right
# with a gap in the front liner, a compartment without floor and an inner wall ending at it).
_LINER_BL = """ ,> 0mm
 | ,> 50mm
 | | ,> 40mm
+-+-+-+
| | | |  0mm
+-+-+-+
| | | |  60mm
+-+-+-+
| |   |  30mm
+-+-+-+
"""
_LINER_FR = """ ,> 40mm
 | ,> 60mm
 | | ,> 30mm
 | | | ,> 0mm
+-+-+-+-+
| | | | |  50mm
+-+ +-+-+
| |   | |  30mm
+-+-+-+-+
| |X| | |  40mm
+-+ +-+-+
| | | | |  0mm
+-+-+-+-+
"""

CASES: dict[str, list[dict]] = {
    "DisplayShelf": [{"sx": "100:150:80"}, {"angle": "-20"}, {"include_back": "1", "include_front": "1", "include_bottom": "1"}, {"front_wall_height": "0"}, {"divider_wall_height": "40"}, {"slope_top": "1"}],
    "FlexBook": [{"recess_wall": "1"}, {"x": "60", "y": "50", "h": "100", "latchsize": "6"}],
    "SkadisStand": [{"foot_front": "60"}, {"angle": "90", "connectors": "2:4:6", "foot_front": "40"}],
    "FatBallDispenser": [{"sides": "5"}, {"sides": "8", "balcony_height": "0"}, {"balcony_height": "35", "roof_height": "60"}],
    "BreadBox": [{"radius": "30"}, {"x": "250", "h": "140", "radius": "60"}],
    "ShutterBox": [{"style": "double"}, {"h": "70", "radius": "35"}, {"style": "double", "h": "160", "y": "200"}],
    "BayonetBox": [{"lugs": "6"}, {"diameter": "120", "outside": "0"}],
    "BottleStack": [{"double": "0"}, {"number": "5", "diameter": "60"}],
    "LaptopStand": [{"angle": "8"}, {"l_depth": "300", "angle": "20"}],
    "OrganPipe": [{"pitch": "a", "octave": "4"}],
    "FilamentSpool": [{"sides": "5"}, {"sides": "12", "h": "70"}],
    "PhoneHolder": [{"angle": "15"}, {"angle": "35", "phone_width": "90"}],
    "Ramp": [{"n": "2"}, {"n": "3", "h": "40", "y": "120"}],
    "TriangleLamp": [{"sharpcorners": "1"}, {"x": "150", "cornersize": "20"}],
    "BirdHouse": [{"x":"150","y":"120","h":"100","roof_overhang":"0.2"}],
    "CoinDisplay": [{"outside":"0"},{"angle":"45","coin_plate":"40"}],
    "Display": [{"angle":"10"}],
    "BookHolder": [{"ledge_height":"20"},{"angle":"60","back_support":"0","radius":"5"}],
    "DiceTower": [{"bottom":"0","tray_height":"0"},{"ramps":"4","angle":"40"},{"ramps":"2"}],
    "Desksign": [{"feet":"1","mirror":"1"},{"angle":"45","height":"60"}],
    "DoubleFlexDoorBox": [{"radius":"30"},{"x":"150","h":"60"}],
    "Tetris": [{"shape":"T"},{"shape":"S"},{"shape":"I"},{"shape":"O"}],
    "Console": [{"front_height":"0"},{"angle":"30","h":"60"},{"y":"50","h":"120"}],
    "HeartBox": [{"top":"lid"},{"top":"hole","x":"80"}],
    "RoundedTrapezoidBox": [{"x_back":"40","wall_pieces":"4"},{"top":"lid","radius_back_left":"0"},{"top":"closed","wall_pieces":"1"}],
    "Coffin": [{"x":"150","h":"40"},{"cross":"0","width":"0.5"}],
    "RoundedRegularBox": [{"sides":"6","wallpieces":"2"},{"top":"lid"},{"top":"closed","radius":"5"},{"sides":"3","wallpieces":"1"}],
    "RegularStarBox": [{"n":"3"},{"n":"4","h":"30"},{"outside":"1"}],
    "RegularBox": [{"n":"4"},{"n":"6","radius_top":"35"},{"radius_top":"70","top":"closed"},{"top":"round lid","bottom":"angled lid"},{"top":"angled lid2","bottom":"hole"},{"top":"angled hole","n":"3"}],
    "AngledBox": [{"n":"4"},{"n":"2","top":"angled lid"},{"top":"angled lid2"},{"top":"angled hole","n":"1"},{"x":"60","y":"90"},{"bottom_edge":"e"}],
    "CoffeeCapsuleHolder": [{"backplate": "off"}],
    "AirPurifier": [{"split_frames": "off"}, {"filters": "1"}, {"filters": "1", "split_frames": "off", "fan_diameter": "120"}],
    "MakitaPowerSupply": [{"secondary_power": "none"}],
    "PhotoFrame": [{"split_front": "off"}, {"x": "130", "y": "90"}],
    "TrafficLight": [{"n": "2"}, {"upright": "off"}, {"back_edge": "h"}, {"back_edge": "e"}],
    "Matrix": [{"h": "50"}],
    "Dispenser": [{"x": "80", "y": "120"}, {"bottomheight": "40", "sideedges": "h"}, {"viewingwidth": "0"}],
    "HalfBox": [{"sy": "30:60"}, {"Sturdy": "on", "sy": "30:60"}, {"Sturdy": "on", "sy": "50"}],
    "CoinBankSafe": [{"x": "120", "y": "90"}],
    "RollHolder": [{"one_piece": "off"}, {"height": "40", "axle": "30"}],
    "KeyHolder": [{"num_hooks": "3", "mounting": "1"}],
    "DinRailBox": [{"rail_offset": "10"}, {"x": "120", "y": "60", "rail_width": "15"}],
    "WineRack": [{"walls": "minimal"}, {"walls": "no_verticals"}, {"y": "400"}, {"y": "400", "walls": "minimal"}],
    "SpicesRack": [{"numx": "3", "numy": "2"}, {"feet": "1"}, {"in_place_supports": "on"}, {"in_place_supports": "on", "feet": "1"}],
    "HobbyCase": [{"unit_w": "150:215:100", "shelves_n": "1:3:0", "rows": "4"}, {"inset_shelves": "0"}, {"add_rails": "off", "add_cover": "0"}],
    "SmallPartsTray": [{"sx": "30:50:40"}, {"two_sided": "0"}, {"two_sided": "0", "front_panel": "off"}, {"front_panel": "0"}, {"angle": "30", "rampheight": "0.3"}, {"outside": "0"}],
    "GridfinityTrayLayout": [{"nx": "1", "ny": "3"}, {"stacking": "1", "h": "3u"}, {"countx": "0", "county": "0"}],
    "DividerTray": [{"sx": "30:50:40", "sy": "20:60:40"}, {"Slot_angle": "0"}, {"left_wall": "0"}, {"bottom": "1"}, {"bottom": "1", "handle": "1"}, {"outside": "1", "bottom": "1"}, {"sy": "0:40:50:0"}],
    "TrayInsert": [{"sx": "30:50:40", "sy": "20:60"}, {"x": "200", "y": "130"}, {"draft_angle": "5"}],
    "GridfinityBase": [{"bottom_edge": "e"}, {"h": "0"}, {"Lid_style": "flat"}, {"Lid_style": "flatbrim"}],
    "SmallPartsTray2": [{"sx": "30:50:40", "sy": "60:40:50"}, {"back_height": "20"}, {"hi": "20"}, {"outside": "1"}],
    "PaintStorage": [{"drawer": "1"}, {"additional_bottom": "1", "additional_top": "1"}],
    "SBCMicroRack": [{"sbcs": "3"}, {"switch": "1"}],
    "CardHolder": [{"sx": "50:80:60"}, {"angle": "15"}, {"outside": "1"}],
    "DiscRack": [{"sx": "15*5:25*4"}, {"angle": "30"}],
    "HingeBox": [{"splitlid": "30"}, {"outside": "1"}, {"lidheight": "35"}],
    "IntegratedHingeBox": [{"outside": "1"}, {"lidheight": "30", "x": "120"}],
    # top2 1.2: a layer boundary at 1.5 mm would sit right on a fill sample (0.5 t).
    "Keypad": [{"top2_enable": "1", "top2_thickness": "1.2"}, {"h": "50"}],
    "NotesHolder": [{"sx": "40:70:30"}, {"opening": "10"}, {"sx": "40:70:30", "back_openings": "1"}, {"bottom_edge": "f"}],
    "BrickSorter": [{"level": "bottom"}],
    "RackBox": [{"outside": "1"}, {"x": "150", "y": "80", "h": "60"}],
    "Crate": [{"MakeStackable": "0"}, {"x": "150", "y": "220"}],
    "StackableBin": [{"sx": "40:70:30"}, {"outside": "1"}, {"front": "0.6"}],
    "BinTray": [{"sx": "40:70:30", "sh": "30:60:45"}, {"outside": "1"}],
    "Rack19HalfWidth": [{"ru_count": "2", "z": "40"}],
    "TwoPiece": [{"hi": "30"}, {"outside": "1"}, {"play": "0.3"}],
    "SlidingDrawer": [{"hi": "20"}, {"outside": "1"}, {"play": "0.3"}],
    "PenHolderBox": [{"bottom_edge": "h"}, {"plate_gap": "40"}],
    "ElectronicsBox": [{"outsidemounts": "0"}, {"outside": "1"}],
    "DisplayCase": [{"overhang": "5"}, {"outside": "1"}],
    "StorageRack": [{"sh": "40:60:30"}, {"bottom_edge": "e"}, {"top_edge": "e"},
                    {"top_edge": "h"}],
    "SlantedTray": [{"sx": "30:50:20"}, {"front_height": "0.6"}],
    "OpenBox": [{"edgetype": "h"}, {"outside": "1"}],
    "UnevenHeightBox": [{"height0": "30", "height1": "60", "height2": "90", "height3": "40"},
                        {"add_lid": "0"}, {"lid_height": "10"}, {"bottom_edge": "h"}],
    "SlidingLidBox": [{"lid_type": "lip"}, {"lid_type": "none"}, {"bottom_edge": "h"},
                      {"outside": "1"}],
    "WallRack": [{"sh": "80:120"}, {"side_edges": "h"}, {"outside": "1"}, {"top_edge": "E"}],
    "CompartmentBox": [{"sx": "30:50:20", "sy": "20:40"}, {"handle": "hole"}, {"handle": "none"},
                       {"bottom_edge": "F"}],
    "WallHopper": [{"sx": "40:80:30"}, {"label": "0"}, {"slope_angle": "10", "h": "120"}],
    "WallConsole": [{"sx": "40:80:30"}, {"top_depth": "30", "bottom_depth": "60"},
                    {"walltype": "slatwall"}],
    "WallHook": [{"width": "30", "hook_inside_diameter": "30", "hook_thickness": "15"}],
    "WallCaliper": [{"width": "25", "height": "10"}],
    "WallChiselHolder": [{"holediameter": "20"}, {"holediameter": "20", "hooks": "odds"},
                         {"number": "5", "tooldiameter": "40"}],
    "WallSlottedHolder": [{"hooks": "everythird"}, {"slot_depth": "60"}],
    "WallStairs": [{"sx": "60:90:40", "sy": "30:50:40", "sh": "20:60:150"}, {"braceheight": "0"}],
    "WallPinRow": [{"angle": "0"}, {"angle": "35", "hooks": "4"}, {"h": "80", "pins": "5"},
                   {"walltype": "slatwall"}],
    "WallPliersHolder": [{"sx": "60:100:80", "angle": "30"}, {"outside": "0"}],
    "WallRollHolder": [{"width": "200", "diameter": "100", "height": "120", "axle": "30"}],
    # sh must increase front to back (the inner walls are as high as the row behind them).
    "DrillStand": [{"sx": "25*3", "sy": "10:20", "sh": "25:40"}, {"extra_height": "0"},
                   {"sx": "20:40:30", "sy": "30:15:20:25", "sh": "20:30:30:70"}],
    "WallDrillBox": [{"sx": "25*3", "sy": "10:20", "sh": "25:40"}, {"extra_height": "30"},
                     {"sx": "20:40:30", "sy": "30:15:20:25", "sh": "20:30:30:70"}],
    "MagazineFile": [{"x": "80", "y": "150", "h": "120", "hi": "100"}, {"h": "200", "hi": "40"},
                     {"top_edge": "G"}],
    "FlexBox2": [{"y": "40", "radius": "25"}, {"h": "50", "latchsize": "3"}],
    "FlexBox4": [{"y": "40", "radius": "25"}, {"h": "50", "latchsize": "3"}],
    "FlexBox5": [{"top_diameter": "40", "bottom_diameter": "70"}, {"top_diameter": "80", "x": "100"}],
    "UBox": [{"top_edge": "f"}, {"top_edge": "i"}, {"top_edge": "k"}, {"y": "40", "radius": "25"}, {"top_edge": "L"}],
    "RoundedBox": [{"wallpieces": "2"}, {"wallpieces": "3", "sh": "40:50"}, {"wallpieces": "4", "top": "lid"},
                   {"edge_style": "F"}, {"edge_style": "h"}, {"y": "30", "radius": "15"},
                   {"x": "150", "y": "60", "radius": "20", "top": "closed"}],
    "FlexBox3": [{"h": "20", "radius": "10"}, {"h": "8", "radius": "20"}, {"c": "3"}],
    "FlexBox": [{"sx": "40:60:30"}, {"y": "40", "radius": "25"}, {"h": "40", "latchsize": "3"},
                {"sx": "50:50", "outside": "0"}],
    "NightLightBox": [{"BoxStyle": "minimalist"}, {"BoxStyle": "extra customizable face"},
                      {"WoodPlatesCount": "1", "WoodPlateThickness": "3", "InterPlateSpacing": "20"},
                      {"hooks": "1", "Margin": "1"}],
    "WallStackableBin": [{"sx": "40:60:30", "angle": "45"}, {"label": "0"},
                         {"Stackable_bottom_stabilizers": "0", "front": "0.5"}, {"walltype": "slatwall"}],
    "WallWrenchHolder": [{"x": "150", "depth": "50"}],
    "WallPlaneHolder": [{"length": "200", "hold_length": "50"}],
    "WallTypeTray": [{"sx": "30:50", "sy": "20:40:30"}, {"back_height": "30"},
                     {"back_height": "30", "all_mounts": "1"}, {"hi": "30"},
                     {"walltype": "french cleat"}],
    "StorageShelf": [{"sy": "30:50", "sh": "40:60:30"}, {"bottom_edge": "F", "top_edge": "f"},
                     {"retainer": "15", "sh": "40:60"}, {"top_edge": "E"}],
    "Shadowbox": [{"layers": "3"}, {"back_edge": "f"}, {"back_edge": "E"}, {"back_edge": "h"},
                  {"casejoinery": "0"}],
    "ABox": [{"bottom_edge": "F"}, {"Lid_style": "flat"}, {"Lid_style": "flatbrim"},
             {"Lid_style": "overthetop"}, {"Lid_style": "ontop"}, {"x": "150", "y": "80"},
             {"Lid_style": "flat", "Lid_handle": "long_trapezoid"}, {"Lid_style": "flat", "Lid_handle": "knob"},
             {"Lid_style": "ontop", "Lid_handle": "long_doublerounded"},
             {"Lid_style": "overthetop", "Lid_handle": "knob"}],
    "UniversalBox": [{"top_edge": "f"}, {"top_edge": "F"}, {"top_edge": "E"},
                     {"top_edge": "L"}, {"top_edge": "i"}, {"top_edge": "k"}, {"top_edge": "v"},
                     {"vertical_edges": "finger holes"}, {"bottom_edge": "h"},
                     {"Lid_style": "flatfang"}, {"Lid_style": "overthetop"}],
    "TypeTray": [{"sx": "30:50:70", "sy": "20:60"}, {"top_edge": "f"}, {"bottom_edge": "e"},
                 {"ramp": "1"}, {"ramp": "1", "ramp_side": "left", "hi": "15", "ramp_height": "40"},
                 {"back_height": "20"}, {"back_height": "20", "sx": "30:50", "sy": "20:60:40"},
                 {"back_height": "20", "ramp": "1", "ramp_side": "back"}, {"handle": "1"},
                 {"top_edge": "f", "Lid_style": "overthetop"}, {"Lid_style": "flat"},
                 {"Lid_style": "flat", "ramp": "1"}],
    "TrayLayout": [{"sx": "30:50:70", "sy": "20:60"}, {"outside": "0", "hi": "40"},
                   {"hi": "120"}, {"layout": _LAYOUT}, {"layout": _LAYOUT, "outside": "0"},
                   {"Lid_style": "flat"}, {"Lid_style": "overthetop"},
                   {"Lid_style": "sliding"}, {"Lid_style": "sliding", "outside": "0", "Lid_magnet_diameter": "6"},
                   {"fingerholes": "front-and-back", "sx": "30:50:70"}, {"fingerholes": "inside-only", "layout": _LAYOUT},
                   {"fingerholes": "front", "hi": "40", "FingerHoleEdge_relative_depth": "0.5"},
                   *({"ramp": "1", "ramp_side": s, "layout": _LAYOUT} for s in ("front", "back", "left", "right")),
                   {"ramp": "1", "ramp_angle": "20", "hi": "10"},
                   {"layout": _LINER_BL}, {"layout": _LINER_BL, "outside": "0", "fingerholes": "inside-only"},
                   {"layout": _LINER_FR}, {"layout": _LINER_FR, "Lid_style": "sliding", "hi": "40"},
                   *({"layout": l, "ramp": "1", "ramp_side": s} for l in (_LINER_BL, _LINER_FR)
                     for s in ("front", "back", "left", "right")),
                   # Inner walls higher than the outer ones, with finger holes (U1-G-01).
                   {"h": "40", "hi": "80", "fingerholes": "front-and-back"},
                   # Flat lid on inner walls as high as the outer ones (N-05).
                   {"Lid_style": "flat", "h": "30"}, {"Lid_style": "flat", "h": "30", "hi": "20"},
                   # Sliding lid with finger holes, a handle, magnets, an open back, low walls.
                   {"Lid_style": "sliding", "fingerholes": "front-and-back"},
                   {"Lid_style": "sliding", "fingerholes": "back", "ramp": "1", "ramp_side": "back"},
                   {"Lid_style": "sliding", "Lid_handle": "long_rounded"},
                   {"Lid_style": "sliding", "Lid_magnet_diameter": "6", "Lid_handle": "knob"},
                   {"Lid_style": "flat", "Lid_handle": "knob", "hi": "40"},
                   {"Lid_style": "sliding", "layout": _BACK_GAP},
                   {"Lid_style": "sliding", "ramp": "1", "h": "20"},
                   {"Lid_style": "sliding", "ramp": "1", "ramp_side": "front", "h": "20",
                    "fingerholes": "front"}],
    "ClosedBox": [{"x": "60", "y": "120", "h": "40"}],
    "CardBox": [{"openingdirection": "right"}, {"sx": "40:65", "add_lidtopper": "1"}],
    "DiceBox": [{"lidheight": "25"}],
    "BasedBox": [{"top_edge": "f"}, {"top_edge": "E"}, {"Lid_style": "overthetop"}],
    "DrillBox": [{"bottom_edge": "F"}, {"sh": "5:25:10:20"}, {"Lid_style": "flat"}],
    "GridfinityDrillBox": [{"sh": "5:10:30"}, {"Lid_style": "ontop"}],
    "BeeQueenTransportBox": [{"bottom_edge": "F"}, {"sh": "12:30:40"}],
}

# Finger holes of the hinges of the v (ChestHinge) top edge with the default x, in the back
# wall and the lid top.
_HINGE_HOLES = tuple(f"finger hole at {x}," for x in
                     ("6.2", "12.4", "18.8", "72.2", "78.5", "84.8", "9.3", "15.6", "75.4", "81.7"))

# Parts the placement map leaves out (see "unplaced" in check()): by label, or any unlabelled one.
_2D = "unplaced (2D only): "
_2D_UNLABELLED = _2D + "#"

# Problems that come from upstream's design, per generator and argument value.
# A pattern is a substring of the problem, or a tuple of substrings that must all be in it.
EXPECTED = {  # (generator, (argument, value) or None for every case): problems to ignore
    # Front and face have three peg holes, but only two pegs are drawn.
    ("NightLightBox", ("BoxStyle", "extra customizable face")): ("front finger hole", "customizable face finger hole"),
    # The inner vertical walls list sh bottom to top on their back edge (SlottedEdge(self.sh)),
    # the back plate and their own front edge top to bottom: uneven rows miss the holes.
    ("BinTray", ("sh", "30:60:45")): ("back finger hole", "inner vertical"),
    # With back_height the front wall is h high (holes too), the sides' front edge and the
    # inner walls only hi - t*sqrt(2): it sticks out and its upper holes stay empty.
    # One-sided without front panel: the sides get a plain bottom edge, the floor's finger
    # joints to them have nothing to go into.
    ("SmallPartsTray", ("front_panel", "off")): ("edge 1 'f'", "edge 3 'f'", "edge 3 '?'"),
    # The back rail is 8 t shorter than the shelf's finger hole line in the back: its end holes
    # stay empty (any case). Without rails, slots without shelves are empty.
    ("HobbyCase", None): (("base plate", "finger hole", "fill 0%"),),
    ("HobbyCase", ("add_rails", "off")): (("finger hole", "fill 0%"),),
    # Supports cut inside the shelves' can holes are recorded as part of the shelf.
    ("SpicesRack", ("in_place_supports", "on")): (("(325x", "finger hole", "fill 0%"),),
    # The slot for the latch (2D) in the rail holder cuts through its middle finger.
    ("DinRailBox", None): ("(70x8) finger hole", "Back finger hole at 32.0", _2D_UNLABELLED),  # latch
    ("SmallPartsTray2", ("back_height", "20")): (
        "front finger hole", "front edge 1 'f'", "front edge 3 'f'", "front cuts into slope",
        "side edge 1 'h'", "side finger hole", ("inner y", "edge 1 '?'")),
    # Without Sturdy the outer supports stand flush with the bottom's edges: their finger holes
    # touch the outline and become notches.
    ("HalfBox", None): ("bottom cuts into support",),
    # even n leaning inwards: the corner jogs of the G edges graze the neighbour wall (~1%)
    ("RegularBox", ("radius_top", "35")): ("cuts into",),
    # sharpcorners: the walls are lengthened for a 22.5 degree bevel ground on by hand
    ("TriangleLamp", ("sharpcorners", "1")): ("cuts into",),
    # The door is cut for pi r / 2 at the outer radius, longer than its closed path: with its
    # end on the floor, the handle at its start runs into the fixed top.
    ("BreadBox", None): ("cuts into #7 (6x",),
    # The balcony walls are cut to their outer length; their ends are mitred by hand along the
    # etched lines, so plain slabs overlap at the corners.
    ("FatBallDispenser", None): ("x23) cuts into #",),
    ("FatBallDispenser", ("balcony_height", "35")): ("x38) cuts into #",),
    # Without a back, the inner horizontal walls still have finger joints there.
    ("TrafficLight", ("back_edge", "e")): ("edge 0 'f'",),
    # Upstream: the inner frames' bottom edge is F but the bottom has finger holes (fit f), their
    # top edge and the top's are both f, and the bottom's front/back fingers meet the outer
    # frames' plain (E) bottom edge. The outer frames' top finger holes hold nothing.
    ("AirPurifier", None): ("top edge", "bottom edge", "bottom finger hole", "edge 0 'F'",
                            "edge 2 'f'", "edge 2 'h'", "x30) finger hole", "x493) finger hole",
                            "(498x30) cuts into bottom", "(498x30) cuts into top"),
    # Parts drawn in 2D only (see "unplaced"): the finger holes they go into stay empty.
    # Hinges of the v top edge (HingeBox: its default lid).
    ("HingeBox", None): _HINGE_HOLES + (_2D + "hinges",),
    ("UniversalBox", ("top_edge", "v")): _HINGE_HOLES + (_2D + "hinges",),
    # The latch parts on the cover's end and the back (latch brackets and pin).
    ("FlexBook", None): (("#1 (", "finger hole"), ("#3 (", "finger hole"), _2D_UNLABELLED),
    # The lock parts in the door (dials, pins and handle).
    ("CoinBankSafe", None): (("#5 (", "finger hole"), _2D_UNLABELLED),
    # Parts drawn in 2D only by design (the placement's docstring says which).
    ("DividerTray", None): (_2D_UNLABELLED,),  # single dividers, alternatives to the full one
    ("GridfinityDrillBox", None): (_2D_UNLABELLED,),  # small feet glued under the bottom
    ("MakitaPowerSupply", None): (_2D_UNLABELLED,),  # the rails' inner plates
    ("PaintStorage", None): (_2D_UNLABELLED,),  # strips
    ("RollHolder", None): (_2D_UNLABELLED,),  # axle rings
    ("WallRollHolder", None): (_2D_UNLABELLED,),  # axle rings
    ("TrafficLight", None): (_2D + "colored windows",),
    # Known gaps: parts the placement map does not place yet (to be fixed, then removed here).
    ("Crate", ("MakeStackable", "0")): (_2D_UNLABELLED,),  # 4 strips, 6 wide
    ("GridfinityTrayLayout", ("ny", "3")): (_2D_UNLABELLED,),  # one 36x36 pad
    ("SBCMicroRack", ("switch", "1")): (_2D_UNLABELLED,),  # a 170.5x63 plate
    ("SmallPartsTray", None): (_2D_UNLABELLED,),  # 3 squares of 10.6x10.6
    ("SpicesRack", ("feet", "1")): (_2D_UNLABELLED,),  # 4 feet
    ("StackableBin", None): (_2D + "for label (optional)",),
    ("UBox", ("top_edge", "i")): (_2D + "wall",),
    ("UBox", ("top_edge", "k")): (_2D + "wall",),
    ("WineRack", ("walls", "minimal")): (_2D_UNLABELLED,),  # 8 plates of 54.8x210
}

# Generators whose default arguments are degenerate upstream; only CASES are checked.
SKIP_DEFAULTS = {
    # holediameter == tooldiameter: the tool holes meet at the braces, which then sit on the
    # plate's edges and in the holes (d = min(2t, (wt - rt) / 4) = 0).
    "WallChiselHolder": "braces have no plate to sit on with the default sizes",
}

FILL_MIN = 0.9
OVERLAP_MAX = 0.05
FINGER_EDGES = set("fFhH")
# Generators may define finger joints under other chars (FlexBox3's g/G); square ones only.
FINGER_TYPES = {"FingerJointEdge", "FingerJointEdgeCounterPart", "FingerHoleEdge"}
# Wall mount joints (b/B fingers, c/C slots; edge classes Wall*) are plain finger joints with the
# plain wall type. Other generators use b/B for their own edges.
WALL_EDGES = set("bBcC")


class BendPath:
    """Exact model of a flex part's bend path (Placement.bend, mirrors web/src/bend.ts)."""

    def __init__(self, bends) -> None:
        # Pieces: (x0, x1, k, P, T) with k = 0 for straight pieces; N = (-T[1], T[0]).
        self.pieces = []
        P, T, x = np.zeros(2), np.array([1.0, 0.0]), 0.0
        # Arcs: k is the turn per part length, the radius 1/|k| * s (s: stretch).
        for x0, angle, r, *s in sorted(bends):
            s = s[0] if s else 1.0
            P = self._straight(x, x0, P, T)
            k, x1 = np.sign(angle) * s / r, x0 + r * np.radians(abs(angle)) / s
            self.pieces.append((x0, x1, k, P, T, s))
            P, T = self._arc(P, T, k, s, x1 - x0)
            x = x1
        self.pieces.append((x, np.inf, 0.0, P, T, 1.0))

    def _straight(self, x0, x1, P, T):
        if x1 > x0:
            self.pieces.append((x0, x1, 0.0, P, T, 1.0))
        return P + T * (x1 - x0)

    @staticmethod
    def _arc(P, T, k, st, l):
        N = np.array([-T[1], T[0]])
        c, s = np.cos(k * l), np.sin(k * l)
        return P + (T * s + N * (c - 1)) * st / k, T * c - N * s

    def map(self, x, z):
        """(x, z) -> bent (x, z) for arrays; x before 0 extends the first piece."""
        out = np.zeros((len(x), 2))
        for i, (x0, x1, k, P, T, st) in enumerate(self.pieces):
            sel = (x >= x0 if i else np.ones(len(x), bool)) & (x < x1)
            l = x[sel] - x0
            if k == 0:
                Pl, Tl = P + np.outer(l, T), np.tile(T, (len(l), 1))
            else:
                N = np.array([-T[1], T[0]])
                c, s = np.cos(k * l)[:, None], np.sin(k * l)[:, None]
                Pl, Tl = P + (T * s + N * (c - 1)) * st / k, T * c - N * s
            Nl = np.column_stack([-Tl[:, 1], Tl[:, 0]])
            out[sel] = Pl + Nl * z[sel, None]
        return out

    def inverse(self, X, Z, t):
        """Bent (X, Z) -> list of candidate unbent (x, z, valid) per piece."""
        d0 = np.column_stack([X, Z])
        for x0, x1, k, P, T, st in self.pieces:
            N = np.array([-T[1], T[0]])
            if k == 0:
                d = d0 - P
                l, z = d @ T, d @ N
            else:
                d = d0 - (P - N * st / k)
                s = np.sign(k) * np.hypot(d[:, 0], d[:, 1])
                z = s - st / k
                with np.errstate(invalid="ignore", divide="ignore"):
                    l = np.arctan2((d @ T) / s, (d @ N) / s) / k
            yield x0 + l, z, (l >= -1e-6) & (x0 + l <= x1 + 1e-6)


def part_name(rec: dict) -> str:
    return rec["label"] or f"#{rec['part']} ({rec['x']:g}x{rec['y']:g})"


class Solid:
    def __init__(self, rec: dict, t: float) -> None:
        o = rec["outline"]
        self.rec = rec
        self.name = part_name(rec)
        self.poly = Polygon(o["outer"], o["holes"])
        p = rec["place"]
        self.o = np.array(p["origin"], float)
        self.R = np.column_stack([p["ux"], p["uy"], p["n"]]).astype(float)
        self.Rinv = np.linalg.inv(self.R)
        self.t = p.get("t", t)
        self.bend = BendPath(p["bend"]) if p.get("bend") else None

    def world(self, x, y, z):
        x, y, z = (np.asarray(c, float) for c in (x, y, z))
        if self.bend is not None:
            b = self.bend.map(x, z)
            x, z = b[:, 0], b[:, 1]
        return self.o + np.column_stack([x, y, z]) @ self.R.T

    def contains(self, w) -> np.ndarray:
        local = (w - self.o) @ self.Rinv.T
        eps = 0.05 * self.t
        if self.bend is None:
            inz = (local[:, 2] > eps) & (local[:, 2] < self.t - eps)
            return inz & contains_xy(self.poly, local[:, 0], local[:, 1])
        out = np.zeros(len(w), bool)
        for x, z, ok in self.bend.inverse(local[:, 0], local[:, 2], self.t):
            ok = ok & (z > eps) & (z < self.t - eps)
            if ok.any():
                out[ok] |= contains_xy(self.poly, x[ok], local[ok, 1])
        return out


def segments(rec: dict) -> list[tuple[np.ndarray, np.ndarray, float]]:
    """(start, direction, length) of each edge, counter-clockwise, in local coordinates."""
    return [(np.array(p0), np.array(d), length) for p0, d, length in Part(0, rec).segments()]


def edge_band(s: Solid, i: int, step: float = 0.25, span: tuple[float, float] | None = None):
    """Local sample points in the joint strip of width t along edge i (corners excluded), or
    along span (start, end) of it: one piece of a composite edge."""
    t = s.t
    segs = segments(s.rec)
    if i >= len(segs):
        return None
    p0, d, length = segs[i]
    a0, a1 = span or (0.0, length)
    # Corners are trimmed by ignore_widths etc.; half-step phase keeps samples off finger boundaries.
    along = np.arange(a0 + 2 * t + step / 2, a1 - 2 * t, step)
    if along.size == 0:
        return None
    ccw = sum(q[0] * dq[1] * l - q[1] * dq[0] * l for q, dq, l in segs) > 0  # shoelace
    out = np.array([d[1], -d[0]]) * (1 if ccw else -1)
    dist = np.array([0.2, 0.5, 0.8]) * t
    if s.rec["helper"] == "polygonWall":
        # Edges are drawn right on the polygon line (not startWidth outside it like in
        # rectangularWall): F slots go inwards, f fingers outwards.
        dist = dist - s.rec["edges"][i]["startWidth"]
    a, dd = np.meshgrid(along, dist)
    pts = p0 + np.outer(a.ravel(), d) + np.outer(dd.ravel(), out)
    return pts[:, 0], pts[:, 1]


def finger_hole(hole, t: float):
    """Sample points along the middle of an axis-aligned rectangular hole about t wide."""
    if len(hole) > 6:  # rounded slot (air holes etc.)
        return None
    xs, ys = [q[0] for q in hole], [q[1] for q in hole]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    if abs(min(w, h) - t) > 0.15 * t or max(w, h) < 0.9 * t:
        return None
    if abs(Polygon(hole).area - w * h) > 0.02 * w * h:  # not an axis-aligned rectangle
        return None
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    m = 0.2 * min(w, h)
    if w >= h:
        along = np.linspace(min(xs) + m, max(xs) - m, 5)
        return along, np.full_like(along, cy)
    along = np.linspace(min(ys) + m, max(ys) - m, 5)
    return np.full_like(along, cx), along


def finger_edge(e: dict, args: dict) -> bool:
    """Is edge (or composite edge piece) e a finger joint whose gaps another part fills?"""
    # A letter of FINGER_EDGES a generator uses for its own edge (KeyHolder's H hook).
    own = e.get("type") and e["type"] not in FINGER_TYPES
    return ((e["char"] in FINGER_EDGES and not own)
            or (e.get("type") in FINGER_TYPES and e.get("angle") == 90)
            or (e["char"] in WALL_EDGES and (e.get("type") or "").startswith("Wall")
                and args.get("walltype", "plain") == "plain"))


def check(name: str, args: dict) -> list[str]:
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            r = json.loads(boxes_bridge.render_with_parts(name, json.dumps({"burn": "0", **args})))
    except Exception as e:
        return [f"render failed: {type(e).__name__}: {str(e).splitlines()[-1] if str(e) else ''}"]
    problems = []
    if r["assembly"] is not True:
        return [f"assembly: {r['assembly']}"]
    t = r["thickness"]
    problems += [f"warning: {w}" for w in r["warnings"]]
    problems += [f"unplaced (2D only): {part_name(p)}" for p in r["parts"] if not p["place"]]
    solids = [Solid(p, t) for p in r["parts"] if p["place"] and p["outline"]]
    # Coarse body check: fraction of a's area inside b, for every ordered pair (a, b).
    cut: dict[tuple[int, int], float] = {}
    for ia, a in enumerate(solids):
        others = [b for b in solids if b is not a]

        def hit(w):
            return np.any([b.contains(w) for b in others], axis=0) if others else np.zeros(len(w), bool)

        inner, outer = a.poly.buffer(-0.05), a.poly.buffer(0.05)
        for i, e in enumerate(a.rec["edges"]):
            # Composite edges (slotted, compound, ...): their finger pieces are checked one by
            # one; overlap is checked over the whole edge.
            pieces = e.get("pieces")
            composite = e["char"] is None
            if composite:
                fill_spans = [(q["start"], q["start"] + q["length"]) for q in pieces or ()
                              if finger_edge(q, args) and q["startWidth"] == e["startWidth"]]
            elif finger_edge(e, args):
                fill_spans = [None]
            else:
                continue
            band = edge_band(a, i)
            if band is None:
                continue
            x, y = band
            # Points right on the outline (finger boundaries) count as neither.
            ina = contains_xy(inner, x, y)
            filled = hit(a.world(x, y, np.full_like(x, a.t / 2)))
            overlap = filled[ina].mean() if ina.any() else 0.0
            fill = 1.0
            for span in fill_spans:
                band = edge_band(a, i, span=span) if span else (x, y)
                if band is None:
                    continue
                px, py = band
                gaps = ~contains_xy(outer, px, py)
                if gaps.any():
                    fill = min(fill, hit(a.world(px[gaps], py[gaps], np.full(gaps.sum(), a.t / 2))).mean())
            if fill < FILL_MIN or overlap > OVERLAP_MAX:
                problems.append(f"{a.name} edge {i} '{e['char'] or '?'}': fill {fill:.0%}, overlap {overlap:.0%}")
        for hole in a.rec["outline"]["holes"]:
            band = finger_hole(hole, t)
            if band is None:
                continue
            x, y = band
            fill = hit(a.world(x, y, np.full_like(x, a.t / 2))).mean()
            if fill < FILL_MIN:
                xs, ys = [q[0] for q in hole], [q[1] for q in hole]
                problems.append(f"{a.name} finger hole at {min(xs):.1f},{min(ys):.1f}: fill {fill:.0%}")
        # Coarse body check: parts cutting into each other.
        minx, miny, maxx, maxy = a.poly.bounds
        step = max(1.0, min(maxx - minx, maxy - miny) / 25)
        gx, gy = np.meshgrid(np.arange(minx, maxx, step), np.arange(miny, maxy, step))
        gx, gy = gx.ravel(), gy.ravel()
        keep = contains_xy(a.poly, gx, gy)
        w = a.world(gx[keep], gy[keep], np.full(keep.sum(), a.t / 2))
        for ib, b in enumerate(solids):
            if b is not a:
                cut[ia, ib] = b.contains(w).mean() if len(w) else 0.0
    # Each pair once, but checked both ways: a small part inside a large one covers little of
    # the large one's area.
    for (ia, ib), frac in cut.items():
        if ia > ib:
            continue
        a, b = solids[ia], solids[ib]
        if frac > 0.01:
            problems.append(f"{a.name} cuts into {b.name}: {frac:.0%} of its area")
        elif cut[ib, ia] > 0.01:
            problems.append(f"{b.name} cuts into {a.name}: {cut[ib, ia]:.0%} of its area")
    return problems


def expected(name: str, args: dict) -> tuple:
    """Problems to ignore for this case (see EXPECTED)."""
    return sum((v for (n, kv), v in EXPECTED.items()
                if n == name and (kv is None or args.get(kv[0]) == kv[1])), ())


def main(names: list[str]) -> int:
    failed = 0
    for name in names or sorted(PLACEMENTS):
        for args in ([] if name in SKIP_DEFAULTS else [{}]) + CASES.get(name, []):
            problems = check(name, args)
            soft = expected(name, args)
            hard = [p for p in problems
                    if not any(all(q in p for q in s) if isinstance(s, tuple) else s in p for s in soft)]
            failed += bool(hard)
            print(f"{'FAIL' if hard else 'ok  '} {name} {args or ''}")
            for p in problems:
                print(f"       {p}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""
Real per-controller-type hotspot layouts for the vector controller diagrams — every coordinate here
was measured directly off the real SVG artwork in assets/controllers/ (see svg_path.py), not
eyeballed: extracted programmatically as the centroid of each button's own distinctly-colored glyph
path (e.g. Xbox's blue "X" glyph, fill #009cd3) or, where a shape has no unique color (the D-pad),
identified from the raw SVG source and confirmed by its real position. All coordinates are in each
SVG's own post-transform unit space (i.e. exactly what svg_path.load_svg_shapes() returns), so a
hotspot drawn at a layout coordinate always lines up with the real artwork underneath it.

Neither source SVG includes real shoulder-button (LB/RB/LT/RT) glyphs — both are simple front-facing
icon art with no separate bumper/trigger shapes. Rather than invent button art that doesn't exist in
the source, each controller gets two synthetic "bracket pointer" hotspots (like a printed manual's
"see here" marks) at the top-left/top-right, each covering BOTH the bumper and trigger on that side —
clicking one lets the user choose which of the two to manage, the same two-step pattern already used
for a stick's X/Y axes in controller_tab.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

_ASSETS_DIR = Path(__file__).parent / "assets" / "controllers"


@dataclass
class Hotspot:
    slot_id: str
    center: tuple      # (x, y) in the SVG's own unit space
    radius: float


@dataclass
class ControllerLayout:
    key: str                    # "xbox" / "playstation"
    display_name: str
    svg_path: Path
    hotspots: list = field(default_factory=list)     # list[Hotspot]
    bracket_left: tuple = (0, 0)     # (x, y) anchor for the left shoulder bracket pointer
    bracket_right: tuple = (0, 0)    # (x, y) anchor for the right shoulder bracket pointer
    bbox: tuple = (0, 0, 0, 0)       # (minx, miny, maxx, maxy) — the real SVG bounding box


XBOX = ControllerLayout(
    key="xbox", display_name="Xbox", svg_path=_ASSETS_DIR / "xbox.svg",
    bbox=(10.8, 10.2, 196.9, 139.4),
    bracket_left=(20, 8), bracket_right=(188, 8),
    hotspots=[
        Hotspot("face_west", (139.4, 45.6), 9),
        Hotspot("face_north", (151.7, 31.4), 9),
        Hotspot("face_east", (167.6, 45.2), 9),
        Hotspot("face_south", (152.1, 59.3), 9),
        Hotspot("l_stick", (55.7, 45.5), 13.8),
        Hotspot("r_stick", (128.5, 74.0), 13.8),
        Hotspot("menu_select", (90.1, 43.6), 6),
        Hotspot("menu_start", (117.6, 43.6), 6),
        Hotspot("dpad_up", (79.1, 67.0), 7),
        Hotspot("dpad_down", (79.1, 84.0), 7),
        Hotspot("dpad_left", (70.5, 75.5), 7),
        Hotspot("dpad_right", (87.5, 75.5), 7),
    ],
)

PLAYSTATION = ControllerLayout(
    key="playstation", display_name="PlayStation", svg_path=_ASSETS_DIR / "playstation.svg",
    bbox=(7.0, 6.3, 200.7, 127.1),
    bracket_left=(16, 2), bracket_right=(192, 2),
    hotspots=[
        Hotspot("face_west", (150.1, 41.1), 6),
        Hotspot("face_north", (165.9, 27.5), 6),
        Hotspot("face_east", (179.2, 41.7), 6),
        Hotspot("face_south", (164.9, 57.4), 6),
        Hotspot("l_stick", (73.4, 69.6), 17.6),
        Hotspot("r_stick", (134.3, 69.6), 17.6),
        Hotspot("menu_select", (64.0, 22.4), 5),
        Hotspot("menu_start", (143.6, 22.4), 5),
        Hotspot("dpad_up", (42.7, 32.1), 7),
        Hotspot("dpad_down", (42.7, 51.3), 7),
        Hotspot("dpad_left", (33.2, 41.8), 7),
        Hotspot("dpad_right", (52.5, 41.8), 7),
    ],
)

LAYOUTS = {"xbox": XBOX, "playstation": PLAYSTATION}


def guess_layout_key(hardware_name: str) -> str:
    """Best-effort match from a real dumped Joystick.hardwareName to one of LAYOUTS' keys, or
    "generic" if nothing recognizable matches (falls back to the original hand-drawn diagram)."""
    name = (hardware_name or "").lower()
    if "playstation" in name or "dualshock" in name or "dualsense" in name or "sony" in name or \
            "ps4" in name or "ps5" in name:
        return "playstation"
    if "xbox" in name or "xinput" in name:
        return "xbox"
    return "generic"

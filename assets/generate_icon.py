"""
Dev-only utility — generates assets/icon.ico from the same reticle design nom_app.py draws at
runtime for the in-app window icon (_build_icon_photo), so the exe file itself, the installer,
and its shortcuts all show the same HUD-green-on-navy reticle instead of a generic default icon.

Not a runtime dependency: PIL is only needed to run this script once. Re-run it any time the
reticle design in nom_app.py's _build_icon_photo() changes, to keep icon.ico in sync.

    python assets/generate_icon.py
"""
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "source"))
import theme  # noqa: E402 — after sys.path fix

_SIZE = 256   # render large, downscale for smaller icon sizes — crisper than drawing small


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def render(size=_SIZE):
    bg = _hex_to_rgb(theme.BG)
    hud = _hex_to_rgb(theme.HUD)
    img = Image.new("RGBA", (size, size), bg + (255,))
    px = img.load()

    cx = cy = size / 2 - 0.5
    outer_r = size / 2 - size * 0.06
    ring_w = size * 0.02
    inner_r = size * 0.055
    cross_w = size * 0.01

    for y in range(size):
        for x in range(size):
            dx, dy = x - cx, y - cy
            dist = (dx * dx + dy * dy) ** 0.5
            on_ring = abs(dist - outer_r) <= ring_w
            on_crosshair = (abs(dx) <= cross_w and dist <= outer_r + ring_w) or \
                           (abs(dy) <= cross_w and dist <= outer_r + ring_w)
            on_dot = dist <= inner_r
            if on_ring or on_crosshair or on_dot:
                px[x, y] = hud + (255,)
    return img


def main():
    out = Path(__file__).parent / "icon.ico"
    img = render()
    img.save(out, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)])
    print(f"wrote {out}")


if __name__ == "__main__":
    main()

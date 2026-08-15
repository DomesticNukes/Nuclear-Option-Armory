"""
Blueprinter installer — a one-click shortcut to download nikkorap's Blueprinter mod (the base
loader for .nobp Unity asset bundles: https://github.com/nikkorap/NOBlueprinter-Releases) straight
into the plugin library folder. Mirrors bepinex_installer.py's pattern and reuses its chunked
download() helper — a release asset download is a release asset download regardless of what
happens to the file afterward (BepInEx gets extracted into the game root, this just needs to land
in the library folder as-is, no extraction).

Blueprinter is nikkorap's work, not part of this app — full credit in the README. This module only
automates fetching the same file a user would otherwise get by hand from the releases page.
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from bepinex_installer import download as _download_file

_RELEASES_API = "https://api.github.com/repos/nikkorap/NOBlueprinter-Releases/releases/latest"
_USER_AGENT = "NuclearOptionModManager"

BLUEPRINTER_GUID = "com.nikkorap.blueprinter"


@dataclass
class BlueprinterRelease:
    version: str
    asset_name: str
    url: str
    size: int


def find_latest_release() -> Optional[BlueprinterRelease]:
    """The latest Blueprinter release's .dll asset, or None on any failure (network, API shape
    change). Unlike bepinex_installer there's no safe hardcoded fallback version to fall back to
    here — this is a third-party mod this app doesn't ship or pin a known-good version of."""
    try:
        req = urllib.request.Request(_RELEASES_API, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            release = json.loads(resp.read().decode("utf-8"))
        for asset in release.get("assets", []):
            name = asset.get("name", "")
            if name.lower().endswith(".dll"):
                return BlueprinterRelease(
                    version=release.get("tag_name", "").lstrip("v"),
                    asset_name=name,
                    url=asset["browser_download_url"],
                    size=int(asset.get("size", 0)),
                )
    except Exception:
        pass
    return None


def install(release: BlueprinterRelease, plugin_library: Path,
            progress_cb: Optional[Callable[[int, int], None]] = None) -> Path:
    """Download `release` directly into `plugin_library` (single file, no extraction). Returns
    the destination path. Raises on failure — caller is expected to catch and report."""
    dest = Path(plugin_library) / release.asset_name
    _download_file(release, dest, progress_cb)
    return dest

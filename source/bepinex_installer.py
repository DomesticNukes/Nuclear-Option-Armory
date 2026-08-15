"""
BepInEx installer — pure logic, no Tkinter. Downloads the official BepInEx release zip from
GitHub and extracts it directly into the game folder, replicating the standard manual install
(unzip BepInEx_win_x64_*.zip over the game folder) that every BepInEx-modded game requires before
any plugin DLL will ever actually load.

BepInEx is NOT part of Nuclear Option's own distribution — it's a third-party mod loader the user
(or a previous modding session) installs by hand. This module exists so this app can do that step
for them instead of leaving it as an undocumented prerequisite.

Pinned to the 5.x ("classic"/Mono) release line on purpose — BepInEx 6 restructures around IL2CPP
games, and Nuclear Option is confirmed Mono, so a "latest" release could pick an incompatible
6.x build once one ships. The win_x64 Mono build (confirmed this session: the exact version
already installed on this machine, v5.4.23.5, IS this release line) is always what's needed here.
"""
from __future__ import annotations

import json
import re
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

_RELEASES_API = "https://api.github.com/repos/BepInEx/BepInEx/releases"
_USER_AGENT = "NuclearOptionArmory"

# Known-good fallback if the GitHub API call fails (rate limit, offline, API change) — the exact
# release confirmed working against this game this session.
_FALLBACK_VERSION = "5.4.23.5"
_FALLBACK_ASSET = "BepInEx_win_x64_5.4.23.5.zip"
_FALLBACK_URL = f"https://github.com/BepInEx/BepInEx/releases/download/v{_FALLBACK_VERSION}/{_FALLBACK_ASSET}"
_FALLBACK_SIZE = 639118


@dataclass
class BepInExRelease:
    version: str
    asset_name: str
    url: str
    size: int


def find_latest_release() -> BepInExRelease:
    """The newest 5.x BepInEx release's win_x64 asset. Falls back to a known-good pinned
    version on any failure (network, API shape change, rate limit) — never raises."""
    try:
        req = urllib.request.Request(_RELEASES_API, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            releases = json.loads(resp.read().decode("utf-8"))
        for release in releases:
            tag = release.get("tag_name", "")
            if not re.match(r"^v5\.", tag):
                continue
            for asset in release.get("assets", []):
                if asset.get("name", "").startswith("BepInEx_win_x64_"):
                    return BepInExRelease(
                        version=tag.lstrip("v"),
                        asset_name=asset["name"],
                        url=asset["browser_download_url"],
                        size=int(asset.get("size", 0)),
                    )
    except Exception:
        pass
    return BepInExRelease(version=_FALLBACK_VERSION, asset_name=_FALLBACK_ASSET,
                           url=_FALLBACK_URL, size=_FALLBACK_SIZE)


def download(release: BepInExRelease, dest_path: Path,
             progress_cb: Optional[Callable[[int, int], None]] = None) -> None:
    """Download `release` to `dest_path`. `progress_cb(bytes_read, total_bytes)` is called
    periodically if given (total_bytes may be 0 if the server didn't send Content-Length)."""
    req = urllib.request.Request(release.url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        total = int(resp.headers.get("Content-Length", 0)) or release.size
        read = 0
        with open(dest_path, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                read += len(chunk)
                if progress_cb:
                    progress_cb(read, total)


def _safe_extract(zf: zipfile.ZipFile, dest_dir: Path) -> None:
    """Extract every member of `zf` into `dest_dir`, refusing any entry whose resolved path
    would land outside `dest_dir` (zip-slip protection)."""
    dest_dir = dest_dir.resolve()
    for member in zf.infolist():
        target = (dest_dir / member.filename).resolve()
        if dest_dir not in target.parents and target != dest_dir:
            raise ValueError(f"Refusing to extract unsafe path outside the game folder: {member.filename}")
    zf.extractall(dest_dir)


def install(release: BepInExRelease, game_root: Path,
            progress_cb: Optional[Callable[[int, int], None]] = None) -> None:
    """Download `release` and extract it directly into `game_root` — the standard BepInEx
    install (adds winhttp.dll, doorstop_config.ini, .doorstop_version, BepInEx/ alongside the
    game's own files). Raises on failure; caller is expected to catch and report."""
    game_root = Path(game_root)
    tmp_zip = game_root / f"_{release.asset_name}.download"
    try:
        download(release, tmp_zip, progress_cb)
        with zipfile.ZipFile(tmp_zip) as zf:
            _safe_extract(zf, game_root)
    finally:
        try:
            tmp_zip.unlink(missing_ok=True)
        except Exception:
            pass

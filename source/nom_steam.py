"""
Steam integration utilities for the Nuclear Option Armory.

Provides:
  find_steam_path()          — locate the Steam installation root
  find_nuclear_option_dir()  — locate the Nuclear Option install dir

Adapted from the R.U.S.E. Mod Manager's ruse_mod_engine/steam.py pattern (VDF/appmanifest
parsing), rewritten standalone for a single target game/AppID.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

# Steam AppID for Nuclear Option — confirmed via this machine's
# steamapps/appmanifest_2168680.acf ("name" "Nuclear Option").
NUCLEAR_OPTION_APPID = "2168680"

_STEAM_DEFAULT_PATHS = [
    Path("C:/Program Files (x86)/Steam"),
    Path("C:/Program Files/Steam"),
]


def find_steam_path() -> Optional[Path]:
    """Return the Steam installation root directory, or None if not found.

    Checks the Windows registry first, then falls back to common install paths.
    """
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
        val, _ = winreg.QueryValueEx(key, "SteamPath")
        winreg.CloseKey(key)
        p = Path(val)
        if p.is_dir():
            return p
    except Exception:
        pass

    for candidate in _STEAM_DEFAULT_PATHS:
        if candidate.is_dir():
            return candidate

    return None


def _parse_vdf_paths(vdf_path: Path) -> list:
    """Extract all library root paths from a Steam libraryfolders VDF file."""
    paths = []
    try:
        text = vdf_path.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r'"path"\s+"([^"]+)"', text):
            p = Path(m.group(1))
            if p.is_dir():
                paths.append(p)
    except Exception:
        pass
    return paths


def _find_steam_libraries(steam_path: Path) -> list:
    """Return all Steam library roots, including the Steam install dir itself."""
    libraries = [steam_path]
    for vdf_rel in ("config/libraryfolders.vdf", "steamapps/libraryfolders.vdf"):
        vdf = steam_path / vdf_rel
        if vdf.exists():
            for p in _parse_vdf_paths(vdf):
                if p not in libraries:
                    libraries.append(p)
    return libraries


def _read_appmanifest(library: Path, appid: str) -> Optional[str]:
    """Return the installdir field from an appmanifest ACF, or None."""
    acf = library / "steamapps" / f"appmanifest_{appid}.acf"
    if not acf.exists():
        return None
    try:
        text = acf.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r'"installdir"\s+"([^"]+)"', text)
        return m.group(1) if m else None
    except Exception:
        return None


def find_nuclear_option_dir() -> Optional[Path]:
    """Find the Nuclear Option install directory across all Steam libraries.

    Returns the game root (the folder containing NuclearOption.exe), or None if not found.
    Deliberately does NOT require BepInEx — a vanilla, never-modded install must still be
    discoverable so the app can offer to install BepInEx into it (see bepinex_installer.py).
    """
    steam = find_steam_path()
    if steam is None:
        return None

    for lib in _find_steam_libraries(steam):
        installdir = _read_appmanifest(lib, NUCLEAR_OPTION_APPID)
        if not installdir:
            continue
        candidate = lib / "steamapps" / "common" / installdir
        if (candidate / "NuclearOption.exe").exists():
            return candidate

    return None


def is_valid_game_root(path) -> bool:
    """True if `path` looks like a real Nuclear Option install — the exe is present.
    Deliberately independent of BepInEx; see is_bepinex_installed() for that."""
    if not path:
        return False
    try:
        return (Path(path) / "NuclearOption.exe").exists()
    except Exception:
        return False


def is_bepinex_installed(path) -> bool:
    """True if BepInEx (the Doorstop-injected mod loader, not part of the base game) is
    installed into `path` — the folder plus its winhttp.dll injector proxy are both present."""
    if not path:
        return False
    try:
        p = Path(path)
        return (p / "BepInEx").is_dir() and (p / "winhttp.dll").is_file()
    except Exception:
        return False


def is_mod_ready(path) -> bool:
    """True if `path` is both a real Nuclear Option install AND has BepInEx installed —
    the combined check anything that actually needs to deploy/compile plugins should use."""
    return is_valid_game_root(path) and is_bepinex_installed(path)

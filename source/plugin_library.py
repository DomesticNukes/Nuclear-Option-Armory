"""Shared logic for the plugin library folder — used by plugins_tab.py and config_tab.py so
scanning/auto-detect can't drift out of sync between the two.

A "unit" in the library is either a loose top-level .dll file, or a top-level folder containing
at least one .dll anywhere inside it. BepInEx itself loads plugins recursively at any depth, so a
mod distributed as a folder (a common real-world format) is just as valid as a loose DLL — Armory
now treats each top-level library entry as one opaque deployable unit, whichever shape it is,
rather than trying to flatten folder contents. (Cross-checked against Combat787's NOMM, a more
mature community manager for this game: LocalMods.kt's plugin scan uses this same
opaque-top-level-unit model for exactly this reason.)
"""
from pathlib import Path


def list_library_entries(library: Path) -> list:
    """Top-level .dll files and folders-containing-a-.dll in `library`, sorted by name."""
    if not library.is_dir():
        return []
    entries = []
    try:
        children = list(library.iterdir())
    except OSError:
        return []
    for child in children:
        try:
            if child.is_file() and child.suffix.lower() == ".dll":
                entries.append(child)
            elif child.is_dir() and any(child.rglob("*.dll")):
                entries.append(child)
        except OSError:
            continue
    return sorted(entries, key=lambda p: p.name.lower())


def primary_dll(path: Path) -> Path:
    """The DLL to read metadata from: itself if a file, else the first .dll found inside it."""
    if path.is_file():
        return path
    found = sorted(path.rglob("*.dll"), key=lambda p: p.name.lower())
    if not found:
        raise FileNotFoundError(f"No .dll found inside {path}")
    return found[0]


# ── Auto-detect ──────────────────────────────────────────────────────────────

def _default_stash_candidates() -> list:
    """Existing-folder conventions worth checking before falling back to an app-owned folder."""
    home = Path.home()
    return [home / "Desktop" / "Game Mods" / "Nuclear Option Mods"]


def app_owned_library_dir() -> Path:
    """Always-creatable fallback so auto-detect never leaves the user stuck setting it manually."""
    return Path.home() / "Documents" / "Nuclear Option Armory" / "Plugins"


def auto_detect_library() -> Path:
    """Best existing candidate folder, or the app-owned fallback (created on disk). Always
    succeeds — never returns a path that doesn't exist."""
    for candidate in _default_stash_candidates():
        if candidate.is_dir():
            return candidate
    fallback = app_owned_library_dir()
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback

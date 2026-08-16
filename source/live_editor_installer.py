"""
Live Editor Suite installer — one-click downloads of two well-known, actively-maintained
third-party BepInEx dev tools that run IN the game itself as an overlay, not inside this app:

  RuntimeUnityEditor (ManlyMarco)             — a live Unity scene/GameObject inspector + REPL
                                                 console. github.com/ManlyMarco/RuntimeUnityEditor
  BepInEx.ConfigurationManager (BepInEx team) — auto-generates an in-game settings screen (F1 by
                                                 default) for every loaded plugin's config values.
                                                 github.com/BepInEx/BepInEx.ConfigurationManager

Neither is part of this app or Nuclear Option — full credit to their authors; this module only
automates the same "download the latest release zip, drop it in your plugin library" step a user
would otherwise do by hand from each project's releases page.

Both ship their release zip with an internal `BepInEx/plugins/<Name>/...` path (their manual
install instructions say to extract it directly over the game root). This installer does NOT need
to unwrap that: the Plugin Manager's library scan (plugin_library.py) finds a .dll at ANY nesting
depth inside a library folder, so the zip is simply extracted as-is into a same-named library
folder — confirmed to be exactly what Combat787's NOMM does too, by inspecting a real machine with
both tools already installed through it (their `BepInEx/plugins/<Name>` subtree sits unmodified
inside the manager's own id folder, and it loads fine).

Verified against this machine's live install (2026-08-15): ConfigurationManager v18.4.1's real
BepInPlugin GUID is ``com.bepis.bepinex.configurationmanager`` (read straight from its deployed
.cfg header) and its default toggle hotkey is F1 — both hardcoded below because they're confirmed
facts, not guesses. RuntimeUnityEditor's GUID is deliberately left unset: this app has no verified
copy of it, and guessing one would risk asserting a fact that isn't true.
"""
from __future__ import annotations

import json
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from bepinex_installer import download as _download_file

_USER_AGENT = "NuclearOptionArmory"


@dataclass
class LiveEditorTool:
    tool_id: str            # library folder name this installer always uses — also the match key
    display_name: str
    guid: Optional[str]     # confirmed BepInPlugin GUID, or None if unverified (never guessed)
    repo: str                # "owner/repo"
    homepage: str
    description: str
    usage: str               # short, fact-checked "how to use it in-game" note
    asset_hint: str           # substring preferred when picking a release's zip asset


TOOLS = [
    LiveEditorTool(
        tool_id="RuntimeUnityEditor",
        display_name="RuntimeUnityEditor",
        guid=None,
        repo="ManlyMarco/RuntimeUnityEditor",
        homepage="https://github.com/ManlyMarco/RuntimeUnityEditor",
        description="A live in-game Unity inspector — browse the object/scene tree, edit component "
                     "values, and run a C# REPL console while the game is actually running.",
        usage="Its toggle key and other settings are configurable but this app hasn't verified a "
              "default — after your first play session with it deployed, BepInEx will have written "
              "its .cfg; open it from the Config Editor tab to see and change every setting, "
              "including the hotkey.",
        asset_hint="bepin5",
    ),
    LiveEditorTool(
        tool_id="BepInEx.ConfigurationManager",
        display_name="Configuration Manager",
        guid="com.bepis.bepinex.configurationmanager",
        repo="BepInEx/BepInEx.ConfigurationManager",
        homepage="https://github.com/BepInEx/BepInEx.ConfigurationManager",
        description="Adds an in-game settings screen auto-generated from every loaded plugin's "
                     "config — the in-game equivalent of Armory's own Config Editor tab.",
        usage="Default hotkey: F1 opens/closes it in-game (confirmed from a real deployed config on "
              "this machine). Change the hotkey any time from the Config Editor tab below.",
        asset_hint="bepinex5",
    ),
]


@dataclass
class ToolRelease:
    version: str
    asset_name: str
    url: str
    size: int


def find_latest_release(tool: LiveEditorTool) -> Optional[ToolRelease]:
    """The newest release's most likely Windows/Mono zip asset for `tool`, or None on any failure
    (network, API shape change, rate limit) — never raises."""
    api_url = f"https://api.github.com/repos/{tool.repo}/releases/latest"
    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            release = json.loads(resp.read().decode("utf-8"))
        assets = [a for a in release.get("assets", []) if a.get("name", "").lower().endswith(".zip")]
        if not assets:
            return None
        chosen = next((a for a in assets if tool.asset_hint.lower() in a.get("name", "").lower()),
                      assets[0])
        return ToolRelease(
            version=release.get("tag_name", "").lstrip("v"),
            asset_name=chosen["name"],
            url=chosen["browser_download_url"],
            size=int(chosen.get("size", 0)),
        )
    except Exception:
        return None


def _safe_extract(zf: zipfile.ZipFile, dest_dir: Path) -> None:
    """Zip-slip guard, same shape as bepinex_installer._safe_extract — refuses any entry whose
    resolved path would land outside `dest_dir`."""
    dest_dir = dest_dir.resolve()
    for member in zf.infolist():
        target = (dest_dir / member.filename).resolve()
        if dest_dir not in target.parents and target != dest_dir:
            raise ValueError(f"Refusing to extract unsafe path: {member.filename}")
    zf.extractall(dest_dir)


def install(tool: LiveEditorTool, release: ToolRelease, plugin_library: Path,
            progress_cb: Optional[Callable[[int, int], None]] = None) -> Path:
    """Download `release` and extract it into `plugin_library / tool.tool_id` (replacing any
    existing copy there — an update). Returns the destination folder. Raises on failure — caller
    is expected to catch and report."""
    plugin_library = Path(plugin_library)
    dest_folder = plugin_library / tool.tool_id
    tmp_zip = plugin_library / f"_{tool.tool_id}.download"
    try:
        _download_file(release, tmp_zip, progress_cb)
        if dest_folder.exists():
            import shutil
            shutil.rmtree(dest_folder)
        dest_folder.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(tmp_zip) as zf:
            _safe_extract(zf, dest_folder)
    finally:
        try:
            tmp_zip.unlink(missing_ok=True)
        except Exception:
            pass
    return dest_folder


def is_in_library(tool: LiveEditorTool, plugin_library: Path) -> bool:
    try:
        return (Path(plugin_library) / tool.tool_id).is_dir()
    except Exception:
        return False


def is_deployed(tool: LiveEditorTool, bepinex_plugins_dir: Path) -> bool:
    try:
        return (Path(bepinex_plugins_dir) / tool.tool_id).is_dir()
    except Exception:
        return False

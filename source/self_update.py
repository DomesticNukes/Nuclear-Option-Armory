"""
Self-updater — pure logic, no Tkinter. Checks GitHub Releases for a newer Nuclear Option Armory
than the running one, and (only when running as a frozen exe — sys.frozen) can download and apply
the update in place.

Requires the repo to actually publish GitHub Releases (tag `vX.Y.Z`, with the portable exe attached
as an asset) — see .github/workflows/build.yml's "release" job, which only runs on a version-tag
push, not on every commit. Running from source has nothing to self-replace, so update_tab.py just
shows a link to the release instead of offering to apply anything.

Self-replace mechanism: Windows won't let you overwrite a running .exe's file while it's still
executing, so the running app has to exit before the replace can happen. `apply_update` writes a
tiny detached .bat helper that waits for the file to unlock (retries the copy for a few seconds),
copies the freshly-downloaded exe over the current one, relaunches it, then deletes itself — the
caller is expected to close the app immediately after spawning it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

_RELEASES_API = "https://api.github.com/repos/DomesticNukes/Nuclear-Option-Armory/releases/latest"
_USER_AGENT = "NuclearOptionArmory"


@dataclass
class ArmoryRelease:
    version: str            # e.g. "0.6.2" — the tag with a leading "v" stripped, if present
    tag: str                # the raw tag name, e.g. "v0.6.2"
    html_url: str            # the Release page on GitHub, for "view what's new"
    notes: str
    asset_name: Optional[str]
    asset_url: Optional[str]
    asset_size: int


def _parse_version(text: str) -> tuple:
    """"0.6.10" -> (0, 6, 10). Non-numeric/missing parts become 0 rather than raising, so a
    malformed tag degrades to "no update" instead of crashing the check."""
    parts = []
    for chunk in text.strip().lstrip("vV").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) if parts else (0,)


def is_newer(current: str, candidate: str) -> bool:
    a, b = _parse_version(current), _parse_version(candidate)
    width = max(len(a), len(b))
    a = a + (0,) * (width - len(a))
    b = b + (0,) * (width - len(b))
    return b > a


def _find_portable_asset(assets: list) -> Optional[dict]:
    """The portable exe asset among a release's assets — NOT matched by an exact filename, because
    GitHub replaces spaces with dots in release asset names server-side (confirmed real: the CI
    build produces "Nuclear Option Armory.exe", but the actual published asset is named
    "Nuclear.Option.Armory.exe") — a hardcoded exact name would never match. Instead: of the two
    .exe assets build.yml always publishes, the portable build is whichever one ISN'T the "Setup"
    installer, which stays robust to exactly how GitHub mangles the rest of the name."""
    exe_assets = [a for a in assets if str(a.get("name", "")).lower().endswith(".exe")]
    portable = [a for a in exe_assets if "setup" not in str(a.get("name", "")).lower()]
    return portable[0] if portable else None


def find_latest_release() -> Optional[ArmoryRelease]:
    """The latest published GitHub Release, or None on any failure (network, no releases
    published yet, rate limit, API shape change) — never raises. A missing/never-published
    release is a completely normal state (see this module's docstring), not an error."""
    try:
        req = urllib.request.Request(_RELEASES_API, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        tag = data.get("tag_name", "")
        if not tag:
            return None
        asset_name = asset_url = None
        asset_size = 0
        portable = _find_portable_asset(data.get("assets", []))
        if portable:
            asset_name = portable["name"]
            asset_url = portable["browser_download_url"]
            asset_size = int(portable.get("size", 0))
        return ArmoryRelease(
            version=tag.lstrip("vV"), tag=tag,
            html_url=data.get("html_url", ""), notes=data.get("body", "") or "",
            asset_name=asset_name, asset_url=asset_url, asset_size=asset_size,
        )
    except Exception:
        return None


def download(release: ArmoryRelease, dest_path: Path,
             progress_cb: Optional[Callable[[int, int], None]] = None) -> None:
    """Download the release's portable exe asset to `dest_path`. Raises ValueError if this
    release has no portable-exe asset attached (shouldn't happen for a release the CI workflow
    published, but a hand-created GitHub Release could omit it)."""
    if not release.asset_url:
        raise ValueError("This release has no portable exe asset to download.")
    req = urllib.request.Request(release.asset_url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        total = int(resp.headers.get("Content-Length", 0)) or release.asset_size
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


def can_self_update() -> bool:
    """Only meaningful when running as an actual frozen exe — running from source has no exe
    file to replace, and sys.executable would just be python.exe itself."""
    return bool(getattr(sys, "frozen", False))


def apply_update(new_exe_path: Path) -> None:
    """Spawns a detached helper that waits for THIS process's exe file to unlock, replaces it with
    `new_exe_path`, relaunches it, and cleans up after itself. Caller must exit the app (so the
    running exe's file handle is released) immediately after calling this — the helper can't
    proceed until then. Only valid when can_self_update() is True."""
    if not can_self_update():
        raise RuntimeError("Can't self-update when running from source, not a frozen exe.")

    current_exe = Path(sys.executable).resolve()
    bat_path = Path(os.environ.get("TEMP", ".")) / "armory_apply_update.bat"
    # /retry loop: the OS won't release the old exe's file lock until this whole process has
    # actually exited, which races the caller's own shutdown — a few retries covers that gap
    # without needing any cross-process signaling.
    bat_path.write_text(
        "@echo off\r\n"
        "setlocal\r\n"
        f'set "NEW={new_exe_path}"\r\n'
        f'set "CUR={current_exe}"\r\n'
        "set /a tries=0\r\n"
        ":retry\r\n"
        "set /a tries+=1\r\n"
        'copy /y "%NEW%" "%CUR%" > nul 2>&1\r\n'
        "if errorlevel 1 (\r\n"
        "    if %tries% GEQ 15 goto giveup\r\n"
        "    timeout /t 1 /nobreak > nul\r\n"
        "    goto retry\r\n"
        ")\r\n"
        'del "%NEW%" > nul 2>&1\r\n'
        'start "" "%CUR%"\r\n'
        ":giveup\r\n"
        'del "%~f0"\r\n',
        encoding="utf-8",
    )
    subprocess.Popen(
        ["cmd", "/c", str(bat_path)],
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        close_fds=True,
    )

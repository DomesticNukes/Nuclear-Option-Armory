"""
DllInspector integration — a real, independent third-party tool by 9138noms
(github.com/9138noms/DllInspector, MIT-unlicensed but publicly released) that checks whether
BepInEx mod DLLs still reference real game code after a Nuclear Option update. It uses Mono.Cecil
to extract each mod's type/member/Harmony-patch references and diffs them against a snapshot of
the game's own Assembly-CSharp.dll — real static analysis, not a guess. Armory doesn't ship or
modify it, just downloads the real release and shells out to it, the same pattern used for
BepInEx/Blueprinter/Configuration Manager.

DllInspector is NOT a BepInEx plugin — it's a standalone exe that inspects files from outside the
game, so it's stored in Armory's own tools folder (app.state_path("tools")), never deployed into
BepInEx/plugins.

Real, confirmed limitation (read straight from its source at Scanner.cs, not guessed): the CLI
commands that GENERATE a fresh snapshot ("scan"/"check") have the Steam default install path
hardcoded (the `ManagedDir` constant) with no command-line override — only its fully-interactive
mode lets a human type a custom path. So snapshot generation here only works when the detected
game_root matches that exact default path (DEFAULT_GAME_PATH below, the literal hardcoded string);
everywhere else this reports itself unavailable rather than silently scanning the wrong game or
failing confusingly. The one command that IS fully scriptable regardless of game location is
`modcheck <mod.dll> <snapshot.json>` — checking one mod's DLL against an already-generated
snapshot — since the snapshot path itself is caller-supplied.
"""
from __future__ import annotations

import json
import re
import subprocess
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

_RELEASES_API = "https://api.github.com/repos/9138noms/DllInspector/releases/latest"
_USER_AGENT = "NuclearOptionArmory"

# The literal path DllInspector's Scanner.cs hardcodes as ManagedDir's parent — confirmed from its
# real source, not guessed. Snapshot generation ("scan") only works when the user's real game_root
# matches this exactly.
DEFAULT_GAME_PATH = r"C:\Program Files (x86)\Steam\steamapps\common\Nuclear Option"

SNAPSHOT_FILENAME = "dll_inspector_snapshot.json"
EXE_FILENAME = "DllInspector.exe"


@dataclass
class DllInspectorRelease:
    version: str
    asset_name: str
    asset_url: str
    asset_size: int


def find_latest_release() -> Optional[DllInspectorRelease]:
    """The latest published DllInspector release's Windows exe asset, or None on any failure
    (network, no releases, API shape change) — never raises."""
    try:
        req = urllib.request.Request(_RELEASES_API, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        tag = data.get("tag_name", "")
        for asset in data.get("assets", []):
            name = str(asset.get("name", ""))
            if name.lower().endswith(".exe"):
                return DllInspectorRelease(
                    version=tag.lstrip("vV"), asset_name=name,
                    asset_url=asset["browser_download_url"], asset_size=int(asset.get("size", 0)),
                )
        return None
    except Exception:
        return None


def download(release: DllInspectorRelease, dest_path: Path,
             progress_cb: Optional[Callable[[int, int], None]] = None) -> None:
    req = urllib.request.Request(release.asset_url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        total = int(resp.headers.get("Content-Length", 0)) or release.asset_size
        read = 0
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                read += len(chunk)
                if progress_cb:
                    progress_cb(read, total)


def is_default_path(game_root) -> bool:
    """True if `game_root` is (close enough to) the exact path DllInspector's scan/check commands
    hardcode — case-insensitive and tolerant of a trailing slash, since Windows paths are
    case-insensitive but this is still a literal-string comparison, not a filesystem check."""
    if not game_root:
        return False
    a = str(Path(str(game_root)).as_posix()).rstrip("/").lower()
    b = str(Path(DEFAULT_GAME_PATH).as_posix()).rstrip("/").lower()
    return a == b


class InspectorError(Exception):
    pass


def run_scan(exe_path: Path, output_json_path: Path, timeout: int = 90) -> str:
    """Runs `DllInspector.exe scan <output_json_path>` — only meaningful when is_default_path() is
    True for the caller's game_root (see module docstring); the exe itself has no way to be told
    otherwise. Returns the raw stdout on success. Raises InspectorError with the real stdout/stderr
    on failure (non-zero exit, timeout, or the exe not existing)."""
    if not Path(exe_path).is_file():
        raise InspectorError(f"DllInspector.exe not found at {exe_path}")
    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            [str(exe_path), "scan", str(output_json_path)],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise InspectorError(f"Timed out after {timeout}s scanning the game DLL.") from e
    if result.returncode != 0 or not output_json_path.is_file():
        raise InspectorError((result.stdout or "") + (result.stderr or "") or
                              f"scan exited with code {result.returncode}")
    return result.stdout


@dataclass
class ModCheckResult:
    mod_name: str
    compatible: bool
    total_refs: int
    ok_count: int
    missing_count: int
    issues: list = field(default_factory=list)   # list[str] — "<Category> <Reference>"
    raw_output: str = ""


# Real output shape, confirmed from DllInspector's own ModScanner.PrintResults source:
#   === ModCheck: <name> ===
#   ...
#   [MISSING] Type  <ref>          (or "Patch <ref>" / "Method <ref>" / "Field <ref>")
#   ...
#   === SUMMARY ===
#     Total: N references
#     OK: N | Missing: N
#     Verdict: COMPATIBLE
#   (or: Verdict: INCOMPATIBLE (N missing, N changed))
_MISSING_RE = re.compile(r"^\[MISSING\]\s+(\S+)\s+(.+)$", re.MULTILINE)
_TOTAL_RE = re.compile(r"Total:\s*(\d+)\s*references")
_OK_MISSING_RE = re.compile(r"OK:\s*(\d+)\s*\|\s*Missing:\s*(\d+)")
_VERDICT_RE = re.compile(r"Verdict:\s*(COMPATIBLE|INCOMPATIBLE)")
_MODNAME_RE = re.compile(r"=== ModCheck:\s*(.+?)\s*===")


def parse_modcheck_output(stdout: str, fallback_name: str = "") -> ModCheckResult:
    """Parses DllInspector's real `modcheck` console output — never raises; a malformed/empty
    output just yields a ModCheckResult with zeroed counts and compatible=False (safer default
    than silently claiming something is fine when the output couldn't be understood)."""
    name_match = _MODNAME_RE.search(stdout)
    mod_name = name_match.group(1) if name_match else fallback_name

    issues = [f"{m.group(1)} {m.group(2)}" for m in _MISSING_RE.finditer(stdout)]

    total_match = _TOTAL_RE.search(stdout)
    total_refs = int(total_match.group(1)) if total_match else 0

    ok_missing_match = _OK_MISSING_RE.search(stdout)
    ok_count = int(ok_missing_match.group(1)) if ok_missing_match else 0
    missing_count = int(ok_missing_match.group(2)) if ok_missing_match else len(issues)

    verdict_match = _VERDICT_RE.search(stdout)
    compatible = bool(verdict_match and verdict_match.group(1) == "COMPATIBLE")

    return ModCheckResult(
        mod_name=mod_name, compatible=compatible, total_refs=total_refs,
        ok_count=ok_count, missing_count=missing_count, issues=issues, raw_output=stdout,
    )


def run_modcheck(exe_path: Path, mod_dll_path: Path, snapshot_path: Path,
                  timeout: int = 30) -> ModCheckResult:
    """Runs `DllInspector.exe modcheck <mod_dll_path> <snapshot_path>` — fully scriptable
    regardless of where the game is installed, since both paths are caller-supplied. Raises
    InspectorError on failure (exe/snapshot missing, timeout, non-zero exit); caller reports."""
    if not Path(exe_path).is_file():
        raise InspectorError(f"DllInspector.exe not found at {exe_path}")
    if not Path(snapshot_path).is_file():
        raise InspectorError(f"No snapshot found at {snapshot_path} — generate one first.")
    if not Path(mod_dll_path).is_file():
        raise InspectorError(f"Mod DLL not found: {mod_dll_path}")
    try:
        result = subprocess.run(
            [str(exe_path), "modcheck", str(mod_dll_path), str(snapshot_path)],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise InspectorError(f"Timed out after {timeout}s checking {mod_dll_path.name}.") from e
    # A non-zero exit is always a real failure, even when SOME stdout was printed before the
    # crash (confirmed real: DllInspector.exe itself has an unhandled Mono.Cecil
    # AssemblyResolutionException on any mod whose [HarmonyPatch] attribute references a type
    # from Harmony's own assembly — a common real pattern — which prints a "Using snapshot: ..."
    # header to stdout before crashing to stderr with a non-zero exit). Treating that as a clean
    # "0 missing" result would be actively misleading — it means the check never actually ran,
    # not that the mod is fine.
    if result.returncode != 0:
        # stderr for an unhandled .NET exception starts with "Unhandled exception. <Type>: <msg>"
        # followed by a multi-line stack trace — the first line is the actual error, the rest is
        # noise for this purpose.
        first_line = (result.stderr or "").strip().splitlines()[0] if result.stderr else ""
        raise InspectorError(
            first_line or f"modcheck exited with code {result.returncode} (DllInspector itself "
                           f"likely crashed on this DLL — see the log for details)")
    return parse_modcheck_output(result.stdout, fallback_name=Path(mod_dll_path).name)

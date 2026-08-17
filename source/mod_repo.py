"""
Community mod repository — pure logic, no Tkinter. Browses and installs mods from NOMNOM
(github.com/KopterBuzz/NOMNOM), the same community-maintained manifest Combat787's NOMM uses — a
public, static JSON file this app only reads, never hosts or maintains itself.

Scope, deliberately narrower than NOMM's own installer: only "plugin"-type artifacts (a bare .dll
or a .zip containing one) are installable here. Two things are shown but NOT one-click-installable,
to avoid silently doing something that doesn't actually work rather than just not doing it:
  - "addon"-type artifacts (confirmed via the real manifest: 116 of 621 real artifacts, mostly
    Blueprinter .nobp content bundles) need to land in a Blueprinter-specific content folder this
    app hasn't verified the real layout of.
  - Non-zip archives (.7z/.rar — 37 of 621 real artifacts) aren't extracted; Python's stdlib has no
    support for either, and adding one would break this app's "no runtime dependencies" design for
    the sake of ~6% of artifacts.

Each installed mod gets its own subfolder in the plugin library (named after its manifest id — the
same folder-per-unit shape plugin_library.py already recognizes as one deployable unit), containing
the extracted/copied files plus a small `armory_repo_meta.json` sidecar ({"id", "version"}) — the
only way to later answer "is this manifest mod installed, and at what version," since a manifest id
is NOT the same identity space as a BepInPlugin GUID (they only coincide when an author deliberately
chose them to match, as Blueprinter's manifest id "com.nikkorap.blueprinter" does).

Dependency resolution mirrors NOMM's own real behavior (RepoMods.kt): installing a mod recursively
installs its manifest-declared `dependencies` first, skipping ones already satisfied — checked two
ways: already installed via THIS mechanism (the meta.json sidecar), or already present as a real
BepInPlugin GUID somewhere in the library or directly in BepInEx/plugins (covers a dependency like
Blueprinter that the user installed via the Config tab's Companion Tools, not through this repo).
"""
from __future__ import annotations

import json
import shutil
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import nom_plugin_meta as npm
import plugin_library

MANIFEST_URL = "https://kopterbuzz.github.io/NOMNOM/manifest/manifest.json"
_USER_AGENT = "NuclearOptionArmory"
META_FILENAME = "armory_repo_meta.json"

# Archive formats this app can actually extract — see module docstring for why 7z/rar aren't here.
_SUPPORTED_ARCHIVE_SUFFIXES = (".zip",)


@dataclass
class PackageRef:
    id: str
    version: Optional[str] = None


@dataclass
class Artifact:
    file_name: Optional[str]
    version: str
    artifact_type: Optional[str]      # "plugin" | "addon" | other — see module docstring
    game_version: Optional[str]
    download_url: Optional[str]
    hash: Optional[str]               # "sha256:<hex>", or None (real: ~30% of artifacts have none)
    extends: Optional[PackageRef]
    dependencies: list = field(default_factory=list)        # list[PackageRef]
    incompatibilities: list = field(default_factory=list)   # list[PackageRef]

    @property
    def installable(self) -> bool:
        """Only real, extractable BepInEx plugin artifacts — see module docstring for the two
        categories deliberately excluded."""
        if self.artifact_type != "plugin" or not self.download_url or not self.file_name:
            return False
        name = self.file_name.lower()
        return name.endswith(".dll") or name.endswith(_SUPPORTED_ARCHIVE_SUFFIXES)


@dataclass
class ModEntry:
    id: str
    display_name: str
    description: str
    tags: list
    authors: list
    urls: list                # list[{"name", "url"}]
    artifacts: list           # list[Artifact]
    download_count: Optional[int] = None


def _parse_version(text: str) -> tuple:
    parts = []
    for chunk in (text or "").strip().lstrip("vV").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) if parts else (0,)


def version_key(v: str):
    return _parse_version(v)


def is_newer(current: str, candidate: str) -> bool:
    a, b = _parse_version(current), _parse_version(candidate)
    width = max(len(a), len(b))
    a, b = a + (0,) * (width - len(a)), b + (0,) * (width - len(b))
    return b > a


def _parse_package_ref(raw) -> Optional[PackageRef]:
    if not isinstance(raw, dict) or not raw.get("id"):
        return None
    return PackageRef(id=raw["id"], version=raw.get("version"))


def _parse_artifact(raw: dict) -> Artifact:
    return Artifact(
        file_name=raw.get("fileName"),
        version=raw.get("version") or "0",
        artifact_type=raw.get("type"),
        game_version=raw.get("gameVersion"),
        download_url=raw.get("downloadUrl") or raw.get("downloadURL"),
        hash=raw.get("hash"),
        extends=_parse_package_ref(raw.get("extends")),
        dependencies=[r for r in (_parse_package_ref(d) for d in raw.get("dependencies", []) or []) if r],
        incompatibilities=[r for r in (_parse_package_ref(d) for d in raw.get("incompatibilities", []) or []) if r],
    )


def fetch_manifest() -> list:
    """Every mod in the real NOMNOM manifest, or an empty list on any failure (network, malformed
    JSON) — never raises. Confirmed real and live this session: 158 mods, 621 artifacts."""
    try:
        req = urllib.request.Request(MANIFEST_URL, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        if not isinstance(raw, list):
            return []
        mods = []
        for entry in raw:
            if not isinstance(entry, dict) or not entry.get("id") or not entry.get("artifacts"):
                continue
            mods.append(ModEntry(
                id=entry["id"], display_name=entry.get("displayName") or entry["id"],
                description=entry.get("description") or "", tags=list(entry.get("tags") or []),
                authors=list(entry.get("authors") or []), urls=list(entry.get("urls") or []),
                artifacts=[_parse_artifact(a) for a in entry["artifacts"]],
                download_count=entry.get("downloadCount"),
            ))
        return mods
    except Exception:
        return []


def latest_artifact(mod: ModEntry) -> Optional[Artifact]:
    if not mod.artifacts:
        return None
    return max(mod.artifacts, key=lambda a: version_key(a.version))


def latest_installable_artifact(mod: ModEntry) -> Optional[Artifact]:
    candidates = [a for a in mod.artifacts if a.installable]
    if not candidates:
        return None
    return max(candidates, key=lambda a: version_key(a.version))


# ── Installed-state tracking ──────────────────────────────────────────────────

def _read_meta(folder: Path) -> Optional[dict]:
    try:
        return json.loads((folder / META_FILENAME).read_text(encoding="utf-8"))
    except Exception:
        return None


def installed_versions(library: Path) -> dict:
    """{manifest_id: installed_version} for every library entry carrying an armory_repo_meta.json
    sidecar — i.e. everything installed through THIS mechanism. Loose top-level DLLs never carry
    one (only folder-shaped entries do, since that's where install() always places them), so this
    naturally only reports repo-installed mods, not everything in the library."""
    found = {}
    if not library.is_dir():
        return found
    try:
        children = list(library.iterdir())
    except OSError:
        return found
    for child in children:
        if not child.is_dir():
            continue
        meta = _read_meta(child)
        if meta and meta.get("id"):
            found[meta["id"]] = meta.get("version")
    return found


def _guid_present_anywhere(guid: str, library: Path, bepinex_plugins_dir: Optional[Path]) -> bool:
    """True if some real BepInPlugin GUID equal to `guid` is found in the library OR directly in
    BepInEx/plugins (e.g. a Companion Tool like Blueprinter installed via the Config tab, not
    through this repo) — used so a manifest dependency isn't redundantly reinstalled when it's
    already satisfied some other way. Best-effort: only catches it when a mod's manifest id
    happens to equal its real GUID, which isn't guaranteed, but is true for the real cases that
    matter most (Blueprinter's manifest id IS "com.nikkorap.blueprinter", confirmed real)."""
    dirs = []
    if library.is_dir():
        dirs.append(library)
    if bepinex_plugins_dir and bepinex_plugins_dir.is_dir():
        dirs.append(bepinex_plugins_dir)
    for d in dirs:
        try:
            children = list(d.iterdir())
        except OSError:
            continue
        for child in children:
            is_plugin = (child.is_file() and child.suffix.lower() == ".dll") or \
                        (child.is_dir() and any(child.rglob("*.dll")))
            if not is_plugin:
                continue
            try:
                if npm.read_primary_plugin_metadata(plugin_library.primary_dll(child)).guid == guid:
                    return True
            except Exception:
                continue
    return False


# ── Install ────────────────────────────────────────────────────────────────────

class InstallError(Exception):
    pass


def _verify_hash(data: bytes, expected: Optional[str]) -> None:
    if not expected:
        return   # real: ~30% of artifacts have none — best-effort, not a hard requirement
    import hashlib
    algo, _, hex_digest = expected.partition(":")
    if algo.lower() != "sha256" or not hex_digest:
        return   # unrecognized hash format — don't block on something we can't check
    actual = hashlib.sha256(data).hexdigest()
    if actual.lower() != hex_digest.lower():
        raise InstallError(f"Hash mismatch — expected {hex_digest[:12]}…, got {actual[:12]}… "
                            f"(the download may be corrupted or tampered with)")


def _download_bytes(url: str, progress_cb: Optional[Callable[[int, int], None]] = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        chunks = []
        read = 0
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            chunks.append(chunk)
            read += len(chunk)
            if progress_cb:
                progress_cb(read, total)
        return b"".join(chunks)


def _place_artifact(data: bytes, artifact: Artifact, dest_folder: Path) -> None:
    name = artifact.file_name or "plugin.dll"
    if name.lower().endswith(".dll"):
        dest_folder.mkdir(parents=True, exist_ok=True)
        (dest_folder / name).write_bytes(data)
        return
    if name.lower().endswith(".zip"):
        import io
        dest_folder.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            dest_resolved = dest_folder.resolve()
            for member in zf.infolist():
                target = (dest_resolved / member.filename).resolve()
                if dest_resolved != target and dest_resolved not in target.parents:
                    raise InstallError(f"Unsafe archive entry: {member.filename}")
            zf.extractall(dest_resolved)
        return
    raise InstallError(f"Unsupported archive format for {name!r} — only .dll and .zip artifacts "
                        f"can be installed automatically.")


def install(mods_by_id: dict, library: Path, mod: ModEntry, artifact: Artifact,
            bepinex_plugins_dir: Optional[Path] = None,
            progress_cb: Optional[Callable[[str, int, int], None]] = None,
            _installing: Optional[set] = None) -> list:
    """Installs `artifact` for `mod` into its own library subfolder, recursively installing any
    manifest-declared dependencies first (skipped if already satisfied — see
    _guid_present_anywhere). `mods_by_id` is the full fetched manifest indexed by id, needed to
    resolve dependency ids into their own ModEntry/latest-installable-artifact. Returns the list of
    manifest ids actually installed this call (mod.id last). Raises InstallError on failure;
    caller is expected to catch and report — nothing already installed is rolled back on a later
    dependency failure, matching NOMM's own best-effort behavior."""
    if not artifact.installable:
        raise InstallError(f'"{artifact.file_name}" isn\'t a supported plugin artifact '
                            f"(only .dll/.zip \"plugin\"-type artifacts can be installed here).")

    installing = _installing if _installing is not None else set()
    if mod.id in installing:
        return []   # dependency cycle guard, mirrors NOMM's RepoMods.installMod
    installing.add(mod.id)

    installed_ids = []
    for dep_ref in artifact.dependencies:
        already = installed_versions(library).get(dep_ref.id)
        if already is not None:
            continue
        if _guid_present_anywhere(dep_ref.id, library, bepinex_plugins_dir):
            continue
        dep_mod = mods_by_id.get(dep_ref.id)
        if dep_mod is None:
            raise InstallError(f'"{mod.display_name}" depends on "{dep_ref.id}", which isn\'t in '
                                f"the manifest — can't auto-install it.")
        dep_artifact = latest_installable_artifact(dep_mod)
        if dep_artifact is None:
            raise InstallError(f'"{mod.display_name}" depends on "{dep_mod.display_name}", which '
                                f"has no installable artifact — can't auto-install it.")
        installed_ids.extend(install(mods_by_id, library, dep_mod, dep_artifact,
                                      bepinex_plugins_dir, progress_cb, installing))

    def _cb(read, total):
        if progress_cb:
            progress_cb(mod.display_name, read, total)

    data = _download_bytes(artifact.download_url, progress_cb=_cb)
    _verify_hash(data, artifact.hash)

    dest_folder = library / mod.id
    if dest_folder.exists():
        shutil.rmtree(dest_folder)
    _place_artifact(data, artifact, dest_folder)
    (dest_folder / META_FILENAME).write_text(
        json.dumps({"id": mod.id, "version": artifact.version}, indent=2), encoding="utf-8")

    installed_ids.append(mod.id)
    return installed_ids

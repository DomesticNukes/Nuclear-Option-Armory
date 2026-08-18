"""
Unit asset layout — reads Nuclear Option's real ScriptableObject unit definitions (AircraftDefinition
/VehicleDefinition/ShipDefinition/BuildingDefinition/MissileDefinition, plus AircraftParameters)
DIRECTLY out of the game's compiled .assets files, byte-exact, no running game required.

Why this is possible at all: Unity strips per-class TypeTrees (serialization layout) from release
builds, so a generic asset reader/writer normally can't deserialize game-specific ScriptableObject
data (see unit_stat_catalog.py's docstring — the existing Unit Editor works around this by reflecting
values out of the LIVE running game instead). But the exact field layout a stripped TypeTree would
have described is NOT actually lost — it's still fully present in the compiled Assembly-CSharp.dll's
own .NET metadata (every field's name, type, and declaration order — required for C# reflection to
work at all). reflect_unit_layout.ps1 recovers it from there via .NET reflection and writes it to
data/unit_asset_layout.json; this module turns that recovered layout back into a real binary
reader (and, for fixed-size fields, a safe in-place writer).

Confirmed byte-exact against a real object (AttackHelo1 in resources.assets, 2026-08-17): reading
AircraftDefinition/UnitDefinition through this exact mechanism consumed precisely the object's real
656-byte size and produced sane, correct values throughout (a real unit name, a real multi-sentence
description, a real mass in kg, a cross-reference to the correct real AircraftParameters object) —
not a coincidence, a genuine validation.

Every MonoBehaviour-backed object (which is what a custom ScriptableObject asset actually is, at the
serialization level) starts with a fixed, non-stripped header before the script's own fields:
m_GameObject (PPtr, 12 bytes), m_Enabled (bool, 4 bytes incl. padding), m_Script (PPtr, 12 bytes),
m_Name (string). This is real, standard Unity structure (confirmed via UnityPy's own bundled
TypeTree database for the MonoBehaviour base class), not something recovered from the DLL.

Real, confirmed Unity TypeTree conventions this parser relies on:
  - float/int/enum: 4 bytes, no padding needed (already 4-byte sized).
  - bool: 1 real byte, ALWAYS followed by 3 padding bytes to the next 4-byte boundary — confirmed
    empirically (a naive "no padding" reading produced a byte-count mismatch and garbage values for
    every field after the first bool; padding after every bool, not just runs of them, was what
    produced byte-exact, sane results).
  - string: a 4-byte length prefix, the UTF-8 bytes themselves, then padding to the next 4-byte
    boundary.
  - PPtr<T> (a reference to another Unity asset — Sprite/GameObject/another ScriptableObject/...):
    always exactly 12 bytes (4-byte m_FileID + 8-byte m_PathID on this game's Unity version) —
    never followed/resolved by this module; editing what a reference POINTS TO is a different,
    unaddressed problem (same scope boundary unit_stat_catalog.py already draws for reflection
    editing).
  - A [Serializable] plain class/struct field (TypeIdentity, RoleIdentity, AircraftInfo, ...)
    serializes INLINE at the same position, not by reference — its own fields just continue the
    same byte stream.
  - List<T>/T[] fields: a 4-byte count prefix followed by that many elements back-to-back, each
    following the SAME rules as any other field of the element's type. Needed because Nuclear
    Option's own field ORDER sometimes puts a list/array field before other fields this app DOES
    want to read (AircraftParameters.airfoils/loadouts/liveries precede maxSpeed/turningRadius/etc)
    — skipping them without understanding their real length would silently misread everything after.

What's NOT supported yet (see reflect_unit_layout.ps1's "unsupported" classification, kept and
surfaced here rather than silently guessed at): fields whose type is a generic other than List<T>,
System.Nullable<T> (Unity doesn't serialize these at all in practice — confirmed live:
MissileDefinition.mass is exactly such a field, and treating it as absent, not zero, is what made
MissileDefinition's own byte count match exactly), and any field type this session hasn't reflected
the internal layout of yet (UnityEngine.AnimationCurve, Addressables' AssetReference<T> — both
appear inside AircraftParameters' Airfoil/Livery array elements, real known follow-up work, not
silently faked).
"""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# is_game_running/backup_value are reused as-is from rewired_registry.py (identical safety need —
# refuse writes while the game has the file open, always back up original bytes first — no reason
# to duplicate the logic just because the underlying resource differs, registry value vs. file).
from rewired_registry import is_game_running, backup_value as backup_object_bytes

_LAYOUT_PATH = Path(__file__).parent / "data" / "unit_asset_layout.json"

with open(_LAYOUT_PATH, encoding="utf-8-sig") as _f:
    LAYOUT: dict = json.load(_f)

# The real, fixed MonoBehaviour header every custom ScriptableObject asset starts with — confirmed
# against UnityPy's own bundled TypeTree database for ClassIDType.MonoBehaviour on this game's real
# Unity version (2022.3.62f2), not re-derived from the (irrelevant, engine-internal) Assembly-CSharp
# reflection data.
_HEAD_FIELDS = ["m_GameObject", "m_Enabled", "m_Script", "m_Name"]


class AssetLayoutError(Exception):
    """Raised when the real object's bytes don't match what this module's layout knowledge expects
    — e.g. an unsupported field was reached, or a game update changed a class's fields. Never
    silently returns partial/guessed data past the point of failure."""


@dataclass
class FieldValue:
    path: str                # dotted path, e.g. "aircraftInfo.maxSpeed" or "spawnOffset.x"
    kind: str                 # "float" / "int" / "bool" / "enum" / "string" / "pptr"
    value: object
    offset: Optional[int]     # absolute byte offset within the object — only set for fixed-size
                               # scalar kinds (float/int/bool/enum), which is what makes them safely
                               # in-place-writable; None for variable-size kinds (string) and for
                               # pptr (writable in principle, deliberately not exposed — see module
                               # docstring's scope boundary).


def _read_aligned_string(data: bytes, pos: int) -> tuple:
    length = struct.unpack_from("<i", data, pos)[0]
    if length < 0 or pos + 4 + length > len(data):
        raise AssetLayoutError(f"Implausible string length {length} at offset {pos}")
    s = data[pos + 4: pos + 4 + length].decode("utf-8", errors="replace")
    newpos = pos + 4 + length
    pad = (4 - newpos % 4) % 4
    return s, newpos + pad


def _read_pptr(data: bytes, pos: int) -> tuple:
    fid, pid = struct.unpack_from("<iq", data, pos)
    return {"m_FileID": fid, "m_PathID": pid}, pos + 12


def _read_fields(type_name: str, data: bytes, pos: int, path_prefix: str, results: list) -> int:
    """Recursively parses `type_name`'s fields (base class fields first, matching real Unity
    serialization order) starting at byte offset `pos`, appending FieldValue entries to `results`.
    Returns the new position. Raises AssetLayoutError on any field this module doesn't know how to
    parse — never guesses past that point, since every subsequent offset would be wrong anyway."""
    node = LAYOUT.get(type_name)
    if node is None:
        raise AssetLayoutError(f"No reflected layout for type {type_name!r} — "
                                f"re-run reflect_unit_layout.ps1?")
    if node["base"]:
        pos = _read_fields(node["base"], data, pos, path_prefix, results)

    for f in node["fields"]:
        full_path = f"{path_prefix}.{f['name']}" if path_prefix else f["name"]
        kind = f["kind"]

        if kind == "float":
            val = struct.unpack_from("<f", data, pos)[0]
            results.append(FieldValue(full_path, kind, val, pos))
            pos += 4
        elif kind in ("int", "enum"):
            val = struct.unpack_from("<i", data, pos)[0]
            results.append(FieldValue(full_path, kind, val, pos))
            pos += 4
        elif kind == "bool":
            val = data[pos] != 0
            results.append(FieldValue(full_path, kind, val, pos))
            pos += 4   # 1 real byte + 3 padding — see module docstring
        elif kind == "string":
            val, pos = _read_aligned_string(data, pos)
            results.append(FieldValue(full_path, kind, val, None))
        elif kind == "pptr":
            val, pos = _read_pptr(data, pos)
            results.append(FieldValue(full_path, kind, val, None))
        elif kind == "class":
            if f["target"] == "UnityEngine.Vector3":
                x, y, z = struct.unpack_from("<3f", data, pos)
                results.append(FieldValue(f"{full_path}.x", "float", x, pos))
                results.append(FieldValue(f"{full_path}.y", "float", y, pos + 4))
                results.append(FieldValue(f"{full_path}.z", "float", z, pos + 8))
                pos += 12
            else:
                pos = _read_fields(f["target"], data, pos, full_path, results)
        elif kind == "array":
            count = struct.unpack_from("<i", data, pos)[0]
            if count < 0 or count > 100000:
                raise AssetLayoutError(f"Implausible array count {count} for {full_path} at offset {pos}")
            pos += 4
            if f.get("elemIsPptr"):
                for i in range(count):
                    _, pos = _read_pptr(data, pos)
            else:
                for i in range(count):
                    pos = _read_fields(f["target"], data, pos, f"{full_path}[{i}]", results)
        elif kind == "unsupported" and "Nullable" in f.get("reason", ""):
            # Confirmed real, not assumed: Unity's serializer does not support System.Nullable<T> at
            # all, so a field of this type contributes ZERO bytes to the real object — it's simply
            # never written, not written-as-something-then-skippable. Verified by byte-exact match
            # on a real MissileDefinition object once this field was treated as fully absent.
            results.append(FieldValue(full_path, "absent", None, None))
        else:
            raise AssetLayoutError(
                f"Field {full_path} on {type_name} is unsupported "
                f"({f.get('reason', 'unknown reason')}) — layout is incomplete past this point")
    return pos


def read_object(data: bytes, type_name: str) -> list:
    """Parses one real MonoBehaviour-backed object's raw bytes (the object's own byte range within
    a .assets file — see how ObjectReader.byte_start/byte_size are used by callers) into a flat list
    of FieldValue entries, covering the real head fields AND the script's own `type_name` fields.
    Raises AssetLayoutError, never returns partial/guessed data, if anything doesn't match."""
    return read_object_checked(data, type_name)[0]


def read_object_checked(data: bytes, type_name: str) -> tuple:
    """Same as read_object, but also returns the exact byte position parsing ended at — callers that
    want byte-exact validation (parsed end position == the object's real total size) should use this
    instead of read_object, which only surfaces the field list."""
    results = []
    pos = 0
    # Head: m_GameObject (PPtr), m_Enabled (bool), m_Script (PPtr), m_Name (string)
    val, pos = _read_pptr(data, pos)
    results.append(FieldValue("m_GameObject", "pptr", val, None))
    results.append(FieldValue("m_Enabled", "bool", data[pos] != 0, pos))
    pos += 4
    val, pos = _read_pptr(data, pos)
    results.append(FieldValue("m_Script", "pptr", val, None))
    val, pos = _read_aligned_string(data, pos)
    results.append(FieldValue("m_Name", "string", val, None))

    pos = _read_fields(type_name, data, pos, "", results)
    return results, pos


def find_field(values: list, path: str) -> Optional[FieldValue]:
    return next((v for v in values if v.path == path), None)


def write_field_in_place(data: bytearray, field: FieldValue, new_value) -> None:
    """Overwrites ONE fixed-size scalar field's bytes in place, at its already-known real offset —
    never resizes the buffer, so nothing else in the object (or file) shifts. Refuses any field
    without a resolved `offset` (string/pptr/array — see FieldValue's docstring) rather than risk
    corrupting the surrounding bytes."""
    if field.offset is None:
        raise AssetLayoutError(
            f"{field.path} ({field.kind}) has no fixed offset — not safe to write in place "
            f"(string/array/pptr fields would need the whole file rebuilt, not attempted here)")
    if field.kind == "float":
        struct.pack_into("<f", data, field.offset, float(new_value))
    elif field.kind in ("int", "enum"):
        struct.pack_into("<i", data, field.offset, int(new_value))
    elif field.kind == "bool":
        data[field.offset] = 1 if new_value else 0
    else:
        raise AssetLayoutError(f"Don't know how to write kind {field.kind!r} for {field.path}")


# ── Real-file orchestration: find a unit's object, back it up, write one field in place ─────────

def find_unit_object(assets_path, json_key: str):
    """Scans `assets_path` (real MonoBehaviour objects, e.g. resources.assets) for the ONE object
    whose real jsonKey matches, resolving its real compiled class name via its m_Script reference
    (never guessed from the object's own display name, which can differ from its jsonKey). Returns
    (class_name, byte_start, byte_size) or None if not found. This does a full linear scan (tens of
    thousands of objects) — slow enough that callers should cache the result, not call this per
    keystroke."""
    import UnityPy
    env = UnityPy.load(str(assets_path))
    for o in env.objects:
        if o.type.name != "MonoBehaviour":
            continue
        try:
            head = o.parse_monobehaviour_head()
        except Exception:
            continue
        if head.m_Name != json_key:
            continue
        try:
            script_obj = head.m_Script.deref_parse_as_object()
        except Exception:
            continue
        class_name = script_obj.m_ClassName
        if class_name not in LAYOUT:
            continue
        return class_name, o.byte_start, o.byte_size
    return None


def scan_all_units(assets_path) -> dict:
    """{class_name: {json_key: real_unitName_or_""}} for every real DIRECT_WRITE_TYPES object
    currently in `assets_path`, read directly off the player's own installed game files — the
    antidote to unit_stat_catalog.py's bundled known_units_seed.json, which is a one-time snapshot
    that goes stale the moment the game ships new units/weapons in a future update. Also the
    antidote to unit names only being knowable via the companion plugin's live dump: UnitDefinition
    .unitName is a plain string field, already fully readable through read_object() with no plugin
    or running game needed — confirmed real (AttackHelo1.unitName == "SAH-46 Chicane", read straight
    off disk, 2026-08-17). One full pass over every MonoBehaviour header to find the ~130-150
    DIRECT_WRITE_TYPES objects (confirmed ~16,000 total objects, well under a second — see the perf
    note in find_unit_object), then one small extra read per matched object for its unitName —
    trivial added cost, safe to call synchronously, no thread needed."""
    import UnityPy
    env = UnityPy.load(str(assets_path))
    result = {cls: {} for cls in DIRECT_WRITE_TYPES}
    for o in env.objects:
        if o.type.name != "MonoBehaviour":
            continue
        try:
            head = o.parse_monobehaviour_head()
            class_name = head.m_Script.deref_parse_as_object().m_ClassName
        except Exception:
            continue
        if class_name not in result or not head.m_Name:
            continue
        unit_name = ""
        try:
            reader = o.reader
            reader.Position = o.byte_start
            data = reader.read_bytes(o.byte_size)
            name_field = find_field(read_object(data, class_name), "unitName")
            if isinstance(name_field.value, str):
                unit_name = name_field.value.strip()
        except Exception:
            pass
        result[class_name][head.m_Name] = unit_name
    return result


def scan_all_unit_keys(assets_path) -> dict:
    """{class_name: sorted [json_key, ...]} — see scan_all_units, which this is a thin projection
    of, for callers that only need the key list, not the real names."""
    return {cls: sorted(names.keys()) for cls, names in scan_all_units(assets_path).items()}


def resources_assets_path(game_root) -> Path:
    return Path(game_root) / "NuclearOption_Data" / "resources.assets"


def write_field_in_file(assets_path: Path, byte_start: int, field: FieldValue, new_value) -> None:
    """Patches ONE fixed-size scalar field's bytes directly in the real .assets file, in place, at
    its exact real file offset (byte_start + field.offset) — never rewrites or resizes the file, so
    every other object in it (there can be tens of thousands) is completely untouched. Callers MUST
    back up the original object bytes first (see backup_object_bytes) and confirm is_game_running()
    is False — neither check is repeated here."""
    if field.offset is None:
        raise AssetLayoutError(
            f"{field.path} ({field.kind}) has no fixed offset — not safe to write in place")
    if field.kind == "float":
        packed = struct.pack("<f", float(new_value))
    elif field.kind in ("int", "enum"):
        packed = struct.pack("<i", int(new_value))
    elif field.kind == "bool":
        packed = bytes([1 if new_value else 0])
    else:
        raise AssetLayoutError(f"Don't know how to write kind {field.kind!r} for {field.path}")

    with open(assets_path, "r+b") as fh:
        fh.seek(byte_start + field.offset)
        fh.write(packed)


# Queue entries whose "type" is one of these five concrete classes can potentially be applied
# directly to the game's own file — anything else (AircraftParameters, whose scalar fields sit
# behind unresolved array element types — see module docstring) is out of scope for this path and
# stays companion-plugin-only.
DIRECT_WRITE_TYPES = frozenset(
    {"AircraftDefinition", "VehicleDefinition", "ShipDefinition", "BuildingDefinition", "MissileDefinition"})


@dataclass
class ApplyOutcome:
    entry: dict            # the original queue entry ({"type","key","field","value","label"})
    status: str             # "applied" / "skipped" / "error"
    message: str
    backup_path: Optional[Path] = None


def apply_queue_entries_to_game_files(game_root, entries: list, backups_dir: Path) -> list:
    """Applies every queue `entries` whose type is direct-writable straight to the real
    resources.assets file, in place — no companion plugin, no running game required. Refuses
    outright (raises AssetLayoutError) if the game is currently running, checked ONCE up front
    rather than per-entry, since the whole batch should succeed or refuse together. Every touched
    object's ORIGINAL bytes are backed up before its first write (see backup_object_bytes) — one
    backup per distinct (assets file, json_key), even if several of its fields are being changed
    this same run, so a single restore undoes all of them together.

    Returns a list of ApplyOutcome, one per input entry, in the same order — entries whose type
    isn't in DIRECT_WRITE_TYPES, whose object/field can't be found, or whose field has no fixed
    offset (string fields) are reported as "skipped", never silently dropped. A per-entry write
    failure is reported as "error" and does NOT stop the remaining entries from being attempted —
    each is an independent, already-backed-up, same-size in-place patch."""
    if is_game_running():
        raise AssetLayoutError(
            "Nuclear Option is currently running — close it before writing directly to game files.")

    assets_path = resources_assets_path(game_root)
    if not assets_path.is_file():
        raise AssetLayoutError(f"resources.assets not found at {assets_path}")

    outcomes = []
    object_cache = {}     # json_key -> (class_name, byte_start, byte_size) or None (not found)
    backed_up_keys = set()  # json_key already backed up this run

    for entry in entries:
        type_name, key, field_name = entry.get("type"), entry.get("key"), entry.get("field")
        if type_name not in DIRECT_WRITE_TYPES:
            outcomes.append(ApplyOutcome(entry, "skipped",
                                          f'"{type_name}" isn\'t supported by direct file writing yet '
                                          f'— use the companion plugin for this field instead.'))
            continue

        if key not in object_cache:
            object_cache[key] = find_unit_object(assets_path, key)
        found = object_cache[key]
        if found is None:
            outcomes.append(ApplyOutcome(entry, "skipped", f'No object named "{key}" found in resources.assets.'))
            continue
        class_name, byte_start, byte_size = found
        if class_name != type_name:
            outcomes.append(ApplyOutcome(
                entry, "skipped",
                f'"{key}" is really a {class_name}, not {type_name} — queue entry looks stale.'))
            continue

        with open(assets_path, "rb") as fh:
            fh.seek(byte_start)
            original_bytes = fh.read(byte_size)
        try:
            values = read_object(original_bytes, class_name)
        except AssetLayoutError as e:
            outcomes.append(ApplyOutcome(entry, "error", f"Couldn't parse {key}: {e}"))
            continue

        field = find_field(values, field_name)
        if field is None:
            outcomes.append(ApplyOutcome(entry, "skipped", f'"{field_name}" not found on {key}.'))
            continue
        if field.offset is None:
            outcomes.append(ApplyOutcome(
                entry, "skipped",
                f'"{field_name}" ({field.kind}) has no fixed offset — not writable in place yet.'))
            continue

        backup_path = None
        cache_key = (str(assets_path), key)
        if cache_key not in backed_up_keys:
            backup_path = backup_object_bytes(backups_dir, f"{assets_path.name}_{key}", original_bytes)
            backed_up_keys.add(cache_key)

        try:
            new_value = float(entry["value"]) if field.kind == "float" else \
                int(float(entry["value"])) if field.kind in ("int", "enum") else \
                entry["value"] in ("true", "True", "1", True)
            write_field_in_file(assets_path, byte_start, field, new_value)
        except Exception as e:
            outcomes.append(ApplyOutcome(entry, "error", f"Write failed for {key}.{field_name}: {e}", backup_path))
            continue

        outcomes.append(ApplyOutcome(entry, "applied", f"{key}.{field_name} = {new_value}", backup_path))

    return outcomes

"""
Rewired registry engine — reads and surgically edits Nuclear Option's REAL controller keybindings.

Rewired (the input middleware this game uses — confirmed by Rewired_Core.dll / Rewired_Windows.dll
in NuclearOption_Data/Managed) saves every binding as Unity PlayerPrefs under
HKEY_CURRENT_USER\\Software\\Shockfront\\NuclearOption, one REG_BINARY value per (player, device
type, action category, hardware). Each value name is itself a structured string, e.g.:

    RewiredSaveData|playerName=Player0|dataType=ControllerMap|kv=2|controllerMapType=JoystickMap|
    categoryId=0|layoutId=0|hardwareGuid=d74a350e-fe8b-4e9e-bbcd-efff16d34115|duplicate=0_h1237724504

(the trailing `_h<digits>` is Unity's own PlayerPrefs key-name hash suffix — opaque to us, never
recomputed, since every write here goes back into the exact same existing value name it was read
from; nothing new is ever created with a fabricated name.)

The value's BYTES are the real surprise, confirmed empirically against a real captured value on this
machine (not assumed from the XML's own header): despite the embedded `<?xml ... encoding="utf-16"?>`
declaration, the actual on-disk bytes are plain single-byte UTF-8 text, plus exactly one trailing
0x00 byte. Round-tripped byte-for-byte in testing before this module was written.

Editing strategy — surgical string substitution, NOT a full XML tree parse/rebuild: every
<ActionElementMap>...</ActionElementMap> block is kept as its own exact original substring
(ActionElementMap.raw); rebind/unbind/add only ever replace or splice around that exact substring,
so everything else in a real user's save data is preserved byte-for-byte, the same discipline
config_editor_tab.py already uses for BepInEx .cfg files. This is real, live user data controlling
their actual game controls, not a disposable mod file — every write is preceded by a timestamped
backup of the untouched original bytes (see backup_value), and is refused outright while the game
process is running (see is_game_running).
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

REG_PATH = r"Software\Shockfront\NuclearOption"

_VALUE_NAME_RE = re.compile(r"^RewiredSaveData\|(.+)_h\d+$")
_AEM_RE = re.compile(r"<ActionElementMap>(.*?)</ActionElementMap>", re.S)
_FIELD_RE = re.compile(r"<(\w+)>(.*?)</\1>")

_CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


def _parse_value_name(name: str) -> dict:
    m = _VALUE_NAME_RE.match(name)
    if not m:
        return {}
    result = {}
    for part in m.group(1).split("|"):
        if "=" in part:
            k, _, v = part.partition("=")
            result[k] = v
    return result


def registry_key_exists() -> bool:
    """False before the game has ever been launched (or Rewired hasn't saved anything yet) — a
    normal, expected state, not an error."""
    import winreg
    try:
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH)
        return True
    except OSError:
        return False


def list_joystick_maps() -> list:
    """Every real saved JoystickMap ControllerMap value currently in the registry — enumerated live,
    never hardcoded, since which categories/hardware exist depends entirely on what the user has
    actually bound. Each entry: {"value_name", "hardware_guid", "category_id", "layout_id",
    "duplicate", "player_name"}. Deliberately excludes the companion "ControllerMap_KnownActionIds"
    sibling values and any non-JoystickMap (Keyboard/Mouse) maps."""
    import winreg
    results = []
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH)
    except OSError:
        return results
    try:
        i = 0
        while True:
            try:
                name = winreg.EnumValue(key, i)[0]
            except OSError:
                break
            i += 1
            parsed = _parse_value_name(name)
            if parsed.get("dataType") != "ControllerMap" or parsed.get("controllerMapType") != "JoystickMap":
                continue
            try:
                results.append({
                    "value_name": name,
                    "hardware_guid": parsed.get("hardwareGuid", ""),
                    "category_id": int(parsed.get("categoryId", -1)),
                    "layout_id": int(parsed.get("layoutId", 0)),
                    "duplicate": int(parsed.get("duplicate", 0)),
                    "player_name": parsed.get("playerName", ""),
                })
            except ValueError:
                continue
    finally:
        winreg.CloseKey(key)
    return results


def find_joystick_map(hardware_guid: str, category_id: int, duplicate: int = 0) -> Optional[dict]:
    for m in list_joystick_maps():
        if m["hardware_guid"].lower() == hardware_guid.lower() and \
                m["category_id"] == category_id and m["duplicate"] == duplicate:
            return m
    return None


def read_value_bytes(value_name: str) -> Optional[bytes]:
    """The exact raw REG_BINARY bytes currently saved for this value — callers should keep this
    around and pass it to backup_value() before writing anything back, so the backup is always the
    real bytes that were actually on disk, not a re-derivation."""
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH)
    except OSError:
        return None
    try:
        data, _ = winreg.QueryValueEx(key, value_name)
    except OSError:
        return None
    finally:
        winreg.CloseKey(key)
    return data


def read_map_xml(value_name: str) -> Optional[str]:
    """The real saved XML text for one JoystickMap value, or None if it's missing or doesn't match
    the confirmed real on-disk shape (UTF-8 bytes + one trailing NUL) — refuses to guess-decode
    anything that looks unexpected rather than risk silently misreading real user data."""
    raw = read_value_bytes(value_name)
    if not raw or raw[-1:] != b"\x00":
        return None
    try:
        return raw[:-1].decode("utf-8")
    except UnicodeDecodeError:
        return None


@dataclass
class ActionElementMap:
    action_category_id: int
    action_id: int
    element_type: int          # 0 = Axis, 1 = Button, 2 = CompoundElement (Rewired's ControllerElementType)
    element_identifier_id: int
    axis_range: int
    invert: bool
    axis_contribution: int
    enabled: bool
    section: str                # "buttonMaps" or "axisMaps" — which real list this came from
    raw: str                    # the exact original <ActionElementMap>...</ActionElementMap> substring


def _parse_bool(s: str) -> bool:
    return (s or "").strip().lower() == "true"


def parse_action_element_maps(xml_text: str) -> list:
    """Every real binding in this JoystickMap, from BOTH the <buttonMaps> and <axisMaps> sections
    (confirmed real: Rewired keeps button-type and axis-type bindings in two separate sibling lists
    under the same JoystickMap root). Regex-based on purpose — see module docstring — so every
    result keeps `.raw`, its own exact original substring, for byte-exact surgical edits."""
    results = []
    for section in ("buttonMaps", "axisMaps"):
        section_m = re.search(rf"<{section}>(.*?)</{section}>", xml_text, re.S)
        if not section_m:
            continue
        for block_m in _AEM_RE.finditer(section_m.group(1)):
            fields = dict(_FIELD_RE.findall(block_m.group(1)))
            try:
                results.append(ActionElementMap(
                    action_category_id=int(fields.get("actionCategoryId", -1)),
                    action_id=int(fields.get("actionId", -1)),
                    element_type=int(fields.get("elementType", -1)),
                    element_identifier_id=int(fields.get("elementIdentifierId", -1)),
                    axis_range=int(fields.get("axisRange", 0)),
                    invert=_parse_bool(fields.get("invert", "false")),
                    axis_contribution=int(fields.get("axisContribution", 0)),
                    enabled=_parse_bool(fields.get("enabled", "true")),
                    section=section,
                    raw=block_m.group(0),
                ))
            except (ValueError, TypeError):
                continue
    return results


def bindings_for_element(entries: list, element_identifier_id: int) -> list:
    """Usually 0 or 1 entries, but Rewired does allow more than one action bound to the same
    physical element, so this always returns a list rather than assuming exactly one."""
    return [e for e in entries if e.element_identifier_id == element_identifier_id]


def rebind_action(xml_text: str, entry: "ActionElementMap", new_action_id: int,
                   new_action_category_id: int) -> str:
    """Replaces ONLY entry's <actionId>/<actionCategoryId> values, inside its own exact original
    substring — every other byte of the file (including every OTHER binding) is untouched."""
    new_block = entry.raw
    new_block = re.sub(r"(<actionCategoryId>)-?\d+(</actionCategoryId>)",
                        rf"\g<1>{new_action_category_id}\g<2>", new_block, count=1)
    new_block = re.sub(r"(<actionId>)-?\d+(</actionId>)",
                        rf"\g<1>{new_action_id}\g<2>", new_block, count=1)
    return xml_text.replace(entry.raw, new_block, 1)


def unbind(xml_text: str, entry: "ActionElementMap") -> str:
    return xml_text.replace(entry.raw, "", 1)


def add_binding(xml_text: str, element_identifier_id: int, element_type: int,
                 action_id: int, action_category_id: int) -> str:
    """Inserts a brand-new <ActionElementMap> for a currently-unbound physical element, using the
    exact same field set Rewired's own real saved data uses (confirmed against a real captured
    JoystickMap), into the correct section for element_type (0=Axis -> axisMaps, else -> buttonMaps)
    so the game reads it back exactly as if it had been bound in-game."""
    section = "axisMaps" if element_type == 0 else "buttonMaps"
    new_block = (
        "<ActionElementMap>"
        f"<actionCategoryId>{action_category_id}</actionCategoryId>"
        f"<actionId>{action_id}</actionId>"
        f"<elementType>{element_type}</elementType>"
        f"<elementIdentifierId>{element_identifier_id}</elementIdentifierId>"
        "<axisRange>0</axisRange><invert>false</invert><axisContribution>0</axisContribution>"
        "<keyboardKeyCode>0</keyboardKeyCode><modifierKey1>0</modifierKey1>"
        "<modifierKey2>0</modifierKey2><modifierKey3>0</modifierKey3><enabled>true</enabled>"
        "</ActionElementMap>"
    )
    close_tag = f"</{section}>"
    idx = xml_text.find(close_tag)
    if idx == -1:
        raise ValueError(f'This JoystickMap has no <{section}> section to add a binding to.')
    return xml_text[:idx] + new_block + xml_text[idx:]


def is_game_running() -> bool:
    """True if NuclearOption.exe currently appears in the process list. Checked via `tasklist`
    (stdlib subprocess, no new dependency) — writing bindings while the game's own live Rewired
    instance is running risks a race against its exit-time save silently undoing this edit. On any
    failure to check (unexpected, but tasklist could be missing/blocked), returns False rather than
    permanently locking the feature — the backup taken before every write is the real safety net."""
    try:
        proc = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq NuclearOption.exe", "/NH"],
            capture_output=True, text=True, timeout=10, creationflags=_CREATE_NO_WINDOW,
        )
        return "NuclearOption.exe" in (proc.stdout or "")
    except Exception:
        return False


def backup_value(backups_dir: Path, value_name: str, raw_bytes: bytes) -> Path:
    """Writes a timestamped copy of the ORIGINAL, untouched registry bytes into `backups_dir` before
    any write — this is a real user's real keybinds, not a disposable mod file, so every edit here
    has a way back. Never overwrites a previous backup (timestamped filename)."""
    backups_dir = Path(backups_dir)
    backups_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", value_name)[:150]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backups_dir / f"{safe_name}_{ts}.bin"
    dest.write_bytes(raw_bytes)
    return dest


def write_map_xml(value_name: str, new_xml_text: str) -> None:
    """Writes new_xml_text back into the SAME existing registry value, re-encoded the same real way
    it was read (UTF-8 bytes + one trailing NUL — see module docstring). Callers MUST back up the
    original bytes first (read_value_bytes + backup_value) and confirm is_game_running() is False
    before calling this — neither check is repeated here."""
    import winreg
    new_bytes = new_xml_text.encode("utf-8") + b"\x00"
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE)
    try:
        winreg.SetValueEx(key, value_name, 0, winreg.REG_BINARY, new_bytes)
    finally:
        winreg.CloseKey(key)

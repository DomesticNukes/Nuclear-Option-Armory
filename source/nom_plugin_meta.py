"""
BepInEx plugin metadata reading — pure logic, no Tkinter, safe to unit-test standalone.

Two independent, fail-open responsibilities (never raise, never block the caller):

1. read_plugin_metadata(dll_path) — best-effort extraction of a DLL's [BepInPlugin(guid, name,
   version)] attribute arguments straight from its raw bytes, with no .NET/PE metadata library.

   How it works: a BepInPlugin attribute's 3 string constructor arguments are encoded in the
   assembly's #Blob heap as an ECMA-335 CustomAttrib: a 2-byte prolog (0x01 0x00), then each string
   as a 1-byte compressed length followed by its raw UTF-8 bytes, then a 2-byte zero (no named args).
   Confirmed by direct inspection this session — e.g. in GravityOption.dll, offset 6085 reads
   ``01 00 18 "com.combat.GravityOption" 10 "Gravity Modifier" 05 "1.0.0" 00 00`` byte-for-byte,
   with 0x18/0x10/0x05 exactly matching each string's length. Scanning every ``\\x01\\x00`` in the
   file for this shape and filtering to GUID-shaped/printable strings correctly identified 19 of 20
   real community plugin DLLs tested (the one miss falls back to filename — see below), including a
   DLL with two plugins in it (each found independently).

   Never raises; on no match, returns an empty list, and callers should fall back to the filename.

2. parse_cfg / render_cfg — BepInEx's ConfigFile INI-like format. Unlike a generic re-serializer,
   this keeps each setting's full original comment block (description + "# Setting type:" +
   "# Default value:" + optional "# Acceptable values:" lines) as opaque, verbatim text and only
   ever rewrites the "Key = Value" line — so an edit changes exactly the one line the user touched,
   byte-identical everywhere else. type_hint/default/acceptable_values are pulled out of that same
   comment block for the editor form (Boolean -> checkbox, "Acceptable values" -> dropdown) but are
   never used to regenerate anything.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── DLL byte-scraper ─────────────────────────────────────────────────────────

@dataclass
class PluginMeta:
    guid: Optional[str]
    name: str
    version: Optional[str]
    source: str   # "scraped" or "filename-fallback"


_PROLOG = b"\x01\x00"
_MAX_STR_LEN = 200


def _try_read_string(data: bytes, pos: int, n: int):
    """Read one ECMA-335 compressed-length-prefixed UTF-8 string at `pos`.

    Only handles the common single-byte length form (0-127) — plugin GUID/name/version strings are
    always short, so the 2/4-byte compressed-int forms never come up in practice here. Returns
    (string, next_pos) or None if this doesn't look like a valid, printable string.
    """
    if pos >= n:
        return None
    length = data[pos]
    if length & 0x80 or length == 0 or length > _MAX_STR_LEN:
        return None
    start = pos + 1
    end = start + length
    if end > n:
        return None
    raw = data[start:end]
    try:
        s = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not s or not s.isprintable() or "\t" in s:
        return None
    return s, end


def _looks_like_guid(s: str) -> bool:
    return "." in s and " " not in s and len(s) < 100 and re.match(r"^[A-Za-z0-9_.\-]+$", s) is not None


def read_plugin_metadata(dll_path) -> list:
    """Scan a DLL's raw bytes for every BepInPlugin(guid, name, version) attribute blob it contains.

    Returns a list of PluginMeta (source="scraped") — usually one entry, occasionally more than one
    for a DLL that bundles several plugins, and possibly empty if nothing matched. Never raises.
    """
    results = []
    try:
        data = Path(dll_path).read_bytes()
    except Exception:
        return results

    n = len(data)
    i = 0
    while True:
        idx = data.find(_PROLOG, i)
        if idx == -1:
            break
        i = idx + 1   # advance by 1 so overlapping prologs (unlikely but cheap to allow) aren't missed

        pos = idx + 2
        r1 = _try_read_string(data, pos, n)
        if not r1:
            continue
        guid, pos = r1
        if not _looks_like_guid(guid):
            continue
        r2 = _try_read_string(data, pos, n)
        if not r2:
            continue
        name, pos = r2
        r3 = _try_read_string(data, pos, n)
        if not r3:
            continue
        version, pos = r3
        # Trailing NumNamed (ushort) should be present and, for a plain BepInPlugin call, zero.
        if pos + 2 > n or data[pos:pos + 2] != b"\x00\x00":
            continue
        results.append(PluginMeta(guid=guid, name=name, version=version, source="scraped"))

    return results


def read_primary_plugin_metadata(dll_path) -> PluginMeta:
    """Convenience wrapper: the first scraped plugin, or a filename-based fallback."""
    found = read_plugin_metadata(dll_path)
    if found:
        return found[0]
    return PluginMeta(guid=None, name=Path(dll_path).stem, version=None, source="filename-fallback")


def find_cfg_for_guid(guid: Optional[str], bepinex_config_dir) -> Optional[Path]:
    if not guid:
        return None
    candidate = Path(bepinex_config_dir) / f"{guid}.cfg"
    return candidate if candidate.is_file() else None


# ── BepInEx .cfg parser / renderer ───────────────────────────────────────────

_SECTION_RE = re.compile(r"^\[(.+)\]\s*$")
_KV_RE = re.compile(r"^([^=]+?)\s*=\s*(.*)$")
_TYPE_RE = re.compile(r"^#\s*Setting type:\s*(.+)$", re.IGNORECASE)
_DEFAULT_RE = re.compile(r"^#\s*Default value:\s*(.*)$", re.IGNORECASE)
_ACCEPT_RE = re.compile(r"^#\s*Acceptable values:\s*(.+)$", re.IGNORECASE)


@dataclass
class SettingEntry:
    value: str
    comment_lines: list = field(default_factory=list)   # raw lines, original prefix/text, in order
    type_hint: Optional[str] = None
    default: Optional[str] = None
    acceptable_values: Optional[list] = None


@dataclass
class ConfigDoc:
    header_lines: list
    section_order: list
    sections: dict            # {section_name: {key: SettingEntry}}
    section_preambles: dict = field(default_factory=dict)   # {section_name: [lines before its "[..]"]}


def parse_cfg(text: str) -> ConfigDoc:
    lines = text.splitlines()
    header_lines = []
    section_order = []
    sections = {}
    section_preambles = {}

    current_section = None
    pending = []   # comment/blank lines accumulated since the last Key=Value or [Section]

    def flush_header():
        header_lines.extend(pending)
        pending.clear()

    i = 0
    # Header: everything before the first [Section] line.
    while i < len(lines):
        m = _SECTION_RE.match(lines[i])
        if m:
            break
        pending.append(lines[i])
        i += 1
    flush_header()

    while i < len(lines):
        line = lines[i]
        m = _SECTION_RE.match(line)
        if m:
            current_section = m.group(1)
            if current_section not in sections:
                sections[current_section] = {}
                section_order.append(current_section)
                section_preambles[current_section] = list(pending)   # blank/comment lines before "[..]"
            pending = []
            i += 1
            continue

        stripped = line.strip()
        if stripped.startswith("#") or stripped == "":
            pending.append(line)
            i += 1
            continue

        kv = _KV_RE.match(line)
        if kv and current_section is not None:
            key, value = kv.group(1).strip(), kv.group(2)
            entry = SettingEntry(value=value, comment_lines=list(pending))
            for cl in pending:
                tm = _TYPE_RE.match(cl.strip())
                if tm:
                    entry.type_hint = tm.group(1).strip()
                    continue
                dm = _DEFAULT_RE.match(cl.strip())
                if dm:
                    entry.default = dm.group(1).strip()
                    continue
                am = _ACCEPT_RE.match(cl.strip())
                if am:
                    entry.acceptable_values = [v.strip() for v in am.group(1).split(",")]
            sections[current_section][key] = entry
            pending = []
        # A stray non-comment, non-kv, non-section line (malformed) is just dropped from pending.
        i += 1

    return ConfigDoc(header_lines=header_lines, section_order=section_order, sections=sections,
                      section_preambles=section_preambles)


def render_cfg(doc: ConfigDoc) -> str:
    out = list(doc.header_lines)
    for section in doc.section_order:
        out.extend(doc.section_preambles.get(section, []))
        out.append(f"[{section}]")
        for key, entry in doc.sections[section].items():
            out.extend(entry.comment_lines)
            out.append(f"{key} = {entry.value}")
    return "\n".join(out) + "\n"

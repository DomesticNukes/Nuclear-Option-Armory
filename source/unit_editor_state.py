"""
Unit Editor shared state — pure logic, no Tkinter. The queue of pending stat overrides and the
permanent baseline cache of first-ever-seen live values, shared by EVERY Unit Editor tab
(Aircraft/Vehicle/Ship/Building/Missile/Ammo, and the Queue & Build tab).

One instance per app session, created lazily via `UnitEditorState.get(app)` and stashed on
`app._unit_editor_state` — every tab reads/writes the SAME queue and baseline rather than each
category keeping (and fragmenting) its own copy, so "Build Override Plugin" always produces ONE
companion plugin covering every category's queued overrides together, and clicking a field's
reset button in the Aircraft tab is visible everywhere else that field appears too.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import unit_asset_layout as ual
import unit_editor_engine as uee


class UnitEditorState:
    def __init__(self, app):
        self.app = app
        self.queue = []      # [{"type":..., "key":..., "field":..., "value":..., "label":...}, ...]
        self.baseline = {}    # {(type, key, field): value_str} — first-ever-seen live values, kept forever
        self._listeners = []
        self._load_state()
        self._load_baseline()

    @classmethod
    def get(cls, app) -> "UnitEditorState":
        state = getattr(app, "_unit_editor_state", None)
        if state is None:
            state = cls(app)
            app._unit_editor_state = state
        return state

    def add_listener(self, fn):
        """`fn()` is called whenever the queue changes (add/remove) — lets every open tab stay in
        sync without polling. Errors from one listener never block the others."""
        self._listeners.append(fn)

    def _notify(self):
        for fn in list(self._listeners):
            try:
                fn()
            except Exception:
                pass

    # ── Queue persistence ────────────────────────────────────────────────

    def _state_file(self) -> Path:
        return self.app.state_path("unit_editor_queue.json")

    def _load_state(self):
        try:
            path = self._state_file()
            if path.exists():
                with open(path, encoding="utf-8") as f:
                    data = json.load(f) or {}
                self.queue = data.get("queue", [])
        except Exception:
            self.queue = []

    def save_state(self):
        try:
            tmp = self._state_file().with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"queue": self.queue}, f, indent=2)
            os.replace(tmp, self._state_file())
        except Exception:
            pass

    def upsert_queue_entry(self, entry):
        for i, existing in enumerate(self.queue):
            if (existing["type"], existing["key"], existing["field"]) == \
                    (entry["type"], entry["key"], entry["field"]):
                self.queue[i] = entry
                self._notify()
                return
        self.queue.append(entry)
        self._notify()

    def remove_queue_indices(self, indices):
        for idx in sorted(set(indices), reverse=True):
            if 0 <= idx < len(self.queue):
                del self.queue[idx]
        self._notify()

    # ── Baseline persistence ─────────────────────────────────────────────

    def _baseline_file(self) -> Path:
        return self.app.state_path("unit_editor_baseline.json")

    def _load_baseline(self):
        try:
            path = self._baseline_file()
            if path.exists():
                with open(path, encoding="utf-8") as f:
                    entries = json.load(f) or []
                self.baseline = {
                    (e["type"], e["key"], e["field"]): e["value"]
                    for e in entries if all(k in e for k in ("type", "key", "field", "value"))
                }
            else:
                self.baseline = {}
        except Exception:
            self.baseline = {}

    def save_baseline(self):
        try:
            tmp = self._baseline_file().with_suffix(".json.tmp")
            entries = [{"type": t_, "key": k_, "field": f_, "value": v_}
                       for (t_, k_, f_), v_ in self.baseline.items()]
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(entries, f, indent=2)
            os.replace(tmp, self._baseline_file())
        except Exception:
            pass

    def reset_baseline_entry(self, entry_type: str, key: str, field_name: str) -> bool:
        """Clears one field's captured original value so the NEXT live reading becomes the new
        baseline. Returns True if there was anything to clear."""
        removed = self.baseline.pop((entry_type, key, field_name), None)
        if removed is not None:
            self.save_baseline()
        return removed is not None

    def capture_new_baselines(self, values: dict):
        """`values` is {(type,key,field): value_str} from a fresh dump. Any key not already in
        the baseline is captured now and persisted forever; existing baseline entries are left
        untouched even if the dump's current value has since diverged (e.g. because an override
        is now active) — that's the whole point of a baseline."""
        newly_seen = {k: v for k, v in values.items() if k not in self.baseline}
        if newly_seen:
            self.baseline.update(newly_seen)
            self.save_baseline()

    # ── Deploy paths / dump IO ───────────────────────────────────────────

    def override_folder(self) -> Path:
        return Path(self.app._settings.get("plugin_library", "")) / uee.PLUGIN_ID

    def read_current_values(self) -> dict:
        """Reads the companion plugin's last dump (empty dict if it hasn't been built/deployed/run
        yet) and captures any newly-seen values into the baseline as a side effect."""
        dump_path = self.override_folder() / uee.DUMP_FILENAME
        values = uee.read_current_values(dump_path) if dump_path.is_file() else {}
        self.capture_new_baselines(values)
        return values

    def known_keys_for_type(self, type_name: str) -> list:
        """Every distinct `key` this app has ever seen dumped for `type_name`. The companion
        plugin reads these off the game's own master roster object (the same one its Encyclopedia/
        hangar screens use) on every dump pass, so this is normally the FULL in-game list, not
        just things you've happened to load/visit — it only falls short of that if the roster
        object itself hasn't loaded yet (rare; it's read defensively with a fallback to whatever's
        actually instantiated in memory). Empty list, not an error, if the plugin hasn't been
        built/deployed/run yet."""
        dump_path = self.override_folder() / uee.DUMP_FILENAME
        if not dump_path.is_file():
            return []
        names = {e.get("key") for e in uee.read_overrides_json(dump_path)
                 if isinstance(e, dict) and e.get("type") == type_name and e.get("key")}
        return sorted(names)

    def save_overrides(self) -> int:
        """Writes the current queue to the deployed override JSON. Raises on I/O failure — caller
        reports; returns the number of entries written."""
        self.save_state()
        entries = [{"type": e["type"], "key": e["key"], "field": e["field"], "value": e["value"]}
                   for e in self.queue]
        uee.write_overrides_json(self.override_folder() / uee.OVERRIDES_FILENAME, entries)
        return len(entries)

    # ── Direct-to-file writing (alternative to the companion plugin, see unit_asset_layout.py) ──

    def known_keys_from_game_files(self, definition_class: str) -> list:
        """Real jsonKeys for `definition_class` read straight off the player's own installed
        resources.assets (see unit_asset_layout.scan_all_units) — the FULL current roster for
        this game version, always, unlike the bundled seed list which is a fixed snapshot that goes
        stale the moment the game ships new units/weapons. Cached per app session (a fast ~1-2s scan,
        but no reason to repeat it on every keystroke); call refresh_game_file_units() to force a
        re-scan after a game update. Returns [] (never raises) if no game folder is set, the file
        can't be found, or scanning fails for any reason — this is a bonus source, not required."""
        return sorted(self._game_file_units().get(definition_class, {}).keys())

    def direct_file_current_value(self, class_name: str, key: str, field_name: str) -> Optional[str]:
        """This field's REAL current value, read straight off the player's own installed game
        files — the only way to see a genuinely current value for Missile-class fields (blastYield,
        pierceDamage, gLimit, maxTurnRate), which are direct-file-write-only and so can never
        appear in the companion plugin's dump (see unit_editor_engine._dump_targets). Works for any
        direct-writable class, not just Missile, but callers should prefer the live dump for classes
        that DO support it (self.read_current_values()) — this reads the file on disk, which won't
        reflect an active companion-plugin override even if one happens to be running right now.
        None (never raises) if no game folder is set, the object/field isn't found, or the field has
        no fixed offset (e.g. a string)."""
        try:
            assets_path = ual.resources_assets_path(self.app._settings.get("game_root", ""))
            if not assets_path.is_file():
                return None
            if class_name in ual._TWO_HOP_TYPES:
                found = ual.find_missile_component(assets_path, key)
                if found is None:
                    return None
                byte_start, byte_size = found
            elif class_name in ual.DIRECT_WRITE_TYPES:
                found = ual.find_unit_object(assets_path, key)
                if found is None or found[0] != class_name:
                    return None
                _, byte_start, byte_size = found
            else:
                return None
            with open(assets_path, "rb") as fh:
                fh.seek(byte_start)
                data = fh.read(byte_size)
            field = ual.find_field(ual.read_object(data, class_name), field_name)
            if field is None or field.offset is None:
                return None
            return f"{field.value:g}" if isinstance(field.value, float) else str(field.value)
        except Exception:
            return None

    def game_file_unit_name(self, definition_class: str, key: str) -> Optional[str]:
        """The real UnitDefinition.unitName for `key`, read straight off disk — no plugin build/
        deploy/run needed, since it's a plain string field like anything else scan_all_units reads.
        None if unknown or blank, so callers can fall back to another source rather than display an
        empty string."""
        name = self._game_file_units().get(definition_class, {}).get(key)
        return name if name else None

    def _game_file_units(self) -> dict:
        cache = getattr(self, "_game_file_units_cache", None)
        if cache is None:
            cache = self.refresh_game_file_units()
        return cache

    def refresh_game_file_units(self) -> dict:
        try:
            assets_path = ual.resources_assets_path(self.app._settings.get("game_root", ""))
            cache = ual.scan_all_units(assets_path) if assets_path.is_file() else {}
        except Exception:
            cache = {}
        self._game_file_units_cache = cache
        return cache

    def direct_writable_count(self) -> int:
        """How many queued entries COULD go through apply_direct_to_game_files — used to grey out
        that action when nothing queued qualifies (e.g. only AircraftParameters fields queued)."""
        return sum(1 for e in self.queue if e.get("type") in ual.DIRECT_WRITE_TYPES)

    def apply_direct_to_game_files(self) -> list:
        """Writes every direct-writable queued override straight into the real resources.assets,
        no companion plugin or running game needed. Raises AssetLayoutError up front if the game is
        currently running or the file can't be found; otherwise returns one ual.ApplyOutcome per
        queue entry (including the non-direct-writable ones, reported as "skipped") so the caller
        can show a full per-entry report rather than just a count."""
        game_root = self.app._settings.get("game_root", "")
        backups_dir = self.app.state_path("unit_editor_asset_backups")
        return ual.apply_queue_entries_to_game_files(game_root, self.queue, backups_dir)

    def is_plugin_built(self) -> bool:
        return (self.override_folder() / f"{uee.PLUGIN_ID}.dll").is_file()

    def install_built_dll(self, dll_bytes: bytes) -> Path:
        dest_folder = self.override_folder()
        dest_folder.mkdir(parents=True, exist_ok=True)
        dest_dll = dest_folder / f"{uee.PLUGIN_ID}.dll"
        dest_dll.write_bytes(dll_bytes)
        return dest_dll

    def export_named_mod(self, assembly_name: str, dll_bytes: bytes, entries: list) -> Path:
        """Writes a STANDALONE named mod — its own folder, own DLL, own frozen snapshot of
        overrides — distinct from the shared dev/test "Armory Stat Override" plugin
        (override_folder()/install_built_dll() above). `entries` is copied at export time, not
        live-linked to the shared queue, so editing the queue later doesn't silently change a mod
        you've already exported and possibly shared. Raises if `assembly_name` collides with the
        shared plugin's own folder name (uee.PLUGIN_ID) — exporting under that name would silently
        overwrite the shared dev plugin, which is never what "export as a NAMED mod" means."""
        if assembly_name == uee.PLUGIN_ID:
            raise ValueError(
                f'"{assembly_name}" is reserved for the shared Unit Editor plugin — pick a different name.')
        library = Path(self.app._settings.get("plugin_library", ""))
        dest_folder = library / assembly_name
        dest_folder.mkdir(parents=True, exist_ok=True)
        dest_dll = dest_folder / f"{assembly_name}.dll"
        dest_dll.write_bytes(dll_bytes)
        uee.write_overrides_json(dest_folder / uee.OVERRIDES_FILENAME,
                                  [{"type": e["type"], "key": e["key"], "field": e["field"], "value": e["value"]}
                                   for e in entries])
        return dest_folder

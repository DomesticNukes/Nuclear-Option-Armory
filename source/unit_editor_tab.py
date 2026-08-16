"""
Unit Editor category panel — one instance per category (Aircraft/Vehicle/Ship/Building/Missile),
each its own sub-tab under the UNIT EDITOR group. Browse real unit/aircraft stat fields
(unit_stat_catalog.py) with sliders, spinbox-paired entries, and checkboxes instead of hand-typing
a value + key, then queue overrides here — Save/Build/the Build Log live on the shared "Queue &
Build" tab (unit_editor_queue_tab.py), since one companion plugin covers every category's queued
overrides together (see unit_editor_state.py).

Mechanism recap (full detail in unit_stat_catalog.py / unit_editor_engine.py docstrings): this
game's unit stats are Unity ScriptableObject data whose serialization layout is stripped from the
release build, so this app cannot read/write the compiled asset files directly (verified with a
real UnityPy test). Instead, overrides are applied at runtime by a small generated BepInEx plugin,
the same technique every stat-touching mod already on this machine (Munitions Manager, AI Aircraft
Limit, Gravity Modifier) uses. That means changes take effect the next time the affected unit is
loaded in-game, not retroactively on units already spawned this session.
"""
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import theme
import ui_util
import unit_editor_state as ues
import unit_editor_widgets as uew
import unit_stat_catalog as usc
from i18n import t


class _Tab:
    def __init__(self, parent, app, category: str):
        self.app = app
        self.category = category
        self.state = ues.UnitEditorState.get(app)
        self.rows = {}       # (class_name, field_name) -> FieldRow
        self._build_widgets(parent)
        self._on_setup_done()

    # ── Widgets ──────────────────────────────────────────────────────────

    def _build_widgets(self, parent):
        intro = ttk.Frame(parent)
        intro.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Label(intro, text=t("{cat} Editor", cat=self.category), font=theme.FHEAD,
                  foreground=theme.GOLD).pack(anchor="w")
        ttk.Label(intro, text=t(
            "Overrides apply to the LIVE game via a small companion plugin, re-checked every few "
            "seconds — not by editing the game's files directly (verified not currently possible). "
            "Changes take effect next time the unit loads, not retroactively on anything already "
            "spawned this session. Queue overrides below, then switch to \"Queue & Build\" to save "
            "and build the plugin — one plugin covers every category together."),
            wraplength=780, justify="left", foreground=theme.DIM).pack(anchor="w", pady=(2, 0))

        picker = ttk.Frame(parent)
        picker.pack(fill="x", padx=8, pady=(4, 4))

        ttk.Label(picker, text=t("Unit")).pack(side=tk.LEFT)
        # The combobox itself shows/edits a friendly "Display Name (jsonKey)" string (falling back
        # to the bare jsonKey until a real name is known — see _live_unit_name); self.unit_var is
        # kept as the RESOLVED raw jsonKey, since everything downstream (queueing, the
        # AircraftParameters auto-follow, _resolve_type_and_key) needs the real key, never the
        # pretty label. self._key_by_display maps one back to the other.
        self._key_by_display = {}
        self.unit_display_var = tk.StringVar(value="")
        self.unit_combo = ttk.Combobox(picker, textvariable=self.unit_display_var, values=[],
                                        width=34, font=theme.F)
        self.unit_combo.pack(side=tk.LEFT, padx=(4, 6))
        ui_util.tooltip(self.unit_combo, t(
            "Known keys come from two places: your own saved missions and a bundled seed list "
            "(always available), and the game's own master roster, read by the companion plugin "
            "once you've built, deployed, and run it at least once — normally the FULL in-game "
            "list for this category. Real unit names (\"F-4 Phantom\" rather than \"Fighter1\") "
            "only appear once that live read has happened at least once — until then this shows "
            "the bare jsonKey. Pick one, or type any jsonKey by hand."))

        self.unit_var = tk.StringVar(value="")

        def _on_unit_display_changed(*_args):
            self.unit_var.set(self._key_by_display.get(self.unit_display_var.get(),
                                                         self.unit_display_var.get().strip()))
        self.unit_display_var.trace_add("write", _on_unit_display_changed)

        ttk.Button(picker, text=t("Refresh Known Units"), command=self._refresh_known_units).pack(
            side=tk.LEFT, padx=(0, 6))

        refresh_current_btn = ttk.Button(picker, text=t("Refresh Current Values"),
                                          command=self._refresh_current_values)
        refresh_current_btn.pack(side=tk.LEFT, padx=(0, 12))
        ui_util.tooltip(refresh_current_btn, t(
            "Reads the LIVE values the companion plugin last saw for this unit — only available "
            "after you've built + deployed it and run the game at least once with it enabled."))

        self.ap_key_frame = ttk.Frame(picker)
        if self.category == "Aircraft":
            self.ap_key_frame.pack(side=tk.LEFT)
        ttk.Label(self.ap_key_frame, text=t("AircraftParameters key")).pack(side=tk.LEFT)
        self.ap_key_var = tk.StringVar(value="")
        ap_key_entry = ttk.Entry(self.ap_key_frame, textvariable=self.ap_key_var, width=16, font=theme.F)
        ap_key_entry.pack(side=tk.LEFT, padx=(4, 0))
        ui_util.tooltip(ap_key_entry, t(
            "Flight-performance fields live on a SEPARATE object (AircraftParameters) keyed by its "
            "own aircraftName, which this app hasn't verified always matches the mission jsonKey. "
            "Auto-follows the selected unit until you type your own value here — check the current "
            "value readout after refreshing and adjust if only base fields took effect."))

        # Auto-follow the unit picker until the user manually edits this field themselves — a plain
        # "fill if empty" guard would only ever apply to the FIRST unit picked, then go stale for
        # every unit picked after that.
        self._ap_key_auto = True
        self._syncing_ap_key = False
        self.ap_key_var.trace_add("write", self._on_ap_key_edited)
        self.unit_var.trace_add("write", lambda *_: (self._sync_ap_key_default(),
                                                       self._refresh_current_values()))

        body = ttk.Frame(parent)
        body.pack(fill="both", expand=True, padx=8, pady=(4, 4))
        self.field_scroll = ui_util.make_scrollable(body)

        # Live preview of every currently-checked field for the selected unit — updates as you
        # check boxes or edit values, so you can review what you're about to queue before
        # clicking Add rather than only finding out from the queue list afterward.
        pending_frame = ttk.LabelFrame(parent, text=t("Pending Changes (not yet added)"))
        pending_frame.pack(fill="x", padx=8, pady=(0, 4))
        self.pending_list = tk.Listbox(
            pending_frame, height=4, activestyle="none",
            background=theme.WIDGET, foreground=theme.TEXT,
            selectbackground=theme.SEL_BG, selectforeground=theme.SEL_FG,
            font=theme.F, relief="flat",
            highlightthickness=1, highlightcolor=theme.BORDER, highlightbackground=theme.BORDER)
        self.pending_list.pack(fill="x", padx=4, pady=4)

        add_bar = ttk.Frame(parent)
        add_bar.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(add_bar, text=t("Add / Update in Queue"), command=self._add_to_queue).pack(side=tk.LEFT)
        self.status_var = tk.StringVar(value="")
        ttk.Label(add_bar, textvariable=self.status_var, foreground=theme.DIM).pack(
            side=tk.LEFT, padx=(12, 0))

        meta = usc.CATEGORIES[self.category]
        for i, f in enumerate(meta["fields"]):
            row = uew.FieldRow(self.field_scroll, f, reset_callback=self._make_reset_callback(f),
                                index=i, on_change=self._refresh_pending_changes)
            self.rows[(f.class_name, f.field_name)] = row

        self._refresh_pending_changes()

    def _refresh_pending_changes(self):
        self.pending_list.delete(0, tk.END)
        for row in self.rows.values():
            if row.override_var.get():
                self.pending_list.insert(tk.END, f"{row.field.label} = {row.raw_value()}")
        if self.pending_list.size() == 0:
            self.pending_list.insert(tk.END, t("(no fields checked yet)"))

    def _make_reset_callback(self, field: usc.StatField):
        def _reset(f):
            entry_type, key = self._resolve_type_and_key(f.class_name)
            self.state.reset_baseline_entry(entry_type, key, f.field_name)
        return _reset

    def _on_setup_done(self):
        self._refresh_known_units()
        self._refresh_current_values()

    # ── Unit picker ──────────────────────────────────────────────────────

    def _live_unit_name(self, definition_class: str, key: str, current_values: dict):
        """The real in-game "Unit Name" (UnitDefinition.unitName — same field as the "Unit Name"
        row further down this tab) for `key`, from the companion plugin's last live dump — the
        ONLY source for this, since it's actual ScriptableObject asset data, not anything present
        in mission JSON or otherwise derivable statically. None if no live dump has ever captured
        this unit (nothing built/deployed/run yet, or this key hasn't loaded in-game yet)."""
        name = current_values.get((definition_class, key, "unitName"))
        return name.strip() if isinstance(name, str) and name.strip() else None

    def _refresh_known_units(self):
        # Two sources, merged: mission-scraped keys (plus the bundled seed list) work immediately
        # with zero setup but only cover units already known from saved missions; live-dump-
        # discovered keys come from the companion plugin reading the game's own master roster
        # object (the same one its Encyclopedia/hangar screens use) — normally the FULL roster for
        # this category, not just what's been touched — but only once you've built + deployed the
        # plugin and run the game at least once. That same live dump is also the only place real
        # unit NAMES come from (see _live_unit_name) — the dropdown shows "Name (jsonKey)" once a
        # name is known, and just the bare jsonKey until then.
        definition_class = usc.CATEGORIES[self.category]["definition_class"]
        from_missions = set(usc.known_unit_keys(self.app.missions_dir()).get(self.category, []))
        from_game = set(self.state.known_keys_for_type(definition_class))
        keys = sorted(from_missions | from_game)

        current_values = self.state.read_current_values()
        self._key_by_display = {}
        display_values = []
        named = 0
        for key in keys:
            name = self._live_unit_name(definition_class, key, current_values)
            display = f"{name} ({key})" if name else key
            self._key_by_display[display] = key
            display_values.append(display)
            named += 1 if name else 0

        self.unit_combo.configure(values=display_values)
        if display_values and not self.unit_display_var.get():
            self.unit_display_var.set(display_values[0])
        self.status_var.set(t(
            "{n} known {cat} key(s) — {m} from your saved missions, {d} seen live in-game, "
            "{named} with a real name known.", n=len(keys), cat=self.category, m=len(from_missions),
            d=len(from_game), named=named))

    def _sync_ap_key_default(self):
        if self.category != "Aircraft" or not self._ap_key_auto:
            return
        self._syncing_ap_key = True
        try:
            self.ap_key_var.set(self.unit_var.get())
        finally:
            self._syncing_ap_key = False

    def _on_ap_key_edited(self, *_args):
        if not self._syncing_ap_key:
            self._ap_key_auto = False

    def _refresh_current_values(self):
        """Reads the companion plugin's last dump (if any) and pushes each row's live current
        value in — a no-op, not an error, if the plugin hasn't been built/deployed/run yet."""
        values = self.state.read_current_values()
        for (class_name, field_name), row in self.rows.items():
            entry_type, key = self._resolve_type_and_key(class_name)
            lookup_key = (entry_type, key, field_name)
            row.set_current(values.get(lookup_key), self.state.baseline.get(lookup_key))

    # ── Runtime type/key resolution ──────────────────────────────────────

    def _resolve_type_and_key(self, class_name: str):
        """(concrete_class, key) for a catalog field's `class_name` given the current unit
        selection — fields declared on the shared UnitDefinition base must resolve to the CONCRETE
        category class (e.g. AircraftDefinition), not "UnitDefinition" itself, since that's what
        the companion plugin's KeyFieldByType table and Resources.FindObjectsOfTypeAll() lookup are
        keyed on (Type.GetField still finds the inherited field either way — this only affects
        which live instances get matched). Shared by queueing AND reading current values back, so
        the two can never drift apart on how a field is addressed."""
        definition_class = usc.CATEGORIES[self.category]["definition_class"]
        unit_key = self.unit_var.get().strip()
        if class_name == "AircraftParameters":
            return "AircraftParameters", (self.ap_key_var.get().strip() or unit_key)
        return definition_class, unit_key

    # ── Queue ────────────────────────────────────────────────────────────

    def _add_to_queue(self):
        unit_key = self.unit_var.get().strip()
        if not unit_key:
            ui_util.warning(self.app, t("No Unit Selected"), t("Pick or type a unit jsonKey first."))
            return

        added = 0
        for (class_name, field_name), row in self.rows.items():
            if not row.override_var.get():
                continue
            entry_type, key = self._resolve_type_and_key(class_name)
            entry = {
                "type": entry_type,
                "key": key,
                "field": field_name,
                "value": row.raw_value(),
                "label": f"{self.category} · {unit_key} · {row.field.label} = {row.raw_value()}",
            }
            self.state.upsert_queue_entry(entry)
            added += 1

        if added == 0:
            ui_util.warning(self.app, t("Nothing Checked"),
                             t("Check the override box next to at least one field first."))
            return

        self.status_var.set(t(
            "{n} override(s) added/updated for {unit} — switch to \"Queue & Build\" to save/build.",
            n=added, unit=unit_key))


def build(parent, app, category: str = "Aircraft"):
    tab = _Tab(parent, app, category)
    setattr(app, f"_unit_editor_tab_{category.lower()}", tab)

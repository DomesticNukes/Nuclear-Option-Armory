"""
Shared Unit Editor field row widget — one StatField's checkbox + slider/entry/checkbutton +
default/current readout + reset button. Used identically by every category tab
(unit_editor_tab.py: Aircraft/Vehicle/Ship/Building/Weapon), so the row behaviour and look can
never drift between categories.
"""
import tkinter as tk
from tkinter import ttk

import theme
import ui_util
import unit_stat_catalog as usc
from i18n import t


def _display_const(field: usc.StatField, value) -> str:
    if field.field_type == "bool":
        return "true" if value else "false"
    if field.field_type == "int":
        return str(int(round(value)))
    if field.field_type == "float":
        try:
            return f"{float(value):g}"
        except (TypeError, ValueError):
            return str(value)
    return str(value)


class FieldRow:
    """One StatField's row: an override checkbox + the value widget(s), plus a small info label
    showing a "default" for the field even when the game's own source never declared one. Checked
    in order, most specific/trustworthy first:

      1. baseline_raw — the first LIVE value this app ever saw for this exact unit/weapon+field,
         captured once from the companion plugin's dump and kept forever after (see
         UnitEditorState.baseline) — i.e. the actual original value the game ships with, not a
         guess. HUD-green text. A small reset button clears it (e.g. if it was captured while an
         override was already active) so the next live reading becomes the new baseline.
      2. reference_raw — this SPECIFIC unit's real value, sourced from an external reference
         dataset (currently unit_stat_catalog.wiki_reference(), compiled from the community wiki —
         see data/aircraft_wiki_reference.json's own "_provenance" note) rather than captured
         directly. Set via set_reference_default(). Shown identically to any other default (gold,
         "default N") since it IS the real per-unit value, just not yet independently captured —
         more specific and more useful than #3, which only ever describes one generic number
         shared by every unit in the category.
      3. field.default_value — a real C# initializer (e.g. `= 9f`), when one exists — the SAME
         placeholder value for every unit in the category, not this unit's actual number. Gold
         text, same as #2; only reached when neither #1 nor #2 is available for this unit.
      4. "(unknown — build, deploy, and run once)" — nothing at all is available yet.

    current_raw (separate, dim text) is the LATEST dump reading, which may differ from the
    baseline if an override is already active — baseline never changes once captured (until
    explicitly reset), so it stays trustworthy as "the original" even after you start overriding
    the field.

    Value widgets are disabled (greyed, inert) until the override checkbox is checked, so an
    unedited field is never accidentally queued. The first time a row is checked, its value is
    seeded from the best known real number — current, else baseline, else declared default, else
    the slider floor — rather than an arbitrary starting point; a user who then edits it manually
    keeps that edit even if set_current() is called again later (e.g. after a Refresh)."""

    def __init__(self, parent, field: usc.StatField, reset_callback=None, index=0, on_change=None):
        self.field = field
        self._reset_callback = reset_callback   # fn(field) -> None, clears the PERSISTED baseline
        self._on_change = on_change              # fn() -> None, called on any live edit (for a
                                                   # "pending changes" preview before Add is clicked)
        self.override_var = tk.BooleanVar(value=False)
        self.current_raw = None      # str | None — the live value from the last dump, if any
        self.baseline_raw = None     # str | None — the first-ever-seen live value, kept forever
        self.reference_raw = None    # str | None — this unit's real value from an external
                                      # reference dataset (e.g. the wiki), set via set_reference_default()
        self._user_touched = False   # True once the user edits the value themselves

        # RUSE-style zebra striping (ui_util.row_bg/apply_row_bg) so a wide row's checkbox, label,
        # and value stay visually tied together across the row instead of blurring into the next
        # one — `index` (this field's position in its tab) picks even/odd. The row and everything
        # in it that ISN'T an input field (Entry) is plain tk, not ttk, specifically so it accepts
        # a per-instance background colour — ttk widgets ignore configure(background=...).
        row_color = ui_util.row_bg(index, theme.PANEL)
        row = tk.Frame(parent, background=row_color)
        row.pack(fill="x", padx=4, pady=2)

        chk = tk.Checkbutton(row, variable=self.override_var, command=self._on_toggle,
                              background=row_color, activebackground=row_color,
                              selectcolor=theme.WIDGET, foreground=theme.TEXT,
                              highlightthickness=0, bd=0)
        chk.pack(side=tk.LEFT)

        lbl = tk.Label(row, text=field.label, width=24, anchor="w",
                        background=row_color, foreground=theme.TEXT, font=theme.F)
        lbl.pack(side=tk.LEFT, padx=(2, 4))
        if field.tooltip:
            ui_util.tooltip(lbl, field.tooltip)

        # Two separate labels (not one combined string) so the default and current readouts can
        # carry different colours — default in gold (a declared source-code fact) or HUD green (a
        # captured live-game fact), current left dim since it's a secondary, may-be-unset reading.
        self.default_var = tk.StringVar(value="")
        self.default_lbl = tk.Label(row, textvariable=self.default_var, width=30, anchor="w",
                                     background=row_color)
        self.default_lbl.pack(side=tk.LEFT, padx=(0, 2))

        # A plain tk.Label standing in for a button (not ttk.Button) — with ~130 rows across the
        # Unit Editor tabs, ttk's per-widget theme-engine drawing cost adds up to real, measured
        # lag (build+first-render timed at ~770ms for one 33-row tab with ttk.Button + ttk.Scale,
        # ~370ms with lighter tk equivalents — same behaviour, half the cost).
        self._reset_enabled = False
        self.reset_btn = tk.Label(row, text="↺", width=3, cursor="arrow",
                                   background=row_color, foreground=theme.DIM, font=theme.FB)
        self.reset_btn.pack(side=tk.LEFT, padx=(0, 4))
        self.reset_btn.bind("<Button-1>", lambda _e: self._on_reset_baseline())
        ui_util.tooltip(self.reset_btn, t(
            "Clear the captured original value for this field, so the next live reading (after a "
            "Refresh Current Values) becomes the new baseline — use this if the original was "
            "captured after an override had already taken effect."))

        self.current_var = tk.StringVar(value="")
        current_lbl = tk.Label(row, textvariable=self.current_var, width=16, anchor="w",
                                background=row_color, foreground=theme.DIM)
        current_lbl.pack(side=tk.LEFT, padx=(0, 6))

        self.widgets = []
        if field.field_type == "bool":
            self.value_var = tk.BooleanVar(value=bool(field.default_value))
            w = tk.Checkbutton(row, variable=self.value_var, command=self._on_value_committed,
                                background=row_color, activebackground=row_color,
                                selectcolor=theme.WIDGET, foreground=theme.TEXT,
                                highlightthickness=0, bd=0)
            w.pack(side=tk.LEFT)
            self.widgets.append(w)
        elif field.field_type in ("float", "int"):
            lo = field.min_value if field.min_value is not None else 0
            hi = field.max_value if field.max_value is not None else 100
            start = field.default_value if field.default_value is not None else lo
            self.value_var = tk.DoubleVar(value=start)

            # No slider — just a compact, plain Entry. (A slider used to sit here; dropped for
            # feeling janky to use, and typing/pasting an exact number is precise anyway.) Fixed,
            # short width rather than filling the row — most values here are a handful of digits.
            self.entry_var = tk.StringVar(value=self._format(start))
            entry = ttk.Entry(row, textvariable=self.entry_var, width=10, font=theme.F)
            entry.pack(side=tk.LEFT)
            entry.bind("<Return>", self._on_entry_commit)
            entry.bind("<FocusOut>", self._on_entry_commit)
            self.widgets.append(entry)
        else:   # string
            self.value_var = tk.StringVar(value="")
            w = ttk.Entry(row, textvariable=self.value_var, width=18, font=theme.F)
            w.bind("<Key>", lambda _e: self._mark_touched())
            w.bind("<Return>", lambda _e: self._on_value_committed())
            w.bind("<FocusOut>", lambda _e: self._on_value_committed())
            w.pack(side=tk.LEFT)
            self.widgets.append(w)

        self._refresh_info()
        self._on_toggle()

    def _format(self, v) -> str:
        if self.field.field_type == "int":
            return str(int(round(v)))
        return f"{float(v):g}"

    def _mark_touched(self, *_args):
        self._user_touched = True

    def _notify_change(self):
        if self._on_change is not None:
            try:
                self._on_change()
            except Exception:
                pass

    def _on_value_committed(self):
        """Called whenever the VALUE itself changes (bool click, entry Return/FocusOut) — as
        opposed to _mark_touched, which just records that the user has taken the wheel."""
        self._mark_touched()
        self._notify_change()

    def _on_entry_commit(self, _event=None):
        try:
            v = float(self.entry_var.get())
        except ValueError:
            self._mark_touched()
            self.entry_var.set(self._format(self.value_var.get()))
            return
        lo = self.field.min_value
        hi = self.field.max_value
        if lo is not None and v < lo:
            v = lo
        if hi is not None and v > hi:
            v = hi
        self.value_var.set(v)
        self.entry_var.set(self._format(v))
        self._on_value_committed()

    def _on_toggle(self):
        state = "normal" if self.override_var.get() else "disabled"
        for w in self.widgets:
            try:
                w.configure(state=state)
            except tk.TclError:
                pass
        if self.override_var.get() and not self._user_touched:
            self._seed_from_best_known()
        self._notify_change()

    def _seed_from_best_known(self):
        """Pick the strongest available real number for this field: the latest live reading beats
        the captured original, which beats a mere class-declared default, which beats the entry's
        slider's arbitrary floor."""
        if self.field.field_type not in ("float", "int", "bool"):
            return
        raw = self.current_raw or self.baseline_raw or self.reference_raw
        if raw is None and self.field.default_value is not None:
            raw = _display_const(self.field, self.field.default_value)
        if raw is None:
            return
        try:
            if self.field.field_type == "bool":
                self.value_var.set(raw in ("true", "True", "1"))
            else:
                v = float(raw)
                self.value_var.set(v)
                if hasattr(self, "entry_var"):
                    self.entry_var.set(self._format(v))
        except (ValueError, TypeError):
            pass

    def set_reference_default(self, raw_value):
        """`raw_value` is a pre-formatted string (e.g. "9" or "3.5") for this SPECIFIC unit, from
        an external reference dataset (unit_stat_catalog.wiki_reference()) — never a bare guess.
        Displayed and seeded exactly like any other default (see _refresh_info/_seed_from_best_known);
        a real captured live value (baseline_raw) still always wins over it."""
        self.reference_raw = raw_value
        self._refresh_info()

    def set_current(self, raw_value, baseline_value=None):
        """Called by the owning tab after reading a fresh dump — `raw_value` is the plugin's own
        string form of the live value for the currently-selected unit/weapon (None if not known
        yet); `baseline_value` is the permanently-cached first-ever-seen value (also None until a
        dump has captured it, or after a reset)."""
        self.current_raw = raw_value
        self.baseline_raw = baseline_value
        self._refresh_info()
        if self.override_var.get() and not self._user_touched:
            self._seed_from_best_known()

    def _on_reset_baseline(self):
        if not self._reset_enabled:
            return
        if self._reset_callback is not None:
            self._reset_callback(self.field)
        self.baseline_raw = None
        self._refresh_info()

    def _refresh_info(self):
        if self.baseline_raw is not None:
            # The ORIGINAL live value has been captured at least once for THIS unit — shown in
            # HUD green since it's a fact about the running game, not the source code.
            self.default_var.set(t("default {v}", v=self.baseline_raw))
            self.default_lbl.configure(foreground=theme.HUD, font=theme.FB)
        elif self.reference_raw is not None:
            # Not independently captured yet, but a reference dataset (see set_reference_default's
            # docstring) documents THIS unit's real value — shown exactly like any other default,
            # since it's the actual per-unit number, not a placeholder.
            self.default_var.set(t("default {v}", v=self.reference_raw))
            self.default_lbl.configure(foreground=theme.GOLD, font=theme.FB)
        elif self.field.default_value is not None:
            # Only a generic, same-for-every-unit source-code constant is known.
            self.default_var.set(t("default {v}", v=_display_const(self.field, self.field.default_value)))
            self.default_lbl.configure(foreground=theme.GOLD, font=theme.FB)
        else:
            # Explicit rather than blank — a blank cell reads as "this is broken/missing," when
            # really this app just hasn't captured a live value for this field+unit/weapon yet.
            self.default_var.set(t("(unknown — build, deploy, run once)"))
            self.default_lbl.configure(foreground=theme.DIM, font=theme.F)
        self.current_var.set(t("current {v}", v=self.current_raw) if self.current_raw is not None else "")

        self._reset_enabled = self.baseline_raw is not None
        self.reset_btn.configure(
            foreground=(theme.GOLD if self._reset_enabled else theme.DIM),
            cursor=("hand2" if self._reset_enabled else "arrow"))

    def raw_value(self) -> str:
        if self.field.field_type == "bool":
            return "true" if self.value_var.get() else "false"
        if self.field.field_type == "int":
            return str(int(round(self.value_var.get())))
        if self.field.field_type == "float":
            return f"{float(self.value_var.get())}"
        return self.value_var.get()

    def reset(self):
        self.override_var.set(False)
        self._user_touched = False
        self._on_toggle()

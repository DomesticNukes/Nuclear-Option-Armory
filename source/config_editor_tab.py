"""
Config Editor tab — a standalone, browse-everything panel for every deployed plugin's BepInEx
.cfg, built on the same form renderer as the Plugins tab's one-at-a-time "Edit Config…" popup
(config_editor.build_form/apply_form) but embedded here so the whole set can be browsed in one
place instead of opening a plugin at a time from the Plugins list.

Scans BepInEx/config directly rather than cross-referencing the plugin library, so it picks up
EVERY plugin that has ever written a config — including ones installed outside Armory entirely
(manually placed, or by another manager) — using BepInEx's own standard config header
(nom_plugin_meta.plugin_info_from_cfg_header) to get a friendly name/GUID for each, with no
dependency on this app already knowing about the plugin.
"""
import os
import tkinter as tk
from tkinter import ttk

import config_editor
import nom_plugin_meta as npm
import theme
import ui_util
from i18n import t


class _CfgEntry:
    __slots__ = ("path", "name", "guid")

    def __init__(self, path, name, guid):
        self.path = path
        self.name = name
        self.guid = guid


class _Tab:
    def __init__(self, parent, app):
        self.app = app
        self.entries = []
        self.doc = None
        self.widgets = {}
        self.dirty = False
        self.current_entry = None
        self._build_widgets(parent)
        self.refresh_list()
        app.register_settings_listener(self.refresh_list)

    # ── Widgets ──────────────────────────────────────────────────────────

    def _build_widgets(self, parent):
        body = ttk.PanedWindow(parent, orient="horizontal")
        body.pack(fill="both", expand=True, padx=6, pady=6)

        list_frame = ttk.Frame(body)
        body.add(list_frame, weight=2)

        list_actions = ttk.Frame(list_frame)
        list_actions.pack(fill="x", padx=2, pady=(2, 4))
        ttk.Button(list_actions, text=t("Refresh"), command=self.refresh_list).pack(side=tk.LEFT)

        self.listbox = tk.Listbox(
            list_frame, activestyle="none",
            background=theme.WIDGET, foreground=theme.TEXT,
            selectbackground=theme.SEL_BG, selectforeground=theme.SEL_FG,
            font=theme.F, relief="flat",
            highlightthickness=1, highlightcolor=theme.BORDER, highlightbackground=theme.BORDER)
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side=tk.LEFT, fill="both", expand=True)
        sb.pack(side=tk.RIGHT, fill="y")
        ui_util.debounce_load(self.listbox, self._on_pick)

        editor_holder = ttk.Frame(body)
        body.add(editor_holder, weight=3)

        header = ttk.Frame(editor_holder)
        header.pack(fill="x", padx=4, pady=(2, 0))
        self.title_var = tk.StringVar(value=t("Select a plugin's config to edit."))
        ttk.Label(header, textvariable=self.title_var, font=theme.FHEAD, foreground=theme.GOLD).pack(
            anchor="w")
        self.path_var = tk.StringVar(value="")
        ttk.Label(header, textvariable=self.path_var, foreground=theme.DIM, wraplength=460).pack(
            anchor="w")

        self.editor_canvas_holder = ttk.Frame(editor_holder)
        self.editor_canvas_holder.pack(fill="both", expand=True)
        self._build_empty_editor()

        actions = ttk.Frame(editor_holder)
        actions.pack(fill="x", padx=4, pady=6)
        self.save_btn = ttk.Button(actions, text=t("Save"), command=self._save, state="disabled")
        self.save_btn.pack(side=tk.RIGHT)
        self.revert_btn = ttk.Button(actions, text=t("Revert"), command=self._load_selected, state="disabled")
        self.revert_btn.pack(side=tk.RIGHT, padx=(0, 6))
        self.reveal_btn = ttk.Button(actions, text=t("Reveal File"), command=self._reveal, state="disabled")
        self.reveal_btn.pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value="")
        ttk.Label(editor_holder, textvariable=self.status_var, foreground=theme.DIM).pack(
            anchor="w", padx=4, pady=(0, 4))

    def _build_empty_editor(self):
        for w in self.editor_canvas_holder.winfo_children():
            w.destroy()
        self.editor_inner = ui_util.make_scrollable(self.editor_canvas_holder)
        self.widgets = {}

    # ── Scan ─────────────────────────────────────────────────────────────

    def refresh_list(self):
        sel_guid = self.current_entry.guid if self.current_entry else None
        config_dir = None
        try:
            config_dir = self.app.bepinex_config_dir()
        except Exception:
            pass

        self.entries = []
        if config_dir and config_dir.is_dir():
            for cfg_path in sorted(config_dir.glob("*.cfg"), key=lambda p: p.name.lower()):
                name, guid = self._read_header(cfg_path)
                self.entries.append(_CfgEntry(cfg_path, name or cfg_path.stem, guid or cfg_path.stem))

        self.listbox.delete(0, tk.END)
        for entry in self.entries:
            self.listbox.insert(tk.END, entry.name)

        if not config_dir or not config_dir.is_dir():
            self.status_var.set(t("No BepInEx config folder found yet — set a game folder with "
                                   "BepInEx installed."))
        else:
            self.status_var.set(t("{n} config file(s) found.", n=len(self.entries)))

        if self.dirty:
            return   # keep the unsaved edit open; the list underneath is still refreshed

        if sel_guid:
            for i, entry in enumerate(self.entries):
                if entry.guid == sel_guid:
                    self.listbox.selection_set(i)
                    self._load_selected()
                    return
        self.current_entry = None
        self._show_empty_state(t("Select a plugin's config to edit."))

    @staticmethod
    def _read_header(cfg_path):
        try:
            text = cfg_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None, None
        try:
            return npm.plugin_info_from_cfg_header(text.splitlines()[:6])
        except Exception:
            return None, None

    # ── Selection / load ─────────────────────────────────────────────────

    def _selected_entry(self):
        sel = self.listbox.curselection()
        if len(sel) != 1:
            return None
        idx = sel[0]
        return self.entries[idx] if 0 <= idx < len(self.entries) else None

    def _on_pick(self):
        entry = self._selected_entry()
        if entry is None:
            return
        if self.current_entry is not None and entry is not self.current_entry and self.dirty:
            if not ui_util.confirm(self.app, t("Discard Changes?"),
                                    t("You have unsaved changes to {name}. Discard them?",
                                      name=self.current_entry.name)):
                self._reselect_current()
                return
        self._load_selected()

    def _reselect_current(self):
        if self.current_entry is None:
            return
        for i, entry in enumerate(self.entries):
            if entry is self.current_entry:
                self.listbox.selection_clear(0, tk.END)
                self.listbox.selection_set(i)
                self.listbox.activate(i)
                return

    def _load_selected(self):
        entry = self._selected_entry()
        if entry is None:
            return
        try:
            text = entry.path.read_text(encoding="utf-8")
            self.doc = npm.parse_cfg(text)
        except Exception as e:
            ui_util.error(self.app, t("Couldn't Open Config"), str(e))
            return

        self.current_entry = entry
        self.title_var.set(entry.name)
        self.path_var.set(str(entry.path))
        self._build_empty_editor()
        self.widgets = config_editor.build_form(self.editor_inner, self.doc)
        for kind, var in self.widgets.values():
            var.trace_add("write", lambda *_: self._mark_dirty())
        self.dirty = False
        self.save_btn.configure(state="disabled")
        self.revert_btn.configure(state="normal")
        self.reveal_btn.configure(state="normal")
        self.status_var.set("")

    def _mark_dirty(self):
        self.dirty = True
        self.save_btn.configure(state="normal")

    def _show_empty_state(self, message):
        self._build_empty_editor()
        ttk.Label(self.editor_inner, text=message, foreground=theme.DIM, padding=20).pack()
        self.title_var.set(message)
        self.path_var.set("")
        self.save_btn.configure(state="disabled")
        self.revert_btn.configure(state="disabled")
        self.reveal_btn.configure(state="disabled")

    # ── Save / reveal ────────────────────────────────────────────────────

    def _save(self):
        if self.current_entry is None or self.doc is None:
            return
        try:
            self.current_entry.path.write_text(config_editor.apply_form(self.doc, self.widgets),
                                                encoding="utf-8")
        except Exception as e:
            ui_util.error(self.app, t("Couldn't Save Config"), str(e))
            return
        self.dirty = False
        self.save_btn.configure(state="disabled")
        self.status_var.set(t("Saved."))

    def _reveal(self):
        if self.current_entry is None:
            return
        try:
            os.startfile(self.current_entry.path.parent)
        except Exception as e:
            ui_util.error(self.app, t("Couldn't Open Folder"), str(e))


def build(parent, app):
    app._config_editor_tab = _Tab(parent, app)

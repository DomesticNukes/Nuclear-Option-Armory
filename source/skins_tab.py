"""
Skins tab — organizes aircraft livery folders under
%USERPROFILE%\\AppData\\LocalLow\\Shockfront\\NuclearOption\\Skins\\<folder>\\.

A real skin folder needs a "meta.json" (DisplayName/Faction/Aircraft/AircraftKey), a
"catalog_1.json" (Unity Addressables catalog), and a compiled Unity AssetBundle the catalog
references. Building that bundle needs Unity + Shockfront's mod-project template, which this app
does not provide — this tab only organizes folders and edits meta.json's plain fields for bundles
you've already built by hand. Empty-state-first: no custom skins exist on a fresh install.
"""
import json
import os
import tkinter as tk
from tkinter import ttk

import theme
import ui_util
from i18n import t

_META_FIELDS = ("DisplayName", "Faction", "Aircraft")


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=4)


class _Tab:
    def __init__(self, parent, app):
        self.app = app
        self.folders = []
        self._field_vars = {}
        self._build_widgets(parent)
        self.refresh()

    def _build_widgets(self, parent):
        actions = ttk.Frame(parent)
        actions.pack(side=tk.BOTTOM, fill="x", padx=6, pady=4)
        ttk.Button(actions, text=t("Reveal in Explorer"), command=self.reveal).pack(side=tk.LEFT, padx=2)
        ttk.Button(actions, text=t("Refresh"), command=self.refresh).pack(side=tk.LEFT, padx=2)

        self.status_var = tk.StringVar(value="")
        ttk.Label(parent, textvariable=self.status_var, foreground=theme.DIM).pack(
            side=tk.BOTTOM, fill="x", padx=8, pady=(0, 2))

        self.body = ttk.Frame(parent)
        self.body.pack(side=tk.TOP, fill="both", expand=True, padx=6, pady=(6, 0))

        # Populated by _show_empty_state() or _show_list_state() in refresh().
        self.empty_frame = None
        self.list_frame = None

    def _clear_body(self):
        for child in self.body.winfo_children():
            child.destroy()

    def _show_empty_state(self, folder_exists: bool):
        self._clear_body()
        wrap = ttk.Frame(self.body)
        wrap.pack(expand=True)
        ttk.Label(wrap, text=t("No custom skins yet"), font=theme.FHEAD, foreground=theme.GOLD).pack(
            pady=(40, 8))
        msg = t(
            "A custom aircraft livery needs a compiled Unity AssetBundle plus a meta.json and "
            "catalog_1.json, built with Unity and Nuclear Option's mod-project tooling — this app "
            "doesn't build bundles for you. Once you've dropped a skin folder here, it will show up "
            "in this list so you can organize it and edit its DisplayName/Faction/Aircraft fields."
        )
        ttk.Label(wrap, text=msg, wraplength=480, justify="center").pack(padx=20)
        if not folder_exists:
            ttk.Label(wrap, text=t("Folder: {p}", p=str(self.app.skins_dir())),
                      foreground=theme.DIM).pack(pady=(12, 0))

    def _show_list_state(self):
        self._clear_body()
        body = ttk.PanedWindow(self.body, orient="horizontal")
        body.pack(fill="both", expand=True)

        list_frame = ttk.Frame(body)
        body.add(list_frame, weight=2)
        self.listbox = tk.Listbox(
            list_frame, selectmode="browse", activestyle="none",
            background=theme.WIDGET, foreground=theme.TEXT,
            selectbackground=theme.SEL_BG, selectforeground=theme.SEL_FG,
            font=("Courier New", 10), relief="flat",
            highlightthickness=1, highlightcolor=theme.BORDER, highlightbackground=theme.BORDER)
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side=tk.LEFT, fill="both", expand=True)
        sb.pack(side=tk.RIGHT, fill="y")
        self.listbox.bind("<<ListboxSelect>>", lambda e: self._load_selected())

        form_frame = ttk.LabelFrame(body, text=t("Meta.json"))
        body.add(form_frame, weight=3)
        self._field_vars = {}
        for i, field in enumerate(_META_FIELDS):
            ttk.Label(form_frame, text=field, width=14, anchor="w").grid(row=i, column=0, sticky="w", padx=8, pady=6)
            var = tk.StringVar(value="")
            ttk.Entry(form_frame, textvariable=var, font=theme.F).grid(row=i, column=1, sticky="ew", padx=(0, 8), pady=6)
            self._field_vars[field] = var
        form_frame.columnconfigure(1, weight=1)
        self.save_btn = ttk.Button(form_frame, text=t("Save"), command=self._save_selected, state="disabled")
        self.save_btn.grid(row=len(_META_FIELDS), column=1, sticky="e", padx=8, pady=(6, 8))

        for folder in self.folders:
            self.listbox.insert(tk.END, folder.name)

    def refresh(self):
        root = self.app.skins_dir()
        if not root.is_dir():
            self.folders = []
            self.status_var.set(t("No skins folder yet."))
            self._show_empty_state(folder_exists=False)
            return

        self.folders = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name.lower())
        if not self.folders:
            self.status_var.set(t("No skin folders found."))
            self._show_empty_state(folder_exists=True)
            return

        self.status_var.set(t("{n} skin folder(s).", n=len(self.folders)))
        self._show_list_state()

    def _selected_folder(self):
        sel = self.listbox.curselection()
        if not sel:
            return None
        return self.folders[sel[0]]

    def _load_selected(self):
        folder = self._selected_folder()
        if folder is None:
            for var in self._field_vars.values():
                var.set("")
            self.save_btn.configure(state="disabled")
            return
        meta = _read_json(folder / "meta.json") or {}
        for field in _META_FIELDS:
            self._field_vars[field].set(str(meta.get(field, "")))
        self.save_btn.configure(state="normal")

    def _save_selected(self):
        folder = self._selected_folder()
        if folder is None:
            return
        meta_path = folder / "meta.json"
        meta = _read_json(meta_path) or {}
        for field in _META_FIELDS:
            meta[field] = self._field_vars[field].get()
        try:
            _write_json(meta_path, meta)
        except Exception as e:
            ui_util.error(self.app, t("Couldn't Save"), str(e))
            return
        ui_util.info(self.app, t("Saved"), t("meta.json updated for \"{name}\".", name=folder.name))

    def reveal(self):
        try:
            root = self.app.skins_dir()
            root.mkdir(parents=True, exist_ok=True)
            os.startfile(root)
        except Exception as e:
            ui_util.error(self.app, t("Couldn't Open Folder"), str(e))


def build(parent, app):
    app._skins_tab = _Tab(parent, app)

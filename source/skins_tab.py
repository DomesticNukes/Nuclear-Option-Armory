"""
Skins tab — organizes aircraft livery folders under
%USERPROFILE%\\AppData\\LocalLow\\Shockfront\\NuclearOption\\Skins\\<folder>\\ (your own, locally
built liveries) AND Steam Workshop-subscribed liveries under
steamapps\\workshop\\content\\2168680\\<id>\\ (someone else's, downloaded via Subscribe).

A real skin folder needs a "meta.json" (DisplayName/Faction/Aircraft/AircraftKey), a
"catalog_1.json" (Unity Addressables catalog), and a compiled Unity AssetBundle the catalog
references. Building that bundle needs Unity + Shockfront's mod-project template, which this app
does not provide — this tab only organizes folders and edits meta.json's plain fields, and only for
LOCAL folders: a subscribed item's compiled AssetBundle bakes its catalog IDs against that exact
folder, so unlike a mission's plain JSON, copying or renaming it isn't something this app has
verified stays working — editing/duplicating a subscribed skin is left to Steam's own management.
Empty-state-first: no custom or subscribed skins exist on a fresh install.
"""
import json
import os
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import nom_steam
import theme
import ui_util
from i18n import t

_META_FIELDS = ("DisplayName", "Faction", "Aircraft")

# The only Workshop TypeHint confirmed (on a real subscribed item, 2026-08-16) to mean "this is a
# skin, not a mission" — Nuclear Option currently only ships aircraft liveries via Workshop, so
# this is deliberately narrow rather than guessing at hypothetical future types.
_SKIN_TYPE_HINTS = {"AircraftLivery"}


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=4)


def _display_name(folder, meta=None) -> str:
    """meta.json's DisplayName when present (subscribed Workshop folders are named by their
    numeric Steam published-file ID, not anything human-readable), else the folder name."""
    if meta is None:
        meta = _read_json(folder / "meta.json")
    if isinstance(meta, dict) and meta.get("DisplayName"):
        return str(meta["DisplayName"])
    return folder.name


def _subscribed_skin_folders() -> list:
    """Steam Workshop items subscribed for this game, filtered to real aircraft liveries via each
    item's own workshop.json TypeHint field — the same content folder also holds subscribed
    missions (see missions_tab._subscribed_mission_folders for that side of this same split)."""
    folders = []
    for content_dir in nom_steam.find_workshop_content_dirs():
        try:
            children = list(content_dir.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir():
                continue
            ws = _read_json(child / "workshop.json")
            if isinstance(ws, dict) and ws.get("TypeHint") in _SKIN_TYPE_HINTS:
                folders.append(child)
    return folders


class _Tab:
    def __init__(self, parent, app):
        self.app = app
        self.folders = []
        self._subscribed_keys = set()
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
        ttk.Label(wrap, text=t("No skins yet"), font=theme.FHEAD, foreground=theme.GOLD).pack(
            pady=(40, 8))
        msg = t(
            "A custom aircraft livery needs a compiled Unity AssetBundle plus a meta.json and "
            "catalog_1.json, built with Unity and Nuclear Option's mod-project tooling — this app "
            "doesn't build bundles for you. Once you've dropped a skin folder here, or subscribed "
            "to one on the Steam Workshop, it will show up in this list."
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
        self.tree = ttk.Treeview(list_frame, columns=("source",), show="tree headings", selectmode="browse")
        self.tree.heading("#0", text=t("Skin"))
        self.tree.heading("source", text=t("Source"))
        self.tree.column("source", width=100, anchor="center", stretch=False)
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side=tk.LEFT, fill="both", expand=True)
        sb.pack(side=tk.RIGHT, fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._load_selected())
        self.tree.tag_configure("subscribed", foreground=theme.GOLD)  # gold — someone else's, subscribed

        form_frame = ttk.LabelFrame(body, text=t("Meta.json"))
        body.add(form_frame, weight=3)
        self._field_vars = {}
        for i, field in enumerate(_META_FIELDS):
            ttk.Label(form_frame, text=field, width=14, anchor="w").grid(row=i, column=0, sticky="w", padx=8, pady=6)
            var = tk.StringVar(value="")
            ttk.Entry(form_frame, textvariable=var, font=theme.F).grid(row=i, column=1, sticky="ew", padx=(0, 8), pady=6)
            self._field_vars[field] = var
        form_frame.columnconfigure(1, weight=1)
        self.save_note_var = tk.StringVar(value="")
        ttk.Label(form_frame, textvariable=self.save_note_var, foreground=theme.DIM, wraplength=320,
                  justify="left").grid(row=len(_META_FIELDS), column=0, columnspan=2, sticky="w", padx=8)
        self.save_btn = ttk.Button(form_frame, text=t("Save"), command=self._save_selected, state="disabled")
        self.save_btn.grid(row=len(_META_FIELDS) + 1, column=1, sticky="e", padx=8, pady=(6, 8))

        for folder in self.folders:
            subscribed = self._is_subscribed(folder)
            self.tree.insert("", tk.END, iid=str(folder), text=_display_name(folder),
                              values=(t("Subscribed") if subscribed else t("Local"),),
                              tags=("subscribed",) if subscribed else ())

    def refresh(self):
        root = self.app.skins_dir()
        local_found = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name.lower()) \
            if root.is_dir() else []
        subscribed_found = sorted(_subscribed_skin_folders(), key=lambda p: p.name.lower())

        self.folders = local_found + subscribed_found
        self._subscribed_keys = {str(f) for f in subscribed_found}

        if not self.folders:
            self.status_var.set(t("No skins found.") if root.is_dir() else t("No skins folder yet."))
            self._show_empty_state(folder_exists=root.is_dir())
            return

        if subscribed_found:
            self.status_var.set(t("{n} skin(s) — {s} subscribed from the Workshop.",
                                   n=len(self.folders), s=len(subscribed_found)))
        else:
            self.status_var.set(t("{n} skin folder(s).", n=len(self.folders)))
        self._show_list_state()

    def _is_subscribed(self, folder) -> bool:
        return str(folder) in self._subscribed_keys

    def _selected_folder(self):
        tree = getattr(self, "tree", None)
        if tree is None:
            return None
        sel = tree.selection()
        if not sel:
            return None
        return Path(sel[0])

    def _load_selected(self):
        folder = self._selected_folder()
        if folder is None:
            for var in self._field_vars.values():
                var.set("")
            self.save_btn.configure(state="disabled")
            self.save_note_var.set("")
            return
        meta = _read_json(folder / "meta.json") or {}
        for field in _META_FIELDS:
            self._field_vars[field].set(str(meta.get(field, "")))
        if self._is_subscribed(folder):
            self.save_btn.configure(state="disabled")
            self.save_note_var.set(t(
                "Subscribed from the Steam Workshop — Steam manages this folder, so editing isn't "
                "offered here."))
        else:
            self.save_btn.configure(state="normal")
            self.save_note_var.set("")

    def _save_selected(self):
        folder = self._selected_folder()
        if folder is None or self._is_subscribed(folder):
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
        self.refresh()

    def reveal(self):
        folder = self._selected_folder()
        target = folder if folder is not None else self.app.skins_dir()
        try:
            if folder is None:
                target.mkdir(parents=True, exist_ok=True)
            os.startfile(target)
        except Exception as e:
            ui_util.error(self.app, t("Couldn't Open Folder"), str(e))


def build(parent, app):
    app._skins_tab = _Tab(parent, app)

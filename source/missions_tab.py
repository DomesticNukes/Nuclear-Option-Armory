"""
Missions tab — organizes saved missions under
%USERPROFILE%\\AppData\\LocalLow\\Shockfront\\NuclearOption\\Missions\\<name>\\.

Each mission is a folder containing "<name>.json" (the full mission data), "meta.json"
({"FileName": "<name>"}), and optionally "workshop.json" if published. This tab organizes those
folders (rename / duplicate / delete / reveal) — it does not edit mission content.

Clean-room design (no direct RUSE tab to port — R.U.S.E. has nothing structurally similar), built
from theme.py / ui_util.py the same way the rest of this app is.
"""
import json
import os
import shutil
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import theme
import ui_util
from i18n import t

_DELETED_SUBDIR = ".deleted"


def _read_json(path: Path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_json(path: Path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=4)


def _mission_json_path(folder: Path) -> Path:
    """Best-effort: the folder's main mission JSON, preferring meta.json's FileName."""
    meta = _read_json(folder / "meta.json")
    if isinstance(meta, dict) and meta.get("FileName"):
        candidate = folder / f"{meta['FileName']}.json"
        if candidate.is_file():
            return candidate
    for p in folder.glob("*.json"):
        if p.name not in ("meta.json", "workshop.json"):
            return p
    return folder / f"{folder.name}.json"


def _unique_path(base: Path) -> Path:
    if not base.exists():
        return base
    n = 2
    while True:
        candidate = base.with_name(f"{base.name} ({n})")
        if not candidate.exists():
            return candidate
        n += 1


def _prompt_text(parent, title, prompt, initial=""):
    win = ui_util.themed_toplevel(parent, title, size=(380, 140), resizable=False)
    ttk.Label(win, text=prompt).pack(anchor="w", padx=12, pady=(12, 4))
    var = tk.StringVar(value=initial)
    entry = ttk.Entry(win, textvariable=var, font=theme.F)
    entry.pack(fill="x", padx=12)
    entry.select_range(0, tk.END)
    entry.focus_set()

    result = {"value": None}

    def _ok():
        result["value"] = var.get().strip()
        win.destroy()

    def _cancel():
        win.destroy()

    btns = ttk.Frame(win)
    btns.pack(side=tk.BOTTOM, fill="x", padx=12, pady=12)
    ttk.Button(btns, text=t("Cancel"), command=_cancel).pack(side=tk.RIGHT, padx=(4, 0))
    ttk.Button(btns, text=t("OK"), command=_ok).pack(side=tk.RIGHT)
    entry.bind("<Return>", lambda e: _ok())
    entry.bind("<Escape>", lambda e: _cancel())

    win.wait_window()
    return result["value"]


class _Tab:
    def __init__(self, parent, app):
        self.app = app
        self.folders = []   # list[Path], in display order matching the Treeview rows
        self._build_widgets(parent)
        self.refresh()

    def _build_widgets(self, parent):
        actions = ttk.Frame(parent)
        actions.pack(side=tk.BOTTOM, fill="x", padx=6, pady=4)
        ttk.Button(actions, text=t("Rename…"), command=self.rename_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(actions, text=t("Duplicate"), command=self.duplicate_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(actions, text=t("Delete"), command=self.delete_selected).pack(side=tk.LEFT, padx=2)
        ttk.Separator(actions, orient="vertical").pack(side=tk.LEFT, fill="y", padx=6)
        ttk.Button(actions, text=t("Reveal in Explorer"), command=self.reveal_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(actions, text=t("Refresh"), command=self.refresh).pack(side=tk.LEFT, padx=2)

        self.status_var = tk.StringVar(value="")
        ttk.Label(parent, textvariable=self.status_var, foreground=theme.DIM).pack(
            side=tk.BOTTOM, fill="x", padx=8, pady=(0, 2))

        body = ttk.PanedWindow(parent, orient="horizontal")
        body.pack(side=tk.TOP, fill="both", expand=True, padx=6, pady=(6, 0))

        list_frame = ttk.Frame(body)
        body.add(list_frame, weight=3)

        self.tree = ttk.Treeview(list_frame, columns=("workshop",), show="tree headings", selectmode="browse")
        self.tree.heading("#0", text=t("Mission"))
        self.tree.heading("workshop", text=t("Workshop"))
        self.tree.column("workshop", width=90, anchor="center", stretch=False)
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side=tk.LEFT, fill="both", expand=True)
        sb.pack(side=tk.RIGHT, fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._update_detail())
        self.tree.tag_configure("published", foreground=theme.HUD)   # HUD green — live on Workshop

        detail_frame = ttk.LabelFrame(body, text=t("Details"))
        body.add(detail_frame, weight=2)
        self.detail_var = tk.StringVar(value=t("Select a mission to see details."))
        ttk.Label(detail_frame, textvariable=self.detail_var, justify="left", wraplength=280).pack(
            anchor="nw", padx=8, pady=8)

    def refresh(self):
        root = self.app.missions_dir()
        self.tree.delete(*self.tree.get_children())
        self.folders = []
        if not root.is_dir():
            self.status_var.set(t("No missions folder found yet — save a mission in-game first."))
            self._update_detail()
            return
        found = sorted(
            (p for p in root.iterdir() if p.is_dir() and p.name != _DELETED_SUBDIR and (p / "meta.json").is_file()),
            key=lambda p: p.name.lower())
        for folder in found:
            published = (folder / "workshop.json").is_file()
            self.tree.insert("", tk.END, iid=str(folder), text=folder.name,
                              values=(t("Yes") if published else "",),
                              tags=("published",) if published else ())
            self.folders.append(folder)
        self.status_var.set(t("{n} mission(s).", n=len(found)))
        self._update_detail()

    def _selected_folder(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return Path(sel[0])

    def _update_detail(self):
        folder = self._selected_folder()
        if folder is None:
            self.detail_var.set(t("Select a mission to see details."))
            return
        lines = [t("Folder: {name}", name=folder.name)]
        json_path = _mission_json_path(folder)
        data = _read_json(json_path) if json_path.is_file() else None
        if isinstance(data, dict):
            desc = None
            settings = data.get("missionSettings")
            if isinstance(settings, dict):
                desc = settings.get("description")
            n_aircraft = len(data.get("aircraft", [])) if isinstance(data.get("aircraft"), list) else None
            n_vehicles = len(data.get("vehicles", [])) if isinstance(data.get("vehicles"), list) else None
            if desc:
                lines.append(t("Description: {d}", d=desc))
            if n_aircraft is not None:
                lines.append(t("Aircraft: {n}", n=n_aircraft))
            if n_vehicles is not None:
                lines.append(t("Vehicles: {n}", n=n_vehicles))
        else:
            lines.append(t("(no preview available)"))
        self.detail_var.set("\n".join(lines))

    def rename_selected(self):
        folder = self._selected_folder()
        if folder is None:
            return
        new_name = _prompt_text(self.app, t("Rename Mission"), t("New name:"), initial=folder.name)
        if not new_name or new_name == folder.name:
            return
        new_folder = folder.with_name(new_name)
        if new_folder.exists():
            ui_util.error(self.app, t("Rename Failed"), t("A mission named \"{name}\" already exists.", name=new_name))
            return
        try:
            self._rename_mission_contents(folder, new_name)
            os.rename(folder, new_folder)   # folder rename LAST — only after internal files are consistent
        except Exception as e:
            ui_util.error(self.app, t("Rename Failed"), str(e))
            return
        self.refresh()

    def _rename_mission_contents(self, folder: Path, new_name: str):
        """Update meta.json's FileName and rename the inner "<old>.json" to "<new>.json", still inside
        the OLD folder path. Must fully succeed before the caller renames the folder itself."""
        old_json = _mission_json_path(folder)
        meta_path = folder / "meta.json"
        meta = _read_json(meta_path) or {}
        meta["FileName"] = new_name
        _write_json(meta_path, meta)
        new_json = folder / f"{new_name}.json"
        if old_json.is_file() and old_json != new_json:
            os.rename(old_json, new_json)

    def duplicate_selected(self):
        folder = self._selected_folder()
        if folder is None:
            return
        dest = _unique_path(folder.with_name(f"{folder.name} - Copy"))
        try:
            shutil.copytree(folder, dest)
            self._rename_mission_contents(dest, dest.name)
        except Exception as e:
            ui_util.error(self.app, t("Duplicate Failed"), str(e))
            return
        self.refresh()

    def delete_selected(self):
        folder = self._selected_folder()
        if folder is None:
            return
        if not ui_util.confirm(self.app, t("Delete Mission"),
                                t("Move \"{name}\" to the Deleted Missions holding folder?", name=folder.name)):
            return
        holding = self.app.missions_dir() / _DELETED_SUBDIR
        try:
            holding.mkdir(parents=True, exist_ok=True)
            dest = _unique_path(holding / folder.name)
            shutil.move(str(folder), str(dest))
        except Exception as e:
            ui_util.error(self.app, t("Delete Failed"), str(e))
            return
        self.refresh()

    def reveal_selected(self):
        folder = self._selected_folder()
        target = folder if folder is not None else self.app.missions_dir()
        try:
            target.mkdir(parents=True, exist_ok=True)
            os.startfile(target)
        except Exception as e:
            ui_util.error(self.app, t("Couldn't Open Folder"), str(e))


def build(parent, app):
    app._missions_tab = _Tab(parent, app)

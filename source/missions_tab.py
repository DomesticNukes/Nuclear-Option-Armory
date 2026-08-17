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
from tkinter import filedialog, ttk

import nom_steam
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


def _subscribed_mission_folders() -> list:
    """Steam Workshop items subscribed for this game, filtered to real missions via each item's
    own workshop.json — Nuclear Option writes {"TypeHint": "Mission"} for mission uploads and a
    different TypeHint (e.g. "AircraftLivery") for skins, confirmed real on this machine, so
    liveries sharing the same content folder are correctly excluded here (see skins_tab.py for
    the livery side of this same split)."""
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
            if isinstance(ws, dict) and ws.get("TypeHint") == "Mission":
                folders.append(child)
    return folders


def _display_name(folder: Path) -> str:
    """meta.json's FileName when present (the real mission title — subscribed Workshop folders are
    named by their numeric Steam published-file ID, not anything human-readable), else the folder
    name itself as a fallback."""
    meta = _read_json(folder / "meta.json")
    if isinstance(meta, dict) and meta.get("FileName"):
        return str(meta["FileName"])
    return folder.name


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
        self._subscribed_keys = set()   # str(Path) of entries sourced from Steam Workshop, not local
        self._build_widgets(parent)
        self.refresh()

    def _build_widgets(self, parent):
        actions = ttk.Frame(parent)
        actions.pack(side=tk.BOTTOM, fill="x", padx=6, pady=4)
        ttk.Button(actions, text=t("Rename…"), command=self.rename_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(actions, text=t("Duplicate"), command=self.duplicate_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(actions, text=t("Delete"), command=self.delete_selected).pack(side=tk.LEFT, padx=2)
        ttk.Separator(actions, orient="vertical").pack(side=tk.LEFT, fill="y", padx=6)
        import_btn = ttk.Button(actions, text=t("Import…"), command=self.import_mission)
        import_btn.pack(side=tk.LEFT, padx=2)
        ui_util.tooltip(import_btn, t(
            "Copies a mission folder from somewhere else on disk (e.g. one someone shared with "
            "you) into your local Missions folder."))
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
        self.tree.column("workshop", width=100, anchor="center", stretch=False)
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side=tk.LEFT, fill="both", expand=True)
        sb.pack(side=tk.RIGHT, fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._update_detail())
        self.tree.tag_configure("published", foreground=theme.HUD)    # HUD green — YOU published this
        self.tree.tag_configure("subscribed", foreground=theme.GOLD)  # gold — someone else's, subscribed

        detail_frame = ttk.LabelFrame(body, text=t("Details"))
        body.add(detail_frame, weight=2)
        self.detail_var = tk.StringVar(value=t("Select a mission to see details."))
        ttk.Label(detail_frame, textvariable=self.detail_var, justify="left", wraplength=280).pack(
            anchor="nw", padx=8, pady=8)

    def refresh(self):
        root = self.app.missions_dir()
        self.tree.delete(*self.tree.get_children())
        self.folders = []
        self._subscribed_keys = set()

        local_found = []
        if root.is_dir():
            local_found = sorted(
                (p for p in root.iterdir()
                 if p.is_dir() and p.name != _DELETED_SUBDIR and (p / "meta.json").is_file()),
                key=lambda p: p.name.lower())
        subscribed_found = sorted(_subscribed_mission_folders(), key=lambda p: p.name.lower())

        if not local_found and not subscribed_found:
            self.status_var.set(t("No missions found yet — save one in-game first, "
                                   "or subscribe to one on the Steam Workshop."))
            self._update_detail()
            return

        for folder in local_found:
            published = (folder / "workshop.json").is_file()
            self.tree.insert("", tk.END, iid=str(folder), text=folder.name,
                              values=(t("Published") if published else "",),
                              tags=("published",) if published else ())
            self.folders.append(folder)

        for folder in subscribed_found:
            self.tree.insert("", tk.END, iid=str(folder), text=_display_name(folder),
                              values=(t("Subscribed"),), tags=("subscribed",))
            self.folders.append(folder)
            self._subscribed_keys.add(str(folder))

        if subscribed_found:
            self.status_var.set(t("{n} mission(s) — {s} subscribed from the Workshop.",
                                   n=len(self.folders), s=len(subscribed_found)))
        else:
            self.status_var.set(t("{n} mission(s).", n=len(self.folders)))
        self._update_detail()

    def _is_subscribed(self, folder: Path) -> bool:
        return str(folder) in self._subscribed_keys

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
        if self._is_subscribed(folder):
            lines.append(t("Source: Steam Workshop (subscribed) — Steam manages this copy; "
                            "use Duplicate to make an editable local one."))
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
        if self._is_subscribed(folder):
            ui_util.warning(self.app, t("Steam Workshop Item"),
                             t("This mission is managed by Steam, not by you — renaming its cache "
                               "folder would just get undone on the next sync. Use Duplicate to "
                               "make an editable local copy first."))
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
        if self._is_subscribed(folder):
            # A subscribed item's own folder is Steam-managed cache named by numeric ID — the
            # useful "duplicate" here is an editable LOCAL copy, named after the mission's real
            # title, dropped into the same Missions folder saved-in-game missions use.
            base_name = _display_name(folder)
            dest = _unique_path(self.app.missions_dir() / f"{base_name} - Copy")
        else:
            dest = _unique_path(folder.with_name(f"{folder.name} - Copy"))
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(folder, dest)
            self._rename_mission_contents(dest, dest.name)
            (dest / "workshop.json").unlink(missing_ok=True)   # a copy isn't the same Workshop item
        except Exception as e:
            ui_util.error(self.app, t("Duplicate Failed"), str(e))
            return
        self.refresh()

    def import_mission(self):
        """Copies a mission folder from anywhere else on disk into the local Missions folder —
        for one someone shared with you directly (not via Workshop subscribe, which the tab
        already picks up on its own). Requires a real mission JSON inside the chosen folder, same
        shape local/duplicated missions already have; meta.json is normalized to match afterward
        (same helper "Duplicate" already uses), and any workshop.json is stripped since an
        imported copy isn't that same Workshop item."""
        chosen = filedialog.askdirectory(title=t("Select a mission folder to import"))
        if not chosen:
            return
        src = Path(chosen)
        has_mission_json = any(
            p.name not in ("meta.json", "workshop.json") for p in src.glob("*.json"))
        if not has_mission_json:
            ui_util.warning(self.app, t("Not a Mission Folder"),
                             t("\"{name}\" doesn't contain a mission JSON file.", name=src.name))
            return
        missions_dir = self.app.missions_dir()
        dest = _unique_path(missions_dir / src.name)
        try:
            missions_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dest)
            self._rename_mission_contents(dest, dest.name)
            (dest / "workshop.json").unlink(missing_ok=True)
        except Exception as e:
            ui_util.error(self.app, t("Import Failed"), str(e))
            return
        self.refresh()

    def delete_selected(self):
        folder = self._selected_folder()
        if folder is None:
            return
        if self._is_subscribed(folder):
            ui_util.warning(self.app, t("Steam Workshop Item"),
                             t("This mission lives in Steam's own Workshop cache, not your local "
                               "missions — to remove it, unsubscribe from it on the Workshop page "
                               "in-game or in your browser instead."))
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

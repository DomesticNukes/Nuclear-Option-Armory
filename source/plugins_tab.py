"""
Plugin Manager tab — the primary tab. Ports the R.U.S.E. Mod Manager's checkbox-list-of-mods
pattern (a plain themed Listbox with "checkbox glyphs" drawn as text, click-region hit-testing,
full-rebuild vs. single-row-refresh redraws) for BepInEx plugin DLLs.

Deliberately simpler than RUSE's deploy: BepInEx plugins ARE the mod (not a patch over original
game files), so there's no backup/restore pair — only enable/disable + Apply(deploy), which just
copies enabled DLLs into BepInEx/plugins and removes disabled/removed ones.
"""
import json
import os
import shutil
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font, ttk

import nom_plugin_meta as npm
import theme
import ui_util
from i18n import t

_STATE_FILE_NAME = "plugin_library_state.json"
_STATE_LOCK = threading.Lock()


def _atomic_write_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _norm(path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


class _Tab:
    """Holds the Plugin Manager tab's widgets/state. One instance per app (build() creates it)."""

    def __init__(self, parent, app):
        self.app = app
        self.plugin_vars = []          # [(tk.BooleanVar, Path), ...]
        self.meta_cache = {}           # str(path) -> PluginMeta
        self._state_loading = False
        self._build_widgets(parent)
        self._load_state()
        self.scan_library()
        app.register_settings_listener(self.scan_library)

    # ── Widgets ───────────────────────────────────────────────────────────

    def _build_widgets(self, parent):
        pad = {"padx": 6, "pady": 4}

        actions = ttk.Frame(parent)
        actions.pack(side=tk.BOTTOM, fill="x", **pad)

        ttk.Button(actions, text=t("Enable All"), command=self.enable_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(actions, text=t("Disable All"), command=self.disable_all).pack(side=tk.LEFT, padx=2)
        ttk.Separator(actions, orient="vertical").pack(side=tk.LEFT, fill="y", padx=6)
        ttk.Button(actions, text=t("Import DLL(s)…"), command=self.import_dlls).pack(side=tk.LEFT, padx=2)
        ttk.Button(actions, text=t("Refresh"), command=self.scan_library).pack(side=tk.LEFT, padx=2)
        ttk.Separator(actions, orient="vertical").pack(side=tk.LEFT, fill="y", padx=6)
        ttk.Button(actions, text=t("Reveal Library"), command=self.reveal_library).pack(side=tk.LEFT, padx=2)
        ttk.Button(actions, text=t("Reveal BepInEx/plugins"), command=self.reveal_deployed).pack(side=tk.LEFT, padx=2)

        self.deploy_btn = ttk.Button(actions, text=t("Apply (Deploy)"), command=self.deploy)
        self.deploy_btn.pack(side=tk.RIGHT, padx=2)

        self.status_var = tk.StringVar(value="")
        ttk.Label(parent, textvariable=self.status_var, foreground=theme.DIM).pack(
            side=tk.BOTTOM, fill="x", padx=8, pady=(0, 2))

        body = ttk.PanedWindow(parent, orient="horizontal")
        body.pack(side=tk.TOP, fill="both", expand=True, padx=6, pady=(6, 0))

        list_frame = ttk.Frame(body)
        body.add(list_frame, weight=3)

        self.listbox = tk.Listbox(
            list_frame, selectmode="extended", activestyle="none",
            background=theme.WIDGET, foreground=theme.TEXT,
            selectbackground=theme.SEL_BG, selectforeground=theme.SEL_FG,
            font=("Courier New", 10), relief="flat",
            highlightthickness=1, highlightcolor=theme.BORDER, highlightbackground=theme.BORDER)
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side=tk.LEFT, fill="both", expand=True)
        sb.pack(side=tk.RIGHT, fill="y")
        self.listbox.bind("<ButtonRelease-1>", self._on_click)
        self.listbox.bind("<space>", self._on_toggle_selected)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        detail_frame = ttk.LabelFrame(body, text=t("Details"))
        body.add(detail_frame, weight=2)

        self.detail_var = tk.StringVar(value=t("Select a plugin to see details."))
        ttk.Label(detail_frame, textvariable=self.detail_var, justify="left", wraplength=280).pack(
            anchor="nw", padx=8, pady=8)

        self.edit_cfg_btn = ttk.Button(detail_frame, text=t("Edit Config…"), command=self._edit_selected_config,
                                        state="disabled")
        self.edit_cfg_btn.pack(anchor="nw", padx=8, pady=(0, 8))

    # ── State persistence ────────────────────────────────────────────────

    def _state_file(self) -> Path:
        return self.app.state_path(_STATE_FILE_NAME)

    def _load_state(self):
        self._state_loading = True
        try:
            path = self._state_file()
            if path.exists():
                with open(path, encoding="utf-8") as f:
                    data = json.load(f) or {}
                entries = [e for e in data.get("plugins", []) if e.get("path")]
                self._saved_enabled = {_norm(e["path"]): bool(e.get("enabled")) for e in entries}
                self.descriptions = {_norm(e["path"]): e["description"] for e in entries if e.get("description")}
            else:
                self._saved_enabled = {}
                self.descriptions = {}
        except Exception:
            self._saved_enabled = {}
            self.descriptions = {}
        finally:
            self._state_loading = False

    def _save_state(self):
        if self._state_loading:
            return
        try:
            with _STATE_LOCK:
                data = {"plugins": [
                    {"path": str(p), "enabled": bool(v.get()), "description": self.descriptions.get(_norm(p), "")}
                    for v, p in self.plugin_vars
                ]}
                _atomic_write_json(self._state_file(), data)
        except Exception:
            pass

    def set_description(self, path, description: str):
        """Called by mod_creator_tab after building a plugin, so its description shows up here."""
        self.descriptions[_norm(path)] = description.strip()
        self._save_state()
        self._update_detail()

    # ── Library scan ─────────────────────────────────────────────────────

    def scan_library(self):
        library = Path(self.app._settings.get("plugin_library", ""))
        if not library.is_dir():
            self.plugin_vars = []
            self.meta_cache = {}
            self.status_var.set(t("No plugin library folder configured — set one in Settings."))
            self._redraw_list()
            return

        on_disk = sorted(library.glob("*.dll"))
        on_disk_keys = {_norm(p) for p in on_disk}

        # Prune entries whose file no longer exists.
        self.plugin_vars = [(v, p) for v, p in self.plugin_vars if _norm(p) in on_disk_keys]
        known_keys = {_norm(p) for _, p in self.plugin_vars}

        for dll in on_disk:
            key = _norm(dll)
            if key in known_keys:
                continue
            enabled = self._saved_enabled.get(key, False)
            self.plugin_vars.append((tk.BooleanVar(value=enabled), dll))
            self._get_meta(dll)   # warm the cache

        self.status_var.set(t("{n} plugin(s) in library.", n=len(self.plugin_vars)))
        self._redraw_list()

    def _get_meta(self, path: Path) -> npm.PluginMeta:
        key = str(path)
        meta = self.meta_cache.get(key)
        if meta is None:
            meta = npm.read_primary_plugin_metadata(path)
            self.meta_cache[key] = meta
        return meta

    # ── Row rendering ────────────────────────────────────────────────────

    def _is_deployed(self, path: Path) -> bool:
        try:
            return (self.app.bepinex_plugins_dir() / path.name).is_file()
        except Exception:
            return False

    def _label(self, var: tk.BooleanVar, path: Path) -> str:
        box = "☑ " if var.get() else "☐ "
        meta = self._get_meta(path)
        name = meta.name if meta.name else path.stem
        suffix = "  [deployed]" if self._is_deployed(path) else ""
        return f"{box}{name}{suffix}"

    def _redraw_list(self):
        sel = list(self.listbox.curselection())
        yview = self.listbox.yview()
        self.listbox.delete(0, tk.END)
        for i, (var, path) in enumerate(self.plugin_vars):
            self.listbox.insert(tk.END, self._label(var, path))
            self._tint_row(i, var)
        for s in sel:
            if 0 <= s < self.listbox.size():
                self.listbox.selection_set(s)
        self.listbox.yview_moveto(yview[0])
        self._update_detail()
        self._save_state()

    def _tint_row(self, idx: int, var: tk.BooleanVar):
        """Enabled plugins glow HUD green — the "armed/active" cockpit-instrument look."""
        self.listbox.itemconfig(idx, foreground=(theme.HUD if var.get() else theme.TEXT))

    def _refresh_item(self, idx: int):
        if not (0 <= idx < len(self.plugin_vars)):
            return
        yview = self.listbox.yview()
        var, path = self.plugin_vars[idx]
        self.listbox.delete(idx)
        self.listbox.insert(idx, self._label(var, path))
        self._tint_row(idx, var)
        self.listbox.selection_set(idx)
        self.listbox.yview_moveto(yview[0])
        self._update_detail()

    # ── Interaction ──────────────────────────────────────────────────────

    def _on_click(self, event):
        idx = self.listbox.nearest(event.y)
        if not (0 <= idx < len(self.plugin_vars)):
            return
        bbox = self.listbox.bbox(idx)
        if not bbox:
            return
        if not (bbox[1] <= event.y <= bbox[1] + bbox[3]):
            return
        f = font.Font(font=self.listbox.cget("font"))
        if event.x <= bbox[0] + f.measure("☑ "):
            var, _ = self.plugin_vars[idx]
            var.set(not var.get())
            self._refresh_item(idx)
            self._save_state()

    def _on_toggle_selected(self, _event=None):
        for idx in self.listbox.curselection():
            if 0 <= idx < len(self.plugin_vars):
                var, _ = self.plugin_vars[idx]
                var.set(not var.get())
        self._redraw_list()

    def _on_select(self, _event=None):
        self._update_detail()

    def _selected_index(self):
        sel = self.listbox.curselection()
        if len(sel) != 1:
            return None
        idx = sel[0]
        return idx if 0 <= idx < len(self.plugin_vars) else None

    def _update_detail(self):
        idx = self._selected_index()
        if idx is None:
            self.detail_var.set(t("Select a plugin to see details."))
            self.edit_cfg_btn.configure(state="disabled")
            return
        _, path = self.plugin_vars[idx]
        meta = self._get_meta(path)
        cfg_path = npm.find_cfg_for_guid(meta.guid, self.app.bepinex_config_dir())
        lines = [
            t("File: {name}", name=path.name),
            t("Name: {name}", name=meta.name),
            t("GUID: {guid}", guid=meta.guid or t("(unknown)")),
            t("Version: {v}", v=meta.version or t("(unknown)")),
            t("Deployed: {yn}", yn=t("Yes") if self._is_deployed(path) else t("No")),
            t("Settings file: {yn}", yn=t("Yes") if cfg_path else t("No")),
            t("Description: {d}", d=self.descriptions.get(_norm(path)) or t("(none)")),
        ]
        if meta.source == "filename-fallback":
            lines.append(t("(couldn't read plugin info from this DLL — showing filename)"))
        self.detail_var.set("\n".join(lines))
        self.edit_cfg_btn.configure(state=("normal" if cfg_path else "disabled"))

    # ── Actions ──────────────────────────────────────────────────────────

    def enable_all(self):
        for var, _ in self.plugin_vars:
            var.set(True)
        self._redraw_list()

    def disable_all(self):
        for var, _ in self.plugin_vars:
            var.set(False)
        self._redraw_list()

    def import_dlls(self):
        library = Path(self.app._settings.get("plugin_library", ""))
        if not library.is_dir():
            ui_util.warning(self.app, t("No Library Folder"),
                             t("Set a plugin library folder in Settings first."))
            return
        chosen = filedialog.askopenfilenames(title=t("Select BepInEx plugin DLL(s)"),
                                              filetypes=[(t("DLL files"), "*.dll")])
        if not chosen:
            return
        copied = 0
        for src in chosen:
            src_path = Path(src)
            if _norm(src_path.parent) == _norm(library):
                continue   # already in the library
            dest = library / src_path.name
            try:
                shutil.copy2(src_path, dest)
                copied += 1
            except Exception as e:
                ui_util.error(self.app, t("Import Failed"), str(e))
        if copied:
            self.scan_library()

    def reveal_library(self):
        library = Path(self.app._settings.get("plugin_library", ""))
        if not library.is_dir():
            ui_util.warning(self.app, t("No Library Folder"),
                             t("Set a plugin library folder in Settings first."))
            return
        os.startfile(library)

    def reveal_deployed(self):
        try:
            plugins_dir = self.app.bepinex_plugins_dir()
            plugins_dir.mkdir(parents=True, exist_ok=True)
            os.startfile(plugins_dir)
        except Exception as e:
            ui_util.error(self.app, t("Couldn't Open Folder"), str(e))

    def deploy(self):
        game_root = self.app._settings.get("game_root", "")
        import nom_steam
        if not nom_steam.is_valid_game_root(game_root):
            ui_util.warning(self.app, t("No Game Folder"),
                             t("Set a valid Nuclear Option game folder in Settings first."))
            return
        if not nom_steam.is_bepinex_installed(game_root):
            ui_util.warning(self.app, t("BepInEx Not Installed"),
                             t("Deployed plugins won't do anything until BepInEx is installed — "
                               "go to Settings and click \"Install BepInEx\" first."))
            return
        plugins_dir = self.app.bepinex_plugins_dir()
        try:
            plugins_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            ui_util.error(self.app, t("Deploy Failed"), str(e))
            return

        added, removed, errors = 0, 0, []
        for var, path in self.plugin_vars:
            dest = plugins_dir / path.name
            try:
                if var.get():
                    if not dest.exists() or dest.stat().st_size != path.stat().st_size:
                        shutil.copy2(path, dest)
                        added += 1
                else:
                    if dest.exists():
                        dest.unlink()
                        removed += 1
            except Exception as e:
                errors.append(f"{path.name}: {e}")

        self._redraw_list()
        if errors:
            ui_util.error(self.app, t("Deploy Finished With Errors"), "\n".join(errors))
        self.status_var.set(t("Deployed: {a} updated, {r} removed.", a=added, r=removed))

    def _edit_selected_config(self):
        idx = self._selected_index()
        if idx is None:
            return
        _, path = self.plugin_vars[idx]
        meta = self._get_meta(path)
        cfg_path = npm.find_cfg_for_guid(meta.guid, self.app.bepinex_config_dir())
        if not cfg_path:
            return
        import config_editor
        config_editor.open_editor(self.app, cfg_path, meta)


def build(parent, app):
    app._plugins_tab = _Tab(parent, app)

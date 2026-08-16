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
import tempfile
import threading
import tkinter as tk
import zipfile
from pathlib import Path, PureWindowsPath
from tkinter import filedialog, font, ttk

import blueprinter_installer
import live_editor_installer as lei
import nom_plugin_meta as npm
import plugin_library
import theme
import ui_util
from i18n import t

_STATE_FILE_NAME = "plugin_library_state.json"
_STATE_LOCK = threading.Lock()
_MODPACK_EXT = ".armorypack"
_LIST_FONT = ("Courier New", 11)     # up from 10 — the plugin list is the tab's main content
_DETAIL_FONT = ("Courier New", 10)   # up from ttk's ~9 default


def _atomic_write_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _norm(path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _safe_entry_name(name: str) -> bool:
    """A library entry name from a modpack's modlist must be a bare file/folder name — no path
    separators or "..", so it can't be used to write outside the library folder."""
    return bool(name) and name not in (".", "..") and "/" not in name and "\\" not in name


def _resolve_zip_entry(base: Path, entry_name: str) -> Path:
    """Zip-slip guard: resolves a zip entry's path and rejects anything that would land outside
    `base` (via "..", or an absolute/drive-anchored path).

    Windows-specific trap: ``base / "C:/evil.dll"`` silently discards `base` and resolves to
    ``C:\\evil.dll`` — pathlib treats a drive-anchored right operand as absolute — so a
    drive letter must be rejected explicitly, not just a leading "/"."""
    normalized = entry_name.replace("\\", "/").lstrip("/")
    if PureWindowsPath(normalized).drive:
        raise ValueError(f"Unsafe archive entry: {entry_name}")
    dest = (base / normalized).resolve()
    base_resolved = base.resolve()
    if dest != base_resolved and base_resolved not in dest.parents:
        raise ValueError(f"Unsafe archive entry: {entry_name}")
    return dest


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
        export_btn = ttk.Button(actions, text=t("Export Modpack…"), command=self.export_modpack)
        export_btn.pack(side=tk.LEFT, padx=2)
        ui_util.tooltip(export_btn, t(
            "Save your currently-enabled plugins as a single {ext} file to share with someone else.",
            ext=_MODPACK_EXT))
        import_btn = ttk.Button(actions, text=t("Import Modpack…"), command=self.import_modpack)
        import_btn.pack(side=tk.LEFT, padx=2)
        ui_util.tooltip(import_btn, t(
            "Load a {ext} file someone shared with you — adds its plugins to your library, enabled.",
            ext=_MODPACK_EXT))
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
            font=_LIST_FONT, relief="flat",
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

        # Plain tk rows (not one ttk.Label with embedded newlines) so each line can carry its own
        # zebra-stripe background — same row_bg() pattern the Unit Editor's field rows use, which
        # ttk widgets can't do (ttk ignores `configure(background=...)`).
        self.detail_rows_frame = tk.Frame(detail_frame, background=theme.PANEL)
        self.detail_rows_frame.pack(fill="x", anchor="nw", padx=8, pady=8)

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
            self.status_var.set(t("No plugin library folder configured — set one in Config."))
            self._redraw_list()
            return

        adopted_names = self._adopt_external_plugins(library)

        # Each top-level entry (loose .dll OR a folder containing one anywhere inside it) is one
        # opaque deployable unit — BepInEx loads plugins recursively regardless of nesting, so
        # Armory doesn't need to flatten folder-structured mods, just move/copy them as a whole.
        on_disk = [p for p in plugin_library.list_library_entries(library) if not self._is_blueprinter(p)]
        on_disk_keys = {_norm(p) for p in on_disk}

        # Prune entries whose file/folder no longer exists.
        self.plugin_vars = [(v, p) for v, p in self.plugin_vars if _norm(p) in on_disk_keys]
        known_keys = {_norm(p) for _, p in self.plugin_vars}

        for entry in on_disk:
            key = _norm(entry)
            if key in known_keys:
                continue
            # A plugin adopted just now was already active in BepInEx/plugins — default it
            # enabled so scanning doesn't silently read as "off" something the user already had
            # running. A saved state from a prior session (re-scans, app restarts) always wins.
            default_enabled = entry.name in adopted_names
            enabled = self._saved_enabled.get(key, default_enabled)
            self.plugin_vars.append((tk.BooleanVar(value=enabled), entry))
            self._get_meta(entry)   # warm the cache

        if adopted_names:
            self.status_var.set(t("{n} plugin(s) in library. ({a} adopted from BepInEx/plugins.)",
                                   n=len(self.plugin_vars), a=len(adopted_names)))
        else:
            self.status_var.set(t("{n} plugin(s) in library.", n=len(self.plugin_vars)))
        self._redraw_list()

    def _direct_companion_tool_guids(self) -> set:
        """GUIDs of tools the Config tab installs straight into BepInEx/plugins (Blueprinter,
        Configuration Manager) — always active, managed exclusively from there, never something
        this tab should adopt into the toggleable library."""
        guids = {blueprinter_installer.BLUEPRINTER_GUID}
        for tool in lei.TOOLS:
            if tool.tool_id == "BepInEx.ConfigurationManager" and tool.guid:
                guids.add(tool.guid)
        return guids

    def _adopt_external_plugins(self, library: Path) -> set:
        """Copies any top-level BepInEx/plugins entry that isn't already tracked in the library —
        a plugin installed by hand, by another manager, or from before this app was in the
        picture — into the library, so it becomes a normal, toggleable, visible entry here instead
        of silently invisible. Direct-installed Companion Tools are excluded (they stay Config-tab-
        only). Returns the set of names actually adopted this scan."""
        plugins_dir = self.app.bepinex_plugins_dir()
        if not plugins_dir.is_dir():
            return set()
        known_names = {p.name for p in plugin_library.list_library_entries(library)}
        excluded_guids = self._direct_companion_tool_guids()
        adopted = set()
        try:
            children = list(plugins_dir.iterdir())
        except OSError:
            return set()
        for child in children:
            if child.name in known_names:
                continue
            is_plugin = (child.is_file() and child.suffix.lower() == ".dll") or \
                        (child.is_dir() and any(child.rglob("*.dll")))
            if not is_plugin:
                continue
            try:
                if npm.read_primary_plugin_metadata(plugin_library.primary_dll(child)).guid in excluded_guids:
                    continue
            except Exception:
                pass   # unreadable metadata just means "not a recognized companion tool" — still adopt it
            dest = library / child.name
            try:
                if child.is_dir():
                    shutil.copytree(child, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(child, dest)
                adopted.add(child.name)
            except Exception:
                continue
        return adopted

    def _get_meta(self, path: Path) -> npm.PluginMeta:
        key = str(path)
        meta = self.meta_cache.get(key)
        if meta is None:
            try:
                meta = npm.read_primary_plugin_metadata(plugin_library.primary_dll(path))
            except Exception:
                meta = npm.PluginMeta(guid=None, name=path.name, version=None, source="filename-fallback")
            self.meta_cache[key] = meta
        return meta

    def _is_blueprinter(self, path: Path) -> bool:
        """Blueprinter is now installed/managed straight from the Setup tab (direct into
        BepInEx/plugins, always active, with its own enable/disable toggle there) rather than as
        a toggleable library entry here — several other mods depend on it always being present,
        so it shouldn't be something that can be unchecked by accident in this list. Filtered by
        GUID (not name/path) so a stale copy left over in the library from before this change
        can't reappear here either."""
        return self._get_meta(path).guid == blueprinter_installer.BLUEPRINTER_GUID

    # ── Row rendering ────────────────────────────────────────────────────

    def _is_deployed(self, path: Path) -> bool:
        try:
            dest = self.app.bepinex_plugins_dir() / path.name
            return dest.is_dir() if path.is_dir() else dest.is_file()
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

    def _clear_detail_rows(self):
        for child in self.detail_rows_frame.winfo_children():
            child.destroy()

    def _add_detail_row(self, index: int, text: str, foreground=None):
        tk.Label(
            self.detail_rows_frame, text=text, background=ui_util.row_bg(index, theme.PANEL),
            foreground=foreground or theme.TEXT, font=_DETAIL_FONT, anchor="w", justify="left",
            wraplength=280, padx=6, pady=3,
        ).pack(fill="x")

    def _update_detail(self):
        self._clear_detail_rows()
        idx = self._selected_index()
        if idx is None:
            self._add_detail_row(0, t("Select a plugin to see details."), foreground=theme.DIM)
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
        for i, line in enumerate(lines):
            self._add_detail_row(i, line)
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
                             t("Set a plugin library folder in Config first."))
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
                             t("Set a plugin library folder in Config first."))
            return
        os.startfile(library)

    def reveal_deployed(self):
        try:
            plugins_dir = self.app.bepinex_plugins_dir()
            plugins_dir.mkdir(parents=True, exist_ok=True)
            os.startfile(plugins_dir)
        except Exception as e:
            ui_util.error(self.app, t("Couldn't Open Folder"), str(e))

    # ── Modpack export/import ────────────────────────────────────────────

    def export_modpack(self):
        """Zip the currently-enabled library entries (files or whole folders) plus a modlist.json
        into a single .armorypack, for sharing a loadout with someone else."""
        enabled = [(v, p) for v, p in self.plugin_vars if v.get()]
        if not enabled:
            ui_util.warning(self.app, t("Nothing to Export"),
                             t("Enable at least one plugin first — Export saves your currently-enabled set."))
            return
        dest = filedialog.asksaveasfilename(
            title=t("Export Modpack"), defaultextension=_MODPACK_EXT,
            filetypes=[(t("Armory Modpack"), f"*{_MODPACK_EXT}")])
        if not dest:
            return
        try:
            with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
                modlist = [{"name": p.name, "description": self.descriptions.get(_norm(p), "")}
                           for _, p in enabled]
                zf.writestr("modlist.json", json.dumps(modlist, indent=2))
                for _, path in enabled:
                    if path.is_file():
                        zf.write(path, f"mods/{path.name}")
                    else:
                        for f in path.rglob("*"):
                            if f.is_symlink() or not f.is_file():
                                continue
                            rel = f.relative_to(path.parent).as_posix()
                            zf.write(f, f"mods/{rel}")
            self.status_var.set(t("Modpack exported: {n} plugin(s) → {name}", n=len(enabled), name=Path(dest).name))
        except Exception as e:
            ui_util.error(self.app, t("Export Failed"), str(e))

    def import_modpack(self):
        library = Path(self.app._settings.get("plugin_library", ""))
        if not library.is_dir():
            ui_util.warning(self.app, t("No Library Folder"),
                             t("Set a plugin library folder in Config first."))
            return
        src = filedialog.askopenfilename(
            title=t("Import Modpack"),
            filetypes=[(t("Armory Modpack"), f"*{_MODPACK_EXT}"), (t("All files"), "*.*")])
        if not src:
            return

        try:
            imported_keys = self._extract_modpack(Path(src), library)
        except Exception as e:
            ui_util.error(self.app, t("Import Failed"), str(e))
            return

        self.scan_library()
        for var, path in self.plugin_vars:
            if _norm(path) in imported_keys:
                var.set(True)
        self._redraw_list()
        self.status_var.set(t("Modpack imported: {n} plugin(s). Click Apply (Deploy) to activate.",
                               n=len(imported_keys)))

    def _extract_modpack(self, src: Path, library: Path) -> set:
        """Unzips `src` into a temp staging dir (rejecting any zip-slip/traversal entries), then
        copies the mods it lists into `library`, overwriting same-named existing entries. Returns
        the set of normalized library paths that were imported."""
        with zipfile.ZipFile(src) as zf:
            names = zf.namelist()
            if "modlist.json" not in names:
                raise ValueError(t("Not a valid Armory modpack (missing modlist.json)."))
            modlist = json.loads(zf.read("modlist.json").decode("utf-8"))
            if not isinstance(modlist, list):
                raise ValueError(t("Not a valid Armory modpack (malformed modlist.json)."))

            with tempfile.TemporaryDirectory(prefix="armory-modpack-") as tmp:
                staging = Path(tmp)
                for info in zf.infolist():
                    if not info.filename.startswith("mods/"):
                        continue
                    rel = info.filename[len("mods/"):]
                    if not rel:
                        continue
                    dest = _resolve_zip_entry(staging, rel)
                    if info.is_dir():
                        dest.mkdir(parents=True, exist_ok=True)
                    else:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(info) as src_f, open(dest, "wb") as out_f:
                            shutil.copyfileobj(src_f, out_f)

                imported_keys = set()
                for entry in modlist:
                    name = entry.get("name") if isinstance(entry, dict) else None
                    if not _safe_entry_name(name):
                        continue
                    staged_path = staging / name
                    if not staged_path.exists() or staged_path.is_symlink():
                        continue

                    dest_path = library / name
                    if dest_path.exists():
                        if dest_path.is_dir():
                            shutil.rmtree(dest_path)
                        else:
                            dest_path.unlink()
                    if staged_path.is_dir():
                        shutil.copytree(staged_path, dest_path)
                    else:
                        shutil.copy2(staged_path, dest_path)

                    description = entry.get("description") if isinstance(entry, dict) else ""
                    if description:
                        self.descriptions[_norm(dest_path)] = description.strip()
                    imported_keys.add(_norm(dest_path))

        return imported_keys

    def deploy(self):
        game_root = self.app._settings.get("game_root", "")
        import nom_steam
        if not nom_steam.is_valid_game_root(game_root):
            ui_util.warning(self.app, t("No Game Folder"),
                             t("Set a valid Nuclear Option game folder in Config first."))
            return
        if not nom_steam.is_bepinex_installed(game_root):
            ui_util.warning(self.app, t("BepInEx Not Installed"),
                             t("Deployed plugins won't do anything until BepInEx is installed — "
                               "go to Config and click \"Install BepInEx\" first."))
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
                    if path.is_dir():
                        shutil.copytree(path, dest, dirs_exist_ok=True)
                        added += 1
                    elif not dest.exists() or dest.stat().st_size != path.stat().st_size:
                        shutil.copy2(path, dest)
                        added += 1
                else:
                    if dest.is_dir():
                        shutil.rmtree(dest)
                        removed += 1
                    elif dest.exists():
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

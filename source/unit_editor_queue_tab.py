"""
Queue & Build tab — the shared Save/Build/Log surface for every Unit/Ammo Editor category tab.
One companion plugin ("Armory Stat Override") always covers every category's queued overrides
together, so this lives in exactly one place rather than being duplicated per category (see
unit_editor_state.py for the shared queue/baseline all the category tabs feed into).
"""
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import mod_creator_engine as mce
import theme
import ui_util
import unit_editor_engine as uee
import unit_editor_state as ues
from i18n import t


class _Tab:
    def __init__(self, parent, app):
        self.app = app
        self.state = ues.UnitEditorState.get(app)
        self._build_widgets(parent)
        self.state.add_listener(self._refresh_queue_list)
        self._refresh_queue_list()

    def _build_widgets(self, parent):
        intro = ttk.Frame(parent)
        intro.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Label(intro, text=t("Queue & Build"), font=theme.FHEAD, foreground=theme.GOLD).pack(anchor="w")
        ttk.Label(intro, text=t(
            "Every override queued from any Aircraft/Vehicle/Ship/Building/Missile/Ammo tab lands "
            "here. Save Overrides just rewrites a JSON (fast, no recompile); Build Override Plugin "
            "compiles the companion plugin — only needed once, or after an Armory update."),
            wraplength=780, justify="left", foreground=theme.DIM).pack(anchor="w", pady=(2, 0))

        main_paned = ttk.PanedWindow(parent, orient="vertical")
        main_paned.pack(fill="both", expand=True, padx=8, pady=(4, 4))

        queue_frame = ttk.LabelFrame(main_paned, text=t("Queued Overrides"))
        main_paned.add(queue_frame, weight=3)

        self.queue_list = tk.Listbox(
            queue_frame, activestyle="none",
            background=theme.WIDGET, foreground=theme.TEXT,
            selectbackground=theme.SEL_BG, selectforeground=theme.SEL_FG,
            font=theme.F, relief="flat",
            highlightthickness=1, highlightcolor=theme.BORDER, highlightbackground=theme.BORDER)
        qsb = ttk.Scrollbar(queue_frame, orient="vertical", command=self.queue_list.yview)
        self.queue_list.configure(yscrollcommand=qsb.set)
        self.queue_list.pack(side=tk.LEFT, fill="both", expand=True, padx=(4, 0), pady=4)
        qsb.pack(side=tk.RIGHT, fill="y", pady=4)

        ttk.Button(queue_frame, text=t("Remove Selected"), command=self._remove_selected).pack(
            fill="x", padx=4, pady=(0, 4))

        bottom = ttk.Frame(main_paned)
        main_paned.add(bottom, weight=2)

        actions = ttk.Frame(bottom)
        actions.pack(fill="x", pady=(0, 4))
        ttk.Button(actions, text=t("Save Overrides"), command=self._save_overrides).pack(side=tk.LEFT)
        self.build_btn = ttk.Button(actions, text=t("Build Override Plugin"), command=self._on_build_clicked)
        self.build_btn.pack(side=tk.LEFT, padx=(6, 0))
        ui_util.tooltip(self.build_btn, t(
            "Compiles the companion plugin ONCE — you only need to rebuild after an Armory update, "
            "not after every stat change. Save Overrides alone is enough to update values for a "
            "plugin you've already built."))
        self.goto_btn = ttk.Button(actions, text=t("Go to Plugins tab →"),
                                    command=lambda: self.app.goto("manage", "Plugins"))
        self.goto_btn.pack(side=tk.LEFT, padx=(6, 0))

        self.export_btn = ttk.Button(actions, text=t("Export as Named Mod…"), command=self._on_export_clicked)
        self.export_btn.pack(side=tk.LEFT, padx=(6, 0))
        ui_util.tooltip(self.export_btn, t(
            "Bakes a SNAPSHOT of everything currently queued into its own standalone, independently "
            "named/versioned plugin — separate from the shared \"Armory Stat Override\" dev plugin, "
            "so you can share it or keep tweaking the queue without affecting what you already "
            "exported."))

        self.status_var = tk.StringVar(value="")
        ttk.Label(bottom, textvariable=self.status_var, foreground=theme.DIM, wraplength=780).pack(
            anchor="w", pady=(0, 4))

        log_frame = ttk.LabelFrame(bottom, text=t("Build Log"))
        log_frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(log_frame, height=8, state="disabled", wrap="none",
                                 background=theme.WIDGET, foreground=theme.TEXT,
                                 insertbackground=theme.HUD, font=("Courier New", 9),
                                 relief="flat", highlightthickness=1,
                                 highlightbackground=theme.BORDER, highlightcolor=theme.BORDER)
        log_sb = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_sb.set)
        self.log_text.pack(side=tk.LEFT, fill="both", expand=True, padx=(4, 0), pady=4)
        log_sb.pack(side=tk.RIGHT, fill="y", pady=4)

        def _set_initial_split():
            try:
                main_paned.update_idletasks()
                total = main_paned.winfo_height()
                if total > 300:
                    main_paned.sashpos(0, max(160, total - 300))
            except Exception:
                pass
        main_paned.after(100, _set_initial_split)

    # ── Queue ────────────────────────────────────────────────────────────

    def _refresh_queue_list(self):
        self.queue_list.delete(0, tk.END)
        for entry in self.state.queue:
            self.queue_list.insert(tk.END, entry.get("label", f"{entry['type']}.{entry['field']}"))

    def _remove_selected(self):
        self.state.remove_queue_indices(self.queue_list.curselection())

    # ── Save / build ─────────────────────────────────────────────────────

    def _save_overrides(self):
        library = Path(self.app._settings.get("plugin_library", ""))
        if not library.is_dir():
            ui_util.warning(self.app, t("No Library Folder"),
                             t("Set a plugin library folder in Config first."))
            return
        try:
            n = self.state.save_overrides()
        except Exception as e:
            ui_util.error(self.app, t("Couldn't Save Overrides"), str(e))
            return
        self.app.notify_settings_changed()
        if self.state.is_plugin_built():
            self.status_var.set(t("Saved {n} override(s). Already built — just re-deploy in the "
                                   "Plugins tab to apply.", n=n))
        else:
            self.status_var.set(t("Saved {n} override(s). Click \"Build Override Plugin\" (only "
                                   "needed once) before it can be enabled in the Plugins tab.", n=n))

    def _on_build_clicked(self):
        library = Path(self.app._settings.get("plugin_library", ""))
        if not library.is_dir():
            ui_util.warning(self.app, t("No Library Folder"),
                             t("Set a plugin library folder in Config first."))
            return
        game_root = self.app._settings.get("game_root", "")
        import nom_steam
        if not nom_steam.is_bepinex_installed(game_root):
            ui_util.warning(self.app, t("BepInEx Not Installed"),
                             t("Compiling needs BepInEx's own DLLs as references — go to Settings "
                               "and click \"Install BepInEx\" first."))
            return
        dotnet = mce.find_dotnet_exe()
        if not dotnet:
            ui_util.warning(self.app, t("No .NET SDK"),
                             t("Install the .NET SDK to build the override plugin, then reopen this tab."))
            return

        self._save_overrides()

        self.build_btn.configure(state="disabled", text=t("Building…"))
        self.status_var.set(t("Compiling the Armory Stat Override plugin…"))
        self._log(t("Building {name}…\n", name=uee.PLUGIN_NAME))

        project_dir = self.app.state_path("unit_editor_build") / uee.PLUGIN_ID

        def worker():
            result = uee.build(game_root, project_dir, dotnet)
            self.app.after(0, lambda: self._on_build_finished(result))

        threading.Thread(target=worker, daemon=True).start()

    def _on_build_finished(self, result: "mce.BuildResult"):
        self.build_btn.configure(state="normal", text=t("Build Override Plugin"))
        self._log(result.log or t("(no build output)"))

        if not result.success:
            self.status_var.set(t("Build failed — see the log above."))
            return

        try:
            self.state.install_built_dll(result.dll_path.read_bytes())
        except Exception as e:
            self.status_var.set(t("Built OK, but couldn't copy into the plugin library: {err}", err=str(e)))
            return

        self.app.notify_settings_changed()
        self.status_var.set(t(
            "Built and added to your plugin library as \"{id}\". Go to the Plugins tab, enable it, "
            "and click Apply (Deploy).", id=uee.PLUGIN_ID))

    def _log(self, text):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.insert("1.0", text)
        self.log_text.configure(state="disabled")

    # ── Export as a standalone named mod ────────────────────────────────

    def _on_export_clicked(self):
        if not self.state.queue:
            ui_util.warning(self.app, t("Nothing Queued"), t("Queue at least one override first."))
            return
        library = Path(self.app._settings.get("plugin_library", ""))
        if not library.is_dir():
            ui_util.warning(self.app, t("No Library Folder"),
                             t("Set a plugin library folder in Config first."))
            return
        game_root = self.app._settings.get("game_root", "")
        import nom_steam
        if not nom_steam.is_bepinex_installed(game_root):
            ui_util.warning(self.app, t("BepInEx Not Installed"),
                             t("Compiling needs BepInEx's own DLLs as references — go to Settings "
                               "and click \"Install BepInEx\" first."))
            return
        dotnet = mce.find_dotnet_exe()
        if not dotnet:
            ui_util.warning(self.app, t("No .NET SDK"),
                             t("Install the .NET SDK to build a named mod, then reopen this tab."))
            return
        self._open_export_dialog()

    def _open_export_dialog(self):
        win = ui_util.themed_toplevel(self.app, t("Export as Named Mod"),
                                       size=(440, 300), min_size=(400, 280), resizable=False)
        inner = ttk.Frame(win)
        inner.pack(fill="both", expand=True, padx=14, pady=14)
        inner.columnconfigure(1, weight=1)

        ttk.Label(inner, text=t(
            "{n} override(s) currently queued will be baked into this mod as a snapshot — editing "
            "the queue afterward won't change what you're about to export.", n=len(self.state.queue)),
            foreground=theme.DIM, wraplength=380, justify="left").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        ttk.Label(inner, text=t("Name")).grid(row=1, column=0, sticky="w", pady=6)
        name_var = tk.StringVar(value=t("My Balance Mod"))
        ttk.Entry(inner, textvariable=name_var, font=theme.F).grid(row=1, column=1, sticky="ew", pady=6)

        ttk.Label(inner, text=t("Plugin GUID")).grid(row=2, column=0, sticky="w", pady=6)
        guid_var = tk.StringVar(value=mce.suggest_guid(name_var.get()))
        guid_row = ttk.Frame(inner)
        guid_row.grid(row=2, column=1, sticky="ew", pady=6)
        guid_row.columnconfigure(0, weight=1)
        ttk.Entry(guid_row, textvariable=guid_var, font=theme.F).grid(row=0, column=0, sticky="ew")
        ttk.Button(guid_row, text=t("Suggest"),
                   command=lambda: guid_var.set(mce.suggest_guid(name_var.get()))).grid(
            row=0, column=1, padx=(4, 0))

        ttk.Label(inner, text=t("Version")).grid(row=3, column=0, sticky="w", pady=6)
        version_var = tk.StringVar(value="1.0.0")
        ttk.Entry(inner, textvariable=version_var, font=theme.F, width=12).grid(
            row=3, column=1, sticky="w", pady=6)

        btn_bar = ttk.Frame(win)
        btn_bar.pack(side=tk.BOTTOM, fill="x", padx=14, pady=(0, 14))

        def _confirm():
            name = name_var.get().strip()
            guid = guid_var.get().strip()
            version = version_var.get().strip() or "1.0.0"
            if not name:
                ui_util.warning(win, t("Missing Name"), t("Enter a name for the mod."))
                return
            if not guid or "." not in guid:
                ui_util.warning(win, t("Missing GUID"), t("Enter a plugin GUID (e.g. com.you.mymod)."))
                return
            assembly_name = mce.sanitize_identifier(name, "MyMod")
            if assembly_name == uee.PLUGIN_ID:
                ui_util.warning(win, t("Reserved Name"),
                                 t("\"{id}\" is reserved for the shared dev plugin — pick a "
                                   "different name.", id=uee.PLUGIN_ID))
                return
            win.destroy()
            self._run_named_export(assembly_name, guid, name, version)

        ttk.Button(btn_bar, text=t("Cancel"), command=win.destroy).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(btn_bar, text=t("Export"), command=_confirm).pack(side=tk.RIGHT)

    def _run_named_export(self, assembly_name, guid, name, version):
        game_root = self.app._settings.get("game_root", "")
        dotnet = mce.find_dotnet_exe()
        entries_snapshot = [dict(e) for e in self.state.queue]   # frozen NOW, not live-linked

        self.export_btn.configure(state="disabled")
        self.status_var.set(t("Compiling \"{name}\"…", name=name))
        self._log(t("Building {name}…\n", name=name))

        project_dir = self.app.state_path("unit_editor_build") / assembly_name

        def worker():
            result = uee.build_named(game_root, project_dir, dotnet, assembly_name, guid, name, version)
            self.app.after(0, lambda: self._on_named_export_finished(result, assembly_name,
                                                                       entries_snapshot, name))

        threading.Thread(target=worker, daemon=True).start()

    def _on_named_export_finished(self, result, assembly_name, entries_snapshot, display_name):
        self.export_btn.configure(state="normal")
        self._log(result.log or t("(no build output)"))

        if not result.success:
            self.status_var.set(t("Export failed — see the log above."))
            return

        try:
            self.state.export_named_mod(assembly_name, result.dll_path.read_bytes(), entries_snapshot)
        except Exception as e:
            self.status_var.set(t("Built OK, but couldn't write it to your plugin library: {err}", err=str(e)))
            return

        self.app.notify_settings_changed()
        self.status_var.set(t("Exported \"{name}\" — enable it in the Plugins tab.", name=display_name))
        ui_util.info(self.app, t("Exported"), t(
            "\"{name}\" was built with {n} override(s) baked in and added to your plugin library "
            "as its own mod (\"{id}\"). Enable it in the Plugins tab and click Apply (Deploy) to "
            "try it — or share the \"{id}\" folder from your library with someone else to give "
            "them the same mod.", name=display_name, n=len(entries_snapshot), id=assembly_name))


def build(parent, app):
    app._unit_editor_queue_tab = _Tab(parent, app)

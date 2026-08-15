"""
Mod Creator tab — scaffolds a real BepInEx C# plugin project from a template and compiles it with
the installed .NET SDK (mod_creator_engine.py), dropping the resulting DLL straight into the
Plugin Manager's library folder. Generated project sources are kept under this app's own
``mod_creator_projects/`` folder so they can be reopened and hand-edited later (e.g. in Visual
Studio) if the user wants to go beyond what a template covers.
"""
import os
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import ttk

import mod_creator_engine as mce
import nom_steam
import theme
import ui_util
from i18n import t

_TEMPLATES = ["Empty Plugin", "Config Tweak", "Harmony Patch"]

_DEFAULT_PATCH_BODY = 'Debug.Log("patched!");'


class _Tab:
    def __init__(self, parent, app):
        self.app = app
        self._building = False
        self._last_dll_path = None
        self._project_root = app.state_path("mod_creator_projects")
        self._build_widgets(parent)
        self._refresh_dotnet_status()

    # ── Widgets ──────────────────────────────────────────────────────────

    def _build_widgets(self, parent):
        outer = ui_util.make_scrollable(parent)

        self.dotnet_status_var = tk.StringVar(value="")
        self.dotnet_status_lbl = ttk.Label(outer, textvariable=self.dotnet_status_var, cursor="hand2")
        self.dotnet_status_lbl.pack(anchor="w", padx=8, pady=(8, 4))
        self.dotnet_status_lbl.bind("<Button-1>", lambda e: webbrowser.open("https://dotnet.microsoft.com/download"))

        basics = ttk.LabelFrame(outer, text=t("New Plugin"))
        basics.pack(fill="x", padx=8, pady=6)
        basics.columnconfigure(1, weight=1)

        ttk.Label(basics, text=t("Name")).grid(row=0, column=0, sticky="w", padx=8, pady=6)
        self.name_var = tk.StringVar(value="My Mod")
        ttk.Entry(basics, textvariable=self.name_var, font=theme.F).grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=6)

        ttk.Label(basics, text=t("Plugin GUID")).grid(row=1, column=0, sticky="w", padx=8, pady=6)
        self.guid_var = tk.StringVar(value=mce.suggest_guid("My Mod"))
        guid_row = ttk.Frame(basics)
        guid_row.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=6)
        guid_row.columnconfigure(0, weight=1)
        ttk.Entry(guid_row, textvariable=self.guid_var, font=theme.F).grid(row=0, column=0, sticky="ew")
        ttk.Button(guid_row, text=t("Suggest"), command=self._suggest_guid).grid(row=0, column=1, padx=(4, 0))

        ttk.Label(basics, text=t("Version")).grid(row=2, column=0, sticky="w", padx=8, pady=6)
        self.version_var = tk.StringVar(value="1.0.0")
        ttk.Entry(basics, textvariable=self.version_var, font=theme.F, width=12).grid(
            row=2, column=1, sticky="w", padx=(0, 8), pady=6)

        ttk.Label(basics, text=t("Template")).grid(row=3, column=0, sticky="w", padx=8, pady=6)
        self.template_var = tk.StringVar(value=_TEMPLATES[0])
        template_combo = ttk.Combobox(basics, textvariable=self.template_var, values=_TEMPLATES,
                                       state="readonly", font=theme.F)
        template_combo.grid(row=3, column=1, sticky="w", padx=(0, 8), pady=6)
        template_combo.bind("<<ComboboxSelected>>", lambda e: self._show_template_fields())

        self.template_frame = ttk.Frame(outer)
        self.template_frame.pack(fill="x", padx=8, pady=(0, 6))
        self._build_template_fields()
        self._show_template_fields()

        actions = ttk.Frame(outer)
        actions.pack(fill="x", padx=8, pady=(0, 6))
        self.build_btn = ttk.Button(actions, text=t("Build Plugin"), command=self._on_build_clicked)
        self.build_btn.pack(side=tk.LEFT)
        ttk.Button(actions, text=t("Reveal Project Folder"), command=self._reveal_project_folder).pack(
            side=tk.LEFT, padx=(6, 0))

        self.status_var = tk.StringVar(value="")
        ttk.Label(outer, textvariable=self.status_var, foreground=theme.DIM, wraplength=560).pack(
            anchor="w", padx=8, pady=(0, 4))

        log_frame = ttk.LabelFrame(outer, text=t("Build Log"))
        log_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.log_text = tk.Text(log_frame, height=12, state="disabled", wrap="none",
                                 background=theme.WIDGET, foreground=theme.TEXT,
                                 insertbackground=theme.HUD, font=("Courier New", 9),
                                 relief="flat", highlightthickness=1,
                                 highlightbackground=theme.BORDER, highlightcolor=theme.BORDER)
        log_sb = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_sb.set)
        self.log_text.pack(side=tk.LEFT, fill="both", expand=True)
        log_sb.pack(side=tk.RIGHT, fill="y")

    def _build_template_fields(self):
        # Config Tweak fields
        self.cfg_frame = ttk.LabelFrame(self.template_frame, text=t("Config Tweak fields"))
        self.cfg_frame.columnconfigure(1, weight=1)
        ttk.Label(self.cfg_frame, text=t("Setting key")).grid(row=0, column=0, sticky="w", padx=8, pady=4)
        self.cfg_key_var = tk.StringVar(value="MyValue")
        ttk.Entry(self.cfg_frame, textvariable=self.cfg_key_var, font=theme.F).grid(
            row=0, column=1, sticky="ew", padx=(0, 8), pady=4)

        ttk.Label(self.cfg_frame, text=t("Type")).grid(row=1, column=0, sticky="w", padx=8, pady=4)
        self.cfg_type_var = tk.StringVar(value="Single")
        ttk.Combobox(self.cfg_frame, textvariable=self.cfg_type_var,
                     values=["Boolean", "Single", "Int32", "String"], state="readonly", font=theme.F).grid(
            row=1, column=1, sticky="w", padx=(0, 8), pady=4)

        ttk.Label(self.cfg_frame, text=t("Default value")).grid(row=2, column=0, sticky="w", padx=8, pady=4)
        self.cfg_default_var = tk.StringVar(value="1.0")
        ttk.Entry(self.cfg_frame, textvariable=self.cfg_default_var, font=theme.F).grid(
            row=2, column=1, sticky="ew", padx=(0, 8), pady=4)

        ttk.Label(self.cfg_frame, text=t("Description")).grid(row=3, column=0, sticky="w", padx=8, pady=4)
        self.cfg_desc_var = tk.StringVar(value="")
        ttk.Entry(self.cfg_frame, textvariable=self.cfg_desc_var, font=theme.F).grid(
            row=3, column=1, sticky="ew", padx=(0, 8), pady=4)

        # Harmony Patch fields
        self.hp_frame = ttk.LabelFrame(self.template_frame, text=t("Harmony Patch fields"))
        self.hp_frame.columnconfigure(1, weight=1)
        ttk.Label(self.hp_frame, text=t("Target class")).grid(row=0, column=0, sticky="w", padx=8, pady=4)
        self.hp_class_var = tk.StringVar(value="Aircraft")
        class_entry = ttk.Entry(self.hp_frame, textvariable=self.hp_class_var, font=theme.F)
        class_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=4)
        ui_util.tooltip(class_entry, t(
            "A bare name (e.g. Aircraft) works for most gameplay classes. For a class under a "
            "NuclearOption.* namespace, use its full name (e.g. NuclearOption.Workshop.SteamWorkshop)."))

        ttk.Label(self.hp_frame, text=t("Target method")).grid(row=1, column=0, sticky="w", padx=8, pady=4)
        self.hp_method_var = tk.StringVar(value="Awake")
        ttk.Entry(self.hp_frame, textvariable=self.hp_method_var, font=theme.F).grid(
            row=1, column=1, sticky="ew", padx=(0, 8), pady=4)

        ttk.Label(self.hp_frame, text=t("Patch type")).grid(row=2, column=0, sticky="w", padx=8, pady=4)
        self.hp_kind_var = tk.StringVar(value="Postfix")
        ttk.Combobox(self.hp_frame, textvariable=self.hp_kind_var, values=["Prefix", "Postfix"],
                     state="readonly", font=theme.F).grid(row=2, column=1, sticky="w", padx=(0, 8), pady=4)

        ttk.Label(self.hp_frame, text=t("Patch body (C#)")).grid(row=3, column=0, sticky="nw", padx=8, pady=4)
        self.hp_body_text = tk.Text(self.hp_frame, height=4, font=("Courier New", 9),
                                     background=theme.WIDGET, foreground=theme.TEXT,
                                     insertbackground=theme.HUD, relief="flat",
                                     highlightthickness=1, highlightbackground=theme.BORDER)
        self.hp_body_text.insert("1.0", _DEFAULT_PATCH_BODY)
        self.hp_body_text.grid(row=3, column=1, sticky="ew", padx=(0, 8), pady=4)

        # Empty Plugin has no extra fields — just a short note.
        self.empty_frame = ttk.Frame(self.template_frame)
        ttk.Label(self.empty_frame, text=t(
            "Creates a bare, working plugin with no patches — a clean starting point you can build "
            "on by hand-editing the generated Plugin.cs afterward."), wraplength=520, foreground=theme.DIM
        ).pack(anchor="w", padx=8, pady=4)

    def _show_template_fields(self):
        for f in (self.empty_frame, self.cfg_frame, self.hp_frame):
            f.pack_forget()
        template = self.template_var.get()
        if template == "Config Tweak":
            self.cfg_frame.pack(fill="x")
        elif template == "Harmony Patch":
            self.hp_frame.pack(fill="x")
        else:
            self.empty_frame.pack(fill="x")

    def _suggest_guid(self):
        self.guid_var.set(mce.suggest_guid(self.name_var.get()))

    # ── dotnet status ────────────────────────────────────────────────────

    def _refresh_dotnet_status(self):
        dotnet = mce.find_dotnet_exe()
        if dotnet:
            self.dotnet_status_var.set(t("Using .NET SDK: {path}", path=dotnet))
            self.dotnet_status_lbl.configure(foreground=theme.HUD)
            self.build_btn.configure(state="normal")
        else:
            self.dotnet_status_var.set(t(".NET SDK not found — click here to download it."))
            self.dotnet_status_lbl.configure(foreground=theme.RED)
            self.build_btn.configure(state="disabled")

    # ── Build ────────────────────────────────────────────────────────────

    def _log(self, text):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.insert("1.0", text)
        self.log_text.configure(state="disabled")

    def _on_build_clicked(self):
        if self._building:
            return
        name = self.name_var.get().strip()
        guid = self.guid_var.get().strip()
        version = self.version_var.get().strip()
        template = self.template_var.get()

        if not name:
            ui_util.warning(self.app, t("Missing Name"), t("Enter a name for the plugin."))
            return
        if not guid or "." not in guid:
            ui_util.warning(self.app, t("Missing GUID"), t("Enter a plugin GUID (e.g. com.you.mymod)."))
            return
        if not version:
            version = "1.0.0"

        game_root = self.app._settings.get("game_root", "")
        if not nom_steam.is_valid_game_root(game_root):
            ui_util.warning(self.app, t("No Game Folder"),
                             t("Set a valid Nuclear Option game folder in Settings first."))
            return
        if not nom_steam.is_bepinex_installed(game_root):
            ui_util.warning(self.app, t("BepInEx Not Installed"),
                             t("Compiling needs BepInEx's own DLLs as references — go to Settings "
                               "and click \"Install BepInEx\" first."))
            return

        dotnet = mce.find_dotnet_exe()
        if not dotnet:
            ui_util.warning(self.app, t("No .NET SDK"),
                             t("Install the .NET SDK to build plugins, then reopen this tab."))
            return

        namespace = mce.sanitize_identifier(name, "MyMod") + "Ns"
        assembly_name = mce.sanitize_identifier(name, "MyMod")

        try:
            if template == "Config Tweak":
                plugin_cs = mce.render_config_tweak_plugin(
                    namespace, guid, name, version,
                    self.cfg_key_var.get().strip() or "MyValue",
                    self.cfg_type_var.get(),
                    self.cfg_default_var.get().strip() or "0",
                    self.cfg_desc_var.get().strip())
            elif template == "Harmony Patch":
                target_class = self.hp_class_var.get().strip()
                target_method = self.hp_method_var.get().strip()
                if not target_class or not target_method:
                    ui_util.warning(self.app, t("Missing Target"),
                                     t("Enter both a target class and method for the Harmony patch."))
                    return
                plugin_cs = mce.render_harmony_patch_plugin(
                    namespace, guid, name, version, target_class, target_method,
                    self.hp_kind_var.get(), self.hp_body_text.get("1.0", tk.END))
            else:
                plugin_cs = mce.render_empty_plugin(namespace, guid, name, version)
        except Exception as e:
            ui_util.error(self.app, t("Couldn't Generate Code"), str(e))
            return

        references = mce.discover_references(Path(game_root))
        csproj = mce.render_csproj(assembly_name, references)
        project_dir = self._project_root / assembly_name

        self._building = True
        self.build_btn.configure(state="disabled", text=t("Building…"))
        self.status_var.set(t("Compiling with the .NET SDK…"))
        self._log(t("Building {name}…\n", name=name))

        def worker():
            result = mce.build_project(project_dir, csproj, plugin_cs, assembly_name, dotnet)
            self.app.after(0, lambda: self._on_build_finished(result, assembly_name))

        threading.Thread(target=worker, daemon=True).start()

    def _on_build_finished(self, result: "mce.BuildResult", assembly_name: str):
        self._building = False
        self.build_btn.configure(state="normal", text=t("Build Plugin"))
        self._log(result.log or t("(no build output)"))

        if not result.success:
            self.status_var.set(t("Build failed — see the log below."))
            return

        self._last_dll_path = result.dll_path
        library = Path(self.app._settings.get("plugin_library", ""))
        if library.is_dir():
            try:
                dest = library / result.dll_path.name
                dest.write_bytes(result.dll_path.read_bytes())
                self.status_var.set(t("Built and copied to your plugin library: {name}", name=dest.name))
                self.app.notify_settings_changed()
            except Exception as e:
                self.status_var.set(t("Built OK, but couldn't copy to the plugin library: {err}", err=str(e)))
        else:
            self.status_var.set(t(
                "Built OK: {path} — set a plugin library folder in Settings to auto-copy it there.",
                path=str(result.dll_path)))

    def _reveal_project_folder(self):
        try:
            self._project_root.mkdir(parents=True, exist_ok=True)
            os.startfile(self._project_root)
        except Exception as e:
            ui_util.error(self.app, t("Couldn't Open Folder"), str(e))


def build(parent, app):
    app._mod_creator_tab = _Tab(parent, app)

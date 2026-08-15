"""Settings tab — game root, plugin library folder, and an about/version block."""
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import nom_steam
import theme
import ui_util
from i18n import t

_APP_VERSION = "0.1.0"


def build(parent, app):
    pad = {"padx": 6, "pady": 6}

    style = ttk.Style(parent)
    style.configure("Valid.TLabel", background=theme.PANEL, foreground=theme.HUD, font=theme.FB)
    style.configure("Invalid.TLabel", background=theme.PANEL, foreground=theme.RED, font=theme.FB)

    body = ttk.Frame(parent)
    body.pack(fill="both", expand=True, **pad)

    # ── Game root ────────────────────────────────────────────────────────────
    gr_frame = ttk.LabelFrame(body, text=t("Nuclear Option game folder"))
    gr_frame.pack(fill="x", pady=(0, 10))

    gr_var = tk.StringVar(value=app._settings.get("game_root", ""))
    gr_entry = ttk.Entry(gr_frame, textvariable=gr_var, font=theme.F)
    gr_entry.grid(row=0, column=0, sticky="ew", padx=(8, 4), pady=6)
    gr_frame.columnconfigure(0, weight=1)

    gr_status = ttk.Label(gr_frame, text="")
    gr_status.grid(row=1, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 6))

    def _refresh_gr_status():
        if nom_steam.is_valid_game_root(gr_var.get()):
            gr_status.configure(text=t("Found NuclearOption.exe and BepInEx/ here."), style="Valid.TLabel")
        else:
            gr_status.configure(text=t("This folder doesn't look like a Nuclear Option install."),
                                 style="Invalid.TLabel")

    def _save_game_root():
        app._settings["game_root"] = gr_var.get().strip()
        app.save_settings()
        _refresh_gr_status()
        app.notify_settings_changed()

    def _browse_game_root():
        chosen = filedialog.askdirectory(title=t("Select the Nuclear Option game folder"),
                                          initialdir=gr_var.get() or str(Path.home()))
        if chosen:
            gr_var.set(chosen)
            _save_game_root()

    def _autodetect_game_root():
        found = nom_steam.find_nuclear_option_dir()
        if found:
            gr_var.set(str(found))
            _save_game_root()
        else:
            ui_util.warning(app, t("Not Found"), t("Couldn't auto-detect a Nuclear Option Steam install."))

    ttk.Button(gr_frame, text=t("Browse…"), command=_browse_game_root).grid(row=0, column=1, padx=4, pady=6)
    ttk.Button(gr_frame, text=t("Auto-detect"), command=_autodetect_game_root).grid(row=0, column=2, padx=(4, 8), pady=6)
    gr_entry.bind("<FocusOut>", lambda e: _save_game_root())
    gr_entry.bind("<Return>", lambda e: _save_game_root())

    # ── Plugin library ───────────────────────────────────────────────────────
    pl_frame = ttk.LabelFrame(body, text=t("Plugin library folder (your collection of BepInEx .dll mods)"))
    pl_frame.pack(fill="x", pady=(0, 10))

    pl_var = tk.StringVar(value=app._settings.get("plugin_library", ""))
    pl_entry = ttk.Entry(pl_frame, textvariable=pl_var, font=theme.F)
    pl_entry.grid(row=0, column=0, sticky="ew", padx=(8, 4), pady=6)
    pl_frame.columnconfigure(0, weight=1)

    pl_status = ttk.Label(pl_frame, text="")
    pl_status.grid(row=1, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 6))

    def _refresh_pl_status():
        p = pl_var.get().strip()
        if p and Path(p).is_dir():
            n = len(list(Path(p).glob("*.dll")))
            pl_status.configure(text=t("{n} .dll file(s) found here.", n=n), style="Valid.TLabel")
        else:
            pl_status.configure(text=t("Folder doesn't exist yet."), style="Invalid.TLabel")

    def _save_plugin_library():
        app._settings["plugin_library"] = pl_var.get().strip()
        app.save_settings()
        _refresh_pl_status()
        app.notify_settings_changed()

    def _browse_plugin_library():
        chosen = filedialog.askdirectory(title=t("Select your plugin library folder"),
                                          initialdir=pl_var.get() or str(Path.home() / "Desktop"))
        if chosen:
            pl_var.set(chosen)
            _save_plugin_library()

    def _autodetect_plugin_library():
        default_stash = Path.home() / "Desktop" / "Game Mods" / "Nuclear Option Mods"
        if default_stash.is_dir():
            pl_var.set(str(default_stash))
            _save_plugin_library()
        else:
            ui_util.warning(app, t("Not Found"),
                             t("Couldn't find a default plugin stash folder — pick one with Browse."))

    ttk.Button(pl_frame, text=t("Browse…"), command=_browse_plugin_library).grid(row=0, column=1, padx=4, pady=6)
    ttk.Button(pl_frame, text=t("Auto-detect"), command=_autodetect_plugin_library).grid(row=0, column=2, padx=(4, 8), pady=6)
    pl_entry.bind("<FocusOut>", lambda e: _save_plugin_library())
    pl_entry.bind("<Return>", lambda e: _save_plugin_library())

    # ── About ────────────────────────────────────────────────────────────────
    about = ttk.LabelFrame(body, text=t("About"))
    about.pack(fill="x")
    ttk.Label(about, text=t("Nuclear Option Mod Manager"), font=theme.FHEAD).pack(anchor="w", padx=8, pady=(6, 0))
    ttk.Label(about, text=t("Version {v}", v=_APP_VERSION)).pack(anchor="w", padx=8)
    ttk.Label(about, text=t("A companion tool to the R.U.S.E. Mod Manager, sharing its visual theme."),
              wraplength=560).pack(anchor="w", padx=8, pady=(0, 6))

    _refresh_gr_status()
    _refresh_pl_status()

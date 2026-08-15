"""Settings tab — game root, plugin library folder, BepInEx install, and an about/version block."""
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import bepinex_installer
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
            gr_status.configure(text=t("Found NuclearOption.exe here."), style="Valid.TLabel")
        else:
            gr_status.configure(text=t("This folder doesn't look like a Nuclear Option install."),
                                 style="Invalid.TLabel")
        _refresh_bx_status()

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

    # ── BepInEx ──────────────────────────────────────────────────────────────
    # BepInEx is the actual mod-loading runtime (Doorstop-injected into the game process) — it is
    # NOT part of Nuclear Option's own distribution and NOT made obsolete by this app. Without it
    # actually installed, nothing in BepInEx\plugins\ ever gets loaded; this app only manages the
    # files that sit on top of it.
    bx_frame = ttk.LabelFrame(body, text=t("BepInEx (the mod loader Nuclear Option needs)"))
    bx_frame.pack(fill="x", pady=(0, 10))
    bx_frame.columnconfigure(0, weight=1)

    bx_status = ttk.Label(bx_frame, text="")
    bx_status.grid(row=0, column=0, sticky="w", padx=8, pady=(6, 2))
    bx_install_btn = ttk.Button(bx_frame, text=t("Install BepInEx"))
    bx_install_btn.grid(row=0, column=1, padx=(4, 8), pady=(6, 2))
    bx_progress = ttk.Label(bx_frame, text="", foreground=theme.DIM)
    bx_progress.grid(row=1, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 6))

    bx_installing = {"active": False}

    def _refresh_bx_status():
        gr = gr_var.get().strip()
        if not nom_steam.is_valid_game_root(gr):
            bx_status.configure(text=t("Set a valid game folder above first."), style="Invalid.TLabel")
            bx_install_btn.configure(state="disabled", text=t("Install BepInEx"))
        elif nom_steam.is_bepinex_installed(gr):
            bx_status.configure(text=t("Installed."), style="Valid.TLabel")
            bx_install_btn.configure(state="normal", text=t("Reinstall BepInEx"))
        else:
            bx_status.configure(text=t("Not installed — plugins can't load without it."), style="Invalid.TLabel")
            bx_install_btn.configure(state="normal", text=t("Install BepInEx"))

    def _bx_progress_cb(read, total):
        if total:
            pct = int(read * 100 / total)
            app.after(0, lambda: bx_progress.configure(text=t("Downloading… {pct}%", pct=pct)))
        else:
            app.after(0, lambda: bx_progress.configure(text=t("Downloading… {kb} KB", kb=read // 1024)))

    def _bx_install_finished(error):
        bx_installing["active"] = False
        if error:
            bx_progress.configure(text="")
            ui_util.error(app, t("Install Failed"), str(error))
        else:
            bx_progress.configure(text=t("Done."))
            app.notify_settings_changed()
        _refresh_bx_status()

    def _bx_do_install(release):
        try:
            bepinex_installer.install(release, Path(gr_var.get().strip()), progress_cb=_bx_progress_cb)
        except Exception as e:
            app.after(0, lambda: _bx_install_finished(e))
            return
        app.after(0, lambda: _bx_install_finished(None))

    def _on_install_clicked():
        if bx_installing["active"]:
            return
        gr = gr_var.get().strip()
        if not nom_steam.is_valid_game_root(gr):
            return
        bx_install_btn.configure(state="disabled")
        bx_progress.configure(text=t("Checking latest release…"))

        def lookup():
            release = bepinex_installer.find_latest_release()
            app.after(0, lambda: _confirm_and_install(release))

        threading.Thread(target=lookup, daemon=True).start()

    def _confirm_and_install(release):
        size_kb = release.size // 1024
        ok = ui_util.confirm(
            app, t("Install BepInEx?"),
            t("This will download {name} ({size} KB) from github.com/BepInEx/BepInEx and extract "
              "it into your Nuclear Option folder. Continue?", name=release.asset_name, size=size_kb))
        if not ok:
            bx_progress.configure(text="")
            _refresh_bx_status()
            return
        bx_installing["active"] = True
        bx_progress.configure(text=t("Downloading… 0%"))
        threading.Thread(target=_bx_do_install, args=(release,), daemon=True).start()

    bx_install_btn.configure(command=_on_install_clicked)

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

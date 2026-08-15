"""
Setup tab — a RUSE-Mod-Manager-style step checklist. Two required steps (game directory found,
BepInEx installed) gate access to the MANAGE and CREATE tab groups — see nom_app.py's
_refresh_gating(), which this tab's actions trigger via app.notify_settings_changed().
"""
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import bepinex_installer
import nom_steam
import theme
import ui_util
from i18n import t


def build(parent, app):
    style = ttk.Style(parent)
    style.configure("Valid.TLabel", background=theme.PANEL, foreground=theme.HUD, font=theme.FB)
    style.configure("Invalid.TLabel", background=theme.PANEL, foreground=theme.RED, font=theme.FB)

    body = ttk.Frame(parent)
    body.pack(fill="both", expand=True, padx=6, pady=6)

    sf = ttk.LabelFrame(body, text=t("Setup Checklist — complete both steps to use the manager"))
    sf.pack(fill="x", pady=(0, 10))
    sf.columnconfigure(1, weight=1)

    # ── Step 1: game directory ──────────────────────────────────────────────
    ttk.Label(sf, text=t("Step 1"), font=theme.FB, foreground=theme.GOLD).grid(
        row=0, column=0, padx=(8, 4), pady=(8, 2), sticky="nw")
    s1_status = ttk.Label(sf, text="", wraplength=420, justify="left")
    s1_status.grid(row=0, column=1, sticky="ew", padx=4, pady=(8, 2))
    s1_btns = ttk.Frame(sf)
    s1_btns.grid(row=0, column=2, padx=(4, 8), pady=(8, 2))

    gr_var = tk.StringVar(value=app._settings.get("game_root", ""))

    def _save_game_root():
        app._settings["game_root"] = gr_var.get().strip()
        app.save_settings()
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

    ttk.Button(s1_btns, text=t("Browse…"), command=_browse_game_root).pack(side=tk.LEFT, padx=2)
    ttk.Button(s1_btns, text=t("Auto-detect"), command=_autodetect_game_root).pack(side=tk.LEFT, padx=2)

    # ── Step 2: BepInEx ──────────────────────────────────────────────────────
    ttk.Label(sf, text=t("Step 2"), font=theme.FB, foreground=theme.GOLD).grid(
        row=1, column=0, padx=(8, 4), pady=(2, 4), sticky="nw")
    s2_status = ttk.Label(sf, text="", wraplength=420, justify="left")
    s2_status.grid(row=1, column=1, sticky="ew", padx=4, pady=(2, 4))
    bx_install_btn = ttk.Button(sf, text=t("Install BepInEx"))
    bx_install_btn.grid(row=1, column=2, padx=(4, 8), pady=(2, 4))

    bx_progress = ttk.Label(sf, text="", foreground=theme.DIM)
    bx_progress.grid(row=2, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 8))

    bx_installing = {"active": False}

    def _refresh():
        # Re-sync from the canonical settings dict, not just this tab's own Entry — game_root can
        # change from outside this tab's own Browse/Auto-detect flow (tests, future features).
        canonical = app._settings.get("game_root", "")
        if canonical != gr_var.get():
            gr_var.set(canonical)
        gr = gr_var.get().strip()
        if nom_steam.is_valid_game_root(gr):
            s1_status.configure(text=t("Found NuclearOption.exe at {p}", p=gr), style="Valid.TLabel")
        elif gr:
            s1_status.configure(text=t("\"{p}\" doesn't look like a Nuclear Option install.", p=gr),
                                 style="Invalid.TLabel")
        else:
            s1_status.configure(text=t("Not set — Browse to your Nuclear Option folder, or try Auto-detect."),
                                 style="Invalid.TLabel")

        if not nom_steam.is_valid_game_root(gr):
            s2_status.configure(text=t("Complete Step 1 first."), style="Invalid.TLabel")
            bx_install_btn.configure(state="disabled", text=t("Install BepInEx"))
        elif nom_steam.is_bepinex_installed(gr):
            s2_status.configure(text=t("Installed — BepInEx is ready."), style="Valid.TLabel")
            bx_install_btn.configure(state="normal", text=t("Reinstall BepInEx"))
        else:
            s2_status.configure(text=t("Not installed — plugins can't load without it."), style="Invalid.TLabel")
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
        _refresh()

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
        if not nom_steam.is_valid_game_root(gr_var.get().strip()):
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
            _refresh()
            return
        bx_installing["active"] = True
        bx_progress.configure(text=t("Downloading… 0%"))
        threading.Thread(target=_bx_do_install, args=(release,), daemon=True).start()

    bx_install_btn.configure(command=_on_install_clicked)

    note = ttk.Label(
        body, foreground=theme.DIM, wraplength=560, justify="left",
        text=t("BepInEx is the mod-loading runtime Nuclear Option needs — it isn't part of the "
               "game itself, and this app doesn't replace it, only manages what sits on top of it. "
               "Once both steps are green, the MANAGE and CREATE tabs unlock above."))
    note.pack(anchor="w", padx=2)

    app.register_settings_listener(_refresh)
    _refresh()

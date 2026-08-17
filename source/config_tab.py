"""
Config tab (renamed from Setup) — a RUSE-Mod-Manager-style step checklist. Two required steps
(game directory found, BepInEx installed) gate access to the MANAGE and CREATE tab groups — see
nom_app.py's _refresh_gating(), which this tab's actions trigger via app.notify_settings_changed().
The plugin library folder lives here too (moved from the old Settings tab, now Credits) since it's
set-once config a user configures alongside the rest of this checklist.
"""
import shutil
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import bepinex_installer
import blueprinter_installer
import dll_inspector as di
import live_editor_installer as lei
import nom_plugin_meta as npm
import nom_steam
import plugin_library
import theme
import ui_util
from i18n import t


def build(parent, app):
    style = ttk.Style(parent)
    style.configure("Valid.TLabel", background=theme.PANEL, foreground=theme.HUD, font=theme.FB)
    style.configure("Invalid.TLabel", background=theme.PANEL, foreground=theme.RED, font=theme.FB)

    body = ttk.Frame(parent)
    body.pack(fill="both", expand=True, padx=6, pady=6)

    sf = ttk.LabelFrame(body, text=t("Config Checklist — complete both steps to use the manager"))
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
            # Capture the message NOW — `e` is deleted by Python at the end of this except block,
            # but app.after(0, ...) defers the lambda, so closing over `e` itself would raise
            # NameError once the deferred callback actually runs.
            message = str(e)
            app.after(0, lambda: _bx_install_finished(message))
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
    note.pack(anchor="w", padx=2, pady=(0, 10))

    # ── Plugin library folder (not a gating step — set-once config that lives here for
    # convenience, alongside the rest of this checklist) ────────────────────
    pl_frame = ttk.LabelFrame(body, text=t("Plugin library folder (your collection of BepInEx .dll mods)"))
    pl_frame.pack(fill="x", pady=(0, 10))
    pl_frame.columnconfigure(0, weight=1)

    pl_var = tk.StringVar(value=app._settings.get("plugin_library", ""))
    pl_entry = ttk.Entry(pl_frame, textvariable=pl_var, font=theme.F)
    pl_entry.grid(row=0, column=0, sticky="ew", padx=(8, 4), pady=6)

    pl_status = ttk.Label(pl_frame, text="")
    pl_status.grid(row=1, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 6))

    def _refresh_pl_status():
        p = pl_var.get().strip()
        if p and Path(p).is_dir():
            n = len(plugin_library.list_library_entries(Path(p)))
            pl_status.configure(text=t("{n} plugin(s) found here.", n=n), style="Valid.TLabel")
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
        target = plugin_library.auto_detect_library()
        pl_var.set(str(target))
        _save_plugin_library()

    ttk.Button(pl_frame, text=t("Browse…"), command=_browse_plugin_library).grid(
        row=0, column=1, padx=4, pady=6)
    ttk.Button(pl_frame, text=t("Auto-detect"), command=_autodetect_plugin_library).grid(
        row=0, column=2, padx=(4, 8), pady=6)
    pl_entry.bind("<FocusOut>", lambda e: _save_plugin_library())
    pl_entry.bind("<Return>", lambda e: _save_plugin_library())

    _refresh_pl_status()

    # ── Companion tools — installed DIRECTLY into BepInEx/plugins, NOT the toggleable plugin
    # library, so they're always active and can't be accidentally disabled from the Plugins tab.
    # Several other mods depend on Blueprinter/Configuration Manager being present no matter
    # what, so they're treated as config prerequisites rather than optional library entries —
    # plugins_tab.py's scan_library() also filters Blueprinter out by GUID so a stale library
    # copy from before this change can't reappear there either.
    tools_frame = ttk.LabelFrame(body, text=t("Companion Tools (installed directly, always active)"))
    tools_frame.pack(fill="x", pady=(0, 10))
    tools_frame.columnconfigure(1, weight=1)

    def _tools_plugins_dir() -> Path:
        return Path(gr_var.get().strip()) / "BepInEx" / "plugins"

    def _tools_disabled_dir() -> Path:
        # A future mod might not get along with one of these — this holding folder (outside
        # BepInEx's own plugins/ scan path, so inert either way) is what "Disable" below moves a
        # tool into, without uninstalling it, so it's a one-click swap back via "Enable".
        return Path(gr_var.get().strip()) / "BepInEx" / "disabledPlugins"

    ttk.Label(tools_frame, text=t("Blueprinter"), font=theme.FB).grid(
        row=0, column=0, sticky="w", padx=(8, 4), pady=(8, 2))
    bp_status = ttk.Label(tools_frame, text="", wraplength=340, justify="left")
    bp_status.grid(row=0, column=1, sticky="ew", padx=4, pady=(8, 2))
    bp_btn = ttk.Button(tools_frame, text=t("Install Blueprinter"))
    bp_btn.grid(row=0, column=2, padx=(4, 2), pady=(8, 2))
    ui_util.tooltip(bp_btn, t(
        "nikkorap's Blueprinter — the base loader for .nobp asset bundles used by several other "
        "mods. github.com/nikkorap/NOBlueprinter-Releases"))
    bp_toggle_btn = ttk.Button(tools_frame, text=t("Disable"))
    bp_toggle_btn.grid(row=0, column=3, padx=(2, 8), pady=(8, 2))
    ui_util.tooltip(bp_toggle_btn, t(
        "Moves it out of BepInEx/plugins without uninstalling it, in case it's ever incompatible "
        "with something else you're running — click again to bring it back."))

    ttk.Label(tools_frame, text=t("Configuration Manager"), font=theme.FB).grid(
        row=1, column=0, sticky="w", padx=(8, 4), pady=(2, 8))
    cm_status = ttk.Label(tools_frame, text="", wraplength=340, justify="left")
    cm_status.grid(row=1, column=1, sticky="ew", padx=4, pady=(2, 8))
    cm_btn = ttk.Button(tools_frame, text=t("Install Configuration Manager"))
    cm_btn.grid(row=1, column=2, padx=(4, 2), pady=(2, 8))
    ui_util.tooltip(cm_btn, t(
        "Adds an in-game settings screen (F1 by default) auto-generated from every loaded "
        "plugin's config — by the BepInEx team."))
    cm_toggle_btn = ttk.Button(tools_frame, text=t("Disable"))
    cm_toggle_btn.grid(row=1, column=3, padx=(2, 8), pady=(2, 8))
    ui_util.tooltip(cm_toggle_btn, t(
        "Moves it out of BepInEx/plugins without uninstalling it, in case it's ever incompatible "
        "with something else you're running — click again to bring it back."))

    cm_tool = next(tool for tool in lei.TOOLS if tool.tool_id == "BepInEx.ConfigurationManager")

    def _find_blueprinter_anywhere():
        """(path, enabled) for whichever copy exists — the one in BepInEx/plugins wins if somehow
        both exist — or (None, False) if it isn't installed at all."""
        for base, enabled in ((_tools_plugins_dir(), True), (_tools_disabled_dir(), False)):
            if not base.is_dir():
                continue
            for dll in base.glob("*.dll"):
                try:
                    if npm.read_primary_plugin_metadata(dll).guid == blueprinter_installer.BLUEPRINTER_GUID:
                        return dll, enabled
                except Exception:
                    continue
        return None, False

    def _cm_location():
        if (_tools_plugins_dir() / cm_tool.tool_id).is_dir():
            return "enabled"
        if (_tools_disabled_dir() / cm_tool.tool_id).is_dir():
            return "disabled"
        return None

    def _refresh_tools():
        gr = gr_var.get().strip()
        if not nom_steam.is_bepinex_installed(gr):
            for status, btn, toggle, install_label in (
                (bp_status, bp_btn, bp_toggle_btn, t("Install Blueprinter")),
                (cm_status, cm_btn, cm_toggle_btn, t("Install Configuration Manager")),
            ):
                status.configure(text=t("Complete Step 2 first."), style="Invalid.TLabel")
                btn.configure(state="disabled", text=install_label)
                toggle.configure(state="disabled", text=t("Disable"))
            return

        bp_dll, bp_enabled = _find_blueprinter_anywhere()
        if bp_dll is None:
            bp_status.configure(text=t("Not installed."), style="Invalid.TLabel")
            bp_btn.configure(state="normal", text=t("Install Blueprinter"))
            bp_toggle_btn.configure(state="disabled", text=t("Disable"))
        elif bp_enabled:
            bp_status.configure(text=t("Installed & active: {name}", name=bp_dll.name), style="Valid.TLabel")
            bp_btn.configure(state="normal", text=t("Reinstall Blueprinter"))
            bp_toggle_btn.configure(state="normal", text=t("Disable"))
        else:
            bp_status.configure(text=t("Installed but DISABLED: {name}", name=bp_dll.name),
                                 style="Invalid.TLabel")
            bp_btn.configure(state="normal", text=t("Reinstall Blueprinter"))
            bp_toggle_btn.configure(state="normal", text=t("Enable"))

        cm_loc = _cm_location()
        if cm_loc is None:
            cm_status.configure(text=t("Not installed."), style="Invalid.TLabel")
            cm_btn.configure(state="normal", text=t("Install Configuration Manager"))
            cm_toggle_btn.configure(state="disabled", text=t("Disable"))
        elif cm_loc == "enabled":
            cm_status.configure(text=t("Installed & active."), style="Valid.TLabel")
            cm_btn.configure(state="normal", text=t("Reinstall Configuration Manager"))
            cm_toggle_btn.configure(state="normal", text=t("Disable"))
        else:
            cm_status.configure(text=t("Installed but DISABLED."), style="Invalid.TLabel")
            cm_btn.configure(state="normal", text=t("Reinstall Configuration Manager"))
            cm_toggle_btn.configure(state="normal", text=t("Enable"))

    # ── Blueprinter install ──────────────────────────────────────────────
    def _on_bp_install_clicked():
        bp_btn.configure(state="disabled")
        bp_status.configure(text=t("Checking latest release…"), style="Invalid.TLabel")

        def lookup():
            release = blueprinter_installer.find_latest_release()
            app.after(0, lambda: _bp_confirm(release))
        threading.Thread(target=lookup, daemon=True).start()

    def _bp_confirm(release):
        if not release:
            ui_util.error(app, t("Couldn't Check for Updates"),
                           t("Couldn't reach GitHub to look up the latest Blueprinter release."))
            _refresh_tools()
            return
        size_kb = release.size // 1024
        ok = ui_util.confirm(
            app, t("Install Blueprinter?"),
            t("This will download {name} ({size} KB) from github.com/nikkorap/NOBlueprinter-Releases "
              "(by nikkorap) directly into BepInEx/plugins. Continue?", name=release.asset_name, size=size_kb))
        if not ok:
            _refresh_tools()
            return
        bp_status.configure(text=t("Downloading…"), style="Invalid.TLabel")

        def worker():
            try:
                # Reinstalling while a disabled copy exists shouldn't leave a stale duplicate
                # sitting in disabledPlugins/ — a fresh install always lands enabled.
                stale, stale_enabled = _find_blueprinter_anywhere()
                if stale is not None and not stale_enabled:
                    stale.unlink(missing_ok=True)
                blueprinter_installer.install(release, _tools_plugins_dir())
                app.after(0, _refresh_tools)
            except Exception as e:
                # Capture the message NOW — see the comment on the same pattern above.
                message = str(e)
                app.after(0, lambda: (ui_util.error(app, t("Install Failed"), message), _refresh_tools()))
        threading.Thread(target=worker, daemon=True).start()

    bp_btn.configure(command=_on_bp_install_clicked)

    def _on_bp_toggle_clicked():
        dll, enabled = _find_blueprinter_anywhere()
        if dll is None:
            return
        dest_dir = _tools_disabled_dir() if enabled else _tools_plugins_dir()
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dll), str(dest_dir / dll.name))
        except Exception as e:
            ui_util.error(app, t("Couldn't Toggle Blueprinter"), str(e))
        _refresh_tools()

    bp_toggle_btn.configure(command=_on_bp_toggle_clicked)

    # ── Configuration Manager install ────────────────────────────────────
    def _on_cm_install_clicked():
        cm_btn.configure(state="disabled")
        cm_status.configure(text=t("Checking latest release…"), style="Invalid.TLabel")

        def lookup():
            release = lei.find_latest_release(cm_tool)
            app.after(0, lambda: _cm_confirm(release))
        threading.Thread(target=lookup, daemon=True).start()

    def _cm_confirm(release):
        if not release:
            ui_util.error(app, t("Couldn't Check for Updates"),
                           t("Couldn't reach GitHub to look up the latest Configuration Manager release."))
            _refresh_tools()
            return
        size_kb = release.size // 1024
        ok = ui_util.confirm(
            app, t("Install Configuration Manager?"),
            t("This will download {asset} ({size} KB) from github.com/{repo} directly into "
              "BepInEx/plugins. Continue?", asset=release.asset_name, size=size_kb, repo=cm_tool.repo))
        if not ok:
            _refresh_tools()
            return
        cm_status.configure(text=t("Downloading…"), style="Invalid.TLabel")

        def worker():
            try:
                stale = _tools_disabled_dir() / cm_tool.tool_id
                if stale.is_dir():
                    shutil.rmtree(stale)
                lei.install(cm_tool, release, _tools_plugins_dir())
                app.after(0, _refresh_tools)
            except Exception as e:
                # Capture the message NOW — see the comment on the same pattern above.
                message = str(e)
                app.after(0, lambda: (ui_util.error(app, t("Install Failed"), message), _refresh_tools()))
        threading.Thread(target=worker, daemon=True).start()

    cm_btn.configure(command=_on_cm_install_clicked)

    def _on_cm_toggle_clicked():
        loc = _cm_location()
        if loc is None:
            return
        src_dir = _tools_plugins_dir() if loc == "enabled" else _tools_disabled_dir()
        dest_dir = _tools_disabled_dir() if loc == "enabled" else _tools_plugins_dir()
        src = src_dir / cm_tool.tool_id
        dest = dest_dir / cm_tool.tool_id
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                shutil.rmtree(dest)
            shutil.move(str(src), str(dest))
        except Exception as e:
            ui_util.error(app, t("Couldn't Toggle Configuration Manager"), str(e))
        _refresh_tools()

    cm_toggle_btn.configure(command=_on_cm_toggle_clicked)

    # ── Mod Compatibility Checker (DllInspector, by 9138noms — a real independent third-party
    # tool, not something this app authored) — NOT a BepInEx plugin, so it lives in Armory's own
    # tools folder, never BepInEx/plugins. Checks whether a mod DLL's referenced game types/
    # members/Harmony-patch-targets still exist in the current Assembly-CSharp.dll, using
    # Mono.Cecil. Real, confirmed limitation (read from its own source, not guessed): generating a
    # fresh snapshot only works when game_root matches its hardcoded default Steam path exactly —
    # see dll_inspector.py's module docstring — so "Generate Snapshot" stays disabled otherwise
    # rather than silently failing or scanning the wrong game.
    di_frame = ttk.LabelFrame(body, text=t("Mod Compatibility Checker (DllInspector by 9138noms)"))
    di_frame.pack(fill="x", pady=(0, 10))

    def _di_tools_dir() -> Path:
        return app.state_path("tools")

    def _di_exe_path() -> Path:
        return _di_tools_dir() / di.EXE_FILENAME

    def _di_snapshot_path() -> Path:
        return _di_tools_dir() / di.SNAPSHOT_FILENAME

    di_status = ttk.Label(di_frame, text="", wraplength=560, justify="left")
    di_status.grid(row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 2))
    di_snapshot_status = ttk.Label(di_frame, text="", wraplength=560, justify="left")
    di_snapshot_status.grid(row=1, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 8))

    di_install_btn = ttk.Button(di_frame, text=t("Install DllInspector"))
    di_install_btn.grid(row=2, column=0, padx=(8, 4), pady=(0, 8), sticky="w")
    ui_util.tooltip(di_install_btn, t(
        "Downloads the real release from github.com/9138noms/DllInspector — Armory doesn't ship "
        "or modify it, just automates fetching it, the same as BepInEx/Blueprinter."))
    di_snapshot_btn = ttk.Button(di_frame, text=t("Generate Snapshot"))
    di_snapshot_btn.grid(row=2, column=1, padx=(4, 8), pady=(0, 8), sticky="w")
    ui_util.tooltip(di_snapshot_btn, t(
        "Scans the game's own Assembly-CSharp.dll so plugin compatibility can be checked against "
        "it from the Plugins tab. Only available when your game folder matches DllInspector's own "
        "hardcoded default Steam path — a real limitation in the tool itself, not Armory."))

    def _refresh_di():
        gr = gr_var.get().strip()
        exe = _di_exe_path()
        if exe.is_file():
            di_status.configure(text=t("Installed."), style="Valid.TLabel")
            di_install_btn.configure(text=t("Reinstall DllInspector"))
        else:
            di_status.configure(text=t("Not installed."), style="Invalid.TLabel")
            di_install_btn.configure(text=t("Install DllInspector"))

        snap = _di_snapshot_path()
        if snap.is_file():
            di_snapshot_status.configure(
                text=t("Snapshot ready ({size} KB).", size=snap.stat().st_size // 1024),
                style="Valid.TLabel")
        else:
            di_snapshot_status.configure(text=t("No snapshot yet."), style="Invalid.TLabel")

        can_snapshot = di.is_default_path(gr) and exe.is_file()
        di_snapshot_btn.configure(state=("normal" if can_snapshot else "disabled"))
        if exe.is_file() and not di.is_default_path(gr):
            di_snapshot_status.configure(text=t(
                "No snapshot yet. Unavailable: DllInspector can only scan the game at its own "
                "hardcoded default Steam path, and this install isn't there."), style="Invalid.TLabel")

    def _on_di_install_clicked():
        di_install_btn.configure(state="disabled")
        di_status.configure(text=t("Checking latest release…"), style="Invalid.TLabel")

        def lookup():
            release = di.find_latest_release()
            app.after(0, lambda: _di_confirm(release))
        threading.Thread(target=lookup, daemon=True).start()

    def _di_confirm(release):
        if not release:
            ui_util.error(app, t("Couldn't Check for Updates"),
                           t("Couldn't reach GitHub to look up the latest DllInspector release."))
            _refresh_di()
            return
        size_kb = release.asset_size // 1024
        ok = ui_util.confirm(
            app, t("Install DllInspector?"),
            t("This will download {name} ({size} KB) from github.com/9138noms/DllInspector "
              "into Armory's own tools folder (not BepInEx/plugins — this isn't a game mod). "
              "Continue?", name=release.asset_name, size=size_kb))
        if not ok:
            _refresh_di()
            return
        di_status.configure(text=t("Downloading…"), style="Invalid.TLabel")

        def worker():
            try:
                di.download(release, _di_exe_path())
            except Exception as e:
                message = str(e)
                app.after(0, lambda: (ui_util.error(app, t("Install Failed"), message), _refresh_di()))
                return
            app.after(0, _refresh_di)
        threading.Thread(target=worker, daemon=True).start()

    di_install_btn.configure(command=_on_di_install_clicked)

    def _on_di_snapshot_clicked():
        di_snapshot_btn.configure(state="disabled")
        di_snapshot_status.configure(text=t("Scanning Assembly-CSharp.dll…"), style="Invalid.TLabel")

        def worker():
            try:
                di.run_scan(_di_exe_path(), _di_snapshot_path())
            except di.InspectorError as e:
                message = str(e)
                app.after(0, lambda: (ui_util.error(app, t("Scan Failed"), message), _refresh_di()))
                return
            app.after(0, _refresh_di)
        threading.Thread(target=worker, daemon=True).start()

    di_snapshot_btn.configure(command=_on_di_snapshot_clicked)

    app.register_settings_listener(_refresh)
    app.register_settings_listener(_refresh_tools)
    app.register_settings_listener(_refresh_di)
    _refresh()
    _refresh_tools()
    _refresh_di()

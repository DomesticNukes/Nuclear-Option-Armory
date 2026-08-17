"""
Live Editor Suite tab — one-click install/update for RuntimeUnityEditor + BepInEx.ConfigurationManager
(live_editor_installer.py), with honest framing about what they actually are.

Important distinction this tab exists to make clear: these two tools run INSIDE the game process as
a Unity overlay (injected via BepInEx/Harmony) — Armory is an external desktop app and has no way to
embed or become that overlay. What Armory CAN do, and does here, is remove every manual step around
getting them onto your machine and configured: fetch the latest release, drop it in your plugin
library as a normal entry (so the existing Plugins tab enables/deploys/updates it like anything
else), and — where this app has actually verified a fact (ConfigurationManager's real GUID and
default hotkey, read straight off a real deployed .cfg) — offer a direct settings shortcut too.
"""
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import ttk

import live_editor_installer as lei
import nom_plugin_meta as npm
import theme
import ui_util
from i18n import t


class _ToolCard:
    """One tool's LabelFrame + its install/status logic. Built fresh each refresh() call rather
    than tracking widget identity across state changes — these cards are cheap and refresh rarely
    (on tab build, after an install, and on library/game-folder changes)."""

    def __init__(self, outer, app, tab, tool: lei.LiveEditorTool):
        self.app = app
        self.tab = tab
        self.tool = tool
        self.installing = False

        self.frame = ttk.LabelFrame(outer, text=tool.display_name)
        self.frame.pack(fill="x", padx=8, pady=6)

        ttk.Label(self.frame, text=tool.description, wraplength=620, justify="left").pack(
            anchor="w", padx=8, pady=(6, 2))
        ttk.Label(self.frame, text=tool.usage, wraplength=620, justify="left",
                  foreground=theme.DIM).pack(anchor="w", padx=8, pady=(0, 6))

        self.status_var = tk.StringVar(value="")
        self.status_lbl = ttk.Label(self.frame, textvariable=self.status_var, font=theme.FB)
        self.status_lbl.pack(anchor="w", padx=8, pady=(0, 6))

        actions = ttk.Frame(self.frame)
        actions.pack(fill="x", padx=8, pady=(0, 8))

        self.install_btn = ttk.Button(actions, text=t("Install / Update"), command=self._on_install)
        self.install_btn.pack(side=tk.LEFT)

        ttk.Button(actions, text=t("Project Page"),
                   command=lambda: webbrowser.open(tool.homepage)).pack(side=tk.LEFT, padx=(6, 0))

        self.goto_btn = ttk.Button(actions, text=t("Go to Plugins tab →"),
                                    command=lambda: app.goto("manage", "Plugins"))
        self.goto_btn.pack(side=tk.LEFT, padx=(6, 0))

        self.config_btn = ttk.Button(actions, text=t("Edit Settings…"), command=self._on_edit_config)
        self.config_btn.pack(side=tk.LEFT, padx=(6, 0))

        self.refresh()

    # ── Status ───────────────────────────────────────────────────────────

    def refresh(self):
        library = Path(self.app._settings.get("plugin_library", ""))
        in_library = library.is_dir() and lei.is_in_library(self.tool, library)
        deployed = False
        try:
            deployed = lei.is_deployed(self.tool, self.app.bepinex_plugins_dir())
        except Exception:
            pass

        if deployed:
            self.status_var.set(t("● Deployed — active next time you launch the game"))
            self.status_lbl.configure(foreground=theme.HUD)
        elif in_library:
            self.status_var.set(t("○ In your library — enable it in the Plugins tab and Apply (Deploy)"))
            self.status_lbl.configure(foreground=theme.GOLD_BRT)
        else:
            self.status_var.set(t("Not installed"))
            self.status_lbl.configure(foreground=theme.DIM)

        self.goto_btn.configure(state=("normal" if in_library else "disabled"))

        cfg_path = self._find_cfg() if self.tool.guid else None
        self.config_btn.configure(state=("normal" if cfg_path else "disabled"))
        if self.tool.guid and not cfg_path:
            ui_util.tooltip(self.config_btn, t(
                "No settings file yet — BepInEx writes one the first time the game actually loads "
                "this plugin. Deploy it and play once, then come back here."))

    def _find_cfg(self):
        if not self.tool.guid:
            return None
        try:
            return npm.find_cfg_for_guid(self.tool.guid, self.app.bepinex_config_dir())
        except Exception:
            return None

    # ── Install / update ─────────────────────────────────────────────────

    def _on_install(self):
        if self.installing:
            return
        library = Path(self.app._settings.get("plugin_library", ""))
        if not library.is_dir():
            ui_util.warning(self.app, t("No Library Folder"),
                             t("Set a plugin library folder in Config first."))
            return

        self.installing = True
        self.install_btn.configure(state="disabled", text=t("Checking…"))

        def lookup():
            release = lei.find_latest_release(self.tool)
            self.app.after(0, lambda: self._confirm_and_install(release, library))

        threading.Thread(target=lookup, daemon=True).start()

    def _confirm_and_install(self, release, library: Path):
        if not release:
            self.installing = False
            self.install_btn.configure(state="normal", text=t("Install / Update"))
            ui_util.error(self.app, t("Couldn't Check for Updates"),
                           t("Couldn't reach GitHub to look up the latest {name} release.",
                             name=self.tool.display_name))
            return

        already = lei.is_in_library(self.tool, library)
        note = t(" You already have a copy — this will replace it with the latest.") if already else ""
        size_kb = release.size // 1024
        ok = ui_util.confirm(
            self.app, t("Install {name}?", name=self.tool.display_name),
            t("This will download {asset} ({size} KB) from github.com/{repo} into your plugin "
              "library.{note} Continue?", asset=release.asset_name, size=size_kb,
              repo=self.tool.repo, note=note))
        if not ok:
            self.installing = False
            self.install_btn.configure(state="normal", text=t("Install / Update"))
            return

        self.install_btn.configure(text=t("Downloading…"))

        def worker():
            try:
                dest = lei.install(self.tool, release, library)
                self.app.after(0, lambda: self._install_finished(dest, None))
            except Exception as e:
                # Capture the message NOW — `e` is deleted by Python at the end of this except
                # block, but app.after(0, ...) defers the lambda, so closing over `e` itself
                # would raise NameError once the deferred callback actually runs.
                message = str(e)
                self.app.after(0, lambda: self._install_finished(None, message))

        threading.Thread(target=worker, daemon=True).start()

    def _install_finished(self, dest, error):
        self.installing = False
        self.install_btn.configure(state="normal", text=t("Install / Update"))
        if error:
            ui_util.error(self.app, t("Install Failed"), str(error))
            return
        self.app.notify_settings_changed()   # Plugins tab rescans and picks up the new library entry
        self.refresh()
        ui_util.info(self.app, t("Installed"), t(
            "{name} is in your plugin library. Enable it in the Plugins tab and click "
            "Apply (Deploy) to activate it.", name=self.tool.display_name))

    # ── Settings shortcut ────────────────────────────────────────────────

    def _on_edit_config(self):
        cfg_path = self._find_cfg()
        if not cfg_path:
            return
        meta = npm.PluginMeta(guid=self.tool.guid, name=self.tool.display_name,
                               version=None, source="scraped")
        import config_editor
        config_editor.open_editor(self.app, cfg_path, meta)


class _Tab:
    def __init__(self, parent, app):
        self.app = app
        self.cards = []
        self._build_widgets(parent)
        app.register_settings_listener(self.refresh)

    def _build_widgets(self, parent):
        outer = ui_util.make_scrollable(parent)

        intro = ttk.Frame(outer)
        intro.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Label(intro, text=t("Live Editor Suite"), font=theme.FHEAD, foreground=theme.GOLD).pack(
            anchor="w")
        ttk.Label(intro, text=t(
            "These tools run INSIDE the game itself as an in-game overlay — Armory installs and "
            "manages them, but you use them in-game once deployed, not from this window. Install one "
            "below, enable it in the Plugins tab, deploy, then launch the game."),
            wraplength=640, justify="left", foreground=theme.DIM).pack(anchor="w", pady=(2, 0))

        for tool in lei.TOOLS:
            self.cards.append(_ToolCard(outer, self.app, self, tool))

    def refresh(self):
        for card in self.cards:
            card.refresh()


def build(parent, app):
    app._live_editor_tab = _Tab(parent, app)

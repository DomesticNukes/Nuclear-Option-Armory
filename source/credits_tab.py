"""
Credits tab (renamed from Settings) — the About block plus a full credits list for every project,
tool, and person this app builds on top of or bundles an installer for. Nuclear Option Armory is a
companion/wrapper app: it doesn't ship any of these projects' code, it downloads their real
releases from their own GitHub repos (see bepinex_installer.py, blueprinter_installer.py,
live_editor_installer.py) or shells out to their own CLI tools at build time (see build.py).
"""
from tkinter import ttk

import theme
import ui_util
from i18n import t

_APP_VERSION = "0.6.1"


def build(parent, app):
    body = ttk.Frame(parent)
    body.pack(fill="both", expand=True, padx=6, pady=6)
    inner = ui_util.make_scrollable(body)

    about = ttk.LabelFrame(inner, text=t("About"))
    about.pack(fill="x", padx=2, pady=(0, 12))
    ttk.Label(about, text=t("Nuclear Option Armory"), font=theme.FHEAD, foreground=theme.GOLD).pack(
        anchor="w", padx=8, pady=(8, 0))
    ttk.Label(about, text=t("Version {v}", v=_APP_VERSION), font=theme.FB).pack(
        anchor="w", padx=8, pady=(0, 4))
    ttk.Label(
        about, wraplength=560, justify="left",
        text=t("A companion tool to the R.U.S.E. Mod Manager, built for managing BepInEx plugins, "
               "skins, missions, and custom stat overrides for Nuclear Option.")
    ).pack(anchor="w", padx=8, pady=(0, 8))

    credits = ttk.LabelFrame(inner, text=t("Credits — the people and projects this app is built on"))
    credits.pack(fill="x", padx=2, pady=(0, 12))

    def _entry(parent_frame, name, role, link, desc, first=False):
        row = ttk.Frame(parent_frame)
        row.pack(fill="x", padx=8, pady=(10 if first else 8, 0))
        ttk.Label(row, text=name, font=theme.FB, foreground=theme.HUD).pack(anchor="w")
        ttk.Label(row, text=role, font=theme.F, foreground=theme.GOLD).pack(anchor="w")
        ttk.Label(row, text=desc, wraplength=560, justify="left").pack(anchor="w", pady=(2, 0))
        link_lbl = ttk.Label(row, text=link, foreground=theme.DIM, cursor="hand2")
        link_lbl.pack(anchor="w", pady=(2, 0))

    _entry(
        credits, "Shockfront", t("Developer of Nuclear Option"), "store.steampowered.com/app/2168680",
        t("Thank you for making Nuclear Option, and for building it in a way that welcomes modding "
          "in the first place — none of this app would exist without that."),
        first=True)

    _entry(
        credits, "Combat787", t("Original idea & inspiration — NOMM"), "github.com/Combat787/NOMM",
        t("NOMM (Nuclear Option Mod Manager) was the original dedicated mod manager for this game "
          "and the direct inspiration for building Armory in the first place. Armory doesn't share "
          "any of NOMM's code — a separate, independent project — but the idea started there."))

    _entry(
        credits, "LittleGroove", t("Original creator — R.U.S.E. Mod Manager"),
        "github.com/LittleGroove/RUSE-Mod-Manager",
        t("This app's entire look and feel — the theme, colors, panel styling, and general UI "
          "conventions (theme.py / ui_util.py) — is carried over directly from LittleGroove's "
          "R.U.S.E. Mod Manager, the sister project this app was built alongside."))

    _entry(
        credits, "nikkorap", t("Blueprinter"), "github.com/nikkorap/NOBlueprinter-Releases",
        t("The .nobp asset-bundle loader several other Nuclear Option mods depend on. Installed "
          "directly via the Config tab's Companion Tools section, downloaded from nikkorap's own "
          "releases."))

    _entry(
        credits, "BepInEx Team", t("BepInEx"), "github.com/BepInEx/BepInEx",
        t("The mod-loading runtime that makes any of this possible in the first place. Installed "
          "via the Config tab's Step 2, downloaded straight from the BepInEx team's own releases."))

    _entry(
        credits, "BepInEx Team", t("BepInEx.ConfigurationManager"),
        "github.com/BepInEx/BepInEx.ConfigurationManager",
        t("The in-game F1 settings screen, auto-generated from every loaded plugin's config. "
          "Installed directly via the Config tab's Companion Tools section."))

    _entry(
        credits, "ManlyMarco", t("RuntimeUnityEditor"), "github.com/ManlyMarco/RuntimeUnityEditor",
        t("The live scene/object inspector bundled as part of the Live Editor Suite in the Create "
          "tab, downloaded from ManlyMarco's own releases."))

    _entry(
        credits, "Harmony (pardeike / HarmonyX)", t("HarmonyLib"), "github.com/pardeike/Harmony",
        t("The runtime-patching library used by the Mod Creator's Harmony Patch template and by "
          "the generated Armory Stat Override plugin to hook into the game's own classes without "
          "editing its files.")
    )

    tools = ttk.LabelFrame(inner, text=t("Build tooling — used to produce this app's own installer"))
    tools.pack(fill="x", padx=2, pady=(0, 12))

    _entry(tools, "PyInstaller", t("Python → .exe packaging"), "pyinstaller.org",
           t("Used to build this app's standalone executable from its Python source."), first=True)
    _entry(tools, "Inno Setup", t("Windows installer builder"), "jrsoftware.org/isinfo.php",
           t("Used to build the distributable Windows installer for this app."))

    ttk.Label(
        inner, foreground=theme.DIM, wraplength=560, justify="left",
        text=t("Nuclear Option Armory doesn't bundle or redistribute any of the above projects' "
               "source or binaries — each is downloaded from its own official GitHub releases at "
               "install time, or invoked as an external build tool. All trademarks and copyrights "
               "belong to their respective owners.")
    ).pack(anchor="w", padx=2, pady=(0, 12))

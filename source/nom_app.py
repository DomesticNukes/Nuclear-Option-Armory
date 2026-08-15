"""
Nuclear Option Mod Manager
============================
Four switchable tab groups:
  SETUP    — the gating checklist (game directory, BepInEx install) — always reachable
  MANAGE   — Plugins (enable/disable BepInEx DLLs, deploy, edit .cfg settings),
             Missions (organize saved missions), Skins (organize livery folders)
             — locked until Setup's two steps are both done
  CREATE   — Mod Creator (scaffold + compile a real BepInEx plugin from a template)
             — locked until Setup's two steps are both done
  SETTINGS — plugin library folder / about

A persistent "Launch Nuclear Option" button sits in the switcher bar, enabled once a valid game
folder is set.

Companion app to the R.U.S.E. Mod Manager, sharing its visual theme (theme.py / ui_util.py) and
window-chrome conventions but otherwise an independent, standalone project.
"""

import colorsys
import ctypes
import json
import math
import os
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

if getattr(sys, "frozen", False):
    _LAUNCH_DIR = Path(sys.executable).parent.resolve()
else:
    _LAUNCH_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_LAUNCH_DIR))

import i18n
from i18n import t
import theme
import ui_util
import nom_steam

_SETTINGS_FILE = _LAUNCH_DIR / "settings.json"

_PULSE_PERIOD_SEC = 5.0     # one full dim->bright->dim cycle
_PULSE_SAT_DELTA = 0.15     # how far saturation swings each way — kept small on purpose


def _hex_to_rgb01(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _rgb01_to_hex(rgb):
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in rgb)


def _pulse_color(base_hex: str, t: float) -> str:
    """`base_hex` with its saturation gently oscillating over a _PULSE_PERIOD_SEC cycle — hue and
    value stay fixed, so it reads as the same colour breathing, not a colour change."""
    r, g, b = _hex_to_rgb01(base_hex)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    phase = (t % _PULSE_PERIOD_SEC) / _PULSE_PERIOD_SEC
    s = max(0.0, min(1.0, s + math.sin(phase * 2 * math.pi) * _PULSE_SAT_DELTA))
    return _rgb01_to_hex(colorsys.hsv_to_rgb(h, s, v))

# 32x32 gold reticle-on-navy placeholder icon, drawn at runtime (no external asset / dependency).
_ICON_SIZE = 32


def _build_icon_photo() -> tk.PhotoImage:
    """A HUD-green reticle on navy, drawn at runtime — evokes the game's cockpit HUD rather than a
    generic gold app icon."""
    photo = tk.PhotoImage(width=_ICON_SIZE, height=_ICON_SIZE)
    bg = theme.BG
    hud = theme.HUD
    cx = cy = _ICON_SIZE / 2 - 0.5
    outer_r = _ICON_SIZE / 2 - 2
    ring_w = 2.5
    inner_r = 3.5
    photo.put(bg, to=(0, 0, _ICON_SIZE, _ICON_SIZE))
    for y in range(_ICON_SIZE):
        row_colors = []
        for x in range(_ICON_SIZE):
            dx, dy = x - cx, y - cy
            dist = (dx * dx + dy * dy) ** 0.5
            on_ring = abs(dist - outer_r) <= ring_w
            on_crosshair = (abs(dx) <= 1 and dist <= outer_r + 1) or (abs(dy) <= 1 and dist <= outer_r + 1)
            on_dot = dist <= inner_r
            row_colors.append(hud if (on_ring or on_crosshair or on_dot) else bg)
        # put() accepts one row at a time as a brace-delimited color list for speed.
        photo.put("{" + " ".join(row_colors) + "}", to=(0, y))
    return photo


def _atomic_write_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class NomApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()   # stay hidden until startup finishes; deiconify() at the end of __init__
        self.minsize(900, 640)
        self.resizable(True, True)
        self.configure(background=theme.BG)

        self._set_window_icon()
        self._apply_titlebar_theme()
        self._settings = self._load_settings()
        i18n.load(self._settings.get("default_language", "us"))
        self.title(t("Nuclear Option Mod Manager"))

        if not self._settings.get("game_root"):
            self._auto_detect_game_root()
        if not self._settings.get("plugin_library"):
            self._auto_detect_plugin_library()

        self._settings_listeners = []
        self._apply_theme()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Centre the window on screen before showing it (Tk otherwise leaves it at a monitor corner).
        try:
            self.update_idletasks()
            w, h = self.winfo_reqwidth(), self.winfo_reqheight()
            x = (self.winfo_screenwidth() - w) // 2
            y = (self.winfo_screenheight() - h) // 3
            self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        except Exception:
            pass
        self.deiconify()

    # ── Window chrome ─────────────────────────────────────────────────────────

    def _set_window_icon(self):
        try:
            photo = _build_icon_photo()
            self.iconphoto(True, photo)
            self._icon_photo = photo   # keep reference so GC doesn't drop it
        except Exception:
            pass

    def _apply_titlebar_theme(self):
        """Colour the OS title bar via Windows DWM.

        Win11 21H2+: sets exact caption + border colours from the app palette.
        Win10:       falls back to system dark-mode (dark grey bar).
        Fails silently on non-Windows or old builds.
        """
        def _colorref(hex_str: str) -> int:
            h = hex_str.lstrip("#")
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            return (b << 16) | (g << 8) | r   # COLORREF = 0x00BBGGRR

        try:
            dwm = ctypes.windll.dwmapi
            hwnd = self.winfo_id()
            for attr, value in (
                (35, ctypes.c_uint32(_colorref(theme.BG))),        # DWMWA_CAPTION_COLOR
                (36, ctypes.c_uint32(_colorref(theme.GOLD_BRT))),  # DWMWA_TEXT_COLOR
                (34, ctypes.c_uint32(_colorref(theme.HUD))),       # DWMWA_BORDER_COLOR — HUD green outline
            ):
                try:
                    dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
                except Exception:
                    pass
            dark = ctypes.c_int(1)
            dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), ctypes.sizeof(dark))  # Win10 fallback
        except Exception:
            pass

    # ── Theme ─────────────────────────────────────────────────────────────────

    def _apply_theme(self):
        s = ttk.Style(self)
        s.theme_use("clam")

        ui_util.configure_dialogs(
            panel_bg=theme.PANEL, widget_bg=theme.WIDGET, border=theme.BORDER,
            text=theme.TEXT, dim=theme.DIM, gold=theme.GOLD, gold_brt=theme.GOLD_BRT,
            btn=theme.BTN, btn_act=theme.BTN_ACT, sel_bg=theme.SEL_BG, sel_fg=theme.SEL_FG,
            font=theme.F, font_bold=theme.FB, font_head=theme.FHEAD)

        s.configure("TFrame", background=theme.PANEL)
        s.configure("TLabelFrame", background=theme.PANEL, bordercolor=theme.BORDER, relief="groove")
        s.configure("TLabelFrame.Label", background=theme.PANEL, foreground=theme.GOLD, font=theme.FB)

        s.configure("TLabel", background=theme.PANEL, foreground=theme.TEXT, font=theme.F)

        s.configure("TButton", background=theme.BTN, foreground=theme.TEXT, font=theme.FB,
                     bordercolor=theme.BORDER, relief="flat", padding=(8, 3))
        s.map("TButton",
              background=[("active", theme.BTN_ACT), ("pressed", theme.SEL_BG), ("disabled", theme.PANEL)],
              foreground=[("active", theme.GOLD_BRT), ("disabled", theme.DIM)])

        s.configure("TEntry", fieldbackground=theme.WIDGET, foreground=theme.TEXT, font=theme.F,
                     insertcolor=theme.GOLD, bordercolor=theme.BORDER,
                     selectbackground=theme.SEL_BG, selectforeground=theme.SEL_FG)

        s.configure("TCombobox", fieldbackground=theme.WIDGET, foreground=theme.TEXT, font=theme.F,
                     background=theme.BTN, arrowcolor=theme.GOLD, bordercolor=theme.BORDER,
                     selectbackground=theme.SEL_BG, selectforeground=theme.SEL_FG)
        s.map("TCombobox", fieldbackground=[("readonly", theme.WIDGET)],
              selectbackground=[("readonly", theme.SEL_BG)])

        s.configure("TCheckbutton", background=theme.PANEL, foreground=theme.TEXT, font=theme.F,
                     focuscolor=theme.GOLD)
        s.map("TCheckbutton", background=[("active", theme.PANEL)], foreground=[("active", theme.GOLD)])

        s.configure("Group.TButton", background=theme.BTN, foreground=theme.DIM, font=theme.FHEAD,
                     bordercolor=theme.BORDER, relief="flat", padding=(16, 6))
        s.map("Group.TButton",
              background=[("active", theme.BTN_ACT)],
              foreground=[("active", theme.TEXT)])
        s.configure("GroupActive.TButton", background=theme.HUD_BG, foreground=theme.HUD, font=theme.FHEAD,
                     bordercolor=theme.HUD_DIM, relief="flat", padding=(16, 6))
        s.map("GroupActive.TButton",
              background=[("active", theme.HUD_BG)],
              foreground=[("active", theme.HUD)])

        s.configure("Launch.TButton", background=theme.HUD_BG, foreground=theme.HUD, font=theme.FHEAD,
                     bordercolor=theme.HUD, relief="flat", padding=(16, 6))
        s.map("Launch.TButton",
              background=[("active", theme.HUD_BG), ("disabled", theme.BTN)],
              foreground=[("active", theme.HUD), ("disabled", theme.DIM)])

        s.configure("TNotebook", background=theme.BG, bordercolor=theme.BORDER, tabmargins=[2, 4, 0, 0])
        s.configure("TNotebook.Tab", background=theme.BTN, foreground=theme.DIM, font=theme.FB,
                     padding=(12, 5), bordercolor=theme.BORDER)
        s.map("TNotebook.Tab", background=[("selected", theme.PANEL)], foreground=[("selected", theme.GOLD)])

        s.configure("TScrollbar", background=theme.PANEL, troughcolor=theme.WIDGET,
                     arrowcolor=theme.GOLD, bordercolor=theme.BORDER, relief="flat")
        s.map("TScrollbar", background=[("active", theme.BTN_ACT)])

        s.configure("Treeview", background=theme.WIDGET, foreground=theme.TEXT,
                     fieldbackground=theme.WIDGET, font=theme.F, bordercolor=theme.BORDER, rowheight=20)
        s.configure("Treeview.Heading", background=theme.BTN, foreground=theme.GOLD, font=theme.FB,
                     bordercolor=theme.BORDER, relief="flat")
        s.map("Treeview", background=[("selected", theme.SEL_BG)], foreground=[("selected", theme.SEL_FG)])
        s.map("Treeview.Heading", background=[("active", theme.BTN_ACT)])

        s.configure("TPanedwindow", background=theme.BG)
        s.configure("Sash", sashthickness=5, sashpad=2, background=theme.BORDER)

        s.configure("TSeparator", background=theme.BORDER)

        s.configure("TLabelframe", background=theme.PANEL, bordercolor=theme.BORDER, relief="groove")
        s.configure("TLabelframe.Label", background=theme.PANEL, foreground=theme.GOLD, font=theme.FB)

        self.tk_setPalette(
            background=theme.PANEL, foreground=theme.TEXT,
            activeBackground=theme.BTN_ACT, activeForeground=theme.GOLD_BRT,
            selectBackground=theme.SEL_BG, selectForeground=theme.SEL_FG,
            insertBackground=theme.GOLD, highlightBackground=theme.BORDER, highlightColor=theme.GOLD,
            disabledForeground=theme.DIM,
        )

    # ── Settings ──────────────────────────────────────────────────────────────

    def _load_settings(self) -> dict:
        d = {"game_root": "", "plugin_library": "", "default_language": "us"}
        saved = {}
        if _SETTINGS_FILE.exists():
            try:
                with open(_SETTINGS_FILE, encoding="utf-8") as f:
                    saved = json.load(f) or {}
            except Exception:
                saved = {}
        if not isinstance(saved, dict):
            saved = {}
        d.update(saved)
        if not isinstance(d.get("game_root"), str):
            d["game_root"] = ""
        if not isinstance(d.get("plugin_library"), str):
            d["plugin_library"] = ""
        return d

    def save_settings(self):
        try:
            _atomic_write_json(_SETTINGS_FILE, self._settings)
        except Exception as e:
            ui_util.error(self, t("Save Error"), str(e))

    def _auto_detect_game_root(self):
        try:
            found = nom_steam.find_nuclear_option_dir()
            if found:
                self._settings["game_root"] = str(found)
                self.save_settings()
        except Exception:
            pass

    def _auto_detect_plugin_library(self):
        default_stash = Path.home() / "Desktop" / "Game Mods" / "Nuclear Option Mods"
        try:
            if default_stash.is_dir():
                self._settings["plugin_library"] = str(default_stash)
                self.save_settings()
        except Exception:
            pass

    def bepinex_plugins_dir(self) -> Path:
        return Path(self._settings.get("game_root", "")) / "BepInEx" / "plugins"

    def bepinex_config_dir(self) -> Path:
        return Path(self._settings.get("game_root", "")) / "BepInEx" / "config"

    def register_settings_listener(self, fn):
        """Call `fn()` whenever game_root/plugin_library changes (e.g. so the Plugins tab rescans)."""
        self._settings_listeners.append(fn)

    def notify_settings_changed(self):
        for fn in list(self._settings_listeners):
            try:
                fn()
            except Exception:
                pass

    def state_path(self, filename: str) -> Path:
        return _LAUNCH_DIR / filename

    def missions_dir(self) -> Path:
        return Path.home() / "AppData" / "LocalLow" / "Shockfront" / "NuclearOption" / "Missions"

    def skins_dir(self) -> Path:
        return Path.home() / "AppData" / "LocalLow" / "Shockfront" / "NuclearOption" / "Skins"

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        import setup_tab
        import plugins_tab
        import missions_tab
        import skins_tab
        import mod_creator_tab
        import settings_tab

        # Four top-level groups, switched via the bar below rather than one flat row of tabs:
        #   SETUP    — the gating checklist (game directory, BepInEx) — single tab, always reachable
        #   MANAGE   — day-to-day mod management (Plugins/Missions/Skins) — locked until setup's done
        #   CREATE   — build tools (Mod Creator) — locked until setup's done
        #   SETTINGS — day-to-day preferences (plugin library, about) — single tab, next to Create
        groups = [
            ("setup", t("SETUP"), [(t("Setup"), setup_tab.build)]),
            ("manage", t("MANAGE"), [
                (t("  Plugins  "), plugins_tab.build),
                (t("  Missions  "), missions_tab.build),
                (t("  Skins  "), skins_tab.build),
            ]),
            ("create", t("CREATE"), [(t("Mod Creator"), mod_creator_tab.build)]),
            ("settings", t("SETTINGS"), [(t("Settings"), settings_tab.build)]),
        ]
        _GATED_GROUPS = ("manage", "create")

        switcher = ttk.Frame(self)
        switcher.pack(fill="x", padx=6, pady=(6, 0))

        content = ttk.Frame(self)
        content.pack(fill="both", expand=True, padx=6, pady=6)
        content.rowconfigure(0, weight=1)
        content.columnconfigure(0, weight=1)

        self._group_notebooks = {}
        self._group_buttons = {}
        self._active_group = None

        def _show_group(key):
            if self._group_buttons[key].cget("state") == "disabled":
                return
            for gkey, page in self._group_notebooks.items():
                page.grid_remove()
            self._group_notebooks[key].grid(row=0, column=0, sticky="nsew")
            for gkey, btn in self._group_buttons.items():
                btn.configure(style=("GroupActive.TButton" if gkey == key else "Group.TButton"))
            self._active_group = key

        for key, label, tabs in groups:
            if len(tabs) == 1:
                page = ttk.Frame(content)
                page.grid(row=0, column=0, sticky="nsew")
                tabs[0][1](page, self)
            else:
                page = ttk.Notebook(content)
                page.grid(row=0, column=0, sticky="nsew")
                for tab_label, builder in tabs:
                    frame = ttk.Frame(page)
                    page.add(frame, text=tab_label)
                    builder(frame, self)
            self._group_notebooks[key] = page

            btn = ttk.Button(switcher, text=label, style="Group.TButton",
                              command=lambda k=key: _show_group(k))
            btn.pack(side=tk.LEFT, padx=(0, 4), ipady=2)
            self._group_buttons[key] = btn

        self._launch_btn = ttk.Button(switcher, text=t("▶ Launch Nuclear Option"),
                                       style="Launch.TButton", command=self.launch_game)
        self._launch_btn.pack(side=tk.RIGHT, ipady=2)
        self._start_launch_button_pulse()

        def _refresh_gating():
            ready = nom_steam.is_mod_ready(self._settings.get("game_root", ""))
            for gk in _GATED_GROUPS:
                self._group_buttons[gk].configure(state=("normal" if ready else "disabled"))
            if not ready and self._active_group in _GATED_GROUPS:
                _show_group("setup")
            self._launch_btn.configure(
                state=("normal" if nom_steam.is_valid_game_root(self._settings.get("game_root", "")) else "disabled"))

        self.register_settings_listener(_refresh_gating)
        initial = "manage" if nom_steam.is_mod_ready(self._settings.get("game_root", "")) else "setup"
        _show_group(initial)
        _refresh_gating()

    def launch_game(self):
        try:
            os.startfile(f"steam://rungameid/{nom_steam.NUCLEAR_OPTION_APPID}")
        except Exception as e:
            ui_util.error(self, t("Couldn't Launch"), str(e))

    def _start_launch_button_pulse(self):
        """A slow saturation breathe on the Launch button — pure flavour, so any failure here
        (e.g. the window closing mid-tick) must never surface as an error."""
        style = ttk.Style(self)
        self._pulse_after_id = None

        def _tick():
            try:
                color = _pulse_color(theme.HUD, time.monotonic())
                style.configure("Launch.TButton", foreground=color, bordercolor=color)
                self._pulse_after_id = self.after(100, _tick)
            except Exception:
                pass

        _tick()

    def _on_close(self):
        if getattr(self, "_pulse_after_id", None):
            try:
                self.after_cancel(self._pulse_after_id)
            except Exception:
                pass
        self.destroy()


def main():
    try:
        import single_instance
        if not single_instance.acquire():
            sys.exit(0)
    except SystemExit:
        raise
    except Exception:
        pass

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("NuclearOptionModManager")
    except Exception:
        pass

    try:
        app = NomApp()
    except SystemExit:
        raise
    except Exception as startup_err:
        import traceback
        tb = traceback.format_exc()
        try:
            r = tk.Tk()
            r.withdraw()
            ui_util.error(r, t("Startup Failed"), t("Nuclear Option Mod Manager couldn't start: {err}", err=str(startup_err)))
            r.destroy()
        except Exception:
            pass
        try:
            sys.stderr.write(tb)
        except Exception:
            pass
        sys.exit(1)
    app.mainloop()


if __name__ == "__main__":
    main()

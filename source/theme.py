"""Single source of truth for the app's visual theme.

The "Field Operations" military palette — dark navy command-room steel, scratched silver-white text,
military gold — plus the Courier terminal fonts. Started as a byte-for-byte copy of the R.U.S.E. Mod
Manager's theme.py; since forked to add an HUD_* green accent evoking a cockpit HUD/avionics display
(fitting for Nuclear Option specifically), layered on top of the same navy/gold base so the app still
reads as part of the same family. Every window, tab and editor imports its colours and fonts from
HERE so the whole app reads as one system.

Gold stays the primary "brand" accent (headings, selection, tab highlight — matches RUSE). HUD green
is used specifically for active/positive status: an enabled plugin, a workshop-published mission, a
valid detected path — the glowing-green-readout feel of a cockpit instrument coming online.

ui_util's themed pop-up dialogs are pointed at these same values via ``nom_app._apply_theme`` (which
forwards them to ``ui_util.configure_dialogs``), so dialogs match their parent windows too.

Naming is deliberately neutral (``PANEL`` not ``_NOM_BG_PANEL``): each module binds its own local
names to these, e.g. ``_PANEL = theme.PANEL``, so nothing at call sites needs to change if a value here does.
"""

# ── Colours ───────────────────────────────────────────────────────────────────
BG        = "#08101c"   # deep navy black — window background
PANEL     = "#0e1a2a"   # navy blue — frame / panel background
WIDGET    = "#060d18"   # near-black navy — listbox / entry / log background
BORDER    = "#243a5c"   # steel blue border
GOLD      = "#c8a020"   # military gold — primary accent
GOLD_BRT  = "#e0c030"   # bright gold — headings / selected text
RED       = "#b03020"   # danger red
GREEN     = "#3a8030"   # success / OK green (status only) — kept for compatibility, prefer HUD below
TEXT      = "#ccd8e8"   # scratched silver-white — body text
DIM       = "#3e5878"   # muted steel blue — hint / secondary text
SEL_BG    = "#1a3060"   # selection background
SEL_FG    = "#e0c030"   # selection foreground
BTN       = "#122030"   # button face
BTN_ACT   = "#1e3250"   # button active / hover

# ── Cockpit HUD green ────────────────────────────────────────────────────────
HUD       = "#33ff6a"   # bright phosphor green — active/enabled/valid status, the "HUD" accent
HUD_DIM   = "#1f8f47"   # dimmer green — borders, secondary HUD marks, hover states
HUD_BG    = "#08170f"   # near-black green-tinted panel background, for HUD-flavoured surfaces

# ── Fonts ─────────────────────────────────────────────────────────────────────
F      = ("Courier New", 9)            # body
FB     = ("Courier New", 9, "bold")    # emphasis
FHEAD  = ("Courier New", 10, "bold")   # headings
FS     = ("Courier New", 8)            # small / secondary

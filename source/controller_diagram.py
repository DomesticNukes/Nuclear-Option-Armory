"""
Controller Diagram — a clickable controller layout drawn on a plain tk.Canvas, in one of two modes:

- **Vector mode** ("xbox"/"playstation"): renders the real SVG artwork in assets/controllers/ (via
  svg_path.py, a small stdlib-only parser — see that module's docstring for why: Tkinter has no
  native SVG support) plus real, measured hotspot positions from controller_vector_layouts.py, so
  clicks land exactly on the real button in the real artwork. Two synthetic "bracket pointer" marks
  (like a manual's "see here" leader) stand in for LB/RB/LT/RT, which neither source SVG draws as
  separate shapes — clicking one lets the caller offer a choice between the bumper and trigger on
  that side (see controller_tab.py's _on_slot_clicked).
- **Generic mode** (anything else / SLOT_KEYWORDS didn't recognize the connected hardware): the
  original hand-drawn gamepad silhouette, kept as a fallback so an unrecognized real controller still
  gets a usable (if generic) diagram instead of nothing.

A slot with no real element matched to it (see controller_tab.py's fuzzy name matching) is still
drawn, just dimmed and unclickable — never silently mislabeled with a guess.
"""
from __future__ import annotations

import tkinter as tk

import controller_vector_layouts as cvl
import svg_path as svgp
import theme

# ── Generic (fallback) layout, in a fixed virtual coordinate space ──────────────────────────────
_VW, _VH = 480, 300

SLOTS = [
    {"id": "face_north", "shape": "oval", "coords": (392, 96, 424, 128)},
    {"id": "face_south", "shape": "oval", "coords": (392, 156, 424, 188)},
    {"id": "face_east",  "shape": "oval", "coords": (422, 126, 454, 158)},
    {"id": "face_west",  "shape": "oval", "coords": (362, 126, 394, 158)},
    {"id": "lb", "shape": "rect", "coords": (54, 40, 134, 62)},
    {"id": "rb", "shape": "rect", "coords": (346, 40, 426, 62)},
    {"id": "lt", "shape": "rect", "coords": (54, 16, 134, 36)},
    {"id": "rt", "shape": "rect", "coords": (346, 16, 426, 36)},
    {"id": "l_stick", "shape": "oval", "coords": (100, 150, 148, 198)},
    {"id": "r_stick", "shape": "oval", "coords": (272, 150, 320, 198)},
    {"id": "dpad_up",    "shape": "tri_up",    "coords": (170, 96, 194, 118)},
    {"id": "dpad_down",  "shape": "tri_down",  "coords": (170, 128, 194, 150)},
    {"id": "dpad_left",  "shape": "tri_left",  "coords": (146, 112, 168, 134)},
    {"id": "dpad_right", "shape": "tri_right", "coords": (196, 112, 218, 134)},
    {"id": "menu_select", "shape": "oval", "coords": (216, 68, 240, 84)},
    {"id": "menu_start",  "shape": "oval", "coords": (256, 68, 280, 84)},
]

_SLOT_LABEL_OFFSET = {
    "face_north": (0, -16), "face_south": (0, 16), "face_east": (18, 0), "face_west": (-18, 0),
    "lb": (0, -12), "rb": (0, -12), "lt": (0, -12), "rt": (0, -12),
    "l_stick": (0, 22), "r_stick": (0, 22),
    "dpad_up": (0, -12), "dpad_down": (0, 12), "dpad_left": (-14, 0), "dpad_right": (14, 0),
    "menu_select": (0, -12), "menu_start": (0, -12),
}

_VECTOR_LABEL_OFFSET = {
    "face_north": (0, -13), "face_south": (0, 13), "face_east": (14, 0), "face_west": (-14, 0),
    "l_stick": (0, 20), "r_stick": (0, 20),
    "dpad_up": (0, -11), "dpad_down": (0, 11), "dpad_left": (-11, 0), "dpad_right": (11, 0),
    "menu_select": (0, -10), "menu_start": (0, -10),
    "shoulder_left": (0, -10), "shoulder_right": (0, -10),
}

_BRACKET_SIZE = 10   # half-height of the [ / ] bracket mark, in SVG unit space


class ControllerDiagram(tk.Canvas):
    def __init__(self, parent, on_slot_click=None, controller_type: str = "generic", **kwargs):
        kwargs.setdefault("background", theme.WIDGET)
        kwargs.setdefault("highlightthickness", 1)
        kwargs.setdefault("highlightbackground", theme.BORDER)
        kwargs.setdefault("highlightcolor", theme.BORDER)
        super().__init__(parent, **kwargs)
        self._on_slot_click = on_slot_click
        self._slot_shape_ids = {}
        self._slot_label_ids = {}
        self._slot_states = {}
        self._pending_labels = {}
        self._vector_shapes = None   # cached svgp.Shape list, loaded lazily
        self.set_controller_type(controller_type)
        self.bind("<Configure>", lambda e: self._redraw())
        self._redraw()

    # ── Public API ───────────────────────────────────────────────────────────

    def set_controller_type(self, controller_type: str):
        self.controller_type = controller_type if controller_type in cvl.LAYOUTS else "generic"
        self.layout = cvl.LAYOUTS.get(self.controller_type)
        self._vector_shapes = None
        self._pending_labels.clear()
        self._slot_states.clear()
        self._redraw()

    def set_slot_label(self, slot_id: str, text: str, state: str = "bound"):
        """`state` is "bound" (HUD green — has a real action assigned), "unbound" (gold outline —
        a real physical element with nothing assigned), or "unmapped" (dim — this diagram slot
        couldn't be confidently matched to any real element on the connected controller)."""
        self._pending_labels[slot_id] = text
        self._slot_states[slot_id] = state
        self._redraw()

    def clear(self):
        self._pending_labels.clear()
        self._slot_states.clear()
        self._redraw()

    # ── Shared helpers ───────────────────────────────────────────────────────

    def _state_colors(self, state):
        if state == "bound":
            return theme.HUD_DIM, theme.HUD
        if state == "unbound":
            return theme.BTN, theme.GOLD
        return theme.WIDGET, theme.DIM

    def _handle_click(self, slot_id):
        if self._on_slot_click:
            self._on_slot_click(slot_id)

    def _redraw(self):
        self.delete("all")
        self._slot_shape_ids.clear()
        self._slot_label_ids.clear()
        if self.layout is not None:
            self._redraw_vector()
        else:
            self._redraw_generic()

    # ── Generic (hand-drawn) mode ────────────────────────────────────────────

    def _scale_generic(self):
        w = max(self.winfo_width(), 10)
        h = max(self.winfo_height(), 10)
        s = min(w / _VW, h / _VH)
        return s, (w - _VW * s) / 2, (h - _VH * s) / 2

    def _redraw_generic(self):
        s, ox, oy = self._scale_generic()
        self.create_oval(20 * s + ox, 60 * s + oy, 160 * s + ox, 220 * s + oy,
                          fill=theme.PANEL, outline=theme.BORDER, width=2)
        self.create_oval(320 * s + ox, 60 * s + oy, 460 * s + ox, 220 * s + oy,
                          fill=theme.PANEL, outline=theme.BORDER, width=2)
        self.create_rectangle(90 * s + ox, 60 * s + oy, 390 * s + ox, 200 * s + oy,
                               fill=theme.PANEL, outline=theme.PANEL)
        for slot in SLOTS:
            self._draw_generic_slot(slot, s, ox, oy)

    def _draw_generic_slot(self, slot, s, ox, oy):
        slot_id = slot["id"]
        state = self._slot_states.get(slot_id, "unmapped")
        fill, outline = self._state_colors(state)
        x0, y0, x1, y1 = [v * s for v in slot["coords"]]
        x0, x1 = x0 + ox, x1 + ox
        y0, y1 = y0 + oy, y1 + oy
        shape = slot["shape"]

        if shape == "oval":
            item = self.create_oval(x0, y0, x1, y1, fill=fill, outline=outline, width=2)
        elif shape == "rect":
            item = self.create_rectangle(x0, y0, x1, y1, fill=fill, outline=outline, width=2)
        else:
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            if shape == "tri_up":
                pts = [cx, y0, x1, y1, x0, y1]
            elif shape == "tri_down":
                pts = [cx, y1, x0, y0, x1, y0]
            elif shape == "tri_left":
                pts = [x0, cy, x1, y0, x1, y1]
            else:
                pts = [x1, cy, x0, y0, x0, y1]
            item = self.create_polygon(pts, fill=fill, outline=outline, width=2)

        self._slot_shape_ids[slot_id] = item
        if state != "unmapped":
            self.tag_bind(item, "<Button-1>", lambda e, sid=slot_id: self._handle_click(sid))
            self.tag_bind(item, "<Enter>", lambda e: self.configure(cursor="hand2"))
            self.tag_bind(item, "<Leave>", lambda e: self.configure(cursor=""))

        label_text = self._pending_labels.get(slot_id, "")
        if label_text:
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            dx, dy = _SLOT_LABEL_OFFSET.get(slot_id, (0, 14))
            label_item = self.create_text(cx + dx * s, cy + dy * s, text=label_text,
                                           fill=theme.TEXT, font=theme.FS, width=90 * s)
            self._slot_label_ids[slot_id] = label_item
            if state != "unmapped":
                self.tag_bind(label_item, "<Button-1>", lambda e, sid=slot_id: self._handle_click(sid))

    # ── Vector (real SVG artwork) mode ───────────────────────────────────────

    def _scale_vector(self):
        minx, miny, maxx, maxy = self.layout.bbox
        pad = 24
        w = max(self.winfo_width(), 10)
        h = max(self.winfo_height(), 10)
        bw, bh = maxx - minx, maxy - miny
        s = min((w - pad * 2) / bw, (h - pad * 2) / bh)
        ox = (w - bw * s) / 2 - minx * s
        oy = (h - bh * s) / 2 - miny * s
        return s, ox, oy

    def _tx_vector(self, x, y, s, ox, oy):
        return x * s + ox, y * s + oy

    def _redraw_vector(self):
        if self._vector_shapes is None:
            try:
                self._vector_shapes = svgp.load_svg_shapes(str(self.layout.svg_path))
            except Exception:
                self._vector_shapes = []
        s, ox, oy = self._scale_vector()

        for shape in self._vector_shapes:
            fill = shape.fill if shape.fill and shape.fill != "none" else ""
            outline = shape.stroke if shape.stroke else ""
            if shape.kind == "polygon":
                pts = []
                for x, y in shape.points:
                    pts.extend(self._tx_vector(x, y, s, ox, oy))
                if len(pts) >= 6:
                    self.create_polygon(pts, fill=fill, outline=outline, width=1)
            else:
                cx, cy, r = shape.points[0]
                x0, y0 = self._tx_vector(cx - r, cy - r, s, ox, oy)
                x1, y1 = self._tx_vector(cx + r, cy + r, s, ox, oy)
                self.create_oval(x0, y0, x1, y1, fill=fill, outline=outline, width=1)

        for hotspot in self.layout.hotspots:
            self._draw_vector_hotspot(hotspot, s, ox, oy)

        self._draw_bracket(self.layout.bracket_left, "shoulder_left", s, ox, oy, points_right=True)
        self._draw_bracket(self.layout.bracket_right, "shoulder_right", s, ox, oy, points_right=False)

    def _draw_vector_hotspot(self, hotspot, s, ox, oy):
        state = self._slot_states.get(hotspot.slot_id, "unmapped")
        fill, outline = self._state_colors(state)
        cx, cy = self._tx_vector(*hotspot.center, s, ox, oy)
        r = hotspot.radius * s
        item = self.create_oval(cx - r, cy - r, cx + r, cy + r, fill="", outline=outline, width=2)
        self._slot_shape_ids[hotspot.slot_id] = item
        if state != "unmapped":
            self.tag_bind(item, "<Button-1>", lambda e, sid=hotspot.slot_id: self._handle_click(sid))
            self.tag_bind(item, "<Enter>", lambda e: self.configure(cursor="hand2"))
            self.tag_bind(item, "<Leave>", lambda e: self.configure(cursor=""))

        label_text = self._pending_labels.get(hotspot.slot_id, "")
        if label_text:
            dx, dy = _VECTOR_LABEL_OFFSET.get(hotspot.slot_id, (0, 12))
            label_item = self.create_text(cx + dx * s, cy + dy * s, text=label_text,
                                           fill=theme.TEXT, font=theme.FS, width=90 * s)
            self._slot_label_ids[hotspot.slot_id] = label_item
            if state != "unmapped":
                self.tag_bind(label_item, "<Button-1>", lambda e, sid=hotspot.slot_id: self._handle_click(sid))

    def _draw_bracket(self, anchor, slot_id, s, ox, oy, points_right: bool):
        """A '[' or ']' pointer mark standing in for the missing LB/RB/LT/RT artwork — see module
        docstring. `anchor` is the bracket's own top corner in SVG unit space; it always opens
        toward the controller body (right-opening on the left side, left-opening on the right)."""
        ax, ay = anchor
        x0, y0 = self._tx_vector(ax, ay, s, ox, oy)
        h = _BRACKET_SIZE * s
        tick = 6 * s
        state = self._slot_states.get(slot_id, "unmapped")
        fill, outline = self._state_colors(state)
        tick_dir = tick if points_right else -tick
        pts = [x0 + tick_dir, y0, x0, y0, x0, y0 + h, x0 + tick_dir, y0 + h]
        item = self.create_line(pts, fill=outline, width=3, capstyle="round", joinstyle="round")
        self._slot_shape_ids[slot_id] = item
        if state != "unmapped":
            self.tag_bind(item, "<Button-1>", lambda e, sid=slot_id: self._handle_click(sid))
            self.tag_bind(item, "<Enter>", lambda e: self.configure(cursor="hand2"))
            self.tag_bind(item, "<Leave>", lambda e: self.configure(cursor=""))

        label_text = self._pending_labels.get(slot_id, "LB / LT" if points_right else "RB / RT")
        label_x = x0 + (14 * s if points_right else -14 * s)
        label_item = self.create_text(label_x, y0 + h / 2, text=label_text, fill=theme.TEXT,
                                       font=theme.FS, width=70 * s,
                                       anchor=("w" if points_right else "e"))
        self._slot_label_ids[slot_id] = label_item
        self.tag_bind(label_item, "<Button-1>", lambda e, sid=slot_id: self._handle_click(sid))

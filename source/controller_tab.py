"""
Controller Mapper tab — remap a connected gamepad's buttons/axes to real in-game Rewired actions,
via a clickable 2D controller diagram (controller_diagram.py) backed by REAL data: the companion
"Armory Controller Dump" plugin (controller_engine.py) reports real action names and real per-
controller element names straight from Rewired's own runtime API, and edits are written directly
into Nuclear Option's real saved keybindings (rewired_registry.py) — the same Windows Registry
PlayerPrefs data the game's own in-game control-remapping screen reads and writes.

Three-step flow, mirrored in the UI top-to-bottom:
  1. Build + deploy the dumper plugin once (same compile pipeline as Mod Creator / Unit Editor),
     then launch the game at least once with a controller connected so it has real data to dump.
  2. Pick the connected controller + action category, load its real current bindings.
  3. Click a button on the diagram (or a row in the full element list, which always covers every
     real element even ones the diagram's fuzzy name-matching couldn't confidently place) to bind/
     unbind/re-bind it to a real action. Nothing touches the registry until "Save to Game" — the
     game must be closed first (writing while it's running risks its own exit-time save undoing the
     edit), and the ORIGINAL bytes are always backed up first (see rewired_registry.backup_value).
"""
from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import controller_diagram as cdiag
import controller_engine as cte
import controller_vector_layouts as cvl
import mod_creator_engine as mce
import nom_steam
import rewired_registry as rr
import theme
import ui_util
from i18n import t

_SLOT_KEYWORDS = {
    "face_north": ["north", "triangle"],
    "face_south": ["south", "cross"],
    "face_east": ["east", "circle"],
    "face_west": ["west", "square"],
    "lb": ["left bumper", "left shoulder", "l1"],
    "rb": ["right bumper", "right shoulder", "r1"],
    "lt": ["left trigger", "l2"],
    "rt": ["right trigger", "r2"],
    "dpad_up": ["d-pad up", "dpad up", "hat up", "pov up", "d pad up"],
    "dpad_down": ["d-pad down", "dpad down", "hat down", "pov down", "d pad down"],
    "dpad_left": ["d-pad left", "dpad left", "hat left", "pov left", "d pad left"],
    "dpad_right": ["d-pad right", "dpad right", "hat right", "pov right", "d pad right"],
    "menu_select": ["select", "back", "view", "share", "touchpad"],
    "menu_start": ["start", "menu", "options"],
}
# Real Xbox-template element names are bare single letters ("A"/"B"/"X"/"Y", confirmed live) — an
# exact (not substring) match, since a substring check for "x"/"y" would also match "Left Stick X"/
# "Right Stick Y". PlayStation-style single-word names (Cross/Circle/Square/Triangle) are still
# caught by the substring keywords above.
_SLOT_EXACT_NAMES = {
    "face_south": {"a"}, "face_east": {"b"}, "face_west": {"x"}, "face_north": {"y"},
}
_STICK_PREFIX = {"l_stick": "left stick", "r_stick": "right stick"}
# The two synthetic bracket-pointer hotspots (see controller_diagram.py) each stand in for a real
# PAIR of slots that neither source SVG draws separately — clicking one offers a choice between them,
# the same two-step pattern _open_stick_axis_chooser already uses for a stick's X/Y axes.
_SHOULDER_GROUPS = {"shoulder_left": ("lb", "lt"), "shoulder_right": ("rb", "rt")}

_DIAGRAM_TYPE_CHOICES = ["Auto", "Xbox", "PlayStation", "Generic"]


def _elements_matching(keywords, elements, exact_names=None):
    out = []
    for el in elements:
        name = (el.get("name") or "").strip().lower()
        if exact_names and name in exact_names:
            out.append(el)
            continue
        haystack = " ".join(filter(None, [el.get("name"), el.get("positiveName"), el.get("negativeName")])).lower()
        if any(kw in haystack for kw in keywords):
            out.append(el)
    return out


class _Tab:
    def __init__(self, parent, app):
        self.app = app
        self.dump = {"categories": [], "actions": [], "joysticks": []}
        self.selected_joystick = None      # dict from dump["joysticks"]
        self.selected_category_id = None
        self.current_map = None            # dict from rr.list_joystick_maps() for the current selection
        self.current_xml = None            # in-memory XML, possibly edited but not yet saved
        self.original_bytes = None         # exact bytes read from the registry, for backup-before-write
        self.entries = []                  # parsed rr.ActionElementMap list from current_xml
        self.dirty = False
        self._build_widgets(parent)
        self._refresh_build_status()
        self._refresh_dump(silent=True)

    # ── Layout ───────────────────────────────────────────────────────────────

    def _build_widgets(self, parent):
        intro = ttk.Frame(parent)
        intro.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Label(intro, text=t("Controller Mapper"), font=theme.FHEAD, foreground=theme.GOLD).pack(anchor="w")
        ttk.Label(intro, text=t(
            "Remap a connected controller's buttons straight into Nuclear Option's real saved "
            "keybindings (the same Rewired data its own Controls menu uses). Needs a one-time "
            "companion plugin to read real button/action names from the live game."),
            wraplength=780, justify="left", foreground=theme.DIM).pack(anchor="w", pady=(2, 0))

        build_row = ttk.Frame(parent)
        build_row.pack(fill="x", padx=8, pady=(6, 4))
        self.build_btn = ttk.Button(build_row, text=t("Build Controller Dumper Plugin"),
                                     command=self._on_build_clicked)
        self.build_btn.pack(side=tk.LEFT)
        self.refresh_btn = ttk.Button(build_row, text=t("Refresh Data From Game"),
                                       command=lambda: self._refresh_dump(silent=False))
        self.refresh_btn.pack(side=tk.LEFT, padx=(6, 0))
        self.build_status_var = tk.StringVar(value="")
        ttk.Label(build_row, textvariable=self.build_status_var, foreground=theme.DIM).pack(
            side=tk.LEFT, padx=(10, 0))

        picker_row = ttk.Frame(parent)
        picker_row.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(picker_row, text=t("Controller:")).pack(side=tk.LEFT)
        self.joystick_var = tk.StringVar(value="")
        self.joystick_combo = ttk.Combobox(picker_row, textvariable=self.joystick_var,
                                            state="readonly", width=34)
        self.joystick_combo.pack(side=tk.LEFT, padx=(4, 12))
        self.joystick_combo.bind("<<ComboboxSelected>>", lambda e: self._on_joystick_selected())

        ttk.Label(picker_row, text=t("Category:")).pack(side=tk.LEFT)
        self.category_var = tk.StringVar(value="")
        self.category_combo = ttk.Combobox(picker_row, textvariable=self.category_var,
                                            state="readonly", width=24)
        self.category_combo.pack(side=tk.LEFT, padx=(4, 12))
        self.category_combo.bind("<<ComboboxSelected>>", lambda e: self._on_category_selected())

        ttk.Label(picker_row, text=t("Diagram:")).pack(side=tk.LEFT)
        saved_type = self.app._settings.get("controller_diagram_type", "Auto")
        self.diagram_type_var = tk.StringVar(
            value=saved_type if saved_type in _DIAGRAM_TYPE_CHOICES else "Auto")
        diagram_type_combo = ttk.Combobox(picker_row, textvariable=self.diagram_type_var,
                                           state="readonly", width=12, values=_DIAGRAM_TYPE_CHOICES)
        diagram_type_combo.pack(side=tk.LEFT, padx=(4, 0))
        diagram_type_combo.bind("<<ComboboxSelected>>", lambda e: self._on_diagram_type_changed())
        ui_util.tooltip(diagram_type_combo, t(
            "Which controller artwork to draw. \"Auto\" picks Xbox/PlayStation from the real "
            "connected controller's own reported name; override it if that guess is wrong, or if "
            "you'd rather map a different controller's bindings than the one plugged in right now."))

        main_paned = ttk.PanedWindow(parent, orient="horizontal")
        main_paned.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        diagram_frame = ttk.LabelFrame(main_paned, text=t("Diagram (click a button)"))
        main_paned.add(diagram_frame, weight=3)
        self.diagram = cdiag.ControllerDiagram(diagram_frame, on_slot_click=self._on_slot_clicked,
                                                controller_type="generic")
        self.diagram.pack(fill="both", expand=True, padx=4, pady=4)

        list_frame = ttk.LabelFrame(main_paned, text=t("Every Button/Axis On This Controller"))
        main_paned.add(list_frame, weight=2)
        self.tree = ttk.Treeview(list_frame, columns=("type", "bound"), show="tree headings",
                                  selectmode="browse")
        self.tree.heading("#0", text=t("Element"))
        self.tree.heading("type", text=t("Type"))
        self.tree.heading("bound", text=t("Bound To"))
        self.tree.column("type", width=60, anchor="center", stretch=False)
        self.tree.column("bound", width=180, anchor="w")
        tree_sb = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_sb.set)
        self.tree.pack(side=tk.LEFT, fill="both", expand=True, padx=(4, 0), pady=4)
        tree_sb.pack(side=tk.RIGHT, fill="y", pady=4)
        self.tree.bind("<Double-1>", lambda e: self._on_tree_activate())
        ttk.Button(list_frame, text=t("Manage Binding…"), command=self._on_tree_activate).pack(
            side=tk.BOTTOM, fill="x", padx=4, pady=(0, 4))

        bottom = ttk.Frame(parent)
        bottom.pack(fill="x", padx=8, pady=(0, 8))
        self.save_btn = ttk.Button(bottom, text=t("Save to Game"), command=self._on_save_clicked,
                                    state="disabled")
        self.save_btn.pack(side=tk.LEFT)
        self.discard_btn = ttk.Button(bottom, text=t("Discard Changes"), command=self._on_discard_clicked,
                                       state="disabled")
        self.discard_btn.pack(side=tk.LEFT, padx=(6, 0))
        self.status_var = tk.StringVar(value=t("Build the dumper plugin below, then launch the "
                                                "game once with your controller connected."))
        ttk.Label(bottom, textvariable=self.status_var, foreground=theme.DIM, wraplength=780).pack(
            side=tk.LEFT, padx=(10, 0))

    # ── Build / deploy the dumper plugin ────────────────────────────────────

    def _deploy_folder(self) -> Path:
        """Where a freshly-built DLL is written first, in the plugin LIBRARY — the Plugins tab's own
        Apply (Deploy) button is what copies it onward into BepInEx/plugins."""
        return Path(self.app._settings.get("plugin_library", "")) / cte.PLUGIN_ID

    def _dump_path(self) -> Path:
        """Where the companion plugin actually writes its live dump: next to its OWN compiled
        assembly at runtime (see controller_engine.py's Plugin.cs), which is the DEPLOYED copy
        inside BepInEx/plugins — NOT the library copy. Deploy only ever copies library -> BepInEx/
        plugins, one-way, so a file the running game writes into BepInEx/plugins never appears back
        in the library on its own."""
        return self.app.bepinex_plugins_dir() / cte.PLUGIN_ID / cte.DUMP_FILENAME

    def _is_plugin_built(self) -> bool:
        return (self._deploy_folder() / f"{cte.PLUGIN_ID}.dll").is_file()

    def _refresh_build_status(self):
        if self._is_plugin_built():
            self.build_status_var.set(t("Dumper plugin built. Enable it in the Plugins tab if you "
                                         "haven't, then launch the game once."))
        else:
            self.build_status_var.set(t("Dumper plugin not built yet."))

    def _on_build_clicked(self):
        library = Path(self.app._settings.get("plugin_library", ""))
        if not library.is_dir():
            ui_util.warning(self.app, t("No Library Folder"),
                             t("Set a plugin library folder in Config first."))
            return
        game_root = self.app._settings.get("game_root", "")
        if not nom_steam.is_bepinex_installed(game_root):
            ui_util.warning(self.app, t("BepInEx Not Installed"),
                             t("Compiling needs BepInEx's own DLLs as references — go to Config "
                               "and click \"Install BepInEx\" first."))
            return
        dotnet = mce.find_dotnet_exe()
        if not dotnet:
            ui_util.warning(self.app, t("No .NET SDK"),
                             t("Install the .NET SDK to build the dumper plugin, then reopen this tab."))
            return

        self.build_btn.configure(state="disabled", text=t("Building…"))
        self.status_var.set(t("Compiling the Armory Controller Dump plugin…"))
        project_dir = self.app.state_path("controller_mapper_build") / cte.PLUGIN_ID

        def worker():
            result = cte.build(game_root, project_dir, dotnet)
            self.app.after(0, lambda: self._on_build_finished(result))

        threading.Thread(target=worker, daemon=True).start()

    def _on_build_finished(self, result: "mce.BuildResult"):
        self.build_btn.configure(state="normal", text=t("Build Controller Dumper Plugin"))
        if not result.success:
            ui_util.show_text(self.app, t("Build Failed"),
                               t("Couldn't build the dumper plugin — see the log below."),
                               result.log or t("(no build output)"))
            self.status_var.set(t("Build failed — see the error dialog."))
            return
        try:
            dest_folder = self._deploy_folder()
            dest_folder.mkdir(parents=True, exist_ok=True)
            (dest_folder / f"{cte.PLUGIN_ID}.dll").write_bytes(result.dll_path.read_bytes())
        except Exception as e:
            self.status_var.set(t("Built OK, but couldn't copy into the plugin library: {err}", err=str(e)))
            return
        self.app.notify_settings_changed()
        self._refresh_build_status()
        self.status_var.set(t("Built. Enable \"Armory Controller Dump\" in the Plugins tab, deploy, "
                               "then launch the game once with your controller connected."))

    # ── Loading real data from the dump ─────────────────────────────────────

    def _refresh_dump(self, silent: bool):
        dump_path = self._dump_path()
        if not dump_path.is_file():
            if not silent:
                ui_util.warning(self.app, t("No Data Yet"),
                                 t("No dump file found yet — build the plugin, enable + deploy it in "
                                   "the Plugins tab, then launch the game once with your controller "
                                   "connected."))
            return
        self.dump = cte.read_dump(dump_path)
        joystick_names = [self._joystick_label(j) for j in self.dump["joysticks"]]
        self.joystick_combo.configure(values=joystick_names)
        if joystick_names and self.joystick_var.get() not in joystick_names:
            self.joystick_var.set(joystick_names[0])
        category_names = [self._category_label(c) for c in self.dump["categories"]]
        self.category_combo.configure(values=category_names)
        if category_names and self.category_var.get() not in category_names:
            self.category_var.set(category_names[0])
        # .set() on the StringVar does NOT fire <<ComboboxSelected>> (that only fires on a real user
        # pick), so the category selection has to be applied explicitly here too, not just the
        # joystick one — otherwise selected_category_id stays None and nothing ever loads.
        if category_names:
            self._on_category_selected()
        if joystick_names:
            self._on_joystick_selected()
        if not silent:
            self.status_var.set(t("Loaded {j} controller(s), {a} action(s).",
                                   j=len(self.dump["joysticks"]), a=len(self.dump["actions"])))

    @staticmethod
    def _joystick_label(j: dict) -> str:
        return f'{j.get("hardwareName") or j.get("name") or "Unknown Controller"} (#{j.get("unityId", "?")})'

    @staticmethod
    def _category_label(c: dict) -> str:
        return c.get("descriptiveName") or c.get("name") or f'Category {c.get("id")}'

    def _find_joystick_by_label(self, label):
        for j in self.dump["joysticks"]:
            if self._joystick_label(j) == label:
                return j
        return None

    def _find_category_by_label(self, label):
        for c in self.dump["categories"]:
            if self._category_label(c) == label:
                return c
        return None

    def _effective_diagram_type(self) -> str:
        """The controller_diagram.py "controller_type" this tab should actually draw: the user's
        explicit override if they picked one, else auto-detected from the real connected
        controller's own reported hardwareName (never a guess made without real data — "Auto" with
        no controller selected yet just falls back to the generic diagram)."""
        choice = self.diagram_type_var.get()
        if choice == "Xbox":
            return "xbox"
        if choice == "PlayStation":
            return "playstation"
        if choice == "Generic":
            return "generic"
        if self.selected_joystick is not None:
            return cvl.guess_layout_key(self.selected_joystick.get("hardwareName", ""))
        return "generic"

    def _on_diagram_type_changed(self):
        self.app._settings["controller_diagram_type"] = self.diagram_type_var.get()
        self.app.save_settings()
        self.diagram.set_controller_type(self._effective_diagram_type())
        self._refresh_diagram()

    def _on_joystick_selected(self):
        self.selected_joystick = self._find_joystick_by_label(self.joystick_var.get())
        self.diagram.set_controller_type(self._effective_diagram_type())
        self._load_current_map()

    def _on_category_selected(self):
        cat = self._find_category_by_label(self.category_var.get())
        self.selected_category_id = cat["id"] if cat else None
        self._load_current_map()

    def _load_current_map(self):
        if self.selected_joystick is None or self.selected_category_id is None:
            return
        if self.dirty:
            if not ui_util.confirm(self.app, t("Discard Unsaved Changes?"),
                                    t("Switching controller/category will discard unsaved binding "
                                      "changes. Continue?")):
                return
        hardware_guid = self.selected_joystick.get("hardwareTypeGuid", "")
        self.current_map = rr.find_joystick_map(hardware_guid, self.selected_category_id)
        if self.current_map is None:
            self.current_xml = None
            self.original_bytes = None
            self.entries = []
            self.dirty = False
            self._set_dirty(False)
            self.status_var.set(t(
                "No saved bindings found for this controller in this category yet — bind at least "
                "one button to it from Nuclear Option's own Controls menu first, then click "
                "\"Refresh Data From Game\" here."))
            self._refresh_tree()
            self._refresh_diagram()
            return
        self.original_bytes = rr.read_value_bytes(self.current_map["value_name"])
        self.current_xml = rr.read_map_xml(self.current_map["value_name"])
        self.entries = rr.parse_action_element_maps(self.current_xml) if self.current_xml else []
        self._set_dirty(False)
        self.status_var.set(t("Loaded real saved bindings for this controller/category."))
        self._refresh_tree()
        self._refresh_diagram()

    # ── Rendering ────────────────────────────────────────────────────────────

    def _action_display(self, action_id: int) -> str:
        for a in self.dump["actions"]:
            if a.get("id") == action_id:
                name = a.get("name") or f"Action {action_id}"
                desc = a.get("descriptiveName")
                return f"{name} — {desc}" if desc and desc != name else name
        return t("(unknown action #{id})", id=action_id)

    def _bindings_label(self, element_id: int) -> str:
        matches = rr.bindings_for_element(self.entries, element_id)
        if not matches:
            return t("(unbound)")
        return "; ".join(self._action_display(m.action_id) for m in matches)

    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        if self.selected_joystick is None:
            return
        for el in self.selected_joystick.get("elements", []):
            self.tree.insert("", tk.END, iid=str(el["id"]), text=el.get("name") or f'Element {el["id"]}',
                              values=(el.get("elementType", ""), self._bindings_label(el["id"])))

    def _refresh_diagram(self):
        self.diagram.clear()
        if self.selected_joystick is None:
            return
        elements = self.selected_joystick.get("elements", [])
        for slot_id, keywords in _SLOT_KEYWORDS.items():
            matches = _elements_matching(keywords, elements, exact_names=_SLOT_EXACT_NAMES.get(slot_id))
            if not matches:
                continue
            el = matches[0]
            bindings = rr.bindings_for_element(self.entries, el["id"])
            state = "bound" if bindings else "unbound"
            label = self._bindings_label(el["id"])
            self.diagram.set_slot_label(slot_id, label, state=state)
        for slot_id, prefix in _STICK_PREFIX.items():
            matches = [e for e in _elements_matching([prefix], elements) if e.get("elementType") == "Axis"]
            if not matches:
                continue
            any_bound = any(rr.bindings_for_element(self.entries, el["id"]) for el in matches)
            self.diagram.set_slot_label(slot_id, t("stick"), state=("bound" if any_bound else "unbound"))
        for bracket_slot_id, (sub_a, sub_b) in _SHOULDER_GROUPS.items():
            found = []
            for sub_slot_id in (sub_a, sub_b):
                sub_matches = _elements_matching(_SLOT_KEYWORDS.get(sub_slot_id, []), elements)
                if sub_matches:
                    found.append(sub_matches[0])
            if not found:
                continue
            any_bound = any(rr.bindings_for_element(self.entries, el["id"]) for el in found)
            self.diagram.set_slot_label(bracket_slot_id, "", state=("bound" if any_bound else "unbound"))

    # ── Interaction ──────────────────────────────────────────────────────────

    def _on_tree_activate(self):
        sel = self.tree.selection()
        if not sel or self.selected_joystick is None:
            return
        element_id = int(sel[0])
        el = next((e for e in self.selected_joystick.get("elements", []) if e["id"] == element_id), None)
        if el:
            self._open_assign_dialog(el)

    def _on_slot_clicked(self, slot_id):
        if self.selected_joystick is None:
            return
        elements = self.selected_joystick.get("elements", [])
        if slot_id in _STICK_PREFIX:
            matches = [e for e in _elements_matching([_STICK_PREFIX[slot_id]], elements)
                       if e.get("elementType") == "Axis"]
            if not matches:
                return
            if len(matches) == 1:
                self._open_assign_dialog(matches[0])
            else:
                self._open_stick_axis_chooser(matches)
            return
        if slot_id in _SHOULDER_GROUPS:
            found = []
            for sub_slot_id in _SHOULDER_GROUPS[slot_id]:
                sub_matches = _elements_matching(_SLOT_KEYWORDS.get(sub_slot_id, []), elements)
                if sub_matches:
                    found.append(sub_matches[0])
            if len(found) == 1:
                self._open_assign_dialog(found[0])
            elif found:
                self._open_shoulder_chooser(found)
            return
        matches = _elements_matching(_SLOT_KEYWORDS.get(slot_id, []), elements,
                                      exact_names=_SLOT_EXACT_NAMES.get(slot_id))
        if matches:
            self._open_assign_dialog(matches[0])

    def _open_stick_axis_chooser(self, elements):
        self._open_element_chooser(elements, t(
            "This stick has more than one axis — exact X/Y order can vary by controller, check "
            "in-game if unsure."))

    def _open_shoulder_chooser(self, elements):
        self._open_element_chooser(elements, t(
            "This side has a bumper and a trigger — the real controller artwork doesn't draw them "
            "separately, so pick which one to manage."))

    def _open_element_chooser(self, elements, message: str):
        win = ui_util.themed_toplevel(self.app, t("Choose One"), size=(300, 150), resizable=False)
        inner = ttk.Frame(win)
        inner.pack(fill="both", expand=True, padx=14, pady=14)
        ttk.Label(inner, text=message, wraplength=260, justify="left",
                  foreground=theme.DIM).pack(anchor="w", pady=(0, 8))
        for el in elements:
            ttk.Button(inner, text=el.get("name") or f'Element {el["id"]}',
                       command=lambda e=el: (win.destroy(), self._open_assign_dialog(e))).pack(
                fill="x", pady=2)

    def _open_assign_dialog(self, element: dict):
        if self.current_xml is None:
            ui_util.warning(self.app, t("Nothing Loaded"),
                             t("No saved bindings loaded for this controller/category yet."))
            return
        win = ui_util.themed_toplevel(
            self.app, t("Bind: {name}", name=element.get("name") or f'Element {element["id"]}'),
            size=(460, 440), min_size=(420, 400), resizable=True)
        inner = ttk.Frame(win)
        inner.pack(fill="both", expand=True, padx=14, pady=14)

        ttk.Label(inner, text=element.get("name") or f'Element {element["id"]}',
                  font=theme.FHEAD, foreground=theme.GOLD).pack(anchor="w")
        ttk.Label(inner, text=t("Type: {type}", type=element.get("elementType", "?")),
                  foreground=theme.DIM).pack(anchor="w", pady=(0, 8))

        ttk.Label(inner, text=t("Currently bound to:")).pack(anchor="w")
        bound_list = tk.Listbox(inner, height=4, background=theme.WIDGET, foreground=theme.TEXT,
                                 selectbackground=theme.SEL_BG, selectforeground=theme.SEL_FG,
                                 font=theme.F, relief="flat")
        bound_list.pack(fill="x", pady=(2, 4))
        bound_entries = rr.bindings_for_element(self.entries, element["id"])

        def _refill_bound():
            bound_list.delete(0, tk.END)
            if not bound_entries:
                bound_list.insert(tk.END, t("(not bound to anything)"))
            for be in bound_entries:
                bound_list.insert(tk.END, self._action_display(be.action_id))

        _refill_bound()

        def _remove_selected():
            sel = bound_list.curselection()
            if not sel or not bound_entries or sel[0] >= len(bound_entries):
                return
            target = bound_entries.pop(sel[0])
            self._apply_xml_edit(rr.unbind(self.current_xml, target))
            _refill_bound()

        ttk.Button(inner, text=t("Remove Selected Binding"), command=_remove_selected).pack(anchor="w")
        ttk.Separator(inner, orient="horizontal").pack(fill="x", pady=10)

        ttk.Label(inner, text=t("Bind another action to this button:")).pack(anchor="w")
        filter_var = tk.StringVar()
        ttk.Entry(inner, textvariable=filter_var, font=theme.F).pack(fill="x", pady=(2, 4))

        list_frame = ttk.Frame(inner)
        list_frame.pack(fill="both", expand=True)
        action_list = tk.Listbox(list_frame, background=theme.WIDGET, foreground=theme.TEXT,
                                  selectbackground=theme.SEL_BG, selectforeground=theme.SEL_FG,
                                  font=theme.F, relief="flat")
        alsb = ttk.Scrollbar(list_frame, orient="vertical", command=action_list.yview)
        action_list.configure(yscrollcommand=alsb.set)
        action_list.pack(side=tk.LEFT, fill="both", expand=True)
        alsb.pack(side=tk.RIGHT, fill="y")

        candidates = [a for a in self.dump["actions"] if a.get("categoryId") == self.selected_category_id]
        filtered = []

        def _refill_actions(*_):
            query = filter_var.get().strip().lower()
            filtered[:] = [a for a in candidates if query in
                           f'{a.get("name", "")} {a.get("descriptiveName", "")}'.lower()]
            action_list.delete(0, tk.END)
            for a in filtered:
                desc = a.get("descriptiveName") or ""
                action_list.insert(tk.END, f'{a.get("name", "")} — {desc} [{a.get("type", "")}]')

        filter_var.trace_add("write", _refill_actions)
        _refill_actions()

        def _bind_selected():
            sel = action_list.curselection()
            if not sel or sel[0] >= len(filtered):
                return
            action = filtered[sel[0]]
            element_type_int = 0 if element.get("elementType") == "Axis" else 1
            self._apply_xml_edit(rr.add_binding(
                self.current_xml, element_identifier_id=element["id"], element_type=element_type_int,
                action_id=action["id"], action_category_id=self.selected_category_id))
            bound_entries[:] = rr.bindings_for_element(self.entries, element["id"])
            _refill_bound()

        btn_row = ttk.Frame(inner)
        btn_row.pack(fill="x", pady=(6, 0))
        ttk.Button(btn_row, text=t("Bind Selected Action"), command=_bind_selected).pack(side=tk.LEFT)
        ttk.Button(btn_row, text=t("Close"), command=win.destroy).pack(side=tk.RIGHT)

    def _apply_xml_edit(self, new_xml: str):
        self.current_xml = new_xml
        self.entries = rr.parse_action_element_maps(self.current_xml)
        self._set_dirty(True)
        self._refresh_tree()
        self._refresh_diagram()

    def _set_dirty(self, dirty: bool):
        self.dirty = dirty
        self.save_btn.configure(state=("normal" if dirty else "disabled"))
        self.discard_btn.configure(state=("normal" if dirty else "disabled"))

    def _on_discard_clicked(self):
        if not ui_util.confirm(self.app, t("Discard Changes?"),
                                t("Reload the real saved bindings and discard everything you've "
                                  "changed here?")):
            return
        self._load_current_map()

    def _on_save_clicked(self):
        if self.current_map is None or self.current_xml is None or self.original_bytes is None:
            return
        if rr.is_game_running():
            ui_util.warning(self.app, t("Close Nuclear Option First"),
                             t("The game is currently running — close it before saving, so its own "
                               "exit-time save doesn't overwrite your changes."))
            return
        if not ui_util.confirm(self.app, t("Save Controller Bindings?"),
                                t("This writes directly to Nuclear Option's real saved keybindings. "
                                  "The current bindings are backed up first, in case anything looks "
                                  "wrong afterward. Continue?")):
            return
        try:
            backup_path = rr.backup_value(self.app.state_path("controller_mapper_backups"),
                                           self.current_map["value_name"], self.original_bytes)
            rr.write_map_xml(self.current_map["value_name"], self.current_xml)
        except Exception as e:
            ui_util.error(self.app, t("Save Failed"), str(e))
            return
        self.original_bytes = rr.read_value_bytes(self.current_map["value_name"])
        self._set_dirty(False)
        self.status_var.set(t("Saved. Backup of the previous bindings: {path}", path=str(backup_path)))


def build(parent, app):
    app._controller_tab = _Tab(parent, app)

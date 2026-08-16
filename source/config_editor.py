"""
Plugin settings (.cfg) editor — a themed popup built from nom_plugin_meta.parse_cfg's parsed
fields. Saving only ever rewrites the "Key = Value" lines the user actually changed; every comment
line (description, "Setting type:", "Default value:", "Acceptable values:") is preserved verbatim.
"""
import tkinter as tk
from tkinter import ttk

import nom_plugin_meta as npm
import theme
import ui_util
from i18n import t


def _strip_comment_prefix(line: str) -> str:
    s = line.strip()
    while s.startswith("#"):
        s = s[1:]
    return s.strip()


def build_form(container, doc: npm.ConfigDoc) -> dict:
    """Builds one row per setting (grouped under section headings) into `container` from a parsed
    ConfigDoc. Returns {(section, key): (kind, tk.Variable)} — `kind` is "bool" or "text", matching
    what `apply_form` expects back. Shared by the popup editor (open_editor) and the standalone
    Config Editor tab (config_editor_tab.py) so both render settings identically."""
    widgets = {}

    for section in doc.section_order:
        entries = doc.sections[section]
        if not entries:
            continue
        ttk.Label(container, text=section, font=theme.FHEAD, foreground=theme.GOLD).pack(
            anchor="w", padx=8, pady=(12, 2))
        ttk.Separator(container, orient="horizontal").pack(fill="x", padx=8, pady=(0, 6))

        for key, entry in entries.items():
            row = ttk.Frame(container)
            row.pack(fill="x", padx=8, pady=3)

            label_text = key
            desc = " ".join(_strip_comment_prefix(l) for l in entry.comment_lines
                             if _strip_comment_prefix(l) and not _strip_comment_prefix(l).lower().startswith(
                                 ("setting type:", "default value:", "acceptable values:")))

            lbl = ttk.Label(row, text=label_text, width=24, anchor="w")
            lbl.pack(side=tk.LEFT)
            if desc:
                ui_util.tooltip(lbl, desc)

            type_hint = (entry.type_hint or "").strip().lower()

            if type_hint == "boolean":
                var = tk.BooleanVar(value=entry.value.strip().lower() == "true")
                ttk.Checkbutton(row, variable=var).pack(side=tk.LEFT)
                widgets[(section, key)] = ("bool", var)
            elif entry.acceptable_values:
                var = tk.StringVar(value=entry.value)
                cb = ttk.Combobox(row, textvariable=var, values=entry.acceptable_values,
                                   state="readonly", font=theme.F)
                cb.pack(side=tk.LEFT, fill="x", expand=True)
                widgets[(section, key)] = ("text", var)
            else:
                var = tk.StringVar(value=entry.value)
                ttk.Entry(row, textvariable=var, font=theme.F).pack(side=tk.LEFT, fill="x", expand=True)
                widgets[(section, key)] = ("text", var)

    if not widgets:
        ttk.Label(container, text=t("This plugin has no configurable settings."), padding=20).pack()

    return widgets


def apply_form(doc: npm.ConfigDoc, widgets: dict) -> str:
    """Copies each widget's current value back into `doc`, returning the rendered .cfg text —
    does NOT write to disk (caller decides where/whether to save)."""
    for (section, key), (kind, var) in widgets.items():
        entry = doc.sections[section][key]
        if kind == "bool":
            entry.value = "true" if var.get() else "false"
        else:
            entry.value = var.get()
    return npm.render_cfg(doc)


def open_editor(app, cfg_path, meta):
    try:
        original_text = cfg_path.read_text(encoding="utf-8")
    except Exception as e:
        ui_util.error(app, t("Couldn't Open Config"), str(e))
        return

    try:
        doc = npm.parse_cfg(original_text)
    except Exception as e:
        ui_util.error(app, t("Couldn't Parse Config"), str(e))
        return

    win = ui_util.themed_toplevel(app, t("{name} — Settings", name=meta.name),
                                   size=(560, 480), min_size=(420, 320), resizable=True)

    inner = ui_util.make_scrollable(win)
    widgets = build_form(inner, doc)

    btn_bar = ttk.Frame(win)
    btn_bar.pack(side=tk.BOTTOM, fill="x", padx=8, pady=8)

    def _save():
        try:
            cfg_path.write_text(apply_form(doc, widgets), encoding="utf-8")
        except Exception as e:
            ui_util.error(win, t("Couldn't Save Config"), str(e))
            return
        win.destroy()

    ttk.Button(btn_bar, text=t("Cancel"), command=win.destroy).pack(side=tk.RIGHT, padx=(4, 0))
    ttk.Button(btn_bar, text=t("Save"), command=_save).pack(side=tk.RIGHT)

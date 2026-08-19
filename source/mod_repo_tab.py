"""
Search tab — browse and one-click install mods from the community NOMNOM manifest (mod_repo.py),
the same public catalog Combat787's NOMM reads. Lives under MANAGE, after Plugins/Missions/Skins:
this is where a mod comes FROM, those tabs are what you do with it once it's here — installing here
just drops it into the same plugin library folder as everything else, so it shows up in the
Plugins tab automatically (via app.notify_settings_changed()) once installed.

Only "plugin"-type .dll/.zip artifacts are one-click-installable (see mod_repo.py's docstring for
why addon/7z/rar artifacts aren't) — those still show up in the browse list (so search stays
useful for everything in the manifest) but with Install disabled and a note why.
"""
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import ttk

import mod_repo as mr
import theme
import ui_util
from i18n import t


class _Tab:
    def __init__(self, parent, app):
        self.app = app
        self.mods = []
        self.mods_by_id = {}
        self.filtered = []
        self._build_widgets(parent)
        # Deferred via .after(), not called directly: this kicks off a background thread that
        # calls back into Tk via self.app.after(0, ...) once the network fetch completes. Called
        # synchronously here, that background thread can finish (or fail fast, e.g. no network)
        # and try to call back BEFORE the app's own mainloop() has actually started — the rest of
        # the app's tabs are still being built at this point — which trips Tkinter's real
        # "main thread is not in main loop" safety check (confirmed real: reproduced repeatedly,
        # 2026-08-18). Scheduling via .after() instead only starts the thread once mainloop is
        # already pumping events, so the race is structurally impossible.
        self.app.after(0, self.refresh_manifest)

    # ── Widgets ──────────────────────────────────────────────────────────

    def _build_widgets(self, parent):
        top = ttk.Frame(parent)
        top.pack(fill="x", padx=6, pady=(6, 0))
        ttk.Label(top, text=t("Search")).pack(side=tk.LEFT)
        self.search_var = tk.StringVar(value="")
        search_entry = ttk.Entry(top, textvariable=self.search_var, font=theme.F, width=30)
        search_entry.pack(side=tk.LEFT, padx=(4, 6))
        self.search_var.trace_add("write", lambda *_: self._apply_filter())
        ui_util.tooltip(search_entry, t("Matches mod name, tags, and authors."))
        self.refresh_btn = ttk.Button(top, text=t("Refresh Manifest"), command=self.refresh_manifest)
        self.refresh_btn.pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value=t("Loading the community mod manifest…"))
        ttk.Label(parent, textvariable=self.status_var, foreground=theme.DIM).pack(
            side=tk.BOTTOM, fill="x", padx=8, pady=(0, 2))

        body = ttk.PanedWindow(parent, orient="horizontal")
        body.pack(fill="both", expand=True, padx=6, pady=6)

        list_frame = ttk.Frame(body)
        body.add(list_frame, weight=3)
        self.tree = ttk.Treeview(list_frame, columns=("tags", "downloads", "status"),
                                  show="tree headings", selectmode="browse")
        self.tree.heading("#0", text=t("Mod"))
        self.tree.heading("tags", text=t("Tags"))
        self.tree.heading("downloads", text=t("Downloads"))
        self.tree.heading("status", text=t("Status"))
        self.tree.column("#0", width=220)
        self.tree.column("tags", width=140, anchor="w")
        self.tree.column("downloads", width=90, anchor="e", stretch=False)
        self.tree.column("status", width=140, anchor="center", stretch=False)
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side=tk.LEFT, fill="both", expand=True)
        sb.pack(side=tk.RIGHT, fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._update_detail())
        self.tree.tag_configure("installed", foreground=theme.HUD)
        self.tree.tag_configure("update", foreground=theme.GOLD)

        detail_frame = ttk.LabelFrame(body, text=t("Details"))
        body.add(detail_frame, weight=2)

        self.detail_rows_frame = tk.Frame(detail_frame, background=theme.PANEL)
        self.detail_rows_frame.pack(fill="x", anchor="nw", padx=8, pady=8)

        version_row = ttk.Frame(detail_frame)
        version_row.pack(fill="x", padx=8)
        ttk.Label(version_row, text=t("Version")).pack(side=tk.LEFT)
        self.version_var = tk.StringVar(value="")
        self.version_combo = ttk.Combobox(version_row, textvariable=self.version_var, values=[],
                                           state="readonly", width=14, font=theme.F)
        self.version_combo.pack(side=tk.LEFT, padx=(4, 0))

        self.install_btn = ttk.Button(detail_frame, text=t("Install"), command=self._on_install_clicked,
                                       state="disabled")
        self.install_btn.pack(anchor="nw", padx=8, pady=8)

    def _clear_detail_rows(self):
        for child in self.detail_rows_frame.winfo_children():
            child.destroy()

    def _add_detail_row(self, index, text, foreground=None):
        tk.Label(
            self.detail_rows_frame, text=text, background=ui_util.row_bg(index, theme.PANEL),
            foreground=foreground or theme.TEXT, font=theme.F, anchor="w", justify="left",
            wraplength=280, padx=6, pady=3,
        ).pack(fill="x")

    def _add_link_row(self, index, text, url):
        """Same as _add_detail_row, but click-to-open in the default browser — used for a mod's
        own info/GitHub/Discord links when it has nothing installable here, so there's still a
        real way to go get it manually."""
        lbl = tk.Label(
            self.detail_rows_frame, text=text, background=ui_util.row_bg(index, theme.PANEL),
            foreground=theme.GOLD, font=theme.F, anchor="w", justify="left",
            wraplength=280, padx=6, pady=3, cursor="hand2",
        )
        lbl.pack(fill="x")
        lbl.bind("<Button-1>", lambda e, u=url: self._open_link(u))

    def _open_link(self, url):
        webbrowser.open(url)

    # ── Manifest fetch ───────────────────────────────────────────────────

    def refresh_manifest(self):
        self.refresh_btn.configure(state="disabled")
        self.status_var.set(t("Fetching the community mod manifest…"))

        def worker():
            mods = mr.fetch_manifest()
            self.app.after(0, lambda: self._on_manifest_fetched(mods))
        threading.Thread(target=worker, daemon=True).start()

    def _on_manifest_fetched(self, mods):
        self.refresh_btn.configure(state="normal")
        self.mods = mods
        self.mods_by_id = {m.id: m for m in mods}
        if not mods:
            self.status_var.set(t(
                "Couldn't fetch the community mod manifest ({url}) — check your internet "
                "connection and try again.", url=mr.MANIFEST_URL))
        else:
            self.status_var.set(t("{n} mod(s) in the community manifest.", n=len(mods)))
        self._apply_filter()

    # ── List / filter ────────────────────────────────────────────────────

    def _library(self) -> Path:
        return Path(self.app._settings.get("plugin_library", ""))

    def _apply_filter(self):
        query = self.search_var.get().strip().lower()
        if not query:
            self.filtered = list(self.mods)
        else:
            self.filtered = [
                m for m in self.mods
                if query in m.display_name.lower()
                or query in " ".join(m.tags).lower()
                or query in " ".join(m.authors).lower()
            ]
        self._redraw_list()

    def _redraw_list(self):
        sel = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        installed = mr.installed_versions(self._library())
        for mod in sorted(self.filtered, key=lambda m: m.display_name.lower()):
            latest = mr.latest_artifact(mod)
            installed_version = installed.get(mod.id)
            tags = ", ".join(mod.tags[:3])
            downloads = str(mod.download_count) if mod.download_count is not None else ""
            if installed_version is None:
                status, tag = "", ()
            elif latest and mr.is_newer(installed_version, latest.version):
                status, tag = t("Update: {v}", v=latest.version), ("update",)
            else:
                status, tag = t("Installed {v}", v=installed_version), ("installed",)
            self.tree.insert("", tk.END, iid=mod.id, text=mod.display_name,
                              values=(tags, downloads, status), tags=tag)
        for iid in sel:
            if self.tree.exists(iid):
                self.tree.selection_set(iid)
        self._update_detail()

    def _selected_mod(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return self.mods_by_id.get(sel[0])

    # ── Detail / install ─────────────────────────────────────────────────

    def _update_detail(self):
        self._clear_detail_rows()
        mod = self._selected_mod()
        if mod is None:
            self._add_detail_row(0, t("Select a mod to see details."), foreground=theme.DIM)
            self.version_combo.configure(values=[])
            self.version_var.set("")
            self.install_btn.configure(state="disabled")
            return

        installed_version = mr.installed_versions(self._library()).get(mod.id)
        lines = [
            t("Name: {n}", n=mod.display_name),
            t("Author(s): {a}", a=", ".join(mod.authors) or t("(unknown)")),
            t("Tags: {t}", t=", ".join(mod.tags) or t("(none)")),
            t("Downloads: {d}", d=mod.download_count if mod.download_count is not None else t("(unknown)")),
            t("Installed: {v}", v=installed_version) if installed_version else t("Installed: No"),
            mod.description or t("(no description)"),
        ]
        for i, line in enumerate(lines):
            self._add_detail_row(i, line)

        installable_versions = sorted(
            {a.version for a in mod.artifacts if a.installable},
            key=mr.version_key, reverse=True)
        self.version_combo.configure(values=installable_versions)
        if installable_versions and self.version_var.get() not in installable_versions:
            self.version_var.set(installable_versions[0])
        elif not installable_versions:
            self.version_var.set("")

        if not installable_versions:
            row_index = len(lines)
            self._add_detail_row(row_index, t(
                "No installable artifact for this mod (only .dll/.zip \"plugin\"-type artifacts "
                "can be installed here). Get it manually from the link(s) below:"),
                foreground=theme.DIM)
            row_index += 1
            if mod.urls:
                for url_ref in mod.urls:
                    name = url_ref.get("name") or t("Link")
                    url = url_ref.get("url")
                    if url:
                        self._add_link_row(row_index, f"{name}: {url}", url)
                        row_index += 1
            else:
                self._add_detail_row(row_index, t("(no link provided in the manifest)"),
                                      foreground=theme.DIM)
            self.install_btn.configure(state="disabled")
        else:
            self.install_btn.configure(
                state="normal",
                text=t("Update") if installed_version else t("Install"))

    def _selected_artifact(self, mod):
        version = self.version_var.get()
        for a in mod.artifacts:
            if a.version == version and a.installable:
                return a
        return mr.latest_installable_artifact(mod)

    def _on_install_clicked(self):
        mod = self._selected_mod()
        if mod is None:
            return
        artifact = self._selected_artifact(mod)
        if artifact is None:
            return
        library = self._library()
        if not library.is_dir():
            ui_util.warning(self.app, t("No Library Folder"),
                             t("Set a plugin library folder in Config first."))
            return

        dep_note = ""
        if artifact.dependencies:
            dep_names = [self.mods_by_id[d.id].display_name if d.id in self.mods_by_id else d.id
                         for d in artifact.dependencies]
            dep_note = t(" This will also install its dependencies: {deps}.",
                         deps=", ".join(dep_names))
        ok = ui_util.confirm(
            self.app, t("Install Mod?"),
            t("This will download \"{name}\" v{version} ({file}) from its own GitHub releases "
              "and add it to your plugin library, disabled by default.{dep_note}",
              name=mod.display_name, version=artifact.version, file=artifact.file_name,
              dep_note=dep_note))
        if not ok:
            return

        self.install_btn.configure(state="disabled")
        self.status_var.set(t("Installing \"{name}\"…", name=mod.display_name))

        def progress_cb(display_name, read, total):
            if total:
                pct = int(read * 100 / total)
                self.app.after(0, lambda: self.status_var.set(
                    t("Downloading \"{name}\"… {pct}%", name=display_name, pct=pct)))

        def worker():
            try:
                installed = mr.install(self.mods_by_id, library, mod, artifact,
                                        bepinex_plugins_dir=self.app.bepinex_plugins_dir(),
                                        progress_cb=progress_cb)
            except (mr.InstallError, Exception) as e:
                # Capture the message NOW — `e` is deleted by Python at the end of this except
                # block, but app.after(0, ...) defers the lambda until later, so closing over `e`
                # itself (instead of str(e) evaluated here) would raise NameError when it finally runs.
                message = str(e)
                self.app.after(0, lambda: self._on_install_failed(message))
                return
            self.app.after(0, lambda: self._on_install_succeeded(mod, installed))

        threading.Thread(target=worker, daemon=True).start()

    def _on_install_failed(self, message):
        self.install_btn.configure(state="normal")
        self.status_var.set(t("Install failed."))
        ui_util.error(self.app, t("Install Failed"), message)

    def _on_install_succeeded(self, mod, installed_ids):
        self.app.notify_settings_changed()
        self.status_var.set(t(
            "Installed {n} mod(s): {names}. Enable in the Plugins tab and click Apply (Deploy).",
            n=len(installed_ids), names=", ".join(installed_ids)))
        self._redraw_list()


def build(parent, app):
    app._mod_repo_tab = _Tab(parent, app)

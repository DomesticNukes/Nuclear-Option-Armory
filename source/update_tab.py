"""
Updates tab (under CONFIG, alongside Config) — checks GitHub Releases for a newer Nuclear Option
Armory than the running one and, when running the packaged exe, can download and apply it in
place. Split out from the Credits tab into its own sub-tab so it isn't buried in the About block.

Requires the repo to actually publish a GitHub Release (tag `vX.Y.Z`, see
.github/workflows/build.yml's "release" job, which only runs on a version-tag push, not on every
commit) — "no release published yet" is a normal, expected outcome here, not an error. See
self_update.py for the actual check/download/self-replace logic.
"""
import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import self_update as su
import theme
import ui_util
from app_version import APP_VERSION
from i18n import t


def build(parent, app):
    body = ttk.Frame(parent)
    body.pack(fill="both", expand=True, padx=6, pady=6)

    panel = ttk.LabelFrame(body, text=t("Check for Updates"))
    panel.pack(fill="x", padx=2, pady=(0, 12))

    ttk.Label(panel, text=t("Current version: {v}", v=APP_VERSION), font=theme.FB).pack(
        anchor="w", padx=8, pady=(8, 4))

    # Manual only — no automatic network call at startup; see module docstring for why "no
    # release published yet" is a normal outcome, not an error.
    update_status_var = tk.StringVar(value=t(
        "Click \"Check for Updates\" to check GitHub for a newer version."))
    ttk.Label(panel, textvariable=update_status_var, wraplength=560, justify="left").pack(
        anchor="w", padx=8, pady=(0, 2))
    update_progress_var = tk.StringVar(value="")
    ttk.Label(panel, textvariable=update_progress_var, foreground=theme.DIM).pack(
        anchor="w", padx=8)

    update_row = ttk.Frame(panel)
    update_row.pack(fill="x", padx=8, pady=(4, 8))
    check_btn = ttk.Button(update_row, text=t("Check for Updates"))
    check_btn.pack(side=tk.LEFT)
    install_btn = ttk.Button(update_row, text=t("Download & Install Update"), state="disabled")
    install_btn.pack(side=tk.LEFT, padx=(6, 0))

    _state = {"release": None}

    def _on_check_clicked():
        check_btn.configure(state="disabled")
        install_btn.configure(state="disabled")
        update_status_var.set(t("Checking…"))

        def worker():
            release = su.find_latest_release()
            app.after(0, lambda: _on_check_finished(release))
        threading.Thread(target=worker, daemon=True).start()

    def _on_check_finished(release):
        check_btn.configure(state="normal")
        _state["release"] = release
        if release is None:
            update_status_var.set(t(
                "Couldn't check for updates — no release has been published yet, or GitHub "
                "couldn't be reached."))
            return
        if not su.is_newer(APP_VERSION, release.version):
            update_status_var.set(t("You're on the latest version ({v}).", v=APP_VERSION))
            return
        base = t("Version {v} is available (you have {cur}).", v=release.version, cur=APP_VERSION)
        if not su.can_self_update():
            update_status_var.set(base + " " + t(
                "Running from source — grab the new version from GitHub instead of updating here."))
        elif not release.asset_url:
            update_status_var.set(base + " " + t("This release has no downloadable exe attached yet."))
        else:
            update_status_var.set(base)
            install_btn.configure(state="normal")

    def _on_install_clicked():
        release = _state["release"]
        if release is None or not release.asset_url:
            return
        size_kb = release.asset_size // 1024
        ok = ui_util.confirm(
            app, t("Install Update?"),
            t("This will download {name} ({size} KB) from github.com/DomesticNukes/"
              "Nuclear-Option-Armory, replace the running app, and restart it. Continue?",
              name=release.asset_name, size=size_kb))
        if not ok:
            return
        install_btn.configure(state="disabled")
        check_btn.configure(state="disabled")
        update_progress_var.set(t("Downloading… 0%"))

        def progress_cb(read, total):
            if total:
                pct = int(read * 100 / total)
                app.after(0, lambda: update_progress_var.set(t("Downloading… {pct}%", pct=pct)))

        def worker():
            try:
                dest = Path(os.environ.get("TEMP", ".")) / "NuclearOptionArmory_update.exe"
                su.download(release, dest, progress_cb=progress_cb)
            except Exception as e:
                # Capture the exception NOW — Python deletes `e` at the end of this except block,
                # but app.after(0, ...) defers the lambda until later, so closing over `e` itself
                # would raise NameError when the deferred callback finally runs.
                message = str(e)
                app.after(0, lambda: _on_download_failed(message))
                return
            app.after(0, lambda: _on_download_finished(dest))
        threading.Thread(target=worker, daemon=True).start()

    def _on_download_failed(message):
        install_btn.configure(state="normal")
        check_btn.configure(state="normal")
        update_progress_var.set("")
        ui_util.error(app, t("Download Failed"), message)

    def _on_download_finished(dest):
        update_progress_var.set(t("Downloaded."))
        ok = ui_util.confirm(
            app, t("Restart Now?"),
            t("The update was downloaded. Restart Nuclear Option Armory now to apply it?"))
        if not ok:
            install_btn.configure(state="normal")
            check_btn.configure(state="normal")
            return
        try:
            su.apply_update(dest)
        except Exception as e:
            ui_util.error(app, t("Update Failed"), str(e))
            install_btn.configure(state="normal")
            check_btn.configure(state="normal")
            return
        app._on_close()

    check_btn.configure(command=_on_check_clicked)
    install_btn.configure(command=_on_install_clicked)

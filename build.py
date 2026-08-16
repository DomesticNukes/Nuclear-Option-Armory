"""
Build a standalone Nuclear Option Armory.exe with PyInstaller, then — if Inno Setup's ISCC.exe
is found on this machine — also build a proper Setup Wizard installer from installer.iss.

Usage:
    pip install pyinstaller
    python build.py

Produces dist/Nuclear Option Armory.exe — a single-file, windowed (no console) build.
lang/ and data/ are bundled alongside the app so i18n.py's data_dir() and unit_stat_catalog.py's
seed-file loader (both of which read from sys._MEIPASS when frozen) find them. settings.json /
plugin_library_state.json are NOT bundled — they're written next to the exe at runtime
(nom_app._LAUNCH_DIR resolves to sys.executable's folder when frozen).

The installer step is optional and never fails the exe build: if Inno Setup isn't installed, this
just prints where to get it (or run `winget install JRSoftware.InnoSetup`) and stops after the exe.
That raw exe is still fully usable on its own — the installer is a nicer on-ramp for people who
don't want to think about where to put a loose .exe, not a requirement to run the app.
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
SOURCE = ROOT / "source"
ENTRY = SOURCE / "nom_app.py"
APP_NAME = "Nuclear Option Armory"
ICON = ROOT / "assets" / "icon.ico"
ISS_SCRIPT = ROOT / "installer.iss"

_ISCC_CANDIDATES = [
    r"C:\Users\{user}\AppData\Local\Programs\Inno Setup 6\ISCC.exe",
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
]


def _find_iscc():
    found = shutil.which("ISCC.exe") or shutil.which("ISCC")
    if found:
        return found
    import os
    for template in _ISCC_CANDIDATES:
        candidate = Path(template.format(user=os.environ.get("USERNAME", "")))
        if candidate.is_file():
            return str(candidate)
    return None


def build_exe():
    import PyInstaller.__main__

    sep = ";" if sys.platform == "win32" else ":"
    args = [
        str(ENTRY),
        "--name", APP_NAME,
        "--onefile",
        "--windowed",
        "--noconfirm",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT),
        "--paths", str(SOURCE),
        "--add-data", f"{SOURCE / 'lang'}{sep}lang",
        "--add-data", f"{SOURCE / 'data'}{sep}data",
    ]
    if ICON.is_file():
        args += ["--icon", str(ICON)]
    PyInstaller.__main__.run(args)


def build_installer():
    iscc = _find_iscc()
    if not iscc:
        print("\nInno Setup not found — skipping the installer build (the exe above still works on "
              "its own). Install it with:\n  winget install JRSoftware.InnoSetup\nthen re-run this "
              "script to also produce a Setup Wizard installer.")
        return
    print(f"\nBuilding installer with {iscc} ...")
    subprocess.run([iscc, str(ISS_SCRIPT)], cwd=str(ROOT), check=True)


def main():
    build_exe()
    build_installer()


if __name__ == "__main__":
    main()

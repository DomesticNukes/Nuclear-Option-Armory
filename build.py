"""
Build a standalone Nuclear Option Mod Manager.exe with PyInstaller.

Usage:
    pip install pyinstaller
    python build.py

Produces dist/Nuclear Option Mod Manager.exe — a single-file, windowed (no console) build.
lang/ is bundled alongside the app so i18n.py's data_dir() (which reads from sys._MEIPASS when
frozen) finds it. settings.json / plugin_library_state.json are NOT bundled — they're written next
to the exe at runtime (nom_app._LAUNCH_DIR resolves to sys.executable's folder when frozen).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
SOURCE = ROOT / "source"
ENTRY = SOURCE / "nom_app.py"
APP_NAME = "Nuclear Option Mod Manager"


def main():
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
    ]
    PyInstaller.__main__.run(args)


if __name__ == "__main__":
    main()

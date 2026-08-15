# Nuclear Option Mod Manager

[![Build](https://github.com/DomesticNukes/Nuclear-Option-Mod-Manager/actions/workflows/build.yml/badge.svg)](https://github.com/DomesticNukes/Nuclear-Option-Mod-Manager/actions/workflows/build.yml)

A Windows app for managing **Nuclear Option** mods — BepInEx plugins (including installing BepInEx
itself), saved missions, and aircraft liveries — plus a Mod Creator that scaffolds and compiles real
plugins for you. A companion tool to the [R.U.S.E. Mod Manager](https://github.com/LittleGroove/RUSE-Mod-Manager),
sharing its dark navy/gold "Field Operations" visual theme (`theme.py` / `ui_util.py`, copied
verbatim) but otherwise an independent project for a different game.

## Download

Grab the latest build from the [Actions tab](https://github.com/DomesticNukes/Nuclear-Option-Mod-Manager/actions/workflows/build.yml) (click the newest green run, scroll to Artifacts) — two options:

- **Setup installer** (recommended if you don't have Python or don't want to think about where to
  put a loose exe) — a normal Windows Setup Wizard: Next, Next, Finish. Installs to your user
  folder (no admin rights needed), adds a Start Menu entry and optional Desktop shortcut, and shows
  up in "Apps & Features" for a proper uninstall later.
- **Portable exe** — a single file, no installation, no shortcuts. Run it from wherever you put it.

## What it does

Tabs are grouped under **SETUP** (game folder + BepInEx install — gates the rest of the app until
both are done), **MANAGE** (Plugins/Missions/Skins), **CREATE** (Mod Creator), and **SETTINGS**
(plugin library folder). A persistent Launch button starts the game from anywhere in the app.

**Setup tab** — BepInEx isn't part of Nuclear Option itself; it's the third-party mod-loading
runtime every plugin needs, normally installed by hand. This tab detects your game folder (or
finds it via Steam) and, if BepInEx is missing, downloads the official release and installs it in
one click. MANAGE and CREATE stay locked until both steps are done.

**Mod Creator tab** — scaffolds a real BepInEx C# plugin project (Empty Plugin / Config Tweak /
Harmony Patch template) and compiles it with the .NET SDK against the game's own assemblies,
dropping a working DLL straight into your plugin library. Give it a description and it'll show up
in the Plugins tab's Details pane once built.

**Plugins tab** — Nuclear Option mods are BepInEx plugin DLLs: dropping one into
`BepInEx\plugins\` enables it, removing it disables it. This tab keeps your DLLs in one library
folder, lets you tick which ones are active, and copies exactly those into the live game with one
button. It reads each plugin's name/GUID/version straight out of the compiled DLL — no need to run
the game first — and can edit a plugin's `.cfg` settings file in a themed form. Unlike a typical
"mod manager," there's no backup/restore: BepInEx plugins are standalone files, not a patch over
the game's own data, so there's nothing to restore.

**Missions tab** — organizes missions saved by the in-game mission editor
(`%USERPROFILE%\AppData\LocalLow\Shockfront\NuclearOption\Missions\`): rename, duplicate, delete
(moved to a `.deleted` holding folder, not permanently removed), reveal in Explorer. It does not
edit mission content.

**Skins tab** — organizes aircraft livery folders. Building the actual Unity asset bundle a skin
needs isn't something this app can do (that requires Unity + Nuclear Option's own mod-project
tooling) — this tab just organizes folders and edits a skin's `meta.json` fields once you've built
one.

**Settings tab** — game folder and plugin library folder, both auto-detected on first launch.

## Running from source

Pure stdlib Tkinter — no runtime dependencies.

```
python source\nom_app.py
```

## Building the exe / installer

```
pip install pyinstaller
python build.py
```

Always produces `dist\Nuclear Option Mod Manager.exe`. If [Inno Setup](https://jrsoftware.org/isinfo.php)
is also installed (`winget install JRSoftware.InnoSetup`), it additionally builds
`dist_installer\Nuclear Option Mod Manager Setup.exe` from `installer.iss`. CI does both automatically.

## Design notes

- The plugin DLL metadata reader works by scanning raw bytes for the `[BepInPlugin(guid, name,
  version)]` attribute's argument blob (ECMA-335 custom-attribute strings are UTF-8, so they're
  directly readable without any .NET metadata library) — confirmed against real community plugins.
- The `.cfg` editor only ever rewrites the one `Key = Value` line you change; every comment line
  (description, type, default, acceptable values) is preserved byte-for-byte.

## Special thanks

The dark navy/gold "Field Operations" theme and the general feel of this app's UI come from
**[LittleGroove](https://github.com/LittleGroove)**'s **[R.U.S.E. Mod Manager](https://github.com/LittleGroove/RUSE-Mod-Manager)**
— `theme.py` and `ui_util.py` are copied from it essentially verbatim. If you mod R.U.S.E., go
check that project out.

## License

MIT.

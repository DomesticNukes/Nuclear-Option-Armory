# Nuclear Option Mod Manager

[![Build](https://github.com/DomesticNukes/Nuclear-Option-Mod-Manager/actions/workflows/build.yml/badge.svg)](https://github.com/DomesticNukes/Nuclear-Option-Mod-Manager/actions/workflows/build.yml)

A Windows app for managing **Nuclear Option** mods — BepInEx plugins, saved missions, and aircraft
liveries — in one place. A companion tool to the [R.U.S.E. Mod Manager](https://github.com/), sharing
its dark navy/gold "Field Operations" visual theme (`theme.py` / `ui_util.py`, copied verbatim) but
otherwise an independent project for a different game.

## What it does

**Plugins tab** (the main one) — Nuclear Option mods are BepInEx plugin DLLs: dropping one into
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

## Building the exe

```
pip install pyinstaller
python build.py
```

## Design notes

- The plugin DLL metadata reader works by scanning raw bytes for the `[BepInPlugin(guid, name,
  version)]` attribute's argument blob (ECMA-335 custom-attribute strings are UTF-8, so they're
  directly readable without any .NET metadata library) — confirmed against real community plugins.
- The `.cfg` editor only ever rewrites the one `Key = Value` line you change; every comment line
  (description, type, default, acceptable values) is preserved byte-for-byte.

## License

MIT.

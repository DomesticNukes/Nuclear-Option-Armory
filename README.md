# Nuclear Option Armory

[![Build](https://github.com/DomesticNukes/Nuclear-Option-Armory/actions/workflows/build.yml/badge.svg)](https://github.com/DomesticNukes/Nuclear-Option-Armory/actions/workflows/build.yml)

A Windows app for managing **Nuclear Option** mods — BepInEx plugins (including installing BepInEx
itself), saved missions, aircraft liveries, and Steam Workshop subscriptions — plus a Mod Creator
that scaffolds and compiles real plugins for you, and a Unit Editor that lets you tweak unit stats
in the live game without hand-writing a plugin. A companion tool to the
[R.U.S.E. Mod Manager](https://github.com/LittleGroove/RUSE-Mod-Manager), sharing its dark
navy/gold "Field Operations" visual theme (`theme.py` / `ui_util.py`, copied nearly verbatim) but
otherwise an independent project for a different game.

## Download

Grab the latest build from the [Actions tab](https://github.com/DomesticNukes/Nuclear-Option-Armory/actions/workflows/build.yml) (click the newest green run, scroll to Artifacts) — two options:

- **Setup installer** (recommended if you don't have Python or don't want to think about where to
  put a loose exe) — a normal Windows Setup Wizard: Next, Next, Finish. Installs to your user
  folder (no admin rights needed), adds a Start Menu entry and optional Desktop shortcut, and shows
  up in "Apps & Features" for a proper uninstall later.
- **Portable exe** — a single file, no installation, no shortcuts. Run it from wherever you put it.

## What it does

Tabs are grouped under **CONFIG** (game folder + BepInEx + Companion Tools install — gates the rest
of the app until the first two are done), **MANAGE** (Plugins/Missions/Skins), **UNIT EDITOR**
(live in-game stat overrides, one sub-tab per unit category plus a shared Queue & Build tab),
**CREATE** (Mod Creator / Live Editor Suite / Config Editor), and **CREDITS** (about + full
attribution). A persistent Launch button, top right, starts the game from anywhere in the app.

### Config tab

BepInEx isn't part of Nuclear Option itself; it's the third-party mod-loading runtime every plugin
needs, normally installed by hand. This tab detects your game folder (or finds it via Steam) and,
if BepInEx is missing, downloads the official release and installs it in one click — MANAGE, UNIT
EDITOR, and CREATE stay locked until it's done. Below that: your plugin library folder (also
auto-detected), and **Companion Tools** — [nikkorap](https://github.com/nikkorap)'s Blueprinter and
BepInEx's own Configuration Manager, installed directly into `BepInEx\plugins\` (not the toggleable
library, since several other mods depend on Blueprinter always being present) with a per-tool
Enable/Disable button that moves the file out to a holding folder without uninstalling it, in case
either ever conflicts with something else you're running.

### Manage tab

**Plugins** — Nuclear Option mods are BepInEx plugin DLLs (loose files or a folder containing one,
loaded recursively at any depth — both work here). This tab keeps your DLLs in one library folder,
lets you tick which ones are active, and copies exactly those into the live game with one button.
It reads each plugin's name/GUID/version straight out of the compiled DLL — no need to run the game
first — and can edit a plugin's `.cfg` settings file in a themed form. A plugin already sitting in
`BepInEx\plugins\` from before you started using Armory (dropped in by hand, or by another manager)
gets automatically adopted into your library the next time you open this tab, instead of staying
invisible. You can also export your currently-enabled set as a shareable `.armorypack` and import
one someone else sent you. Unlike a typical "mod manager," there's no backup/restore: BepInEx
plugins are standalone files, not a patch over the game's own data, so there's nothing to restore.

**Missions** — organizes missions saved by the in-game mission editor
(`%USERPROFILE%\AppData\LocalLow\Shockfront\NuclearOption\Missions\`): rename, duplicate, delete
(moved to a `.deleted` holding folder, not permanently removed), reveal in Explorer. It also lists
missions you've **subscribed to on the Steam Workshop**, tagged distinctly from your own — since
those live in Steam's own cache, Rename/Delete are blocked on them (Steam manages that folder and
would just undo the change) but Duplicate makes you an editable local copy under the mission's real
title. It does not edit mission content.

**Skins** — organizes aircraft livery folders the same way: your own locally-built ones alongside
Workshop-subscribed liveries, tagged by source. Building the actual Unity asset bundle a skin needs
isn't something this app can do (that requires Unity + Nuclear Option's own mod-project tooling) —
this tab organizes folders and edits a *local* skin's `meta.json` fields (DisplayName/Faction/
Aircraft); editing is intentionally not offered for subscribed skins, since unlike a mission's plain
JSON, a compiled AssetBundle likely bakes its catalog IDs to that exact folder.

### Unit Editor tab

Lets you override real unit stats — top speed, turning radius, armor tier, capture strength, and
more — on the **live running game**, without writing a line of C# yourself. One sub-tab per
category (Aircraft/Vehicle/Ship/Building/Weapon — "Weapon" covers every standalone munition
including bombs, not just missiles), plus a shared **Queue & Build** tab.

Nuclear Option's unit data is compiled Unity ScriptableObject data whose serialization layout is
stripped from the release build, so this app can't read or write the game's asset files directly
(verified with a real UnityPy test — it fails to deserialize). Instead, queuing an override here
and clicking **Build Override Plugin** (once) generates and compiles a small companion BepInEx
plugin ("Armory Stat Override") that applies your queued overrides to the live game via reflection,
re-checked every few seconds — the same technique every other stat-touching Nuclear Option mod
uses. Changes take effect the next time the affected unit loads, not retroactively on anything
already spawned. Every field listed is a real public field confirmed by decompiling the game's own
`Assembly-CSharp.dll`.

Every category's unit picker shows the real in-game unit name (e.g. "F-4 Phantom (Fighter1)")
rather than the bare internal ID, once that name has been seen — see "Real names and default
values," below. The picker itself ships pre-populated: 126 real unit IDs across all five categories
(`source/data/known_units_seed.json`, scraped from real saved missions) are bundled with the app,
so a fresh install already has full coverage without you having to build a mission touching every
unit type first. A **"Refresh Current Values"** button shows the live value the plugin last saw for
whatever's selected, and the very first live value ever seen for each field is captured permanently
as a **baseline** you can revert to with a per-field reset button — so you always have a way back to
"how the game originally had it," even after tweaking a value repeatedly.

Once you're happy with a set of overrides, **Export as Named Mod…** (on Queue & Build) bakes a
frozen snapshot of the current queue into its own standalone, independently named/GUID'd/versioned
plugin — separate from the shared "Armory Stat Override" dev plugin, so you can share it or keep
iterating without touching what you already exported.

**Real names and default values** — a unit's actual name and its real per-unit stat values are live
ScriptableObject asset data, not anything present in mission files or otherwise derivable
statically — they only become known once you've built + deployed the plugin and run the game at
least once with it enabled, reading off the game's own master roster object (the same one its
Encyclopedia/hangar screens use). Until then, the picker falls back to the bare unit ID and default
readouts show "(unknown — build, deploy, run once)."

### Create tab

**Mod Creator** — scaffolds a real BepInEx C# plugin project (Empty Plugin / Config Tweak / Harmony
Patch template) and compiles it with the .NET SDK against the game's own assemblies, dropping a
working DLL straight into your plugin library. Give it a description and it'll show up in the
Plugins tab's Details pane once built.

**Live Editor Suite** — one-click install/update for two well-known third-party dev tools that run
*inside* the game itself as a Unity overlay: [ManlyMarco](https://github.com/ManlyMarco)'s
RuntimeUnityEditor (a live scene/object inspector + REPL console) and BepInEx's own Configuration
Manager. Armory can't become that overlay — it's an external desktop app — but it removes every
manual step around getting them onto your machine.

**Config Editor** — a standalone, browse-everything panel for every deployed plugin's `.cfg`,
built on the same form renderer as the Plugins tab's one-at-a-time "Edit Config…" popup but scanning
`BepInEx\config` directly, so it picks up every plugin that's ever written a config — including ones
installed outside Armory entirely.

### Credits tab

App version and a full attribution list for every project this app is built on top of or bundles an
installer for — see [Special thanks](#special-thanks) below for the same list.

## Running from source

Pure stdlib Tkinter — no runtime dependencies for the app itself. Compiling any plugin (Mod
Creator, Unit Editor's Build/Export) needs the [.NET SDK](https://dotnet.microsoft.com/download)
installed separately; the app tells you if it can't find `dotnet`.

```
python source\nom_app.py
```

## Building the exe / installer

```
pip install pyinstaller
python build.py
```

Always produces `dist\Nuclear Option Armory.exe`. If [Inno Setup](https://jrsoftware.org/isinfo.php)
is also installed (`winget install JRSoftware.InnoSetup`), it additionally builds
`dist_installer\Nuclear Option Armory Setup.exe` from `installer.iss`. CI does both automatically.

## Design notes

- The plugin DLL metadata reader works by scanning raw bytes for the `[BepInPlugin(guid, name,
  version)]` attribute's argument blob (ECMA-335 custom-attribute strings are UTF-8, so they're
  directly readable without any .NET metadata library) — confirmed against real community plugins.
  A second reader falls back to BepInEx's own standard `.cfg` header comment
  (`## Settings file was created by plugin <Name> v<Version>`) for plugins it can't otherwise
  identify.
- The `.cfg` editor only ever rewrites the one `Key = Value` line you change; every comment line
  (description, type, default, acceptable values) is preserved byte-for-byte.
- Unit stat overrides apply via runtime reflection through a generated companion plugin rather than
  editing the game's compiled asset files, because Unity strips per-class serialization layout
  (TypeTrees) from release builds — confirmed with a real failed UnityPy deserialization attempt,
  not assumed.
- A subscribed Steam Workshop mission or skin is told apart from a plain mod purely by each item's
  own `workshop.json` `TypeHint` field ("Mission" vs. "AircraftLivery") — the real, authoritative
  value Nuclear Option itself writes, not a guess based on file layout.

## Special thanks

- **[Combat787](https://github.com/Combat787)** — [NOMM](https://github.com/Combat787/NOMM)
  (Nuclear Option Mod Manager) was the original dedicated mod manager for this game and the direct
  inspiration for building Armory in the first place. Armory is a separate, independent project and
  doesn't share any of NOMM's code, but the idea started there.
- **[LittleGroove](https://github.com/LittleGroove)** — the dark navy/gold "Field Operations" theme
  and general UI feel of this app come from the
  **[R.U.S.E. Mod Manager](https://github.com/LittleGroove/RUSE-Mod-Manager)**; `theme.py` and
  `ui_util.py` are carried over from it almost verbatim. If you mod R.U.S.E., go check that project
  out.
- **[nikkorap](https://github.com/nikkorap)** — **[Blueprinter](https://github.com/nikkorap/NOBlueprinter-Releases)**,
  the `.nobp` asset-bundle loader several other Nuclear Option mods depend on. Installed directly
  from the Config tab, downloaded from nikkorap's own releases — this app doesn't ship or modify it.
- **[BepInEx team](https://github.com/BepInEx)** — [BepInEx](https://github.com/BepInEx/BepInEx)
  itself, the mod-loading runtime everything else here depends on, and
  [BepInEx.ConfigurationManager](https://github.com/BepInEx/BepInEx.ConfigurationManager), the
  in-game F1 settings screen. Both installed straight from the BepInEx team's own releases.
- **[ManlyMarco](https://github.com/ManlyMarco)** — [RuntimeUnityEditor](https://github.com/ManlyMarco/RuntimeUnityEditor),
  the live in-game inspector bundled as part of the Live Editor Suite.
- **Shockfront** — the developer of Nuclear Option itself. This app only manages mods for it and
  doesn't modify, redistribute, or include any of the game's own files.
- **[Harmony](https://github.com/pardeike/Harmony)** — the runtime-patching library used by the Mod
  Creator's Harmony Patch template and by the generated Armory Stat Override plugin.
- **[PyInstaller](https://pyinstaller.org)** and **[Inno Setup](https://jrsoftware.org/isinfo.php)**
  — used to build this app's own standalone exe and Setup Wizard installer.

## License

MIT.

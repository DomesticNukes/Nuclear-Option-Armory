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

Tabs are grouped under **CONFIG** (Config: game folder + BepInEx + Companion Tools install — gates
the rest of the app until the first two are done; Updates: checks for a newer Armory), **MANAGE**
(Plugins/Plugin Config/Missions/Skins/Search/Controller Mapper), **UNIT EDITOR** (live in-game stat overrides, one
sub-tab per unit category plus a shared Queue & Build tab), **CREATE** (Mod Creator / Live Editor
Suite), and **CREDITS** (about + full attribution). A persistent Launch button, top right, starts
the game from anywhere in the app.

### Config tab

**Config** — BepInEx isn't part of Nuclear Option itself; it's the third-party mod-loading runtime
every plugin needs, normally installed by hand. This tab detects your game folder (or finds it via
Steam) and, if BepInEx is missing, downloads the official release and installs it in one click —
MANAGE, UNIT EDITOR, and CREATE stay locked until it's done. Below that: your plugin library folder
(also auto-detected), and **Companion Tools** — [nikkorap](https://github.com/nikkorap)'s
Blueprinter and BepInEx's own Configuration Manager, installed directly into `BepInEx\plugins\`
(not the toggleable library, since several other mods depend on Blueprinter always being present)
with a per-tool Enable/Disable button that moves the file out to a holding folder without
uninstalling it, in case either ever conflicts with something else you're running.

**Updates** — checks GitHub Releases for a newer Armory than the one you're running; when running
the packaged exe, can download and apply the update in place (see
[Design notes](#design-notes)). Manual only, no automatic check on startup.

**Mod Compatibility Checker** — installs [9138noms](https://github.com/9138noms)'s
[DllInspector](https://github.com/9138noms/DllInspector), a standalone tool that statically checks
whether a mod DLL's referenced types/methods/fields/Harmony patches still exist in your currently
installed Nuclear Option, so you can tell which mod actually broke after a game update instead of
guessing. Armory downloads the real release and shells out to it — it isn't bundled or modified.
Generating the snapshot DllInspector checks against only works when your game is installed at
Steam's exact default path (a real limitation of the tool itself, which hardcodes that path for
snapshot generation with no override); this section explains why and disables itself with a clear
message otherwise. Once a snapshot exists, the Plugins tab's **Check Compatibility** button runs it
against any one plugin.

### Manage tab

**Plugins** — Nuclear Option mods are BepInEx plugin DLLs (loose files or a folder containing one,
loaded recursively at any depth — both work here). This tab keeps your DLLs in one library folder,
lets you tick which ones are active, and copies exactly those into the live game with one button.
It reads each plugin's name/GUID/version straight out of the compiled DLL — no need to run the game
first — and can edit a plugin's `.cfg` settings file in a themed form. A plugin already sitting in
`BepInEx\plugins\` from before you started using Armory (dropped in by hand, or by another manager)
gets automatically adopted into your library the next time you open this tab, instead of staying
invisible. If a plugin declares a `[BepInDependency(...)]` on another plugin's GUID, the Details
pane shows whether that dependency is actually present and enabled, warning when a *hard*
dependency is missing (checked against your library AND anything installed directly into
BepInEx/plugins, like a Companion Tool). A **Check Compatibility** button (needs the Mod
Compatibility Checker set up on the Config tab first) runs that plugin's DLL against your current
game version and shows real COMPATIBLE/INCOMPATIBLE verdicts with the specific missing
type/method/field, or a distinct failure status if the checker itself can't process that DLL. You
can also export your currently-enabled set as a shareable `.armorypack` and import one someone else
sent you. Unlike a typical "mod manager,"
there's no backup/restore: BepInEx plugins are standalone files, not a patch over the game's own
data, so there's nothing to restore.

**Plugin Config** — a standalone, browse-everything panel for every deployed plugin's `.cfg`, built
on the same form renderer as the Plugins tab's one-at-a-time "Edit Config…" popup but scanning
`BepInEx\config` directly, so it picks up every plugin that's ever written a config — including
ones installed outside Armory entirely.

**Missions** — organizes missions saved by the in-game mission editor
(`%USERPROFILE%\AppData\LocalLow\Shockfront\NuclearOption\Missions\`): rename, duplicate, delete
(moved to a `.deleted` holding folder, not permanently removed), reveal in Explorer, or import a
mission folder from anywhere else on disk (e.g. one someone shared with you directly). It also
lists missions you've **subscribed to on the Steam Workshop**, tagged distinctly from your own —
since those live in Steam's own cache, Rename/Delete are blocked on them (Steam manages that folder
and would just undo the change) but Duplicate makes you an editable local copy under the mission's
real title. It does not edit mission content.

**Skins** — organizes aircraft livery folders the same way: your own locally-built ones alongside
Workshop-subscribed liveries, tagged by source, with the same folder-import option as Missions.
Building the actual Unity asset bundle a skin needs isn't something this app can do (that requires
Unity + Nuclear Option's own mod-project tooling) — this tab organizes folders and edits a *local*
skin's `meta.json` fields (DisplayName/Faction/Aircraft); editing is intentionally not offered for
subscribed skins, since unlike a mission's plain JSON, a compiled AssetBundle likely bakes its
catalog IDs to that exact folder.

**Search** — browse and one-click install mods from [NOMNOM](https://github.com/KopterBuzz/NOMNOM),
the same public community mod catalog [Combat787](https://github.com/Combat787)'s NOMM reads.
Installing a mod recursively installs its declared dependencies too (skipped if already satisfied —
either a prior Search install, or a real BepInPlugin GUID match elsewhere, like Blueprinter via the
Config tab), with SHA-256 hash verification when the manifest provides one. Only `.dll`/`.zip`
"plugin"-type artifacts install automatically here — Blueprinter "addon" content bundles and
non-zip archives (`.7z`/`.rar`) are shown (so search stays useful for everything in the manifest)
but not auto-installed, since this app hasn't verified where the former needs to land and the
stdlib can't extract the latter. Installed mods show up in the Plugins tab automatically.

**Controller Mapper** — remap a connected gamepad's buttons/axes straight into Nuclear Option's real
saved keybindings, via a clickable diagram (plus a full list of every real button/axis on the
controller, for anything the diagram's fuzzy name-matching doesn't confidently place). The diagram
draws real Xbox/PlayStation controller artwork (auto-detected from the connected controller, or
picked manually via the **Diagram:** setting) with hotspots at real, measured button positions —
bumpers/triggers aren't drawn separately in the source artwork, so those get a "bracket pointer"
marker instead, offering a choice between the bumper and trigger on that side when clicked. The game
uses [Rewired](https://guavaman.com/projects/rewired/) for all input, which stores every binding as
real, readable XML in Windows Registry PlayerPrefs — this tab reads and surgically edits that same
data the game's own Controls menu uses, always backing up the original bytes first and refusing to
write while the game is running. Needs a one-time companion plugin ("Armory Controller Dump") built
from this tab, since the registry only ever stores numeric action/button IDs — the real names come
from Rewired's live runtime API, read once the game's been launched with a controller connected.

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

### Credits tab

App version and a full attribution list for every project this app is built on top of or bundles
an installer for — see
[Special thanks](#special-thanks) below for the same list.

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
- The `[BepInDependency(...)]` scanner uses the same raw-byte technique as the `[BepInPlugin(...)]`
  reader, extended to both of BepInEx's real constructor overloads — verified against actual
  installed plugins on the maintainer's machine (a real hard dependency on Blueprinter, a real soft
  dependency between two other mods) before being trusted, not derived from the spec alone.
- Self-update replaces the running exe by spawning a detached helper script that waits for the file
  to unlock, copies the new build over it, and relaunches — Windows won't allow overwriting an
  exe's file while it's still executing, so the app closing is what releases the lock the helper is
  waiting on.
- DllInspector itself throws an unhandled exception on some real mod DLLs (a Mono.Cecil assembly
  resolution failure, confirmed by running the real tool against real installed plugins) — Armory
  treats any non-zero exit from it as a distinct "check failed" result rather than either crashing
  or silently reporting a false compatibility verdict.
- Rewired stores keybindings as Windows Registry PlayerPrefs, one value per (player, device type,
  action category, hardware) — real, readable UTF-8 XML despite the XML's own header claiming
  `encoding="utf-16"` (confirmed against a real captured value, not assumed from the declaration).
  The Controller Mapper edits it surgically, replacing/splicing around one `<ActionElementMap>`
  block's own exact original substring at a time, never rebuilding or reserializing the rest of the
  file — the same "only touch what changed" discipline the `.cfg` editor uses.
- The companion Controller Dump plugin hand-builds its JSON output instead of using Unity's
  `JsonUtility`: confirmed live that `JsonUtility.ToJson` silently returns an empty `"{}"` for any
  object containing a `List<T>` field on this game's runtime, even a single-item, correctly-wrapped
  list with real data — a plain object with only int/string fields serializes fine via the same call.
- The Controller Mapper's diagrams render real SVG artwork via a small, self-contained parser
  (`svg_path.py`) instead of a graphics library, since Tkinter has no native SVG support — it reads
  `<path>`/`<circle>` elements with `xml.etree.ElementTree` (stdlib) and flattens bezier curves and
  elliptical arcs into straight-line points Canvas can draw directly. The arc math specifically
  matters for correctness, not just polish: both source SVGs draw full circles as four 90-degree
  arcs, and a naive straight-line approximation between each arc's own endpoints draws a diamond, not
  a circle — a real defect this project hit, subtle enough at small on-screen sizes to pass an
  initial visual check, caught only once an automated roundness check was added.

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
- **[9138noms](https://github.com/9138noms)** — [DllInspector](https://github.com/9138noms/DllInspector),
  the mod-DLL compatibility checker installed from the Config tab and run from the Plugins tab.
- **[Guavaman Enterprises](https://guavaman.com/)** — [Rewired](https://guavaman.com/projects/rewired/),
  the input middleware Nuclear Option itself uses for every keybinding, which is what makes the
  Controller Mapper tab possible in the first place — Armory doesn't ship or modify it, just reads
  and edits the real binding data the game's own Rewired instance already saves.
- **everesd_design** — the real Xbox and PlayStation controller vector artwork the Controller Mapper
  renders, from Pixabay: [Controller, Gamepad, Xbox](https://pixabay.com/vectors/controller-gamepad-xbox-video-games-1827840/)
  and [Ps4, Playstation, Controller](https://pixabay.com/vectors/ps4-playstation-controller-to-play-5172918/),
  both under the [Pixabay Content License](https://pixabay.com/service/license-summary/) (free to
  use and modify, attribution not required — credited here anyway, matching this list's own habit).
- **Shockfront** — thank you for making Nuclear Option, and for building it in a way that welcomes
  modding in the first place. None of this app would exist without that.
- **[Harmony](https://github.com/pardeike/Harmony)** — the runtime-patching library used by the Mod
  Creator's Harmony Patch template and by the generated Armory Stat Override plugin.
- **[PyInstaller](https://pyinstaller.org)** and **[Inno Setup](https://jrsoftware.org/isinfo.php)**
  — used to build this app's own standalone exe and Setup Wizard installer.

## License

MIT.

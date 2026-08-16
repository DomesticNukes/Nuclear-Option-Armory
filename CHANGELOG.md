# Changelog

All notable changes to Nuclear Option Armory are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions match the app's own `_APP_VERSION`
constant (shown on the Credits tab).

## [0.6.0] - 2026-08-16

### Added

- **Unit Editor** — an entirely new tab group for overriding real unit stats (top speed, turning
  radius, armor tier, capture strength, and more) on the live running game. One sub-tab per
  category (Aircraft/Vehicle/Ship/Building/Weapon) plus a shared Queue & Build tab. Works by
  generating and compiling a small companion BepInEx plugin ("Armory Stat Override") that applies
  queued overrides via reflection — Nuclear Option's unit data is compiled Unity ScriptableObject
  data that can't be read/written statically (confirmed with a real failed UnityPy deserialization
  test), so this was the only viable approach, the same one every other stat-touching mod uses.
  - Per-field "current value" readout (from the plugin's live dump) and a permanent baseline
    captured the first time each value is ever seen, with a per-field reset-to-baseline button.
  - Live "Pending Changes" preview of everything checked, before you click Add.
  - **Export as Named Mod…** bakes a frozen snapshot of the queue into its own standalone,
    independently named/GUID'd/versioned plugin, separate from the shared dev plugin.
  - A bundled seed file (`source/data/known_units_seed.json`, 126 real unit IDs across all five
    categories, scraped from real saved missions) ships with the app, so the unit picker has full
    coverage on a fresh install with no prerequisite mission-building or live game run.
  - The unit picker shows the real in-game unit name (e.g. "F-4 Phantom (Fighter1)") once a live
    dump has captured it, instead of just the bare internal jsonKey.
- **Live Editor Suite** tab (under CREATE) — one-click install/update for RuntimeUnityEditor
  (ManlyMarco) and BepInEx.ConfigurationManager, the two well-known third-party tools that run
  inside the game itself as a Unity overlay.
- **Config Editor** tab (under CREATE) — a standalone, browse-everything panel for every deployed
  plugin's `.cfg`, scanning `BepInEx\config` directly so it picks up plugins installed outside
  Armory entirely, not just ones in the library.
- **Steam Workshop-subscribed content** — the Missions and Skins tabs now discover items you've
  subscribed to (not just your own local ones), identified by each item's real `workshop.json`
  `TypeHint` field ("Mission" vs. "AircraftLivery") and tagged distinctly in the list. Rename/Delete
  are blocked on subscribed missions (Steam manages that cache); Duplicate makes an editable local
  copy under the mission's real title instead of its numeric Workshop ID. Editing is not offered
  for subscribed skins, since a compiled AssetBundle likely bakes its catalog IDs to that folder.
- **Companion Tools** section on the Config tab — Blueprinter and Configuration Manager now install
  directly into `BepInEx\plugins\` (not the toggleable plugin library, since other mods depend on
  Blueprinter always being present) with a per-tool Enable/Disable button that moves the file to a
  holding folder without uninstalling it.
- **Adopt external plugins** — the Plugins tab now automatically copies any plugin already sitting
  in `BepInEx\plugins\` (dropped in by hand, by another manager, or from before you started using
  Armory) into your library instead of leaving it invisible, defaulting it to enabled since it was
  already active.
- **Modpack export/import** — save your currently-enabled plugin set as a single `.armorypack` file
  to share, or import one someone sent you.
- Folder-structured plugin support — a mod distributed as a folder (not just a loose DLL) is now
  correctly detected and deployed as one unit, matching how BepInEx itself loads plugins.
- A second plugin-identity fallback: parsing BepInEx's own standard `.cfg` header comment
  (`## Settings file was created by plugin <Name> v<Version>`) for plugins whose DLL metadata can't
  otherwise be read.

### Changed

- **Renamed tabs**: SETUP → **CONFIG**, SETTINGS → **CREDITS**. The plugin library folder setting
  moved from Settings/Credits to Config, alongside the rest of the setup checklist. Credits now
  carries a full attribution section for every project this app is built on, in addition to the
  About block.
- Plugins tab Details panel now renders as individually zebra-striped rows (matching the Unit
  Editor's row styling) instead of one flat text block, and both the plugin list and details use a
  larger font.
- The Launch Nuclear Option button's pulse animation now fades between green and gold in HSV space
  (holding saturation constant) instead of a straight RGB blend, which was visibly desaturating at
  the midpoint of the fade.

### Fixed

- A wrong/fabricated Steam App ID on the Credits tab's Shockfront entry, corrected to the real,
  verified ID (`2168680`) already used elsewhere in the app for actual Steam library lookups.
- About a dozen leftover "set one in Settings" messages across several tabs, stale after the
  Setup→Config rename, now correctly say "Config."

## [0.1.0] - 2026-08-15

Initial foundation, built as "Nuclear Option Mod Manager" and renamed to "Nuclear Option Armory"
partway through the same day:

- Plugins tab: enable/disable BepInEx plugin DLLs from a library folder, deploy with one click, read
  name/GUID/version straight from each compiled DLL, edit a plugin's `.cfg` in a themed form.
- Missions tab: rename/duplicate/delete (to a holding folder, not permanently)/reveal saved missions.
- Skins tab: organize aircraft livery folders and edit `meta.json` fields.
- Mod Creator tab: scaffold a real BepInEx C# plugin project (Empty Plugin / Config Tweak / Harmony
  Patch templates) and compile it with the .NET SDK against the game's own assemblies.
- Setup checklist tab: auto-detect the game folder via Steam, one-click BepInEx installer, gating
  Manage/Create until both are done.
- One-click Blueprinter installer.
- A mod description field, from Mod Creator through to the Plugins tab's Details pane.
- A subtle pulse animation on the Launch Nuclear Option button.
- GitHub Actions build workflow, README badge, and a real Inno Setup Setup Wizard installer for
  people without Python installed.
- Adopted the R.U.S.E. Mod Manager's dark navy/gold "Field Operations" theme.

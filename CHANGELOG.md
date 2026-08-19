# Changelog

All notable changes to Nuclear Option Armory are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions match the app's own `APP_VERSION`
constant (`app_version.py`, shown on the Credits tab).

## [0.10.0] - 2026-08-18

### Added

- **Munitions combat stats in the Weapon tab** — Warhead Yield, Pierce Damage, Missile G-Limit, and
  Max Turn Rate are now real, editable fields for every standalone munition (missiles, rockets,
  bombs, guided shells), alongside the existing shared UnitDefinition fields. These live on the
  "Missile" MonoBehaviour attached to each munition's prefab (found via a two-hop reference chain:
  MissileDefinition → its `unitPrefab` → the prefab's Missile component), not on MissileDefinition
  itself. Direct-file-write only — the companion plugin can't reach these (a live spawned Missile
  has no simple per-instance key field to match against), so "Write Directly to Game Files…" is the
  only apply path; a genuine current-value readout is shown instead by reading the field straight
  off the installed game files, so you can see real numbers without ever running the plugin.
  Verified byte-exact against 10 diverse real munitions (small missiles through a tactical nuke),
  including a real live write→verify→restore cycle against the actual installed game file.

### Fixed (found while building the above)

- Extended `unit_asset_layout.py`'s reflected-field reader to correctly handle several real cases
  it hadn't hit yet on the simpler ScriptableObject Definition classes: `double`/`uint` primitives
  (previously misclassified as unsupported nested classes), C# delegate/event fields and any other
  generic type (contribute zero bytes, like `Nullable<T>` already did), `UnityEngine.Quaternion` and
  `UnityEngine.AnimationCurve` (hand-solved real byte layouts, the latter confirmed via a
  calibrated brute-force search against a known field offset), and — the big one — Unity's real
  field-visibility rule for what gets serialized at all (`[NonSerialized]` always wins; short of
  that, public, or private with `[SerializeField]`, or private with only Mirage's `[SyncVar]` still
  counts as serialized on this game's networked MonoBehaviours). The previous reflector silently
  included every public+private field regardless, which happened to be harmless on simple
  ScriptableObjects but broke completely on `Missile`'s deeply-nested, Mirage-networked layout.

## [0.9.0] - 2026-08-17

### Added

- **Direct-to-game-file editing for the Unit Editor** — a second way to apply queued Aircraft/
  Vehicle/Ship/Building/Weapon overrides, alongside the existing companion-plugin path: "Write
  Directly to Game Files…" (Queue & Build tab) patches the values straight into the game's own
  compiled `resources.assets`, in place, with the game closed — no plugin build/deploy/run needed.
  Made possible by reflecting the real field layout out of the game's own `Assembly-CSharp.dll`
  (`reflect_unit_layout.ps1` + `unit_asset_layout.py`): even though Unity strips per-class
  TypeTrees from release builds, that exact layout is still fully recoverable from the compiled
  assembly's own .NET reflection metadata. Every touched object's original bytes are backed up
  first; the game must be closed; only fixed-width numeric fields (float/int/bool/enum) are
  supported this way — string/array/reference fields, and all of AircraftParameters (its scalar
  fields sit behind array element types not yet reflected), still need the companion plugin.
  Verified byte-exact against all 5 real unit categories, and against a real live edit-then-restore
  round trip on the player's own installed game file.
- The Unit Editor's "known units" picker now ALSO scans the player's own installed game files
  directly (`unit_asset_layout.scan_all_unit_keys`, well under a second) as a third source, in
  addition to the bundled seed list and the companion plugin's live dump — so the picker always
  reflects whichever units/weapons are in the currently installed game version, with nothing going
  stale when the game ships new ones in a future update.

## [0.8.1] - 2026-08-17

### Added

- **Controller Mapper now draws real Xbox/PlayStation controller artwork** instead of a generic
  hand-drawn silhouette — a small, stdlib-only SVG parser (`svg_path.py`, no new dependency) renders
  the real vector artwork with real, measured hotspot positions for every button, so a click always
  lands on the real button in the real picture. Which artwork to draw is auto-detected from the real
  connected controller's own reported name, with a **Diagram:** setting (Auto/Xbox/PlayStation/
  Generic, remembered across restarts) to override it.
- Neither source SVG draws separate bumper/trigger (LB/RB/LT/RT) shapes — both are simple front-
  facing icon art with no shoulder-button glyphs. Rather than invent artwork that doesn't exist,
  added two "bracket pointer" marks (like a manual's "see here" leader) at the top-left/top-right,
  each covering both the bumper and trigger on that side; clicking one offers a choice between them.

### Fixed (found live while building the above)

- A real bug in the new SVG parser itself, caught by an automated roundness check after an earlier
  visual check missed it: elliptical arc ("A") path commands were parsed but never actually used —
  the arc handler still fell through to a straight-line approximation. Both source SVGs draw full
  circles (button backgrounds, the Xbox Guide ring) as four 90-degree arcs each, so the un-wired
  version rendered them as diamonds/squares, not circles — subtle enough at small on-screen sizes
  that an earlier visual spot-check didn't catch it, but a real, visible defect. Fixed by actually
  calling the (separately correct, verified in isolation) arc-flattening function from the path
  command dispatcher.

## [0.8.0] - 2026-08-16

### Added

- **Controller Mapper** (under MANAGE) — remap a connected gamepad's buttons/axes straight into
  Nuclear Option's real saved keybindings, via a clickable 2D controller diagram. The game uses
  Rewired for all input (confirmed: `Rewired_Core.dll`/`Rewired_Windows.dll` in
  `NuclearOption_Data/Managed`), which stores every binding as real, readable XML in Windows
  Registry PlayerPrefs — this tab reads and surgically edits that same data the game's own Controls
  menu uses, byte-for-byte preserving everything untouched, always backing up the original bytes
  first, and refusing to write while the game is running. Needs a one-time companion plugin
  ("Armory Controller Dump") to read real action and button names from Rewired's live runtime API,
  since the registry only ever stores numeric IDs.
- A full "every button/axis on this controller" list sits alongside the diagram, covering every
  real physical element even ones the diagram's fuzzy name-matching can't confidently place onto a
  drawn hotspot — so the feature stays fully usable on unfamiliar controllers.

### Fixed (found live while building the above)

- A real Unity `JsonUtility` limitation on this game's runtime: `JsonUtility.ToJson` silently
  returns an empty `"{}"` for any object containing a `List<T>` field, even a single-item,
  correctly-wrapped list with real data — confirmed with a live diagnostic showing genuinely
  populated data (7 categories, 61 actions) still serializing to 2 bytes. The companion plugin's
  dump is hand-built as a JSON string instead, sidestepping `JsonUtility` entirely.
- Two more issues confirmed real but out of scope for this release, flagged for a follow-up fix:
  the Unit Editor's own live-values dump reads from the plugin library folder instead of the
  deployed BepInEx/plugins copy the running game actually writes to, and likely hits this same
  `JsonUtility` limitation.

## [0.7.3] - 2026-08-16

### Added

- **Mod Compatibility Checker**: installs [9138noms](https://github.com/9138noms)'s
  [DllInspector](https://github.com/9138noms/DllInspector) from the Config tab, and a new **Check
  Compatibility** button in the Plugins tab's Details pane runs any one plugin's DLL against your
  current game version, reporting a real COMPATIBLE/INCOMPATIBLE verdict with the specific missing
  type/method/field DllInspector found — not just a pass/fail. Snapshot generation (the step that
  reads your installed game's own code) only works when the game sits at Steam's exact default
  install path, a real hardcoded limitation in DllInspector itself (confirmed by reading its own
  source) rather than anything Armory can route around; the Config tab explains this plainly instead
  of just disabling the button with no reason given.
- DllInspector itself crashes (an unhandled Mono.Cecil exception) on some real mod DLLs — hit on
  10 of 35 real plugins tested. Armory surfaces this as its own distinct "check failed" status with
  the real error message, rather than either crashing itself or silently showing a false
  compatibility verdict.

## [0.7.2] - 2026-08-16

### Fixed

- A real bug found immediately after publishing the first-ever GitHub Release (v0.7.1): GitHub
  replaces spaces with dots in release asset filenames server-side (`Nuclear Option Armory.exe`
  is actually published as `Nuclear.Option.Armory.exe`), so `self_update.py`'s exact-filename
  match never found the portable exe asset on a real release — confirmed by checking the real
  v0.7.1 release via the GitHub API right after publishing it. Now identifies the portable build
  as "whichever `.exe` asset isn't the Setup installer" instead of an exact name, which stays
  correct regardless of exactly how GitHub mangles the rest of the filename.

## [0.7.1] - 2026-08-16

### Added

- **Search tab**: a mod with nothing installable here now shows its real info/Discord/etc. links
  as clickable rows in the Details pane, so there's still a way to go get it manually.
- **Import…** buttons on the Missions and Skins tabs — copy a mission or skin folder from
  anywhere else on disk (e.g. one someone shared with you directly, not via Workshop subscribe)
  into your local library, alongside Rename/Duplicate/Delete.
- **Updates** is now its own sub-tab under CONFIG, next to Config, instead of being folded into
  the Credits tab's About block.
- **Plugin Config** (renamed from Config Editor) moved from CREATE to MANAGE, right next to
  Plugins — it's day-to-day plugin management, not a build tool.

### Fixed

- A real, user-visible bug: `ui_util`'s confirm/info/warning/error dialogs called `t("ui.yes")`,
  `t("ui.no")`, and `t("common.ok")` — a dotted-key style this app's own `i18n.t()` doesn't
  actually use (every other call site passes plain English text, and `lang/us.json` is empty), so
  those buttons literally read "ui.yes" / "ui.no" / "common.ok" instead of "Yes" / "No" / "OK" on
  every themed dialog in the app. Now call `t("Yes")` / `t("No")` / `t("OK")` like everywhere else.

## [0.7.0] - 2026-08-16

Prompted by a re-evaluation of Combat787's NOMM (the mod manager Armory was originally inspired
by) to see what real capabilities it has that Armory was still missing.

### Added

- **Self-updater** — the Credits tab can now check GitHub Releases for a newer Armory version and,
  when running as the packaged exe, download and apply the update in place (a detached helper
  script swaps the file once the app closes, then relaunches it). Requires a real GitHub Release
  to exist — added a `release` job to the build workflow, triggered by pushing a version tag
  (`vX.Y.Z`), that publishes one with both the portable exe and the installer attached; plain
  commits to main still only produce Actions artifacts, not a Release.
- **BepInEx dependency awareness** — the Plugins tab's Details pane now shows each plugin's
  declared `[BepInDependency(...)]` requirements (a real, standard BepInEx attribute plugin authors
  use) and flags a missing or disabled *hard* dependency as a warning; soft dependencies are shown
  informationally only. Also checks whether a dependency is satisfied by something installed
  directly into BepInEx/plugins (e.g. a Companion Tool like Blueprinter) even when it isn't a
  library entry. The underlying byte-level scanner (`nom_plugin_meta.read_plugin_dependencies`)
  was verified against real installed plugins on this machine before being trusted, not guessed
  from the spec alone.
- **Search tab** (under MANAGE) — browse and one-click install mods from the community NOMNOM
  manifest, the same public catalog NOMM itself reads. Recursively installs a mod's declared
  dependencies too (skipping ones already satisfied, either by a prior repo install or by a real
  BepInPlugin GUID match elsewhere, e.g. Blueprinter via the Config tab), with SHA-256 hash
  verification when the manifest provides one. Scope is deliberately narrower than NOMM's own
  installer: only "plugin"-type `.dll`/`.zip` artifacts install automatically — Blueprinter "addon"
  content bundles and non-zip archives (`.7z`/`.rar`) are shown but not auto-installed, since this
  app hasn't verified where the former actually needs to land, and the stdlib can't extract the
  latter.

### Fixed

- A real, pre-existing bug found while building the above: four call sites across three files
  (`credits_tab.py`, `config_tab.py` ×2, `live_editor_tab.py`) deferred an exception object into a
  `tkinter.after(0, ...)` callback via a closure — Python deletes an `except ... as e:` variable at
  the end of its except block, so by the time the deferred callback ran, accessing `e` raised
  `NameError` instead of showing the intended error dialog. All four now capture `str(e)`
  immediately and close over that instead.

## [0.6.1] - 2026-08-16

### Added

- Credited **Combat787** on the Credits tab (and README) for **[NOMM](https://github.com/Combat787/NOMM)**,
  the original Nuclear Option mod manager and the direct inspiration for building Armory.

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

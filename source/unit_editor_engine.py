"""
Unit Editor engine — generates the "Armory Stat Override" companion BepInEx plugin: a small,
generic, JSON-driven reflection plugin that overrides UnitDefinition/AircraftParameters fields on
the LIVE running game, matched by jsonKey/aircraftName. Compiled via mod_creator_engine.build_project
— the same pipeline Mod Creator already uses and has verified compiles cleanly against this game's
real assemblies.

Why THIS is still worth having even though unit_asset_layout.py can now also write game files
directly: this path needs no game restart between edits (values re-read every few seconds off a
running game) and covers AircraftParameters, which direct file writing can't reach yet (see that
module's docstring). Every BepInEx mod this app found already installed on this machine that
touches stats (Munitions Manager, AI Aircraft Limit, Gravity Modifier) uses this same
runtime-reflection technique, not file editing — this generator follows that same proven pattern.

The override VALUES live in a JSON file dropped next to the compiled plugin DLL (read from the
plugin's own assembly directory at runtime, re-read every few seconds so load order never has to
be guessed exactly right) — so day-to-day editing only needs to rewrite that JSON
(write_overrides_json, fast, no recompile), and the DLL itself only needs building once per app
version.
"""
from __future__ import annotations

import json
from pathlib import Path

import mod_creator_engine as mce
import unit_stat_catalog as usc

PLUGIN_ID = "ArmoryStatOverride"
PLUGIN_GUID = "com.armory.statoverride"
PLUGIN_NAME = "Armory Stat Override"
PLUGIN_VERSION = "1.0.0"
OVERRIDES_FILENAME = "armory_stat_overrides.json"
DUMP_FILENAME = "armory_stat_current_values.json"


def _dump_targets() -> list:
    """[(concrete_class, field_name), ...] for every catalogued field the companion plugin can
    actually dump/apply — using the CONCRETE class for each category (AircraftDefinition, not the
    abstract UnitDefinition) — the same tagging unit_editor_tab.py uses when queuing overrides, so a
    dumped "current value" and a queued override always speak the same (type, field) language.
    De-duplicated since several categories share the same UnitDefinition-declared fields under
    different concrete classes. Skips any field whose class has no KEY_FIELD_BY_CLASS entry (e.g.
    Missile — its combat stats live on a prefab-attached MonoBehaviour with no simple per-instance
    key field the live game exposes for reflection matching, unlike jsonKey/aircraftName; those
    fields are direct-file-write-only, see unit_asset_layout.py's Missile/_TWO_HOP_TYPES handling)
    rather than crashing or silently generating broken C# for a class the plugin can't match."""
    targets = []
    seen = set()
    for meta in usc.CATEGORIES.values():
        definition_class = meta["definition_class"]
        for f in meta["fields"]:
            concrete = f.class_name if f.class_name in usc.KEY_FIELD_BY_CLASS else definition_class
            if concrete not in usc.KEY_FIELD_BY_CLASS:
                continue
            key = (concrete, f.field_name)
            if key in seen:
                continue
            seen.add(key)
            targets.append(key)
    return targets


def render_plugin_cs(plugin_guid: str = PLUGIN_GUID, plugin_name: str = PLUGIN_NAME,
                      plugin_version: str = PLUGIN_VERSION) -> str:
    """Generates the companion plugin's C# source. Parametrized so the SAME generic reflection
    logic can be compiled either as the shared dev/test "Armory Stat Override" plugin (build(),
    below — the defaults) or as a distinct, independently-named/versioned mod for export/sharing
    (build_named()) — the only difference between the two is the [BepInPlugin(...)] identity;
    the applier/dumper logic is identical either way."""
    key_field_entries = ",\n            ".join(
        f'{{ "{cls}", "{field}" }}' for cls, field in usc.KEY_FIELD_BY_CLASS.items())
    dump_target_entries = ",\n            ".join(
        f'new DumpTarget {{ type = "{cls}", field = "{field}" }}' for cls, field in _dump_targets())
    return f"""using BepInEx;
using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using UnityEngine;

namespace ArmoryGenerated
{{
    [Serializable]
    public class StatOverrideEntry
    {{
        public string type;
        public string key;
        public string field;
        public string value;
    }}

    [Serializable]
    public class StatOverrideFile
    {{
        public List<StatOverrideEntry> overrides = new List<StatOverrideEntry>();
    }}

    public class DumpTarget
    {{
        public string type;
        public string field;
    }}

    [BepInPlugin("{plugin_guid}", "{plugin_name}", "{plugin_version}")]
    public class Plugin : BaseUnityPlugin
    {{
        private static readonly Dictionary<string, string> KeyFieldByType = new Dictionary<string, string>
        {{
            {key_field_entries}
        }};

        private static readonly DumpTarget[] DumpTargets = new DumpTarget[]
        {{
            {dump_target_entries}
        }};

        private void Awake()
        {{
            Logger.LogInfo("{plugin_name} loaded — re-applying overrides and re-dumping current values every few seconds so load order never matters.");
            StartCoroutine(ApplyLoop());
        }}

        private IEnumerator ApplyLoop()
        {{
            string jsonPath = Path.Combine(
                Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location), "{OVERRIDES_FILENAME}");
            string dumpPath = Path.Combine(
                Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location), "{DUMP_FILENAME}");
            while (true)
            {{
                if (File.Exists(jsonPath))
                {{
                    try
                    {{
                        StatOverrideFile data = JsonUtility.FromJson<StatOverrideFile>(File.ReadAllText(jsonPath));
                        if (data != null && data.overrides != null)
                        {{
                            foreach (StatOverrideEntry entry in data.overrides)
                            {{
                                ApplyOne(entry);
                            }}
                        }}
                    }}
                    catch (Exception e)
                    {{
                        Logger.LogWarning("Stat override apply failed: " + e.Message);
                    }}
                }}

                try
                {{
                    DumpCurrentValues(dumpPath);
                }}
                catch (Exception e)
                {{
                    Logger.LogWarning("Stat dump failed: " + e.Message);
                }}

                yield return new WaitForSeconds(3f);
            }}
        }}

        private void DumpCurrentValues(string dumpPath)
        {{
            List<StatOverrideEntry> results = new List<StatOverrideEntry>();

            // Preferred, guaranteed-COMPLETE source: the game's own master roster object (the
            // same one its Encyclopedia/hangar screens read from), reflected into by name so this
            // still needs no compile-time reference to it. Covers every aircraft/vehicle/missile/
            // building/ship/other-unit in one pass, regardless of what's actually been touched
            // in-game this session — unlike the Resources.FindObjectsOfTypeAll fallback below,
            // which only sees what's been loaded.
            try
            {{
                DumpFromRoster(results);
            }}
            catch (Exception e)
            {{
                Logger.LogWarning("Roster dump failed (falling back to loaded-instances only): " + e.Message);
            }}

            DumpFromLoadedInstances(results);

            StatOverrideFile dumpFile = new StatOverrideFile {{ overrides = results }};
            File.WriteAllText(dumpPath, JsonUtility.ToJson(dumpFile, true));
        }}

        private void DumpFromRoster(List<StatOverrideEntry> results)
        {{
            Type rosterType = AppDomain.CurrentDomain.GetAssemblies()
                .SelectMany(SafeGetTypes)
                .FirstOrDefault(t => t.Name == "Encyclopedia");
            if (rosterType == null)
            {{
                return;
            }}
            PropertyInfo instanceProp = rosterType.GetProperty("i", BindingFlags.Public | BindingFlags.Static);
            object roster = instanceProp?.GetValue(null);
            if (roster == null)
            {{
                return;
            }}

            Dictionary<string, string> rosterListFields = new Dictionary<string, string>
            {{
                {{ "aircraft", "AircraftDefinition" }},
                {{ "vehicles", "VehicleDefinition" }},
                {{ "missiles", "MissileDefinition" }},
                {{ "buildings", "BuildingDefinition" }},
                {{ "ships", "ShipDefinition" }},
                {{ "otherUnits", "UnitDefinition" }},
            }};

            foreach (KeyValuePair<string, string> listField in rosterListFields)
            {{
                FieldInfo field = rosterType.GetField(listField.Key, BindingFlags.Public | BindingFlags.Instance);
                IEnumerable items = field?.GetValue(roster) as IEnumerable;
                if (items == null)
                {{
                    continue;
                }}
                foreach (object item in items)
                {{
                    if (item != null)
                    {{
                        DumpInstanceFields(results, listField.Value, item);
                    }}
                }}
            }}

            // Aircraft flight-performance data (AircraftParameters) is one hop further — each
            // AircraftDefinition references its own via a plain "aircraftParameters" field — so
            // walking it this way is also a definitive fix for the AircraftParameters-key
            // uncertainty flagged elsewhere in this app: it's read directly off the CORRECT
            // linked object, never guessed/matched by assuming aircraftName == jsonKey.
            FieldInfo aircraftListField = rosterType.GetField("aircraft", BindingFlags.Public | BindingFlags.Instance);
            IEnumerable aircraftList = aircraftListField?.GetValue(roster) as IEnumerable;
            if (aircraftList != null)
            {{
                foreach (object aircraftDef in aircraftList)
                {{
                    if (aircraftDef == null)
                    {{
                        continue;
                    }}
                    FieldInfo paramsField = aircraftDef.GetType().GetField(
                        "aircraftParameters", BindingFlags.Public | BindingFlags.Instance);
                    object aircraftParams = paramsField?.GetValue(aircraftDef);
                    if (aircraftParams != null)
                    {{
                        DumpInstanceFields(results, "AircraftParameters", aircraftParams);
                    }}
                }}
            }}
        }}

        private void DumpInstanceFields(List<StatOverrideEntry> results, string typeName, object instance)
        {{
            string keyFieldName;
            if (!KeyFieldByType.TryGetValue(typeName, out keyFieldName))
            {{
                return;
            }}
            Type instanceType = instance.GetType();
            FieldInfo keyField = instanceType.GetField(keyFieldName, BindingFlags.Public | BindingFlags.Instance);
            object keyValue = keyField?.GetValue(instance);
            if (keyValue == null)
            {{
                return;
            }}
            string key = keyValue.ToString();

            foreach (DumpTarget targetSpec in DumpTargets)
            {{
                if (targetSpec.type != typeName)
                {{
                    continue;
                }}
                FieldInfo valueField = instanceType.GetField(targetSpec.field, BindingFlags.Public | BindingFlags.Instance);
                if (valueField == null)
                {{
                    continue;
                }}
                results.Add(new StatOverrideEntry
                {{
                    type = typeName,
                    key = key,
                    field = targetSpec.field,
                    value = FormatValue(valueField.GetValue(instance))
                }});
            }}
        }}

        private void DumpFromLoadedInstances(List<StatOverrideEntry> results)
        {{
            Dictionary<string, Type> typeCache = new Dictionary<string, Type>();
            Dictionary<string, UnityEngine.Object[]> instancesCache = new Dictionary<string, UnityEngine.Object[]>();

            foreach (DumpTarget targetSpec in DumpTargets)
            {{
                string keyFieldName;
                if (!KeyFieldByType.TryGetValue(targetSpec.type, out keyFieldName))
                {{
                    continue;
                }}

                Type targetType;
                if (!typeCache.TryGetValue(targetSpec.type, out targetType))
                {{
                    targetType = AppDomain.CurrentDomain.GetAssemblies()
                        .SelectMany(SafeGetTypes)
                        .FirstOrDefault(t => t.Name == targetSpec.type && typeof(UnityEngine.Object).IsAssignableFrom(t));
                    typeCache[targetSpec.type] = targetType;
                }}
                if (targetType == null)
                {{
                    continue;
                }}

                FieldInfo keyField = targetType.GetField(keyFieldName, BindingFlags.Public | BindingFlags.Instance);
                FieldInfo valueField = targetType.GetField(targetSpec.field, BindingFlags.Public | BindingFlags.Instance);
                if (keyField == null || valueField == null)
                {{
                    continue;
                }}

                UnityEngine.Object[] instances;
                if (!instancesCache.TryGetValue(targetSpec.type, out instances))
                {{
                    instances = Resources.FindObjectsOfTypeAll(targetType);
                    instancesCache[targetSpec.type] = instances;
                }}

                foreach (UnityEngine.Object obj in instances)
                {{
                    object keyValue = keyField.GetValue(obj);
                    if (keyValue == null)
                    {{
                        continue;
                    }}
                    object rawValue = valueField.GetValue(obj);
                    results.Add(new StatOverrideEntry
                    {{
                        type = targetSpec.type,
                        key = keyValue.ToString(),
                        field = targetSpec.field,
                        value = FormatValue(rawValue)
                    }});
                }}
            }}
        }}

        private static string FormatValue(object rawValue)
        {{
            if (rawValue == null)
            {{
                return "";
            }}
            if (rawValue is float f)
            {{
                return f.ToString(CultureInfo.InvariantCulture);
            }}
            if (rawValue is int i)
            {{
                return i.ToString(CultureInfo.InvariantCulture);
            }}
            return rawValue.ToString();
        }}

        private void ApplyOne(StatOverrideEntry entry)
        {{
            if (entry == null || string.IsNullOrEmpty(entry.type) || string.IsNullOrEmpty(entry.field))
            {{
                return;
            }}
            string keyFieldName;
            if (!KeyFieldByType.TryGetValue(entry.type, out keyFieldName))
            {{
                return;
            }}

            Type targetType = AppDomain.CurrentDomain.GetAssemblies()
                .SelectMany(SafeGetTypes)
                .FirstOrDefault(t => t.Name == entry.type && typeof(UnityEngine.Object).IsAssignableFrom(t));
            if (targetType == null)
            {{
                return;
            }}

            FieldInfo keyField = targetType.GetField(keyFieldName, BindingFlags.Public | BindingFlags.Instance);
            FieldInfo valueField = targetType.GetField(entry.field, BindingFlags.Public | BindingFlags.Instance);
            if (keyField == null || valueField == null)
            {{
                return;
            }}

            UnityEngine.Object[] instances = Resources.FindObjectsOfTypeAll(targetType);
            foreach (UnityEngine.Object obj in instances)
            {{
                object keyValue = keyField.GetValue(obj);
                if (keyValue == null || keyValue.ToString() != entry.key)
                {{
                    continue;
                }}
                object converted = ConvertValue(entry.value, valueField.FieldType);
                if (converted != null)
                {{
                    valueField.SetValue(obj, converted);
                }}
            }}
        }}

        private static IEnumerable<Type> SafeGetTypes(Assembly a)
        {{
            try {{ return a.GetTypes(); }}
            catch {{ return new Type[0]; }}
        }}

        private static object ConvertValue(string raw, Type fieldType)
        {{
            try
            {{
                if (fieldType == typeof(float)) return float.Parse(raw, CultureInfo.InvariantCulture);
                if (fieldType == typeof(int)) return int.Parse(raw, CultureInfo.InvariantCulture);
                if (fieldType == typeof(bool)) return raw == "true" || raw == "True" || raw == "1";
                if (fieldType == typeof(string)) return raw;
            }}
            catch {{ }}
            return null;
        }}
    }}
}}
"""


def write_overrides_json(path: Path, entries: list) -> None:
    """`entries` is [{"type": ..., "key": ..., "field": ..., "value": ...}, ...]."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"overrides": entries}, indent=2), encoding="utf-8")


def read_overrides_json(path: Path) -> list:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data.get("overrides", []) if isinstance(data, dict) else []
    except Exception:
        return []


def read_current_values(path: Path) -> dict:
    """{(type, key, field): value_str} from a dump file the companion plugin wrote while the game
    was running — the REAL current value for that unit, not a guessed/class-level default. Missing
    or unreadable file (plugin never built/deployed/run yet) returns an empty dict, never raises."""
    result = {}
    for entry in read_overrides_json(path):
        if not isinstance(entry, dict):
            continue
        t, k, f = entry.get("type"), entry.get("key"), entry.get("field")
        if t and k and f:
            result[(t, k, f)] = entry.get("value", "")
    return result


def build(game_root, project_dir, dotnet_exe: str) -> "mce.BuildResult":
    references = mce.discover_references(Path(game_root))
    csproj = mce.render_csproj(PLUGIN_ID, references)
    return mce.build_project(Path(project_dir), csproj, render_plugin_cs(), PLUGIN_ID, dotnet_exe)


def build_named(game_root, project_dir, dotnet_exe: str, assembly_name: str,
                 plugin_guid: str, plugin_name: str, plugin_version: str) -> "mce.BuildResult":
    """Compiles a STANDALONE, independently-named/versioned copy of the same generic companion
    plugin — for exporting a snapshot of the shared Unit Editor queue as its own shareable mod
    (see unit_editor_state.export_named_mod), distinct from the dev/test "Armory Stat Override"
    plugin build() produces. Same applier/dumper logic either way; only the BepInPlugin identity
    and assembly name differ, so two exported mods (or an export + the dev plugin) can coexist in
    the same BepInEx/plugins folder without colliding."""
    references = mce.discover_references(Path(game_root))
    csproj = mce.render_csproj(assembly_name, references)
    plugin_cs = render_plugin_cs(plugin_guid, plugin_name, plugin_version)
    return mce.build_project(Path(project_dir), csproj, plugin_cs, assembly_name, dotnet_exe)

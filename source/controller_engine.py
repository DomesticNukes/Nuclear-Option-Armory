"""
Controller Mapper engine — generates the "Armory Controller Dump" companion BepInEx plugin: a
small, read-only diagnostic plugin that dumps real Rewired input data (action categories, actions,
and every connected controller's real element names) to JSON every few seconds. Compiled via
mod_creator_engine.build_project, the same pipeline Mod Creator and the Unit Editor already use.

Why this has to come from a live dump instead of a static file: Nuclear Option uses Rewired for
all input (Rewired_Core.dll / Rewired_Windows.dll, confirmed present in NuclearOption_Data/Managed).
Its actual keybindings are real, readable UTF-8 XML stored as Windows Registry PlayerPrefs (see
rewired_registry.py) — but that XML only ever contains numeric actionId / elementIdentifierId
values, never the human-readable names ("Fire Guns", "Right Trigger"). Those names only exist at
runtime, inside Rewired's own ReInput.mapping/ReInput.controllers API — confirmed by reflecting the
real compiled Rewired_Core.dll on this machine (Rewired.ReInput.mapping.Actions, .ActionCategories,
Rewired.ReInput.controllers.Joysticks, Joystick.ElementIdentifiers, Joystick.hardwareName,
Joystick.hardwareTypeGuid — every field/property name below was verified against the real DLL via
.NET reflection, not guessed from Rewired's public docs). So the same "run a tiny companion plugin
once, capture real data" technique the Unit Editor already uses for live unit stats is reused here
for live controller data.

Joystick.hardwareTypeGuid.ToString() is the SAME GUID string format Rewired writes into its own
ControllerMap registry XML as the `hardwareGuid` attribute (lowercase, hyphenated, no braces) — this
is the join key rewired_registry.py uses to match a dumped joystick to its real saved bindings.

Real gotcha found by actually running this against the live game (not assumed, and not simply
"nested lists" as first suspected — isolated with a live A/B diagnostic): on this game's Unity/Mono
runtime, JsonUtility.ToJson silently returns an empty "{}" for ANY object containing a List<T> field,
even a single-item, one-level, correctly-wrapped list — no exception, no partial data. A plain object
with no List<T> field (just int/string fields) serializes perfectly fine via the same call. Confirmed
live: DumpNow's own diagnostic counters showed real non-empty data (categories=7 actions=61
joysticks=1 elements=24) at the exact moment JsonUtility.ToJson(file, true) still produced a literal
2-character "{}". Rather than fight JsonUtility further, the dump is hand-built as a JSON string
below (BuildJson) — fully self-contained, no List<T> ever crosses JsonUtility, so this doesn't depend
on guessing which shape it will or won't accept.
"""
from __future__ import annotations

import json
from pathlib import Path

import mod_creator_engine as mce

PLUGIN_ID = "ArmoryControllerDump"
PLUGIN_GUID = "com.armory.controllerdump"
PLUGIN_NAME = "Armory Controller Dump"
PLUGIN_VERSION = "1.0.0"
DUMP_FILENAME = "armory_controller_dump.json"

_EMPTY_DUMP = {"categories": [], "actions": [], "joysticks": []}


def render_plugin_cs(plugin_guid: str = PLUGIN_GUID, plugin_name: str = PLUGIN_NAME,
                      plugin_version: str = PLUGIN_VERSION) -> str:
    return f"""using BepInEx;
using Rewired;
using System;
using System.Collections;
using System.IO;
using System.Reflection;
using System.Text;
using UnityEngine;

namespace ArmoryGenerated
{{
    [BepInPlugin("{plugin_guid}", "{plugin_name}", "{plugin_version}")]
    public class Plugin : BaseUnityPlugin
    {{
        private void Awake()
        {{
            Logger.LogInfo("{plugin_name} loaded — dumping real Rewired action/controller data every few seconds.");
            StartCoroutine(DumpLoop());
        }}

        private IEnumerator DumpLoop()
        {{
            string dumpPath = Path.Combine(
                Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location), "{DUMP_FILENAME}");
            while (true)
            {{
                try
                {{
                    DumpNow(dumpPath);
                }}
                catch (Exception e)
                {{
                    Logger.LogWarning("Controller dump failed: " + e);
                }}
                yield return new WaitForSeconds(2f);
            }}
        }}

        // Hand-built JSON, not JsonUtility: on this game's Unity/Mono runtime JsonUtility.ToJson
        // silently returns "{{}}" for any object containing a List<T> field, confirmed with a live
        // A/B diagnostic (a plain object with only int/string fields serializes fine; the same
        // fields wrapped in a List do not, even with real, non-empty, single-item data) — so this
        // never hands JsonUtility a List at all.
        private void DumpNow(string dumpPath)
        {{
            StringBuilder sb = new StringBuilder();
            sb.Append("{{");

            sb.Append("\\"categories\\":[");
            if (ReInput.mapping != null)
            {{
                bool first = true;
                foreach (InputCategory cat in ReInput.mapping.ActionCategories)
                {{
                    if (!first) sb.Append(",");
                    first = false;
                    sb.Append("{{\\"id\\":").Append(cat.id)
                      .Append(",\\"name\\":\\"").Append(JsonEscape(cat.name)).Append("\\"")
                      .Append(",\\"descriptiveName\\":\\"").Append(JsonEscape(cat.descriptiveName)).Append("\\"}}");
                }}
            }}
            sb.Append("],");

            sb.Append("\\"actions\\":[");
            if (ReInput.mapping != null)
            {{
                bool first = true;
                foreach (InputAction action in ReInput.mapping.Actions)
                {{
                    if (!first) sb.Append(",");
                    first = false;
                    sb.Append("{{\\"id\\":").Append(action.id)
                      .Append(",\\"name\\":\\"").Append(JsonEscape(action.name)).Append("\\"")
                      .Append(",\\"descriptiveName\\":\\"").Append(JsonEscape(action.descriptiveName)).Append("\\"")
                      .Append(",\\"categoryId\\":").Append(action.categoryId)
                      .Append(",\\"type\\":\\"").Append(JsonEscape(action.type.ToString())).Append("\\"}}");
                }}
            }}
            sb.Append("],");

            sb.Append("\\"joysticks\\":[");
            StringBuilder elementsSb = new StringBuilder();
            bool firstElement = true;
            if (ReInput.controllers != null)
            {{
                bool firstJoystick = true;
                foreach (Joystick joystick in ReInput.controllers.Joysticks)
                {{
                    if (!firstJoystick) sb.Append(",");
                    firstJoystick = false;
                    sb.Append("{{\\"unityId\\":").Append(joystick.unityId)
                      .Append(",\\"name\\":\\"").Append(JsonEscape(joystick.name)).Append("\\"")
                      .Append(",\\"hardwareName\\":\\"").Append(JsonEscape(joystick.hardwareName)).Append("\\"")
                      .Append(",\\"hardwareTypeGuid\\":\\"").Append(JsonEscape(joystick.hardwareTypeGuid.ToString())).Append("\\"")
                      .Append(",\\"isConnected\\":").Append(joystick.isConnected ? "true" : "false").Append("}}");

                    foreach (ControllerElementIdentifier el in joystick.ElementIdentifiers)
                    {{
                        if (!firstElement) elementsSb.Append(",");
                        firstElement = false;
                        elementsSb.Append("{{\\"joystickUnityId\\":").Append(joystick.unityId)
                                  .Append(",\\"id\\":").Append(el.id)
                                  .Append(",\\"name\\":\\"").Append(JsonEscape(el.name)).Append("\\"")
                                  .Append(",\\"positiveName\\":\\"").Append(JsonEscape(el.positiveName)).Append("\\"")
                                  .Append(",\\"negativeName\\":\\"").Append(JsonEscape(el.negativeName)).Append("\\"")
                                  .Append(",\\"elementType\\":\\"").Append(JsonEscape(el.elementType.ToString())).Append("\\"}}");
                    }}
                }}
            }}
            sb.Append("],");

            sb.Append("\\"elements\\":[").Append(elementsSb).Append("]");
            sb.Append("}}");

            File.WriteAllText(dumpPath, sb.ToString());
        }}

        private static string JsonEscape(string s)
        {{
            if (string.IsNullOrEmpty(s)) return "";
            return s.Replace("\\\\", "\\\\\\\\").Replace("\\"", "\\\\\\"")
                     .Replace("\\n", "\\\\n").Replace("\\r", "").Replace("\\t", "\\\\t");
        }}
    }}
}}
"""


def read_dump(path: Path) -> dict:
    """{"categories": [...], "actions": [...], "joysticks": [...]} straight from the companion
    plugin's real dump file — each joystick dict carries an "elements" list, reconstructed here from
    the file's real on-disk FLAT "elements" list (each tagged with its own "joystickUnityId") back
    into a per-joystick grouping, since the on-disk shape has to stay flat (see module docstring:
    JsonUtility silently produces no data at all for a list-of-objects containing another nested
    list). Missing/unreadable/malformed (plugin never built/deployed/run yet, or the game hasn't
    loaded Rewired yet) returns the same empty shape, never raises — callers can always safely index
    ["categories"]/["actions"]/["joysticks"], and each joystick's ["elements"], without checking first."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return dict(_EMPTY_DUMP)
    if not isinstance(data, dict):
        return dict(_EMPTY_DUMP)

    elements_by_joystick = {}
    for el in data.get("elements") or []:
        if isinstance(el, dict):
            elements_by_joystick.setdefault(el.get("joystickUnityId"), []).append(el)

    joysticks = []
    for j in data.get("joysticks") or []:
        if isinstance(j, dict):
            j = dict(j)
            j["elements"] = elements_by_joystick.get(j.get("unityId"), [])
            joysticks.append(j)

    return {
        "categories": data.get("categories") or [],
        "actions": data.get("actions") or [],
        "joysticks": joysticks,
    }


def build(game_root, project_dir, dotnet_exe: str) -> "mce.BuildResult":
    references = mce.discover_references(Path(game_root))
    csproj = mce.render_csproj(PLUGIN_ID, references)
    return mce.build_project(Path(project_dir), csproj, render_plugin_cs(), PLUGIN_ID, dotnet_exe)

"""
Mod Creator engine — pure logic, no Tkinter. Generates a real BepInEx C# plugin project (a .csproj
referencing the game's own assemblies + a Plugin.cs from one of three templates) and compiles it
with the installed .NET SDK (``dotnet build``), producing a working plugin DLL.

Validated this session against the real game install: a project referencing every DLL in
NuclearOption_Data/Managed and BepInEx/core (minus the 3 known-conflicting ones below) compiles a
Harmony patch against a real decompiled gameplay class (Aircraft.Awake) with zero manual tweaking.

Reference-assembly gotchas found and worked around (see EXCLUDED_REFERENCE_DLLS):
  - mscorlib.dll / netstandard.dll — this is a Mono player build that ships its own BCL; referencing
    these alongside the .NET SDK's own netstandard2.1 reference assemblies causes duplicate-type
    conflicts. The SDK's own BCL is used instead — do not reference the game's copies.
  - 0Harmony20.dll — a legacy Harmony 1.x-compat shim BepInEx also ships alongside the real 2.x
    0Harmony.dll; both define ``HarmonyPatch``, so referencing both is ambiguous (CS0433).
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

TARGET_FRAMEWORK = "netstandard2.1"
EXCLUDED_REFERENCE_DLLS = {"mscorlib.dll", "netstandard.dll", "0Harmony20.dll"}

_DOTNET_CANDIDATES = [
    r"C:\Program Files\dotnet\dotnet.exe",
    r"C:\Program Files (x86)\dotnet\dotnet.exe",
]


def find_dotnet_exe() -> Optional[str]:
    found = shutil.which("dotnet")
    if found:
        return found
    for candidate in _DOTNET_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    return None


def discover_references(game_root: Path) -> list:
    """Every compile-time-usable DLL from the game's Managed folder + BepInEx's core folder,
    minus the known-conflicting ones. Order: Managed first, then BepInEx core."""
    managed = Path(game_root) / "NuclearOption_Data" / "Managed"
    core = Path(game_root) / "BepInEx" / "core"
    refs = []
    seen_stems = set()
    for folder in (managed, core):
        if not folder.is_dir():
            continue
        for dll in sorted(folder.glob("*.dll")):
            if dll.name in EXCLUDED_REFERENCE_DLLS:
                continue
            if dll.stem in seen_stems:
                continue
            seen_stems.add(dll.stem)
            refs.append(dll)
    return refs


def sanitize_identifier(text: str, fallback: str = "Mod") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "", text.replace(" ", "_"))
    if not cleaned or cleaned[0].isdigit():
        cleaned = "_" + cleaned
    return cleaned or fallback


def suggest_guid(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]", "", name.lower())
    return f"com.nom.{slug or 'mod'}"


def render_csproj(assembly_name: str, references: list) -> str:
    lines = [
        '<Project Sdk="Microsoft.NET.Sdk">',
        "  <PropertyGroup>",
        f"    <TargetFramework>{TARGET_FRAMEWORK}</TargetFramework>",
        "    <LangVersion>latest</LangVersion>",
        f"    <AssemblyName>{assembly_name}</AssemblyName>",
        "    <Nullable>disable</Nullable>",
        "    <GenerateAssemblyInfo>false</GenerateAssemblyInfo>",
        "  </PropertyGroup>",
        "  <ItemGroup>",
    ]
    for dll in references:
        lines.append(f'    <Reference Include="{dll.stem}">')
        lines.append(f"      <HintPath>{dll}</HintPath>")
        lines.append("      <Private>false</Private>")
        lines.append("    </Reference>")
    lines.append("  </ItemGroup>")
    lines.append("</Project>")
    return "\n".join(lines) + "\n"


# ── Plugin.cs templates ──────────────────────────────────────────────────────

def render_empty_plugin(namespace: str, guid: str, name: str, version: str) -> str:
    return f"""using BepInEx;

namespace {namespace}
{{
    [BepInPlugin("{guid}", "{name}", "{version}")]
    public class Plugin : BaseUnityPlugin
    {{
        private void Awake()
        {{
            Logger.LogInfo("{name} loaded!");
        }}
    }}
}}
"""


_CONFIG_TYPE_MAP = {
    "Boolean": "bool",
    "Single": "float",
    "Int32": "int",
    "String": "string",
}


def _config_default_literal(type_name: str, default: str) -> str:
    if type_name == "Boolean":
        return "true" if default.strip().lower() in ("true", "1", "yes") else "false"
    if type_name == "Single":
        try:
            return f"{float(default)}f"
        except ValueError:
            return "0f"
    if type_name == "Int32":
        try:
            return str(int(default))
        except ValueError:
            return "0"
    escaped = default.replace('"', '\\"')
    return f'"{escaped}"'


def render_config_tweak_plugin(namespace: str, guid: str, name: str, version: str,
                                key: str, type_name: str, default: str, description: str) -> str:
    cs_type = _CONFIG_TYPE_MAP.get(type_name, "string")
    field = sanitize_identifier(key, "Value")
    default_literal = _config_default_literal(type_name, default)
    desc_escaped = description.replace('"', '\\"') or f"{key} setting."
    key_escaped = key.replace('"', '\\"')
    return f"""using BepInEx;
using BepInEx.Configuration;

namespace {namespace}
{{
    [BepInPlugin("{guid}", "{name}", "{version}")]
    public class Plugin : BaseUnityPlugin
    {{
        public static ConfigEntry<{cs_type}> {field}Entry;

        private void Awake()
        {{
            {field}Entry = Config.Bind("General", "{key_escaped}", {default_literal}, "{desc_escaped}");
            Logger.LogInfo("{name} loaded! Edit BepInEx/config/{guid}.cfg to change settings.");
        }}
    }}
}}
"""


def render_harmony_patch_plugin(namespace: str, guid: str, name: str, version: str,
                                 target_class: str, target_method: str, patch_kind: str,
                                 patch_body: str) -> str:
    patch_class_name = sanitize_identifier(f"{target_class}_{target_method}_Patch", "GeneratedPatch")
    body = patch_body.strip() or f'Debug.Log("[{name}] {target_class}.{target_method} was called");'
    return f"""using BepInEx;
using HarmonyLib;
using UnityEngine;

namespace {namespace}
{{
    [BepInPlugin("{guid}", "{name}", "{version}")]
    public class Plugin : BaseUnityPlugin
    {{
        private void Awake()
        {{
            Logger.LogInfo("{name} loaded!");
            new Harmony("{guid}").PatchAll();
        }}
    }}

    [HarmonyPatch(typeof({target_class}), "{target_method}")]
    public static class {patch_class_name}
    {{
        static void {patch_kind}()
        {{
            {body}
        }}
    }}
}}
"""


# ── Build ─────────────────────────────────────────────────────────────────

@dataclass
class BuildResult:
    success: bool
    dll_path: Optional[Path]
    log: str


def build_project(project_dir: Path, csproj_text: str, plugin_cs_text: str, assembly_name: str,
                   dotnet_exe: str) -> BuildResult:
    project_dir = Path(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    csproj_path = project_dir / f"{assembly_name}.csproj"
    csproj_path.write_text(csproj_text, encoding="utf-8")
    (project_dir / "Plugin.cs").write_text(plugin_cs_text, encoding="utf-8")

    try:
        proc = subprocess.run(
            [dotnet_exe, "build", "-c", "Release"],
            cwd=str(project_dir), capture_output=True, text=True, timeout=180,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
    except Exception as e:
        return BuildResult(success=False, dll_path=None, log=f"Failed to run dotnet: {e}")

    log = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        return BuildResult(success=False, dll_path=None, log=log)

    dll_path = project_dir / "bin" / "Release" / TARGET_FRAMEWORK / f"{assembly_name}.dll"
    if not dll_path.is_file():
        return BuildResult(success=False, dll_path=None, log=log + "\n(Build reported success but the output DLL wasn't found.)")
    return BuildResult(success=True, dll_path=dll_path, log=log)

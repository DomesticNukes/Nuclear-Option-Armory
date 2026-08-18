# Reflects Nuclear Option's real Assembly-CSharp.dll to produce a JSON field-layout description for
# the Unit Editor's direct-asset-file read/write path (see unit_asset_layout.py, which consumes this
# output). Walks each root type's full inheritance chain (down to but excluding
# UnityEngine.Object/ScriptableObject) and recursively follows any nested custom value-type/class
# field to its own definition, so the output is self-contained -- no further reflection needed at
# app runtime, just re-run this script after a game update and regenerate the JSON.
#
# Classification per field (this is the part unit_asset_layout.py actually depends on):
#   - "float"/"int"/"bool"/"string": real Unity TypeTree primitive, byte-exact known size.
#   - "pptr": a UnityEngine.Object-derived reference (Sprite/GameObject/ScriptableObject/...) --
#     always exactly 12 bytes (4-byte m_FileID + 8-byte m_PathID on this game's Unity version,
#     confirmed against the real MonoBehaviour head TypeTree), never followed/resolved here.
#   - "enum": a C# enum -- serializes as a plain 4-byte int, real enum names kept for display.
#   - "class": a [Serializable] plain class/struct field -- serialized INLINE (not by reference),
#     its own field list appears elsewhere in the same output keyed by its type name.
#   - "unsupported": anything else (arrays, List<T>, Dictionary, Nullable<T>, non-serializable
#     types) -- flagged explicitly rather than silently guessed at, since Unity's own serializer
#     either skips these fields entirely or needs handling this script doesn't attempt yet.
#
# Usage: powershell -File reflect_unit_layout.ps1 > unit_asset_layout.json

param(
    [string]$DllPath = "C:\Program Files (x86)\Steam\steamapps\common\Nuclear Option\NuclearOption_Data\Managed\Assembly-CSharp.dll",
    [string[]]$RootTypes = @("AircraftDefinition", "AircraftParameters", "VehicleDefinition", "ShipDefinition", "BuildingDefinition", "MissileDefinition")
)

$managedDir = Split-Path $DllPath -Parent
[System.Reflection.Assembly]::LoadFrom((Join-Path $managedDir "UnityEngine.CoreModule.dll")) | Out-Null
$asm = [System.Reflection.Assembly]::LoadFrom($DllPath)
$visited = @{}   # type full name -> $true once processed, avoids infinite recursion / duplicate work
$output = [ordered]@{}

function Classify-Field($fieldType) {
    $fn = $fieldType.FullName
    if ($fieldType.IsGenericType -and $fieldType.GetGenericTypeDefinition().FullName -eq "System.Collections.Generic.List``1") {
        $elemType = $fieldType.GetGenericArguments()[0]
        return @{ kind = "array"; target = $elemType.FullName; elemIsPptr = [UnityEngine.Object].IsAssignableFrom($elemType) }
    }
    if ($fieldType.IsGenericType) { return @{ kind = "unsupported"; reason = "generic ($fn)" } }
    if ($fieldType.IsArray) {
        $elemType = $fieldType.GetElementType()
        return @{ kind = "array"; target = $elemType.FullName; elemIsPptr = [UnityEngine.Object].IsAssignableFrom($elemType) }
    }
    switch ($fn) {
        "System.Single" { return @{ kind = "float"; size = 4 } }
        "System.Int32"  { return @{ kind = "int"; size = 4 } }
        "System.Boolean"{ return @{ kind = "bool"; size = 1 } }
        "System.String" { return @{ kind = "string" } }
    }
    if ($fieldType.IsEnum) {
        return @{ kind = "enum"; size = 4; values = [System.Enum]::GetNames($fieldType) }
    }
    if ([UnityEngine.Object].IsAssignableFrom($fieldType)) {
        return @{ kind = "pptr"; target = $fieldType.Name }
    }
    if ($fieldType.IsClass -or $fieldType.IsValueType) {
        # A custom [Serializable] class/struct -- inline. Queue it for its own reflection pass.
        return @{ kind = "class"; target = $fieldType.FullName }
    }
    return @{ kind = "unsupported"; reason = "unclassified ($fn)" }
}

function Reflect-Type($type) {
    $key = $type.FullName
    if ($visited.ContainsKey($key)) { return }
    $visited[$key] = $true

    $baseName = $null
    if ($type.BaseType -and $type.BaseType.FullName -notin @("UnityEngine.ScriptableObject", "UnityEngine.Object", "System.Object", "System.ValueType")) {
        $baseName = $type.BaseType.FullName
        Reflect-Type $type.BaseType
    }

    $fields = @()
    $flags = [System.Reflection.BindingFlags]::Public -bor [System.Reflection.BindingFlags]::NonPublic -bor [System.Reflection.BindingFlags]::Instance -bor [System.Reflection.BindingFlags]::DeclaredOnly
    foreach ($f in $type.GetFields($flags)) {
        if ($f.Name.Contains("k__BackingField")) { continue }   # auto-property backing fields -- not real serialized data
        $info = Classify-Field $f.FieldType
        $entry = [ordered]@{ name = $f.Name; kind = $info.kind }
        foreach ($k in @("size", "target", "reason", "values", "elemIsPptr")) {
            if ($info.ContainsKey($k)) { $entry[$k] = $info[$k] }
        }
        $fields += $entry
        if ($info.kind -eq "class" -or ($info.kind -eq "array" -and -not $info.elemIsPptr)) {
            $nested = $asm.GetType($info.target)
            if ($nested) { Reflect-Type $nested }
            elseif ($info.kind -eq "array") {
                # element type lives outside Assembly-CSharp.dll (e.g. a UnityEngine/System struct
                # this script can't reflect from here) -- mark unresolvable rather than silently
                # treating the array as skippable with unknown element size.
                $entry.kind = "unsupported"
                $entry.reason = "array element type not found in Assembly-CSharp.dll: $($info.target)"
            }
        }
    }

    $output[$key] = [ordered]@{ base = $baseName; fields = $fields }
}

foreach ($rootName in $RootTypes) {
    $t = $asm.GetType($rootName)
    if (-not $t) { Write-Error "Root type not found: $rootName"; continue }
    Reflect-Type $t
}

$output | ConvertTo-Json -Depth 10

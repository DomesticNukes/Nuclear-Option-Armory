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
        "System.Double" { return @{ kind = "double"; size = 8 } }
        "System.Int32"  { return @{ kind = "int"; size = 4 } }
        "System.UInt32" { return @{ kind = "uint"; size = 4 } }
        "System.Boolean"{ return @{ kind = "bool"; size = 1 } }
        "System.String" { return @{ kind = "string" } }
    }
    if ($fieldType.IsEnum) {
        return @{ kind = "enum"; size = 4; values = [System.Enum]::GetNames($fieldType) }
    }
    if ([UnityEngine.Object].IsAssignableFrom($fieldType)) {
        return @{ kind = "pptr"; target = $fieldType.Name }
    }
    if ([System.Delegate].IsAssignableFrom($fieldType)) {
        # A C# event/delegate field (Action, Action<T>, custom delegate types, ...) -- Unity's
        # serializer never touches these regardless of [Serializable]; confirmed real (Unit's
        # onInitialize/OnRearmUnit are plain System.Action, would otherwise be misclassified as a
        # serializable "class" by the generic catch-all below, since Action IS a class).
        return @{ kind = "unsupported"; reason = "delegate ($fn)" }
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
    $stopBases = @("UnityEngine.ScriptableObject", "UnityEngine.Object", "System.Object", "System.ValueType",
                   "UnityEngine.MonoBehaviour", "UnityEngine.Behaviour", "UnityEngine.Component",
                   "Mirage.NetworkBehaviour", "Mirage.NetworkIdentity")
    if ($type.BaseType -and $type.BaseType.FullName -notin $stopBases) {
        $baseName = $type.BaseType.FullName
        Reflect-Type $type.BaseType
    }

    $fields = @()
    $flags = [System.Reflection.BindingFlags]::Public -bor [System.Reflection.BindingFlags]::NonPublic -bor [System.Reflection.BindingFlags]::Instance -bor [System.Reflection.BindingFlags]::DeclaredOnly
    foreach ($f in $type.GetFields($flags)) {
        if ($f.Name.Contains("k__BackingField")) { continue }   # auto-property backing fields -- not real serialized data
        if ($f.IsStatic -or $f.IsLiteral -or $f.IsInitOnly) { continue }   # static/const/readonly -- never instance data
        if ($f.IsDefined([System.NonSerializedAttribute], $false)) { continue }
        # Unity's ACTUAL serialization rule for THIS game (confirmed real, not assumed -- fixed
        # 2026-08-18 after two rounds of empirical byte-offset validation against a real Missile
        # object): [NonSerialized] is an absolute veto Unity always respects (Unit.unitName etc. are
        # public but [NonSerialized] -- synced over the network via Mirage's SyncVar system instead
        # of Unity's own serializer, contribute zero bytes). Short of that veto, a field is written
        # if it's PUBLIC, or PRIVATE with an explicit [SerializeField], OR carries Mirage's own
        # [SyncVar] attribute -- confirmed empirically real: Missile._targetID is private with only
        # [SyncVar] (no [SerializeField]) and its 4 bytes ARE genuinely present in the real data
        # (proven by every field after it landing exactly on its expected value, incl. an exact
        # match against Missile+Motor.topSpeed's real 299792450f sentinel default, once counted).
        # Mirage's weaver evidently makes SyncVar fields serializable regardless of visibility,
        # unless [NonSerialized] is also present to explicitly opt back out.
        $hasSerializeField = $f.IsDefined([UnityEngine.SerializeField], $false)
        $hasSyncVar = $f.CustomAttributes | Where-Object { $_.AttributeType.FullName -eq "Mirage.SyncVarAttribute" }
        if (-not $f.IsPublic -and -not $hasSerializeField -and -not $hasSyncVar) { continue }
        $info = Classify-Field $f.FieldType
        $entry = [ordered]@{ name = $f.Name; kind = $info.kind }
        foreach ($k in @("size", "target", "reason", "values", "elemIsPptr")) {
            if ($info.ContainsKey($k)) { $entry[$k] = $info[$k] }
        }
        $fields += $entry
        # Vector3/Quaternion live outside Assembly-CSharp.dll (UnityEngine.CoreModule), so
        # $asm.GetType() below can never resolve them -- but unit_asset_layout.py's Python reader
        # hand-special-cases these two exact struct layouts (confirmed real, byte-exact), so they
        # must stay kind="class" with their real target name, not get marked unsupported.
        $handSolvedStructs = @("UnityEngine.Vector3", "UnityEngine.Quaternion", "UnityEngine.AnimationCurve")
        if (($info.kind -eq "class" -or ($info.kind -eq "array" -and -not $info.elemIsPptr)) -and $info.target -notin $handSolvedStructs) {
            $nested = $asm.GetType($info.target)
            if ($nested) { Reflect-Type $nested }
            else {
                # Nested type lives outside Assembly-CSharp.dll (e.g. a UnityEngine/System/Mirage
                # struct this script can't reflect from here) -- mark unresolvable rather than
                # silently claiming kind="class"/"array" with a target that will never be found in
                # the output, which would surface as a much more confusing "no reflected layout for
                # type X" error two steps removed from the real cause. Applies to plain class fields
                # too, not just array elements -- a bug fixed 2026-08-18 after Unit.hit
                # (UnityEngine.RaycastHit) and Unit.HQ (Mirage.NetworkBehaviorSyncvar) silently kept
                # kind="class" and broke the Missile read path two fields later than the real cause.
                $entry.kind = "unsupported"
                $noun = if ($info.kind -eq "array") { "array element" } else { "nested" }
                $entry.reason = "$noun type not found in Assembly-CSharp.dll: $($info.target)"
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

"""
Unit stat catalog — pure data/logic, no Tkinter. The editable field surface for the Unit Editor
tab, plus a scraper that pulls real, already-in-play unit identifiers (jsonKeys) out of the
player's own saved mission JSON files.

Every field listed here is a REAL public field confirmed by decompiling this machine's own
Assembly-CSharp.dll (ilspycmd, 2026-08-15) — UnitDefinition.cs / AircraftParameters.cs and their
subclasses (AircraftDefinition, VehicleDefinition, ShipDefinition, BuildingDefinition,
MissileDefinition all derive from UnitDefinition with no extra primitive fields of their own).
Deliberately excludes: reference-type fields (Sprite/GameObject/AssetReference — editing those
means swapping assets, a different problem), private fields (disabled, isEventContent — harder to
reach safely via reflection), and `mass` (recomputed at runtime via CacheMass(), so an override
would likely just get silently overwritten).

Field values are applied to the LIVE running game via a companion BepInEx plugin
(unit_editor_engine.py) using reflection, matched by UnitDefinition.jsonKey / AircraftParameters
.aircraftName. As of 2026-08-17 there is a SECOND path too (unit_asset_layout.py): direct, no-plugin
-needed, no-game-running-required patching of the game's compiled resources.assets file, for the 5
UnitDefinition subclasses only (not AircraftParameters — its own scalar fields sit behind array
element types this app hasn't reflected yet, see that module's docstring). Field TYPES here
(float/int/bool/string) apply to either path identically; which path a given queued override
actually goes through is a Queue & Build tab choice, not something this catalog needs to know.

min_value/max_value/step below are UI conveniences (slider ranges), NOT limits the game itself
enforces — this app has not verified the game's own safe operating ranges for these fields, so an
extreme value may behave oddly or not at all in-game.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class StatField:
    class_name: str        # the exact C# type name this field lives on
    field_name: str         # the exact C# field name
    field_type: str          # "float" | "int" | "bool" | "string"
    label: str
    tooltip: str = ""
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    step: float = 1.0
    # The field's C# DECLARED default (e.g. `public float cruiseThrottle = 0.9f;`) — set ONLY when
    # the decompiled source actually shows an explicit initializer, never guessed. Most fields have
    # none (declared as just `public float maxSpeed;`), which C# defaults to 0/false — NOT shown
    # here, since 0 isn't a meaningful "default" for something like max speed, it's just "no value
    # was set in code" (the real per-unit number lives in the ScriptableObject asset data, which
    # this app can't statically read — see the module docstring). The genuinely LIVE current value
    # for a specific unit, once known, is a much stronger signal than this and comes from the
    # companion plugin's runtime dump instead (unit_editor_engine.DUMP_FILENAME).
    default_value: Optional[object] = None


# Shared across every unit category — Aircraft/Vehicle/Ship/Building/Missile all derive from
# UnitDefinition with the same base field set (each subclass only adds enum/reference fields).
_UNIT_DEFINITION_FIELDS = [
    StatField("UnitDefinition", "unitName", "string", "Unit Name"),
    StatField("UnitDefinition", "bogeyName", "string", "Bogey Name",
              "Shown for contacts not yet visually identified."),
    StatField("UnitDefinition", "visibleRange", "float", "Visible Range",
              min_value=0, max_value=50000, step=100),
    StatField("UnitDefinition", "iconRange", "float", "Icon Range", min_value=0, max_value=50000, step=100),
    StatField("UnitDefinition", "radarSize", "float", "Radar Cross-Section", min_value=0, max_value=1000, step=1),
    StatField("UnitDefinition", "iconSize", "float", "Icon Size", min_value=0, max_value=10, step=0.1),
    StatField("UnitDefinition", "mapIconSize", "float", "Map Icon Size", min_value=0, max_value=10, step=0.1,
              default_value=1.0),
    StatField("UnitDefinition", "mapOrient", "bool", "Map Icon Orients With Heading"),
    StatField("UnitDefinition", "IsObstacle", "bool", "Is Obstacle", default_value=True),
    StatField("UnitDefinition", "captureCapacity", "int", "Capture Capacity", min_value=0, max_value=100, step=1),
    StatField("UnitDefinition", "captureStrength", "float", "Capture Strength", min_value=0, max_value=100, step=1),
    StatField("UnitDefinition", "captureDefense", "float", "Capture Defense", min_value=0, max_value=100, step=1),
    StatField("UnitDefinition", "value", "float", "Point Value", min_value=0, max_value=1000, step=1),
    StatField("UnitDefinition", "manpower", "float", "Manpower", min_value=0, max_value=100, step=1),
    StatField("UnitDefinition", "armorTier", "float", "Armor Tier", min_value=0, max_value=20, step=1),
    StatField("UnitDefinition", "damageTolerance", "float", "Damage Tolerance",
              min_value=0, max_value=1000, step=10),
    StatField("UnitDefinition", "CanSlingLoad", "bool", "Can Sling-Load"),
]

_AIRCRAFT_PARAMETER_FIELDS = [
    StatField("AircraftParameters", "rankRequired", "int", "Rank Required", min_value=0, max_value=20, step=1),
    StatField("AircraftParameters", "DefaultFuelLevel", "float", "Default Fuel Level (0-1)",
              min_value=0, max_value=1, step=0.05, default_value=1.0),
    StatField("AircraftParameters", "aircraftGLimit", "float", "G Limit", min_value=1, max_value=30, step=0.5,
              default_value=9.0),
    StatField("AircraftParameters", "maxSpeed", "float", "Max Speed (m/s)", min_value=0, max_value=1000, step=5),
    StatField("AircraftParameters", "takeoffSpeed", "float", "Takeoff Speed (m/s)",
              min_value=0, max_value=200, step=1),
    StatField("AircraftParameters", "takeoffDistance", "float", "Takeoff Distance (m)",
              min_value=0, max_value=3000, step=10),
    StatField("AircraftParameters", "verticalLanding", "bool", "Vertical Landing"),
    StatField("AircraftParameters", "turningRadius", "float", "Turning Radius (m)",
              min_value=1, max_value=2000, step=5),
    StatField("AircraftParameters", "cornerSpeed", "float", "Corner Speed (m/s)",
              min_value=0, max_value=500, step=5),
    StatField("AircraftParameters", "approachSpeed", "float", "Approach Speed (m/s)",
              min_value=0, max_value=200, step=1, default_value=60.0),
    StatField("AircraftParameters", "landingSpeed", "float", "Landing Speed (m/s)",
              min_value=0, max_value=200, step=1, default_value=30.0),
    StatField("AircraftParameters", "shortLandingSpeed", "float", "Short Landing Speed (m/s)",
              min_value=0, max_value=200, step=1, default_value=30.0),
    StatField("AircraftParameters", "cruiseThrottle", "float", "Cruise Throttle (0-1)",
              min_value=0, max_value=1, step=0.05, default_value=0.9),
    StatField("AircraftParameters", "minimumRadarAlt", "float", "Minimum Radar Altitude (m)",
              min_value=0, max_value=5000, step=10),
    StatField("AircraftParameters", "hoverTiltFactor", "float", "Hover Tilt Factor",
              min_value=0, max_value=5, step=0.1, default_value=1.0),
    StatField("AircraftParameters", "groundTurningRadius", "float", "Ground Turning Radius (m)",
              min_value=0, max_value=200, step=1, default_value=10.0),
]

# The real combat stats for an individual munition (blast yield, pierce damage, G-limit, turn
# rate) — confirmed real via decompiling Missile.cs and byte-exact validated against 10 diverse
# real munitions (2026-08-18). These live on the "Missile" MonoBehaviour attached to the munition's
# prefab, NOT on MissileDefinition (which only covers the shared UnitDefinition fields above) — a
# different object, found via a two-hop reference chain (see unit_asset_layout.find_missile_component).
# DIRECT-FILE-WRITE ONLY: unlike every other category's extra_classes entry, Missile fields can't go
# through the companion plugin, since a live spawned Missile GameObject has no simple per-instance
# key field (like jsonKey/aircraftName) for runtime reflection matching — see
# unit_editor_engine._dump_targets's own note on why it skips these.
_MISSILE_COMBAT_FIELDS = [
    StatField("Missile", "blastYield", "float", "Warhead Yield (kg TNT-equiv.)",
              "The real 'Yield' stat shown on the wiki — ranges from single digits for a light AAM "
              "warhead to tens of millions for a nuclear payload.", min_value=0, max_value=25000000, step=1),
    StatField("Missile", "pierceDamage", "float", "Pierce Damage", min_value=0, max_value=5000, step=10),
    StatField("Missile", "gLimit", "float", "Missile G-Limit",
              "How many g's the airframe itself can pull — separate from aircraftGLimit, since "
              "missiles routinely pull far more g than any aircraft.", min_value=0, max_value=200, step=1),
    StatField("Missile", "maxTurnRate", "float", "Max Turn Rate (deg/s)", min_value=0, max_value=720, step=5),
]

# category display name -> {definition_class, mission_key, fields}. `mission_key` is the key a
# saved mission JSON uses for that category's unit list — confirmed real for all five, including
# "missiles" (a real top-level mission category for standalone/free-flying munitions like guided
# shells, ARMs, cruise missiles — a mission JSON with these placed directly was inspected
# 2026-08-15 and matches the same {"type": "<jsonKey>", ...} shape as every other category).
CATEGORIES = {
    "Aircraft": {"definition_class": "AircraftDefinition", "mission_key": "aircraft",
                 "fields": _UNIT_DEFINITION_FIELDS + _AIRCRAFT_PARAMETER_FIELDS,
                 "extra_classes": ["AircraftParameters"]},
    "Vehicle": {"definition_class": "VehicleDefinition", "mission_key": "vehicles",
                "fields": list(_UNIT_DEFINITION_FIELDS), "extra_classes": []},
    "Ship": {"definition_class": "ShipDefinition", "mission_key": "ships",
             "fields": list(_UNIT_DEFINITION_FIELDS), "extra_classes": []},
    "Building": {"definition_class": "BuildingDefinition", "mission_key": "buildings",
                 "fields": list(_UNIT_DEFINITION_FIELDS), "extra_classes": []},
    # Labelled "Weapon" rather than "Missile" — the game's own MissileDefinition class (confirmed
    # via a real comprehensive mission, 2026-08-15) covers every standalone munition: guided
    # missiles, rockets, gun shells, AND bombs (bomb500, nuclearBomb1, ...), not just missiles.
    "Weapon": {"definition_class": "MissileDefinition", "mission_key": "missiles",
               "fields": _UNIT_DEFINITION_FIELDS + _MISSILE_COMBAT_FIELDS, "extra_classes": ["Missile"]},
}

# Which field, on which class, identifies a live instance of that class at runtime — must match
# unit_editor_engine.py's generated C# KeyFieldByType table exactly (kept in sync by hand; both
# are small, fixed facts about the real game, not runtime-configurable data).
KEY_FIELD_BY_CLASS = {
    "AircraftDefinition": "jsonKey",
    "VehicleDefinition": "jsonKey",
    "ShipDefinition": "jsonKey",
    "BuildingDefinition": "jsonKey",
    "MissileDefinition": "jsonKey",
    "AircraftParameters": "aircraftName",
}


def fields_for_class(class_name: str) -> list:
    """Every StatField that applies to `class_name` specifically (not the whole category —
    e.g. "AircraftParameters" alone, separate from "AircraftDefinition")."""
    seen = {}
    for meta in CATEGORIES.values():
        for f in meta["fields"]:
            seen[(f.class_name, f.field_name)] = f
    return [f for f in seen.values() if f.class_name == class_name]


_seed_cache: Optional[dict] = None


def _seed_data_dir() -> Path:
    """``data/`` directory: packaged beside the exe (PyInstaller ``_MEIPASS``, see build.py's
    --add-data) or this source file's own folder when running unfrozen."""
    base = getattr(sys, "_MEIPASS", None) or Path(__file__).parent
    return Path(base) / "data"


def seed_unit_keys() -> dict:
    """{category: [jsonKey, ...]} from the bundled data/known_units_seed.json — 126 real unit
    identifiers scraped straight from actual saved mission JSON (never fabricated/guessed; see
    that file's own "_provenance" note), shipped with the app so a fresh install's Unit Editor
    picker already has full category coverage without requiring the same mission-building or
    live-game-run legwork the maintainer went through to discover them. Cached after first read;
    returns {name: [] for name in CATEGORIES} if the file is missing or unreadable, never raises."""
    global _seed_cache
    if _seed_cache is None:
        try:
            raw = json.loads((_seed_data_dir() / "known_units_seed.json").read_text(encoding="utf-8"))
            _seed_cache = {name: sorted(raw.get(name, []) or []) for name in CATEGORIES}
        except Exception:
            _seed_cache = {name: [] for name in CATEGORIES}
    return _seed_cache


_wiki_reference_cache: Optional[dict] = None


def wiki_reference(category: str, key: str) -> Optional[dict]:
    """Community-wiki reference stats for one specific unit (currently Aircraft only — see
    data/aircraft_wiki_reference.json's own "_provenance" note), keyed by jsonKey. This is
    EXTERNAL, unverified-against-the-binary data — the caller must always label it distinctly
    (e.g. "wiki: ...") and never treat it as equivalent to a real captured live value or a
    declared C# default. None if this category has no wiki file, or this key isn't in it."""
    global _wiki_reference_cache
    if _wiki_reference_cache is None:
        _wiki_reference_cache = {}
        try:
            path = _seed_data_dir() / "aircraft_wiki_reference.json"
            raw = json.loads(path.read_text(encoding="utf-8"))
            _wiki_reference_cache["Aircraft"] = {k: v for k, v in raw.items() if not k.startswith("_")}
        except Exception:
            pass
    return _wiki_reference_cache.get(category, {}).get(key)


def known_unit_keys(missions_dir: Path) -> dict:
    """{category: sorted [jsonKey, ...]} — the bundled seed list (see seed_unit_keys()) UNIONED
    with whatever's scraped from every mission JSON under `missions_dir`: real unit identifiers
    already used in this player's own saved missions (all five categories, including Missile —
    standalone munitions ARE directly placeable in the mission editor). The seed is a floor, not a
    replacement — anything found locally that isn't in the seed (e.g. a modded/custom unit) still
    shows up too. Mission-scraping is best-effort: a corrupt/unreadable mission file (or a sidecar
    like meta.json/workshop.json, which simply has no matching keys) is skipped, never raises."""
    found = {name: set(keys) for name, keys in seed_unit_keys().items()}
    missions_dir = Path(missions_dir)
    if not missions_dir.is_dir():
        return {name: sorted(keys) for name, keys in found.items()}

    for mission_json in missions_dir.glob("*/*.json"):
        try:
            data = json.loads(mission_json.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        for category, meta in CATEGORIES.items():
            mission_key = meta["mission_key"]
            if not mission_key:
                continue
            for item in data.get(mission_key, None) or []:
                if isinstance(item, dict) and item.get("type"):
                    found[category].add(str(item["type"]))

    return {name: sorted(keys) for name, keys in found.items()}

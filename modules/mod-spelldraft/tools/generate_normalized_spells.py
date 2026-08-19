#!/usr/bin/env python3
"""Build level-normalized SpellDraft clones from the live WotLK DBCs.

The source registry intentionally stores policy, not copied Blizzard numbers.
At prepare time this tool resolves the current real SpellDraft catalog, selects
all non-talent class roots learned at or before the configured level, reads each
canonical AzerothCore rank family as scaling anchors, and creates one 201xxx
spell per family.

The original rank rows remain in the DBC because core scripts can reference
them, but the generated resolved registry tells the SpellDraft catalog stage to
replace the native root card with the rankless custom spell.

Runtime scaling is generic: for every amount-bearing effect we interpolate the
native rank values per player level. The custom DBC effect has no native random
roll/RealPointsPerLevel; C++ chooses the exact level range before the cast with
Spell::SetSpellValue, so damage, healing, absorbs, armor, energize and other
normal effect amounts keep AzerothCore's regular handling after normalization.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import struct
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from generate_spelldraft_catalog import (
    CLASS_SET,
    CatalogError,
    DEFAULT_CARD_DEPENDENCIES,
    DEFAULT_RARITY_OVERRIDES,
    build_catalog,
    load_card_dependencies,
    load_rarity_overrides,
    parse_spell_data,
    parse_spell_ranks,
    read_dbc as read_catalog_dbc,
    skillline_categories,
    spell_meta,
    spell_skill_categories,
    talent_spells,
)
from patch_adventurer_class_dbcs import DBCError, read_dbc, set_u32, u32, write_dbc

MODULE = Path(__file__).resolve().parent.parent
REPO = MODULE.parents[1]
DEFAULT_REGISTRY = MODULE / "custom_spells.json"
DEFAULT_SPELL_RANKS = REPO / "data/sql/base/db_world/spell_ranks.sql"

SPELL_FIELDS = 234
SPELL_RECORD_SIZE = 936
SPELL_ID = 0
STANCE_MASK_LOW = 12
STANCE_MASK_HIGH = 13
STANCE_EXCLUDE_LOW = 14
STANCE_EXCLUDE_HIGH = 15
MAX_LEVEL = 37
BASE_LEVEL = 38
SPELL_LEVEL = 39
DURATION_INDEX = 40
EFFECT_TYPE = 71
EFFECT_DIE_SIDES = 74
EFFECT_REAL_POINTS_PER_LEVEL = 77
EFFECT_BASE_POINTS = 80
EFFECT_APPLY_AURA = 95
EFFECT_AMPLITUDE = 98

SKILLLINE_ID = 0
SKILLLINE_SKILL = 1
SKILLLINE_SPELL = 2
SKILLLINE_SUPERSEDED = 8

# Effect kinds whose numeric BasePoints are normal magnitudes even when a spell
# has only one native rank. For APPLY_AURA/area-aura effects we scale only when
# the amount actually changes across ranks, which avoids shrinking fixed 40%
# slows, fixed stun strengths, form IDs, and similar mechanics below level 20.
DIRECT_MAGNITUDE_EFFECTS = {
    2,    # SCHOOL_DAMAGE
    3,    # DUMMY (class scripts commonly consume CalcValue)
    7,    # ENVIRONMENTAL_DAMAGE
    8,    # POWER_DRAIN
    9,    # HEALTH_LEECH
    10,   # HEAL
    17,   # WEAPON_DAMAGE_NOSCHOOL
    19,   # ADD_EXTRA_ATTACKS
    30,   # ENERGIZE
    31,   # WEAPON_PERCENT_DAMAGE
    58,   # WEAPON_DAMAGE
    62,   # POWER_BURN
    63,   # THREAT
    67,   # HEAL_MAX_HEALTH
    75,   # HEAL_MECHANICAL
    77,   # SCRIPT_EFFECT
    80,   # ADD_COMBO_POINTS
    91,   # THREAT_ALL
    94,   # SELF_RESURRECT
    109,  # RESURRECT_PET
    121,  # NORMALIZED_WEAPON_DMG
    125,  # MODIFY_THREAT_PERCENT
    136,  # HEAL_PCT
    137,  # ENERGIZE_PCT
    141,  # FORCE_CAST_WITH_VALUE
    142,  # TRIGGER_SPELL_WITH_VALUE
    148,  # TRIGGER_MISSILE_SPELL_WITH_VALUE
}
AURA_EFFECT_TYPES = {6, 27, 35, 65, 119, 128, 129, 143}


CLASS_SKILL_LINES = {
    "MAGE": {6, 8, 237},
    "WARRIOR": {26, 256, 257},
    "WARLOCK": {188, 354, 355, 593, 761},
    "PRIEST": {56, 78, 613},
    "DRUID": {134, 573, 574},
    "ROGUE": {38, 39, 253, 633},
    "HUNTER": {50, 51, 163, 270, 788},
    "PALADIN": {184, 267, 594},
    "SHAMAN": {373, 374, 375},
}
CLASS_BY_SET = {value: key for key, value in CLASS_SET.items()}


class NormalizeError(RuntimeError):
    pass


@dataclass(frozen=True)
class AmountRange:
    minimum: int
    maximum: int

    @property
    def strength(self) -> float:
        return (abs(self.minimum) + abs(self.maximum)) / 2.0


@dataclass(frozen=True)
class RankSample:
    spell_id: int
    level: int
    record: bytes
    duration_ms: int


@dataclass(frozen=True)
class EffectCurve:
    effect_index: int
    effect_type: int
    aura_type: int
    anchors: tuple[tuple[int, AmountRange], ...]
    levels: tuple[AmountRange, ...]


def i32(record: bytes | bytearray, field: int) -> int:
    return struct.unpack_from("<i", record, field * 4)[0]


def f32(record: bytes | bytearray, field: int) -> float:
    return struct.unpack_from("<f", record, field * 4)[0]


def set_i32(record: bytearray, field: int, value: int) -> None:
    struct.pack_into("<i", record, field * 4, int(value))


def set_f32(record: bytearray, field: int, value: float) -> None:
    struct.pack_into("<f", record, field * 4, float(value))


def set_u64(record: bytearray, low_field: int, high_field: int, value: int) -> None:
    set_u32(record, low_field, value & 0xFFFFFFFF)
    set_u32(record, high_field, (value >> 32) & 0xFFFFFFFF)


def load_policy(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise NormalizeError(f"missing custom spell registry: {path}") from exc
    except json.JSONDecodeError as exc:
        raise NormalizeError(f"invalid JSON in {path}: {exc}") from exc

    if data.get("version") != 2:
        raise NormalizeError(f"{path}: expected registry version 2")
    id_range = data.get("custom_id_range")
    if not isinstance(id_range, list) or len(id_range) != 2:
        raise NormalizeError("custom_id_range must be [min, max]")
    custom_id_offset = data.get("custom_id_offset")
    if not isinstance(custom_id_offset, int) or custom_id_offset <= 0:
        raise NormalizeError("custom_id_offset must be a positive integer")
    selection = data.get("selection")
    if not isinstance(selection, dict):
        raise NormalizeError("selection must be an object")
    if selection.get("mode") != "current_spelldraft_roots":
        raise NormalizeError("only selection.mode=current_spelldraft_roots is supported")
    return data


def dbc_records_by_id(path: Path) -> tuple[int, int, list[bytearray], bytearray, bytes, dict[int, bytearray]]:
    fields, record_size, records, strings, trailing = read_dbc(path)
    by_id = {u32(row, 0): row for row in records}
    return fields, record_size, records, strings, trailing, by_id


def duration_map(path: Path) -> dict[int, int]:
    dbc = read_catalog_dbc(path)
    if dbc.fields != 4 or dbc.record_size != 16:
        raise NormalizeError(
            f"{path}: unexpected SpellDuration layout {dbc.fields} fields / {dbc.record_size} bytes"
        )
    result: dict[int, int] = {}
    for row in dbc.records:
        duration_id = dbc.u32(row, 0)
        raw = struct.unpack_from("<i", row, 4)[0]
        result[duration_id] = -1 if raw == -1 else abs(raw)
    return result


def effect_range(record: bytes | bytearray, effect_index: int) -> AmountRange:
    base = i32(record, EFFECT_BASE_POINTS + effect_index)
    die = i32(record, EFFECT_DIE_SIDES + effect_index)
    if die == 0:
        return AmountRange(base, base)
    low = base + min(1, die)
    high = base + max(1, die)
    return AmountRange(min(low, high), max(low, high))


def sample_strength(record: bytes | bytearray) -> float:
    total = 0.0
    for index in range(3):
        if u32(record, EFFECT_TYPE + index) == 0:
            continue
        total += effect_range(record, index).strength
    return total


def rank_samples(
    root: int,
    rank_rows: list[tuple[int, int]],
    spell_rows: dict[int, bytearray],
    durations: dict[int, int],
) -> list[RankSample]:
    strongest_by_level: dict[int, RankSample] = {}
    for _rank, spell_id in rank_rows:
        row = spell_rows.get(spell_id)
        if row is None:
            continue
        level = max(1, u32(row, SPELL_LEVEL))
        duration = durations.get(u32(row, DURATION_INDEX), 0)
        sample = RankSample(spell_id, level, bytes(row), duration)
        previous = strongest_by_level.get(level)
        if previous is None or sample_strength(sample.record) > sample_strength(previous.record):
            strongest_by_level[level] = sample

    if not strongest_by_level:
        row = spell_rows.get(root)
        if row is None:
            raise NormalizeError(f"rank root {root} is missing from Spell.dbc")
        level = max(1, u32(row, SPELL_LEVEL))
        strongest_by_level[level] = RankSample(
            root,
            level,
            bytes(row),
            durations.get(u32(row, DURATION_INDEX), 0),
        )
    return [strongest_by_level[level] for level in sorted(strongest_by_level)]


def signed_scaled(value: int, ratio: float) -> int:
    if value == 0:
        return 0
    magnitude = max(1, int(math.floor(abs(value) * ratio + 0.5)))
    return magnitude if value > 0 else -magnitude


def linear_int(a: int, b: int, t: float) -> int:
    value = a + (b - a) * t
    if value >= 0:
        return int(math.floor(value + 0.5))
    return -int(math.floor(abs(value) + 0.5))


def interpolate_ranges(
    anchors: list[tuple[int, AmountRange]],
    max_level: int,
    low_level_offset: float,
) -> tuple[AmountRange, ...]:
    if not anchors:
        raise NormalizeError("cannot interpolate an empty effect curve")

    points = list(anchors)
    first_level, first_range = points[0]
    if first_level > 1:
        ratio = (1.0 + low_level_offset) / (first_level + low_level_offset)
        level_one = AmountRange(
            signed_scaled(first_range.minimum, ratio),
            signed_scaled(first_range.maximum, ratio),
        )
        points.insert(0, (1, level_one))

    result: list[AmountRange] = []
    for level in range(1, max_level + 1):
        if level <= points[0][0]:
            current = points[0][1]
        elif level >= points[-1][0]:
            current = points[-1][1]
        else:
            current = points[-1][1]
            for index in range(len(points) - 1):
                left_level, left = points[index]
                right_level, right = points[index + 1]
                if left_level <= level <= right_level:
                    span = right_level - left_level
                    t = 0.0 if span == 0 else (level - left_level) / span
                    current = AmountRange(
                        linear_int(left.minimum, right.minimum, t),
                        linear_int(left.maximum, right.maximum, t),
                    )
                    break
        result.append(AmountRange(min(current.minimum, current.maximum), max(current.minimum, current.maximum)))
    return tuple(result)


def should_scale_effect(samples: list[RankSample], effect_index: int) -> bool:
    root = samples[0].record
    effect_type = u32(root, EFFECT_TYPE + effect_index)
    if effect_type == 0:
        return False

    ranges = [effect_range(sample.record, effect_index) for sample in samples]
    has_amount = any(item.minimum != 0 or item.maximum != 0 for item in ranges)
    if not has_amount:
        return False

    signatures = {
        (
            item.minimum,
            item.maximum,
            round(f32(sample.record, EFFECT_REAL_POINTS_PER_LEVEL + effect_index), 6),
        )
        for sample, item in zip(samples, ranges)
    }
    if len(signatures) > 1:
        return True

    first_level = samples[0].level
    return first_level > 1 and effect_type in DIRECT_MAGNITUDE_EFFECTS


def build_effect_curves(
    samples: list[RankSample],
    max_level: int,
    low_level_offset: float,
) -> list[EffectCurve]:
    curves: list[EffectCurve] = []
    root_record = samples[0].record
    for effect_index in range(3):
        if not should_scale_effect(samples, effect_index):
            continue
        effect_type = u32(root_record, EFFECT_TYPE + effect_index)
        aura_type = u32(root_record, EFFECT_APPLY_AURA + effect_index)
        anchors = [(sample.level, effect_range(sample.record, effect_index)) for sample in samples]
        levels = interpolate_ranges(anchors, max_level, low_level_offset)
        curves.append(
            EffectCurve(
                effect_index=effect_index,
                effect_type=effect_type,
                aura_type=aura_type,
                anchors=tuple(anchors),
                levels=levels,
            )
        )
    return curves


def duration_levels(samples: list[RankSample], max_level: int) -> tuple[int, ...] | None:
    values = {sample.duration_ms for sample in samples}
    if len(values) <= 1:
        return None
    result: list[int] = []
    current = samples[0].duration_ms
    next_index = 1
    for level in range(1, max_level + 1):
        while next_index < len(samples) and level >= samples[next_index].level:
            current = samples[next_index].duration_ms
            next_index += 1
        result.append(current)
    return tuple(result)


def selected_skill_line(ability_dbc, root: int, class_name: str) -> int:
    preferred = CLASS_SKILL_LINES.get(class_name, set())
    rows = [row for row in ability_dbc.records if ability_dbc.u32(row, SKILLLINE_SPELL) == root]
    for row in rows:
        skill = ability_dbc.u32(row, SKILLLINE_SKILL)
        if skill in preferred:
            return skill
    if rows:
        return ability_dbc.u32(rows[0], SKILLLINE_SKILL)
    raise NormalizeError(f"spell {root} has no SkillLineAbility row")


def assign_ids(
    selected: list[dict[str, Any]],
    policy: dict[str, Any],
) -> dict[int, int]:
    low, high = [int(value) for value in policy["custom_id_range"]]
    offset = int(policy["custom_id_offset"])

    result: dict[int, int] = {}
    used: set[int] = set()

    for entry in selected:
        root = int(entry["id"])
        custom_id = offset + root

        if custom_id < low or custom_id > high:
            raise NormalizeError(
                f"native root {root} maps to custom spell {custom_id}, "
                f"outside reserved range {low}-{high}"
            )

        if custom_id in used:
            raise NormalizeError(
                f"duplicate deterministic custom spell ID {custom_id}"
            )

        result[root] = custom_id
        used.add(custom_id)

    return result


def pinned_changes(policy: dict[str, Any]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for item in policy.get("pinned", []):
        result[int(item["clone_from"])] = dict(item.get("changes") or {})
    return result


def patch_spell_rows(
    spell_path: Path,
    selected: list[dict[str, Any]],
    custom_ids: dict[int, int],
    samples_by_root: dict[int, list[RankSample]],
    curves_by_root: dict[int, list[EffectCurve]],
    max_level: int,
    changes_by_root: dict[int, dict[str, Any]],
) -> None:
    fields, record_size, records, strings, trailing, by_id = dbc_records_by_id(spell_path)
    if fields != SPELL_FIELDS or record_size != SPELL_RECORD_SIZE:
        raise NormalizeError(
            f"{spell_path}: expected Spell.dbc {SPELL_FIELDS} fields / {SPELL_RECORD_SIZE} bytes"
        )

    custom_id_set = set(custom_ids.values())
    records[:] = [row for row in records if u32(row, SPELL_ID) not in custom_id_set]

    for entry in selected:
        root = int(entry["id"])
        source = by_id.get(root)
        if source is None:
            raise NormalizeError(f"source spell {root} missing while patching Spell.dbc")
        clone = bytearray(source)
        set_u32(clone, SPELL_ID, custom_ids[root])
        set_u32(clone, MAX_LEVEL, max_level)
        set_u32(clone, BASE_LEVEL, 1)
        set_u32(clone, SPELL_LEVEL, 1)

        changes = changes_by_root.get(root, {})
        if "stance_mask" in changes:
            set_u64(clone, STANCE_MASK_LOW, STANCE_MASK_HIGH, int(changes["stance_mask"]))
        if "stance_exclude" in changes:
            set_u64(clone, STANCE_EXCLUDE_LOW, STANCE_EXCLUDE_HIGH, int(changes["stance_exclude"]))

        for curve in curves_by_root[root]:
            level_one = curve.levels[0]
            # Runtime chooses an exact roll in [min,max] and passes it through
            # SPELLVALUE_BASE_POINTn. Zero native dice/per-level prevents a
            # second hidden roll or level adjustment from being added afterward.
            set_i32(clone, EFFECT_DIE_SIDES + curve.effect_index, 0)
            set_f32(clone, EFFECT_REAL_POINTS_PER_LEVEL + curve.effect_index, 0.0)
            set_i32(
                clone,
                EFFECT_BASE_POINTS + curve.effect_index,
                int(math.floor((level_one.minimum + level_one.maximum) / 2.0 + 0.5)),
            )
        records.append(clone)

    records.sort(key=lambda row: u32(row, SPELL_ID))
    write_dbc(spell_path, fields, record_size, records, strings, trailing)


def patch_skillline_rows(
    path: Path,
    selected: list[dict[str, Any]],
    custom_ids: dict[int, int],
    selected_skill_lines: dict[int, int],
) -> None:
    fields, record_size, records, strings, trailing = read_dbc(path)
    if record_size != fields * 4 or fields < 12:
        raise NormalizeError(f"{path}: unexpected SkillLineAbility layout")

    custom_set = set(custom_ids.values())
    records = [row for row in records if u32(row, SKILLLINE_SPELL) not in custom_set]
    next_id = max((u32(row, SKILLLINE_ID) for row in records), default=0) + 1

    source_rows: dict[int, list[bytearray]] = defaultdict(list)
    for row in records:
        source_rows[u32(row, SKILLLINE_SPELL)].append(row)

    for entry in selected:
        root = int(entry["id"])
        skill_line = selected_skill_lines[root]
        candidates = [row for row in source_rows.get(root, []) if u32(row, SKILLLINE_SKILL) == skill_line]
        if not candidates:
            candidates = source_rows.get(root, [])
        if not candidates:
            raise NormalizeError(f"cannot clone SkillLineAbility for spell {root}")
        clone = bytearray(candidates[0])
        set_u32(clone, SKILLLINE_ID, next_id)
        next_id += 1
        set_u32(clone, SKILLLINE_SPELL, custom_ids[root])
        set_u32(clone, SKILLLINE_SUPERSEDED, 0)
        records.append(clone)

    records.sort(key=lambda row: u32(row, SKILLLINE_ID))
    write_dbc(path, fields, record_size, records, strings, trailing)


def render_scaling_tsv(
    selected: list[dict[str, Any]],
    custom_ids: dict[int, int],
    curves_by_root: dict[int, list[EffectCurve]],
    durations_by_root: dict[int, tuple[int, ...] | None],
    max_level: int,
) -> str:
    lines = [
        "# Aventureros de Azeroth normalized custom spell scaling",
        "# spell_id level duration_ms e0_min e0_max e1_min e1_max e2_min e2_max",
    ]
    for entry in selected:
        root = int(entry["id"])
        curve_by_index = {curve.effect_index: curve for curve in curves_by_root[root]}
        durations = durations_by_root[root]
        for level in range(1, max_level + 1):
            values = [str(custom_ids[root]), str(level), str(durations[level - 1] if durations else 0)]
            for effect_index in range(3):
                curve = curve_by_index.get(effect_index)
                if curve is None:
                    values.extend(["x", "x"])
                else:
                    amount = curve.levels[level - 1]
                    values.extend([str(amount.minimum), str(amount.maximum)])
            lines.append(" ".join(values))
    return "\n".join(lines) + "\n"


def write_resolved_json(
    path: Path,
    policy: dict[str, Any],
    selected: list[dict[str, Any]],
    custom_ids: dict[int, int],
    samples_by_root: dict[int, list[RankSample]],
    curves_by_root: dict[int, list[EffectCurve]],
    skill_lines: dict[int, int],
) -> None:
    resolved_spells: list[dict[str, Any]] = []
    for entry in selected:
        root = int(entry["id"])
        class_name = CLASS_BY_SET[int(entry["classSet"])]
        effects: list[dict[str, Any]] = []
        for curve in curves_by_root[root]:
            effects.append({
                "index": curve.effect_index,
                "effect_type": curve.effect_type,
                "aura_type": curve.aura_type,
                "anchors": [
                    {"level": level, "min": amount.minimum, "max": amount.maximum}
                    for level, amount in curve.anchors
                ],
            })
        resolved_spells.append({
            "id": custom_ids[root],
            "clone_from": root,
            "name": entry["name"],
            "class": class_name,
            "class_set": int(entry["classSet"]),
            "rarity": int(entry["rarity"]),
            "skill_line": skill_lines[root],
            "native_first_level": int(entry["minLevel"]),
            "native_ranks": [
                {"id": sample.spell_id, "level": sample.level}
                for sample in samples_by_root[root]
            ],
            "effects": effects,
            "draft": {
                "replace_original": True,
                "original_family": [sample.spell_id for sample in samples_by_root[root]],
            },
        })

    out = {
        "version": 1,
        "generated_from": "live DBC + current SpellDraft catalog + canonical spell_ranks.sql",
        "policy": policy["selection"],
        "runtime_max_level": int(policy["runtime_max_level"]),
        "spells": resolved_spells,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dbc-dir", required=True, type=Path)
    parser.add_argument("--spell-data", required=True, type=Path)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--spell-ranks-sql", type=Path, default=DEFAULT_SPELL_RANKS)
    parser.add_argument("--resolved-output", required=True, type=Path)
    parser.add_argument("--scaling-output", required=True, type=Path)
    args = parser.parse_args()

    dbc_dir = args.dbc_dir.expanduser().resolve()
    required = (
        "Spell.dbc",
        "SpellDuration.dbc",
        "SkillLine.dbc",
        "SkillLineAbility.dbc",
        "Talent.dbc",
    )
    missing = [name for name in required if not (dbc_dir / name).is_file()]
    if missing:
        raise SystemExit("Normalized-spell DBC input missing: " + ", ".join(missing))

    try:
        policy = load_policy(args.registry.expanduser().resolve())
        max_first_level = int(policy["selection"]["max_first_rank_level"])
        max_level = int(policy["runtime_max_level"])
        low_level_offset = float(policy["scaling"]["low_level_offset"])
        excluded_classes = set(policy["selection"].get("exclude_classes", []))

        curated = parse_spell_data(args.spell_data.expanduser().resolve())
        dependencies = load_card_dependencies(DEFAULT_CARD_DEPENDENCIES)
        rarity_overrides = load_rarity_overrides(DEFAULT_RARITY_OVERRIDES)
        root_by_spell, ranks_by_root = parse_spell_ranks(args.spell_ranks_sql.expanduser().resolve())
        spell_dbc = read_catalog_dbc(dbc_dir / "Spell.dbc")
        skill_dbc = read_catalog_dbc(dbc_dir / "SkillLine.dbc")
        ability_dbc = read_catalog_dbc(dbc_dir / "SkillLineAbility.dbc")
        talent_dbc = read_catalog_dbc(dbc_dir / "Talent.dbc")
        spells = spell_meta(spell_dbc)
        categories = skillline_categories(skill_dbc)
        categories_by_spell = spell_skill_categories(ability_dbc, categories)
        talents = talent_spells(talent_dbc)

        # Reuse the exact production catalog eligibility rather than maintain a
        # second approximation of what "draftable" means.
        with contextlib.redirect_stdout(io.StringIO()):
            base_catalog = build_catalog(
                curated,
                spells,
                categories_by_spell,
                talents,
                root_by_spell,
                ranks_by_root,
                dependencies,
                rarity_overrides,
            )
        selected = [
            entry for entry in base_catalog
            if int(entry["minLevel"]) <= max_first_level
            and CLASS_BY_SET[int(entry["classSet"])] not in excluded_classes
        ]
        if not selected:
            raise NormalizeError("selection produced no custom spells")

        custom_ids = assign_ids(selected, policy)
        changes_by_root = pinned_changes(policy)
        durations = duration_map(dbc_dir / "SpellDuration.dbc")
        _, _, _, _, _, spell_rows = dbc_records_by_id(dbc_dir / "Spell.dbc")

        samples_by_root: dict[int, list[RankSample]] = {}
        curves_by_root: dict[int, list[EffectCurve]] = {}
        durations_by_root: dict[int, tuple[int, ...] | None] = {}
        skill_lines: dict[int, int] = {}
        for entry in selected:
            root = int(entry["id"])
            class_name = CLASS_BY_SET[int(entry["classSet"])]
            samples = rank_samples(
                root,
                ranks_by_root.get(root, [(1, root)]),
                spell_rows,
                durations,
            )
            samples_by_root[root] = samples
            curves_by_root[root] = build_effect_curves(samples, max_level, low_level_offset)
            durations_by_root[root] = duration_levels(samples, max_level)
            skill_lines[root] = selected_skill_line(ability_dbc, root, class_name)

        patch_spell_rows(
            dbc_dir / "Spell.dbc",
            selected,
            custom_ids,
            samples_by_root,
            curves_by_root,
            max_level,
            changes_by_root,
        )
        patch_skillline_rows(
            dbc_dir / "SkillLineAbility.dbc",
            selected,
            custom_ids,
            skill_lines,
        )

        resolved_output = args.resolved_output.expanduser().resolve()
        scaling_output = args.scaling_output.expanduser().resolve()
        write_resolved_json(
            resolved_output,
            policy,
            selected,
            custom_ids,
            samples_by_root,
            curves_by_root,
            skill_lines,
        )
        scaling_output.parent.mkdir(parents=True, exist_ok=True)
        scaling_output.write_text(
            render_scaling_tsv(
                selected,
                custom_ids,
                curves_by_root,
                durations_by_root,
                max_level,
            ),
            encoding="utf-8",
        )
    except (CatalogError, DBCError, NormalizeError, KeyError, ValueError) as exc:
        raise SystemExit(f"Normalized custom spell generation aborted: {exc}") from exc

    counts = Counter(CLASS_BY_SET[int(entry["classSet"])] for entry in selected)
    scaled_effects = sum(len(curves_by_root[int(entry["id"])]) for entry in selected)
    print(f"Normalized custom spells generated: {len(selected)} families -> 201xxx")
    print(f"  source first-rank level: <= {max_first_level}")
    print(f"  runtime levels: 1-{max_level}")
    print(f"  generic numeric effect curves: {scaled_effects}")
    print("  classes: " + ", ".join(f"{name}={counts[name]}" for name in sorted(counts)))
    print(f"  resolved registry: {args.resolved_output.expanduser().resolve()}")
    print(f"  runtime scaling:   {args.scaling_output.expanduser().resolve()}")
    print("  originals remain as internal DBC sources but will be removed from the draft catalog")


if __name__ == "__main__":
    main()

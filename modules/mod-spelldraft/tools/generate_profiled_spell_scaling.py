#!/usr/bin/env python3
"""Generate profile-aware per-level runtime data from native WoW rank anchors.

The first normalized-spell implementation treated every scalable numeric effect
as an anonymous min/max pair. That is sufficient for direct damage but loses
important spell semantics: a periodic damage effect is a per-tick amount while
its tooltip normally talks about TOTAL damage over a duration, and cast time is
not an effect at all.

This stage runs after generate_normalized_spells.py. It keeps the existing
201xxx IDs/DBC clones, but rebuilds their runtime scaling from the native rank
family using explicit profile fields.

For a damage_with_dot spell the authored/resolved model is:
    level -> direct min/max | DoT total min/max | duration | cast time | tick

Between native rank anchors values are linearly interpolated. Integer gameplay
amounts and durations are rounded; cast time is quantized to 100 ms so client
and server can display/use values such as 1.6 s. The generated TSV still stores
effect base-point ranges because AzerothCore consumes per-effect values at cast
time, but the semantic JSON remains the source of truth for client tooltips and
future profile-specific rules.

Profiles currently emitted:
  * damage_with_dot  - direct school damage + periodic-damage aura
  * direct_damage    - direct school damage only
  * dot_damage       - periodic-damage aura only
  * generic          - existing scalable effect curves, plus cast/duration

No spell-power/intellect formula is baked into this file. Runtime values are
base spell values; AzerothCore applies its normal spell-power, crit, aura and
target modifiers afterwards.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from generate_normalized_spells import (
    AmountRange,
    effect_range,
    interpolate_ranges,
    linear_int,
)
from patch_adventurer_class_dbcs import read_dbc, set_u32, u32, write_dbc

MODULE = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY = MODULE / "custom_spells.json"

SPELL_ID = 0
CAST_TIME_INDEX = 28
DURATION_INDEX = 40
EFFECT_TYPE = 71
EFFECT_DIE_SIDES = 74
EFFECT_REAL_POINTS_PER_LEVEL = 77
EFFECT_BASE_POINTS = 80
EFFECT_APPLY_AURA = 95
EFFECT_AMPLITUDE = 98

SPELL_EFFECT_SCHOOL_DAMAGE = 2
SPELL_AURA_PERIODIC_DAMAGE = 3


class ProfileError(RuntimeError):
    pass


@dataclass(frozen=True)
class NativeRank:
    spell_id: int
    level: int
    row: bytearray
    cast_ms: int
    duration_ms: int


@dataclass(frozen=True)
class RuntimeLevel:
    cast_ms: int
    duration_ms: int
    effects: tuple[AmountRange | None, AmountRange | None, AmountRange | None]


def i32(row: bytes | bytearray, field: int) -> int:
    return struct.unpack_from("<i", row, field * 4)[0]


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProfileError(f"{label} not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ProfileError(f"invalid {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProfileError(f"{label} must be a JSON object: {path}")
    return value


def rows_by_id(path: Path) -> tuple[int, int, list[bytearray], bytearray, bytes, dict[int, bytearray]]:
    fields, record_size, records, strings, trailing = read_dbc(path)
    return fields, record_size, records, strings, trailing, {u32(row, 0): row for row in records}


def signed_row_value(row: bytearray | None, field: int, default: int = 0) -> int:
    if row is None:
        return default
    return i32(row, field)


def load_cast_times(path: Path) -> dict[int, int]:
    fields, record_size, records, _strings, _trailing = read_dbc(path)
    if fields < 2 or record_size != fields * 4:
        raise ProfileError(f"{path}: unexpected SpellCastTimes.dbc layout")
    return {u32(row, 0): max(0, i32(row, 1)) for row in records}


def load_durations(path: Path) -> dict[int, int]:
    fields, record_size, records, _strings, _trailing = read_dbc(path)
    if fields < 2 or record_size != fields * 4:
        raise ProfileError(f"{path}: unexpected SpellDuration.dbc layout")
    result: dict[int, int] = {}
    for row in records:
        raw = i32(row, 1)
        result[u32(row, 0)] = 0 if raw < 0 else abs(raw)
    return result


def nearest_quantum(value: float, quantum: int) -> int:
    if quantum <= 1:
        return int(math.floor(value + 0.5))
    return int(math.floor(value / quantum + 0.5)) * quantum


def interpolate_scalar(
    anchors: list[tuple[int, int]],
    max_level: int,
    quantum: int,
) -> tuple[int, ...]:
    if not anchors:
        return tuple(0 for _ in range(max_level))

    ordered = sorted(anchors)
    result: list[int] = []
    for level in range(1, max_level + 1):
        if level <= ordered[0][0]:
            value = ordered[0][1]
        elif level >= ordered[-1][0]:
            value = ordered[-1][1]
        else:
            value = ordered[-1][1]
            for index in range(len(ordered) - 1):
                left_level, left = ordered[index]
                right_level, right = ordered[index + 1]
                if left_level <= level <= right_level:
                    t = (level - left_level) / (right_level - left_level)
                    value = nearest_quantum(left + (right - left) * t, quantum)
                    break
        result.append(int(value))
    return tuple(result)


def profile_low_level_offset(registry: dict[str, Any]) -> float:
    scaling = registry.get("scaling")
    if not isinstance(scaling, dict):
        raise ProfileError("custom spell registry has no scaling object")
    try:
        return float(scaling["low_level_offset"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ProfileError("custom spell registry scaling.low_level_offset is invalid") from exc


def native_ranks(
    spec: dict[str, Any],
    spell_rows: dict[int, bytearray],
    casts: dict[int, int],
    durations: dict[int, int],
) -> list[NativeRank]:
    raw_ranks = spec.get("native_ranks")
    if not isinstance(raw_ranks, list) or not raw_ranks:
        raise ProfileError(f"custom spell {spec.get('id')} has no native_ranks")

    result: list[NativeRank] = []
    seen_levels: set[int] = set()
    for item in raw_ranks:
        if not isinstance(item, dict):
            raise ProfileError(f"custom spell {spec.get('id')} has malformed native rank")
        spell_id = int(item["id"])
        level = max(1, int(item["level"]))
        row = spell_rows.get(spell_id)
        if row is None:
            raise ProfileError(f"native rank {spell_id} is missing from Spell.dbc")
        if level in seen_levels:
            raise ProfileError(f"custom spell {spec.get('id')} has duplicate native level {level}")
        seen_levels.add(level)
        cast_ms = casts.get(u32(row, CAST_TIME_INDEX), 0)
        duration_ms = durations.get(u32(row, DURATION_INDEX), 0)
        result.append(NativeRank(spell_id, level, row, cast_ms, duration_ms))
    result.sort(key=lambda rank: rank.level)
    return result


def effect_metadata(row: bytearray, effect_index: int) -> tuple[int, int, int]:
    return (
        u32(row, EFFECT_TYPE + effect_index),
        u32(row, EFFECT_APPLY_AURA + effect_index),
        u32(row, EFFECT_AMPLITUDE + effect_index),
    )


def detect_profile(ranks: list[NativeRank]) -> tuple[str, int | None, int | None]:
    root = ranks[0].row
    direct_index: int | None = None
    periodic_index: int | None = None
    for effect_index in range(3):
        effect_type, aura_type, _amplitude = effect_metadata(root, effect_index)
        if direct_index is None and effect_type == SPELL_EFFECT_SCHOOL_DAMAGE:
            direct_index = effect_index
        if periodic_index is None and aura_type == SPELL_AURA_PERIODIC_DAMAGE:
            periodic_index = effect_index

    if direct_index is not None and periodic_index is not None:
        return "damage_with_dot", direct_index, periodic_index
    if direct_index is not None:
        return "direct_damage", direct_index, None
    if periodic_index is not None:
        return "dot_damage", None, periodic_index
    return "generic", None, None


def amount_anchor_dict(level: int, amount: AmountRange) -> dict[str, int]:
    return {"level": level, "min": amount.minimum, "max": amount.maximum}


def semantic_anchors(
    ranks: list[NativeRank],
    profile: str,
    direct_index: int | None,
    periodic_index: int | None,
) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    for rank in ranks:
        entry: dict[str, Any] = {
            "level": rank.level,
            "source_spell_id": rank.spell_id,
            "cast_ms": rank.cast_ms,
            "duration_ms": rank.duration_ms,
        }
        if direct_index is not None:
            direct = effect_range(rank.row, direct_index)
            entry["direct"] = {"min": direct.minimum, "max": direct.maximum}

        if periodic_index is not None:
            periodic = effect_range(rank.row, periodic_index)
            amplitude_ms = u32(rank.row, EFFECT_AMPLITUDE + periodic_index)
            if amplitude_ms <= 0:
                raise ProfileError(
                    f"spell {rank.spell_id} periodic-damage effect {periodic_index} has zero amplitude"
                )
            ticks = max(1, rank.duration_ms // amplitude_ms) if rank.duration_ms > 0 else 1
            entry["tick_ms"] = amplitude_ms
            entry["dot_total"] = {
                "min": periodic.minimum * ticks,
                "max": periodic.maximum * ticks,
            }

        anchors.append(entry)
    return anchors


def synthetic_amount_points(
    anchors: list[tuple[int, AmountRange]],
    max_level: int,
    low_level_offset: float,
) -> tuple[AmountRange, ...]:
    return interpolate_ranges(anchors, max_level, low_level_offset)


def divide_dot_total(total: AmountRange, ticks: int) -> AmountRange:
    ticks = max(1, ticks)
    minimum = linear_int(0, total.minimum, 1.0 / ticks)
    maximum = linear_int(0, total.maximum, 1.0 / ticks)
    return AmountRange(min(minimum, maximum), max(minimum, maximum))


def build_profile_runtime(
    ranks: list[NativeRank],
    profile: str,
    direct_index: int | None,
    periodic_index: int | None,
    resolved_effects: list[dict[str, Any]],
    max_level: int,
    low_level_offset: float,
) -> tuple[list[RuntimeLevel], list[dict[str, Any]]]:
    cast_levels = interpolate_scalar([(rank.level, rank.cast_ms) for rank in ranks], max_level, 100)
    duration_levels = interpolate_scalar(
        [(rank.level, rank.duration_ms) for rank in ranks], max_level, 1000
    )
    semantic = semantic_anchors(ranks, profile, direct_index, periodic_index)

    effect_levels: dict[int, tuple[AmountRange, ...]] = {}
    for effect in resolved_effects:
        if not isinstance(effect, dict):
            continue
        effect_index = int(effect.get("index", -1))
        raw_anchors = effect.get("anchors")
        if effect_index not in (0, 1, 2) or not isinstance(raw_anchors, list) or not raw_anchors:
            continue
        anchors = [
            (
                int(anchor["level"]),
                AmountRange(int(anchor["min"]), int(anchor["max"])),
            )
            for anchor in raw_anchors
        ]
        effect_levels[effect_index] = synthetic_amount_points(anchors, max_level, low_level_offset)

    if direct_index is not None:
        direct_anchors = [
            (rank.level, effect_range(rank.row, direct_index))
            for rank in ranks
        ]
        effect_levels[direct_index] = synthetic_amount_points(
            direct_anchors, max_level, low_level_offset
        )

    dot_total_levels: tuple[AmountRange, ...] | None = None
    tick_ms_levels: tuple[int, ...] | None = None
    if periodic_index is not None:
        total_anchors: list[tuple[int, AmountRange]] = []
        tick_anchors: list[tuple[int, int]] = []
        for rank in ranks:
            per_tick = effect_range(rank.row, periodic_index)
            amplitude_ms = u32(rank.row, EFFECT_AMPLITUDE + periodic_index)
            if amplitude_ms <= 0:
                raise ProfileError(
                    f"spell {rank.spell_id} periodic-damage effect {periodic_index} has zero amplitude"
                )
            ticks = max(1, rank.duration_ms // amplitude_ms) if rank.duration_ms > 0 else 1
            total_anchors.append(
                (
                    rank.level,
                    AmountRange(per_tick.minimum * ticks, per_tick.maximum * ticks),
                )
            )
            tick_anchors.append((rank.level, amplitude_ms))
        dot_total_levels = synthetic_amount_points(total_anchors, max_level, low_level_offset)
        tick_ms_levels = interpolate_scalar(tick_anchors, max_level, 1)

    runtime: list[RuntimeLevel] = []
    for level in range(1, max_level + 1):
        effects: list[AmountRange | None] = [None, None, None]
        for effect_index, levels in effect_levels.items():
            effects[effect_index] = levels[level - 1]

        if periodic_index is not None and dot_total_levels is not None and tick_ms_levels is not None:
            duration_ms = duration_levels[level - 1]
            tick_ms = max(1, tick_ms_levels[level - 1])
            ticks = max(1, duration_ms // tick_ms) if duration_ms > 0 else 1
            effects[periodic_index] = divide_dot_total(dot_total_levels[level - 1], ticks)

        runtime.append(
            RuntimeLevel(
                cast_ms=cast_levels[level - 1],
                duration_ms=duration_levels[level - 1],
                effects=(effects[0], effects[1], effects[2]),
            )
        )
    return runtime, semantic


def patch_custom_fallback_cast(
    spell_path: Path,
    specs: list[dict[str, Any]],
) -> int:
    fields, record_size, records, strings, trailing = read_dbc(spell_path)
    by_id = {u32(row, SPELL_ID): row for row in records}
    changed = 0
    for spec in specs:
        custom_id = int(spec["id"])
        source_id = int(spec["clone_from"])
        custom = by_id.get(custom_id)
        source = by_id.get(source_id)
        if custom is None or source is None:
            raise ProfileError(f"cannot restore fallback cast for {custom_id} <- {source_id}")
        desired = u32(source, CAST_TIME_INDEX)
        if u32(custom, CAST_TIME_INDEX) != desired:
            set_u32(custom, CAST_TIME_INDEX, desired)
            changed += 1
    write_dbc(spell_path, fields, record_size, records, strings, trailing)
    return changed


def render_runtime_tsv(
    runtime_by_spell: dict[int, list[RuntimeLevel]],
) -> str:
    lines = [
        "# Aventureros de Azeroth profile-aware normalized spell scaling v2",
        "# spell_id level cast_ms duration_ms e0_min e0_max e1_min e1_max e2_min e2_max",
    ]
    for spell_id in sorted(runtime_by_spell):
        for level, rule in enumerate(runtime_by_spell[spell_id], 1):
            values = [str(spell_id), str(level), str(rule.cast_ms), str(rule.duration_ms)]
            for effect in rule.effects:
                if effect is None:
                    values.extend(["x", "x"])
                else:
                    values.extend([str(effect.minimum), str(effect.maximum)])
            lines.append(" ".join(values))
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dbc-dir", required=True, type=Path)
    parser.add_argument("--resolved", required=True, type=Path)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--scaling-output", required=True, type=Path)
    parser.add_argument("--profiles-output", required=True, type=Path)
    args = parser.parse_args()

    dbc_dir = args.dbc_dir.expanduser().resolve()
    required = ["Spell.dbc", "SpellCastTimes.dbc", "SpellDuration.dbc"]
    missing = [name for name in required if not (dbc_dir / name).is_file()]
    if missing:
        raise SystemExit("Profiled scaling DBC input missing: " + ", ".join(missing))

    try:
        resolved = load_json(args.resolved.expanduser().resolve(), "resolved custom spell registry")
        registry = load_json(args.registry.expanduser().resolve(), "custom spell registry")
        max_level = int(resolved["runtime_max_level"])
        specs = resolved.get("spells")
        if max_level <= 0 or not isinstance(specs, list) or not specs:
            raise ProfileError("resolved registry has invalid runtime_max_level/spells")

        low_level_offset = profile_low_level_offset(registry)
        _fields, _size, _records, _strings, _trailing, spell_rows = rows_by_id(dbc_dir / "Spell.dbc")
        casts = load_cast_times(dbc_dir / "SpellCastTimes.dbc")
        durations = load_durations(dbc_dir / "SpellDuration.dbc")

        runtime_by_spell: dict[int, list[RuntimeLevel]] = {}
        profile_specs: list[dict[str, Any]] = []
        profile_counts: dict[str, int] = {}

        for raw_spec in specs:
            if not isinstance(raw_spec, dict):
                raise ProfileError("resolved spells list contains a non-object")
            custom_id = int(raw_spec["id"])
            source_id = int(raw_spec["clone_from"])
            ranks = native_ranks(raw_spec, spell_rows, casts, durations)
            profile, direct_index, periodic_index = detect_profile(ranks)
            runtime, semantic = build_profile_runtime(
                ranks,
                profile,
                direct_index,
                periodic_index,
                raw_spec.get("effects") if isinstance(raw_spec.get("effects"), list) else [],
                max_level,
                low_level_offset,
            )
            runtime_by_spell[custom_id] = runtime
            profile_counts[profile] = profile_counts.get(profile, 0) + 1

            item: dict[str, Any] = {
                "id": custom_id,
                "clone_from": source_id,
                "name": raw_spec.get("name", f"Spell {custom_id}"),
                "profile": profile,
                "anchors": semantic,
            }
            if direct_index is not None:
                item["direct_effect_index"] = direct_index
            if periodic_index is not None:
                item["periodic_effect_index"] = periodic_index
            profile_specs.append(item)

        changed_cast_rows = patch_custom_fallback_cast(dbc_dir / "Spell.dbc", specs)

        scaling_output = args.scaling_output.expanduser().resolve()
        scaling_output.parent.mkdir(parents=True, exist_ok=True)
        scaling_output.write_text(render_runtime_tsv(runtime_by_spell), encoding="utf-8")

        profiles_output = args.profiles_output.expanduser().resolve()
        profiles_output.parent.mkdir(parents=True, exist_ok=True)
        profiles_output.write_text(
            json.dumps(
                {
                    "version": 2,
                    "runtime_max_level": max_level,
                    "low_level_offset": low_level_offset,
                    "generated_from": "native rank Spell.dbc + SpellCastTimes.dbc + SpellDuration.dbc",
                    "spells": profile_specs,
                },
                indent=2,
                ensure_ascii=False,
            ) + "\n",
            encoding="utf-8",
        )
    except (KeyError, TypeError, ValueError, ProfileError) as exc:
        raise SystemExit(f"Profiled custom spell generation aborted: {exc}") from exc

    print("Profile-aware custom spell scaling generated:")
    print(f"  spells: {len(profile_specs)}")
    print("  profiles: " + ", ".join(f"{key}={profile_counts[key]}" for key in sorted(profile_counts)))
    print(f"  runtime levels: 1-{max_level}")
    print("  interpolation: effect amounts=integer, duration=1s, cast=0.1s")
    print(f"  custom DBC fallback casts restored to rank-1 source: {changed_cast_rows}")
    print(f"  runtime TSV v2: {scaling_output}")
    print(f"  semantic profiles: {profiles_output}")


if __name__ == "__main__":
    main()

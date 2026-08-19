#!/usr/bin/env python3
"""Validate profile-aware native anchors against the generated runtime TSV.

This is intentionally data-only: it does not start or build AzerothCore. It
checks the invariants that matter before in-game testing:

* every 201xxx profile has exactly levels 1..runtime_max_level in TSV v2;
* every native rank anchor is reproduced exactly for cast time, duration and
  direct damage;
* native periodic anchors reproduce their total DoT exactly when represented by
  AzerothCore's integer per-tick base amount;
* the custom Spell.dbc fallback CastingTimeIndex is the native root/rank-1 one,
  never the former highest-rank conservative cast;
* intermediate periodic totals report their maximum integer tick-quantization
  drift so it is visible instead of silently hidden.
"""

from __future__ import annotations

import argparse
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from patch_adventurer_class_dbcs import read_dbc, u32

SPELL_ID = 0
CAST_TIME_INDEX = 28


class ValidateError(RuntimeError):
    pass


@dataclass(frozen=True)
class EffectRange:
    minimum: int
    maximum: int


@dataclass(frozen=True)
class RuntimeRow:
    cast_ms: int
    duration_ms: int
    effects: tuple[EffectRange | None, EffectRange | None, EffectRange | None]


def i32(row: bytes | bytearray, field: int) -> int:
    return struct.unpack_from("<i", row, field * 4)[0]


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValidateError(f"profile registry not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValidateError(f"invalid profile registry {path}: {exc}") from exc
    if not isinstance(data, dict) or int(data.get("version", 0)) != 2:
        raise ValidateError(f"{path}: expected profile registry version 2")
    return data


def load_runtime(path: Path) -> dict[int, dict[int, RuntimeRow]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise ValidateError(f"runtime TSV not found: {path}") from exc

    result: dict[int, dict[int, RuntimeRow]] = {}
    for line_number, raw in enumerate(lines, 1):
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        parts = raw.split()
        if len(parts) != 10:
            raise ValidateError(
                f"{path}:{line_number}: expected TSV v2 with 10 fields, got {len(parts)}"
            )
        try:
            spell_id = int(parts[0])
            level = int(parts[1])
            cast_ms = int(parts[2])
            duration_ms = int(parts[3])
            effects: list[EffectRange | None] = []
            for index in range(3):
                low = parts[4 + index * 2]
                high = parts[5 + index * 2]
                if low == "x" and high == "x":
                    effects.append(None)
                elif low == "x" or high == "x":
                    raise ValueError("partial x range")
                else:
                    minimum = int(low)
                    maximum = int(high)
                    if maximum < minimum:
                        raise ValueError("reversed effect range")
                    effects.append(EffectRange(minimum, maximum))
        except ValueError as exc:
            raise ValidateError(f"{path}:{line_number}: malformed TSV v2 row") from exc

        if not 201000 <= spell_id <= 201999 or level <= 0 or cast_ms < 0 or duration_ms < 0:
            raise ValidateError(f"{path}:{line_number}: invalid spell/level/cast/duration")
        levels = result.setdefault(spell_id, {})
        if level in levels:
            raise ValidateError(f"{path}:{line_number}: duplicate {spell_id}:{level}")
        levels[level] = RuntimeRow(cast_ms, duration_ms, tuple(effects))  # type: ignore[arg-type]
    return result


def dbc_rows(path: Path) -> dict[int, bytearray]:
    _fields, _record_size, records, _strings, _trailing = read_dbc(path)
    return {u32(row, SPELL_ID): row for row in records}


def scalar_at_anchor(anchor: dict[str, Any], field: str) -> int:
    try:
        return int(anchor[field])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidateError(f"malformed anchor field {field}: {anchor}") from exc


def range_at_anchor(anchor: dict[str, Any], field: str) -> EffectRange:
    value = anchor.get(field)
    if not isinstance(value, dict):
        raise ValidateError(f"malformed anchor range {field}: {anchor}")
    try:
        minimum = int(value["min"])
        maximum = int(value["max"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidateError(f"malformed anchor range {field}: {anchor}") from exc
    if maximum < minimum:
        raise ValidateError(f"reversed anchor range {field}: {anchor}")
    return EffectRange(minimum, maximum)


def validate_anchor_effect(
    spell_id: int,
    level: int,
    effect_index: int,
    expected: EffectRange,
    runtime: RuntimeRow,
    label: str,
) -> None:
    actual = runtime.effects[effect_index]
    if actual != expected:
        raise ValidateError(
            f"{spell_id} level {level} {label}: expected "
            f"{expected.minimum}-{expected.maximum}, got "
            f"{actual.minimum if actual else 'x'}-{actual.maximum if actual else 'x'}"
        )


def validate_profiles(
    profiles: dict[str, Any],
    runtime: dict[int, dict[int, RuntimeRow]],
    rows: dict[int, bytearray],
) -> tuple[int, int, int]:
    max_level = int(profiles.get("runtime_max_level", 0))
    spells = profiles.get("spells")
    if max_level <= 0 or not isinstance(spells, list) or not spells:
        raise ValidateError("profile registry has invalid runtime_max_level/spells")

    anchor_count = 0
    periodic_anchor_count = 0
    max_periodic_drift = 0
    profile_ids: set[int] = set()

    for spell in spells:
        if not isinstance(spell, dict):
            raise ValidateError("profile spells list contains a non-object")
        spell_id = int(spell["id"])
        source_id = int(spell["clone_from"])
        if spell_id in profile_ids:
            raise ValidateError(f"duplicate profile spell ID {spell_id}")
        profile_ids.add(spell_id)

        levels = runtime.get(spell_id)
        if levels is None:
            raise ValidateError(f"runtime TSV has no rows for {spell_id}")
        if set(levels) != set(range(1, max_level + 1)):
            raise ValidateError(f"runtime TSV levels are incomplete for {spell_id}")

        custom_row = rows.get(spell_id)
        source_row = rows.get(source_id)
        if custom_row is None or source_row is None:
            raise ValidateError(f"Spell.dbc missing custom/source row {spell_id}/{source_id}")
        if u32(custom_row, CAST_TIME_INDEX) != u32(source_row, CAST_TIME_INDEX):
            raise ValidateError(
                f"custom {spell_id} fallback CastingTimeIndex is not native root {source_id}"
            )

        direct_index = spell.get("direct_effect_index")
        periodic_index = spell.get("periodic_effect_index")
        if direct_index is not None:
            direct_index = int(direct_index)
        if periodic_index is not None:
            periodic_index = int(periodic_index)

        anchors = spell.get("anchors")
        if not isinstance(anchors, list) or not anchors:
            raise ValidateError(f"profile {spell_id} has no anchors")

        for anchor in anchors:
            if not isinstance(anchor, dict):
                raise ValidateError(f"profile {spell_id} contains malformed anchor")
            level = int(anchor["level"])
            if level < 1 or level > max_level:
                continue
            row = levels[level]
            anchor_count += 1

            expected_cast = scalar_at_anchor(anchor, "cast_ms")
            expected_duration = scalar_at_anchor(anchor, "duration_ms")
            if row.cast_ms != expected_cast:
                raise ValidateError(
                    f"{spell_id} level {level} cast: expected {expected_cast}, got {row.cast_ms}"
                )
            if row.duration_ms != expected_duration:
                raise ValidateError(
                    f"{spell_id} level {level} duration: expected {expected_duration}, got {row.duration_ms}"
                )

            if direct_index is not None and "direct" in anchor:
                validate_anchor_effect(
                    spell_id,
                    level,
                    direct_index,
                    range_at_anchor(anchor, "direct"),
                    row,
                    "direct",
                )

            if periodic_index is not None and "dot_total" in anchor:
                effect = row.effects[periodic_index]
                if effect is None:
                    raise ValidateError(
                        f"{spell_id} level {level}: periodic runtime effect is missing"
                    )
                tick_ms = max(1, scalar_at_anchor(anchor, "tick_ms"))
                ticks = max(1, row.duration_ms // tick_ms) if row.duration_ms > 0 else 1
                actual_total = EffectRange(effect.minimum * ticks, effect.maximum * ticks)
                expected_total = range_at_anchor(anchor, "dot_total")
                if actual_total != expected_total:
                    raise ValidateError(
                        f"{spell_id} level {level} native DoT anchor: expected total "
                        f"{expected_total.minimum}-{expected_total.maximum}, got "
                        f"{actual_total.minimum}-{actual_total.maximum}"
                    )
                periodic_anchor_count += 1

        # Intermediate levels can require integer per-tick quantization. Report
        # the maximum distance from the linear semantic total; anchor levels
        # above already require exact equality.
        if periodic_index is not None:
            semantic_by_level = {
                int(anchor["level"]): anchor
                for anchor in anchors
                if isinstance(anchor, dict) and "dot_total" in anchor
            }
            ordered = sorted(semantic_by_level)
            for level in range(1, max_level + 1):
                row = levels[level]
                effect = row.effects[periodic_index]
                if effect is None or row.duration_ms <= 0:
                    continue
                left_level = max((value for value in ordered if value <= level), default=ordered[0])
                right_level = min((value for value in ordered if value >= level), default=ordered[-1])
                left = range_at_anchor(semantic_by_level[left_level], "dot_total")
                right = range_at_anchor(semantic_by_level[right_level], "dot_total")
                if right_level == left_level:
                    desired = left
                else:
                    t = (level - left_level) / (right_level - left_level)
                    desired = EffectRange(
                        int(left.minimum + (right.minimum - left.minimum) * t + 0.5),
                        int(left.maximum + (right.maximum - left.maximum) * t + 0.5),
                    )
                tick_anchor = semantic_by_level[left_level]
                tick_ms = max(1, int(tick_anchor.get("tick_ms", 1)))
                ticks = max(1, row.duration_ms // tick_ms)
                actual_min = effect.minimum * ticks
                actual_max = effect.maximum * ticks
                max_periodic_drift = max(
                    max_periodic_drift,
                    abs(actual_min - desired.minimum),
                    abs(actual_max - desired.maximum),
                )

    extra_runtime = sorted(set(runtime) - profile_ids)
    if extra_runtime:
        raise ValidateError(
            "runtime TSV contains custom spells without profiles: "
            + ", ".join(str(value) for value in extra_runtime[:10])
        )
    return anchor_count, periodic_anchor_count, max_periodic_drift


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", required=True, type=Path)
    parser.add_argument("--scaling", required=True, type=Path)
    parser.add_argument("--dbc-dir", required=True, type=Path)
    args = parser.parse_args()

    try:
        profiles = load_json(args.profiles.expanduser().resolve())
        runtime = load_runtime(args.scaling.expanduser().resolve())
        rows = dbc_rows(args.dbc_dir.expanduser().resolve() / "Spell.dbc")
        anchors, periodic_anchors, drift = validate_profiles(profiles, runtime, rows)
    except (KeyError, TypeError, ValueError, ValidateError) as exc:
        raise SystemExit(f"Profiled spell validation aborted: {exc}") from exc

    print("Profile-aware custom spell scaling validated:")
    print(f"  native anchors checked: {anchors}")
    print(f"  periodic native anchors exact: {periodic_anchors}")
    print("  runtime TSV v2: complete levels for every profile")
    print("  Spell.dbc fallback casts: native rank-1/root")
    print(f"  max intermediate DoT integer-quantization drift: {drift} base damage")
    if drift:
        print("  note: tooltip/client validation must use represented runtime DoT totals")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Validate profile-aware native anchors against the generated runtime TSV.

The profile registry and TSV are generated independently enough that this tool
can catch semantic/runtime drift before the server is built or started.

Periodic damage is authoritative PER TICK. Every native rank anchor must
round-trip exactly, and every intermediate runtime row must equal the same
integer per-tick interpolation used by the profile model. Tooltip totals are
therefore always derivable exactly as runtime_tick * runtime_tick_count.
"""

from __future__ import annotations

import argparse
import json
import math
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


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValidateError(f"profile registry not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValidateError(f"invalid profile registry {path}: {exc}") from exc
    if not isinstance(data, dict) or int(data.get("version", 0)) != 2:
        raise ValidateError(f"{path}: expected profile registry version 2")
    if data.get("periodic_model") != "per_tick_integer_interpolation":
        raise ValidateError(f"{path}: unexpected or missing periodic_model")
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

        if not 200000 <= spell_id <= 299999 or level <= 0 or cast_ms < 0 or duration_ms < 0:
            raise ValidateError(f"{path}:{line_number}: invalid spell/level/cast/duration")
        levels = result.setdefault(spell_id, {})
        if level in levels:
            raise ValidateError(f"{path}:{line_number}: duplicate {spell_id}:{level}")
        levels[level] = RuntimeRow(
            cast_ms,
            duration_ms,
            (effects[0], effects[1], effects[2]),
        )
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


def signed_scaled(value: int, ratio: float) -> int:
    if value == 0:
        return 0
    magnitude = max(1, int(math.floor(abs(value) * ratio + 0.5)))
    return magnitude if value > 0 else -magnitude


def linear_int(left: int, right: int, t: float) -> int:
    value = left + (right - left) * t
    if value >= 0:
        return int(math.floor(value + 0.5))
    return -int(math.floor(abs(value) + 0.5))


def interpolated_range(
    raw_anchors: list[tuple[int, EffectRange]],
    level: int,
    low_level_offset: float,
) -> EffectRange:
    points = list(sorted(raw_anchors))
    if not points:
        raise ValidateError("cannot interpolate an empty range")

    first_level, first = points[0]
    if first_level > 1:
        ratio = (1.0 + low_level_offset) / (first_level + low_level_offset)
        points.insert(
            0,
            (
                1,
                EffectRange(
                    signed_scaled(first.minimum, ratio),
                    signed_scaled(first.maximum, ratio),
                ),
            ),
        )

    if level <= points[0][0]:
        return points[0][1]
    if level >= points[-1][0]:
        return points[-1][1]

    for index in range(len(points) - 1):
        left_level, left = points[index]
        right_level, right = points[index + 1]
        if left_level <= level <= right_level:
            t = (level - left_level) / (right_level - left_level)
            minimum = linear_int(left.minimum, right.minimum, t)
            maximum = linear_int(left.maximum, right.maximum, t)
            return EffectRange(min(minimum, maximum), max(minimum, maximum))
    raise ValidateError(f"failed to interpolate range at level {level}")


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
    low_level_offset = float(profiles.get("low_level_offset", 0.0))
    spells = profiles.get("spells")
    if max_level <= 0 or not isinstance(spells, list) or not spells:
        raise ValidateError("profile registry has invalid runtime_max_level/spells")

    anchor_count = 0
    periodic_anchor_count = 0
    periodic_runtime_levels = 0
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

            if periodic_index is not None and "dot_tick" in anchor:
                expected_tick = range_at_anchor(anchor, "dot_tick")
                validate_anchor_effect(
                    spell_id,
                    level,
                    periodic_index,
                    expected_tick,
                    row,
                    "periodic tick",
                )
                tick_ms = max(1, scalar_at_anchor(anchor, "tick_ms"))
                ticks = max(1, row.duration_ms // tick_ms) if row.duration_ms > 0 else 1
                expected_total = range_at_anchor(anchor, "dot_total")
                actual_total = EffectRange(
                    expected_tick.minimum * ticks,
                    expected_tick.maximum * ticks,
                )
                if actual_total != expected_total:
                    raise ValidateError(
                        f"{spell_id} level {level} native DoT total: expected "
                        f"{expected_total.minimum}-{expected_total.maximum}, got "
                        f"{actual_total.minimum}-{actual_total.maximum}"
                    )
                periodic_anchor_count += 1

        if periodic_index is not None:
            tick_anchors: list[tuple[int, EffectRange]] = []
            for anchor in anchors:
                if not isinstance(anchor, dict) or "dot_tick" not in anchor:
                    continue
                tick_anchors.append(
                    (int(anchor["level"]), range_at_anchor(anchor, "dot_tick"))
                )
            if not tick_anchors:
                raise ValidateError(f"profile {spell_id} has periodic effect but no dot_tick anchors")

            for level in range(1, max_level + 1):
                expected = interpolated_range(
                    tick_anchors,
                    level,
                    low_level_offset,
                )
                actual = levels[level].effects[periodic_index]
                if actual != expected:
                    raise ValidateError(
                        f"{spell_id} level {level} periodic runtime drift: expected "
                        f"{expected.minimum}-{expected.maximum}, got "
                        f"{actual.minimum if actual else 'x'}-{actual.maximum if actual else 'x'}"
                    )
                periodic_runtime_levels += 1

    extra_runtime = sorted(set(runtime) - profile_ids)
    if extra_runtime:
        raise ValidateError(
            "runtime TSV contains custom spells without profiles: "
            + ", ".join(str(value) for value in extra_runtime[:10])
        )
    return anchor_count, periodic_anchor_count, periodic_runtime_levels


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
        anchors, periodic_anchors, periodic_levels = validate_profiles(
            profiles, runtime, rows
        )
    except (KeyError, TypeError, ValueError, ValidateError) as exc:
        raise SystemExit(f"Profiled spell validation aborted: {exc}") from exc

    print("Profile-aware custom spell scaling validated:")
    print(f"  native anchors checked: {anchors}")
    print(f"  periodic native anchors exact: {periodic_anchors}")
    print(f"  periodic runtime levels checked exactly: {periodic_levels}")
    print("  periodic model: integer per-tick interpolation; total = tick x tick count")
    print("  runtime TSV v2: complete levels for every profile")
    print("  Spell.dbc fallback casts: native rank-1/root")
    print("  intermediate DoT runtime/tooltip representability drift: 0 by construction")


if __name__ == "__main__":
    main()

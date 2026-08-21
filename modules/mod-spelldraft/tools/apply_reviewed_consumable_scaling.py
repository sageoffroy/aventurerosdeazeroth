#!/usr/bin/env python3
"""Apply reviewed level-scaling to internal consumable helper spells.

This stage does not introduce a second runtime scaling system. It creates
internal 200000+native helper clones, rewires the reviewed item-use wrapper to
those clones, and appends their per-level rows to the same canonical
custom_spell_scaling.tsv consumed by CustomSpellScaling.cpp.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
from pathlib import Path

from patch_adventurer_class_dbcs import DBCError, read_dbc, set_u32, u32, write_dbc

TOOLS_DIR = Path(__file__).resolve().parent
DEFAULT_MUTATIONS = TOOLS_DIR.parent / "reviewed_spell_mutations.json"

SPELL_FIELDS = 234
SPELL_RECORD_SIZE = 936
SPELL_ID = 0
MAX_LEVEL = 37
BASE_LEVEL = 38
SPELL_LEVEL = 39
EFFECT_DIE_SIDES = 74
EFFECT_REAL_POINTS_PER_LEVEL = 77
EFFECT_BASE_POINTS = 80
EFFECT_TRIGGER_SPELL_FIELDS = tuple(range(116, 119))


class ConsumableScalingError(RuntimeError):
    pass


def i32(row: bytes | bytearray, field: int) -> int:
    return struct.unpack_from("<i", row, field * 4)[0]


def set_i32(row: bytearray, field: int, value: int) -> None:
    struct.pack_into("<i", row, field * 4, int(value))


def set_f32(row: bytearray, field: int, value: float) -> None:
    struct.pack_into("<f", row, field * 4, float(value))


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConsumableScalingError(f"cannot read {path}: {exc}") from exc


def load_specs(path: Path) -> list[dict]:
    raw = load_json(path)
    mutations = raw.get("mutations")
    if raw.get("schema_version") != 1 or not isinstance(mutations, list):
        raise ConsumableScalingError(f"{path}: expected schema_version=1 and mutations[]")

    specs: list[dict] = []
    seen_runtime: set[int] = set()
    for mutation in mutations:
        if not isinstance(mutation, dict):
            continue
        spec = mutation.get("consumable_scaling")
        if spec is None:
            continue
        if not isinstance(spec, dict):
            raise ConsumableScalingError("consumable_scaling must be an object")

        owner = int(mutation.get("native_root", 0))
        wrapper = spec.get("wrapper_spell_id")
        duration = spec.get("duration_ms")
        max_level = spec.get("runtime_max_level")
        helpers = spec.get("helpers")
        if not isinstance(wrapper, int) or wrapper <= 0:
            raise ConsumableScalingError(f"mutation {owner}: invalid wrapper_spell_id")
        if not isinstance(duration, int) or duration <= 0:
            raise ConsumableScalingError(f"mutation {owner}: invalid duration_ms")
        if not isinstance(max_level, int) or not 1 <= max_level <= 255:
            raise ConsumableScalingError(f"mutation {owner}: invalid runtime_max_level")
        if not isinstance(helpers, list) or not helpers:
            raise ConsumableScalingError(f"mutation {owner}: helpers[] is required")

        normalized_helpers: list[dict] = []
        for helper in helpers:
            if not isinstance(helper, dict):
                raise ConsumableScalingError(f"mutation {owner}: helper must be an object")
            native_id = helper.get("native_spell_id")
            runtime_id = helper.get("runtime_spell_id")
            effect_index = helper.get("effect_index")
            anchors = helper.get("anchors")
            if not isinstance(native_id, int) or native_id <= 0:
                raise ConsumableScalingError(f"mutation {owner}: invalid native helper ID")
            if (
                not isinstance(runtime_id, int)
                or not 200000 <= runtime_id <= 299999
                or runtime_id != 200000 + native_id
            ):
                raise ConsumableScalingError(
                    f"mutation {owner}: runtime helper must be deterministic 200000+native"
                )
            if runtime_id in seen_runtime:
                raise ConsumableScalingError(f"duplicate runtime helper {runtime_id}")
            if not isinstance(effect_index, int) or effect_index not in (0, 1, 2):
                raise ConsumableScalingError(f"mutation {owner}: invalid helper effect_index")
            if not isinstance(anchors, list) or len(anchors) < 2:
                raise ConsumableScalingError(f"mutation {owner}: helper needs at least two anchors")

            cleaned: list[tuple[int, int]] = []
            seen_levels: set[int] = set()
            for anchor in anchors:
                if not isinstance(anchor, dict):
                    raise ConsumableScalingError(f"mutation {owner}: invalid anchor")
                level = anchor.get("level")
                amount = anchor.get("amount")
                if not isinstance(level, int) or not 1 <= level <= max_level:
                    raise ConsumableScalingError(f"mutation {owner}: invalid anchor level")
                if not isinstance(amount, int) or amount < 0:
                    raise ConsumableScalingError(f"mutation {owner}: invalid anchor amount")
                if level in seen_levels:
                    raise ConsumableScalingError(f"mutation {owner}: duplicate anchor level {level}")
                seen_levels.add(level)
                cleaned.append((level, amount))
            cleaned.sort()
            if cleaned[0][0] != 1 or cleaned[-1][0] != max_level:
                raise ConsumableScalingError(
                    f"mutation {owner}: helper anchors must include level 1 and {max_level}"
                )

            normalized_helpers.append(
                {
                    "native_spell_id": native_id,
                    "runtime_spell_id": runtime_id,
                    "effect_index": effect_index,
                    "anchors": cleaned,
                }
            )
            seen_runtime.add(runtime_id)

        specs.append(
            {
                "owner": owner,
                "wrapper_spell_id": wrapper,
                "duration_ms": duration,
                "runtime_max_level": max_level,
                "helpers": normalized_helpers,
            }
        )
    return specs


def linear_int(a: int, b: int, t: float) -> int:
    value = a + (b - a) * t
    if value >= 0:
        return int(math.floor(value + 0.5))
    return -int(math.floor(abs(value) + 0.5))


def interpolate(anchors: list[tuple[int, int]], max_level: int) -> list[int]:
    result: list[int] = []
    for level in range(1, max_level + 1):
        if level <= anchors[0][0]:
            result.append(anchors[0][1])
            continue
        if level >= anchors[-1][0]:
            result.append(anchors[-1][1])
            continue

        value = anchors[-1][1]
        for index in range(len(anchors) - 1):
            left_level, left_value = anchors[index]
            right_level, right_value = anchors[index + 1]
            if left_level <= level <= right_level:
                span = right_level - left_level
                t = 0.0 if span == 0 else (level - left_level) / span
                value = linear_int(left_value, right_value, t)
                break
        result.append(value)
    return result


def patch_spell_dbc(path: Path, specs: list[dict]) -> dict[int, list[int]]:
    fields, record_size, records, strings, trailing = read_dbc(path)
    if fields != SPELL_FIELDS or record_size != SPELL_RECORD_SIZE:
        raise ConsumableScalingError(f"unexpected Spell.dbc layout: {fields}/{record_size}")

    runtime_ids = {
        int(helper["runtime_spell_id"])
        for spec in specs
        for helper in spec["helpers"]
    }
    records = [row for row in records if u32(row, SPELL_ID) not in runtime_ids]
    by_id = {u32(row, SPELL_ID): row for row in records}
    level_values: dict[int, list[int]] = {}

    for spec in specs:
        wrapper_id = int(spec["wrapper_spell_id"])
        wrapper = by_id.get(wrapper_id)
        if wrapper is None:
            raise ConsumableScalingError(
                f"mutation {spec['owner']}: wrapper spell {wrapper_id} is missing"
            )

        for helper in spec["helpers"]:
            native_id = int(helper["native_spell_id"])
            runtime_id = int(helper["runtime_spell_id"])
            effect_index = int(helper["effect_index"])
            source = by_id.get(native_id)
            if source is None:
                raise ConsumableScalingError(
                    f"mutation {spec['owner']}: native helper {native_id} is missing"
                )

            values = interpolate(helper["anchors"], int(spec["runtime_max_level"]))
            level_values[runtime_id] = values

            clone = bytearray(source)
            set_u32(clone, SPELL_ID, runtime_id)
            set_u32(clone, MAX_LEVEL, int(spec["runtime_max_level"]))
            set_u32(clone, BASE_LEVEL, 1)
            set_u32(clone, SPELL_LEVEL, 1)
            set_i32(clone, EFFECT_DIE_SIDES + effect_index, 0)
            set_f32(clone, EFFECT_REAL_POINTS_PER_LEVEL + effect_index, 0.0)
            set_i32(clone, EFFECT_BASE_POINTS + effect_index, values[0])
            records.append(clone)
            by_id[runtime_id] = clone

            touched = 0
            for field in EFFECT_TRIGGER_SPELL_FIELDS:
                current = u32(wrapper, field)
                if current == native_id:
                    set_u32(wrapper, field, runtime_id)
                    touched += 1
                elif current == runtime_id:
                    touched += 1
            if touched == 0:
                raise ConsumableScalingError(
                    f"mutation {spec['owner']}: wrapper {wrapper_id} does not reference helper {native_id}"
                )

    records.sort(key=lambda row: u32(row, SPELL_ID))
    write_dbc(path, fields, record_size, records, strings, trailing)

    _, _, verify_rows, _, _ = read_dbc(path)
    verify = {u32(row, SPELL_ID): row for row in verify_rows}
    for spec in specs:
        wrapper = verify[int(spec["wrapper_spell_id"])]
        trigger_values = [u32(wrapper, field) for field in EFFECT_TRIGGER_SPELL_FIELDS]
        for helper in spec["helpers"]:
            native_id = int(helper["native_spell_id"])
            runtime_id = int(helper["runtime_spell_id"])
            effect_index = int(helper["effect_index"])
            clone = verify.get(runtime_id)
            if clone is None:
                raise ConsumableScalingError(f"runtime helper {runtime_id} was not written")
            if native_id in trigger_values or runtime_id not in trigger_values:
                raise ConsumableScalingError(
                    f"wrapper remap {native_id}->{runtime_id} failed validation"
                )
            if i32(clone, EFFECT_BASE_POINTS + effect_index) != level_values[runtime_id][0]:
                raise ConsumableScalingError(
                    f"runtime helper {runtime_id} level-1 base amount failed validation"
                )
    return level_values


def patch_scaling_table(
    path: Path,
    specs: list[dict],
    level_values: dict[int, list[int]],
) -> int:
    if not path.is_file():
        raise ConsumableScalingError(f"runtime scaling table not found: {path}")

    runtime_ids = set(level_values)
    output: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line or raw_line.startswith("#"):
            output.append(raw_line)
            continue
        tokens = raw_line.split()
        if len(tokens) != 10:
            raise ConsumableScalingError(
                f"runtime scaling table has malformed row with {len(tokens)} fields: {raw_line}"
            )
        try:
            spell_id = int(tokens[0])
        except ValueError as exc:
            raise ConsumableScalingError(f"invalid spell ID in scaling row: {raw_line}") from exc
        if spell_id not in runtime_ids:
            output.append(raw_line)

    rows_added = 0
    for spec in specs:
        duration_ms = int(spec["duration_ms"])
        max_level = int(spec["runtime_max_level"])
        for helper in spec["helpers"]:
            runtime_id = int(helper["runtime_spell_id"])
            effect_index = int(helper["effect_index"])
            values = level_values[runtime_id]
            for level in range(1, max_level + 1):
                fields = [str(runtime_id), str(level), "0", str(duration_ms)]
                for index in range(3):
                    if index == effect_index:
                        amount = values[level - 1]
                        fields.extend([str(amount), str(amount)])
                    else:
                        fields.extend(["x", "x"])
                output.append(" ".join(fields))
                rows_added += 1

    path.write_text("\n".join(output) + "\n", encoding="utf-8")

    seen: dict[int, int] = {runtime_id: 0 for runtime_id in runtime_ids}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line or raw_line.startswith("#"):
            continue
        tokens = raw_line.split()
        spell_id = int(tokens[0])
        if spell_id in seen:
            seen[spell_id] += 1
    expected_by_id = {
        int(helper["runtime_spell_id"]): int(spec["runtime_max_level"])
        for spec in specs
        for helper in spec["helpers"]
    }
    bad = [
        f"{spell_id}:{seen[spell_id]}/{expected}"
        for spell_id, expected in expected_by_id.items()
        if seen[spell_id] != expected
    ]
    if bad:
        raise ConsumableScalingError(
            "consumable helper scaling row validation failed: " + ", ".join(bad)
        )
    return rows_added


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dbc-dir", required=True, type=Path)
    parser.add_argument("--scaling", required=True, type=Path)
    parser.add_argument("--mutations", type=Path, default=DEFAULT_MUTATIONS)
    args = parser.parse_args()

    try:
        specs = load_specs(args.mutations.expanduser().resolve())
        if not specs:
            print("Reviewed consumable scaling: no configured consumables.")
            return
        values = patch_spell_dbc(
            args.dbc_dir.expanduser().resolve() / "Spell.dbc",
            specs,
        )
        rows = patch_scaling_table(args.scaling.expanduser().resolve(), specs, values)
    except (DBCError, ConsumableScalingError, KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"Reviewed consumable scaling aborted: {exc}") from exc

    print("Reviewed consumable scaling applied and validated:")
    for spec in specs:
        helper_text = ", ".join(
            f"{helper['native_spell_id']}->{helper['runtime_spell_id']}"
            for helper in spec["helpers"]
        )
        print(
            f"  owner={spec['owner']} wrapper={spec['wrapper_spell_id']} "
            f"helpers={helper_text} levels=1-{spec['runtime_max_level']} duration={spec['duration_ms']}ms"
        )
    print(f"  canonical runtime scaling rows added: {rows}")


if __name__ == "__main__":
    main()

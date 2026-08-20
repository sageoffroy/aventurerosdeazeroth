#!/usr/bin/env python3
"""Apply reviewed one-off SpellDraft behavior mutations after normalization.

This stage is intentionally narrow: it mutates already-generated runtime spell
rows without creating a second scaling system. Numeric scaling fields remain
owned by the normalizer; this tool only copies reviewed structural behavior
(such as group targeting/duration) from a native reference spell and, when a
reviewed design explicitly requires it, updates the duration column of the
canonical runtime scaling table for that normalized spell.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from patch_adventurer_class_dbcs import (
    DBCError,
    append_string,
    read_dbc,
    set_u32,
    u32,
    write_dbc,
)

TOOLS_DIR = Path(__file__).resolve().parent
DEFAULT_MUTATIONS = TOOLS_DIR.parent / "reviewed_spell_mutations.json"

SPELL_FIELDS = 234
SPELL_RECORD_SIZE = 936
SPELL_ID = 0
TARGETS = 16
DURATION_INDEX = 40
RANGE_INDEX = 46
ITEM_REQUIREMENT_FIELDS = tuple(range(50, 68))
EFFECT_TYPE_FIELDS = tuple(range(71, 74))
AMOUNT_FIELDS = tuple(range(74, 83))
EFFECT_BEHAVIOR_FIELDS = tuple(range(83, 131))
NAME_FIELDS = tuple(range(136, 152))
DESCRIPTION_FIELDS = tuple(range(170, 186))
TOOLTIP_FIELDS = tuple(range(187, 203))
MAX_AFFECTED_TARGETS = 212

# These fields describe how an effect selects/applies to targets, but deliberately
# exclude BasePoints/DieSides/RealPointsPerLevel (74-82), which remain controlled
# by the canonical normalization/scaling pipeline.
GROUP_BEHAVIOR_FIELDS = (
    TARGETS,
    RANGE_INDEX,
    *EFFECT_TYPE_FIELDS,
    *EFFECT_BEHAVIOR_FIELDS,
    MAX_AFFECTED_TARGETS,
)


class MutationError(RuntimeError):
    pass


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MutationError(f"cannot read {path}: {exc}") from exc


def load_replacements(path: Path) -> dict[int, int]:
    raw = load_json(path)
    result: dict[int, int] = {}
    for spell in raw.get("spells", []):
        result[int(spell["clone_from"])] = int(spell["id"])
    return result


def validate_positive_spell_list(owner: int, field: str, values: object) -> list[int]:
    if not isinstance(values, list) or any(
        isinstance(value, bool) or not isinstance(value, int) or value <= 0
        for value in values
    ):
        raise MutationError(f"mutation {owner}: invalid {field}")
    return list(dict.fromkeys(values))


def load_mutations(path: Path) -> list[dict]:
    raw = load_json(path)
    if raw.get("schema_version") != 1 or not isinstance(raw.get("mutations"), list):
        raise MutationError(f"{path}: expected schema_version=1 and mutations[]")

    result: list[dict] = []
    seen: set[int] = set()
    for mutation in raw["mutations"]:
        if not isinstance(mutation, dict):
            raise MutationError(f"{path}: every mutation must be an object")
        native_root = mutation.get("native_root")
        if isinstance(native_root, bool) or not isinstance(native_root, int) or native_root <= 0:
            raise MutationError(f"{path}: invalid native_root {native_root!r}")
        if native_root in seen:
            raise MutationError(f"{path}: duplicate mutation for native root {native_root}")

        source = mutation.get("behavior_source_spell_id")
        if isinstance(source, bool) or not isinstance(source, int) or source <= 0:
            raise MutationError(
                f"mutation {native_root}: behavior_source_spell_id must be a positive spell ID"
            )

        normalized = dict(mutation)
        normalized["copy_group_behavior"] = bool(mutation.get("copy_group_behavior", False))
        normalized["copy_duration"] = bool(mutation.get("copy_duration", False))
        normalized["clear_item_requirements"] = bool(
            mutation.get("clear_item_requirements", False)
        )
        normalized["exclude_from_pool"] = validate_positive_spell_list(
            native_root,
            "exclude_from_pool",
            mutation.get("exclude_from_pool", []),
        )

        fixed_runtime_duration = mutation.get("fixed_runtime_duration_ms")
        if fixed_runtime_duration is not None:
            if (
                isinstance(fixed_runtime_duration, bool)
                or not isinstance(fixed_runtime_duration, int)
                or fixed_runtime_duration <= 0
            ):
                raise MutationError(
                    f"mutation {native_root}: fixed_runtime_duration_ms must be a positive integer"
                )
        normalized["fixed_runtime_duration_ms"] = fixed_runtime_duration

        if not (
            normalized["copy_group_behavior"]
            or normalized["copy_duration"]
            or normalized["clear_item_requirements"]
            or normalized.get("description")
            or normalized["exclude_from_pool"]
            or normalized["fixed_runtime_duration_ms"] is not None
        ):
            raise MutationError(f"mutation {native_root}: no mutation action configured")
        result.append(normalized)
        seen.add(native_root)
    return result


def clear_item_requirements(row: bytearray) -> None:
    for field in ITEM_REQUIREMENT_FIELDS:
        set_u32(row, field, 0)


def set_text(
    row: bytearray,
    fields: tuple[int, ...],
    strings: bytearray,
    value: str,
) -> None:
    offset = append_string(strings, value)
    for field in fields:
        set_u32(row, field, offset)


def patch_spell_dbc(
    path: Path,
    mutations: list[dict],
    replacements: dict[int, int],
) -> dict[int, int]:
    fields, record_size, records, strings, trailing = read_dbc(path)
    if fields != SPELL_FIELDS or record_size != SPELL_RECORD_SIZE:
        raise MutationError(f"unexpected Spell.dbc layout: {fields}/{record_size}")

    by_id = {u32(row, SPELL_ID): row for row in records}
    runtime_ids: dict[int, int] = {}

    for mutation in mutations:
        native_root = int(mutation["native_root"])
        runtime_id = replacements.get(native_root, native_root)
        source_id = int(mutation["behavior_source_spell_id"])
        target = by_id.get(runtime_id)
        source = by_id.get(source_id)
        if target is None:
            raise MutationError(
                f"mutation {native_root}: runtime spell {runtime_id} is missing from Spell.dbc"
            )
        if source is None:
            raise MutationError(
                f"mutation {native_root}: behavior source {source_id} is missing from Spell.dbc"
            )

        original_amounts = tuple(u32(target, field) for field in AMOUNT_FIELDS)

        if mutation["copy_group_behavior"]:
            for field in GROUP_BEHAVIOR_FIELDS:
                set_u32(target, field, u32(source, field))
        if mutation["copy_duration"]:
            # DBC stores a SpellDuration row index, not milliseconds. Copying the
            # source index keeps client tooltip/presentation aligned with the
            # chosen native behavior source.
            set_u32(target, DURATION_INDEX, u32(source, DURATION_INDEX))
        if mutation["clear_item_requirements"]:
            clear_item_requirements(target)
        description = mutation.get("description")
        if description:
            set_text(target, DESCRIPTION_FIELDS, strings, str(description))
            set_text(target, TOOLTIP_FIELDS, strings, str(description))

        # The mutation may alter targeting/effect kinds but never numeric scaling.
        if tuple(u32(target, field) for field in AMOUNT_FIELDS) != original_amounts:
            raise MutationError(
                f"mutation {native_root}: normalized amount/scaling fields changed unexpectedly"
            )
        runtime_ids[native_root] = runtime_id

    records.sort(key=lambda row: u32(row, SPELL_ID))
    write_dbc(path, fields, record_size, records, strings, trailing)

    _, _, verify_rows, _, _ = read_dbc(path)
    verify = {u32(row, SPELL_ID): row for row in verify_rows}
    for mutation in mutations:
        native_root = int(mutation["native_root"])
        runtime_id = runtime_ids[native_root]
        source_id = int(mutation["behavior_source_spell_id"])
        target = verify[runtime_id]
        source = verify[source_id]
        if mutation["copy_group_behavior"]:
            mismatched = [
                field for field in GROUP_BEHAVIOR_FIELDS
                if u32(target, field) != u32(source, field)
            ]
            if mismatched:
                raise MutationError(
                    f"mutation {native_root}: group behavior fields failed validation: {mismatched}"
                )
        if mutation["copy_duration"] and u32(target, DURATION_INDEX) != u32(source, DURATION_INDEX):
            raise MutationError(f"mutation {native_root}: duration failed validation")
        if mutation["clear_item_requirements"] and any(
            u32(target, field) != 0 for field in ITEM_REQUIREMENT_FIELDS
        ):
            raise MutationError(f"mutation {native_root}: item requirement survived")

    return runtime_ids


def patch_runtime_scaling_duration(
    path: Path,
    mutations: list[dict],
    runtime_ids: dict[int, int],
) -> dict[int, int]:
    """Patch only the duration column of canonical normalized scaling rows.

    CustomSpellScaling.cpp reapplies duration_ms from this table at cast time.
    Therefore changing only Spell.dbc is insufficient for a normalized spell
    whose original family had another duration.
    """
    if not path.is_file():
        raise MutationError(f"runtime scaling table not found: {path}")

    fixed_by_runtime: dict[int, int] = {}
    for mutation in mutations:
        duration_ms = mutation.get("fixed_runtime_duration_ms")
        if duration_ms is None:
            continue
        native_root = int(mutation["native_root"])
        runtime_id = runtime_ids[native_root]
        if not 200000 <= runtime_id <= 299999:
            raise MutationError(
                f"mutation {native_root}: fixed runtime duration requires a normalized custom spell, got {runtime_id}"
            )
        fixed_by_runtime[runtime_id] = int(duration_ms)

    if not fixed_by_runtime:
        return {}

    seen_rows: dict[int, int] = {spell_id: 0 for spell_id in fixed_by_runtime}
    output: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line or raw_line.startswith("#"):
            output.append(raw_line)
            continue

        tokens = raw_line.split()
        if len(tokens) != 10:
            raise MutationError(
                f"runtime scaling table has malformed row with {len(tokens)} fields: {raw_line}"
            )
        try:
            spell_id = int(tokens[0])
            int(tokens[1])
            int(tokens[2])
            int(tokens[3])
        except ValueError as exc:
            raise MutationError(f"runtime scaling table has non-integer header fields: {raw_line}") from exc

        if spell_id in fixed_by_runtime:
            tokens[3] = str(fixed_by_runtime[spell_id])
            seen_rows[spell_id] += 1
        output.append(" ".join(tokens))

    missing = [spell_id for spell_id, count in seen_rows.items() if count == 0]
    if missing:
        raise MutationError(
            "fixed-duration mutation IDs missing from runtime scaling table: "
            + ", ".join(str(value) for value in sorted(missing))
        )

    path.write_text("\n".join(output) + "\n", encoding="utf-8")

    # Validate every row for each patched spell now carries the requested value.
    bad: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line or raw_line.startswith("#"):
            continue
        tokens = raw_line.split()
        spell_id = int(tokens[0])
        if spell_id in fixed_by_runtime and int(tokens[3]) != fixed_by_runtime[spell_id]:
            bad.append(f"{spell_id}:{tokens[1]}={tokens[3]}")
    if bad:
        raise MutationError(
            "fixed runtime duration failed validation: " + ", ".join(bad[:10])
        )

    return seen_rows


def runtime_ids_for_native(native_ids: set[int], replacements: dict[int, int]) -> set[int]:
    result = set(native_ids)
    result.update(replacements[value] for value in native_ids if value in replacements)
    return result


def patch_catalog(
    path: Path,
    mutations: list[dict],
    replacements: dict[int, int],
) -> int:
    lines = path.read_text(encoding="utf-8").splitlines()
    native_remove: set[int] = set()
    for mutation in mutations:
        native_remove.update(int(value) for value in mutation["exclude_from_pool"])
    remove_ids = runtime_ids_for_native(native_remove, replacements)

    in_catalog = False
    removed = 0
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == "SpellDraftCatalog = {":
            in_catalog = True
            output.append(line)
            continue
        if in_catalog and stripped == "}":
            in_catalog = False
            output.append(line)
            continue
        if in_catalog:
            match = re.match(r"^\s*\{ id = (\d+),", line)
            if match and int(match.group(1)) in remove_ids:
                removed += 1
                continue
        output.append(line)

    path.write_text("\n".join(output) + "\n", encoding="utf-8")
    final = path.read_text(encoding="utf-8")
    final_ids = {
        int(value)
        for value in re.findall(r"^\s*\{ id = (\d+),", final, re.MULTILINE)
    }
    leftover = sorted(remove_ids & final_ids)
    if leftover:
        raise MutationError(
            "reviewed mutation exclusions survived catalog patch: "
            + ", ".join(str(value) for value in leftover)
        )
    return removed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dbc-dir", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--resolved", required=True, type=Path)
    parser.add_argument("--scaling", required=True, type=Path)
    parser.add_argument("--mutations", type=Path, default=DEFAULT_MUTATIONS)
    args = parser.parse_args()

    try:
        mutations = load_mutations(args.mutations.expanduser().resolve())
        replacements = load_replacements(args.resolved.expanduser().resolve())
        runtime_ids = patch_spell_dbc(
            args.dbc_dir.expanduser().resolve() / "Spell.dbc",
            mutations,
            replacements,
        )
        duration_rows = patch_runtime_scaling_duration(
            args.scaling.expanduser().resolve(),
            mutations,
            runtime_ids,
        )
        removed = patch_catalog(
            args.catalog.expanduser().resolve(),
            mutations,
            replacements,
        )
    except (DBCError, MutationError, KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"Reviewed SpellDraft mutation application aborted: {exc}") from exc

    print("Reviewed SpellDraft mutations applied and validated:")
    for mutation in mutations:
        native_root = int(mutation["native_root"])
        runtime_id = runtime_ids[native_root]
        fixed = mutation.get("fixed_runtime_duration_ms")
        print(
            f"  {native_root} -> {runtime_id} {mutation.get('name', '')}: "
            f"behavior_source={mutation['behavior_source_spell_id']}, "
            f"group={mutation['copy_group_behavior']}, duration_source={mutation['copy_duration']}, "
            f"fixed_runtime_duration_ms={fixed}, scaling_rows={duration_rows.get(runtime_id, 0)}"
        )
    print(f"  superseded standalone draft cards removed: {removed}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Normalize reviewed internal trigger helpers into the canonical runtime pipeline.

Some draftable abilities are wrappers/channels whose real numeric effect lives in
another ranked spell family. The normalizer intentionally selects draft cards,
so such internal helper families may not have their own 200000+ clone.

This stage closes that gap without introducing another runtime scaling engine:
for every helper referenced by reviewed_spell_mutations.json through
normalize_trigger_spells that is still missing from custom_spells.resolved.json,
it builds a deterministic 200000+native helper from the canonical spell_ranks
family, appends its 1-80 rules to custom_spell_scaling.tsv, records the same
semantic profile used by the tooltip pipeline, and exposes the replacement in
the resolved registry. apply_reviewed_spell_mutations.py then performs the
actual parent -> helper trigger remap in its existing reviewed mutation stage.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from generate_normalized_spells import (
    BASE_LEVEL,
    EFFECT_BASE_POINTS,
    EFFECT_DIE_SIDES,
    EFFECT_REAL_POINTS_PER_LEVEL,
    MAX_LEVEL,
    SPELL_ID,
    SPELL_LEVEL,
    build_effect_curves,
    dbc_records_by_id,
    duration_map,
    rank_samples,
    set_f32,
    set_i32,
)
from generate_profiled_spell_scaling import (
    NativeRank,
    build_profile_runtime,
    detect_profile,
    load_cast_times,
    profile_low_level_offset,
)
from generate_spelldraft_catalog import parse_spell_ranks
from patch_adventurer_class_dbcs import DBCError, set_u32, u32, write_dbc

TOOLS_DIR = Path(__file__).resolve().parent
MODULE = TOOLS_DIR.parent
REPO = MODULE.parents[1]
DEFAULT_MUTATIONS = MODULE / "reviewed_spell_mutations.json"
DEFAULT_REGISTRY = MODULE / "custom_spells.json"
DEFAULT_SPELL_RANKS = REPO / "data/sql/base/db_world/spell_ranks.sql"


class InternalHelperError(RuntimeError):
    pass


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InternalHelperError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise InternalHelperError(f"{label} must be a JSON object: {path}")
    return value


def reviewed_helper_roots(path: Path) -> list[int]:
    data = load_json(path, "reviewed mutations")
    mutations = data.get("mutations")
    if data.get("schema_version") != 1 or not isinstance(mutations, list):
        raise InternalHelperError(f"{path}: expected schema_version=1 and mutations[]")

    result: list[int] = []
    for mutation in mutations:
        if not isinstance(mutation, dict):
            raise InternalHelperError(f"{path}: every mutation must be an object")
        helpers = mutation.get("normalize_trigger_spells", [])
        if not isinstance(helpers, list):
            raise InternalHelperError(
                f"mutation {mutation.get('native_root')}: normalize_trigger_spells must be a list"
            )
        for helper in helpers:
            if isinstance(helper, bool) or not isinstance(helper, int) or helper <= 0:
                raise InternalHelperError(
                    f"mutation {mutation.get('native_root')}: invalid trigger helper {helper!r}"
                )
            if helper not in result:
                result.append(helper)
    return result


def replacement_map(resolved: dict[str, Any]) -> dict[int, int]:
    spells = resolved.get("spells")
    if not isinstance(spells, list):
        raise InternalHelperError("resolved custom spell registry has no spells[]")
    result: dict[int, int] = {}
    for spell in spells:
        if not isinstance(spell, dict):
            raise InternalHelperError("resolved custom spell registry contains a non-object spell")
        result[int(spell["clone_from"])] = int(spell["id"])
    return result


def resolved_effects(curves: list[Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for curve in curves:
        output.append(
            {
                "index": curve.effect_index,
                "effect_type": curve.effect_type,
                "aura_type": curve.aura_type,
                "anchors": [
                    {"level": level, "min": amount.minimum, "max": amount.maximum}
                    for level, amount in curve.anchors
                ],
            }
        )
    return output


def append_scaling_rows(path: Path, runtime_by_id: dict[int, list[Any]]) -> int:
    if not path.is_file():
        raise InternalHelperError(f"runtime scaling table not found: {path}")

    helper_ids = set(runtime_by_id)
    output: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line or raw_line.startswith("#"):
            output.append(raw_line)
            continue
        tokens = raw_line.split()
        if len(tokens) != 10:
            raise InternalHelperError(
                f"runtime scaling table has malformed row with {len(tokens)} fields: {raw_line}"
            )
        if int(tokens[0]) not in helper_ids:
            output.append(raw_line)

    added = 0
    for spell_id in sorted(runtime_by_id):
        for level, rule in enumerate(runtime_by_id[spell_id], 1):
            fields = [str(spell_id), str(level), str(rule.cast_ms), str(rule.duration_ms)]
            for effect in rule.effects:
                if effect is None:
                    fields.extend(["x", "x"])
                else:
                    fields.extend([str(effect.minimum), str(effect.maximum)])
            output.append(" ".join(fields))
            added += 1

    path.write_text("\n".join(output) + "\n", encoding="utf-8")
    return added


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dbc-dir", required=True, type=Path)
    parser.add_argument("--resolved", required=True, type=Path)
    parser.add_argument("--profiles", required=True, type=Path)
    parser.add_argument("--scaling", required=True, type=Path)
    parser.add_argument("--mutations", type=Path, default=DEFAULT_MUTATIONS)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--spell-ranks-sql", type=Path, default=DEFAULT_SPELL_RANKS)
    args = parser.parse_args()

    dbc_dir = args.dbc_dir.expanduser().resolve()
    spell_path = dbc_dir / "Spell.dbc"
    cast_path = dbc_dir / "SpellCastTimes.dbc"
    duration_path = dbc_dir / "SpellDuration.dbc"

    try:
        resolved_path = args.resolved.expanduser().resolve()
        profiles_path = args.profiles.expanduser().resolve()
        scaling_path = args.scaling.expanduser().resolve()
        mutations_path = args.mutations.expanduser().resolve()
        registry = load_json(args.registry.expanduser().resolve(), "custom spell registry")
        resolved = load_json(resolved_path, "resolved custom spell registry")
        profiles = load_json(profiles_path, "resolved custom spell profiles")

        max_level = int(resolved["runtime_max_level"])
        if max_level <= 0:
            raise InternalHelperError("resolved runtime_max_level must be positive")
        low_level_offset = profile_low_level_offset(registry)
        custom_offset = int(registry["custom_id_offset"])
        custom_low, custom_high = [int(value) for value in registry["custom_id_range"]]

        helpers = reviewed_helper_roots(mutations_path)
        replacements = replacement_map(resolved)
        missing_helpers = [helper for helper in helpers if helper not in replacements]
        if not missing_helpers:
            print("Reviewed internal helpers: every trigger helper already has a normalized runtime spell.")
            return

        _root_by_spell, ranks_by_root = parse_spell_ranks(
            args.spell_ranks_sql.expanduser().resolve()
        )
        durations = duration_map(duration_path)
        casts = load_cast_times(cast_path)
        fields, record_size, records, strings, trailing, spell_rows = dbc_records_by_id(spell_path)

        runtime_by_id: dict[int, list[Any]] = {}
        resolved_additions: list[dict[str, Any]] = []
        profile_additions: list[dict[str, Any]] = []
        helper_runtime_ids = {custom_offset + helper for helper in missing_helpers}
        records[:] = [row for row in records if u32(row, SPELL_ID) not in helper_runtime_ids]

        for helper_root in missing_helpers:
            runtime_id = custom_offset + helper_root
            if runtime_id < custom_low or runtime_id > custom_high:
                raise InternalHelperError(
                    f"helper {helper_root} maps to {runtime_id}, outside {custom_low}-{custom_high}"
                )
            source = spell_rows.get(helper_root)
            if source is None:
                raise InternalHelperError(f"trigger helper root {helper_root} is missing from Spell.dbc")

            samples = rank_samples(
                helper_root,
                ranks_by_root.get(helper_root, [(1, helper_root)]),
                spell_rows,
                durations,
            )
            curves = build_effect_curves(samples, max_level, low_level_offset)
            effect_specs = resolved_effects(curves)
            native_ranks = [
                NativeRank(
                    spell_id=sample.spell_id,
                    level=sample.level,
                    row=bytearray(sample.record),
                    cast_ms=casts.get(u32(sample.record, 28), 0),
                    duration_ms=sample.duration_ms,
                )
                for sample in samples
            ]
            profile_name, direct_index, periodic_index = detect_profile(native_ranks)
            runtime, semantic = build_profile_runtime(
                native_ranks,
                direct_index,
                periodic_index,
                effect_specs,
                max_level,
                low_level_offset,
                {},
            )
            runtime_by_id[runtime_id] = runtime

            clone = bytearray(source)
            set_u32(clone, SPELL_ID, runtime_id)
            set_u32(clone, MAX_LEVEL, max_level)
            set_u32(clone, BASE_LEVEL, 1)
            set_u32(clone, SPELL_LEVEL, 1)
            for effect_index in range(3):
                level_one = runtime[0].effects[effect_index]
                if level_one is None:
                    continue
                set_i32(clone, EFFECT_DIE_SIDES + effect_index, 0)
                set_f32(clone, EFFECT_REAL_POINTS_PER_LEVEL + effect_index, 0.0)
                set_i32(
                    clone,
                    EFFECT_BASE_POINTS + effect_index,
                    int(math.floor((level_one.minimum + level_one.maximum) / 2.0 + 0.5)),
                )
            records.append(clone)

            resolved_additions.append(
                {
                    "id": runtime_id,
                    "clone_from": helper_root,
                    "name": f"Internal helper {helper_root}",
                    "native_first_level": samples[0].level,
                    "native_ranks": [
                        {"id": sample.spell_id, "level": sample.level}
                        for sample in samples
                    ],
                    "effects": effect_specs,
                    "draft": {
                        "replace_original": False,
                        "internal": True,
                        "original_family": [sample.spell_id for sample in samples],
                    },
                }
            )

            profile_spec: dict[str, Any] = {
                "id": runtime_id,
                "clone_from": helper_root,
                "name": f"Internal helper {helper_root}",
                "profile": profile_name,
                "anchors": semantic,
                "internal_helper": True,
            }
            if direct_index is not None:
                profile_spec["direct_effect_index"] = direct_index
            if periodic_index is not None:
                profile_spec["periodic_effect_index"] = periodic_index
            profile_additions.append(profile_spec)

        records.sort(key=lambda row: u32(row, SPELL_ID))
        write_dbc(spell_path, fields, record_size, records, strings, trailing)

        resolved_spells = resolved.get("spells")
        profile_spells = profiles.get("spells")
        if not isinstance(resolved_spells, list) or not isinstance(profile_spells, list):
            raise InternalHelperError("resolved/profile registries require spells[]")
        helper_ids = set(helper_runtime_ids)
        resolved["spells"] = [
            spell for spell in resolved_spells
            if not isinstance(spell, dict) or int(spell.get("id", -1)) not in helper_ids
        ] + resolved_additions
        profiles["spells"] = [
            spell for spell in profile_spells
            if not isinstance(spell, dict) or int(spell.get("id", -1)) not in helper_ids
        ] + profile_additions

        resolved_path.write_text(
            json.dumps(resolved, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        profiles_path.write_text(
            json.dumps(profiles, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        rows_added = append_scaling_rows(scaling_path, runtime_by_id)

        check_resolved = replacement_map(load_json(resolved_path, "resolved custom spell registry"))
        check_profiles = load_json(profiles_path, "resolved custom spell profiles")
        profile_ids = {
            int(spell["id"])
            for spell in check_profiles.get("spells", [])
            if isinstance(spell, dict) and "id" in spell
        }
        scaling_counts = {runtime_id: 0 for runtime_id in helper_runtime_ids}
        for raw_line in scaling_path.read_text(encoding="utf-8").splitlines():
            if not raw_line or raw_line.startswith("#"):
                continue
            tokens = raw_line.split()
            spell_id = int(tokens[0])
            if spell_id in scaling_counts:
                scaling_counts[spell_id] += 1

        for helper_root in missing_helpers:
            runtime_id = custom_offset + helper_root
            if check_resolved.get(helper_root) != runtime_id:
                raise InternalHelperError(f"resolved helper mapping failed for {helper_root}")
            if runtime_id not in profile_ids:
                raise InternalHelperError(f"profile helper {runtime_id} was not written")
            if scaling_counts[runtime_id] != max_level:
                raise InternalHelperError(
                    f"helper {runtime_id} has {scaling_counts[runtime_id]}/{max_level} scaling rows"
                )

    except (DBCError, InternalHelperError, KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"Reviewed internal helper normalization aborted: {exc}") from exc

    print("Reviewed internal trigger helpers normalized and validated:")
    for helper_root in missing_helpers:
        print(f"  {helper_root} -> {custom_offset + helper_root} (levels 1-{max_level})")
    print(f"  canonical runtime scaling rows added: {rows_added}")
    print("  runtime engine: unchanged; helpers use custom_spell_scaling.tsv")


if __name__ == "__main__":
    main()

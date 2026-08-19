#!/usr/bin/env python3
"""Finalize generated normalized Spell.dbc and SkillLineAbility.dbc rows.

Normalized abilities are intentionally rankless. A raw clone of Blizzard's
first rank would keep its localized "Rank 1" / "Rango 1" subtext, causing the
existing SpellDraft client to render Roman rank suffixes even though no native
rank is ever learned. Custom SkillLineAbility rows are also normalized to every
playable race + Adventurer class 10 so native class masks cannot invalidate a
custom spell after learning/relog.

A normalized custom spell must also be independent from the native
skill-learning semantics of the cloned row. In particular, SkillLineAbility
AcquireMethod=2 means "learned together with the entire skill" in AzerothCore.
Keeping it on a custom spell can make Player::learnSpell() call
LearnDefaultSkill() and teach unrelated stock abilities from that skill line.
Native SupercededBySpell and skill-rank gates are equally invalid for a rankless
custom spell, so those fields are cleared while the SkillLine itself is
preserved for spellbook/UI categorization.

Aventureros also does not use the stock Shaman totem-item progression. Both the
legacy Totem item fields and TotemCategory requirements are cleared from every
custom spell so drafted totems work without class quests or hidden inventory
prerequisites.

Cast time now belongs to the profile-aware runtime. The custom Spell.dbc row
therefore keeps the CastingTimeIndex of the native family root/first rank as a
safe fallback. The server runtime interpolates the base cast time by character
level and then lets AzerothCore apply its normal haste/spell modifiers. Keeping
the DBC fallback at rank 1 also gives the client the correct native level-1
value before the profile-aware tooltip helper runs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from patch_adventurer_class_dbcs import DBCError, read_dbc, set_u32, u32, write_dbc

SPELL_FIELDS = 234
SPELL_RECORD_SIZE = 936
CASTING_TIME_INDEX_FIELD = 28
TOTEM_REQUIREMENT_FIELDS = (50, 51, 222, 223)
RANK_FIRST_FIELD = 153
RANK_LAST_FIELD = 168
RANK_FLAGS_FIELD = 169

SKILLLINE_SPELL_FIELD = 2
SKILLLINE_RACE_MASK_FIELD = 3
SKILLLINE_CLASS_MASK_FIELD = 4
SKILLLINE_EXCLUDE_RACE_FIELD = 5
SKILLLINE_EXCLUDE_CLASS_FIELD = 6
SKILLLINE_MIN_RANK_FIELD = 7
SKILLLINE_SUPERCEDED_BY_SPELL_FIELD = 8
SKILLLINE_ACQUIRE_METHOD_FIELD = 9
SKILLLINE_TRIVIAL_RANK_HIGH_FIELD = 10
SKILLLINE_TRIVIAL_RANK_LOW_FIELD = 11
ADVENTURER_CLASS_MASK = 512


class FinalizeError(RuntimeError):
    pass


def load_resolved(path: Path) -> tuple[int, dict[int, dict[str, Any]]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FinalizeError(f"resolved custom spell registry not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FinalizeError(f"invalid resolved custom spell registry {path}: {exc}") from exc

    runtime_max_level = int(raw.get("runtime_max_level", 0))
    if runtime_max_level <= 0:
        raise FinalizeError(f"{path}: runtime_max_level must be positive")

    spells = raw.get("spells")
    if not isinstance(spells, list) or not spells:
        raise FinalizeError(f"{path}: expected a non-empty spells list")

    result: dict[int, dict[str, Any]] = {}
    for index, spell in enumerate(spells):
        if not isinstance(spell, dict):
            raise FinalizeError(f"{path}: spells[{index}] must be an object")
        try:
            spell_id = int(spell["id"])
            native_ranks = spell["native_ranks"]
        except (KeyError, TypeError, ValueError) as exc:
            raise FinalizeError(f"{path}: malformed spells[{index}]") from exc
        if spell_id in result:
            raise FinalizeError(f"{path}: duplicate custom spell ID {spell_id}")
        if not 200000 <= spell_id <= 299999:
            raise FinalizeError(f"{path}: custom spell ID outside 200000-299999: {spell_id}")
        if not isinstance(native_ranks, list) or not native_ranks:
            raise FinalizeError(f"{path}: custom spell {spell_id} has no native_ranks")
        result[spell_id] = spell

    return runtime_max_level, result


def first_native_rank(spec: dict[str, Any]) -> int:
    ranks = spec.get("native_ranks")
    if not isinstance(ranks, list) or not ranks:
        raise FinalizeError(f"custom spell {spec.get('id')} has no native rank samples")

    ordered: list[tuple[int, int]] = []
    for rank in ranks:
        if not isinstance(rank, dict):
            raise FinalizeError(f"custom spell {spec.get('id')} has malformed native rank data")
        try:
            spell_id = int(rank["id"])
            level = int(rank["level"])
        except (KeyError, TypeError, ValueError) as exc:
            raise FinalizeError(
                f"custom spell {spec.get('id')} has malformed native rank data"
            ) from exc
        ordered.append((level, spell_id))

    ordered.sort()
    return ordered[0][1]


def finalize_spell_rows(
    path: Path,
    specs: dict[int, dict[str, Any]],
) -> tuple[int, int, int]:
    fields, record_size, records, strings, trailing = read_dbc(path)
    if fields != SPELL_FIELDS or record_size != SPELL_RECORD_SIZE:
        raise FinalizeError(
            f"{path}: unexpected Spell.dbc layout {fields} fields / {record_size} bytes"
        )

    by_id = {u32(row, 0): row for row in records}
    found: set[int] = set()
    rank_text_changed = 0
    cast_time_changed = 0
    totem_requirement_changed = 0

    for spell_id, spec in specs.items():
        row = by_id.get(spell_id)
        if row is None:
            continue
        found.add(spell_id)

        row_totem_changed = False
        for field in TOTEM_REQUIREMENT_FIELDS:
            if u32(row, field) != 0:
                set_u32(row, field, 0)
                row_totem_changed = True
        if row_totem_changed:
            totem_requirement_changed += 1

        row_rank_changed = False
        for field in range(RANK_FIRST_FIELD, RANK_LAST_FIELD + 1):
            if u32(row, field) != 0:
                set_u32(row, field, 0)
                row_rank_changed = True
        if u32(row, RANK_FLAGS_FIELD) != 0:
            set_u32(row, RANK_FLAGS_FIELD, 0)
            row_rank_changed = True
        if row_rank_changed:
            rank_text_changed += 1

        source_rank_id = first_native_rank(spec)
        source_rank = by_id.get(source_rank_id)
        if source_rank is None:
            raise FinalizeError(
                f"custom spell {spell_id}: native root rank {source_rank_id} is missing from Spell.dbc"
            )
        desired_cast_time_index = u32(source_rank, CASTING_TIME_INDEX_FIELD)
        if u32(row, CASTING_TIME_INDEX_FIELD) != desired_cast_time_index:
            set_u32(row, CASTING_TIME_INDEX_FIELD, desired_cast_time_index)
            cast_time_changed += 1

    missing = sorted(set(specs) - found)
    if missing:
        raise FinalizeError(
            "resolved custom spell row(s) missing from Spell.dbc: "
            + ", ".join(str(value) for value in missing)
        )

    write_dbc(path, fields, record_size, records, strings, trailing)

    # Read back every invariant rather than trusting the mutation above.
    _, _, checked, _, _ = read_dbc(path)
    checked_by_id = {u32(row, 0): row for row in checked}
    for spell_id, spec in specs.items():
        row = checked_by_id[spell_id]
        if any(u32(row, field) != 0 for field in TOTEM_REQUIREMENT_FIELDS):
            raise FinalizeError(
                f"custom spell {spell_id} still has a totem item/category requirement"
            )
        if any(
            u32(row, field) != 0
            for field in range(RANK_FIRST_FIELD, RANK_LAST_FIELD + 1)
        ):
            raise FinalizeError(f"custom spell {spell_id} still has localized rank subtext")

        source_rank_id = first_native_rank(spec)
        source_rank = checked_by_id.get(source_rank_id)
        if source_rank is None:
            raise FinalizeError(
                f"custom spell {spell_id}: validation root rank {source_rank_id} is missing"
            )
        if u32(row, CASTING_TIME_INDEX_FIELD) != u32(source_rank, CASTING_TIME_INDEX_FIELD):
            raise FinalizeError(
                f"custom spell {spell_id} does not use native root/rank-1 fallback cast time"
            )

    return rank_text_changed, cast_time_changed, totem_requirement_changed


def normalize_skillline_masks(path: Path, ids: set[int]) -> int:
    fields, record_size, records, strings, trailing = read_dbc(path)
    if record_size != fields * 4 or fields < 12:
        raise FinalizeError(
            f"{path}: unexpected SkillLineAbility.dbc layout {fields} fields / {record_size} bytes"
        )

    desired = {
        SKILLLINE_RACE_MASK_FIELD: 0,
        SKILLLINE_CLASS_MASK_FIELD: ADVENTURER_CLASS_MASK,
        SKILLLINE_EXCLUDE_RACE_FIELD: 0,
        SKILLLINE_EXCLUDE_CLASS_FIELD: 0,
        # Custom spells are independent rankless spells. Never inherit the
        # native skill's auto-learn/supersede semantics, otherwise learning one
        # custom spell can cause AzerothCore to teach unrelated stock abilities.
        SKILLLINE_MIN_RANK_FIELD: 0,
        SKILLLINE_SUPERCEDED_BY_SPELL_FIELD: 0,
        SKILLLINE_ACQUIRE_METHOD_FIELD: 0,
        SKILLLINE_TRIVIAL_RANK_HIGH_FIELD: 0,
        SKILLLINE_TRIVIAL_RANK_LOW_FIELD: 0,
    }

    found: dict[int, int] = {spell_id: 0 for spell_id in ids}
    changed = 0
    for row in records:
        spell_id = u32(row, SKILLLINE_SPELL_FIELD)
        if spell_id not in ids:
            continue
        found[spell_id] += 1
        row_changed = False
        for field, value in desired.items():
            if u32(row, field) != value:
                set_u32(row, field, value)
                row_changed = True
        if row_changed:
            changed += 1

    missing = [spell_id for spell_id, count in found.items() if count == 0]
    duplicate = [spell_id for spell_id, count in found.items() if count != 1 and count > 0]
    if missing:
        raise FinalizeError(
            "resolved custom spell SkillLineAbility row(s) missing: "
            + ", ".join(str(value) for value in sorted(missing))
        )
    if duplicate:
        raise FinalizeError(
            "resolved custom spell has duplicate SkillLineAbility rows: "
            + ", ".join(str(value) for value in sorted(duplicate))
        )

    write_dbc(path, fields, record_size, records, strings, trailing)

    # Validate the persisted rows, including the fields that can trigger
    # LearnDefaultSkill()/native rank progression in Player::learnSpell().
    _, _, checked, _, _ = read_dbc(path)
    checked_by_spell: dict[int, list[bytearray]] = {spell_id: [] for spell_id in ids}
    for row in checked:
        spell_id = u32(row, SKILLLINE_SPELL_FIELD)
        if spell_id in checked_by_spell:
            checked_by_spell[spell_id].append(row)

    for spell_id, rows in checked_by_spell.items():
        if len(rows) != 1:
            raise FinalizeError(
                f"custom spell {spell_id}: expected one persisted SkillLineAbility row, found {len(rows)}"
            )
        row = rows[0]
        bad = [field for field, value in desired.items() if u32(row, field) != value]
        if bad:
            raise FinalizeError(
                f"custom spell {spell_id}: SkillLineAbility normalization failed for field(s) "
                + ", ".join(str(field) for field in bad)
            )

    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dbc-dir", required=True, type=Path)
    parser.add_argument("--resolved", required=True, type=Path)
    args = parser.parse_args()

    dbc_dir = args.dbc_dir.expanduser().resolve()
    spell_path = dbc_dir / "Spell.dbc"
    ability_path = dbc_dir / "SkillLineAbility.dbc"
    missing = [str(path) for path in (spell_path, ability_path) if not path.is_file()]
    if missing:
        raise SystemExit("Missing required DBC(s): " + ", ".join(missing))

    try:
        _runtime_max_level, specs = load_resolved(args.resolved.expanduser().resolve())
        rank_changed, cast_time_changed, totem_changed = finalize_spell_rows(spell_path, specs)
        ability_changed = normalize_skillline_masks(ability_path, set(specs))
    except (DBCError, FinalizeError, KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"Normalized custom spell DBC finalization aborted: {exc}") from exc

    print(f"Normalized custom spell DBC rows finalized: {len(specs)} spells validated")
    print(f"  Spell.dbc rank-subtext rows changed: {rank_changed}")
    print(f"  Spell.dbc rank-1 fallback cast-time rows changed: {cast_time_changed}")
    print(f"  Spell.dbc totem-requirement rows changed: {totem_changed}")
    print(f"  SkillLineAbility.dbc normalized association rows changed: {ability_changed}")
    print("  cast-time fallback: native family root/rank 1; runtime profile owns level scaling")
    print("  custom totem item/category requirements: cleared")
    print("  custom associations: every race / Adventurer class 10 only")
    print("  inherited skill auto-learn / superseded-rank semantics: cleared")


if __name__ == "__main__":
    main()

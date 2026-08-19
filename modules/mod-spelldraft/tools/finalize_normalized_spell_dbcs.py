#!/usr/bin/env python3
"""Finalize generated normalized Spell.dbc and SkillLineAbility.dbc rows.

Normalized abilities are intentionally rankless. A raw clone of Blizzard's
first rank would keep its localized "Rank 1" / "Rango 1" subtext, causing the
existing SpellDraft client to render Roman rank suffixes even though no native
rank is ever learned. Custom SkillLineAbility rows are also normalized to every
playable race + Adventurer class 10 so native class masks cannot invalidate a
201xxx spell after learning/relog.

A normalized 201xxx spell must also be independent from the native skill-learning
semantics of the cloned row. In particular, SkillLineAbility AcquireMethod=2
means "learned together with the entire skill" in AzerothCore. Keeping it on a
custom spell can make Player::learnSpell() call LearnDefaultSkill() and teach
unrelated stock abilities from that skill line. Native SupercededBySpell and
skill-rank gates are equally invalid for a rankless custom spell, so those
fields are cleared while the SkillLine itself is preserved for spellbook/UI
categorization.

Cast time needs special handling too. WotLK rank families such as Frostbolt and
Fireball can start with a shorter low-rank cast. Giving a level-60 normalized
damage curve to that first-rank cast time would inflate DPS. Until the runtime
has an explicit per-level cast-time hook, each custom spell therefore inherits
the CastingTimeIndex of the highest native rank at or below the configured
runtime cap. This is deliberately conservative: low-level casts can be slower,
but high-level damage can never be paired with an artificially short Rank-1
cast solely because the custom row was cloned from the family root.
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
        if not 201000 <= spell_id <= 201999:
            raise FinalizeError(f"{path}: custom spell ID outside 201000-201999: {spell_id}")
        if not isinstance(native_ranks, list) or not native_ranks:
            raise FinalizeError(f"{path}: custom spell {spell_id} has no native_ranks")
        result[spell_id] = spell

    return runtime_max_level, result


def strongest_rank_at_cap(spec: dict[str, Any], runtime_max_level: int) -> int:
    ranks = spec.get("native_ranks")
    if not isinstance(ranks, list) or not ranks:
        raise FinalizeError(f"custom spell {spec.get('id')} has no native rank samples")

    usable: list[tuple[int, int]] = []
    all_ranks: list[tuple[int, int]] = []
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
        all_ranks.append((level, spell_id))
        if level <= runtime_max_level:
            usable.append((level, spell_id))

    selected = usable if usable else all_ranks
    selected.sort()
    return selected[-1][1]


def finalize_spell_rows(
    path: Path,
    runtime_max_level: int,
    specs: dict[int, dict[str, Any]],
) -> tuple[int, int]:
    fields, record_size, records, strings, trailing = read_dbc(path)
    if fields != SPELL_FIELDS or record_size != SPELL_RECORD_SIZE:
        raise FinalizeError(
            f"{path}: unexpected Spell.dbc layout {fields} fields / {record_size} bytes"
        )

    by_id = {u32(row, 0): row for row in records}
    found: set[int] = set()
    rank_text_changed = 0
    cast_time_changed = 0

    for spell_id, spec in specs.items():
        row = by_id.get(spell_id)
        if row is None:
            continue
        found.add(spell_id)

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

        source_rank_id = strongest_rank_at_cap(spec, runtime_max_level)
        source_rank = by_id.get(source_rank_id)
        if source_rank is None:
            raise FinalizeError(
                f"custom spell {spell_id}: selected native rank {source_rank_id} is missing from Spell.dbc"
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
        if any(
            u32(row, field) != 0
            for field in range(RANK_FIRST_FIELD, RANK_LAST_FIELD + 1)
        ):
            raise FinalizeError(f"custom spell {spell_id} still has localized rank subtext")

        source_rank_id = strongest_rank_at_cap(spec, runtime_max_level)
        source_rank = checked_by_id.get(source_rank_id)
        if source_rank is None:
            raise FinalizeError(
                f"custom spell {spell_id}: validation source rank {source_rank_id} is missing"
            )
        if u32(row, CASTING_TIME_INDEX_FIELD) != u32(source_rank, CASTING_TIME_INDEX_FIELD):
            raise FinalizeError(
                f"custom spell {spell_id} does not use the conservative rank-{source_rank_id} cast time"
            )

    return rank_text_changed, cast_time_changed


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
        # 201xxx is an independent rankless spell. Never inherit the native
        # skill's auto-learn/supersede semantics, otherwise learning one custom
        # spell can cause AzerothCore to teach unrelated stock abilities.
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
        runtime_max_level, specs = load_resolved(args.resolved.expanduser().resolve())
        rank_changed, cast_time_changed = finalize_spell_rows(
            spell_path,
            runtime_max_level,
            specs,
        )
        ability_changed = normalize_skillline_masks(ability_path, set(specs))
    except (DBCError, FinalizeError, KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"Normalized custom spell DBC finalization aborted: {exc}") from exc

    print(f"Normalized custom spell DBC rows finalized: {len(specs)} spells validated")
    print(f"  Spell.dbc rank-subtext rows changed: {rank_changed}")
    print(f"  Spell.dbc conservative cast-time rows changed: {cast_time_changed}")
    print(f"  SkillLineAbility.dbc normalized association rows changed: {ability_changed}")
    print(f"  cast-time source: highest native rank at/below level {runtime_max_level}")
    print("  custom associations: every race / Adventurer class 10 only")
    print("  inherited skill auto-learn / superseded-rank semantics: cleared")


if __name__ == "__main__":
    main()

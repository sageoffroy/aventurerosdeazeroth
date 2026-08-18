#!/usr/bin/env python3
"""Finalize generated normalized Spell.dbc and SkillLineAbility.dbc rows.

Normalized abilities are intentionally rankless. A raw clone of Blizzard's
first rank would keep its localized "Rank 1" / "Rango 1" subtext, causing the
existing SpellDraft client to render Roman rank suffixes even though no native
rank is ever learned. Custom SkillLineAbility rows are also normalized to every
playable race + Adventurer class 10 so native class masks cannot invalidate a
201xxx spell after learning/relog.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from patch_adventurer_class_dbcs import DBCError, read_dbc, set_u32, u32, write_dbc

SPELL_FIELDS = 234
SPELL_RECORD_SIZE = 936
RANK_FIRST_FIELD = 153
RANK_LAST_FIELD = 168
RANK_FLAGS_FIELD = 169

SKILLLINE_SPELL_FIELD = 2
SKILLLINE_RACE_MASK_FIELD = 3
SKILLLINE_CLASS_MASK_FIELD = 4
SKILLLINE_EXCLUDE_RACE_FIELD = 5
SKILLLINE_EXCLUDE_CLASS_FIELD = 6
ADVENTURER_CLASS_MASK = 512


class FinalizeError(RuntimeError):
    pass


def custom_ids(path: Path) -> set[int]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FinalizeError(f"resolved custom spell registry not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FinalizeError(f"invalid resolved custom spell registry {path}: {exc}") from exc

    spells = raw.get("spells")
    if not isinstance(spells, list) or not spells:
        raise FinalizeError(f"{path}: expected a non-empty spells list")
    result = {
        int(spell["id"])
        for spell in spells
        if isinstance(spell, dict) and "id" in spell
    }
    if len(result) != len(spells):
        raise FinalizeError(f"{path}: duplicate or malformed custom spell IDs")
    if any(spell_id < 201000 or spell_id > 201999 for spell_id in result):
        raise FinalizeError(f"{path}: custom spell ID outside 201000-201999")
    return result


def clear_rank_subtexts(path: Path, ids: set[int]) -> int:
    fields, record_size, records, strings, trailing = read_dbc(path)
    if fields != SPELL_FIELDS or record_size != SPELL_RECORD_SIZE:
        raise FinalizeError(
            f"{path}: unexpected Spell.dbc layout {fields} fields / {record_size} bytes"
        )

    found: set[int] = set()
    changed = 0
    for row in records:
        spell_id = u32(row, 0)
        if spell_id not in ids:
            continue
        found.add(spell_id)
        row_changed = False
        for field in range(RANK_FIRST_FIELD, RANK_LAST_FIELD + 1):
            if u32(row, field) != 0:
                set_u32(row, field, 0)
                row_changed = True
        if u32(row, RANK_FLAGS_FIELD) != 0:
            set_u32(row, RANK_FLAGS_FIELD, 0)
            row_changed = True
        if row_changed:
            changed += 1

    missing = sorted(ids - found)
    if missing:
        raise FinalizeError(
            "resolved custom spell row(s) missing from Spell.dbc: "
            + ", ".join(str(value) for value in missing)
        )

    write_dbc(path, fields, record_size, records, strings, trailing)

    # Read it back so client-visible ranklessness is a checked invariant rather
    # than an assumption made by the generator.
    _, _, checked, _, _ = read_dbc(path)
    for row in checked:
        spell_id = u32(row, 0)
        if spell_id not in ids:
            continue
        if any(
            u32(row, field) != 0
            for field in range(RANK_FIRST_FIELD, RANK_LAST_FIELD + 1)
        ):
            raise FinalizeError(f"custom spell {spell_id} still has localized rank subtext")
    return changed


def normalize_skillline_masks(path: Path, ids: set[int]) -> int:
    fields, record_size, records, strings, trailing = read_dbc(path)
    if record_size != fields * 4 or fields < 12:
        raise FinalizeError(
            f"{path}: unexpected SkillLineAbility.dbc layout {fields} fields / {record_size} bytes"
        )

    found: dict[int, int] = {spell_id: 0 for spell_id in ids}
    changed = 0
    for row in records:
        spell_id = u32(row, SKILLLINE_SPELL_FIELD)
        if spell_id not in ids:
            continue
        found[spell_id] += 1
        row_changed = False
        desired = {
            SKILLLINE_RACE_MASK_FIELD: 0,
            SKILLLINE_CLASS_MASK_FIELD: ADVENTURER_CLASS_MASK,
            SKILLLINE_EXCLUDE_RACE_FIELD: 0,
            SKILLLINE_EXCLUDE_CLASS_FIELD: 0,
        }
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
        ids = custom_ids(args.resolved.expanduser().resolve())
        spell_changed = clear_rank_subtexts(spell_path, ids)
        ability_changed = normalize_skillline_masks(ability_path, ids)
    except (DBCError, FinalizeError, KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"Normalized custom spell DBC finalization aborted: {exc}") from exc

    print(f"Normalized custom spell DBC rows finalized: {len(ids)} spells validated")
    print(f"  Spell.dbc rank-subtext rows changed: {spell_changed}")
    print(f"  SkillLineAbility.dbc class-mask rows changed: {ability_changed}")
    print("  custom associations: every race / Adventurer class 10 only")


if __name__ == "__main__":
    main()

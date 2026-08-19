#!/usr/bin/env python3
"""Run the normalized-spell generator after removing reviewed false roots.

The production catalog intentionally stays broad. This wrapper narrows the
initial <=20 normalization cohort by removing manually reviewed talent proc,
form-granted and duplicate helper rows before custom IDs are assigned.

The 201000-201999 range belongs to Aventureros custom spells, so each reviewed
generation first removes prior generated rows from Spell.dbc and
SkillLineAbility.dbc. That makes regeneration deterministic after the reviewed
cohort changes and prevents stale custom rows surviving an earlier run.
"""

from __future__ import annotations

import sys
from pathlib import Path

import generate_normalized_spells as generator
from reviewed_spell_exclusions import ExclusionError, load_excluded_spell_ids

CUSTOM_MIN = 200000
CUSTOM_MAX = 299999


def argument_path(name: str) -> Path:
    try:
        index = sys.argv.index(name)
        value = sys.argv[index + 1]
    except (ValueError, IndexError) as exc:
        raise SystemExit(f"Reviewed normalized-spell generation requires {name}") from exc
    return Path(value).expanduser().resolve()


def clear_generated_custom_rows(dbc_dir: Path) -> tuple[int, int]:
    spell_path = dbc_dir / "Spell.dbc"
    fields, record_size, records, strings, trailing = generator.read_dbc(spell_path)
    before = len(records)
    records = [
        row for row in records
        if not CUSTOM_MIN <= generator.u32(row, generator.SPELL_ID) <= CUSTOM_MAX
    ]
    generator.write_dbc(spell_path, fields, record_size, records, strings, trailing)
    removed_spells = before - len(records)

    ability_path = dbc_dir / "SkillLineAbility.dbc"
    fields, record_size, records, strings, trailing = generator.read_dbc(ability_path)
    before = len(records)
    records = [
        row for row in records
        if not CUSTOM_MIN <= generator.u32(row, generator.SKILLLINE_SPELL) <= CUSTOM_MAX
    ]
    generator.write_dbc(ability_path, fields, record_size, records, strings, trailing)
    removed_abilities = before - len(records)
    return removed_spells, removed_abilities


def main() -> None:
    try:
        excluded = load_excluded_spell_ids()
    except ExclusionError as exc:
        raise SystemExit(f"Reviewed normalized-spell generation aborted: {exc}") from exc

    dbc_dir = argument_path("--dbc-dir")
    removed_spells, removed_abilities = clear_generated_custom_rows(dbc_dir)
    print(
        "Reviewed custom DBC cleanup: "
        f"Spell.dbc={removed_spells}, SkillLineAbility.dbc={removed_abilities} stale 201xxx rows removed"
    )

    original_build_catalog = generator.build_catalog

    def reviewed_build_catalog(*args, **kwargs):
        catalog = original_build_catalog(*args, **kwargs)
        return [entry for entry in catalog if int(entry["id"]) not in excluded]

    generator.build_catalog = reviewed_build_catalog
    generator.main()


if __name__ == "__main__":
    main()

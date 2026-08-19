#!/usr/bin/env python3
"""Report raw Spell.dbc fields that drive 3.3.5a tooltip scaling."""

from __future__ import annotations

import argparse
from pathlib import Path

from report_spell_family import (
    DEFAULT_DBC_DIR,
    DESCRIPTION_FIRST,
    DESCRIPTION_LAST,
    DESCRIPTION_LOCALE_PREFERENCE,
    EFFECT_BASE_POINTS,
    EFFECT_DIE_SIDES,
    EFFECT_REAL_POINTS_PER_LEVEL,
    EFFECT_TYPE,
    NAME_FIRST,
    NAME_LAST,
    NAME_LOCALE_PREFERENCE,
    clean_description,
    f32,
    i32,
    localized_text,
    rows_by_id,
    u32,
)

MAX_LEVEL = 37
BASE_LEVEL = 38
SPELL_LEVEL = 39


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("ids", nargs="+", type=int)
    parser.add_argument("--dbc-dir", type=Path, default=DEFAULT_DBC_DIR)
    args = parser.parse_args()

    dbc_dir = args.dbc_dir.expanduser().resolve()
    spell_path = dbc_dir / "Spell.dbc"
    if not spell_path.is_file():
        raise SystemExit(f"Missing DBC: {spell_path}")

    _, _, spells, strings = rows_by_id(spell_path)

    for spell_id in args.ids:
        row = spells.get(spell_id)
        if row is None:
            print(f"{spell_id}: MISSING")
            continue

        name = localized_text(row, strings, NAME_LOCALE_PREFERENCE, NAME_FIRST, NAME_LAST)
        description = localized_text(
            row,
            strings,
            DESCRIPTION_LOCALE_PREFERENCE,
            DESCRIPTION_FIRST,
            DESCRIPTION_LAST,
        )

        print(
            f"{spell_id} {name} | MaxLevel={u32(row, MAX_LEVEL)} "
            f"BaseLevel={u32(row, BASE_LEVEL)} SpellLevel={u32(row, SPELL_LEVEL)}"
        )
        for effect_index in range(3):
            effect_type = u32(row, EFFECT_TYPE + effect_index)
            if not effect_type:
                continue
            print(
                f"  e{effect_index}: type={effect_type} "
                f"BasePoints={i32(row, EFFECT_BASE_POINTS + effect_index)} "
                f"DieSides={i32(row, EFFECT_DIE_SIDES + effect_index)} "
                f"RealPointsPerLevel={f32(row, EFFECT_REAL_POINTS_PER_LEVEL + effect_index):g}"
            )
        print(f"  desc: {clean_description(description)}")
        print()


if __name__ == "__main__":
    main()

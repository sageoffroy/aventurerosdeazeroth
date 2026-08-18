#!/usr/bin/env python3
"""Finalize client-facing fields of generated normalized Spell.dbc rows.

Normalized abilities are intentionally rankless. A raw clone of Blizzard's
first rank would keep its localized "Rank 1" / "Rango 1" subtext, causing the
existing SpellDraft client to render Roman rank suffixes even though no native
rank is ever learned. This stage clears all localized Rank fields only on the
resolved 201xxx rows and validates the result.
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
    result = {int(spell["id"]) for spell in spells if isinstance(spell, dict) and "id" in spell}
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
        if any(u32(row, field) != 0 for field in range(RANK_FIRST_FIELD, RANK_LAST_FIELD + 1)):
            raise FinalizeError(f"custom spell {spell_id} still has localized rank subtext")
    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dbc-dir", required=True, type=Path)
    parser.add_argument("--resolved", required=True, type=Path)
    args = parser.parse_args()

    dbc_path = args.dbc_dir.expanduser().resolve() / "Spell.dbc"
    if not dbc_path.is_file():
        raise SystemExit(f"Missing required DBC: {dbc_path}")

    try:
        ids = custom_ids(args.resolved.expanduser().resolve())
        changed = clear_rank_subtexts(dbc_path, ids)
    except (DBCError, FinalizeError, KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"Normalized custom spell DBC finalization aborted: {exc}") from exc

    print(f"Normalized custom spell rank subtexts cleared: {len(ids)} rows validated")
    print(f"  changed this run: {changed}")
    print(f"  Spell.dbc: {dbc_path}")


if __name__ == "__main__":
    main()

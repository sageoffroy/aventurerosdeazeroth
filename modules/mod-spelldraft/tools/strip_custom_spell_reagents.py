#!/usr/bin/env python3
"""Remove selected stock reagent requirements from Adventurer custom spells.

Soul Shards and ordinary class consumables remain untouched. This only removes
reagents from utility spells that Aventureros intentionally wants to cast
without carrying the original class vendor/quest item.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from patch_adventurer_class_dbcs import DBCError, read_dbc, set_u32, u32, write_dbc

SPELL_FIELDS = 234
SPELL_RECORD_SIZE = 936
REAGENT_FIELDS = tuple(range(52, 68))

# Rebirth + all WotLK Mage teleports. Entries above the current <=20 normalized
# cohort are kept here so the rule automatically applies when that cohort grows.
REAGENT_FREE_NATIVE_ROOTS = {
    20484,  # Rebirth
    3561,   # Teleport: Stormwind
    3562,   # Teleport: Ironforge
    3563,   # Teleport: Undercity
    3565,   # Teleport: Darnassus
    3566,   # Teleport: Thunder Bluff
    3567,   # Teleport: Orgrimmar
    32271,  # Teleport: Exodar
    32272,  # Teleport: Silvermoon
    33690,  # Teleport: Shattrath
    49358,  # Teleport: Stonard
    49359,  # Teleport: Theramore
    53140,  # Teleport: Dalaran
}


class ReagentPatchError(RuntimeError):
    pass


def load_targets(path: Path) -> dict[int, int]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise ReagentPatchError(f"cannot read resolved registry {path}: {exc}") from exc

    spells = data.get("spells")
    if not isinstance(spells, list):
        raise ReagentPatchError(f"{path}: expected spells list")

    targets: dict[int, int] = {}
    for spec in spells:
        custom_id = int(spec["id"])
        native_root = int(spec["clone_from"])
        if native_root in REAGENT_FREE_NATIVE_ROOTS:
            targets[custom_id] = native_root
    return targets


def patch_spell_dbc(path: Path, targets: dict[int, int]) -> int:
    fields, record_size, records, strings, trailing = read_dbc(path)
    if fields != SPELL_FIELDS or record_size != SPELL_RECORD_SIZE:
        raise ReagentPatchError(
            f"{path}: unexpected Spell.dbc layout {fields} fields / {record_size} bytes"
        )

    by_id = {u32(row, 0): row for row in records}
    changed = 0
    for custom_id, native_root in targets.items():
        row = by_id.get(custom_id)
        if row is None:
            raise ReagentPatchError(
                f"custom spell {custom_id} (native {native_root}) missing from Spell.dbc"
            )

        row_changed = False
        for field in REAGENT_FIELDS:
            if u32(row, field) != 0:
                set_u32(row, field, 0)
                row_changed = True
        if row_changed:
            changed += 1

    write_dbc(path, fields, record_size, records, strings, trailing)

    _, _, checked, _, _ = read_dbc(path)
    checked_by_id = {u32(row, 0): row for row in checked}
    for custom_id, native_root in targets.items():
        row = checked_by_id[custom_id]
        if any(u32(row, field) != 0 for field in REAGENT_FIELDS):
            raise ReagentPatchError(
                f"custom spell {custom_id} (native {native_root}) still has reagents"
            )

    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dbc-dir", required=True, type=Path)
    parser.add_argument("--resolved", required=True, type=Path)
    args = parser.parse_args()

    dbc_dir = args.dbc_dir.expanduser().resolve()
    spell_path = dbc_dir / "Spell.dbc"

    try:
        targets = load_targets(args.resolved.expanduser().resolve())
        changed = patch_spell_dbc(spell_path, targets)
    except (DBCError, ReagentPatchError, KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"Custom reagent cleanup aborted: {exc}") from exc

    print(f"Custom reagent cleanup: {len(targets)} target spell(s), {changed} row(s) changed")
    for custom_id, native_root in sorted(targets.items(), key=lambda item: item[1]):
        print(f"  native {native_root} -> custom {custom_id}: reagent-free")


if __name__ == "__main__":
    main()

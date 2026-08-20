#!/usr/bin/env python3
"""Finalize generated package-card Spell.dbc rows.

Package cards are virtual/rankless draft choices. They may clone a ranked native
spell only to reuse its icon/presentation, so inherited localized Rank 1 / Rango
1 subtext must never survive on the package marker itself.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from patch_adventurer_class_dbcs import DBCError, read_dbc, set_u32, u32, write_dbc

TOOLS_DIR = Path(__file__).resolve().parent
DEFAULT_PACKAGES = TOOLS_DIR.parent / "card_packages.json"
SPELL_FIELDS = 234
SPELL_RECORD_SIZE = 936
RANK_FIRST_FIELD = 153
RANK_LAST_FIELD = 168
RANK_FLAGS_FIELD = 169


class PackageFinalizeError(RuntimeError):
    pass


def load_package_ids(path: Path) -> set[int]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackageFinalizeError(f"cannot read {path}: {exc}") from exc

    packages = raw.get("packages")
    if raw.get("schema_version") != 1 or not isinstance(packages, list):
        raise PackageFinalizeError(f"{path}: expected schema_version=1 and packages[]")

    ids: set[int] = set()
    for package in packages:
        if not isinstance(package, dict):
            raise PackageFinalizeError(f"{path}: malformed package entry")
        card_id = package.get("card_id")
        if isinstance(card_id, bool) or not isinstance(card_id, int):
            raise PackageFinalizeError(f"{path}: invalid package card_id {card_id!r}")
        ids.add(card_id)
    return ids


def finalize(path: Path, package_ids: set[int]) -> int:
    fields, record_size, records, strings, trailing = read_dbc(path)
    if fields != SPELL_FIELDS or record_size != SPELL_RECORD_SIZE:
        raise PackageFinalizeError(
            f"{path}: unexpected Spell.dbc layout {fields}/{record_size}"
        )

    found: set[int] = set()
    changed = 0
    for row in records:
        spell_id = u32(row, 0)
        if spell_id not in package_ids:
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

    missing = sorted(package_ids - found)
    if missing:
        raise PackageFinalizeError(
            "package card row(s) missing from Spell.dbc: "
            + ", ".join(str(value) for value in missing)
        )

    write_dbc(path, fields, record_size, records, strings, trailing)

    _, _, checked, _, _ = read_dbc(path)
    by_id = {u32(row, 0): row for row in checked}
    for spell_id in package_ids:
        row = by_id[spell_id]
        if any(
            u32(row, field) != 0
            for field in range(RANK_FIRST_FIELD, RANK_LAST_FIELD + 1)
        ) or u32(row, RANK_FLAGS_FIELD) != 0:
            raise PackageFinalizeError(
                f"package card {spell_id} still has localized rank subtext"
            )

    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dbc-dir", required=True, type=Path)
    parser.add_argument("--packages", type=Path, default=DEFAULT_PACKAGES)
    args = parser.parse_args()

    try:
        package_ids = load_package_ids(args.packages.expanduser().resolve())
        changed = finalize(
            args.dbc_dir.expanduser().resolve() / "Spell.dbc",
            package_ids,
        )
    except (DBCError, PackageFinalizeError, KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"Package-card finalization aborted: {exc}") from exc

    print(f"Package cards finalized: {len(package_ids)} validated")
    print(f"  rank-subtext rows changed: {changed}")
    print("  package cards are rankless draft markers")


if __name__ == "__main__":
    main()

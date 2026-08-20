#!/usr/bin/env python3
"""Finalize generated package-card Spell.dbc markers.

Package cards are rankless passive markers. They may clone a ranked Blizzard
spell only to reuse its icon/family presentation, so inherited localized
"Rank 1" / "Rango 1" subtext must never survive on the package card.
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


class PackageMarkerError(RuntimeError):
    pass


def package_ids(path: Path) -> set[int]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackageMarkerError(f"cannot read {path}: {exc}") from exc

    packages = raw.get("packages")
    if raw.get("schema_version") != 1 or not isinstance(packages, list):
        raise PackageMarkerError(f"{path}: expected schema_version=1 and packages[]")

    result: set[int] = set()
    for package in packages:
        card_id = package.get("card_id") if isinstance(package, dict) else None
        if isinstance(card_id, bool) or not isinstance(card_id, int):
            raise PackageMarkerError(f"{path}: invalid package card_id {card_id!r}")
        result.add(card_id)
    return result


def finalize(path: Path, ids: set[int]) -> int:
    fields, record_size, records, strings, trailing = read_dbc(path)
    if fields != SPELL_FIELDS or record_size != SPELL_RECORD_SIZE:
        raise PackageMarkerError(
            f"{path}: unexpected Spell.dbc layout {fields}/{record_size}"
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
        raise PackageMarkerError(
            "package marker spell row(s) missing: "
            + ", ".join(str(value) for value in missing)
        )

    write_dbc(path, fields, record_size, records, strings, trailing)

    _, _, checked, _, _ = read_dbc(path)
    by_id = {u32(row, 0): row for row in checked}
    for spell_id in ids:
        row = by_id[spell_id]
        if any(
            u32(row, field) != 0
            for field in range(RANK_FIRST_FIELD, RANK_LAST_FIELD + 1)
        ) or u32(row, RANK_FLAGS_FIELD) != 0:
            raise PackageMarkerError(
                f"package marker {spell_id} still has localized rank subtext"
            )

    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dbc-dir", required=True, type=Path)
    parser.add_argument("--packages", type=Path, default=DEFAULT_PACKAGES)
    args = parser.parse_args()

    try:
        ids = package_ids(args.packages.expanduser().resolve())
        changed = finalize(
            args.dbc_dir.expanduser().resolve() / "Spell.dbc",
            ids,
        )
    except (DBCError, PackageMarkerError, KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"Package marker finalization aborted: {exc}") from exc

    print("SpellDraft package markers finalized and validated:")
    print(f"  package cards: {len(ids)}")
    print(f"  rank-subtext rows changed: {changed}")
    print("  invariant: package cards are rankless (no Rank 1 / Rango 1)")


if __name__ == "__main__":
    main()

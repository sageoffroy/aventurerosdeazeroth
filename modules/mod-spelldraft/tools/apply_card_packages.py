#!/usr/bin/env python3
"""Apply virtual SpellDraft package cards to the prepared runtime/client data."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from patch_adventurer_class_dbcs import (
    DBCError,
    append_string,
    read_dbc,
    set_u32,
    u32,
    write_dbc,
)

TOOLS_DIR = Path(__file__).resolve().parent
DEFAULT_PACKAGES = TOOLS_DIR.parent / "card_packages.json"
SPELL_FIELDS = 234
SPELL_RECORD_SIZE = 936
ITEM_REQUIREMENT_FIELDS = tuple(range(50, 68))
NAME_FIELDS = tuple(range(136, 152))
DESCRIPTION_FIELDS = tuple(range(170, 186))
TOOLTIP_FIELDS = tuple(range(187, 203))


class PackageError(RuntimeError):
    pass


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackageError(f"cannot read {path}: {exc}") from exc


def load_packages(path: Path) -> list[dict]:
    raw = load_json(path)
    if raw.get("schema_version") != 1 or not isinstance(raw.get("packages"), list):
        raise PackageError(f"{path}: expected schema_version=1 and packages[]")

    packages = raw["packages"]
    seen: set[int] = set()
    for package in packages:
        card_id = package.get("card_id")
        teaches = package.get("teaches")
        if not isinstance(card_id, int) or not 190000 <= card_id <= 199999:
            raise PackageError("virtual package IDs must be in 190000-199999")
        if card_id in seen:
            raise PackageError(f"duplicate package card ID {card_id}")
        if not isinstance(teaches, list) or not teaches or any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in teaches
        ):
            raise PackageError(f"package {card_id}: invalid teaches list")
        if card_id in teaches:
            raise PackageError(f"package {card_id}: cannot teach itself")
        seen.add(card_id)
    return packages


def load_replacements(path: Path) -> dict[int, int]:
    raw = load_json(path)
    result: dict[int, int] = {}
    for spell in raw.get("spells", []):
        result[int(spell["clone_from"])] = int(spell["id"])
    return result


def clear_item_requirements(row: bytearray) -> None:
    for field in ITEM_REQUIREMENT_FIELDS:
        set_u32(row, field, 0)


def set_text(row: bytearray, fields: tuple[int, ...], strings: bytearray, value: str) -> None:
    offset = append_string(strings, value)
    for field in fields:
        set_u32(row, field, offset)


def patch_spell_dbc(
    path: Path,
    packages: list[dict],
    replacements: dict[int, int],
) -> dict[int, int]:
    fields, record_size, records, strings, trailing = read_dbc(path)
    if fields != SPELL_FIELDS or record_size != SPELL_RECORD_SIZE:
        raise PackageError(f"unexpected Spell.dbc layout: {fields}/{record_size}")

    package_ids = {int(package["card_id"]) for package in packages}
    records = [row for row in records if u32(row, 0) not in package_ids]
    by_id = {u32(row, 0): row for row in records}
    cleared_counts: dict[int, int] = {}

    for package in packages:
        card_id = int(package["card_id"])
        source_id = int(package["source_spell_id"])
        source = by_id.get(source_id)
        if source is None:
            raise PackageError(f"package {card_id}: source spell {source_id} is missing")

        card = bytearray(source)
        set_u32(card, 0, card_id)
        set_u32(card, 37, 1)
        set_u32(card, 38, 1)
        set_u32(card, 39, 1)
        clear_item_requirements(card)
        set_text(card, NAME_FIELDS, strings, str(package["name"]))
        set_text(card, DESCRIPTION_FIELDS, strings, str(package["description"]))
        set_text(card, TOOLTIP_FIELDS, strings, str(package["description"]))
        records.append(card)
        by_id[card_id] = card

        touched: set[int] = set()
        if package.get("remove_item_requirements", False):
            for native_id in package["teaches"]:
                touched.add(int(native_id))
                if native_id in replacements:
                    touched.add(replacements[native_id])
            for spell_id in touched:
                row = by_id.get(spell_id)
                if row is None:
                    raise PackageError(
                        f"package {card_id}: reagent target spell {spell_id} is missing"
                    )
                clear_item_requirements(row)
        cleared_counts[card_id] = len(touched)

    records.sort(key=lambda row: u32(row, 0))
    write_dbc(path, fields, record_size, records, strings, trailing)

    _, _, verify_rows, _, _ = read_dbc(path)
    verify = {u32(row, 0): row for row in verify_rows}
    for package in packages:
        card_id = int(package["card_id"])
        if card_id not in verify:
            raise PackageError(f"package {card_id}: virtual DBC row was not written")
        if package.get("remove_item_requirements", False):
            ids = set(int(value) for value in package["teaches"])
            ids.update(replacements[value] for value in package["teaches"] if value in replacements)
            for spell_id in ids:
                if any(u32(verify[spell_id], field) != 0 for field in ITEM_REQUIREMENT_FIELDS):
                    raise PackageError(f"package {card_id}: reagent survived on {spell_id}")
    return cleared_counts


def table_bounds(lines: list[str], marker: str) -> tuple[int, int]:
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == marker)
    except StopIteration as exc:
        raise PackageError(f"catalog missing {marker}") from exc
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip() == "}"), None)
    if end is None:
        raise PackageError(f"catalog table {marker} is not closed")
    return start, end


def patch_catalog(path: Path, packages: list[dict]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    ids = {int(package["card_id"]) for package in packages}

    start, end = table_bounds(lines, "SpellDraftCatalog = {")
    body = [
        line for line in lines[start + 1:end]
        if not (m := re.match(r"^\s*\{ id = (\d+),", line)) or int(m.group(1)) not in ids
    ]
    for package in packages:
        body.append(
            '  { id = %d, rarity = %d, classSet = %d, minLevel = %d, '
            'name = "%s", virtual = true, grants = {}, requires = {}, synergy = {}, '
            'ranks = { { id = %d, level = 1 } } },'
            % (
                package["card_id"], package["rarity"], package["class_set"],
                package.get("min_level", 1), str(package["name"]).replace('"', '\\"'),
                package["card_id"],
            )
        )
    lines = lines[:start + 1] + body + lines[end:]

    start, end = table_bounds(lines, "SpellDraftTeachMap = {")
    body = [
        line for line in lines[start + 1:end]
        if not (m := re.match(r"^\s*\[(\d+)\]\s*=", line)) or int(m.group(1)) not in ids
    ]
    for package in packages:
        teaches = ", ".join(str(value) for value in package["teaches"])
        body.append(f"  [{package['card_id']}] = {{ {teaches} }},")
    lines = lines[:start + 1] + body + lines[end:]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    final = path.read_text(encoding="utf-8")
    for package in packages:
        card_id = int(package["card_id"])
        if len(re.findall(rf"^\s*\{{ id = {card_id},", final, re.MULTILINE)) != 1:
            raise PackageError(f"package {card_id}: catalog entry validation failed")
        if len(re.findall(rf"^\s*\[{card_id}\]\s*=\s*\{{", final, re.MULTILINE)) != 1:
            raise PackageError(f"package {card_id}: teach map validation failed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dbc-dir", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--resolved", required=True, type=Path)
    parser.add_argument("--packages", type=Path, default=DEFAULT_PACKAGES)
    args = parser.parse_args()

    try:
        packages = load_packages(args.packages.expanduser().resolve())
        replacements = load_replacements(args.resolved.expanduser().resolve())
        cleared = patch_spell_dbc(
            args.dbc_dir.expanduser().resolve() / "Spell.dbc",
            packages,
            replacements,
        )
        patch_catalog(args.catalog.expanduser().resolve(), packages)
    except (DBCError, PackageError, KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"SpellDraft package application aborted: {exc}") from exc

    print("SpellDraft package cards applied and validated:")
    for package in packages:
        card_id = int(package["card_id"])
        print(
            f"  {card_id} {package['name']}: teaches={len(package['teaches'])}, "
            f"reagent/item-requirement rows cleared={cleared[card_id]}"
        )
    print("  virtual package cards are draftable but are not learned as spells")


if __name__ == "__main__":
    main()

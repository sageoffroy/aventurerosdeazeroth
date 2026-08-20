#!/usr/bin/env python3
"""Apply SpellDraft package cards and reviewed eligibility rules."""

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
DEFAULT_ELIGIBILITY_RULES = TOOLS_DIR.parent / "spell_eligibility_rules.json"
SPELL_FIELDS = 234
SPELL_RECORD_SIZE = 936
ITEM_REQUIREMENT_FIELDS = tuple(range(50, 68))
EFFECT_DATA_FIELDS = tuple(range(71, 131))
NAME_FIELDS = tuple(range(136, 152))
DESCRIPTION_FIELDS = tuple(range(170, 186))
TOOLTIP_FIELDS = tuple(range(187, 203))
SPELL_ATTR0_FIELD = 4
SPELL_ATTR0_PASSIVE = 0x00000040
TEAM_IDS = {0, 1}


class PackageError(RuntimeError):
    pass


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackageError(f"cannot read {path}: {exc}") from exc


def validate_spell_id_list(card_id: int, field: str, values: object) -> list[int]:
    if not isinstance(values, list) or any(
        isinstance(value, bool) or not isinstance(value, int) or value <= 0
        for value in values
    ):
        raise PackageError(f"package {card_id}: invalid {field} list")

    cleaned: list[int] = []
    for value in values:
        if value == card_id:
            raise PackageError(f"package {card_id}: {field} cannot contain itself")
        if value not in cleaned:
            cleaned.append(value)
    return cleaned


def load_packages(path: Path) -> list[dict]:
    raw = load_json(path)
    if raw.get("schema_version") != 1 or not isinstance(raw.get("packages"), list):
        raise PackageError(f"{path}: expected schema_version=1 and packages[]")

    packages = raw["packages"]
    seen: set[int] = set()
    for package in packages:
        card_id = package.get("card_id")
        if not isinstance(card_id, int) or not 190000 <= card_id <= 199999:
            raise PackageError("package card IDs must be in 190000-199999")
        if card_id in seen:
            raise PackageError(f"duplicate package card ID {card_id}")

        package["teaches"] = validate_spell_id_list(
            card_id,
            "teaches",
            package.get("teaches", []),
        )
        package["exclude_from_pool"] = validate_spell_id_list(
            card_id,
            "exclude_from_pool",
            package.get("exclude_from_pool", []),
        )

        raw_by_team = package.get("teaches_by_team", {})
        if not isinstance(raw_by_team, dict):
            raise PackageError(f"package {card_id}: teaches_by_team must be an object")
        teaches_by_team: dict[int, list[int]] = {}
        for raw_team, values in raw_by_team.items():
            try:
                team = int(raw_team)
            except (TypeError, ValueError) as exc:
                raise PackageError(
                    f"package {card_id}: invalid team key {raw_team!r}"
                ) from exc
            if team not in TEAM_IDS:
                raise PackageError(f"package {card_id}: unsupported team {team}")
            teaches_by_team[team] = validate_spell_id_list(
                card_id,
                f"teaches_by_team[{team}]",
                values,
            )
        package["teaches_by_team"] = teaches_by_team

        if not package["teaches"] and not any(teaches_by_team.values()):
            raise PackageError(f"package {card_id}: no taught spells configured")

        seen.add(card_id)
    return packages


def load_eligibility_rules(path: Path) -> list[dict]:
    raw = load_json(path)
    if raw.get("schema_version") != 1 or not isinstance(raw.get("rules"), list):
        raise PackageError(f"{path}: expected schema_version=1 and rules[]")

    rules: list[dict] = []
    seen: set[int] = set()
    for rule in raw["rules"]:
        if not isinstance(rule, dict):
            raise PackageError(f"{path}: every eligibility rule must be an object")
        native_root = rule.get("native_root")
        if isinstance(native_root, bool) or not isinstance(native_root, int) or native_root <= 0:
            raise PackageError(f"{path}: invalid eligibility native_root {native_root!r}")
        if native_root in seen:
            raise PackageError(f"{path}: duplicate eligibility rule {native_root}")

        races = rule.get("races", [])
        if not isinstance(races, list) or any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in races
        ):
            raise PackageError(f"{path}: invalid races for {native_root}")

        teams = rule.get("teams", [])
        if not isinstance(teams, list) or any(
            isinstance(value, bool) or not isinstance(value, int) or value not in TEAM_IDS
            for value in teams
        ):
            raise PackageError(f"{path}: invalid teams for {native_root}")

        normalized = dict(rule)
        normalized["races"] = list(dict.fromkeys(races))
        normalized["teams"] = list(dict.fromkeys(teams))
        normalized["force_native"] = bool(rule.get("force_native", False))
        if not normalized["races"] and not normalized["teams"] and not normalized["force_native"]:
            raise PackageError(
                f"{path}: rule {native_root} has no races, teams, or force_native"
            )
        rules.append(normalized)
        seen.add(native_root)
    return rules


def load_replacements(path: Path) -> dict[int, int]:
    raw = load_json(path)
    result: dict[int, int] = {}
    for spell in raw.get("spells", []):
        result[int(spell["clone_from"])] = int(spell["id"])
    return result


def package_teaches(package: dict) -> list[int]:
    result: list[int] = []
    for spell_id in package.get("teaches", []):
        if spell_id not in result:
            result.append(spell_id)
    for team in sorted(package.get("teaches_by_team", {})):
        for spell_id in package["teaches_by_team"][team]:
            if spell_id not in result:
                result.append(spell_id)
    return result


def clear_item_requirements(row: bytearray) -> None:
    for field in ITEM_REQUIREMENT_FIELDS:
        set_u32(row, field, 0)


def make_passive_marker(row: bytearray) -> None:
    set_u32(row, SPELL_ATTR0_FIELD, u32(row, SPELL_ATTR0_FIELD) | SPELL_ATTR0_PASSIVE)

    # Package cards are spellbook markers, not casts. Preserve the source icon,
    # family presentation and localized text, but strip all executable effects.
    for field in EFFECT_DATA_FIELDS:
        set_u32(row, field, 0)

    # No cost, cooldown, duration, proc state or stacked aura belongs on a marker.
    for field in (29, 30, 34, 35, 36, 40, 42, 43, 44, 45, 48, 49, 204, 205, 206, 212):
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
        if package.get("passive_marker", False):
            make_passive_marker(card)
        set_text(card, NAME_FIELDS, strings, str(package["name"]))
        set_text(card, DESCRIPTION_FIELDS, strings, str(package["description"]))
        set_text(card, TOOLTIP_FIELDS, strings, str(package["description"]))
        records.append(card)
        by_id[card_id] = card

        touched: set[int] = set()
        if package.get("remove_item_requirements", False):
            for native_id in package_teaches(package):
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
        card = verify.get(card_id)
        if card is None:
            raise PackageError(f"package {card_id}: package DBC row was not written")
        if package.get("passive_marker", False):
            if u32(card, SPELL_ATTR0_FIELD) & SPELL_ATTR0_PASSIVE == 0:
                raise PackageError(f"package {card_id}: passive attribute was not written")
            if any(u32(card, field) != 0 for field in EFFECT_DATA_FIELDS):
                raise PackageError(f"package {card_id}: executable effect survived on marker")

        if package.get("remove_item_requirements", False):
            ids = set(package_teaches(package))
            ids.update(
                replacements[value]
                for value in package_teaches(package)
                if value in replacements
            )
            for spell_id in ids:
                if any(
                    u32(verify[spell_id], field) != 0
                    for field in ITEM_REQUIREMENT_FIELDS
                ):
                    raise PackageError(f"package {card_id}: reagent survived on {spell_id}")
    return cleared_counts


def table_bounds(lines: list[str], marker: str) -> tuple[int, int]:
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == marker)
    except StopIteration as exc:
        raise PackageError(f"catalog missing {marker}") from exc
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].strip() == "}"),
        None,
    )
    if end is None:
        raise PackageError(f"catalog table {marker} is not closed")
    return start, end


def optional_table_bounds(lines: list[str], marker: str) -> tuple[int, int] | None:
    try:
        return table_bounds(lines, marker)
    except PackageError as exc:
        if f"catalog missing {marker}" in str(exc):
            return None
        raise


def runtime_catalog_ids(native_ids: set[int], replacements: dict[int, int]) -> set[int]:
    result = set(native_ids)
    result.update(replacements[value] for value in native_ids if value in replacements)
    return result


def patch_catalog_entry_eligibility(
    body: list[str],
    rule: dict,
    replacements: dict[int, int],
) -> tuple[list[str], int]:
    native_root = int(rule["native_root"])
    runtime_id = replacements.get(native_root, native_root)
    candidates = {native_root, runtime_id}

    matches: list[int] = []
    for index, line in enumerate(body):
        match = re.match(r"^\s*\{ id = (\d+),", line)
        if match and int(match.group(1)) in candidates:
            matches.append(index)

    if len(matches) != 1:
        raise PackageError(
            f"eligibility rule {native_root}: expected one catalog entry, found {len(matches)}"
        )

    index = matches[0]
    line = body[index]
    current_match = re.match(r"^\s*\{ id = (\d+),", line)
    assert current_match is not None
    current_id = int(current_match.group(1))

    if rule.get("force_native", False) and current_id != native_root:
        line = re.sub(rf"\b{current_id}\b", str(native_root), line)
        current_id = native_root

    # Idempotently replace our simple per-entry team/race metadata.
    line = re.sub(r"(?:teams|races) = \{[^}]*\}, ", "", line)
    metadata: list[str] = []
    if rule.get("teams"):
        metadata.append(
            "teams = { " + ", ".join(str(value) for value in rule["teams"]) + " }, "
        )
    if rule.get("races"):
        metadata.append(
            "races = { " + ", ".join(str(value) for value in rule["races"]) + " }, "
        )
    if metadata:
        marker = "grants = {"
        if marker not in line:
            raise PackageError(f"eligibility rule {native_root}: catalog entry has no grants field")
        line = line.replace(marker, "".join(metadata) + marker, 1)

    body[index] = line
    return body, current_id


def patch_catalog(
    path: Path,
    packages: list[dict],
    replacements: dict[int, int],
    eligibility_rules: list[dict],
) -> tuple[int, dict[int, int]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    package_ids = {int(package["card_id"]) for package in packages}

    native_remove: set[int] = set()
    for package in packages:
        native_remove.update(package_teaches(package))
        native_remove.update(int(value) for value in package["exclude_from_pool"])
    remove_ids = runtime_catalog_ids(native_remove, replacements)
    remove_ids.update(package_ids)

    start, end = table_bounds(lines, "SpellDraftCatalog = {")
    original_body = lines[start + 1:end]
    body: list[str] = []
    removed = 0
    for line in original_body:
        match = re.match(r"^\s*\{ id = (\d+),", line)
        if match and int(match.group(1)) in remove_ids:
            removed += 1
            continue
        body.append(line)

    eligibility_runtime_ids: dict[int, int] = {}
    for rule in eligibility_rules:
        body, final_id = patch_catalog_entry_eligibility(body, rule, replacements)
        eligibility_runtime_ids[int(rule["native_root"])] = final_id

    for package in packages:
        body.append(
            '  { id = %d, rarity = %d, classSet = %d, minLevel = %d, '
            'name = "%s", package = true, grants = {}, requires = {}, synergy = {}, '
            'ranks = { { id = %d, level = 1 } } },'
            % (
                package["card_id"],
                package["rarity"],
                package["class_set"],
                package.get("min_level", 1),
                str(package["name"]).replace('"', '\\"'),
                package["card_id"],
            )
        )
    lines = lines[:start + 1] + body + lines[end:]

    start, end = table_bounds(lines, "SpellDraftTeachMap = {")
    body = [
        line
        for line in lines[start + 1:end]
        if not (match := re.match(r"^\s*\[(\d+)\]\s*=", line))
        or int(match.group(1)) not in package_ids
    ]
    for package in packages:
        teaches = ", ".join(str(value) for value in package["teaches"])
        body.append(f"  [{package['card_id']}] = {{ {teaches} }},")
    lines = lines[:start + 1] + body + lines[end:]

    existing = optional_table_bounds(lines, "SpellDraftTeachTeamMap = {")
    if existing is not None:
        team_start, team_end = existing
        lines = lines[:team_start] + lines[team_end + 1:]

    _, teach_end = table_bounds(lines, "SpellDraftTeachMap = {")
    team_table = ["", "SpellDraftTeachTeamMap = {"]
    for package in packages:
        by_team = package.get("teaches_by_team", {})
        if not by_team:
            continue
        team_table.append(f"  [{package['card_id']}] = {{")
        for team in sorted(by_team):
            values = ", ".join(str(value) for value in by_team[team])
            team_table.append(f"    [{team}] = {{ {values} }},")
        team_table.append("  },")
    team_table.append("}")
    lines = lines[:teach_end + 1] + team_table + lines[teach_end + 1:]

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    final = path.read_text(encoding="utf-8")
    final_catalog_ids = {
        int(value)
        for value in re.findall(r"^\s*\{ id = (\d+),", final, re.MULTILINE)
    }
    leftover = sorted(runtime_catalog_ids(native_remove, replacements) & final_catalog_ids)
    if leftover:
        raise PackageError(
            "package-owned spells survived catalog compression: "
            + ", ".join(str(value) for value in leftover)
        )

    for package in packages:
        card_id = int(package["card_id"])
        if len(re.findall(rf"^\s*\{{ id = {card_id},", final, re.MULTILINE)) != 1:
            raise PackageError(f"package {card_id}: catalog entry validation failed")
        if len(
            re.findall(rf"^\s*\[{card_id}\]\s*=\s*\{{", final, re.MULTILINE)
        ) < 1:
            raise PackageError(f"package {card_id}: teach map validation failed")
        if package.get("teaches_by_team") and "SpellDraftTeachTeamMap = {" not in final:
            raise PackageError(f"package {card_id}: team teach map validation failed")

    for rule in eligibility_rules:
        native_root = int(rule["native_root"])
        expected_id = eligibility_runtime_ids[native_root]
        if len(re.findall(rf"^\s*\{{ id = {expected_id},", final, re.MULTILINE)) != 1:
            raise PackageError(f"eligibility rule {native_root}: final ID validation failed")
        if rule.get("force_native", False):
            custom_id = replacements.get(native_root)
            if custom_id and custom_id in final_catalog_ids:
                raise PackageError(
                    f"eligibility rule {native_root}: custom travel clone {custom_id} survived"
                )

    return removed, eligibility_runtime_ids


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dbc-dir", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--resolved", required=True, type=Path)
    parser.add_argument("--packages", type=Path, default=DEFAULT_PACKAGES)
    parser.add_argument(
        "--eligibility-rules",
        type=Path,
        default=DEFAULT_ELIGIBILITY_RULES,
    )
    args = parser.parse_args()

    try:
        packages = load_packages(args.packages.expanduser().resolve())
        eligibility_rules = load_eligibility_rules(
            args.eligibility_rules.expanduser().resolve()
        )
        replacements = load_replacements(args.resolved.expanduser().resolve())
        cleared = patch_spell_dbc(
            args.dbc_dir.expanduser().resolve() / "Spell.dbc",
            packages,
            replacements,
        )
        removed, eligibility_runtime_ids = patch_catalog(
            args.catalog.expanduser().resolve(),
            packages,
            replacements,
            eligibility_rules,
        )
    except (DBCError, PackageError, KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"SpellDraft package application aborted: {exc}") from exc

    print("SpellDraft package cards and eligibility rules applied and validated:")
    for package in packages:
        card_id = int(package["card_id"])
        print(
            f"  {card_id} {package['name']}: teaches={len(package_teaches(package))}, "
            f"reagent/item-requirement rows cleared={cleared[card_id]}"
        )
    print(f"  individual package-owned draft cards removed: {removed}")
    for rule in eligibility_rules:
        native_root = int(rule["native_root"])
        print(
            f"  eligibility {native_root}: runtime_id={eligibility_runtime_ids[native_root]}, "
            f"races={rule['races']}, teams={rule['teams']}"
        )
    print("  passive package cards remain learned as spellbook markers")


if __name__ == "__main__":
    main()

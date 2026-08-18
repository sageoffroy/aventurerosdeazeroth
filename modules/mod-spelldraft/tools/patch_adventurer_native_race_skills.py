#!/usr/bin/env python3
"""Make native race and starter-spell skill lines valid for Adventurer class 10.

AzerothCore validates learned spells against SkillRaceClassInfo.dbc while a
character is loaded. The stock rows do not know about class ID 10, so otherwise
perfectly valid Adventurer baseline spells can be deleted on login with errors
such as Auto Shot -> Marksmanship (163) or Brown Horse -> Mounts (777).

This patch has two deliberately separate responsibilities:

* extend stock race-native language/racial rows to class 10 without broadening
  their race restrictions;
* add class-10-only wildcard race mappings for skill lines required by baseline
  Adventurer spells that are valid for every playable race.

It does not make those skill lines available to any other class.
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

MAGIC = b"WDBC"
HEADER = struct.Struct("<4sIIII")
ADVENTURER_CLASS = 10
ADVENTURER_CLASS_MASK = 1 << (ADVENTURER_CLASS - 1)  # 512
PLAYABLE_RACES = (1, 2, 3, 4, 5, 6, 7, 8, 10, 11)

# Skill lines referenced by permanent Adventurer baseline spells. These are not
# necessarily visible skills we want to grant at creation; SkillRaceClassInfo
# must merely accept them for class 10 so AzerothCore does not delete the spell.
ADVENTURER_BASELINE_SPELL_SKILLS = {
    163,  # Marksmanship: Auto Shot (75)
    762,  # Riding: Apprentice Riding (33388)
    777,  # Mounts: Brown Horse (458)
}

# Stock WotLK race-native skill lines. Faction language is included for every
# race because it is what chat/addon traffic needs immediately on first login.
RACE_NATIVE_SKILLS: dict[int, tuple[int, ...]] = {
    1: (98, 754),            # Human: Common, Human racial
    2: (109, 125),           # Orc: Orcish, Orc racial
    3: (98, 111, 101),       # Dwarf: Common, Dwarven, Dwarf racial
    4: (98, 113, 126),       # Night Elf: Common, Darnassian, Night Elf racial
    5: (109, 673, 220),      # Undead: Orcish, Gutterspeak, Undead racial
    6: (109, 115, 124),      # Tauren: Orcish, Taurahe, Tauren racial
    7: (98, 313, 753),       # Gnome: Common, Gnomish, Gnome racial
    8: (109, 315, 733),      # Troll: Orcish, Troll, Troll racial
    10: (109, 137, 756),     # Blood Elf: Orcish, Thalassian, Blood Elf racial
    11: (98, 759, 760),      # Draenei: Common, Draenei, Draenei racial
}


class DBCError(RuntimeError):
    pass


def read_dbc(path: Path):
    data = path.read_bytes()
    if len(data) < HEADER.size:
        raise DBCError(f"{path}: file is too small")

    magic, count, fields, record_size, string_size = HEADER.unpack_from(data)
    if magic != MAGIC:
        raise DBCError(f"{path}: expected WDBC, got {magic!r}")

    records_start = HEADER.size
    records_end = records_start + count * record_size
    strings_end = records_end + string_size
    if strings_end > len(data):
        raise DBCError(f"{path}: header sizes exceed file size")

    records = [
        bytearray(data[records_start + i * record_size: records_start + (i + 1) * record_size])
        for i in range(count)
    ]
    strings = data[records_end:strings_end]
    trailing = data[strings_end:]
    return fields, record_size, records, strings, trailing


def write_dbc(
    path: Path,
    fields: int,
    record_size: int,
    records: list[bytearray],
    strings: bytes,
    trailing: bytes,
) -> None:
    header = HEADER.pack(MAGIC, len(records), fields, record_size, len(strings))
    path.write_bytes(header + b"".join(records) + strings + trailing)


def u32(record: bytearray, field: int) -> int:
    return struct.unpack_from("<I", record, field * 4)[0]


def set_u32(record: bytearray, field: int, value: int) -> None:
    struct.pack_into("<I", record, field * 4, value)


def race_bit(race: int) -> int:
    return 1 << (race - 1)


def row_applies_to_race(row: bytearray, race: int) -> bool:
    race_mask = u32(row, 2)
    return race_mask == 0 or bool(race_mask & race_bit(race))


def row_applies_to_adventurer(row: bytearray) -> bool:
    class_mask = u32(row, 3)
    return class_mask == 0 or bool(class_mask & ADVENTURER_CLASS_MASK)


def desired_pairs() -> set[tuple[int, int]]:
    return {
        (race, skill)
        for race, skills in RACE_NATIVE_SKILLS.items()
        for skill in skills
    }


def covers_all_adventurer_races(records: list[bytearray], skill: int) -> bool:
    return all(
        any(
            u32(row, 1) == skill
            and row_applies_to_race(row, race)
            and row_applies_to_adventurer(row)
            for row in records
        )
        for race in PLAYABLE_RACES
    )


def choose_skill_template(records: list[bytearray], skill: int) -> bytearray:
    candidates = [row for row in records if u32(row, 1) == skill]
    if not candidates:
        raise DBCError(
            f"SkillRaceClassInfo.dbc has no stock template row for required skill {skill}"
        )

    # Prefer the broadest stock class mapping, then the lowest minimum level.
    # We keep the remaining flags/tier/cost fields from Blizzard's own row.
    def template_key(row: bytearray) -> tuple[int, int, int]:
        class_mask = u32(row, 3)
        race_mask = u32(row, 2)
        class_width = 32 if class_mask == 0 else class_mask.bit_count()
        race_width = 32 if race_mask == 0 else race_mask.bit_count()
        return (-class_width, u32(row, 5), -race_width)

    return min(candidates, key=template_key)


def ensure_baseline_spell_skill_rows(records: list[bytearray]) -> bool:
    changed = False
    next_id = max((u32(row, 0) for row in records), default=0) + 1

    for skill in sorted(ADVENTURER_BASELINE_SPELL_SKILLS):
        if covers_all_adventurer_races(records, skill):
            continue

        template = bytearray(choose_skill_template(records, skill))
        set_u32(template, 0, next_id)
        set_u32(template, 2, 0)  # raceMask wildcard: every playable race
        set_u32(template, 3, ADVENTURER_CLASS_MASK)  # class 10 only
        records.append(template)
        next_id += 1
        changed = True

    if changed:
        records.sort(key=lambda row: u32(row, 0))
    return changed


def patch_skillraceclassinfo(path: Path) -> bool:
    fields, record_size, records, strings, trailing = read_dbc(path)
    if fields != 8 or record_size != 32:
        raise DBCError(
            f"{path}: unexpected SkillRaceClassInfo layout "
            f"{fields} fields / {record_size} bytes"
        )

    wanted = desired_pairs()
    changed = False

    for row in records:
        skill = u32(row, 1)
        class_mask = u32(row, 3)

        # classMask == 0 is already a wildcard and needs no modification.
        if class_mask == 0:
            continue

        should_extend = any(
            wanted_skill == skill and row_applies_to_race(row, race)
            for race, wanted_skill in wanted
        )
        if not should_extend:
            continue

        new_mask = class_mask | ADVENTURER_CLASS_MASK
        if new_mask != class_mask:
            set_u32(row, 3, new_mask)
            changed = True

    if ensure_baseline_spell_skill_rows(records):
        changed = True

    if changed:
        write_dbc(path, fields, record_size, records, strings, trailing)

    validate_skillraceclassinfo(path)
    return changed


def validate_skillraceclassinfo(path: Path) -> None:
    fields, record_size, records, _, _ = read_dbc(path)
    if fields != 8 or record_size != 32:
        raise DBCError(f"{path}: unexpected SkillRaceClassInfo layout during validation")

    missing: list[tuple[int, int]] = []
    for race, skills in RACE_NATIVE_SKILLS.items():
        for skill in skills:
            valid = any(
                u32(row, 1) == skill
                and row_applies_to_race(row, race)
                and row_applies_to_adventurer(row)
                for row in records
            )
            if not valid:
                missing.append((race, skill))

    if missing:
        raise DBCError(
            f"{path}: Adventurer still lacks native race skill mappings: {missing}"
        )

    missing_baseline = [
        skill
        for skill in sorted(ADVENTURER_BASELINE_SPELL_SKILLS)
        if not covers_all_adventurer_races(records, skill)
    ]
    if missing_baseline:
        raise DBCError(
            f"{path}: Adventurer baseline spell skill mappings are missing: "
            f"{missing_baseline}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "dbc_dir",
        type=Path,
        help="Directory containing SkillRaceClassInfo.dbc",
    )
    args = parser.parse_args()

    path = args.dbc_dir.expanduser().resolve() / "SkillRaceClassInfo.dbc"
    if not path.is_file():
        raise SystemExit(f"Missing required DBC: {path}")

    try:
        changed = patch_skillraceclassinfo(path)
    except DBCError as exc:
        raise SystemExit(f"Adventurer native skill patch aborted: {exc}") from exc

    print("Adventurer native skills validated in SkillRaceClassInfo.dbc:")
    print(f"  status: {'patched' if changed else 'already valid'}")
    print("  faction languages: Common 98 / Orcish 109")
    print("  racial languages and racial skill lines: valid for class 10")
    print("  baseline spell skills: 163 Marksmanship, 762 Riding, 777 Mounts")


if __name__ == "__main__":
    main()

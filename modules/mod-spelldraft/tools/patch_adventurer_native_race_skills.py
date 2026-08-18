#!/usr/bin/env python3
"""Make native class/race skill lines valid for Adventurer class ID 10.

AzerothCore validates learned spells against SkillRaceClassInfo.dbc while a
character is loaded. A classless Adventurer can draft spells from every stock
class, so class ID 10 must be valid for the class-bound skill lines behind those
spells. Otherwise a learned spell can be removed on the next login with errors
such as Auto Shot -> Marksmanship (163) or Brown Horse -> Mounts (777).

This patch has two deliberately separate responsibilities:

* preserve race restrictions for stock language/racial skill lines while
  extending the correct race/class combinations to class 10;
* create class-10-only, all-races mappings for every stock skill line that is
  bound to one or more classes. This authorizes classless spells without
  granting the skill at character creation and without changing any other
  class.
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

# Permanent baseline spells that exposed the problem first. Validation keeps
# these explicit sentinels even though the generic classless mapping below now
# covers every class-bound skill line used by future SpellDraft picks as well.
BASELINE_SPELL_SKILLS = {
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
RACE_NATIVE_SKILL_IDS = {
    skill
    for skills in RACE_NATIVE_SKILLS.values()
    for skill in skills
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


def desired_race_pairs() -> set[tuple[int, int]]:
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

    # Prefer Blizzard's broadest class mapping, then its lowest minimum level.
    # Flags/tier/cost remain copied from the stock row.
    def template_key(row: bytearray) -> tuple[int, int, int]:
        class_mask = u32(row, 3)
        race_mask = u32(row, 2)
        class_width = 32 if class_mask == 0 else class_mask.bit_count()
        race_width = 32 if race_mask == 0 else race_mask.bit_count()
        return (-class_width, u32(row, 5), -race_width)

    return min(candidates, key=template_key)


def class_bound_skill_ids(records: list[bytearray]) -> set[int]:
    return {
        u32(row, 1)
        for row in records
        if u32(row, 3) != 0 and u32(row, 1) not in RACE_NATIVE_SKILL_IDS
    }


def ensure_classless_class_skill_rows(records: list[bytearray]) -> bool:
    """Give class 10 its own all-races mapping for every class-bound skill."""

    changed = False
    next_id = max((u32(row, 0) for row in records), default=0) + 1
    skills = sorted(class_bound_skill_ids(records))

    for skill in skills:
        if covers_all_adventurer_races(records, skill):
            continue

        clone = bytearray(choose_skill_template(records, skill))
        set_u32(clone, 0, next_id)
        set_u32(clone, 2, 0)  # raceMask wildcard: every race for Adventurer only
        set_u32(clone, 3, ADVENTURER_CLASS_MASK)
        records.append(clone)
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

    wanted = desired_race_pairs()
    changed = False

    # Race-native rows are extended only where the stock race mask already
    # authorizes that race. This keeps Common/Orcish/racial languages correct.
    for row in records:
        skill = u32(row, 1)
        class_mask = u32(row, 3)
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

    if ensure_classless_class_skill_rows(records):
        changed = True

    if changed:
        write_dbc(path, fields, record_size, records, strings, trailing)

    validate_skillraceclassinfo(path)
    return changed


def validate_skillraceclassinfo(path: Path) -> None:
    fields, record_size, records, _, _ = read_dbc(path)
    if fields != 8 or record_size != 32:
        raise DBCError(f"{path}: unexpected SkillRaceClassInfo layout during validation")

    missing_racial: list[tuple[int, int]] = []
    for race, skills in RACE_NATIVE_SKILLS.items():
        for skill in skills:
            valid = any(
                u32(row, 1) == skill
                and row_applies_to_race(row, race)
                and row_applies_to_adventurer(row)
                for row in records
            )
            if not valid:
                missing_racial.append((race, skill))

    if missing_racial:
        raise DBCError(
            f"{path}: Adventurer still lacks native race skill mappings: "
            f"{missing_racial}"
        )

    missing_classless = [
        skill
        for skill in sorted(class_bound_skill_ids(records))
        if not covers_all_adventurer_races(records, skill)
    ]
    if missing_classless:
        raise DBCError(
            f"{path}: Adventurer still lacks classless skill mappings: "
            f"{missing_classless}"
        )

    missing_baseline = [
        skill
        for skill in sorted(BASELINE_SPELL_SKILLS)
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

    print("Adventurer native/classless skills validated in SkillRaceClassInfo.dbc:")
    print(f"  status: {'patched' if changed else 'already valid'}")
    print("  faction languages: Common 98 / Orcish 109")
    print("  racial languages/racial skill lines: preserve race restrictions")
    print("  all class-bound skill lines: valid for Adventurer on all playable races")
    print("  baseline sentinels: 163 Marksmanship, 762 Riding, 777 Mounts")


if __name__ == "__main__":
    main()

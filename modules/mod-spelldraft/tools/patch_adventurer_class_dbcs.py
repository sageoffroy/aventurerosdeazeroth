#!/usr/bin/env python3
"""Add native class ID 10 (Aventurero) to WotLK 3.3.5a DBC files.

This patcher is intentionally sanitizing, not merely additive. The server is
classless: every playable race must have exactly one available creation class,
Aventurero (class ID 10). CharBaseInfo.dbc is therefore rebuilt to contain only
those ten race/class pairs. No vanilla class remains available at character
creation.
"""

from __future__ import annotations

import argparse
import shutil
import struct
from pathlib import Path

MAGIC = b"WDBC"
HEADER = struct.Struct("<4sIIII")
ADVENTURER_CLASS = 10
ADVENTURER_CLASS_MASK = 1 << (ADVENTURER_CLASS - 1)  # 0x200 / 512
PLAYABLE_RACES = (1, 2, 3, 4, 5, 6, 7, 8, 10, 11)

UNIVERSAL_SKILLS = {
    43, 44, 45, 46, 54, 55, 95, 136, 160, 162, 172, 173, 176,
    226, 228, 229, 293, 413, 414, 415, 433, 473,
}

MAX_OUTFIT_ITEMS = 24
CHARSTART_ITEM_IDS_OFFSET = 8
CHARSTART_DISPLAY_IDS_OFFSET = CHARSTART_ITEM_IDS_OFFSET + MAX_OUTFIT_ITEMS * 4
CHARSTART_INVENTORY_TYPES_OFFSET = CHARSTART_DISPLAY_IDS_OFFSET + MAX_OUTFIT_ITEMS * 4
CHARSTART_FULL_RECORD_SIZE = CHARSTART_INVENTORY_TYPES_OFFSET + MAX_OUTFIT_ITEMS * 4

ADVENTURER_STARTER_ITEMS = (
    25,    # Worn Short Sword
    2362,  # Worn Wooden Shield
    2504,  # Worn Short Bow
    2512,  # Rough Arrow (BuyCount determines the created stack size)
)

# InventoryType values that represent combat equipment we replace with the
# universal Adventurer starter kit. Clothing, bags and miscellaneous starter
# items from the race-specific Warrior template are preserved.
REPLACED_COMBAT_INVENTORY_TYPES = {
    13,  # Weapon
    14,  # Shield
    15,  # Ranged
    17,  # Two-Handed Weapon
    21,  # Main Hand
    22,  # Off Hand
    23,  # Holdable
    24,  # Ammo
    25,  # Thrown
    26,  # Ranged Right
    28,  # Relic
}

# Used only when the item does not appear in any stock CharStartOutfit row.
# ItemId is what the server uses to grant the item; these values keep the client
# metadata structurally sane for the patched row.
STARTER_ITEM_FALLBACK_INVENTORY_TYPE = {
    25: 13,
    2362: 14,
    2504: 15,
    2512: 24,
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
    strings = bytearray(data[records_end:strings_end])
    trailing = data[strings_end:]
    return fields, record_size, records, strings, trailing


def write_dbc(path: Path, fields: int, record_size: int, records: list[bytearray], strings: bytearray, trailing: bytes):
    header = HEADER.pack(MAGIC, len(records), fields, record_size, len(strings))
    path.write_bytes(header + b"".join(records) + strings + trailing)


def append_string(strings: bytearray, value: str) -> int:
    encoded = value.encode("utf-8") + b"\x00"
    pos = bytes(strings).find(encoded)
    if pos >= 0:
        return pos
    pos = len(strings)
    strings.extend(encoded)
    return pos


def u32(record: bytearray, field: int) -> int:
    return struct.unpack_from("<I", record, field * 4)[0]


def set_u32(record: bytearray, field: int, value: int):
    struct.pack_into("<I", record, field * 4, value)


def desired_charbase_pairs() -> set[tuple[int, int]]:
    return {(race, ADVENTURER_CLASS) for race in PLAYABLE_RACES}


def patch_chrclasses(path: Path) -> bool:
    fields, record_size, records, strings, trailing = read_dbc(path)
    if fields != 60 or record_size != 240:
        raise DBCError(f"{path}: unexpected ChrClasses layout {fields} fields / {record_size} bytes")

    original = [bytes(r) for r in records]
    targets = [r for r in records if u32(r, 0) == ADVENTURER_CLASS]

    if targets:
        target = targets[0]
        records = [r for r in records if u32(r, 0) != ADVENTURER_CLASS or r is target]
    else:
        template = next((r for r in records if u32(r, 0) == 1), None)
        if template is None:
            raise DBCError(f"{path}: Warrior template row (class 1) not found")
        target = bytearray(template)
        records.append(target)

    set_u32(target, 0, ADVENTURER_CLASS)
    set_u32(target, 2, 0)  # DisplayPower = Mana

    names = (
        (range(4, 20), "Aventurero"),
        (range(21, 37), "Aventurera"),
        (range(38, 54), "Aventurero"),
    )
    for fields_range, value in names:
        off = append_string(strings, value)
        active_fields = [field for field in fields_range if u32(target, field) != 0]
        if not active_fields:
            active_fields = [next(iter(fields_range))]
        for field in active_fields:
            set_u32(target, field, off)

    # Keep Warrior's client file token only for stock icon/color compatibility.
    # Class identity and server behavior are class ID 10.
    set_u32(target, 56, 0)  # generic spell class set/family
    set_u32(target, 58, 0)  # no class-specific cinematic
    set_u32(target, 59, 0)  # Classic availability

    # Keep DBC enumeration deterministic: class 10 sits between 9 and 11.
    records.sort(key=lambda r: u32(r, 0))

    changed = original != [bytes(r) for r in records]
    if changed:
        write_dbc(path, fields, record_size, records, strings, trailing)
    return changed


def patch_charbaseinfo(path: Path) -> bool:
    fields, record_size, records, strings, trailing = read_dbc(path)
    if fields != 2 or record_size != 2:
        raise DBCError(f"{path}: unexpected CharBaseInfo layout {fields} fields / {record_size} bytes")

    # This server has only one playable class. Rebuild the entire file so old
    # experiments or stock race/class pairs cannot leak into character creation.
    normalized = sorted(desired_charbase_pairs())
    current = [(r[0], r[1]) for r in records]

    if current != normalized:
        records = [bytearray((race, class_id)) for race, class_id in normalized]
        write_dbc(path, fields, record_size, records, strings, trailing)
        return True
    return False


def validate_charbaseinfo(path: Path):
    fields, record_size, records, _, _ = read_dbc(path)
    if fields != 2 or record_size != 2:
        raise DBCError(f"{path}: unexpected CharBaseInfo layout during validation")

    actual_list = [(r[0], r[1]) for r in records]
    desired_list = sorted(desired_charbase_pairs())
    if actual_list != desired_list:
        raise DBCError(
            f"{path}: expected ONLY the ten Adventurer combinations; actual={actual_list}"
        )


def read_outfit_entry(record: bytearray, index: int) -> tuple[int, int, int]:
    item_id = struct.unpack_from("<i", record, CHARSTART_ITEM_IDS_OFFSET + index * 4)[0]
    display_id = struct.unpack_from("<i", record, CHARSTART_DISPLAY_IDS_OFFSET + index * 4)[0]
    inventory_type = struct.unpack_from("<i", record, CHARSTART_INVENTORY_TYPES_OFFSET + index * 4)[0]
    return item_id, display_id, inventory_type


def write_outfit_entry(record: bytearray, index: int, item_id: int, display_id: int, inventory_type: int):
    struct.pack_into("<i", record, CHARSTART_ITEM_IDS_OFFSET + index * 4, item_id)
    struct.pack_into("<i", record, CHARSTART_DISPLAY_IDS_OFFSET + index * 4, display_id)
    struct.pack_into("<i", record, CHARSTART_INVENTORY_TYPES_OFFSET + index * 4, inventory_type)


def collect_outfit_item_metadata(records: list[bytearray]) -> dict[int, tuple[int, int]]:
    metadata: dict[int, tuple[int, int]] = {}
    wanted = set(ADVENTURER_STARTER_ITEMS)
    for row in records:
        for index in range(MAX_OUTFIT_ITEMS):
            item_id, display_id, inventory_type = read_outfit_entry(row, index)
            if item_id in wanted and item_id not in metadata:
                metadata[item_id] = (display_id, inventory_type)
    return metadata


def apply_adventurer_starter_outfit(
    row: bytearray,
    starter_metadata: dict[int, tuple[int, int]],
):
    preserved: list[tuple[int, int, int]] = []

    for index in range(MAX_OUTFIT_ITEMS):
        item_id, display_id, inventory_type = read_outfit_entry(row, index)
        if item_id <= 0 or item_id in ADVENTURER_STARTER_ITEMS:
            continue
        if inventory_type in REPLACED_COMBAT_INVENTORY_TYPES:
            continue
        preserved.append((item_id, display_id, inventory_type))

    starter_entries: list[tuple[int, int, int]] = []
    for item_id in ADVENTURER_STARTER_ITEMS:
        display_id, inventory_type = starter_metadata.get(
            item_id,
            (0, STARTER_ITEM_FALLBACK_INVENTORY_TYPE[item_id]),
        )
        starter_entries.append((item_id, display_id, inventory_type))

    entries = preserved + starter_entries
    if len(entries) > MAX_OUTFIT_ITEMS:
        raise DBCError(
            f"Adventurer starter outfit exceeds {MAX_OUTFIT_ITEMS} items: {len(entries)}"
        )

    for index in range(MAX_OUTFIT_ITEMS):
        write_outfit_entry(row, index, 0, 0, 0)

    for index, (item_id, display_id, inventory_type) in enumerate(entries):
        write_outfit_entry(row, index, item_id, display_id, inventory_type)


def patch_charstartoutfit(path: Path) -> bool:
    fields, record_size, records, strings, trailing = read_dbc(path)
    if record_size < CHARSTART_FULL_RECORD_SIZE:
        raise DBCError(
            f"{path}: unexpected CharStartOutfit layout {fields} fields / {record_size} bytes"
        )

    # Snapshot the file BEFORE mutating existing Adventurer rows. Otherwise the
    # change detector can compare the rebuilt rows against already-mutated
    # objects and incorrectly decide that nothing changed.
    original = [bytes(r) for r in records]

    def row_id(r: bytearray) -> int:
        return struct.unpack_from("<I", r, 0)[0]

    def key(r: bytearray):
        return r[4], r[5], r[6]  # race, class, gender

    # Vanilla outfit rows remain only as templates/data. They do not make those
    # classes creatable because CharBaseInfo exposes only class 10.
    vanilla_rows = [r for r in records if r[5] != ADVENTURER_CLASS]
    existing_adventurer = {key(r): r for r in records if r[5] == ADVENTURER_CLASS}
    starter_metadata = collect_outfit_item_metadata(vanilla_rows)
    next_id = max((row_id(r) for r in vanilla_rows), default=0) + 1
    rebuilt = list(vanilla_rows)

    for race in PLAYABLE_RACES:
        for gender in (0, 1):
            wanted = (race, ADVENTURER_CLASS, gender)
            row = existing_adventurer.get(wanted)
            if row is None:
                template = next((r for r in vanilla_rows if key(r) == (race, 1, gender)), None)
                if template is None:
                    template = next(
                        (r for r in vanilla_rows if r[4] == race and r[6] == gender and r[5] != 6),
                        None,
                    )
                if template is None:
                    raise DBCError(f"{path}: no starter outfit template for race={race}, gender={gender}")
                row = bytearray(template)
                struct.pack_into("<I", row, 0, next_id)
                next_id += 1
                row[5] = ADVENTURER_CLASS

            apply_adventurer_starter_outfit(row, starter_metadata)
            rebuilt.append(row)

    rebuilt.sort(key=lambda r: (r[4], r[5], r[6], row_id(r)))
    changed = original != [bytes(r) for r in rebuilt]
    if changed:
        write_dbc(path, fields, record_size, rebuilt, strings, trailing)
    return changed


def validate_charstartoutfit(path: Path):
    _, record_size, records, _, _ = read_dbc(path)
    if record_size < CHARSTART_FULL_RECORD_SIZE:
        raise DBCError(f"{path}: unexpected CharStartOutfit layout during validation")

    starter_set = set(ADVENTURER_STARTER_ITEMS)
    seen: set[tuple[int, int, int]] = set()

    for row in records:
        if row[5] != ADVENTURER_CLASS:
            continue

        key = (row[4], row[5], row[6])
        if key in seen:
            raise DBCError(f"{path}: duplicate Adventurer starter outfit row {key}")
        seen.add(key)

        item_ids = {
            read_outfit_entry(row, index)[0]
            for index in range(MAX_OUTFIT_ITEMS)
            if read_outfit_entry(row, index)[0] > 0
        }
        missing = starter_set - item_ids
        if missing:
            raise DBCError(f"{path}: Adventurer outfit {key} is missing starter items {sorted(missing)}")

    expected = {
        (race, ADVENTURER_CLASS, gender)
        for race in PLAYABLE_RACES
        for gender in (0, 1)
    }
    if seen != expected:
        raise DBCError(
            f"{path}: expected 20 Adventurer race/gender outfit rows; actual={sorted(seen)}"
        )


def patch_skillraceclassinfo(path: Path) -> bool:
    fields, record_size, records, strings, trailing = read_dbc(path)
    if fields != 8 or record_size != 32:
        raise DBCError(f"{path}: unexpected SkillRaceClassInfo layout {fields} fields / {record_size} bytes")

    changed = False
    for row in records:
        skill = u32(row, 1)
        class_mask = u32(row, 3)
        if skill not in UNIVERSAL_SKILLS or class_mask == 0:
            continue
        new_mask = class_mask | ADVENTURER_CLASS_MASK
        if new_mask != class_mask:
            set_u32(row, 3, new_mask)
            changed = True

    if changed:
        write_dbc(path, fields, record_size, records, strings, trailing)
    return changed


def backup(path: Path):
    backup_path = path.with_name(path.name + ".pre-adventurer.bak")
    if not backup_path.exists():
        shutil.copy2(path, backup_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dbc_dir", type=Path, help="Directory containing extracted/server WotLK DBC files")
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()

    dbc_dir = args.dbc_dir.resolve()
    required = {
        "ChrClasses.dbc": patch_chrclasses,
        "CharBaseInfo.dbc": patch_charbaseinfo,
        "CharStartOutfit.dbc": patch_charstartoutfit,
    }
    optional = {"SkillRaceClassInfo.dbc": patch_skillraceclassinfo}

    for filename in required:
        if not (dbc_dir / filename).is_file():
            raise SystemExit(f"Missing required DBC: {dbc_dir / filename}")

    results: list[tuple[str, str]] = []
    try:
        for filename, patcher in {**required, **optional}.items():
            path = dbc_dir / filename
            if not path.exists():
                results.append((filename, "not present (optional)"))
                continue
            if not args.no_backup:
                backup(path)
            changed = patcher(path)
            results.append((filename, "patched/sanitized" if changed else "already clean"))

        validate_charbaseinfo(dbc_dir / "CharBaseInfo.dbc")
        validate_charstartoutfit(dbc_dir / "CharStartOutfit.dbc")
    except DBCError as exc:
        raise SystemExit(f"Adventurer DBC patch aborted: {exc}") from exc

    print("Adventurer class-10 DBC patch complete:")
    for filename, status in results:
        print(f"  {filename}: {status}")
    print("  CharBaseInfo.dbc: validated EXACTLY 10 race + Adventurer combinations")
    print("  CharStartOutfit.dbc: validated 20 Adventurer outfits with universal starter gear")


if __name__ == "__main__":
    main()

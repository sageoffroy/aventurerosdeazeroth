#!/usr/bin/env python3
"""Generate the runtime SpellDraft ability catalog from the live WotLK DBCs.

The historical SpellDraft client already carries the curated rarity/class
metadata in Interface/AddOns/SpellDraft/SpellData.lua.  This generator combines
that authored metadata with the server's own Spell/SkillLine/Talent DBCs so the
new clean draft engine does not need the historical SQL mirror tables.

The generated Lua file contains only root abilities. Rank chains are attached
to each root and can be upgraded by the runtime as the Adventurer levels.
"""

from __future__ import annotations

import argparse
import re
import struct
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

MAGIC = b"WDBC"
HEADER = struct.Struct("<4sIIII")

RELEVANT_SKILL_CATEGORIES = {6, 7, 8, 9, 11}

CLASS_SET = {
    "MAGE": 3,
    "WARRIOR": 4,
    "WARLOCK": 5,
    "PRIEST": 6,
    "DRUID": 7,
    "ROGUE": 8,
    "HUNTER": 9,
    "PALADIN": 10,
    "SHAMAN": 11,
    "DEATHKNIGHT": 15,
}

# Trigger/helper spells that were explicitly excluded by the historical
# SpellDraft implementation. They are not player-facing draft cards.
BLACKLISTED_SPELLS = {
    20184, 20185, 20187, 20425, 20467,
    27285, 47833, 47834,
    55166,
    34919,
    42234, 42243, 42244, 42245,
    42651,
    47241,
    12976,
    33891,
    47666, 47750,
    25912, 25914,
    13797,
    42231,
}

# Baseline/profession/riding spells are system-owned and must never become a
# random classless pick. This mirrors the protected set from the old engine.
PROTECTED_SPELLS = {
    54197, 33388, 33391, 34090, 34091,
    2259, 3101, 3464, 11611, 28596, 51304,
    2366, 2368, 3570, 11993, 28695, 50300, 2383, 32605,
    7411, 7412, 7413, 13920, 28029, 51313, 13262,
    2018, 3100, 3538, 9785, 29844, 51300,
    45357, 45358, 45359, 45360, 45361, 45363, 55005,
    4036, 4037, 4038, 12656, 30350, 49383, 51306,
    8613, 8617, 8618, 10768, 13697, 32678, 50305, 52158,
    3908, 3909, 3910, 12180, 26790, 51309,
    2108, 3104, 3811, 10662, 32549, 51302,
    25229, 25230, 28894, 28895, 28897, 51311,
    2550, 3102, 3413, 18260, 33359, 51296, 818,
    3273, 3274, 7924, 10846, 27028, 45544,
    7620, 7732, 7731, 18248, 33095, 51294, 7738,
}

SPELLDATA_RE = re.compile(
    r"\[(\d+)\]\s*=\s*\{\s*rarity\s*=\s*(-?\d+)\s*,\s*"
    r"class\s*=\s*\"([^\"]+)\"\s*,\s*name\s*=\s*\"((?:\\.|[^\"])*)\""
)


class CatalogError(RuntimeError):
    pass


@dataclass(frozen=True)
class CuratedSpell:
    spell_id: int
    rarity: int
    class_name: str
    name: str


@dataclass
class DBC:
    fields: int
    record_size: int
    records: list[bytes]
    strings: bytes

    def u32(self, record: bytes, field: int) -> int:
        return struct.unpack_from("<I", record, field * 4)[0]

    def string(self, record: bytes, field: int) -> str:
        offset = self.u32(record, field)
        if offset <= 0 or offset >= len(self.strings):
            return ""
        end = self.strings.find(b"\0", offset)
        if end < 0:
            end = len(self.strings)
        return self.strings[offset:end].decode("utf-8", errors="replace")


def read_dbc(path: Path) -> DBC:
    data = path.read_bytes()
    if len(data) < HEADER.size:
        raise CatalogError(f"{path}: file too small")

    magic, count, fields, record_size, string_size = HEADER.unpack_from(data)
    if magic != MAGIC:
        raise CatalogError(f"{path}: expected WDBC, got {magic!r}")
    if record_size != fields * 4:
        raise CatalogError(
            f"{path}: this generator expects 4-byte WotLK fields; "
            f"fields={fields}, record_size={record_size}"
        )

    start = HEADER.size
    end = start + count * record_size
    strings_end = end + string_size
    if strings_end > len(data):
        raise CatalogError(f"{path}: header sizes exceed file size")

    records = [
        data[start + i * record_size:start + (i + 1) * record_size]
        for i in range(count)
    ]
    return DBC(fields, record_size, records, data[end:strings_end])


def parse_spell_data(path: Path) -> dict[int, CuratedSpell]:
    if not path.is_file():
        raise CatalogError(
            f"SpellDraft client metadata not found: {path}. "
            "The current migration expects the historical SpellDraft addon."
        )

    text = path.read_text(encoding="utf-8", errors="replace")
    result: dict[int, CuratedSpell] = {}
    for spell_id, rarity, class_name, encoded_name in SPELLDATA_RE.findall(text):
        sid = int(spell_id)
        name = encoded_name.replace(r'\\"', '"').replace(r"\\\\", "\\")
        result[sid] = CuratedSpell(sid, int(rarity), class_name, name)

    if len(result) < 100:
        raise CatalogError(
            f"{path}: parsed only {len(result)} SpellDraft entries; expected the real catalog"
        )
    return result


def spell_meta(spell_dbc: DBC) -> dict[int, dict[str, object]]:
    result: dict[int, dict[str, object]] = {}
    for row in spell_dbc.records:
        spell_id = spell_dbc.u32(row, 0)
        result[spell_id] = {
            "id": spell_id,
            "attributes": spell_dbc.u32(row, 4),
            "spell_level": spell_dbc.u32(row, 39),
            "icon": spell_dbc.u32(row, 133),
            "name": spell_dbc.string(row, 136),
            "description": spell_dbc.string(row, 170),
            "family": spell_dbc.u32(row, 208),
        }
    return result


def skillline_categories(skill_dbc: DBC) -> dict[int, int]:
    return {
        skill_dbc.u32(row, 0): skill_dbc.u32(row, 1)
        for row in skill_dbc.records
    }


def skillline_abilities(
    ability_dbc: DBC,
    categories: dict[int, int],
) -> tuple[dict[int, set[int]], dict[int, int]]:
    categories_by_spell: dict[int, set[int]] = defaultdict(set)
    successor: dict[int, int] = {}

    for row in ability_dbc.records:
        skill_line = ability_dbc.u32(row, 1)
        spell_id = ability_dbc.u32(row, 2)
        if spell_id <= 0:
            continue

        category = categories.get(skill_line)
        if category is not None:
            categories_by_spell[spell_id].add(category)

        next_spell = ability_dbc.u32(row, 8)
        if next_spell > 0:
            previous = successor.get(spell_id)
            if previous is None or previous == next_spell:
                successor[spell_id] = next_spell

    return categories_by_spell, successor


def talent_spells(talent_dbc: DBC) -> set[int]:
    result: set[int] = set()
    for row in talent_dbc.records:
        for field in range(4, 9):
            spell_id = talent_dbc.u32(row, field)
            if spell_id > 0:
                result.add(spell_id)
    return result


def lua_quote(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", " ")
        .replace("\n", " ")
    )


def build_catalog(
    curated: dict[int, CuratedSpell],
    spells: dict[int, dict[str, object]],
    categories_by_spell: dict[int, set[int]],
    successor: dict[int, int],
    talents: set[int],
) -> list[dict[str, object]]:
    def static_valid(spell_id: int) -> bool:
        authored = curated.get(spell_id)
        meta = spells.get(spell_id)
        if not authored or not meta:
            return False
        if authored.class_name not in CLASS_SET:
            return False
        if authored.rarity < 0 or authored.rarity > 4:
            return False
        if spell_id in BLACKLISTED_SPELLS or spell_id in PROTECTED_SPELLS:
            return False
        if spell_id in talents:
            return False
        if int(meta["attributes"]) & 0x00000040:  # passive
            return False
        if int(meta["icon"]) <= 1:
            return False
        if not str(meta["description"]).strip():
            return False
        if not (categories_by_spell.get(spell_id, set()) & RELEVANT_SKILL_CATEGORIES):
            return False
        return True

    predecessor: dict[int, int] = {}
    for source, target in successor.items():
        a = curated.get(source)
        b = curated.get(target)
        if not a or not b:
            continue
        if a.class_name != b.class_name or a.name != b.name:
            continue
        predecessor.setdefault(target, source)

    roots: list[int] = []
    for spell_id in sorted(curated):
        if not static_valid(spell_id):
            continue
        if spell_id in predecessor and static_valid(predecessor[spell_id]):
            continue
        roots.append(spell_id)

    catalog: list[dict[str, object]] = []
    consumed: set[int] = set()

    for root in roots:
        if root in consumed:
            continue
        authored = curated[root]
        root_meta = spells[root]
        ranks: list[dict[str, int]] = []
        current = root
        seen: set[int] = set()

        while current > 0 and current not in seen:
            seen.add(current)
            current_authored = curated.get(current)
            current_meta = spells.get(current)
            if not current_authored or not current_meta:
                break
            if (
                current_authored.class_name != authored.class_name
                or current_authored.name != authored.name
            ):
                break
            if current in BLACKLISTED_SPELLS or current in talents:
                break

            ranks.append({
                "id": current,
                "level": int(current_meta["spell_level"]),
            })
            consumed.add(current)
            current = successor.get(current, 0)

        if not ranks:
            ranks = [{"id": root, "level": int(root_meta["spell_level"])}]

        # DBC rows occasionally have rank links with equal/zero levels. Keep
        # deterministic ordering while preserving Blizzard's chain order.
        catalog.append({
            "id": root,
            "rarity": authored.rarity,
            "classSet": CLASS_SET[authored.class_name],
            "minLevel": int(root_meta["spell_level"]),
            "name": authored.name,
            "ranks": ranks,
        })

    return catalog


def write_catalog(path: Path, catalog: list[dict[str, object]]) -> None:
    if len(catalog) < 100:
        raise CatalogError(
            f"Generated pool is unexpectedly small ({len(catalog)} root abilities)"
        )

    counts = Counter(int(entry["rarity"]) for entry in catalog)
    lines = [
        "-- AUTO-GENERATED by generate_spelldraft_catalog.py. DO NOT EDIT.",
        "-- Source: live server DBCs + curated historical SpellDraft metadata.",
        "SpellDraftCatalog = {",
    ]

    for entry in catalog:
        rank_text = ", ".join(
            "{ id = %d, level = %d }" % (rank["id"], rank["level"])
            for rank in entry["ranks"]
        )
        lines.append(
            '  { id = %d, rarity = %d, classSet = %d, minLevel = %d, '
            'name = "%s", ranks = { %s } },'
            % (
                entry["id"],
                entry["rarity"],
                entry["classSet"],
                entry["minLevel"],
                lua_quote(str(entry["name"])),
                rank_text,
            )
        )

    lines.extend([
        "}",
        "",
        "SpellDraftRarityDistribution = {",
        "  [0] = 70.0,",
        "  [1] = 20.0,",
        "  [2] = 7.0,",
        "  [3] = 2.5,",
        "  [4] = 0.5,",
        "}",
        "",
    ])

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")

    print(f"SpellDraft real catalog generated: {len(catalog)} root abilities")
    print(
        "  rarity roots: "
        + ", ".join(f"R{rarity}={counts.get(rarity, 0)}" for rarity in range(5))
    )
    print(f"  output: {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dbc-dir", required=True, type=Path)
    parser.add_argument("--spell-data", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    dbc_dir = args.dbc_dir.expanduser().resolve()
    required = {
        "Spell.dbc": None,
        "SkillLine.dbc": None,
        "SkillLineAbility.dbc": None,
        "Talent.dbc": None,
    }
    missing = [name for name in required if not (dbc_dir / name).is_file()]
    if missing:
        raise SystemExit("Missing SpellDraft DBC input(s): " + ", ".join(missing))

    try:
        curated = parse_spell_data(args.spell_data.expanduser().resolve())
        spell_dbc = read_dbc(dbc_dir / "Spell.dbc")
        skill_dbc = read_dbc(dbc_dir / "SkillLine.dbc")
        ability_dbc = read_dbc(dbc_dir / "SkillLineAbility.dbc")
        talent_dbc = read_dbc(dbc_dir / "Talent.dbc")

        spells = spell_meta(spell_dbc)
        categories = skillline_categories(skill_dbc)
        categories_by_spell, successor = skillline_abilities(ability_dbc, categories)
        talents = talent_spells(talent_dbc)
        catalog = build_catalog(
            curated,
            spells,
            categories_by_spell,
            successor,
            talents,
        )
        write_catalog(args.output.expanduser().resolve(), catalog)
    except CatalogError as exc:
        raise SystemExit(f"SpellDraft catalog generation aborted: {exc}") from exc


if __name__ == "__main__":
    main()

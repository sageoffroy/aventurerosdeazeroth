#!/usr/bin/env python3
"""Generate the runtime SpellDraft ability catalog from canonical WotLK data.

Sources:
- live server DBCs: spell metadata, skill-line scope and talent exclusion;
- historical SpellDraft SpellData.lua: curated rarity and class-origin metadata;
- AzerothCore spell_ranks.sql: canonical rank families.

Only the first spell of each rank family can become a draft card. Higher ranks
are attached to that card and learned automatically as the Adventurer levels.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

MAGIC = b"WDBC"
HEADER = struct.Struct("<4sIIII")
REPO = Path(__file__).resolve().parents[3]
MODULE = Path(__file__).resolve().parents[1]
DEFAULT_SPELL_RANKS_SQL = REPO / "data/sql/base/db_world/spell_ranks.sql"
DEFAULT_CARD_DEPENDENCIES = MODULE / "card_dependencies.json"
DEFAULT_RARITY_OVERRIDES = MODULE / "card_rarity_overrides.json"

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
RANK_ROW_RE = re.compile(r"\((\d+)\s*,\s*(\d+)\s*,\s*(\d+)\)")


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
            f"{path}: expected 4-byte WotLK fields; fields={fields}, record_size={record_size}"
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
        raise CatalogError(f"SpellDraft client metadata not found: {path}")

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


def load_rarity_overrides(path: Path) -> dict[int, int]:
    if not path.is_file():
        raise CatalogError(f"Card rarity override metadata not found: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CatalogError(
            f"Invalid card rarity override metadata {path}: {exc}"
        ) from exc

    if data.get("schema_version") != 1:
        raise CatalogError(
            f"{path}: expected schema_version=1"
        )

    raw = data.get("rarity")
    if not isinstance(raw, dict):
        raise CatalogError(
            f"{path}: rarity must be an object"
        )

    result: dict[int, int] = {}

    for spell_id, rarity in raw.items():
        try:
            sid = int(spell_id)
        except (TypeError, ValueError):
            raise CatalogError(
                f"{path}: invalid spell ID {spell_id!r}"
            )

        if not isinstance(rarity, int) or rarity < 0 or rarity > 4:
            raise CatalogError(
                f"{path}: spell {sid} rarity must be an integer from 0 to 4"
            )

        result[sid] = rarity

    return result


def load_card_dependencies(path: Path) -> dict[int, dict[str, list[str]]]:
    if not path.is_file():
        raise CatalogError(f"Card dependency metadata not found: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CatalogError(
            f"Invalid card dependency metadata {path}: {exc}"
        ) from exc

    if data.get("schema_version") != 1:
        raise CatalogError(
            f"{path}: expected schema_version 1"
        )

    cards = data.get("cards")
    if not isinstance(cards, dict):
        raise CatalogError(
            f"{path}: expected a cards object"
        )

    allowed_fields = {"grants", "requires", "synergy"}
    result: dict[int, dict[str, list[str]]] = {}

    for raw_spell_id, spec in cards.items():
        try:
            spell_id = int(raw_spell_id)
        except (TypeError, ValueError) as exc:
            raise CatalogError(
                f"{path}: invalid spell ID {raw_spell_id!r}"
            ) from exc

        if not isinstance(spec, dict):
            raise CatalogError(
                f"{path}: card {spell_id} metadata must be an object"
            )

        unknown = set(spec) - allowed_fields
        if unknown:
            raise CatalogError(
                f"{path}: card {spell_id} has unknown fields: "
                + ", ".join(sorted(unknown))
            )

        normalized: dict[str, list[str]] = {}

        for field in ("grants", "requires", "synergy"):
            values = spec.get(field, [])

            if not isinstance(values, list):
                raise CatalogError(
                    f"{path}: card {spell_id}.{field} must be a list"
                )

            cleaned: list[str] = []

            for value in values:
                if not isinstance(value, str):
                    raise CatalogError(
                        f"{path}: card {spell_id}.{field} values must be strings"
                    )

                value = value.strip()

                if not value or not re.fullmatch(r"[a-z0-9_.:-]+", value):
                    raise CatalogError(
                        f"{path}: invalid capability tag {value!r} "
                        f"for card {spell_id}.{field}"
                    )

                if value not in cleaned:
                    cleaned.append(value)

            normalized[field] = cleaned

        result[spell_id] = normalized

    return result


def parse_spell_ranks(path: Path) -> tuple[dict[int, int], dict[int, list[tuple[int, int]]]]:
    """Return spell->root and root->[(rank, spell)] from AzerothCore base SQL."""
    if not path.is_file():
        raise CatalogError(f"AzerothCore canonical spell_ranks.sql not found: {path}")

    text = path.read_text(encoding="utf-8", errors="replace")
    root_by_spell: dict[int, int] = {}
    ranks_by_root: dict[int, list[tuple[int, int]]] = defaultdict(list)

    for first_spell, spell_id, rank in RANK_ROW_RE.findall(text):
        root = int(first_spell)
        spell = int(spell_id)
        rank_no = int(rank)
        root_by_spell[spell] = root
        ranks_by_root[root].append((rank_no, spell))

    if len(root_by_spell) < 1000:
        raise CatalogError(
            f"{path}: parsed only {len(root_by_spell)} canonical ranked spells"
        )

    for root in ranks_by_root:
        ranks_by_root[root].sort(key=lambda item: item[0])

    return root_by_spell, dict(ranks_by_root)


def first_localized_string(dbc: DBC, record: bytes, first_field: int) -> str:
    for field in range(first_field, first_field + 16):
        value = dbc.string(record, field).strip()
        if value:
            return value
    return ""


def spell_meta(spell_dbc: DBC) -> dict[int, dict[str, object]]:
    result: dict[int, dict[str, object]] = {}
    for row in spell_dbc.records:
        spell_id = spell_dbc.u32(row, 0)
        result[spell_id] = {
            "attributes": spell_dbc.u32(row, 4),
            "spell_level": spell_dbc.u32(row, 39),
            "icon": spell_dbc.u32(row, 133),
            "name": first_localized_string(spell_dbc, row, 136),
            "description": first_localized_string(spell_dbc, row, 170),
        }
    return result


def skillline_categories(skill_dbc: DBC) -> dict[int, int]:
    return {skill_dbc.u32(row, 0): skill_dbc.u32(row, 1) for row in skill_dbc.records}


def spell_skill_categories(
    ability_dbc: DBC,
    categories: dict[int, int],
) -> dict[int, set[int]]:
    result: dict[int, set[int]] = defaultdict(set)
    for row in ability_dbc.records:
        skill_line = ability_dbc.u32(row, 1)
        spell_id = ability_dbc.u32(row, 2)
        if spell_id > 0 and skill_line in categories:
            result[spell_id].add(categories[skill_line])
    return dict(result)


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


def lua_string_list(values: list[str]) -> str:
    if not values:
        return "{}"
    return "{ " + ", ".join(
        f'"{lua_quote(value)}"' for value in values
    ) + " }"


def build_catalog(
    curated: dict[int, CuratedSpell],
    spells: dict[int, dict[str, object]],
    categories_by_spell: dict[int, set[int]],
    talents: set[int],
    root_by_spell: dict[int, int],
    ranks_by_root: dict[int, list[tuple[int, int]]],
    dependencies: dict[int, dict[str, list[str]]],
    rarity_overrides: dict[int, int],
) -> list[dict[str, object]]:
    def rejection_reason(spell_id: int) -> str | None:
        authored = curated.get(spell_id)
        meta = spells.get(spell_id)
        if not authored:
            return "missing_curated_metadata"
        if not meta:
            return "missing_spell_dbc"

        canonical_root = root_by_spell.get(spell_id, spell_id)
        if canonical_root != spell_id:
            return "nonfirst_rank"

        if authored.class_name not in CLASS_SET:
            return "unsupported_class_or_general"
        if authored.rarity < 0 or authored.rarity > 4:
            return "rarity_outside_0_4"
        if spell_id in BLACKLISTED_SPELLS:
            return "technical_blacklist"
        if spell_id in PROTECTED_SPELLS:
            return "protected_system_spell"
        if spell_id in talents:
            return "talent_spell"
        if int(meta["attributes"]) & 0x00000040:
            return "passive"
        if int(meta["icon"]) <= 1:
            return "missing_icon"
        if not str(meta["description"]).strip():
            return "empty_all_locale_descriptions"
        if not (categories_by_spell.get(spell_id, set()) & RELEVANT_SKILL_CATEGORIES):
            return "outside_draft_skill_categories"
        return None

    rejection_counts: Counter[str] = Counter()
    matched_dbc = 0
    localized_descriptions = 0
    relevant_skillline = 0

    for spell_id in curated:
        meta = spells.get(spell_id)
        if meta:
            matched_dbc += 1
            if str(meta["description"]).strip():
                localized_descriptions += 1
            if categories_by_spell.get(spell_id, set()) & RELEVANT_SKILL_CATEGORIES:
                relevant_skillline += 1
        reason = rejection_reason(spell_id)
        if reason:
            rejection_counts[reason] += 1

    print("SpellDraft catalog input diagnostics:")
    print(f"  curated SpellData entries: {len(curated)}")
    print(f"  IDs present in Spell.dbc: {matched_dbc}")
    print(f"  IDs with any localized description: {localized_descriptions}")
    print(f"  IDs in draft skill-line categories: {relevant_skillline}")
    print(f"  canonical ranked spell IDs: {len(root_by_spell)}")
    print(f"  canonical rank families: {len(ranks_by_root)}")
    for reason, count in rejection_counts.most_common():
        print(f"  rejected {reason}: {count}")

    roots = [
        spell_id for spell_id in sorted(curated)
        if rejection_reason(spell_id) is None
    ]

    catalog: list[dict[str, object]] = []
    for root in roots:
        authored = curated[root]
        root_meta = spells[root]
        rank_rows = ranks_by_root.get(root, [(1, root)])
        ranks: list[dict[str, int]] = []
        seen: set[int] = set()

        for _rank_no, spell_id in rank_rows:
            if spell_id in seen:
                continue
            seen.add(spell_id)
            meta = spells.get(spell_id)
            if not meta:
                continue
            ranks.append({
                "id": spell_id,
                "level": int(meta["spell_level"]),
            })

        if not ranks:
            ranks = [{"id": root, "level": int(root_meta["spell_level"])}]

        dependency = dependencies.get(root, {})

        catalog.append({
            "id": root,
            "rarity": rarity_overrides.get(root, authored.rarity),
            "classSet": CLASS_SET[authored.class_name],
            "minLevel": int(root_meta["spell_level"]),
            "name": authored.name,
            "grants": list(dependency.get("grants", [])),
            "requires": list(dependency.get("requires", [])),
            "synergy": list(dependency.get("synergy", [])),
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
        "-- Canonical ranks: AzerothCore data/sql/base/db_world/spell_ranks.sql.",
        "SpellDraftCatalog = {",
    ]

    for entry in catalog:
        rank_text = ", ".join(
            "{ id = %d, level = %d }" % (rank["id"], rank["level"])
            for rank in entry["ranks"]
        )
        lines.append(
            '  { id = %d, rarity = %d, classSet = %d, minLevel = %d, '
            'name = "%s", grants = %s, requires = %s, synergy = %s, '
            'ranks = { %s } },'
            % (
                entry["id"],
                entry["rarity"],
                entry["classSet"],
                entry["minLevel"],
                lua_quote(str(entry["name"])),
                lua_string_list(entry["grants"]),
                lua_string_list(entry["requires"]),
                lua_string_list(entry["synergy"]),
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
    parser.add_argument("--spell-ranks-sql", type=Path, default=DEFAULT_SPELL_RANKS_SQL)
    parser.add_argument(
        "--dependencies",
        type=Path,
        default=DEFAULT_CARD_DEPENDENCIES,
    )
    parser.add_argument(
        "--rarity-overrides",
        type=Path,
        default=DEFAULT_RARITY_OVERRIDES,
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    dbc_dir = args.dbc_dir.expanduser().resolve()
    for name in ("Spell.dbc", "SkillLine.dbc", "SkillLineAbility.dbc", "Talent.dbc"):
        if not (dbc_dir / name).is_file():
            raise SystemExit(f"Missing SpellDraft DBC input: {dbc_dir / name}")

    try:
        curated = parse_spell_data(args.spell_data.expanduser().resolve())
        root_by_spell, ranks_by_root = parse_spell_ranks(
            args.spell_ranks_sql.expanduser().resolve()
        )
        spell_dbc = read_dbc(dbc_dir / "Spell.dbc")
        skill_dbc = read_dbc(dbc_dir / "SkillLine.dbc")
        ability_dbc = read_dbc(dbc_dir / "SkillLineAbility.dbc")
        talent_dbc = read_dbc(dbc_dir / "Talent.dbc")

        spells = spell_meta(spell_dbc)
        categories = skillline_categories(skill_dbc)
        categories_by_spell = spell_skill_categories(ability_dbc, categories)
        talents = talent_spells(talent_dbc)
        dependencies = load_card_dependencies(
            args.dependencies.expanduser().resolve()
        )
        rarity_overrides = load_rarity_overrides(
            args.rarity_overrides.expanduser().resolve()
        )

        catalog = build_catalog(
            curated,
            spells,
            categories_by_spell,
            talents,
            root_by_spell,
            ranks_by_root,
            dependencies,
            rarity_overrides,
        )
        write_catalog(args.output.expanduser().resolve(), catalog)
    except CatalogError as exc:
        raise SystemExit(f"SpellDraft catalog generation aborted: {exc}") from exc


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Static/self-contained validation for SpellDraft assets."""

from __future__ import annotations

import ast
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
MODULE = TOOLS.parent
REPO = MODULE.parents[1]
ADVENTURER_WORLD_SQL = (
    REPO / "data/sql/updates/pending_db_world/rev_1787027400000000000.sql"
)
SPELLDRAFT_CHARACTER_SQL = (
    REPO / "data/sql/updates/pending_db_characters/rev_1787076000000000000.sql"
)
SPELL_RANKS_SQL = REPO / "data/sql/base/db_world/spell_ranks.sql"
sys.path.insert(0, str(TOOLS))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAIL: {message}")
    print(f"OK: {message}")


def read(path: Path) -> str:
    require(path.is_file(), f"exists: {path.relative_to(REPO)}")
    return path.read_text(encoding="utf-8")


def validate_python_syntax() -> None:
    print("\nPYTHON")
    for path in sorted(TOOLS.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))
        print(f"OK: syntax: {path.name}")


def validate_core() -> None:
    print("\nCORE")
    shared = read(REPO / "src/server/shared/SharedDefines.h")
    require("CLASS_ADVENTURER" in shared and "= 10" in shared,
            "CLASS_ADVENTURER occupies class ID 10")
    require("CLASS_ADVENTURER-1" in shared,
            "Adventurer is included in the playable class mask")

    enuminfo = read(REPO / "src/server/shared/enuminfo_SharedDefines.cpp")
    require("CLASS_ADVENTURER" in enuminfo,
            "EnumUtils knows CLASS_ADVENTURER")

    loader = read(MODULE / "src/SpellDraft_loader.cpp")
    require("AddAdventurerClassScripts" in loader,
            "module loader registers Adventurer")


def validate_adventurer_baseline() -> None:
    print("\nADVENTURER BASELINE")
    cpp = read(MODULE / "src/AdventurerClass.cpp")
    expectations = {
        "SKILL_RIDING = 762": "Riding skill 762",
        "SPELL_APPRENTICE_RIDING = 33388": "Apprentice Riding 33388",
        "SPELL_BROWN_HORSE = 458": "Brown Horse 458",
        "APPRENTICE_RIDING_VALUE = 75": "Riding value 75",
        "75,                       // Auto Shot": "Auto Shot 75",
        "5019,                     // Shoot": "Shoot 5019",
        "2764,                     // Throw": "Throw 2764",
    }
    for token, label in expectations.items():
        require(token in cpp, label)

    resources = read(MODULE / "lua/SpellDraft/resources.lua")
    require("EnsurePlayerLanguages" not in resources,
            "Lua does not repair Adventurer languages")
    require("SetLanguageSkill" not in resources,
            "Lua resource layer owns resources only")

    native_skill_patcher = read(TOOLS / "patch_adventurer_native_race_skills.py")
    native_expectations = {
        "ADVENTURER_CLASS_MASK = 1 << (ADVENTURER_CLASS - 1)": "native skill patch targets class 10",
        "1: (98, 754)": "Human receives Common through native DBC mapping",
        "2: (109, 125)": "Orc receives Orcish through native DBC mapping",
        "10: (109, 137, 756)": "Blood Elf receives Orcish and Thalassian",
        "11: (98, 759, 760)": "Draenei receives Common and Draenei",
        "163,  # Marksmanship: Auto Shot (75)": "Auto Shot skill line is validated",
        "762,  # Riding: Apprentice Riding (33388)": "Riding skill line is validated",
        "777,  # Mounts: Brown Horse (458)": "Mount skill line is validated",
        "ensure_classless_class_skill_rows": "all class-bound skill lines are authorized for classless Adventurer",
        "set_u32(clone, 2, 0)": "classless skill mappings apply to every race",
        "set_u32(clone, 3, ADVENTURER_CLASS_MASK)": "classless skill mappings affect class 10 only",
        "validate_skillraceclassinfo(path)": "native skill patch validates the DBC",
    }
    for token, label in native_expectations.items():
        require(token in native_skill_patcher, label)

    prepare = read(TOOLS / "prepare_first_run.py")
    require("patch_adventurer_native_race_skills.py" in prepare,
            "first-run pipeline applies native Adventurer DBC skill mappings")

    patcher = read(TOOLS / "patch_adventurer_class_dbcs.py")
    for item_id, label in (
        (25, "Worn Short Sword"),
        (2362, "Worn Wooden Shield"),
        (2504, "Worn Short Bow"),
        (2512, "Rough Arrow"),
    ):
        require(str(item_id) in patcher, f"starter item {label} ({item_id})")


def validate_sql() -> None:
    print("\nSQL")
    sql = read(ADVENTURER_WORLD_SQL)
    require("SET @ADVENTURER_CLASS := 10" in sql,
            "pending world SQL targets class 10")
    require("SET @ADVENTURER_CLASS_MASK := 512" in sql,
            "pending world SQL targets class mask 512")
    require("playercreateinfo" in sql and "player_class_stats" in sql,
            "pending world SQL provides creation rows and class stats")

    character_sql = read(SPELLDRAFT_CHARACTER_SQL)
    require("CREATE TABLE IF NOT EXISTS `spelldraft_drafted_spells`" in character_sql,
            "character SQL persists drafted spells")
    require("CREATE TABLE IF NOT EXISTS `spelldraft_pending_offer`" in character_sql,
            "character SQL persists the pending offer")

    ranks_sql = read(SPELL_RANKS_SQL)
    require("CREATE TABLE `spell_ranks`" in ranks_sql,
            "AzerothCore canonical spell_ranks table is available")
    require("`first_spell_id`" in ranks_sql and "`rank`" in ranks_sql,
            "canonical rank source exposes root and rank columns")

    require(not (MODULE / "sql/adventurer_class_10.sql").exists(),
            "there is no duplicate active module SQL copy")
    require(
        not (REPO / "data/sql/custom/db_world/spelldraft_adventurer_class_10.sql").exists(),
        "there is no nonstandard custom SQL copy",
    )


def validate_real_catalog_pipeline() -> None:
    print("\nSPELLDRAFT REAL CATALOG")
    generator = read(TOOLS / "generate_spelldraft_catalog.py")
    expectations = {
        '"Spell.dbc"': "catalog reads Spell.dbc",
        '"SkillLine.dbc"': "catalog reads SkillLine.dbc",
        '"SkillLineAbility.dbc"': "catalog reads SkillLineAbility.dbc",
        '"Talent.dbc"': "catalog reads Talent.dbc",
        "SPELLDATA_RE": "historical authored rarity/class metadata is parsed",
        "DEFAULT_SPELL_RANKS_SQL": "catalog reads AzerothCore canonical spell ranks",
        "parse_spell_ranks": "canonical rank SQL is parsed into families",
        'return "nonfirst_rank"': "non-first ranks cannot become draft cards",
        "ranks_by_root": "higher ranks are attached to their root card",
        "RELEVANT_SKILL_CATEGORIES = {6, 7, 8, 9, 11}": "historical draft skill-line scope is preserved",
        "BLACKLISTED_SPELLS": "technical trigger blacklist is preserved",
        "PROTECTED_SPELLS": "system/profession/riding spells are protected",
        "0x00000040": "passive spells are excluded",
        "SpellDraftRarityDistribution": "generated catalog exports rarity distribution",
        "[0] = 70.0": "common rarity target is 70 percent",
        "[4] = 0.5": "legendary rarity target is 0.5 percent",
    }
    for token, label in expectations.items():
        require(token in generator, label)

    require("SupercededBySpell" not in generator,
            "catalog does not infer rank families from SkillLineAbility supersede links")

    prepare = read(TOOLS / "prepare_first_run.py")
    require("generate_spelldraft_catalog.py" in prepare,
            "first-run pipeline generates the real runtime catalog")
    require('"SpellData.lua"' in prepare,
            "first-run pipeline uses the installed historical SpellData metadata")
    for dbc in ("Spell.dbc", "SkillLine.dbc", "SkillLineAbility.dbc", "Talent.dbc"):
        require(f'"{dbc}"' in prepare, f"first-run requires {dbc}")


def validate_draft_engine() -> None:
    print("\nSPELLDRAFT REAL ENGINE")
    draft = read(MODULE / "lua/SpellDraft/draft.lua")
    expectations = {
        "local CLASS_ADVENTURER = 10": "draft engine is class-10-only",
        "local DRAFTS_PER_LEVEL = 10": "Adventurer receives ten drafts per level",
        "local LOW_LEVEL_POOL_FLOOR = 20": "level 1 uses the historical level-20 pool floor",
        'dofile(parentPath .. "catalog.lua")': "runtime loads the generated real catalog",
        "RollRarity": "offers use rarity-weighted selection",
        "RARITY_DISTRIBUTION": "runtime consumes generated rarity weights",
        "PlayerHasAnyRank": "known rank families are not redrafted",
        "RestoreAndUpgradeDraftedSpells": "drafted rank families upgrade as the player levels",
        'msg == "SC_CHECK"': "historical addon SC_CHECK protocol is supported",
        'msg:match("^SC:(%d+)$")': "historical addon card-pick protocol is supported",
        'player:SendAddonMessage("SpellChoice"': "server sends card offers to the existing addon",
        "spelldraft_drafted_spells": "draft picks use new persistence",
        "spelldraft_pending_offer": "pending offers survive reconnects",
        "local draftedCache = {}": "draft picks are cached against async DB races",
        "local pendingOfferCache = {}": "pending offers are cached against async DB races",
        "RegisterPlayerEvent(19, OnProtocolWhisper)": "self-whisper protocol hook is registered",
        "RegisterPlayerEvent(4, OnLogout)": "session caches are cleared on logout",
    }
    for token, label in expectations.items():
        require(token in draft, label)

    require("local SPELL_POOL = {" not in draft,
            "hardcoded bootstrap spell pool has been removed")
    require("prestige_stats" not in draft,
            "real draft engine remains independent from historical prestige_stats")
    require("FROM drafted_spells " not in draft and "INTO drafted_spells " not in draft,
            "real draft engine does not depend on historical drafted_spells")

    stage = read(TOOLS / "stage_lua_runtime.py")
    require('source.rglob("*.lua")' in stage,
            "runtime staging includes draft.lua automatically")


def validate_client_pipeline() -> None:
    print("\nCLIENT PIPELINE")
    baseline_path = MODULE / "client-baseline/Interface/GlueXML/CharacterCreate.lua"
    baseline = read(baseline_path).encode("utf-8")

    required_markers = (
        b"local TECHNICAL_CLASS_ID = 1; -- Warrior; hidden from the player.",
        b"local function SelectTechnicalClassForCurrentRace()",
        b"function CharacterCreateEnumerateClasses(...)",
        b"function SetCharacterClass(id)",
        b"function CharacterCreate_OnChar()",
        b"CreateCharacter(CharacterCreateNameEdit:GetText());",
    )
    for marker in required_markers:
        require(marker in baseline, f"GlueXML marker: {marker.decode('utf-8')}")

    from build_adventurer_client_patch import adventurer_character_create_lua
    patched = adventurer_character_create_lua(baseline)
    require(b"ResolveOnlyValidClassForCurrentRace" in patched,
            "GlueXML resolves the sole valid class")
    require(b"local TECHNICAL_CLASS_ID = 1" not in patched,
            "technical Warrior selector is removed")
    require(b"SelectTechnicalClassForCurrentRace() ) then" in patched,
            "class 10 is reasserted before CreateCharacter")

    from mpq_writer import write_mpq
    with tempfile.TemporaryDirectory(prefix="spelldraft-selftest-") as td:
        target = Path(td) / "test.mpq"
        write_mpq(target, {"Interface\\GlueXML\\Probe.txt": b"SpellDraft"})
        payload = target.read_bytes()
        require(payload.startswith(b"MPQ\x1a"), "MPQ writer emits MPQ v1 header")
        require(len(payload) > 64, "MPQ writer emits a non-empty archive")


def main() -> None:
    print("SpellDraft repository self-test")
    validate_python_syntax()
    validate_core()
    validate_adventurer_baseline()
    validate_sql()
    validate_real_catalog_pipeline()
    validate_draft_engine()
    validate_client_pipeline()
    print("\nALL SPELLDRAFT CHECKS PASSED")


if __name__ == "__main__":
    main()

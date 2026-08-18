#!/usr/bin/env python3
"""Static/self-contained validation for SpellDraft bootstrap assets."""

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
            "pending SQL targets class 10")
    require("SET @ADVENTURER_CLASS_MASK := 512" in sql,
            "pending SQL targets class mask 512")
    require("playercreateinfo" in sql and "player_class_stats" in sql,
            "pending SQL provides creation rows and class stats")
    require(not (MODULE / "sql/adventurer_class_10.sql").exists(),
            "there is no duplicate active module SQL copy")
    require(
        not (REPO / "data/sql/custom/db_world/spelldraft_adventurer_class_10.sql").exists(),
        "there is no nonstandard custom SQL copy",
    )


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
    validate_client_pipeline()
    print("\nALL SPELLDRAFT BOOTSTRAP CHECKS PASSED")


if __name__ == "__main__":
    main()

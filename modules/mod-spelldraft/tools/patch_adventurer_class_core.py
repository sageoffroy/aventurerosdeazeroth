#!/usr/bin/env python3
"""Patch AzerothCore so WotLK class ID 10 is a real playable Adventurer.

This intentionally occupies the unused class slot between Warlock (9) and Druid
(11). MAX_CLASSES is already 12 in AzerothCore, so no class IDs are shifted.

The patch is idempotent and deliberately narrow:
  * SharedDefines.h: define CLASS_ADVENTURER = 10 and include it in the playable mask.
  * enuminfo_SharedDefines.cpp: teach EnumUtils about the new enum value.
  * StatSystem.cpp: populate the otherwise-zero class-10 avoidance constants.

Run from mod-spelldraft/install.sh or manually:
    python3 tools/patch_adventurer_class_core.py ~/azerothcore
"""

from __future__ import annotations

import argparse
from pathlib import Path


class PatchError(RuntimeError):
    pass


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise PatchError(f"{label}: expected exactly one target, found {count}")
    return text.replace(old, new, 1)


def patch_shared_defines(root: Path) -> bool:
    path = root / "src/server/shared/SharedDefines.h"
    text = path.read_text(encoding="utf-8")
    original = text

    text = replace_once(
        text,
        "    CLASS_WARLOCK       = 9, // TITLE Warlock\n    //CLASS_UNK           = 10,\n    CLASS_DRUID         = 11 // TITLE Druid",
        "    CLASS_WARLOCK       = 9, // TITLE Warlock\n    CLASS_ADVENTURER    = 10, // TITLE Adventurer (SpellDraft custom class)\n    CLASS_DRUID         = 11 // TITLE Druid",
        "SharedDefines Classes",
    )

    text = replace_once(
        text,
        "    (1<<(CLASS_MAGE-1))   |(1<<(CLASS_WARLOCK-1))|(1<<(CLASS_DRUID-1)) | \\\n    (1<<(CLASS_DEATH_KNIGHT-1)))",
        "    (1<<(CLASS_MAGE-1))   |(1<<(CLASS_WARLOCK-1))|(1<<(CLASS_ADVENTURER-1))| \\\n    (1<<(CLASS_DRUID-1))  |(1<<(CLASS_DEATH_KNIGHT-1)))",
        "SharedDefines playable class mask",
    )

    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def patch_enuminfo(root: Path) -> bool:
    path = root / "src/server/shared/enuminfo_SharedDefines.cpp"
    text = path.read_text(encoding="utf-8")
    original = text

    text = replace_once(
        text,
        '        case CLASS_WARLOCK: return { "CLASS_WARLOCK", "Warlock", "" };\n        case CLASS_DRUID: return { "CLASS_DRUID", "Druid", "" };',
        '        case CLASS_WARLOCK: return { "CLASS_WARLOCK", "Warlock", "" };\n        case CLASS_ADVENTURER: return { "CLASS_ADVENTURER", "Adventurer", "SpellDraft custom class" };\n        case CLASS_DRUID: return { "CLASS_DRUID", "Druid", "" };',
        "EnumUtils Classes::ToString",
    )

    text = replace_once(
        text,
        "AC_API_EXPORT std::size_t EnumUtils<Classes>::Count() { return 10; }",
        "AC_API_EXPORT std::size_t EnumUtils<Classes>::Count() { return 11; }",
        "EnumUtils Classes::Count",
    )

    text = replace_once(
        text,
        "        case 8: return CLASS_WARLOCK;\n        case 9: return CLASS_DRUID;",
        "        case 8: return CLASS_WARLOCK;\n        case 9: return CLASS_ADVENTURER;\n        case 10: return CLASS_DRUID;",
        "EnumUtils Classes::FromIndex",
    )

    text = replace_once(
        text,
        "        case CLASS_WARLOCK: return 8;\n        case CLASS_DRUID: return 9;",
        "        case CLASS_WARLOCK: return 8;\n        case CLASS_ADVENTURER: return 9;\n        case CLASS_DRUID: return 10;",
        "EnumUtils Classes::ToIndex",
    )

    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def patch_stat_system(root: Path) -> bool:
    path = root / "src/server/game/Entities/Unit/StatSystem.cpp"
    text = path.read_text(encoding="utf-8")
    original = text

    # Slot 10 (array index 9) is zero in stock WotLK. Zero is unsafe for the
    # diminishing-return formula and also disables parry. Use the hybrid/agi
    # values already used by Hunter/Rogue/Shaman so a classless character can
    # make normal use of dodge/parry/rating regardless of its eventual build.
    text = replace_once(
        text,
        "    0.9830f,  // Warlock\n    0.0f,     // ??\n    0.9720f   // Druid",
        "    0.9830f,  // Warlock\n    0.9880f,  // Adventurer\n    0.9720f   // Druid",
        "StatSystem diminishing k",
    )

    text = replace_once(
        text,
        "        16.00f,     // Warlock //?\n        0.0f,       // ??\n        16.00f      // Druid   //?",
        "        16.00f,     // Warlock //?\n        16.00f,     // Adventurer\n        16.00f      // Druid   //?",
        "StatSystem miss cap",
    )

    text = replace_once(
        text,
        "        0.0f,           // Warlock\n        0.0f,           // ??\n        0.0f            // Druid",
        "        0.0f,           // Warlock\n        145.560408f,    // Adventurer\n        0.0f            // Druid",
        "StatSystem parry cap",
    )

    text = replace_once(
        text,
        "        150.375940f,    // Warlock\n        0.0f,           // ??\n        116.890707f     // Druid",
        "        150.375940f,    // Warlock\n        145.560408f,    // Adventurer\n        116.890707f     // Druid",
        "StatSystem dodge cap",
    )

    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("azerothcore_root", type=Path)
    args = parser.parse_args()

    root = args.azerothcore_root.resolve()
    required = [
        root / "src/server/shared/SharedDefines.h",
        root / "src/server/shared/enuminfo_SharedDefines.cpp",
        root / "src/server/game/Entities/Unit/StatSystem.cpp",
    ]
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        raise SystemExit("AzerothCore source files not found:\n  " + "\n  ".join(missing))

    try:
        changed = {
            "SharedDefines.h": patch_shared_defines(root),
            "enuminfo_SharedDefines.cpp": patch_enuminfo(root),
            "StatSystem.cpp": patch_stat_system(root),
        }
    except PatchError as exc:
        raise SystemExit(f"Adventurer core patch aborted: {exc}") from exc

    print("Adventurer class-10 core patch complete:")
    for name, did_change in changed.items():
        print(f"  {name}: {'patched' if did_change else 'already patched'}")


if __name__ == "__main__":
    main()

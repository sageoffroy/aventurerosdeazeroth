#!/usr/bin/env python3
"""Patch Spell::prepare with the Aventureros per-level cast-time bridge.

AzerothCore calculates m_casttime during Spell::prepare, while the historical
PLAYERHOOK_ON_SPELL_CAST fires later when the cast is executed. Effect values
can be replaced from that hook, but cast time cannot: the timer and
SMSG_SPELL_START have already been committed.

The project therefore uses one deliberately tiny core bridge. Spell.cpp asks
mod-spelldraft for the custom cast time immediately after normal AzerothCore
CalcCastTime() processing and before movement checks/ReSetTimer(). Non-custom
spells receive the unmodified fallback value.

The patch is idempotent and keeps all profile data/selection inside the module.
"""

from __future__ import annotations

import argparse
from pathlib import Path


class PatchError(RuntimeError):
    pass


DECLARATION = (
    "int32 GetAventurerosCustomSpellCastTime("
    "Player const* player, uint32 spellId, int32 fallbackCastTime);"
)

CALL_BLOCK = """    if (Player* playerCaster = m_caster->ToPlayer())
        m_casttime = GetAventurerosCustomSpellCastTime(playerCaster, m_spellInfo->Id, m_casttime);"""


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise PatchError(f"{label}: expected exactly one target, found {count}")
    return text.replace(old, new, 1)


def patch_spell_cpp(root: Path) -> bool:
    path = root / "src/server/game/Spells/Spell.cpp"
    if not path.is_file():
        raise PatchError(f"Spell.cpp not found: {path}")

    text = path.read_text(encoding="utf-8")
    original = text

    text = replace_once(
        text,
        "extern pEffect SpellEffects[TOTAL_SPELL_EFFECTS];",
        "extern pEffect SpellEffects[TOTAL_SPELL_EFFECTS];\n" + DECLARATION,
        "Spell.cpp bridge declaration",
    )

    cast_line = (
        "    m_casttime = HasTriggeredCastFlag(TRIGGERED_CAST_DIRECTLY) ? 0 : "
        "m_spellInfo->CalcCastTime(m_caster, this);"
    )
    text = replace_once(
        text,
        cast_line,
        cast_line + "\n" + CALL_BLOCK,
        "Spell.cpp cast-time bridge",
    )

    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def validate(root: Path) -> None:
    path = root / "src/server/game/Spells/Spell.cpp"
    text = path.read_text(encoding="utf-8")
    if text.count(DECLARATION) != 1:
        raise PatchError("Spell.cpp does not contain exactly one Aventureros bridge declaration")
    if text.count(CALL_BLOCK) != 1:
        raise PatchError("Spell.cpp does not contain exactly one Aventureros cast-time bridge call")

    call_pos = text.index(CALL_BLOCK)
    timer_pos = text.find("ReSetTimer();", call_pos)
    if timer_pos < 0:
        raise PatchError("Aventureros cast-time bridge is not before Spell::ReSetTimer()")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "azerothcore_root",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[3],
    )
    args = parser.parse_args()

    root = args.azerothcore_root.expanduser().resolve()
    try:
        changed = patch_spell_cpp(root)
        validate(root)
    except PatchError as exc:
        raise SystemExit(f"Profiled cast-time core patch aborted: {exc}") from exc

    print("Aventureros profiled cast-time core bridge validated:")
    print(f"  Spell.cpp: {'patched' if changed else 'already patched'}")
    print("  hook point: after CalcCastTime(), before movement checks/ReSetTimer()")
    print("  non-custom spells keep AzerothCore's original cast time")


if __name__ == "__main__":
    main()

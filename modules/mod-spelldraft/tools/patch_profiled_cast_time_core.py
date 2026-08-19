#!/usr/bin/env python3
"""Patch Spell::prepare with the Aventureros per-level cast-time bridge.

AzerothCore calculates m_casttime during Spell::prepare, while the historical
PLAYERHOOK_ON_SPELL_CAST fires later when the cast is executed. Effect values
can be replaced from that hook, but cast time cannot: the timer and
SMSG_SPELL_START have already been committed.

The project therefore uses one deliberately tiny core bridge. For a normalized
201xxx spell, Spell.cpp asks mod-spelldraft for the interpolated BASE cast time,
then runs AzerothCore's normal ranged-slot adjustment and ModSpellCastTime()
processing on that base. Haste, spell modifiers and other normal cast-time
mechanics therefore remain active. Non-custom and triggered-direct spells keep
the stock path unchanged.

The custom and stock branches are mutually exclusive, so ModSpellCastTime() is
never applied twice to the same cast.
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

STOCK_CAST_LINE = (
    "    m_casttime = HasTriggeredCastFlag(TRIGGERED_CAST_DIRECTLY) ? 0 : "
    "m_spellInfo->CalcCastTime(m_caster, this);"
)

CAST_BLOCK = """    if (HasTriggeredCastFlag(TRIGGERED_CAST_DIRECTLY))
        m_casttime = 0;
    else
    {
        int32 customBaseCastTime = -1;
        if (Player* playerCaster = m_caster->ToPlayer())
        {
            customBaseCastTime = GetAventurerosCustomSpellCastTime(
                playerCaster, m_spellInfo->Id, -1);
        }

        if (customBaseCastTime >= 0)
        {
            m_casttime = customBaseCastTime;
            if (m_spellInfo->HasAttribute(SPELL_ATTR0_USES_RANGED_SLOT)
                && !m_spellInfo->IsAutoRepeatRangedSpell())
                m_casttime += 500;
            m_caster->ModSpellCastTime(m_spellInfo, m_casttime, this);
        }
        else
            m_casttime = m_spellInfo->CalcCastTime(m_caster, this);
    }"""


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

    text = replace_once(
        text,
        STOCK_CAST_LINE,
        CAST_BLOCK,
        "Spell.cpp cast-time calculation",
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
    if text.count(CAST_BLOCK) != 1:
        raise PatchError("Spell.cpp does not contain exactly one Aventureros cast-time block")
    if STOCK_CAST_LINE in text:
        raise PatchError("stock one-line cast calculation survived next to the profiled branch")

    call_pos = text.index(CAST_BLOCK)
    cheat_pos = text.find("GetCommandStatus(CHEAT_CASTTIME)", call_pos)
    timer_pos = text.find("ReSetTimer();", call_pos)
    if cheat_pos < 0 or timer_pos < 0 or not call_pos < cheat_pos < timer_pos:
        raise PatchError(
            "Aventureros cast-time bridge must run before cheat handling and ReSetTimer()"
        )


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
    print("  normalized cast base: interpolated by player level")
    print("  normal haste/spell cast modifiers: preserved exactly once")
    print("  triggered-direct/non-custom spells: stock path unchanged")
    print("  hook point: before cheat handling, movement checks and ReSetTimer()")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Patch Spell::prepare with the Aventureros per-level cast-time bridge.

AzerothCore calculates m_casttime during Spell::prepare, while the historical
PLAYERHOOK_ON_SPELL_CAST fires later when the cast is executed. Effect values
can be replaced from that hook, but cast time cannot: the timer and
SMSG_SPELL_START have already been committed.

The core side owns only an OPTIONAL resolver slot. mod-spelldraft registers its
profile-aware resolver after loading the v2 scaling table. With the module
disabled, the resolver remains null and the stock CalcCastTime() path is used;
there is no core -> module link dependency.

For a normalized spell the resolver returns an interpolated BASE cast time,
then Spell.cpp runs AzerothCore's normal ranged-slot adjustment and
ModSpellCastTime() processing once. Haste and ordinary spell modifiers remain
normal game mechanics.
"""

from __future__ import annotations

import argparse
from pathlib import Path


class PatchError(RuntimeError):
    pass


BRIDGE_DEFINITION = """using AventurerosCustomSpellCastTimeResolver = int32 (*)(Player const*, uint32, int32);

namespace
{
AventurerosCustomSpellCastTimeResolver g_AventurerosCustomSpellCastTimeResolver = nullptr;
}

void SetAventurerosCustomSpellCastTimeResolver(AventurerosCustomSpellCastTimeResolver resolver)
{
    g_AventurerosCustomSpellCastTimeResolver = resolver;
}"""

STOCK_CAST_LINE = (
    "    m_casttime = HasTriggeredCastFlag(TRIGGERED_CAST_DIRECTLY) ? 0 : "
    "m_spellInfo->CalcCastTime(m_caster, this);"
)

CAST_BLOCK = """    if (HasTriggeredCastFlag(TRIGGERED_CAST_DIRECTLY))
        m_casttime = 0;
    else
    {
        int32 customBaseCastTime = -1;
        if (g_AventurerosCustomSpellCastTimeResolver)
        {
            if (Player* playerCaster = m_caster->ToPlayer())
            {
                customBaseCastTime = g_AventurerosCustomSpellCastTimeResolver(
                    playerCaster, m_spellInfo->Id, -1);
            }
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
        "extern pEffect SpellEffects[TOTAL_SPELL_EFFECTS];\n\n" + BRIDGE_DEFINITION,
        "Spell.cpp optional resolver definition",
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
    if text.count(BRIDGE_DEFINITION) != 1:
        raise PatchError("Spell.cpp does not contain exactly one optional resolver definition")
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
    print("  core dependency: optional resolver; module-disabled build remains stock")
    print("  normalized cast base: interpolated by player level")
    print("  normal haste/spell cast modifiers: preserved exactly once")
    print("  triggered-direct/non-custom spells: stock path unchanged")
    print("  hook point: before cheat handling, movement checks and ReSetTimer()")


if __name__ == "__main__":
    main()

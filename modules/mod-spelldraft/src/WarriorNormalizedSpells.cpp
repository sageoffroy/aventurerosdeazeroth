#include "Player.h"
#include "SpellAuraEffects.h"
#include "SpellInfo.h"
#include "SpellScript.h"

namespace
{
constexpr uint32 SPELLDRAFT_HEROIC_STRIKE = 200078;
constexpr uint8 HEROIC_STRIKE_DAZED_MIN_LEVEL = 66;
constexpr uint32 ICON_GENERIC_DAZE = 15;
constexpr uint32 SPELL_GENERIC_AFTERMATH = 18118;

class spell_spelldraft_warr_heroic_strike : public SpellScript
{
    PrepareSpellScript(spell_spelldraft_warr_heroic_strike);

    bool Load() override
    {
        Unit* caster = GetCaster();
        return GetSpellInfo()->Id == SPELLDRAFT_HEROIC_STRIKE
            && caster
            && caster->GetLevel() >= HEROIC_STRIKE_DAZED_MIN_LEVEL;
    }

    void HandleOnHit()
    {
        Unit* target = GetHitUnit();
        if (!target)
            return;

        Unit::AuraEffectList const& auraEffects = target->GetAuraEffectsByType(SPELL_AURA_MOD_DECREASE_SPEED);
        bool bonusDamage = false;
        for (AuraEffect* effect : auraEffects)
        {
            SpellInfo const* spellInfo = effect->GetSpellInfo();
            if (!spellInfo)
                continue;

            // Keep AzerothCore's WotLK Heroic Strike Dazed detection exactly.
            if (spellInfo->SpellFamilyName == SPELLFAMILY_WARRIOR
                && (spellInfo->SpellFamilyFlags[1] & (0x20 | 0x200000)))
            {
                bonusDamage = true;
                break;
            }

            if (spellInfo->SpellIconID == ICON_GENERIC_DAZE
                && ((spellInfo->Mechanic == MECHANIC_DAZE || spellInfo->HasEffectMechanic(MECHANIC_DAZE))
                    || (spellInfo->Mechanic == MECHANIC_SNARE || spellInfo->HasEffectMechanic(MECHANIC_SNARE))))
            {
                bonusDamage = true;
                break;
            }

            if (spellInfo->Id == SPELL_GENERIC_AFTERMATH
                || (spellInfo->SpellFamilyName == SPELLFAMILY_MAGE && (spellInfo->SpellFamilyFlags[1] & 0x40))
                || (spellInfo->SpellFamilyName == SPELLFAMILY_PALADIN && (spellInfo->SpellFamilyFlags[2] & 0x4000)))
            {
                bonusDamage = true;
                break;
            }
        }

        if (bonusDamage)
        {
            int32 damage = GetHitDamage();
            AddPct(damage, 35);
            SetHitDamage(damage);
        }
    }

    void Register() override
    {
        OnHit += SpellHitFn(spell_spelldraft_warr_heroic_strike::HandleOnHit);
    }
};
}

void AddSpellDraftWarriorScripts()
{
    RegisterSpellScript(spell_spelldraft_warr_heroic_strike);
}

#include "Player.h"
#include "SpellAuraEffects.h"
#include "SpellInfo.h"
#include "SpellScript.h"

#include <array>

namespace
{
constexpr uint32 SPELLDRAFT_HEROIC_STRIKE = 200078;
constexpr uint32 SPELLDRAFT_REND = 200772;
constexpr uint8 HEROIC_STRIKE_DAZED_MIN_LEVEL = 66;
constexpr uint8 REND_HIGH_HEALTH_BONUS_MIN_LEVEL = 71;
constexpr uint32 ICON_GENERIC_DAZE = 15;
constexpr uint32 SPELL_GENERIC_AFTERMATH = 18118;

struct ThreatAnchor
{
    uint8 level;
    int32 flatThreat;
};

constexpr std::array<ThreatAnchor, 13> HEROIC_STRIKE_THREAT_ANCHORS = {{
    {1, 5},
    {8, 10},
    {16, 16},
    {24, 22},
    {32, 31},
    {40, 48},
    {48, 70},
    {56, 92},
    {60, 104},
    {66, 121},
    {70, 164},
    {72, 224},
    {76, 259},
}};

int32 HeroicStrikeFlatThreat(uint8 level)
{
    if (level <= HEROIC_STRIKE_THREAT_ANCHORS.front().level)
        return HEROIC_STRIKE_THREAT_ANCHORS.front().flatThreat;
    if (level >= HEROIC_STRIKE_THREAT_ANCHORS.back().level)
        return HEROIC_STRIKE_THREAT_ANCHORS.back().flatThreat;

    for (std::size_t index = 0; index + 1 < HEROIC_STRIKE_THREAT_ANCHORS.size(); ++index)
    {
        ThreatAnchor const& left = HEROIC_STRIKE_THREAT_ANCHORS[index];
        ThreatAnchor const& right = HEROIC_STRIKE_THREAT_ANCHORS[index + 1];
        if (level < left.level || level > right.level)
            continue;

        int32 span = int32(right.level) - int32(left.level);
        int32 offset = int32(level) - int32(left.level);
        int32 delta = right.flatThreat - left.flatThreat;
        return left.flatThreat + (delta * offset + span / 2) / span;
    }

    return HEROIC_STRIKE_THREAT_ANCHORS.back().flatThreat;
}

class spell_spelldraft_warr_heroic_strike : public SpellScript
{
    PrepareSpellScript(spell_spelldraft_warr_heroic_strike);

    bool Load() override
    {
        return GetSpellInfo()->Id == SPELLDRAFT_HEROIC_STRIKE && GetCaster();
    }

    void HandleOnHit()
    {
        Unit* caster = GetCaster();
        Unit* target = GetHitUnit();
        if (!caster || !target)
            return;

        // Native Heroic Strike has a rank-specific flat threat row in
        // spell_threat. The normalized spell is rankless, so reproduce that
        // numeric progression continuously from the exact native anchors.
        target->AddThreat(
            caster,
            float(HeroicStrikeFlatThreat(caster->GetLevel())),
            SPELL_SCHOOL_MASK_NORMAL,
            GetSpellInfo()
        );

        // Ranks 1-9 do not have the Dazed bonus. It starts with native rank 10
        // at level 66, so preserve that breakpoint in the rankless spell.
        if (caster->GetLevel() < HEROIC_STRIKE_DAZED_MIN_LEVEL)
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

class spell_spelldraft_warr_rend : public AuraScript
{
    PrepareAuraScript(spell_spelldraft_warr_rend);

    bool Load() override
    {
        return GetSpellInfo()->Id == SPELLDRAFT_REND && GetCaster();
    }

    void CalculateAmount(AuraEffect const* aurEff, int32& amount, bool& canBeRecalculated)
    {
        Unit* caster = GetCaster();
        if (!caster)
            return;

        canBeRecalculated = false;

        // Preserve AzerothCore's WotLK Rend formula exactly:
        // 0.2 * (average main-hand base damage + AP / 14 * weapon speed)
        // is added to EACH of the five 3-second ticks.
        float ap = caster->GetTotalAttackPowerValue(BASE_ATTACK);
        int32 mws = caster->GetAttackTime(BASE_ATTACK);
        float mwbMin = 0.f;
        float mwbMax = 0.f;
        for (uint8 index = 0; index < MAX_ITEM_PROTO_DAMAGES; ++index)
        {
            mwbMin += caster->GetWeaponDamageRange(BASE_ATTACK, MINDAMAGE, index);
            mwbMax += caster->GetWeaponDamageRange(BASE_ATTACK, MAXDAMAGE, index);
        }

        float mwb = ((mwbMin + mwbMax) / 2 + ap * mws / 14000) * 0.2f;
        amount += int32(caster->ApplyEffectModifiers(GetSpellInfo(), aurEff->GetEffIndex(), mwb));

        // Native AzerothCore checks GetRank() >= 9, which corresponds to the
        // level-71 and level-76 ranks. The normalized spell is rankless, so use
        // the equivalent player-level breakpoint and preserve the 35% value.
        if (caster->GetLevel() >= REND_HIGH_HEALTH_BONUS_MIN_LEVEL
            && GetUnitOwner()->HasAuraState(AURA_STATE_HEALTH_ABOVE_75_PERCENT, GetSpellInfo(), caster))
        {
            AddPct(amount, 35);
        }
    }

    void Register() override
    {
        DoEffectCalcAmount += AuraEffectCalcAmountFn(
            spell_spelldraft_warr_rend::CalculateAmount,
            EFFECT_0,
            SPELL_AURA_PERIODIC_DAMAGE
        );
    }
};
}

void AddSpellDraftWarriorScripts()
{
    RegisterSpellScript(spell_spelldraft_warr_heroic_strike);
    RegisterSpellScript(spell_spelldraft_warr_rend);
}

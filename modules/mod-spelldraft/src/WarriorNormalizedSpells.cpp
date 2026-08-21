#include "CustomSpellThreat.h"

#include "Player.h"
#include "Spell.h"
#include "SpellAuraEffects.h"
#include "SpellInfo.h"
#include "SpellScript.h"
#include "ThreatManager.h"

namespace
{
constexpr uint32 SPELLDRAFT_HEROIC_STRIKE = 200078;
constexpr uint32 SPELLDRAFT_REND = 200772;
constexpr uint8 HEROIC_STRIKE_DAZED_MIN_LEVEL = 66;
constexpr uint8 REND_HIGH_HEALTH_BONUS_MIN_LEVEL = 71;
constexpr uint32 ICON_GENERIC_DAZE = 15;
constexpr uint32 SPELL_GENERIC_AFTERMATH = 18118;

// Native spell_threat flatMod is applied once per cast and divided by the final
// target count. Normalized spells cannot store a player-level-dependent flatMod
// in the static world DB, so the generated threat table owns that one numeric
// field. pctMod/apPctMod remain normal static spell_threat data on the runtime
// ID and are therefore still handled by AzerothCore itself.
class spell_spelldraft_warr_flat_threat : public SpellScript
{
    PrepareSpellScript(spell_spelldraft_warr_flat_threat);

    bool Load() override
    {
        Player* player = GetCaster() ? GetCaster()->ToPlayer() : nullptr;
        if (!player)
            return false;

        int32 flatMod = 0;
        float pctMod = 1.0f;
        float apPctMod = 0.0f;
        return GetCustomSpellThreatRule(
            player,
            GetSpellInfo()->Id,
            flatMod,
            pctMod,
            apPctMod
        );
    }

    void HandleOnHit()
    {
        Player* player = GetCaster() ? GetCaster()->ToPlayer() : nullptr;
        Unit* target = GetHitUnit();
        if (!player || !target)
            return;

        int32 flatMod = 0;
        float pctMod = 1.0f;
        float apPctMod = 0.0f;
        if (!GetCustomSpellThreatRule(
            player,
            GetSpellInfo()->Id,
            flatMod,
            pctMod,
            apPctMod
        ) || flatMod == 0)
        {
            return;
        }

        std::list<Spell::TargetInfo>* targets = GetSpell()->GetUniqueTargetInfo();
        if (!targets || targets->empty())
            return;

        // Match Spell::HandleThreatSpells: flat threat is divided by every
        // selected unit target, including misses; OnHit naturally runs only for
        // the successful target, so missed shares remain zero.
        float threat = float(flatMod) / float(targets->size());
        target->GetThreatMgr().AddThreat(player, threat, GetSpellInfo(), true);
    }

    void Register() override
    {
        OnHit += SpellHitFn(spell_spelldraft_warr_flat_threat::HandleOnHit);
    }
};

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
    RegisterSpellScript(spell_spelldraft_warr_flat_threat);
    RegisterSpellScript(spell_spelldraft_warr_heroic_strike);
    RegisterSpellScript(spell_spelldraft_warr_rend);
}

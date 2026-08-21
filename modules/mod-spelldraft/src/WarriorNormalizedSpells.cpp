#include "CustomSpellThreat.h"

#include "Player.h"
#include "Spell.h"
#include "SpellAuraEffects.h"
#include "SpellInfo.h"
#include "SpellScript.h"
#include "ThreatManager.h"

#include <algorithm>
#include <array>

namespace
{
constexpr uint32 SPELLDRAFT_HEROIC_STRIKE = 200078;
constexpr uint32 SPELLDRAFT_REND = 200772;
constexpr uint32 SPELLDRAFT_EXECUTE = 205308;
constexpr uint32 SPELL_WARRIOR_EXECUTE_HELPER = 20647;
constexpr uint32 SPELL_WARRIOR_GLYPH_OF_EXECUTION = 58367;
constexpr uint32 WARRIOR_ICON_ID_SUDDEN_DEATH = 1989;
constexpr uint8 HEROIC_STRIKE_DAZED_MIN_LEVEL = 66;
constexpr uint8 REND_HIGH_HEALTH_BONUS_MIN_LEVEL = 71;
constexpr uint32 ICON_GENERIC_DAZE = 15;
constexpr uint32 SPELL_GENERIC_AFTERMATH = 18118;

struct ExecuteRageAnchor
{
    uint8 level;
    float damagePerRageUnit;
};

// AzerothCore stores rage internally in tenths. The native Execute
// DamageMultiplier therefore uses 0.3 for +3 damage per displayed Rage,
// 0.6 for +6, and so on. These are the exact WotLK rank anchors.
constexpr std::array<ExecuteRageAnchor, 9> EXECUTE_RAGE_ANCHORS = {{
    {24, 0.3f},
    {32, 0.6f},
    {40, 0.9f},
    {48, 1.2f},
    {56, 1.5f},
    {65, 1.8f},
    {70, 2.1f},
    {73, 3.0f},
    {80, 3.8f},
}};

float ExecuteRageMultiplier(uint8 level)
{
    ExecuteRageAnchor const& first = EXECUTE_RAGE_ANCHORS.front();
    if (level < first.level)
    {
        // Same level-offset policy used by the canonical normalizer for
        // absolute magnitudes below the first native rank.
        constexpr float LOW_LEVEL_OFFSET = 2.0f;
        return first.damagePerRageUnit
            * (float(level) + LOW_LEVEL_OFFSET)
            / (float(first.level) + LOW_LEVEL_OFFSET);
    }

    if (level >= EXECUTE_RAGE_ANCHORS.back().level)
        return EXECUTE_RAGE_ANCHORS.back().damagePerRageUnit;

    for (std::size_t index = 0; index + 1 < EXECUTE_RAGE_ANCHORS.size(); ++index)
    {
        ExecuteRageAnchor const& left = EXECUTE_RAGE_ANCHORS[index];
        ExecuteRageAnchor const& right = EXECUTE_RAGE_ANCHORS[index + 1];
        if (level < left.level || level > right.level)
            continue;

        float t = float(level - left.level) / float(right.level - left.level);
        return left.damagePerRageUnit
            + (right.damagePerRageUnit - left.damagePerRageUnit) * t;
    }

    return EXECUTE_RAGE_ANCHORS.back().damagePerRageUnit;
}

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

        auto* targets = GetSpell()->GetUniqueTargetInfo();
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

class spell_spelldraft_warr_execute : public SpellScript
{
    PrepareSpellScript(spell_spelldraft_warr_execute);

    bool Validate(SpellInfo const* /*spellInfo*/) override
    {
        return ValidateSpellInfo({
            SPELL_WARRIOR_EXECUTE_HELPER,
            SPELL_WARRIOR_GLYPH_OF_EXECUTION
        });
    }

    bool Load() override
    {
        return GetSpellInfo()->Id == SPELLDRAFT_EXECUTE && GetCaster();
    }

    void SendMiss(SpellMissInfo missInfo)
    {
        if (missInfo != SPELL_MISS_NONE)
        {
            if (Unit* caster = GetCaster())
            {
                if (Unit* target = GetHitUnit())
                    caster->SendSpellMiss(target, SPELL_WARRIOR_EXECUTE_HELPER, missInfo);
            }
        }
    }

    void HandleEffect(SpellEffIndex /*effIndex*/)
    {
        Unit* caster = GetCaster();
        Unit* target = GetHitUnit();
        if (!caster || !target)
            return;

        SpellInfo const* spellInfo = GetSpellInfo();
        int32 rageUsed = std::min<int32>(
            300 - spellInfo->CalcPowerCost(caster, SpellSchoolMask(spellInfo->SchoolMask)),
            caster->GetPower(POWER_RAGE)
        );
        int32 newRage = std::max<int32>(0, caster->GetPower(POWER_RAGE) - rageUsed);

        // Preserve native Sudden Death rage retention.
        if (AuraEffect* aurEff = caster->GetAuraEffect(
            SPELL_AURA_PROC_TRIGGER_SPELL,
            SPELLFAMILY_GENERIC,
            WARRIOR_ICON_ID_SUDDEN_DEATH,
            EFFECT_0))
        {
            int32 rageSave = aurEff->GetSpellInfo()->Effects[EFFECT_1].CalcValue() * 10;
            newRage = std::max(newRage, rageSave);
        }

        caster->SetPower(POWER_RAGE, uint32(newRage));

        // Preserve Glyph of Execution as virtual extra Rage exactly as native.
        if (AuraEffect* aurEff = caster->GetAuraEffect(
            SPELL_WARRIOR_GLYPH_OF_EXECUTION,
            EFFECT_0))
        {
            rageUsed += aurEff->GetAmount() * 10;
        }

        // Base damage comes from the canonical level-normalized effect curve.
        // Only the native rank-specific DamageMultiplier is replaced here.
        int32 bp = GetEffectValue()
            + int32(rageUsed * ExecuteRageMultiplier(caster->GetLevel())
                + caster->GetTotalAttackPowerValue(BASE_ATTACK) * 0.2f);

        caster->CastCustomSpell(
            target,
            SPELL_WARRIOR_EXECUTE_HELPER,
            &bp,
            nullptr,
            nullptr,
            true,
            nullptr,
            nullptr,
            GetOriginalCaster() ? GetOriginalCaster()->GetGUID() : caster->GetGUID()
        );
    }

    void Register() override
    {
        BeforeHit += BeforeSpellHitFn(spell_spelldraft_warr_execute::SendMiss);
        OnEffectHitTarget += SpellEffectFn(
            spell_spelldraft_warr_execute::HandleEffect,
            EFFECT_0,
            SPELL_EFFECT_DUMMY
        );
    }
};
}

void AddSpellDraftWarriorScripts()
{
    RegisterSpellScript(spell_spelldraft_warr_flat_threat);
    RegisterSpellScript(spell_spelldraft_warr_heroic_strike);
    RegisterSpellScript(spell_spelldraft_warr_rend);
    RegisterSpellScript(spell_spelldraft_warr_execute);
}

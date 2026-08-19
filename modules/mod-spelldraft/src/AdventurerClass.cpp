#include "Configuration/Config.h"
#include "Log.h"
#include "Player.h"
#include "ScriptDefines/PlayerScript.h"

namespace
{
constexpr uint32 SKILL_RIDING = 762;
constexpr uint32 SPELL_APPRENTICE_RIDING = 33388;
constexpr uint32 SPELL_BROWN_HORSE = 458;
constexpr uint32 APPRENTICE_RIDING_VALUE = 75;

constexpr uint32 UNIVERSAL_SKILLS[] =
{
    43,   // Swords
    44,   // Axes
    45,   // Bows
    46,   // Guns
    54,   // Maces
    55,   // Two-Handed Swords
    95,   // Defense
    136,  // Staves
    160,  // Two-Handed Maces
    162,  // Unarmed
    172,  // Two-Handed Axes
    173,  // Daggers
    176,  // Thrown
    226,  // Crossbows
    228,  // Wands
    229,  // Polearms
    293,  // Plate
    413,  // Mail
    414,  // Leather
    415,  // Cloth
    433,  // Shield
    473   // Fist Weapons
};

// The native classless baseline is installed only during PLAYERHOOK_ON_CREATE,
// while the Player is still out of world, and persisted immediately afterwards.
// First login therefore receives these as initial character data instead of
// producing "Has aprendido..." messages.
constexpr uint32 UNIVERSAL_SPELLS[] =
{
    81,    // Dodge (Passive)
    107,   // Block
    3127,  // Parry (Passive)

    9078,  // Cloth
    9077,  // Leather
    8737,  // Mail
    750,   // Plate Mail

    196,   // One-Handed Axes
    197,   // Two-Handed Axes
    198,   // One-Handed Maces
    199,   // Two-Handed Maces
    201,   // One-Handed Swords
    202,   // Two-Handed Swords
    227,   // Staves
    1180,  // Daggers
    200,   // Polearms
    15590, // Fist Weapons
    264,   // Bows
    5011,  // Crossbows
    266,   // Guns
    2567,  // Thrown
    5009,  // Wands

    75,                       // Auto Shot
    5019,                     // Shoot
    2764,                     // Throw
    SPELL_APPRENTICE_RIDING,  // Apprentice Riding
    SPELL_BROWN_HORSE         // Brown Horse
};

constexpr uint32 HUMAN_SPELLS[] = { 59752, 20598, 20599, 20597, 20864 };
constexpr uint32 ORC_SPELLS[] = { 20572, 20573, 20575, 20574 };
constexpr uint32 DWARF_SPELLS[] = { 20594, 20596, 20595, 2481, 59224 };
constexpr uint32 NIGHT_ELF_SPELLS[] = { 58984, 20582, 20585, 20583 };
constexpr uint32 UNDEAD_SPELLS[] = { 7744, 20577, 5227, 20579 };
constexpr uint32 TAUREN_SPELLS[] = { 20549, 20550, 20552, 20551 };
constexpr uint32 GNOME_SPELLS[] = { 20589, 20591, 20593, 20592 };
constexpr uint32 TROLL_SPELLS[] = { 26297, 20555, 20557, 20558, 26290, 58943 };
constexpr uint32 BLOOD_ELF_SPELLS[] = { 28730, 20554, 822 };
// 28877 teaches racial skill 756, which is not valid for Draenei (race 11).
constexpr uint32 DRAENEI_SPELLS[] = { 59547, 28878, 28875 };

bool IsBotSession(Player const* player)
{
#ifdef MOD_PLAYERBOTS
    return player->GetSession() && player->GetSession()->IsBot();
#else
    return false;
#endif
}

bool IsAdventurer(Player const* player)
{
    return player && player->getClass() == CLASS_ADVENTURER;
}

void LearnMissingSpells(Player* player, uint32 const* spells, uint32 count)
{
    for (uint32 i = 0; i < count; ++i)
    {
        if (!player->HasSpell(spells[i]))
            player->learnSpell(spells[i]);
    }
}

template <uint32 N>
void LearnMissingSpells(Player* player, uint32 const (&spells)[N])
{
    LearnMissingSpells(player, spells, N);
}

void LearnRacialBaseline(Player* player)
{
    switch (player->getRace())
    {
        case RACE_HUMAN:
            LearnMissingSpells(player, HUMAN_SPELLS);
            break;
        case RACE_ORC:
            LearnMissingSpells(player, ORC_SPELLS);
            break;
        case RACE_DWARF:
            LearnMissingSpells(player, DWARF_SPELLS);
            break;
        case RACE_NIGHTELF:
            LearnMissingSpells(player, NIGHT_ELF_SPELLS);
            break;
        case RACE_UNDEAD_PLAYER:
            LearnMissingSpells(player, UNDEAD_SPELLS);
            break;
        case RACE_TAUREN:
            LearnMissingSpells(player, TAUREN_SPELLS);
            break;
        case RACE_GNOME:
            LearnMissingSpells(player, GNOME_SPELLS);
            break;
        case RACE_TROLL:
            LearnMissingSpells(player, TROLL_SPELLS);
            break;
        case RACE_BLOODELF:
            LearnMissingSpells(player, BLOOD_ELF_SPELLS);
            break;
        case RACE_DRAENEI:
            LearnMissingSpells(player, DRAENEI_SPELLS);
            break;
        default:
            break;
    }
}

void SetLanguageSkill(Player* player, uint32 skillId)
{
    player->SetSkill(skillId, 1, 300, 300);
}

void SetRacialLanguages(Player* player)
{
    // Faction language plus the race-specific language. Installing these at
    // creation time avoids login-side language grants and their chat feedback.
    switch (player->getRace())
    {
        case RACE_HUMAN:
            SetLanguageSkill(player, 98);   // Common
            break;
        case RACE_DWARF:
            SetLanguageSkill(player, 98);   // Common
            SetLanguageSkill(player, 111);  // Dwarven
            break;
        case RACE_NIGHTELF:
            SetLanguageSkill(player, 98);   // Common
            SetLanguageSkill(player, 113);  // Darnassian
            break;
        case RACE_GNOME:
            SetLanguageSkill(player, 98);   // Common
            SetLanguageSkill(player, 313);  // Gnomish
            break;
        case RACE_DRAENEI:
            SetLanguageSkill(player, 98);   // Common
            SetLanguageSkill(player, 759);  // Draenei
            break;
        case RACE_ORC:
            SetLanguageSkill(player, 109);  // Orcish
            break;
        case RACE_UNDEAD_PLAYER:
            SetLanguageSkill(player, 109);  // Orcish
            SetLanguageSkill(player, 673);  // Gutterspeak
            break;
        case RACE_TAUREN:
            SetLanguageSkill(player, 109);  // Orcish
            SetLanguageSkill(player, 115);  // Taurahe
            break;
        case RACE_TROLL:
            SetLanguageSkill(player, 109);  // Orcish
            SetLanguageSkill(player, 315);  // Troll
            break;
        case RACE_BLOODELF:
            SetLanguageSkill(player, 109);  // Orcish
            SetLanguageSkill(player, 137);  // Thalassian
            break;
        default:
            break;
    }
}

void ApplyServerCapabilities(Player* player)
{
    uint32 allWeapons = (1u << MAX_ITEM_SUBCLASS_WEAPON) - 1u;
    uint32 allArmor = (1u << MAX_ITEM_SUBCLASS_ARMOR) - 1u;

    player->AddWeaponProficiency(allWeapons);
    player->AddArmorProficiency(allArmor);
    player->SetCanParry(true);
    player->SetCanBlock(true);
    player->UpdateDefenseBonusesMod();
}

void EnsureStarterRidingSkill(Player* player)
{
    // Apprentice Riding is a permanent part of the Adventurer level-1 baseline.
    // Keep the raw Riding skill line in sync with the learned training spell so
    // the Brown Horse is immediately usable on first login.
    player->SetSkill(SKILL_RIDING, 1, APPRENTICE_RIDING_VALUE, APPRENTICE_RIDING_VALUE);
}

void SyncAdventurerBaseMana(Player* player)
{
    if (!IsAdventurer(player))
        return;

    // SpellDraft owns a custom maximum-mana pool, but WotLK percentage spell
    // costs use UNIT_FIELD_BASE_MANA through SpellInfo::CalcPowerCost(). Derive
    // that field from the live maximum mana with the normal WotLK intellect
    // contribution instead of leaving class 10 on its small DB BaseMana value.
    //
    // ManaFromIntellect = Int                         (Int < 20)
    // ManaFromIntellect = 20 + 15 * (Int - 20)       (Int >= 20)
    // BaseMana          = MaxMana - ManaFromIntellect
    float intellect = float(player->GetStat(STAT_INTELLECT));
    float baseIntellect = intellect < 20.0f ? intellect : 20.0f;
    float moreIntellect = intellect - baseIntellect;
    uint32 manaFromIntellect = uint32(baseIntellect + moreIntellect * 15.0f);
    uint32 maxMana = player->GetMaxPower(POWER_MANA);
    uint32 baseMana = maxMana > manaFromIntellect ? maxMana - manaFromIntellect : 0;

    if (player->GetCreateMana() != baseMana)
        player->SetCreateMana(baseMana);
}

void FinalizeNewAdventurer(Player* player)
{
    if (!IsAdventurer(player))
        return;

    uint32 maxSkillValue = player->GetLevel() * 5;
    if (maxSkillValue > 400)
        maxSkillValue = 400;

    for (uint32 skillId : UNIVERSAL_SKILLS)
        player->SetSkill(skillId, 0, maxSkillValue, maxSkillValue);

    // Do not depend on PlayerStart.AllSpells, custom spell tables or login Lua.
    // The native class owns its entire baseline before first world entry.
    LearnMissingSpells(player, UNIVERSAL_SPELLS);
    EnsureStarterRidingSkill(player);
    LearnRacialBaseline(player);
    SetRacialLanguages(player);
    ApplyServerCapabilities(player);

    // PLAYERHOOK_ON_CREATE runs after AzerothCore's original creation transaction,
    // so explicitly persist the completed baseline before this temporary Player
    // object is destroyed.
    player->SaveToDB(false, false);
}
}

class AdventurerClassPlayerScript : public PlayerScript
{
public:
    AdventurerClassPlayerScript() : PlayerScript("AdventurerClassPlayerScript",
    {
        PLAYERHOOK_ON_CREATE,
        PLAYERHOOK_ON_LOGIN,
        PLAYERHOOK_ON_UPDATE,
        PLAYERHOOK_ON_BEFORE_UPDATE_ATTACK_POWER_AND_DAMAGE
    }) {}

    void OnPlayerBeforeUpdateAttackPowerAndDamage(
        Player* player,
        float& level,
        float& val2,
        bool ranged) override
    {
        if (!sConfigMgr->GetOption<bool>("SpellDraft.Enable", true))
            return;
        if (!IsAdventurer(player))
            return;

        if (ranged)
        {
            // Adventurer ranged baseline: Hunter-style progression.
            // Agility remains the ranged physical stat while level provides
            // the baseline growth expected by weapon damage at higher levels.
            val2 = level * 2.0f
                + player->GetStat(STAT_AGILITY)
                - 10.0f;
        }
        else
        {
            // Adventurer melee baseline: hybrid physical progression.
            // Both Strength and Agility remain viable for classless builds.
            val2 = level * 2.0f
                + player->GetStat(STAT_STRENGTH)
                + player->GetStat(STAT_AGILITY)
                - 20.0f;
        }
    }

    void OnPlayerCreate(Player* player) override
    {
        if (!sConfigMgr->GetOption<bool>("SpellDraft.Enable", true))
            return;
        if (IsBotSession(player) || !IsAdventurer(player))
            return;

        FinalizeNewAdventurer(player);
        LOG_INFO("module", "[SpellDraft] Created native Adventurer {} (class 10).", player->GetName());
    }

    void OnPlayerLogin(Player* player) override
    {
        if (!sConfigMgr->GetOption<bool>("SpellDraft.Enable", true))
            return;
        if (IsBotSession(player) || !IsAdventurer(player))
            return;

        // Only volatile flags are restored here. No spell or skill is learned,
        // removed or advanced during login for a brand-new Adventurer.
        ApplyServerCapabilities(player);
    }

    void OnPlayerUpdate(Player* player, uint32 /*diff*/) override
    {
        if (!sConfigMgr->GetOption<bool>("SpellDraft.Enable", true))
            return;
        if (IsBotSession(player) || !IsAdventurer(player))
            return;

        // resources.lua can raise MaxMana after login/level/map changes. Keep
        // BaseMana synchronized continuously; SetCreateMana only writes when the
        // derived value actually changed, so normal update ticks stay cheap.
        SyncAdventurerBaseMana(player);
    }
};

void AddAdventurerClassScripts()
{
    new AdventurerClassPlayerScript();
}

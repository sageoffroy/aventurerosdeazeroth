#include "CustomSpellScaling.h"

#include "Configuration/Config.h"
#include "Log.h"
#include "Player.h"
#include "Random.h"
#include "ScriptDefines/PlayerScript.h"
#include "Spell.h"

#include <array>
#include <fstream>
#include <sstream>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace
{
struct EffectRange
{
    bool active = false;
    int32 minimum = 0;
    int32 maximum = 0;
};

struct LevelRule
{
    bool present = false;
    int32 durationMs = 0;
    std::array<EffectRange, 3> effects{};
};

using SpellLevels = std::vector<LevelRule>;

bool g_customScalingEnabled = false;
std::unordered_map<uint32, SpellLevels> g_customScaling;

SpellValueMod EffectSpellValueMod(uint8 effectIndex)
{
    switch (effectIndex)
    {
        case 0:
            return SPELLVALUE_BASE_POINT0;
        case 1:
            return SPELLVALUE_BASE_POINT1;
        default:
            return SPELLVALUE_BASE_POINT2;
    }
}

std::string ScalingFilePath()
{
    std::string dataDir = sConfigMgr->GetOption<std::string>("DataDir", ".");
    if (!dataDir.empty() && dataDir.back() != '/' && dataDir.back() != '\\')
        dataDir += '/';

    return dataDir + "spelldraft/custom_spell_scaling.tsv";
}

bool ParseEffectRange(
    std::string const& minimumToken,
    std::string const& maximumToken,
    EffectRange& result)
{
    if (minimumToken == "x" && maximumToken == "x")
        return true;
    if (minimumToken == "x" || maximumToken == "x")
        return false;

    int32 minimum = std::stoi(minimumToken);
    int32 maximum = std::stoi(maximumToken);
    if (maximum < minimum)
        return false;

    result.active = true;
    result.minimum = minimum;
    result.maximum = maximum;
    return true;
}

bool LoadScalingFile(std::string const& path)
{
    std::ifstream input(path);
    if (!input.is_open())
    {
        LOG_ERROR(
            "module.SpellDraft",
            "Aventureros de Azeroth: normalized spell scaling file is missing: {}",
            path
        );
        return false;
    }

    std::unordered_map<uint32, SpellLevels> loaded;
    std::string line;
    uint32 lineNumber = 0;
    uint32 levelRows = 0;

    try
    {
        while (std::getline(input, line))
        {
            ++lineNumber;
            if (line.empty() || line[0] == '#')
                continue;

            std::istringstream row(line);
            uint32 spellId = 0;
            uint32 level = 0;
            int32 durationMs = 0;
            std::array<std::string, 6> amountTokens{};
            if (!(row >> spellId >> level >> durationMs
                >> amountTokens[0] >> amountTokens[1]
                >> amountTokens[2] >> amountTokens[3]
                >> amountTokens[4] >> amountTokens[5]))
            {
                LOG_ERROR(
                    "module.SpellDraft",
                    "Aventureros de Azeroth: malformed normalized spell scaling row {} in {}",
                    lineNumber,
                    path
                );
                return false;
            }

            std::string extra;
            if (row >> extra)
            {
                LOG_ERROR(
                    "module.SpellDraft",
                    "Aventureros de Azeroth: unexpected extra field on normalized spell scaling row {} in {}",
                    lineNumber,
                    path
                );
                return false;
            }

            if (spellId < 201000 || spellId > 201999 || level == 0 || level > 255 || durationMs < 0)
            {
                LOG_ERROR(
                    "module.SpellDraft",
                    "Aventureros de Azeroth: invalid normalized spell ID/level/duration on row {} in {}",
                    lineNumber,
                    path
                );
                return false;
            }

            LevelRule rule;
            rule.present = true;
            rule.durationMs = durationMs;
            for (uint8 effectIndex = 0; effectIndex < 3; ++effectIndex)
            {
                if (!ParseEffectRange(
                    amountTokens[effectIndex * 2],
                    amountTokens[effectIndex * 2 + 1],
                    rule.effects[effectIndex]))
                {
                    LOG_ERROR(
                        "module.SpellDraft",
                        "Aventureros de Azeroth: invalid normalized effect range on row {} in {}",
                        lineNumber,
                        path
                    );
                    return false;
                }
            }

            SpellLevels& levels = loaded[spellId];
            if (levels.size() <= level)
                levels.resize(level + 1);
            if (levels[level].present)
            {
                LOG_ERROR(
                    "module.SpellDraft",
                    "Aventureros de Azeroth: duplicate normalized spell/level {}:{} in {}",
                    spellId,
                    level,
                    path
                );
                return false;
            }

            levels[level] = rule;
            ++levelRows;
        }
    }
    catch (std::exception const& exception)
    {
        LOG_ERROR(
            "module.SpellDraft",
            "Aventureros de Azeroth: failed to parse normalized spell scaling file {}: {}",
            path,
            exception.what()
        );
        return false;
    }

    if (loaded.empty())
    {
        LOG_ERROR(
            "module.SpellDraft",
            "Aventureros de Azeroth: normalized spell scaling file is empty: {}",
            path
        );
        return false;
    }

    for (auto const& [spellId, levels] : loaded)
    {
        if (levels.size() <= 1)
        {
            LOG_ERROR(
                "module.SpellDraft",
                "Aventureros de Azeroth: normalized spell {} has no level rows in {}",
                spellId,
                path
            );
            return false;
        }

        for (uint32 level = 1; level < levels.size(); ++level)
        {
            if (!levels[level].present)
            {
                LOG_ERROR(
                    "module.SpellDraft",
                    "Aventureros de Azeroth: normalized spell {} is missing level {} in {}",
                    spellId,
                    level,
                    path
                );
                return false;
            }
        }
    }

    g_customScaling = std::move(loaded);
    LOG_INFO(
        "module.SpellDraft",
        "Aventureros de Azeroth: loaded normalized scaling for {} custom spells ({} level rows).",
        g_customScaling.size(),
        levelRows
    );
    return true;
}

class SpellDraftCustomScalingPlayerScript : public PlayerScript
{
public:
    SpellDraftCustomScalingPlayerScript()
        : PlayerScript("SpellDraftCustomScalingPlayerScript", { PLAYERHOOK_ON_SPELL_CAST })
    {
    }

    void OnPlayerSpellCast(Player* player, Spell* spell, bool /*skipCheck*/) override
    {
        if (!g_customScalingEnabled || !player || !spell)
            return;

        auto const spellItr = g_customScaling.find(spell->GetSpellInfo()->Id);
        if (spellItr == g_customScaling.end())
            return;

        SpellLevels const& levels = spellItr->second;
        if (levels.size() <= 1)
            return;

        uint32 level = player->GetLevel();
        if (level >= levels.size())
            level = uint32(levels.size() - 1);
        if (level == 0)
            level = 1;

        LevelRule const& rule = levels[level];
        if (!rule.present)
            return;

        for (uint8 effectIndex = 0; effectIndex < 3; ++effectIndex)
        {
            EffectRange const& range = rule.effects[effectIndex];
            if (!range.active)
                continue;

            int32 value = range.minimum;
            if (range.maximum > range.minimum)
                value = irand(range.minimum, range.maximum);
            spell->SetSpellValue(EffectSpellValueMod(effectIndex), value);
        }

        if (rule.durationMs > 0)
            spell->SetSpellValue(SPELLVALUE_AURA_DURATION, rule.durationMs);
    }
};
}

void ConfigureCustomSpellScaling(bool enabled)
{
    g_customScalingEnabled = false;
    g_customScaling.clear();

    if (!enabled)
    {
        LOG_INFO(
            "module.SpellDraft",
            "Aventureros de Azeroth: normalized custom spell scaling disabled."
        );
        return;
    }

    std::string const path = ScalingFilePath();
    if (!LoadScalingFile(path))
        return;

    g_customScalingEnabled = true;
}

void AddCustomSpellScalingScripts()
{
    new SpellDraftCustomScalingPlayerScript();
}

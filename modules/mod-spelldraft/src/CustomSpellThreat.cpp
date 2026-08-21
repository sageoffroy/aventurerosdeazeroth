#include "CustomSpellThreat.h"

#include "Configuration/Config.h"
#include "Log.h"
#include "Player.h"

#include <exception>
#include <fstream>
#include <sstream>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

// The resolver slot lives in core Spell.cpp. Core callers therefore never take
// a direct link dependency on mod-spelldraft; enabling this module only installs
// the callback after the generated level table loads successfully.
using AventurerosCustomSpellThreatResolver = bool (*)(
    Player const*, uint32, int32&, float&, float&);
void SetAventurerosCustomSpellThreatResolver(AventurerosCustomSpellThreatResolver resolver);

namespace
{
struct ThreatRule
{
    bool present = false;
    int32 flatMod = 0;
    float pctMod = 1.0f;
    float apPctMod = 0.0f;
};

using SpellThreatLevels = std::vector<ThreatRule>;

bool g_customThreatEnabled = false;
std::unordered_map<uint32, SpellThreatLevels> g_customThreat;

std::string ThreatScalingFilePath()
{
    std::string dataDir = sConfigMgr->GetOption<std::string>("DataDir", ".");
    if (!dataDir.empty() && dataDir.back() != '/' && dataDir.back() != '\\')
        dataDir += '/';

    return dataDir + "spelldraft/custom_spell_threat_scaling.tsv";
}

bool LoadThreatScalingFile(std::string const& path)
{
    std::ifstream input(path);
    if (!input.is_open())
    {
        LOG_ERROR(
            "module.SpellDraft",
            "Aventureros de Azeroth: normalized threat scaling file is missing: {}",
            path
        );
        return false;
    }

    std::unordered_map<uint32, SpellThreatLevels> loaded;
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
            ThreatRule rule;
            if (!(row >> spellId >> level >> rule.flatMod >> rule.pctMod >> rule.apPctMod))
            {
                LOG_ERROR(
                    "module.SpellDraft",
                    "Aventureros de Azeroth: malformed normalized threat row {} in {}",
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
                    "Aventureros de Azeroth: unexpected extra field on normalized threat row {} in {}",
                    lineNumber,
                    path
                );
                return false;
            }

            if (spellId < 200000 || spellId > 299999 || level == 0 || level > 255
                || rule.pctMod < 0.0f || rule.apPctMod < 0.0f)
            {
                LOG_ERROR(
                    "module.SpellDraft",
                    "Aventureros de Azeroth: invalid normalized threat values on row {} in {}",
                    lineNumber,
                    path
                );
                return false;
            }

            rule.present = true;
            SpellThreatLevels& levels = loaded[spellId];
            if (levels.size() <= level)
                levels.resize(level + 1);
            if (levels[level].present)
            {
                LOG_ERROR(
                    "module.SpellDraft",
                    "Aventureros de Azeroth: duplicate normalized threat spell/level {}:{} in {}",
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
            "Aventureros de Azeroth: failed to parse normalized threat file {}: {}",
            path,
            exception.what()
        );
        return false;
    }

    for (auto const& [spellId, levels] : loaded)
    {
        if (levels.size() <= 1)
        {
            LOG_ERROR(
                "module.SpellDraft",
                "Aventureros de Azeroth: normalized threat spell {} has no level rows in {}",
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
                    "Aventureros de Azeroth: normalized threat spell {} is missing level {} in {}",
                    spellId,
                    level,
                    path
                );
                return false;
            }
        }
    }

    g_customThreat = std::move(loaded);
    LOG_INFO(
        "module.SpellDraft",
        "Aventureros de Azeroth: loaded normalized threat scaling for {} custom spells ({} level rows).",
        g_customThreat.size(),
        levelRows
    );
    return true;
}

bool ResolveCustomThreat(
    Player const* player,
    uint32 spellId,
    int32& flatMod,
    float& pctMod,
    float& apPctMod)
{
    if (!g_customThreatEnabled || !player)
        return false;

    auto const spellItr = g_customThreat.find(spellId);
    if (spellItr == g_customThreat.end())
        return false;

    SpellThreatLevels const& levels = spellItr->second;
    if (levels.size() <= 1)
        return false;

    uint32 level = player->GetLevel();
    if (level >= levels.size())
        level = uint32(levels.size() - 1);
    if (level == 0)
        level = 1;

    ThreatRule const& rule = levels[level];
    if (!rule.present)
        return false;

    flatMod = rule.flatMod;
    pctMod = rule.pctMod;
    apPctMod = rule.apPctMod;
    return true;
}
}

void ConfigureCustomSpellThreat(bool enabled)
{
    SetAventurerosCustomSpellThreatResolver(nullptr);
    g_customThreatEnabled = false;
    g_customThreat.clear();

    if (!enabled)
    {
        LOG_INFO(
            "module.SpellDraft",
            "Aventureros de Azeroth: normalized custom spell threat disabled."
        );
        return;
    }

    std::string const path = ThreatScalingFilePath();
    if (!LoadThreatScalingFile(path))
        return;

    g_customThreatEnabled = true;
    SetAventurerosCustomSpellThreatResolver(ResolveCustomThreat);
}

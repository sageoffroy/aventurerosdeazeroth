/*
 * This file is part of the AzerothCore Project. See AUTHORS file for Copyright information
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
 * or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for
 * more details.
 *
 * You should have received a copy of the GNU General Public License along
 * with this program. If not, see <http://www.gnu.org/licenses/>.
 */

#include "SpellScriptLoader.h"
#include "ScriptMgr.h"
#include "SpellScript.h"

namespace
{
// Aventureros normalized abilities use the deterministic ID rule
//   runtime = 200000 + native root.
//
// Most normalized spells should inherit spell_script_names from their native
// root. A few native mechanics, however, are bound only to later ranks rather
// than the family root (Heroic Strike's Dazed bonus is the first case). Those
// spells may declare an explicit binding for the normalized runtime ID. Exact
// runtime bindings therefore take precedence; when none exists we fall back to
// the native root exactly as before.
SpellScriptsBounds SpellScriptBounds(uint32 spellId)
{
    SpellScriptsBounds exact = sObjectMgr->GetSpellScriptsBounds(spellId);
    if (exact.first != exact.second)
        return exact;

    constexpr uint32 NORMALIZED_SPELL_MIN = 200000;
    constexpr uint32 NORMALIZED_SPELL_MAX = 299999;
    constexpr uint32 NORMALIZED_SPELL_OFFSET = 200000;

    if (spellId >= NORMALIZED_SPELL_MIN && spellId <= NORMALIZED_SPELL_MAX)
        return sObjectMgr->GetSpellScriptsBounds(spellId - NORMALIZED_SPELL_OFFSET);

    return exact;
}
}

void ScriptMgr::CreateSpellScripts(uint32 spellId, std::list<SpellScript*>& scriptVector)
{
    SpellScriptsBounds bounds = SpellScriptBounds(spellId);

    for (SpellScriptsContainer::iterator itr = bounds.first; itr != bounds.second; ++itr)
    {
        SpellScriptLoader* tempScript = ScriptRegistry<SpellScriptLoader>::GetScriptById(itr->second);
        if (!tempScript)
            continue;

        SpellScript* script = tempScript->GetSpellScript();

        if (!script)
            continue;

        // Initialize against the actual runtime ID so script validation and
        // GetSpellInfo() see the normalized DBC row while the binding itself is
        // inherited from the native source family or explicitly overridden.
        script->_Init(&tempScript->GetName(), spellId);

        scriptVector.push_back(script);
    }
}

void ScriptMgr::CreateAuraScripts(uint32 spellId, std::list<AuraScript*>& scriptVector)
{
    SpellScriptsBounds bounds = SpellScriptBounds(spellId);

    for (SpellScriptsContainer::iterator itr = bounds.first; itr != bounds.second; ++itr)
    {
        SpellScriptLoader* tempScript = ScriptRegistry<SpellScriptLoader>::GetScriptById(itr->second);
        if (!tempScript)
            continue;

        AuraScript* script = tempScript->GetAuraScript();

        if (!script)
            continue;

        script->_Init(&tempScript->GetName(), spellId);

        scriptVector.push_back(script);
    }
}

void ScriptMgr::CreateSpellScriptLoaders(uint32 spellId, std::vector<std::pair<SpellScriptLoader*, SpellScriptsContainer::iterator>>& scriptVector)
{
    SpellScriptsBounds bounds = SpellScriptBounds(spellId);
    scriptVector.reserve(std::distance(bounds.first, bounds.second));

    for (SpellScriptsContainer::iterator itr = bounds.first; itr != bounds.second; ++itr)
    {
        SpellScriptLoader* tempScript = ScriptRegistry<SpellScriptLoader>::GetScriptById(itr->second);
        if (!tempScript)
            continue;

        scriptVector.emplace_back(tempScript, itr);
    }
}

SpellScriptLoader::SpellScriptLoader(char const* name)
    : ScriptObject(name)
{
    ScriptRegistry<SpellScriptLoader>::AddScript(this);
}

template class AC_GAME_API ScriptRegistry<SpellScriptLoader>;

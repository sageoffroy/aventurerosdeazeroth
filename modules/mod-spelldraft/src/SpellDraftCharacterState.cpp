#include "Configuration/Config.h"
#include "Database/DatabaseEnv.h"
#include "Log.h"
#include "Player.h"
#include "ScriptDefines/PlayerScript.h"

namespace
{
constexpr uint8 CLASS_ADVENTURER_ID = 10;

void ClearSpellDraftCharacterState(Player* player)
{
    if (!player || player->getClass() != CLASS_ADVENTURER_ID)
        return;

    uint32 guid = player->GetGUID().GetCounter();

    // SpellDraft persistence is keyed only by the low character GUID. During
    // repeated test-character creation/deletion AzerothCore can eventually
    // reuse a GUID that still has module-owned rows behind. Clear those rows
    // synchronously before the new Adventurer ever logs in, otherwise the Lua
    // login reconciliation can mistake the new character for the deleted one
    // and teach its old drafted abilities.
    CharacterDatabase.DirectExecute(
        "DELETE FROM spelldraft_drafted_spells WHERE player_guid = {}", guid);
    CharacterDatabase.DirectExecute(
        "DELETE FROM spelldraft_pending_offer WHERE player_guid = {}", guid);
    CharacterDatabase.DirectExecute(
        "DELETE FROM spelldraft_draft_resources WHERE player_guid = {}", guid);
    CharacterDatabase.DirectExecute(
        "DELETE FROM spelldraft_banned_spells WHERE player_guid = {}", guid);

    LOG_INFO(
        "module",
        "[SpellDraft] Cleared stale draft state for new Adventurer GUID {}.",
        guid);
}
}

class SpellDraftCharacterStatePlayerScript : public PlayerScript
{
public:
    SpellDraftCharacterStatePlayerScript()
        : PlayerScript("SpellDraftCharacterStatePlayerScript", { PLAYERHOOK_ON_CREATE })
    {
    }

    void OnPlayerCreate(Player* player) override
    {
        if (!sConfigMgr->GetOption<bool>("SpellDraft.Enable", true))
            return;

        ClearSpellDraftCharacterState(player);
    }
};

void AddSpellDraftCharacterStateScripts()
{
    new SpellDraftCharacterStatePlayerScript();
}

#include "Chat.h"
#include "Configuration/Config.h"
#include "Player.h"
#include "ScriptDefines/PlayerScript.h"
#include "WorldPacket.h"

#include <string>
#include <unordered_map>

namespace
{
constexpr uint32 COMBO_RESEND_INTERVAL_MS = 2000;
constexpr char COMBO_ADDON_PREFIX[] = "AventurerosCombo";

struct ComboSyncState
{
    uint8 points = 0;
    uint32 resendTimerMs = 0;
    bool initialized = false;
};

std::unordered_map<ObjectGuid::LowType, ComboSyncState> ComboSyncByPlayer;

bool IsAdventurer(Player const* player)
{
    return player && player->getClass() == CLASS_ADVENTURER;
}

uint8 GetDisplayedComboPoints(Player const* player)
{
    if (!player)
        return 0;

    ObjectGuid comboTarget = player->GetComboTargetGUID();
    if (comboTarget.IsEmpty() || comboTarget != player->GetTarget())
        return 0;

    return player->GetComboPoints();
}

void SendComboAddonState(Player* player, uint8 points)
{
    if (!player || !player->GetSession())
        return;

    std::string message = std::string(COMBO_ADDON_PREFIX) + "\t" + std::to_string(points);
    WorldPacket data;
    ChatHandler::BuildChatPacket(
        data,
        CHAT_MSG_WHISPER,
        LANG_ADDON,
        player,
        player,
        message
    );
    player->GetSession()->SendPacket(&data);
}

void SyncAdventurerComboPoints(Player* player, uint32 diff, bool force)
{
    if (!IsAdventurer(player) || !player->IsInWorld())
        return;

    ObjectGuid::LowType guid = player->GetGUID().GetCounter();
    ComboSyncState& state = ComboSyncByPlayer[guid];
    uint8 points = GetDisplayedComboPoints(player);

    if (state.resendTimerMs < COMBO_RESEND_INTERVAL_MS)
    {
        uint32 remaining = COMBO_RESEND_INTERVAL_MS - state.resendTimerMs;
        state.resendTimerMs += diff >= remaining ? remaining : diff;
    }

    bool periodicResend = state.resendTimerMs >= COMBO_RESEND_INTERVAL_MS;
    if (!force && state.initialized && state.points == points && !periodicResend)
        return;

    SendComboAddonState(player, points);
    state.points = points;
    state.resendTimerMs = 0;
    state.initialized = true;
}
}

class AdventurerComboPointsPlayerScript : public PlayerScript
{
public:
    AdventurerComboPointsPlayerScript() : PlayerScript(
        "AdventurerComboPointsPlayerScript",
        {
            PLAYERHOOK_ON_LOGIN,
            PLAYERHOOK_ON_LOGOUT,
            PLAYERHOOK_ON_UPDATE
        })
    {
    }

    void OnPlayerLogin(Player* player) override
    {
        if (!sConfigMgr->GetOption<bool>("SpellDraft.Enable", true) || !IsAdventurer(player))
            return;

        ComboSyncByPlayer.erase(player->GetGUID().GetCounter());
    }

    void OnPlayerLogout(Player* player) override
    {
        if (player)
            ComboSyncByPlayer.erase(player->GetGUID().GetCounter());
    }

    void OnPlayerUpdate(Player* player, uint32 diff) override
    {
        if (!sConfigMgr->GetOption<bool>("SpellDraft.Enable", true))
            return;

        SyncAdventurerComboPoints(player, diff, false);
    }
};

void AddAdventurerComboPointsScripts()
{
    new AdventurerComboPointsPlayerScript();
}

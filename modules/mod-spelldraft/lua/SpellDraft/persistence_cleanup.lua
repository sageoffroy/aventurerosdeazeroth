-- SpellDraft persistence lifecycle cleanup.
--
-- AzerothCore may reuse a deleted character's low GUID. SpellDraft persistence
-- is keyed by player_guid, so stale rows must not survive deletion or character
-- creation. Cleaning on both events makes the invariant self-healing for old
-- databases that already contain orphaned SpellDraft rows.

local PLAYER_EVENT_ON_CHARACTER_CREATE = 1
local PLAYER_EVENT_ON_CHARACTER_DELETE = 2

local TABLES = {
    "spelldraft_drafted_spells",
    "spelldraft_pending_offer",
    "spelldraft_draft_resources",
    "spelldraft_banned_spells",
}

local function CleanupSpellDraftGuid(guid)
    guid = tonumber(guid) or 0
    if guid <= 0 then
        return
    end

    for _, tableName in ipairs(TABLES) do
        CharDBExecute(string.format(
            "DELETE FROM `%s` WHERE `player_guid` = %u",
            tableName,
            guid
        ))
    end
end

local function OnCharacterCreate(_, player)
    if not player then
        return
    end

    CleanupSpellDraftGuid(player:GetGUIDLow())
end

local function OnCharacterDelete(_, guid)
    CleanupSpellDraftGuid(guid)
end

RegisterPlayerEvent(PLAYER_EVENT_ON_CHARACTER_CREATE, OnCharacterCreate)
RegisterPlayerEvent(PLAYER_EVENT_ON_CHARACTER_DELETE, OnCharacterDelete)

print("[Aventureros de Azeroth] SpellDraft GUID persistence cleanup loaded.")

-- Runtime reconciliation for package cards that changed semantics during audit.
-- Package cards are now real passive spellbook markers; do not remove them.

local PLAYER_EVENT_ON_LOGIN = 3
local PLAYER_EVENT_ON_LEARN_SPELL = 44

local MAESTRO_DE_PORTALES = 190001

local PACKAGE_PORTALS = {
    10059, -- Stormwind
    11416, -- Ironforge
    11417, -- Orgrimmar
    11418, -- Undercity
    11419, -- Darnassus
    11420, -- Thunder Bluff
    32266, -- Exodar
    32267, -- Silvermoon
    33691, -- Shattrath (Alliance)
    35717, -- Shattrath (Horde)
    49360, -- Theramore
    49361, -- Stonard
    53142, -- Dalaran
}

local ALLOWED_BY_TEAM = {
    [0] = { -- Alliance
        [10059] = true,
        [11416] = true,
        [11419] = true,
        [32266] = true,
        [33691] = true,
        [49360] = true,
        [53142] = true,
    },
    [1] = { -- Horde
        [11417] = true,
        [11418] = true,
        [11420] = true,
        [32267] = true,
        [35717] = true,
        [49361] = true,
        [53142] = true,
    },
}

local function ReconcileMaestroDePortales(player)
    if not player or not player:HasSpell(MAESTRO_DE_PORTALES) then
        return
    end

    local allowed = ALLOWED_BY_TEAM[player:GetTeam()] or {}
    for _, spellId in ipairs(PACKAGE_PORTALS) do
        if not allowed[spellId] and player:HasSpell(spellId) then
            player:RemoveSpell(spellId)
        end
    end
end

local function ScheduleReconcile(player, delay)
    if not player then
        return
    end

    local guid = player:GetGUIDLow()
    CreateLuaEvent(function()
        local current = GetPlayerByGUID(guid)
        if current and current:IsInWorld() then
            ReconcileMaestroDePortales(current)
        end
    end, delay, 1)
end

local function OnLearnSpell(_, player, spellId)
    if spellId == MAESTRO_DE_PORTALES then
        -- Let the SpellDraft recursive teach pass finish first.
        ScheduleReconcile(player, 500)
    end
end

local function OnLogin(_, player)
    -- Also migrates characters that learned both factions before this rule existed.
    ScheduleReconcile(player, 1500)
end

RegisterPlayerEvent(PLAYER_EVENT_ON_LEARN_SPELL, OnLearnSpell)
RegisterPlayerEvent(PLAYER_EVENT_ON_LOGIN, OnLogin)

-- Aventureros de Azeroth - puente Dungeon Master -> metaprogresion SpellDraft.
--
-- Dungeon Master ya persiste el total de pisos roguelike por personaje en
-- dm_roguelike_player_stats. Este script observa ese contador y convierte solo
-- el delta nuevo en Honor de cuenta. No toca el submodulo Dungeon Master y no
-- usa dm_player_stats porque ese contador tambien sube dentro del Roguelike.

SpellDraftDungeonRewards = SpellDraftDungeonRewards or {}
local M = SpellDraftDungeonRewards

local CLASS_ADVENTURER = 10

local function ConfigBoolean(name, default)
    local raw = GetConfigValue(name)
    if raw == nil or raw == "" then
        return default
    end
    if raw == true or raw == 1 or raw == "1" then
        return true
    end
    if raw == false or raw == 0 or raw == "0" then
        return false
    end

    local value = string.lower(tostring(raw))
    if value == "true" or value == "yes" or value == "on" then
        return true
    end
    if value == "false" or value == "no" or value == "off" then
        return false
    end
    return default
end

local function ConfigNumber(name, default, minimum, maximum, integer)
    local value = tonumber(GetConfigValue(name))
    if value == nil then
        value = default
    end
    if integer then
        value = math.floor(value)
    end
    if minimum ~= nil then
        value = math.max(minimum, value)
    end
    if maximum ~= nil then
        value = math.min(maximum, value)
    end
    return value
end

local ENABLED = ConfigBoolean(
    "SpellDraft.MetaProgression.DungeonMaster.Enable",
    true
)
local HONOR_PER_ROGUELIKE_FLOOR = ConfigNumber(
    "SpellDraft.MetaProgression.RoguelikeHonorPerFloor",
    10,
    0,
    10000,
    true
)
local POLL_SECONDS = ConfigNumber(
    "SpellDraft.MetaProgression.DungeonMaster.PollSeconds",
    5,
    2,
    60,
    true
)
local POLL_MS = POLL_SECONDS * 1000

-- La DB Execute de ALE es asincrona. Este cache es la autoridad durante la
-- sesion para impedir que dos polls cercanos paguen el mismo delta dos veces.
local checkpointCache = {}

local function IsBotPlayer(player)
    return player and player.IsBot ~= nil and player:IsBot()
end

local function IsAdventurer(player)
    return ENABLED
        and player
        and player:GetClass() == CLASS_ADVENTURER
        and not IsBotPlayer(player)
end

local function AccountId(player)
    if not player then
        return 0
    end
    return tonumber(player:GetAccountId()) or 0
end

local function ReadRoguelikeStats(guid)
    local query = CharDBQuery(
        "SELECT total_floors_cleared, highest_tier, total_runs "
        .. "FROM dm_roguelike_player_stats WHERE guid = " .. guid
    )

    if not query then
        return {
            floors = 0,
            highestTier = 0,
            runs = 0,
        }
    end

    return {
        floors = query:GetUInt32(0),
        highestTier = query:GetUInt32(1),
        runs = query:GetUInt32(2),
    }
end

local function SaveCheckpoint(guid, accountId, state)
    checkpointCache[guid] = {
        accountId = accountId,
        floors = state.floors or 0,
        highestTier = state.highestTier or 0,
        runs = state.runs or 0,
    }

    CharDBExecute(string.format(
        "INSERT INTO spelldraft_dm_reward_checkpoint "
        .. "(player_guid, account_id, roguelike_floors_credited, "
        .. "highest_tier_seen, roguelike_runs_seen) "
        .. "VALUES (%u, %u, %u, %u, %u) "
        .. "ON DUPLICATE KEY UPDATE account_id = VALUES(account_id), "
        .. "roguelike_floors_credited = VALUES(roguelike_floors_credited), "
        .. "highest_tier_seen = VALUES(highest_tier_seen), "
        .. "roguelike_runs_seen = VALUES(roguelike_runs_seen)",
        guid,
        accountId,
        state.floors or 0,
        state.highestTier or 0,
        state.runs or 0
    ))
end

local function LoadCheckpoint(player, stats, force)
    local guid = player:GetGUIDLow()
    if checkpointCache[guid] and not force then
        return checkpointCache[guid]
    end

    local query = CharDBQuery(
        "SELECT account_id, roguelike_floors_credited, highest_tier_seen, "
        .. "roguelike_runs_seen FROM spelldraft_dm_reward_checkpoint "
        .. "WHERE player_guid = " .. guid
    )

    if query then
        local state = {
            accountId = query:GetUInt32(0),
            floors = query:GetUInt32(1),
            highestTier = query:GetUInt32(2),
            runs = query:GetUInt32(3),
        }
        checkpointCache[guid] = state
        return state
    end

    -- Primera vez que instalamos el puente: tomamos los contadores actuales
    -- como baseline. No regalamos Honor retroactivo por runs de desarrollo que
    -- ocurrieron antes de que existiera esta economia.
    local baseline = {
        accountId = AccountId(player),
        floors = stats.floors,
        highestTier = stats.highestTier,
        runs = stats.runs,
    }
    SaveCheckpoint(guid, baseline.accountId, baseline)
    return checkpointCache[guid]
end

local function ResetCheckpointIfStatsWentBack(player, stats, checkpoint)
    if stats.floors >= checkpoint.floors
        and stats.runs >= checkpoint.runs then
        return false
    end

    -- Esto solo deberia pasar si el administrador resetea las estadisticas de
    -- Dungeon Master. Rebaselinar evita bloquear futuras recompensas.
    local state = {
        floors = stats.floors,
        highestTier = stats.highestTier,
        runs = stats.runs,
    }
    SaveCheckpoint(player:GetGUIDLow(), AccountId(player), state)
    return true
end

function M.CheckPlayer(player)
    if not IsAdventurer(player) then
        return 0
    end

    if not SpellDraftTalents
        or not SpellDraftTalents.GrantAccountHonor then
        return 0
    end

    local guid = player:GetGUIDLow()
    local accountId = AccountId(player)
    if accountId == 0 then
        return 0
    end

    local stats = ReadRoguelikeStats(guid)
    local checkpoint = LoadCheckpoint(player, stats, false)

    if ResetCheckpointIfStatsWentBack(player, stats, checkpoint) then
        return 0
    end

    local floorDelta = math.max(0, stats.floors - checkpoint.floors)
    local reward = floorDelta * HONOR_PER_ROGUELIKE_FLOOR

    if floorDelta > 0 and reward > 0 then
        local total = SpellDraftTalents.GrantAccountHonor(player, reward)

        player:SendBroadcastMessage(string.format(
            "[Metaprogresión] +%u Honor de cuenta por %u piso%s de Roguelike.",
            reward,
            floorDelta,
            floorDelta == 1 and "" or "s"
        ))
        player:SendBroadcastMessage(string.format(
            "[Metaprogresión] Honor de cuenta: %u",
            total
        ))
    end

    if SpellDraftTalents.RecordRoguelikeProgress
        and stats.highestTier > (checkpoint.highestTier or 0) then
        SpellDraftTalents.RecordRoguelikeProgress(
            player,
            stats.highestTier,
            false
        )
    end

    if floorDelta > 0
        or stats.highestTier ~= checkpoint.highestTier
        or stats.runs ~= checkpoint.runs
        or checkpoint.accountId ~= accountId then
        SaveCheckpoint(guid, accountId, stats)
    end

    return reward
end

local function ScheduleNext(guid, delayMs)
    CreateLuaEvent(function()
        local player = GetPlayerByGUID(guid)
        if not player or not player:IsInWorld() or not IsAdventurer(player) then
            return
        end

        M.CheckPlayer(player)
        ScheduleNext(guid, POLL_MS)
    end, delayMs, 1)
end

local function OnLogin(_, player)
    if not IsAdventurer(player) then
        return
    end

    local guid = player:GetGUIDLow()
    local stats = ReadRoguelikeStats(guid)
    LoadCheckpoint(player, stats, true)

    -- Damos tiempo a que termine el resto del login de SpellDraft antes del
    -- primer chequeo y luego mantenemos un poll liviano mientras siga online.
    ScheduleNext(guid, 2500)
end

local function OnLogout(_, player)
    if not player then
        return
    end
    checkpointCache[player:GetGUIDLow()] = nil
end

local function OnChat(_, player, msg)
    if not IsAdventurer(player) or not msg then
        return
    end

    if msg:gsub("^%s+", ""):gsub("%s+$", "") == "!talentos sincronizar" then
        local reward = M.CheckPlayer(player)
        player:SendBroadcastMessage(string.format(
            "[Metaprogresión] Sincronización completa. Honor acreditado: %u",
            reward
        ))
        return false
    end
end

RegisterPlayerEvent(3, OnLogin)   -- PLAYER_EVENT_ON_LOGIN
RegisterPlayerEvent(4, OnLogout)  -- PLAYER_EVENT_ON_LOGOUT
RegisterPlayerEvent(18, OnChat)   -- PLAYER_EVENT_ON_CHAT
RegisterPlayerEvent(19, OnChat)   -- PLAYER_EVENT_ON_WHISPER

print(string.format(
    "[Aventureros de Azeroth] Dungeon Master reward bridge loaded: "
    .. "%u Honor per roguelike floor, poll=%us.",
    HONOR_PER_ROGUELIKE_FLOOR,
    POLL_SECONDS
))

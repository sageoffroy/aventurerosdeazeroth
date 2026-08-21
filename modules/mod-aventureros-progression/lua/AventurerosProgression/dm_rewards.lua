-- Aventureros de Azeroth - adaptador de recompensas Dungeon Master.
--
-- Dungeon Master permanece completamente ajeno a la metaprogresion. Este
-- adaptador solo lee su estadistica persistida de pisos roguelike y convierte
-- deltas nuevos en Honor de cuenta a traves de AventurerosProgression.GrantHonor.

AventurerosDungeonRewards = AventurerosDungeonRewards or {}
local M = AventurerosDungeonRewards

if M.__loaded then
    return
end
M.__loaded = true

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
    "AventurerosProgression.DungeonMaster.Enable",
    true
)
local HONOR_PER_FLOOR = ConfigNumber(
    "AventurerosProgression.DungeonMaster.RoguelikeHonorPerFloor",
    10,
    0,
    10000,
    true
)
local POLL_SECONDS = ConfigNumber(
    "AventurerosProgression.DungeonMaster.PollSeconds",
    5,
    2,
    60,
    true
)
local POLL_MS = POLL_SECONDS * 1000

local scriptPath = debug.getinfo(1).source:sub(2)
local parentPath = scriptPath:match("(.+[/\\])") or ""
if not AventurerosProgression or not AventurerosProgression.GrantHonor then
    dofile(parentPath .. "account.lua")
end

-- Cache inmediato para que dos personajes de la misma cuenta, o dos polls muy
-- cercanos, no acrediten el mismo delta mientras CharacterDB procesa UPDATEs.
local checkpointCache = {}
local pollGeneration = {}
local accountBusy = {}

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

local function ReadDmStats(guid)
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
    local snapshot = {
        accountId = accountId,
        floors = math.max(0, math.floor(tonumber(state.floors) or 0)),
        highestTier = math.max(
            0,
            math.floor(tonumber(state.highestTier) or 0)
        ),
        runs = math.max(0, math.floor(tonumber(state.runs) or 0)),
    }

    checkpointCache[guid] = snapshot

    CharDBExecute(string.format(
        "INSERT INTO aventureros_dm_reward_checkpoint "
        .. "(player_guid, account_id, roguelike_floors_credited, "
        .. "highest_tier_seen, roguelike_runs_seen) "
        .. "VALUES (%u, %u, %u, %u, %u) "
        .. "ON DUPLICATE KEY UPDATE account_id = VALUES(account_id), "
        .. "roguelike_floors_credited = VALUES(roguelike_floors_credited), "
        .. "highest_tier_seen = VALUES(highest_tier_seen), "
        .. "roguelike_runs_seen = VALUES(roguelike_runs_seen)",
        guid,
        accountId,
        snapshot.floors,
        snapshot.highestTier,
        snapshot.runs
    ))
end

local function EnsureCurrentCharacterBaseline(player)
    local guid = player:GetGUIDLow()
    local accountId = AccountId(player)
    if accountId == 0 then
        return
    end

    local query = CharDBQuery(
        "SELECT account_id, roguelike_floors_credited, highest_tier_seen, "
        .. "roguelike_runs_seen FROM aventureros_dm_reward_checkpoint "
        .. "WHERE player_guid = " .. guid
    )

    if query then
        checkpointCache[guid] = {
            accountId = query:GetUInt32(0),
            floors = query:GetUInt32(1),
            highestTier = query:GetUInt32(2),
            runs = query:GetUInt32(3),
        }

        if checkpointCache[guid].accountId ~= accountId then
            checkpointCache[guid].accountId = accountId
            SaveCheckpoint(guid, accountId, checkpointCache[guid])
        end
        return
    end

    -- Primera vez que vemos este personaje: sus stats actuales son baseline.
    -- No otorgamos Honor retroactivo por runs anteriores a este sistema.
    SaveCheckpoint(guid, accountId, ReadDmStats(guid))
end

local function LoadAccountCheckpoints(accountId)
    local rows = {}
    local query = CharDBQuery(
        "SELECT player_guid, roguelike_floors_credited, highest_tier_seen, "
        .. "roguelike_runs_seen FROM aventureros_dm_reward_checkpoint "
        .. "WHERE account_id = " .. accountId
    )

    if not query then
        return rows
    end

    repeat
        local guid = query:GetUInt32(0)
        local persisted = {
            accountId = accountId,
            floors = query:GetUInt32(1),
            highestTier = query:GetUInt32(2),
            runs = query:GetUInt32(3),
        }

        -- La memoria gana a la DB si ya procesamos algo en esta sesion.
        local effective = checkpointCache[guid] or persisted
        checkpointCache[guid] = effective
        table.insert(rows, {
            guid = guid,
            checkpoint = effective,
        })
    until not query:NextRow()

    return rows
end

function M.CheckAccount(player)
    if not IsAdventurer(player) then
        return 0
    end

    local accountId = AccountId(player)
    if accountId == 0 or accountBusy[accountId] then
        return 0
    end

    accountBusy[accountId] = true

    local totalFloorDelta = 0
    local maxTierSeen = 0
    local totalRunDelta = 0

    local ok, err = pcall(function()
        EnsureCurrentCharacterBaseline(player)

        for _, row in ipairs(LoadAccountCheckpoints(accountId)) do
            local guid = row.guid
            local checkpoint = row.checkpoint
            local stats = ReadDmStats(guid)

            -- Si un administrador reseteo stats de DM, rebaselinamos. Nunca
            -- convertimos una bajada de contador en credito futuro artificial.
            if stats.floors < checkpoint.floors
                or stats.runs < checkpoint.runs then
                SaveCheckpoint(guid, accountId, stats)
            else
                local floorDelta = stats.floors - checkpoint.floors
                local runDelta = stats.runs - checkpoint.runs

                totalFloorDelta = totalFloorDelta + floorDelta
                totalRunDelta = totalRunDelta + runDelta
                maxTierSeen = math.max(maxTierSeen, stats.highestTier)

                if floorDelta > 0
                    or runDelta > 0
                    or stats.highestTier ~= checkpoint.highestTier then
                    SaveCheckpoint(guid, accountId, stats)
                end
            end
        end
    end)

    accountBusy[accountId] = nil

    if not ok then
        print(string.format(
            "[Aventureros de Azeroth] DM reward sync failed account=%u: %s",
            accountId,
            tostring(err)
        ))
        return 0
    end

    if maxTierSeen > 0 or totalRunDelta > 0 then
        AventurerosProgression.RecordRoguelikeProgress(
            player,
            maxTierSeen,
            totalRunDelta
        )
    end

    local reward = totalFloorDelta * HONOR_PER_FLOOR
    if reward > 0 then
        local total = AventurerosProgression.GrantHonor(player, reward)
        player:SendBroadcastMessage(string.format(
            "[Metaprogresión] +%u Honor de cuenta por %u piso%s de Roguelike.",
            reward,
            totalFloorDelta,
            totalFloorDelta == 1 and "" or "s"
        ))
        player:SendBroadcastMessage(string.format(
            "[Metaprogresión] Honor de cuenta: %u",
            total
        ))
    end

    return reward
end

local function StartPolling(player)
    if not IsAdventurer(player) then
        return
    end

    local guid = player:GetGUIDLow()
    local generation = (pollGeneration[guid] or 0) + 1
    pollGeneration[guid] = generation

    local function Tick()
        if pollGeneration[guid] ~= generation then
            return
        end

        local current = GetPlayerByGUID(guid)
        if not current
            or not current:IsInWorld()
            or not IsAdventurer(current) then
            return
        end

        M.CheckAccount(current)
        CreateLuaEvent(Tick, POLL_MS, 1)
    end

    CreateLuaEvent(Tick, 2500, 1)
end

local function OnLogin(_, player)
    if not IsAdventurer(player) then
        return
    end

    EnsureCurrentCharacterBaseline(player)
    StartPolling(player)
end

local function OnLogout(_, player)
    if not player then
        return
    end

    local guid = player:GetGUIDLow()
    pollGeneration[guid] = (pollGeneration[guid] or 0) + 1
end

local function OnChat(_, player, msg)
    if not IsAdventurer(player) or not msg then
        return
    end

    msg = msg:gsub("^%s+", ""):gsub("%s+$", "")
    if msg == "!talentos sincronizar" then
        local reward = M.CheckAccount(player)
        player:SendBroadcastMessage(string.format(
            "[Metaprogresión] Sincronización completa. Honor acreditado: %u",
            reward
        ))
        return false
    end
end

RegisterPlayerEvent(3, OnLogin)
RegisterPlayerEvent(4, OnLogout)
RegisterPlayerEvent(18, OnChat)
RegisterPlayerEvent(19, OnChat)

print(string.format(
    "[Aventureros de Azeroth] Dungeon Master reward adapter loaded: "
    .. "%u Honor/floor, poll=%us.",
    HONOR_PER_FLOOR,
    POLL_SECONDS
))
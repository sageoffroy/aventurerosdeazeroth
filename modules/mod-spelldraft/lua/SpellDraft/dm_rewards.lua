-- Aventureros de Azeroth - puente Dungeon Master -> metaprogresion SpellDraft.
--
-- Dungeon Master persiste el total de pisos roguelike por personaje en
-- dm_roguelike_player_stats. Este script convierte solamente los deltas nuevos
-- en Honor de cuenta. El checkpoint conserva player_guid -> account_id, por lo
-- que un superviviente nuevo puede cobrar progreso pendiente de uno anterior.
--
-- No usamos dm_player_stats: Dungeon Master tambien incrementa ese contador
-- durante el Roguelike y pagar ambos produciria recompensas dobles.

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

-- ALE encola CharDBExecute. Este cache es la autoridad de checkpoints durante
-- la sesion y evita acreditar dos veces el mismo delta antes de que la escritura
-- asincrona llegue a MySQL.
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

local function LoadCheckpointForGuid(guid, accountId, stats, force)
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

        -- GUIDs no deberian migrar entre cuentas, pero mantener el mapping
        -- actualizado hace el checkpoint autocorrectivo ante datos importados.
        if state.accountId ~= accountId then
            state.accountId = accountId
            SaveCheckpoint(guid, accountId, state)
        else
            checkpointCache[guid] = state
        end
        return checkpointCache[guid]
    end

    -- Primera aparicion despues de instalar el puente: los contadores actuales
    -- son baseline. No acreditamos runs historicas hechas durante desarrollo.
    local baseline = {
        accountId = accountId,
        floors = stats.floors,
        highestTier = stats.highestTier,
        runs = stats.runs,
    }
    SaveCheckpoint(guid, accountId, baseline)
    return checkpointCache[guid]
end

local function EnsureCharacterRegistered(player, force)
    local guid = player:GetGUIDLow()
    local accountId = AccountId(player)
    if accountId == 0 then
        return nil
    end

    local stats = ReadRoguelikeStats(guid)
    return LoadCheckpointForGuid(guid, accountId, stats, force)
end

local function ReadAccountRows(accountId)
    local rows = {}
    local query = CharDBQuery(string.format(
        "SELECT c.player_guid, c.roguelike_floors_credited, "
        .. "c.highest_tier_seen, c.roguelike_runs_seen, "
        .. "COALESCE(r.total_floors_cleared, 0), "
        .. "COALESCE(r.highest_tier, 0), COALESCE(r.total_runs, 0) "
        .. "FROM spelldraft_dm_reward_checkpoint c "
        .. "LEFT JOIN dm_roguelike_player_stats r ON r.guid = c.player_guid "
        .. "WHERE c.account_id = %u",
        accountId
    ))

    if not query then
        return rows
    end

    repeat
        local guid = query:GetUInt32(0)
        table.insert(rows, {
            guid = guid,
            dbCheckpoint = {
                accountId = accountId,
                floors = query:GetUInt32(1),
                highestTier = query:GetUInt32(2),
                runs = query:GetUInt32(3),
            },
            stats = {
                floors = query:GetUInt32(4),
                highestTier = query:GetUInt32(5),
                runs = query:GetUInt32(6),
            },
        })
    until not query:NextRow()

    return rows
end

local function ProcessRow(accountId, row)
    local checkpoint = checkpointCache[row.guid] or row.dbCheckpoint
    checkpointCache[row.guid] = checkpoint

    local stats = row.stats

    -- Si el administrador reseteo las estadisticas de Dungeon Master, hacemos
    -- un nuevo baseline. Nunca usamos un contador decreciente para generar Honor.
    if stats.floors < checkpoint.floors or stats.runs < checkpoint.runs then
        SaveCheckpoint(row.guid, accountId, stats)
        return 0, stats.highestTier
    end

    local floorDelta = math.max(0, stats.floors - checkpoint.floors)
    local changed = floorDelta > 0
        or stats.highestTier ~= checkpoint.highestTier
        or stats.runs ~= checkpoint.runs
        or checkpoint.accountId ~= accountId

    if changed then
        SaveCheckpoint(row.guid, accountId, stats)
    end

    return floorDelta, stats.highestTier
end

function M.CheckPlayer(player)
    if not IsAdventurer(player) then
        return 0
    end

    if not SpellDraftTalents
        or not SpellDraftTalents.GrantAccountHonor then
        return 0
    end

    local accountId = AccountId(player)
    if accountId == 0 then
        return 0
    end

    -- Registrar al superviviente actual antes de consultar la cuenta deja un
    -- mapping durable player_guid -> account_id incluso si luego ese personaje
    -- queda fuera o se elimina de la tabla characters.
    EnsureCharacterRegistered(player, false)

    local totalFloorDelta = 0
    local highestTier = 0

    for _, row in ipairs(ReadAccountRows(accountId)) do
        local floorDelta, rowTier = ProcessRow(accountId, row)
        totalFloorDelta = totalFloorDelta + floorDelta
        highestTier = math.max(highestTier, rowTier or 0)
    end

    local reward = totalFloorDelta * HONOR_PER_ROGUELIKE_FLOOR

    if reward > 0 then
        local total = SpellDraftTalents.GrantAccountHonor(player, reward)

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

    if SpellDraftTalents.RecordRoguelikeProgress and highestTier > 0 then
        SpellDraftTalents.RecordRoguelikeProgress(player, highestTier, false)
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

    EnsureCharacterRegistered(player, true)

    -- Damos tiempo a que termine el login de SpellDraft antes del primer poll.
    ScheduleNext(player:GetGUIDLow(), 2500)
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
RegisterPlayerEvent(18, OnChat)   -- PLAYER_EVENT_ON_CHAT
RegisterPlayerEvent(19, OnChat)   -- PLAYER_EVENT_ON_WHISPER

print(string.format(
    "[Aventureros de Azeroth] Dungeon Master reward bridge loaded: "
    .. "%u Honor per roguelike floor, poll=%us.",
    HONOR_PER_ROGUELIKE_FLOOR,
    POLL_SECONDS
))

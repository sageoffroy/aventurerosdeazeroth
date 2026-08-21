-- Aventureros de Azeroth - metaprogresion persistente por cuenta.
--
-- Fuente de verdad para:
--   * Honor de cuenta;
--   * familias de talento desbloqueadas;
--   * mejor tier y runs roguelike consolidadas.
--
-- Este archivo no sabe como funciona SpellDraft ni como funciona Dungeon Master.

AventurerosProgression = AventurerosProgression or {}
local M = AventurerosProgression

if M.__accountLoaded then
    return
end
M.__accountLoaded = true

local MAX_VISIBLE_HONOR = 75000
local CLASS_ADVENTURER = 10

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

local STARTING_HONOR = ConfigNumber(
    "AventurerosProgression.StartingHonor",
    0,
    0,
    MAX_VISIBLE_HONOR,
    true
)

local scriptPath = debug.getinfo(1).source:sub(2)
local parentPath = scriptPath:match("(.+[/\\])") or ""
if not AventurerosProgressionCatalog then
    dofile(parentPath .. "catalog.lua")
end

local CATALOG = AventurerosProgressionCatalog or {}
local CATALOG_BY_ID = {}
for _, entry in ipairs(CATALOG) do
    CATALOG_BY_ID[entry.id] = entry
end

local progressCache = {}
local unlockCache = {}

local function IsBotPlayer(player)
    return player and player.IsBot ~= nil and player:IsBot()
end

local function IsAdventurer(player)
    return player
        and player:GetClass() == CLASS_ADVENTURER
        and not IsBotPlayer(player)
end

local function AccountId(player)
    if not player then
        return 0
    end
    return tonumber(player:GetAccountId()) or 0
end

local function LoadProgress(player, force)
    local accountId = AccountId(player)
    if accountId == 0 then
        return nil
    end

    if progressCache[accountId] and not force then
        return progressCache[accountId]
    end

    local state = {
        honor = STARTING_HONOR,
        highestTier = 0,
        runsCompleted = 0,
    }

    local query = CharDBQuery(
        "SELECT honor, highest_roguelike_tier, runs_completed "
        .. "FROM aventureros_account_progress WHERE account_id = " .. accountId
    )

    if query then
        state.honor = math.min(MAX_VISIBLE_HONOR, query:GetUInt32(0))
        state.highestTier = query:GetUInt32(1)
        state.runsCompleted = query:GetUInt32(2)
    else
        -- Migracion conservadora: si el primer personaje ya tenia Honor visible,
        -- lo tomamos como saldo inicial de la cuenta.
        local legacyHonor = math.max(0, player:GetHonorPoints() or 0)
        state.honor = math.min(
            MAX_VISIBLE_HONOR,
            math.max(STARTING_HONOR, legacyHonor)
        )

        CharDBExecute(string.format(
            "INSERT IGNORE INTO aventureros_account_progress "
            .. "(account_id, honor, highest_roguelike_tier, runs_completed) "
            .. "VALUES (%u, %u, 0, 0)",
            accountId,
            state.honor
        ))
    end

    progressCache[accountId] = state
    return state
end

local function SaveProgress(player, state)
    local accountId = AccountId(player)
    if accountId == 0 or not state then
        return
    end

    state.honor = math.min(
        MAX_VISIBLE_HONOR,
        math.max(0, math.floor(tonumber(state.honor) or 0))
    )
    state.highestTier = math.max(0, math.floor(tonumber(state.highestTier) or 0))
    state.runsCompleted = math.max(
        0,
        math.floor(tonumber(state.runsCompleted) or 0)
    )

    progressCache[accountId] = state

    CharDBExecute(string.format(
        "INSERT INTO aventureros_account_progress "
        .. "(account_id, honor, highest_roguelike_tier, runs_completed) "
        .. "VALUES (%u, %u, %u, %u) "
        .. "ON DUPLICATE KEY UPDATE honor = VALUES(honor), "
        .. "highest_roguelike_tier = VALUES(highest_roguelike_tier), "
        .. "runs_completed = VALUES(runs_completed)",
        accountId,
        state.honor,
        state.highestTier,
        state.runsCompleted
    ))
end

local function LoadUnlocks(player, force)
    local accountId = AccountId(player)
    if accountId == 0 then
        return {}
    end

    if unlockCache[accountId] and not force then
        return unlockCache[accountId]
    end

    local unlocked = {}
    for _, entry in ipairs(CATALOG) do
        if entry.starter then
            unlocked[entry.id] = true
        end
    end

    local query = CharDBQuery(
        "SELECT talent_id FROM aventureros_account_talents WHERE account_id = "
        .. accountId
    )
    if query then
        repeat
            local talentId = query:GetString(0)
            if talentId and CATALOG_BY_ID[talentId] then
                unlocked[talentId] = true
            end
        until not query:NextRow()
    end

    unlockCache[accountId] = unlocked
    return unlocked
end

function M.GetAccountId(player)
    return AccountId(player)
end

function M.GetHonor(player)
    local state = LoadProgress(player, false)
    return state and state.honor or 0
end

function M.SyncVisibleHonor(player)
    local state = LoadProgress(player, false)
    if not state then
        return
    end

    if player:GetHonorPoints() ~= state.honor then
        player:SetHonorPoints(state.honor)
    end
end

function M.GrantHonor(player, amount)
    amount = math.max(0, math.floor(tonumber(amount) or 0))
    local state = LoadProgress(player, false)
    if not state then
        return 0
    end

    state.honor = math.min(MAX_VISIBLE_HONOR, state.honor + amount)
    SaveProgress(player, state)
    M.SyncVisibleHonor(player)
    return state.honor
end

function M.SpendHonor(player, amount)
    amount = math.max(0, math.floor(tonumber(amount) or 0))
    local state = LoadProgress(player, false)
    if not state or state.honor < amount then
        return false
    end

    state.honor = state.honor - amount
    SaveProgress(player, state)
    M.SyncVisibleHonor(player)
    return true
end

function M.IsTalentUnlocked(player, talentId)
    if not player or not talentId then
        return false
    end

    local unlocked = LoadUnlocks(player, false)
    return unlocked[talentId] == true
end

function M.UnlockTalentWithHonor(player, talentId)
    local entry = CATALOG_BY_ID[talentId]
    if not entry then
        return false, "unknown"
    end

    local unlocked = LoadUnlocks(player, false)
    if unlocked[talentId] then
        return false, "owned"
    end

    local cost = math.max(0, math.floor(tonumber(entry.cost) or 0))
    if not M.SpendHonor(player, cost) then
        return false, "honor"
    end

    local accountId = AccountId(player)
    CharDBExecute(string.format(
        "INSERT IGNORE INTO aventureros_account_talents (account_id, talent_id) "
        .. "VALUES (%u, '%s')",
        accountId,
        talentId
    ))

    unlocked[talentId] = true
    unlockCache[accountId] = unlocked
    return true, "ok"
end

function M.RecordRoguelikeProgress(player, highestTier, completedRunsDelta)
    local state = LoadProgress(player, false)
    if not state then
        return
    end

    highestTier = math.max(0, math.floor(tonumber(highestTier) or 0))
    completedRunsDelta = math.max(
        0,
        math.floor(tonumber(completedRunsDelta) or 0)
    )

    state.highestTier = math.max(state.highestTier or 0, highestTier)
    state.runsCompleted = (state.runsCompleted or 0) + completedRunsDelta
    SaveProgress(player, state)
end

function M.GetTalentCatalog()
    return CATALOG
end

local function ShowShop(player)
    local unlocked = LoadUnlocks(player, false)

    player:SendBroadcastMessage(string.format(
        "[Metaprogresión] Honor de cuenta: %u",
        M.GetHonor(player)
    ))
    player:SendBroadcastMessage("[Metaprogresión] Familias de talento:")

    for _, entry in ipairs(CATALOG) do
        local status
        if entry.starter then
            status = "BÁSICO"
        elseif unlocked[entry.id] then
            status = "DESBLOQUEADO"
        else
            status = tostring(entry.cost or 0) .. " Honor"
        end

        player:SendBroadcastMessage(string.format(
            " - %s [%s] id=%s",
            entry.label,
            status,
            entry.id
        ))
    end

    player:SendBroadcastMessage(
        "[Metaprogresión] Comprar: !talentos comprar <id>"
    )
end

local function HandleChat(_, player, msg)
    if not IsAdventurer(player) or not msg then
        return
    end

    msg = msg:gsub("^%s+", ""):gsub("%s+$", "")

    if msg == "!talentos" then
        ShowShop(player)
        return false
    end

    local talentId = msg:match("^!talentos%s+comprar%s+([%w_%-]+)$")
    if talentId then
        local ok, reason = M.UnlockTalentWithHonor(player, talentId)
        if ok then
            local entry = CATALOG_BY_ID[talentId]
            player:SendBroadcastMessage(string.format(
                "[Metaprogresión] %s quedó desbloqueado para toda la cuenta.",
                entry.label
            ))
        elseif reason == "owned" then
            player:SendBroadcastMessage(
                "[Metaprogresión] Esa familia ya está desbloqueada."
            )
        elseif reason == "honor" then
            player:SendBroadcastMessage(
                "[Metaprogresión] No tenés Honor de cuenta suficiente."
            )
        else
            player:SendBroadcastMessage(
                "[Metaprogresión] No existe esa familia."
            )
        end
        ShowShop(player)
        return false
    end

    -- Comando temporal de test. Se elimina cuando el circuito completo quede
    -- validado desde Dungeon Master.
    local grant = msg:match("^!talentos%s+darhonor%s+(%d+)$")
    if grant and player:IsGM() then
        local total = M.GrantHonor(player, tonumber(grant))
        player:SendBroadcastMessage(string.format(
            "[Metaprogresión] TEST: Honor de cuenta = %u",
            total
        ))
        return false
    end
end

local function OnLogin(_, player)
    if not IsAdventurer(player) then
        return
    end

    LoadProgress(player, true)
    LoadUnlocks(player, true)
    M.SyncVisibleHonor(player)
end

RegisterPlayerEvent(3, OnLogin)
RegisterPlayerEvent(18, HandleChat)
RegisterPlayerEvent(19, HandleChat)

print(string.format(
    "[Aventureros de Azeroth] Account progression loaded: %u talent families.",
    #CATALOG
))

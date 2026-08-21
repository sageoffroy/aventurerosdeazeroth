-- Aventureros de Azeroth - talentos por vida + metaprogresión por cuenta.
--
-- Responsabilidades de este archivo:
--   * una elección de talento en 10, 12, 14... 80;
--   * talentos elegidos pertenecen al superviviente actual (player_guid);
--   * Honor y familias desbloqueadas pertenecen a la cuenta (account_id);
--   * las ofertas usan el protocolo existente SpellChoiceIsTalent = 1;
--   * el draft normal de habilidades sigue siendo autoridad de sus propias cartas.

SpellDraftTalents = SpellDraftTalents or {}
local M = SpellDraftTalents

local CLASS_ADVENTURER = 10
local MAX_PERSISTED_OFFER_SIZE = 5
local MAX_VISIBLE_HONOR = 75000

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

local ENABLED = ConfigBoolean("SpellDraft.Talents.Enable", true)
local FIRST_TALENT_LEVEL = ConfigNumber(
    "SpellDraft.Talents.FirstLevel", 10, 1, 80, true
)
local LEVELS_PER_TALENT = ConfigNumber(
    "SpellDraft.Talents.LevelsPerPick", 2, 1, 80, true
)
local MAX_TALENT_PICKS = ConfigNumber(
    "SpellDraft.Talents.MaxPicks", 36, 0, 200, true
)
local TALENT_OFFER_SIZE = ConfigNumber(
    "SpellDraft.Talents.OfferSize", 3, 1, MAX_PERSISTED_OFFER_SIZE, true
)
local STARTING_ACCOUNT_HONOR = ConfigNumber(
    "SpellDraft.Talents.StartingAccountHonor", 0, 0, MAX_VISIBLE_HONOR, true
)

-- Replicamos solamente la fórmula de cantidad esperada del draft normal. Esto
-- permite esperar a que el jugador resuelva la habilidad de nivel 10/20/etc.
-- antes de abrir Talento (N), sin acoplar este módulo a locales de draft_core.
local STARTING_DRAFTS = ConfigNumber("SpellDraft.StartingDrafts", 3, 0, 100, true)
local FIRST_ADDITIONAL_DRAFT_LEVEL = ConfigNumber(
    "SpellDraft.FirstAdditionalDraftLevel", 5, 2, 80, true
)
local LEVELS_PER_DRAFT = ConfigNumber("SpellDraft.LevelsPerDraft", 5, 1, 80, true)
local DRAFTS_PER_MILESTONE = ConfigNumber(
    "SpellDraft.DraftsPerMilestone", 1, 1, 20, true
)
local MAX_DRAFTED_SPELLS = ConfigNumber(
    "SpellDraft.MaxDraftedSpells", 15, 0, 500, true
)

local scriptPath = debug.getinfo(1).source:sub(2)
local parentPath = scriptPath:match("(.+[/\\])") or ""
if not SpellDraftTalentCatalog then
    dofile(parentPath .. "talent_catalog.lua")
end

local TALENT_FAMILIES = SpellDraftTalentCatalog or {}
local FAMILY_BY_ID = {}
local SPELL_TO_RANK = {}

for _, family in ipairs(TALENT_FAMILIES) do
    FAMILY_BY_ID[family.id] = family
    for rank, spellId in ipairs(family.ranks or {}) do
        SPELL_TO_RANK[spellId] = {
            family = family,
            rank = rank,
        }
    end
end

local characterStateCache = {}
local pendingOfferCache = {}
local pendingOfferLoaded = {}
local accountProgressCache = {}
local accountUnlockCache = {}

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

local function ExpectedNormalDrafts(player)
    local level = math.max(1, player:GetLevel() or 1)
    local expected = STARTING_DRAFTS

    if level >= FIRST_ADDITIONAL_DRAFT_LEVEL then
        local milestones = math.floor(
            (level - FIRST_ADDITIONAL_DRAFT_LEVEL) / LEVELS_PER_DRAFT
        ) + 1
        expected = expected + milestones * DRAFTS_PER_MILESTONE
    end

    if MAX_DRAFTED_SPELLS > 0 then
        expected = math.min(expected, MAX_DRAFTED_SPELLS)
    end
    return expected
end

local function NormalDraftCount(player)
    local query = CharDBQuery(
        "SELECT COUNT(*) FROM spelldraft_drafted_spells WHERE player_guid = "
        .. player:GetGUIDLow()
    )
    if not query then
        return 0
    end
    return query:GetUInt32(0)
end

local function NormalDraftsRemaining(player)
    return math.max(0, ExpectedNormalDrafts(player) - NormalDraftCount(player))
end

local function ExpectedTalentPicks(player)
    if not IsAdventurer(player) then
        return 0
    end

    local level = math.max(1, player:GetLevel() or 1)
    if level < FIRST_TALENT_LEVEL then
        return 0
    end

    local expected = math.floor(
        (level - FIRST_TALENT_LEVEL) / LEVELS_PER_TALENT
    ) + 1

    if MAX_TALENT_PICKS > 0 then
        expected = math.min(expected, MAX_TALENT_PICKS)
    end
    return expected
end

local function LoadCharacterState(player, force)
    local guid = player:GetGUIDLow()
    if characterStateCache[guid] and not force then
        return characterStateCache[guid]
    end

    local state = {
        ranks = {},
        count = 0,
    }

    local query = CharDBQuery(
        "SELECT talent_id, talent_rank FROM spelldraft_character_talents "
        .. "WHERE player_guid = " .. guid .. " ORDER BY talent_index"
    )

    if query then
        repeat
            local talentId = query:GetString(0)
            local rank = query:GetUInt32(1)
            if talentId and talentId ~= "" and rank > 0 then
                state.ranks[talentId] = math.max(
                    state.ranks[talentId] or 0,
                    rank
                )
                state.count = state.count + 1
            end
        until not query:NextRow()
    end

    characterStateCache[guid] = state
    return state
end

local function TalentPicksRemaining(player)
    local state = LoadCharacterState(player, false)
    return math.max(0, ExpectedTalentPicks(player) - state.count)
end

local function LoadAccountProgress(player, force)
    local accountId = AccountId(player)
    if accountId == 0 then
        return nil
    end

    if accountProgressCache[accountId] and not force then
        return accountProgressCache[accountId]
    end

    local state = {
        honor = STARTING_ACCOUNT_HONOR,
        highestTier = 0,
        runsCompleted = 0,
    }

    local query = CharDBQuery(
        "SELECT honor, highest_roguelike_tier, runs_completed "
        .. "FROM spelldraft_account_progress WHERE account_id = " .. accountId
    )

    if query then
        state.honor = math.min(MAX_VISIBLE_HONOR, query:GetUInt32(0))
        state.highestTier = query:GetUInt32(1)
        state.runsCompleted = query:GetUInt32(2)
    else
        -- Migración inicial conservadora: si el primer personaje que entra ya
        -- tenía Honor, lo usamos como saldo inicial de la cuenta.
        local legacyHonor = math.max(0, player:GetHonorPoints() or 0)
        state.honor = math.min(
            MAX_VISIBLE_HONOR,
            math.max(STARTING_ACCOUNT_HONOR, legacyHonor)
        )

        CharDBExecute(string.format(
            "INSERT IGNORE INTO spelldraft_account_progress "
            .. "(account_id, honor, highest_roguelike_tier, runs_completed) "
            .. "VALUES (%u, %u, 0, 0)",
            accountId,
            state.honor
        ))
    end

    accountProgressCache[accountId] = state
    return state
end

local function SaveAccountProgress(player, state)
    local accountId = AccountId(player)
    if accountId == 0 or not state then
        return
    end

    state.honor = math.min(MAX_VISIBLE_HONOR, math.max(0, state.honor or 0))
    accountProgressCache[accountId] = state

    CharDBExecute(string.format(
        "INSERT INTO spelldraft_account_progress "
        .. "(account_id, honor, highest_roguelike_tier, runs_completed) "
        .. "VALUES (%u, %u, %u, %u) "
        .. "ON DUPLICATE KEY UPDATE honor = VALUES(honor), "
        .. "highest_roguelike_tier = VALUES(highest_roguelike_tier), "
        .. "runs_completed = VALUES(runs_completed)",
        accountId,
        state.honor,
        state.highestTier or 0,
        state.runsCompleted or 0
    ))
end

local function SyncVisibleHonor(player)
    local state = LoadAccountProgress(player, false)
    if not state then
        return
    end

    if player:GetHonorPoints() ~= state.honor then
        player:SetHonorPoints(state.honor)
    end
end

local function LoadAccountUnlocks(player, force)
    local accountId = AccountId(player)
    if accountId == 0 then
        return {}
    end

    if accountUnlockCache[accountId] and not force then
        return accountUnlockCache[accountId]
    end

    local unlocked = {}
    for _, family in ipairs(TALENT_FAMILIES) do
        if family.starter then
            unlocked[family.id] = true
        end
    end

    local query = CharDBQuery(
        "SELECT talent_id FROM spelldraft_account_talents WHERE account_id = "
        .. accountId
    )
    if query then
        repeat
            local talentId = query:GetString(0)
            if talentId and FAMILY_BY_ID[talentId] then
                unlocked[talentId] = true
            end
        until not query:NextRow()
    end

    accountUnlockCache[accountId] = unlocked
    return unlocked
end

local function ClearPendingOffer(guid)
    pendingOfferCache[guid] = nil
    pendingOfferLoaded[guid] = true
    CharDBExecute(
        "DELETE FROM spelldraft_pending_talent_offer WHERE player_guid = " .. guid
    )
end

local function LoadPendingOffer(player, force)
    local guid = player:GetGUIDLow()
    if pendingOfferLoaded[guid] and not force then
        return pendingOfferCache[guid]
    end

    pendingOfferLoaded[guid] = true
    pendingOfferCache[guid] = nil

    local query = CharDBQuery(
        "SELECT offer_1, offer_2, offer_3, offer_4, offer_5, offer_size "
        .. "FROM spelldraft_pending_talent_offer WHERE player_guid = " .. guid
    )
    if not query then
        return nil
    end

    if query:GetUInt32(5) ~= TALENT_OFFER_SIZE then
        ClearPendingOffer(guid)
        return nil
    end

    local offer = {}
    for column = 0, MAX_PERSISTED_OFFER_SIZE - 1 do
        local spellId = query:GetUInt32(column)
        if spellId and spellId > 0 then
            table.insert(offer, spellId)
        end
    end

    if #offer == 0 then
        ClearPendingOffer(guid)
        return nil
    end

    pendingOfferCache[guid] = offer
    return offer
end

local function SavePendingOffer(player, offer)
    local guid = player:GetGUIDLow()
    local values = {0, 0, 0, 0, 0}

    for index, spellId in ipairs(offer) do
        if index <= MAX_PERSISTED_OFFER_SIZE then
            values[index] = spellId
        end
    end

    pendingOfferCache[guid] = offer
    pendingOfferLoaded[guid] = true

    CharDBExecute(string.format(
        "INSERT INTO spelldraft_pending_talent_offer "
        .. "(player_guid, offer_1, offer_2, offer_3, offer_4, offer_5, "
        .. "offer_size, offered_level) "
        .. "VALUES (%u, %u, %u, %u, %u, %u, %u, %u) "
        .. "ON DUPLICATE KEY UPDATE offer_1 = VALUES(offer_1), "
        .. "offer_2 = VALUES(offer_2), offer_3 = VALUES(offer_3), "
        .. "offer_4 = VALUES(offer_4), offer_5 = VALUES(offer_5), "
        .. "offer_size = VALUES(offer_size), offered_level = VALUES(offered_level)",
        guid,
        values[1],
        values[2],
        values[3],
        values[4],
        values[5],
        TALENT_OFFER_SIZE,
        player:GetLevel() or 1
    ))
end

local function NextCandidateForFamily(family, state, unlocked)
    if not unlocked[family.id] then
        return nil
    end

    local nextRank = (state.ranks[family.id] or 0) + 1
    local spellId = family.ranks and family.ranks[nextRank]
    if not spellId then
        return nil
    end

    return {
        family = family,
        rank = nextRank,
        spellId = spellId,
    }
end

local function BuildCandidates(player)
    local state = LoadCharacterState(player, false)
    local unlocked = LoadAccountUnlocks(player, false)
    local candidates = {}

    for _, family in ipairs(TALENT_FAMILIES) do
        local candidate = NextCandidateForFamily(family, state, unlocked)
        if candidate then
            table.insert(candidates, candidate)
        end
    end
    return candidates
end

local function Shuffle(values)
    for index = #values, 2, -1 do
        local other = math.random(index)
        values[index], values[other] = values[other], values[index]
    end
end

local function GenerateOffer(player)
    local candidates = BuildCandidates(player)
    Shuffle(candidates)

    local offer = {}
    local take = math.min(TALENT_OFFER_SIZE, #candidates)
    for index = 1, take do
        table.insert(offer, candidates[index].spellId)
    end
    return offer
end

local function OfferContains(offer, spellId)
    for _, offeredId in ipairs(offer or {}) do
        if offeredId == spellId then
            return true
        end
    end
    return false
end

local function OfferIsCurrent(player, offer)
    if not offer or #offer == 0 then
        return false
    end

    local state = LoadCharacterState(player, false)
    local unlocked = LoadAccountUnlocks(player, false)

    for _, spellId in ipairs(offer) do
        local mapped = SPELL_TO_RANK[spellId]
        if not mapped or not unlocked[mapped.family.id] then
            return false
        end

        local expectedRank = (state.ranks[mapped.family.id] or 0) + 1
        if mapped.rank ~= expectedRank then
            return false
        end
    end
    return true
end

local function SendTalentUiState(player)
    player:SendAddonMessage(
        "SpellChoiceDrafts",
        tostring(TalentPicksRemaining(player)),
        0,
        player
    )
    player:SendAddonMessage("SpellChoiceRerolls", "0", 0, player)
    player:SendAddonMessage("SpellChoiceBansLeft", "0", 0, player)
    player:SendAddonMessage("SpellChoiceProtections", "0", 0, player)
    player:SendAddonMessage("SpellChoiceProtectionEnabled", "0", 0, player)
end

local function SendOffer(player, offer)
    local zeroes = {}
    for _ = 1, #offer do
        table.insert(zeroes, "0")
    end

    SendTalentUiState(player)
    player:SendAddonMessage("SpellChoiceIsTalent", "1", 0, player)
    player:SendAddonMessage("SpellChoice", table.concat(offer, ","), 0, player)
    player:SendAddonMessage(
        "SpellChoiceRarities",
        table.concat(zeroes, ","),
        0,
        player
    )
    player:SendAddonMessage(
        "SpellChoiceClasses",
        table.concat(zeroes, ","),
        0,
        player
    )
end

local function LearnCurrentRank(player, family, rank)
    if not family or rank <= 0 then
        return
    end

    -- Dejamos solamente el rango elegido. Así los pasivos 1/5, 2/5... no se
    -- acumulan por error si AzerothCore no trata esa familia como rank chain.
    for index, spellId in ipairs(family.ranks or {}) do
        if index ~= rank and player:HasSpell(spellId) then
            player:RemoveSpell(spellId)
        end
    end

    local spellId = family.ranks and family.ranks[rank]
    if spellId and not player:HasSpell(spellId) then
        player:LearnSpell(spellId)
    end
end

local function RestoreTalents(player)
    local state = LoadCharacterState(player, false)
    for talentId, rank in pairs(state.ranks) do
        local family = FAMILY_BY_ID[talentId]
        if family then
            LearnCurrentRank(player, family, rank)
        end
    end
end

function M.HasPendingOffer(player)
    if not IsAdventurer(player) then
        return false
    end
    local offer = LoadPendingOffer(player, false)
    return offer ~= nil and #offer > 0
end

function M.EnsureAndSendOffer(player)
    if not IsAdventurer(player) then
        return false
    end

    if NormalDraftsRemaining(player) > 0 then
        return false
    end

    if TalentPicksRemaining(player) <= 0 then
        ClearPendingOffer(player:GetGUIDLow())
        return false
    end

    local offer = LoadPendingOffer(player, false)
    if not OfferIsCurrent(player, offer) then
        ClearPendingOffer(player:GetGUIDLow())
        offer = GenerateOffer(player)

        if #offer == 0 then
            player:SendBroadcastMessage(
                "[Talentos] Tu pool desbloqueado no tiene más rangos disponibles."
            )
            player:SendBroadcastMessage(
                "[Talentos] Usá !talentos para ver nuevas familias desbloqueables."
            )
            player:SendAddonMessage("SpellChoiceClose", "", 0, player)
            return false
        end

        SavePendingOffer(player, offer)
    end

    SendOffer(player, offer)
    return true
end

function M.AcceptPick(player, spellId)
    if not IsAdventurer(player) then
        return false
    end

    local guid = player:GetGUIDLow()
    local offer = LoadPendingOffer(player, false)
    if not offer or #offer == 0 then
        return false
    end

    if not OfferContains(offer, spellId) then
        player:SendBroadcastMessage(
            "[Talentos] Esa opción no pertenece a tu oferta actual."
        )
        M.EnsureAndSendOffer(player)
        return true
    end

    if TalentPicksRemaining(player) <= 0 then
        ClearPendingOffer(guid)
        player:SendAddonMessage("SpellChoiceClose", "", 0, player)
        return true
    end

    local mapped = SPELL_TO_RANK[spellId]
    local state = LoadCharacterState(player, false)
    local unlocked = LoadAccountUnlocks(player, false)

    if not mapped or not unlocked[mapped.family.id] then
        ClearPendingOffer(guid)
        M.EnsureAndSendOffer(player)
        return true
    end

    local currentRank = state.ranks[mapped.family.id] or 0
    if mapped.rank ~= currentRank + 1 then
        ClearPendingOffer(guid)
        M.EnsureAndSendOffer(player)
        return true
    end

    local talentIndex = state.count + 1
    local level = player:GetLevel() or 1

    CharDBExecute(string.format(
        "INSERT IGNORE INTO spelldraft_character_talents "
        .. "(player_guid, talent_id, talent_rank, talent_spell_id, "
        .. "talent_index, picked_level) "
        .. "VALUES (%u, '%s', %u, %u, %u, %u)",
        guid,
        mapped.family.id,
        mapped.rank,
        spellId,
        talentIndex,
        level
    ))

    state.ranks[mapped.family.id] = mapped.rank
    state.count = talentIndex
    characterStateCache[guid] = state

    LearnCurrentRank(player, mapped.family, mapped.rank)
    player:CastSpell(player, 24312, true)
    player:RemoveAura(24312)

    ClearPendingOffer(guid)

    if TalentPicksRemaining(player) > 0 then
        M.EnsureAndSendOffer(player)
    else
        player:SendAddonMessage("SpellChoiceClose", "", 0, player)
    end
    return true
end

function M.GetAccountHonor(player)
    local state = LoadAccountProgress(player, false)
    return state and state.honor or 0
end

function M.GrantAccountHonor(player, amount)
    if not player then
        return 0
    end

    amount = math.max(0, math.floor(tonumber(amount) or 0))
    local state = LoadAccountProgress(player, false)
    if not state then
        return 0
    end

    state.honor = math.min(MAX_VISIBLE_HONOR, state.honor + amount)
    SaveAccountProgress(player, state)
    SyncVisibleHonor(player)
    return state.honor
end

function M.SpendAccountHonor(player, amount)
    amount = math.max(0, math.floor(tonumber(amount) or 0))
    local state = LoadAccountProgress(player, false)
    if not state or state.honor < amount then
        return false
    end

    state.honor = state.honor - amount
    SaveAccountProgress(player, state)
    SyncVisibleHonor(player)
    return true
end

function M.RecordRoguelikeProgress(player, tier, completed)
    local state = LoadAccountProgress(player, false)
    if not state then
        return
    end

    tier = math.max(0, math.floor(tonumber(tier) or 0))
    state.highestTier = math.max(state.highestTier or 0, tier)
    if completed then
        state.runsCompleted = (state.runsCompleted or 0) + 1
    end
    SaveAccountProgress(player, state)
end

function M.UnlockFamilyWithHonor(player, talentId)
    local family = FAMILY_BY_ID[talentId]
    if not family then
        return false, "unknown"
    end

    local unlocked = LoadAccountUnlocks(player, false)
    if unlocked[family.id] then
        return false, "owned"
    end

    if not M.SpendAccountHonor(player, family.cost or 0) then
        return false, "honor"
    end

    local accountId = AccountId(player)
    CharDBExecute(string.format(
        "INSERT IGNORE INTO spelldraft_account_talents (account_id, talent_id) "
        .. "VALUES (%u, '%s')",
        accountId,
        family.id
    ))

    unlocked[family.id] = true
    accountUnlockCache[accountId] = unlocked

    -- La compra amplía el pool. Si había una oferta sin resolver la regeneramos
    -- para que la nueva familia pueda aparecer inmediatamente.
    ClearPendingOffer(player:GetGUIDLow())
    return true, "ok"
end

local function ShowTalentShop(player)
    local honor = M.GetAccountHonor(player)
    local unlocked = LoadAccountUnlocks(player, false)

    player:SendBroadcastMessage(string.format(
        "[Talentos] Honor de cuenta: %u",
        honor
    ))
    player:SendBroadcastMessage("[Talentos] Familias disponibles:")

    for _, family in ipairs(TALENT_FAMILIES) do
        local status
        if family.starter then
            status = "BÁSICO"
        elseif unlocked[family.id] then
            status = "DESBLOQUEADO"
        else
            status = tostring(family.cost or 0) .. " Honor"
        end

        player:SendBroadcastMessage(string.format(
            " - %s [%s] id=%s",
            family.label,
            status,
            family.id
        ))
    end

    player:SendBroadcastMessage(
        "[Talentos] Comprar: !talentos comprar <id>"
    )
end

function M.HandleChat(player, msg)
    if not IsAdventurer(player) or not msg then
        return false
    end

    msg = msg:gsub("^%s+", ""):gsub("%s+$", "")

    if msg == "!talentos" then
        ShowTalentShop(player)
        return true
    end

    local talentId = msg:match("^!talentos%s+comprar%s+([%w_%-]+)$")
    if talentId then
        local ok, reason = M.UnlockFamilyWithHonor(player, talentId)
        if ok then
            local family = FAMILY_BY_ID[talentId]
            player:SendBroadcastMessage(string.format(
                "[Talentos] %s quedó desbloqueado para toda la cuenta.",
                family.label
            ))
            M.ScheduleMaybeSend(player, 150, 2)
        elseif reason == "owned" then
            player:SendBroadcastMessage(
                "[Talentos] Esa familia ya está desbloqueada."
            )
        elseif reason == "honor" then
            player:SendBroadcastMessage(
                "[Talentos] No tenés Honor de cuenta suficiente."
            )
        else
            player:SendBroadcastMessage(
                "[Talentos] No existe esa familia."
            )
        end
        ShowTalentShop(player)
        return true
    end

    -- Auxiliar temporal de prueba. Se elimina cuando Dungeon Master otorgue
    -- Honor de cuenta de forma real.
    local grant = msg:match("^!talentos%s+darhonor%s+(%d+)$")
    if grant and player:IsGM() then
        local total = M.GrantAccountHonor(player, tonumber(grant))
        player:SendBroadcastMessage(string.format(
            "[Talentos] TEST: Honor de cuenta = %u",
            total
        ))
        return true
    end

    return false
end

function M.HandleProtocolMessage(player, msg)
    if not IsAdventurer(player) or not msg then
        return false
    end

    if not M.HasPendingOffer(player) then
        return false
    end

    msg = msg:gsub("%s+$", "")

    if msg == "SC_CHECK" then
        M.EnsureAndSendOffer(player)
        return true
    end

    local picked = msg:match("^SC:(%d+)$")
    if picked then
        M.AcceptPick(player, tonumber(picked))
        return true
    end

    -- Los recursos de cartas (reroll/ban/protección) pertenecen al draft de
    -- habilidades. Mientras hay una oferta de talento no deben consumirlos.
    if msg == "SC_REROLL"
        or msg == "SC_REPLACE_BANNED"
        or msg:match("^SC_BAN:%d+$")
        or msg:match("^SC_PROTECT:%d+$") then
        M.EnsureAndSendOffer(player)
        return true
    end

    return false
end

function M.ScheduleMaybeSend(player, delayMs, attempts)
    if not IsAdventurer(player) then
        return
    end

    local guid = player:GetGUIDLow()
    local delay = math.max(50, math.floor(tonumber(delayMs) or 250))
    local tries = math.max(1, math.floor(tonumber(attempts) or 1))

    CreateLuaEvent(function()
        local current = GetPlayerByGUID(guid)
        if not current or not current:IsInWorld() or not IsAdventurer(current) then
            return
        end

        if NormalDraftsRemaining(current) <= 0 then
            M.EnsureAndSendOffer(current)
        elseif tries > 1 then
            M.ScheduleMaybeSend(current, math.max(500, delay * 2), tries - 1)
        end
    end, delay, 1)
end

function M.OnLogin(player)
    if not IsAdventurer(player) then
        return
    end

    LoadAccountProgress(player, true)
    LoadAccountUnlocks(player, true)
    LoadCharacterState(player, true)
    LoadPendingOffer(player, true)
    RestoreTalents(player)
    SyncVisibleHonor(player)

    M.ScheduleMaybeSend(player, 1200, 2)

    print(string.format(
        "[SpellDraft Talents] account=%u guid=%u honor=%u picks=%u/%u",
        AccountId(player),
        player:GetGUIDLow(),
        M.GetAccountHonor(player),
        LoadCharacterState(player, false).count,
        ExpectedTalentPicks(player)
    ))
end

function M.OnLogout(player)
    if not player then
        return
    end

    local guid = player:GetGUIDLow()
    characterStateCache[guid] = nil
    pendingOfferCache[guid] = nil
    pendingOfferLoaded[guid] = nil
end

function M.OnLevelChanged(player)
    if not IsAdventurer(player) then
        return
    end

    -- draft_core abre la habilidad de milestone a los 1000 ms. Esperamos un
    -- poco más; si hay una habilidad pendiente, el talento queda en espera y
    -- el wrapper vuelve a comprobar después de cada SC:<id> aceptado.
    M.ScheduleMaybeSend(player, 1300, 1)
end

function M.GetExpectedPicks(player)
    return ExpectedTalentPicks(player)
end

function M.GetRemainingPicks(player)
    return TalentPicksRemaining(player)
end

function M.GetNormalDraftsRemaining(player)
    return NormalDraftsRemaining(player)
end

print(string.format(
    "[Aventureros de Azeroth] Talent metaprogression loaded: first=%u, "
    .. "every=%u, max=%u, offer=%u, families=%u.",
    FIRST_TALENT_LEVEL,
    LEVELS_PER_TALENT,
    MAX_TALENT_PICKS,
    TALENT_OFFER_SIZE,
    #TALENT_FAMILIES
))

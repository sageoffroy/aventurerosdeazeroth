-- Aventureros de Azeroth - elecciones de talento por vida.
--
-- Este motor es independiente de SpellDraft. Solo usa su contrato publico de
-- persistencia (spelldraft_drafted_spells) para dar prioridad a las habilidades
-- normales cuando ambas progresiones coinciden en un mismo nivel.
--
-- La integracion de protocolo se hace desde agent/integration-testing con un
-- unico punto de delegacion en el handler SC:* de SpellDraft. Este archivo NO
-- registra eventos de chat para evitar que dos motores compitan por SC:<id>.

AventurerosTalentDraft = AventurerosTalentDraft or {}
local M = AventurerosTalentDraft

if M.__loaded then
    return
end
M.__loaded = true

local CLASS_ADVENTURER = 10
local MAX_PERSISTED_OFFER_SIZE = 5

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
    "AventurerosProgression.Talents.Enable",
    true
)
local FIRST_TALENT_LEVEL = ConfigNumber(
    "AventurerosProgression.Talents.FirstLevel",
    10,
    1,
    80,
    true
)
local LEVELS_PER_TALENT = ConfigNumber(
    "AventurerosProgression.Talents.LevelsPerPick",
    2,
    1,
    80,
    true
)
local MAX_TALENT_PICKS = ConfigNumber(
    "AventurerosProgression.Talents.MaxPicks",
    36,
    0,
    200,
    true
)
local TALENT_OFFER_SIZE = ConfigNumber(
    "AventurerosProgression.Talents.OfferSize",
    3,
    1,
    MAX_PERSISTED_OFFER_SIZE,
    true
)
local WAIT_RETRY_MS = ConfigNumber(
    "AventurerosProgression.Talents.WaitRetryMs",
    1500,
    250,
    10000,
    true
)

-- Lectura de la progresion normal. No escribimos archivos ni estado interno de
-- SpellDraft; replicamos solamente la formula publica de cuantos picks deberia
-- tener el personaje a su nivel actual.
local STARTING_DRAFTS = ConfigNumber("SpellDraft.StartingDrafts", 3, 0, 100, true)
local FIRST_ADDITIONAL_DRAFT_LEVEL = ConfigNumber(
    "SpellDraft.FirstAdditionalDraftLevel",
    5,
    2,
    80,
    true
)
local LEVELS_PER_DRAFT = ConfigNumber(
    "SpellDraft.LevelsPerDraft",
    5,
    1,
    80,
    true
)
local DRAFTS_PER_MILESTONE = ConfigNumber(
    "SpellDraft.DraftsPerMilestone",
    1,
    1,
    20,
    true
)
local MAX_DRAFTED_SPELLS = ConfigNumber(
    "SpellDraft.MaxDraftedSpells",
    15,
    0,
    500,
    true
)

local scriptPath = debug.getinfo(1).source:sub(2)
local parentPath = scriptPath:match("(.+[/\\])") or ""

if not AventurerosProgression or not AventurerosProgression.IsTalentUnlocked then
    dofile(parentPath .. "account.lua")
end
if not AventurerosTalentCatalog then
    dofile(parentPath .. "talent_catalog.lua")
end

local TALENT_FAMILIES = AventurerosTalentCatalog or {}
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
local waitGeneration = {}

local function IsBotPlayer(player)
    return player and player.IsBot ~= nil and player:IsBot()
end

local function IsAdventurer(player)
    return ENABLE
        and player
        and player:GetClass() == CLASS_ADVENTURER
        and not IsBotPlayer(player)
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
        "SELECT talent_id, talent_rank FROM aventureros_character_talents "
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

local function PicksRemaining(player)
    local state = LoadCharacterState(player, false)
    return math.max(0, ExpectedTalentPicks(player) - state.count)
end

local function ClearPendingOffer(guid)
    pendingOfferCache[guid] = nil
    pendingOfferLoaded[guid] = true
    CharDBExecute(
        "DELETE FROM aventureros_pending_talent_offer WHERE player_guid = " .. guid
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
        .. "FROM aventureros_pending_talent_offer WHERE player_guid = " .. guid
    )
    if not query then
        return nil
    end

    if query:GetUInt32(5) >= TALENT_OFFER_SIZE then
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
        "INSERT INTO aventureros_pending_talent_offer "
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

local function BuildCandidates(player)
    local state = LoadCharacterState(player, false)
    local candidates = {}

    for _, family in ipairs(TALENT_FAMILIES) do
        if AventurerosProgression.IsTalentUnlocked(player, family.id) then
            local nextRank = (state.ranks[family.id] or 0) + 1
            local spellId = family.ranks and family.ranks[nextRank]
            if spellId then
                table.insert(candidates, {
                    family = family,
                    rank = nextRank,
                    spellId = spellId,
                })
            end
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
    for _, spellId in ipairs(offer) do
        local mapped = SPELL_TO_RANK[spellId]
        if not mapped then
            return false
        end
        if not AventurerosProgression.IsTalentUnlocked(
            player,
            mapped.family.id
        ) then
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
        tostring(PicksRemaining(player)),
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

    if PicksRemaining(player) <= 0 then
        ClearPendingOffer(player:GetGUIDLow())
        return false
    end

    local offer = LoadPendingOffer(player, false)
    if not OfferIsCurrent(player, offer) then
        ClearPendingOffer(player:GetGUIDLow())
        offer = GenerateOffer(player)

        if #offer == 0 then
            player:SendBroadcastMessage(
                "[Talentos] Tu pool desbloqueado no tiene másrangos disponibles."
            )
            player:SendBroadcastMessage(
                "[Talentos] Us� !!talentos para ver nuevas familias desbloqueables."
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

    if PicksRemaining(player) <= 0 then
        ClearPendingOffer(guid)
        player:SendAddonMessage("SpellChoiceClose", "", 0, player)
        return true
    end

    local mapped = SPELL_TO_RANK[spellId]
    local state = LoadCharacterState(player, false)
    if not mapped
        or not AventurerosProgression.IsTalentUnlocked(
            player,
            mapped.family.id
        ) then
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
        "INSERT IGNORE INTO aventureros_character_talents "
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

    if PicksRemaining(player) > 0 then
        M.EnsureAndSendOffer(player)
    else
        player:SendAddonMessage("SpellChoiceClose", "", 0, player)
    end
    return true
end

function M.HandleProtocolMessage(player, msg)
    if not IsAdventurer(player) or not msg then
        return false
    end

    msg = msg:gsub("%s+$", "")
    if msg:sub(1, 2) ~= "SC" then
        return false
    end

    -- Las habilidades normales siempre tienen prioridad si el personaje debe
    -- resolver alguna. Esto permite acumular un Talento (N) pendiente sin
    -- secuestrar el SC:<id> de un milestone de SpellDraft.
    if NormalDraftsRemaining(player) > 0 then
        return false
    end

    if not M.HasPendingOffer(player) then
        return false
    end

    if msg == "SC_CHECK" then
        M.EnsureAndSendOffer(player)
        return true
    end

    local picked = msg:match("^SC:(%d+)$")
    if picked then
        M.AcceptPick(player, tonumber(picked))
        return true
    end

    if msg == "SC_REROLL"
        or msg == "SC_REPLACE_BANNED"
        or msg:match("^SC_BAN:%d+$")
        or msg:match("^SC_PROTECT:%d+$") then
        M.EnsureAndSendOffer(player)
        return true
    end

    return false
end

local function StartWaitLoop(player)
    if not IsAdventurer(player) then
        return
    end

    local guid = player:GetGUIDLow()
    local generation = (waitGeneration[guid] or 0) + 1
    waitGeneration[guid] = generation

    local function Tick()
        if waitGeneration[guid] ~= generation then
            return
        end

        local current = GetPlayerByGUID(guid)
        if not current
            or not current:IsInWorld()
            or not IsAdventurer(current) then
            return
        end

        if PicksRemaining(current) <= 0 then
            return
        end

        if NormalDraftsRemaining(current) <= 0 then
            M.EnsureAndSendOffer(current)
            return
        end

        -- El jugador puede tardar todo lo que quiera en elegir su habilidad.
        -- Seguimos esperando sin pedirle al motor de SpellDraft que nos avise.
        CreateLuaEvent(Tick, WAIT_RETRY_MS, 1)
    end

    CreateLuaEvent(Tick, WAIT_RETRY_MS, 1)
end

local function OnLogin(_, player)
    if not IsAdventurer(player) then
        return
    end

    LoadCharacterState(player, true)
    LoadPendingOffer(player, true)
    RestoreTalents(player)
    StartWaitLoop(player)
end

local function OnLogout(_, player)
    if not player then
        return
    end

    local guid = player:GetGUIDLow()
    characterStateCache[guid] = nil
    pendingOfferCache[guid] = nil
    pendingOfferLoaded[guid] = nil
    waitGeneration[guid] = (waitGeneration[guid] or 0) + 1
end

local function OnLevelChanged(_, player)
    if not IsAdventurer(player) then
        return
    end
    StartWaitLoop(player)
end

function M.GetExpectedPicks(player)
    return ExpectedTalentPicks(player)
end

function M.GetRemainingPicks(player)
    return PicksRemaining(player)
end

function M.GetNormalDraftsRemaining(player)
    return NormalDraftsRemaining(player)
end

RegisterPlayerEvent(3, OnLogin)
RegisterPlayerEvent(4, OnLogout)
RegisterPlayerEvent(13, OnLevelChanged)

print(string.format(
    "[Aventureros de Azeroth] Talent draft loaded: first=%u, every=%u, "
    .. "max=%u, offer=%u, families=%u.",
    FIRST_TALENT_LEVEL,
    LEVELS_PER_TALENT,
    MAX_TALENT_PICKS,
    TALENT_OFFER_SIZE,
    #TALENT_FAMILIES
))

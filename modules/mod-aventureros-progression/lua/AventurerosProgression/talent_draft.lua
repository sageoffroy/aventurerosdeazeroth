-- Aventureros de Azeroth - per-life talent draft.
-- SpellDraft owns normal abilities. This module only reads its persisted pick
-- count so abilities always have priority when both systems unlock together.

AventurerosTalentDraft = AventurerosTalentDraft or {}
local M = AventurerosTalentDraft
if M.__loaded then return end
M.__loaded = true

local CLASS_ADVENTURER = 10
local MAX_OFFER = 5

local function cfgBool(name, default)
    local raw = GetConfigValue(name)
    if raw == nil or raw == "" then return default end
    if raw == true or raw == 1 or raw == "1" then return true end
    if raw == false or raw == 0 or raw == "0" then return false end
    local v = string.lower(tostring(raw))
    if v == "true" or v == "yes" or v == "on" then return true end
    if v == "false" or v == "no" or v == "off" then return false end
    return default
end

local function cfgNum(name, default, lo, hi)
    local v = math.floor(tonumber(GetConfigValue(name)) or default)
    if lo then v = math.max(lo, v) end
    if hi then v = math.min(hi, v) end
    return v
end

local ENABLED = cfgBool("AventurerosProgression.Talents.Enable", true)
local FIRST_LEVEL = cfgNum("AventurerosProgression.Talents.FirstLevel", 10, 1, 80)
local LEVELS_PER_PICK = cfgNum("AventurerosProgression.Talents.LevelsPerPick", 2, 1, 80)
local MAX_PICKS = cfgNum("AventurerosProgression.Talents.MaxPicks", 36, 0, 200)
local OFFER_SIZE = cfgNum("AventurerosProgression.Talents.OfferSize", 3, 1, MAX_OFFER)
local RETRY_MS = cfgNum("AventurerosProgression.Talents.WaitRetryMs", 1500, 250, 10000)

-- Public SpellDraft progression contract. We read config + the existing table;
-- no SpellDraft source file or runtime local is imported here.
local SD_START = cfgNum("SpellDraft.StartingDrafts", 3, 0, 100)
local SD_FIRST = cfgNum("SpellDraft.FirstAdditionalDraftLevel", 5, 2, 80)
local SD_EVERY = cfgNum("SpellDraft.LevelsPerDraft", 5, 1, 80)
local SD_PER_MILESTONE = cfgNum("SpellDraft.DraftsPerMilestone", 1, 1, 20)
local SD_MAX = cfgNum("SpellDraft.MaxDraftedSpells", 15, 0, 500)

local scriptPath = debug.getinfo(1).source:sub(2)
local parentPath = scriptPath:match("(.+[/\\])") or ""
if not AventurerosProgression or not AventurerosProgression.IsTalentUnlocked then
    dofile(parentPath .. "account.lua")
end
if not AventurerosTalentCatalog then
    dofile(parentPath .. "talent_catalog.lua")
end

local FAMILIES = AventurerosTalentCatalog or {}
local BY_ID, SPELL_RANK = {}, {}
for _, family in ipairs(FAMILIES) do
    BY_ID[family.id] = family
    for rank, spellId in ipairs(family.ranks or {}) do
        SPELL_RANK[spellId] = { family = family, rank = rank }
    end
end

local stateCache, offerCache, offerLoaded, generation = {}, {}, {}, {}

local function isBot(player)
    return player and player.IsBot ~= nil and player:IsBot()
end

local function isAdventurer(player)
    return ENABLED and player and player:GetClass() == CLASS_ADVENTURER and not isBot(player)
end

local function expectedNormal(player)
    local level = math.max(1, player:GetLevel() or 1)
    local n = SD_START
    if level >= SD_FIRST then
        n = n + (math.floor((level - SD_FIRST) / SD_EVERY) + 1) * SD_PER_MILESTONE
    end
    if SD_MAX > 0 then n = math.min(n, SD_MAX) end
    return n
end

local function normalCount(player)
    local q = CharDBQuery(
        "SELECT COUNT(*) FROM spelldraft_drafted_spells WHERE player_guid = "
        .. player:GetGUIDLow()
    )
    return q and q:GetUInt32(0) or 0
end

local function normalRemaining(player)
    return math.max(0, expectedNormal(player) - normalCount(player))
end

local function expectedPicks(player)
    if not isAdventurer(player) then return 0 end
    local level = math.max(1, player:GetLevel() or 1)
    if level < FIRST_LEVEL then return 0 end
    local n = math.floor((level - FIRST_LEVEL) / LEVELS_PER_PICK) + 1
    if MAX_PICKS > 0 then n = math.min(n, MAX_PICKS) end
    return n
end

local function loadState(player, force)
    local guid = player:GetGUIDLow()
    if stateCache[guid] and not force then return stateCache[guid] end
    local state = { ranks = {}, count = 0 }
    local q = CharDBQuery(
        "SELECT talent_id, talent_rank FROM aventureros_character_talents "
        .. "WHERE player_guid = " .. guid .. " ORDER BY talent_index"
    )
    if q then
        repeat
            local id, rank = q:GetString(0), q:GetUInt32(1)
            if id and id ~= "" and rank > 0 then
                state.ranks[id] = math.max(state.ranks[id] or 0, rank)
                state.count = state.count + 1
            end
        until not q:NextRow()
    end
    stateCache[guid] = state
    return state
end

local function picksRemaining(player)
    return math.max(0, expectedPicks(player) - loadState(player, false).count)
end

local function clearOffer(guid)
    offerCache[guid], offerLoaded[guid] = nil, true
    CharDBExecute("DELETE FROM aventureros_pending_talent_offer WHERE player_guid = " .. guid)
end

local function loadOffer(player, force)
    local guid = player:GetGUIDLow()
    if offerLoaded[guid] and not force then return offerCache[guid] end
    offerLoaded[guid], offerCache[guid] = true, nil
    local q = CharDBQuery(
        "SELECT offer_1, offer_2, offer_3, offer_4, offer_5, offer_size "
        .. "FROM aventureros_pending_talent_offer WHERE player_guid = " .. guid
    )
    if not q then return nil end
    if q:GetUInt32(5) ~= OFFER_SIZE then clearOffer(guid); return nil end
    local offer = {}
    for col = 0, MAX_OFFER - 1 do
        local id = q:GetUInt32(col)
        if id and id > 0 then table.insert(offer, id) end
    end
    if #offer == 0 then clearOffer(guid); return nil end
    offerCache[guid] = offer
    return offer
end

local function saveOffer(player, offer)
    local guid = player:GetGUIDLow()
    local v = {0, 0, 0, 0, 0}
    for i, id in ipairs(offer) do if i <= MAX_OFFER then v[i] = id end end
    offerCache[guid], offerLoaded[guid] = offer, true
    CharDBExecute(string.format(
        "INSERT INTO aventureros_pending_talent_offer "
        .. "(player_guid,offer_1,offer_2,offer_3,offer_4,offer_5,offer_size,offered_level) "
        .. "VALUES (%u,%u,%u,%u,%u,%u,%u,%u) ON DUPLICATE KEY UPDATE "
        .. "offer_1=VALUES(offer_1),offer_2=VALUES(offer_2),offer_3=VALUES(offer_3),"
        .. "offer_4=VALUES(offer_4),offer_5=VALUES(offer_5),offer_size=VALUES(offer_size),"
        .. "offered_level=VALUES(offered_level)",
        guid, v[1], v[2], v[3], v[4], v[5], OFFER_SIZE, player:GetLevel() or 1
    ))
end

local function candidates(player)
    local state, out = loadState(player, false), {}
    for _, family in ipairs(FAMILIES) do
        if AventurerosProgression.IsTalentUnlocked(player, family.id) then
            local rank = (state.ranks[family.id] or 0) + 1
            local spellId = family.ranks and family.ranks[rank]
            if spellId then table.insert(out, spellId) end
        end
    end
    return out
end

local function shuffle(t)
    for i = #t, 2, -1 do
        local j = math.random(i)
        t[i], t[j] = t[j], t[i]
    end
end

local function makeOffer(player)
    local pool, offer = candidates(player), {}
    shuffle(pool)
    for i = 1, math.min(OFFER_SIZE, #pool) do table.insert(offer, pool[i]) end
    return offer
end

local function contains(offer, spellId)
    for _, id in ipairs(offer or {}) do if id == spellId then return true end end
    return false
end

local function offerCurrent(player, offer)
    if not offer or #offer == 0 then return false end
    local state = loadState(player, false)
    for _, spellId in ipairs(offer) do
        local mapped = SPELL_RANK[spellId]
        if not mapped or not AventurerosProgression.IsTalentUnlocked(player, mapped.family.id) then
            return false
        end
        if mapped.rank ~= (state.ranks[mapped.family.id] or 0) + 1 then return false end
    end
    return true
end

local function sendOffer(player, offer)
    local zeros = {}
    for _ = 1, #offer do table.insert(zeros, "0") end
    player:SendAddonMessage("SpellChoiceDrafts", tostring(picksRemaining(player)), 0, player)
    player:SendAddonMessage("SpellChoiceRerolls", "0", 0, player)
    player:SendAddonMessage("SpellChoiceBansLeft", "0", 0, player)
    player:SendAddonMessage("SpellChoiceProtections", "0", 0, player)
    player:SendAddonMessage("SpellChoiceProtectionEnabled", "0", 0, player)
    player:SendAddonMessage("SpellChoiceIsTalent", "1", 0, player)
    player:SendAddonMessage("SpellChoice", table.concat(offer, ","), 0, player)
    player:SendAddonMessage("SpellChoiceRarities", table.concat(zeros, ","), 0, player)
    player:SendAddonMessage("SpellChoiceClasses", table.concat(zeros, ","), 0, player)
end

local function learnRank(player, family, rank)
    for i, id in ipairs(family.ranks or {}) do
        if i ~= rank and player:HasSpell(id) then player:RemoveSpell(id) end
    end
    local id = family.ranks and family.ranks[rank]
    if id and not player:HasSpell(id) then player:LearnSpell(id) end
end

local function restore(player)
    local state = loadState(player, false)
    for id, rank in pairs(state.ranks) do
        if BY_ID[id] then learnRank(player, BY_ID[id], rank) end
    end
end

function M.HasPendingOffer(player)
    return isAdventurer(player) and loadOffer(player, false) ~= nil
end

function M.EnsureAndSendOffer(player)
    if not isAdventurer(player) or normalRemaining(player) > 0 then return false end
    if picksRemaining(player) <= 0 then clearOffer(player:GetGUIDLow()); return false end
    local offer = loadOffer(player, false)
    if not offerCurrent(player, offer) then
        clearOffer(player:GetGUIDLow())
        offer = makeOffer(player)
        if #offer == 0 then
            player:SendBroadcastMessage("[Talentos] No quedan rangos disponibles en tu pool.")
            player:SendAddonMessage("SpellChoiceClose", "", 0, player)
            return false
        end
        saveOffer(player, offer)
    end
    sendOffer(player, offer)
    return true
end

function M.AcceptPick(player, spellId)
    if not isAdventurer(player) then return false end
    local guid, offer = player:GetGUIDLow(), loadOffer(player, false)
    if not offer or not contains(offer, spellId) then return false end
    local mapped, state = SPELL_RANK[spellId], loadState(player, false)
    if not mapped or not AventurerosProgression.IsTalentUnlocked(player, mapped.family.id) then
        clearOffer(guid); M.EnsureAndSendOffer(player); return true
    end
    local current = state.ranks[mapped.family.id] or 0
    if mapped.rank ~= current + 1 then clearOffer(guid); M.EnsureAndSendOffer(player); return true end

    local idx, level = state.count + 1, player:GetLevel() or 1
    CharDBExecute(string.format(
        "INSERT IGNORE INTO aventureros_character_talents "
        .. "(player_guid,talent_id,talent_rank,talent_spell_id,talent_index,picked_level) "
        .. "VALUES (%u,'%s',%u,%u,%u,%u)",
        guid, mapped.family.id, mapped.rank, spellId, idx, level
    ))
    state.ranks[mapped.family.id], state.count = mapped.rank, idx
    stateCache[guid] = state
    learnRank(player, mapped.family, mapped.rank)
    player:CastSpell(player, 24312, true)
    player:RemoveAura(24312)
    clearOffer(guid)
    if picksRemaining(player) > 0 then M.EnsureAndSendOffer(player)
    else player:SendAddonMessage("SpellChoiceClose", "", 0, player) end
    return true
end

function M.HandleProtocolMessage(player, msg)
    if not isAdventurer(player) or not msg then return false end
    msg = msg:gsub("%s+$", "")
    if msg:sub(1, 2) ~= "SC" or normalRemaining(player) > 0 or not M.HasPendingOffer(player) then
        return false
    end
    if msg == "SC_CHECK" then M.EnsureAndSendOffer(player); return true end
    local picked = msg:match("^SC:(%d+)$")
    if picked then M.AcceptPick(player, tonumber(picked)); return true end
    if msg == "SC_REROLL" or msg == "SC_REPLACE_BANNED"
        or msg:match("^SC_BAN:%d+$") or msg:match("^SC_PROTECT:%d+$") then
        M.EnsureAndSendOffer(player); return true
    end
    return false
end

local function startWait(player)
    if not isAdventurer(player) then return end
    local guid = player:GetGUIDLow()
    local gen = (generation[guid] or 0) + 1
    generation[guid] = gen
    local function tick()
        if generation[guid] ~= gen then return end
        local p = GetPlayerByGUID(guid)
        if not p or not p:IsInWorld() or not isAdventurer(p) then return end
        if picksRemaining(p) <= 0 then return end
        if normalRemaining(p) <= 0 then M.EnsureAndSendOffer(p); return end
        CreateLuaEvent(tick, RETRY_MS, 1)
    end
    CreateLuaEvent(tick, RETRY_MS, 1)
end

local function onLogin(_, player)
    if not isAdventurer(player) then return end
    loadState(player, true); loadOffer(player, true); restore(player); startWait(player)
end
local function onLogout(_, player)
    if not player then return end
    local guid = player:GetGUIDLow()
    stateCache[guid], offerCache[guid], offerLoaded[guid] = nil, nil, nil
    generation[guid] = (generation[guid] or 0) + 1
end
local function onLevel(_, player) startWait(player) end

function M.GetExpectedPicks(player) return expectedPicks(player) end
function M.GetRemainingPicks(player) return picksRemaining(player) end
function M.GetNormalDraftsRemaining(player) return normalRemaining(player) end

RegisterPlayerEvent(3, onLogin)
RegisterPlayerEvent(4, onLogout)
RegisterPlayerEvent(13, onLevel)

print(string.format(
    "[Aventureros de Azeroth] Talent draft loaded: first=%u every=%u max=%u offer=%u families=%u.",
    FIRST_LEVEL, LEVELS_PER_PICK, MAX_PICKS, OFFER_SIZE, #FAMILIES
))

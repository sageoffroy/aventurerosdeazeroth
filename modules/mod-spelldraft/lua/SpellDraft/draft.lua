-- Native Adventurer SpellDraft loop.
--
-- The protocol/persistence layer is intentionally independent from the old
-- prestige implementation. The ability pool itself is generated from the live
-- WotLK DBCs plus the curated rarity/class metadata from the historical addon.

local CLASS_ADVENTURER = 10
local DRAFTS_PER_LEVEL = 10
local OFFER_SIZE = 3
local LOW_LEVEL_POOL_FLOOR = 20

local scriptPath = debug.getinfo(1).source:sub(2)
local parentPath = scriptPath:match("(.+[/\\])") or ""
if not SpellDraftCatalog then
    dofile(parentPath .. "catalog.lua")
end

local SPELL_POOL = SpellDraftCatalog or {}
local RARITY_DISTRIBUTION = SpellDraftRarityDistribution or {
    [0] = 70.0,
    [1] = 20.0,
    [2] = 7.0,
    [3] = 2.5,
    [4] = 0.5,
}

if #SPELL_POOL == 0 then
    error("SpellDraft real catalog is empty or missing")
end

local POOL_BY_ID = {}
for _, entry in ipairs(SPELL_POOL) do
    POOL_BY_ID[entry.id] = entry
end

-- ALE database Execute calls are queued. Keep authoritative per-session caches
-- so fast picks cannot race the async INSERT/REPLACE before the next offer is
-- generated. The character DB remains the persistent source across logins.
local draftedCache = {}
local pendingOfferCache = {}
local pendingOfferLoaded = {}

math.randomseed(os.time())
math.random()
math.random()
math.random()

local function IsBotPlayer(player)
    return player and player.IsBot ~= nil and player:IsBot()
end

local function IsAdventurer(player)
    return player and player:GetClass() == CLASS_ADVENTURER and not IsBotPlayer(player)
end

local function ExpectedDrafts(player)
    return math.max(1, player:GetLevel() or 1) * DRAFTS_PER_LEVEL
end

local function EligibilityLevel(player)
    return math.max(player:GetLevel() or 1, LOW_LEVEL_POOL_FLOOR)
end

local function LoadDraftedState(guid, force)
    if draftedCache[guid] and not force then
        return draftedCache[guid]
    end

    local state = { set = {}, count = 0 }
    local query = CharDBQuery(
        "SELECT spell_id FROM spelldraft_drafted_spells " ..
        "WHERE player_guid = " .. guid .. " ORDER BY draft_index"
    )

    if query then
        repeat
            local spellId = query:GetUInt32(0)
            if spellId > 0 and not state.set[spellId] then
                state.set[spellId] = true
                state.count = state.count + 1
            end
        until not query:NextRow()
    end

    draftedCache[guid] = state
    return state
end

local function DraftsRemaining(player)
    local state = LoadDraftedState(player:GetGUIDLow(), false)
    return math.max(0, ExpectedDrafts(player) - state.count)
end

local function LoadPendingOffer(guid, force)
    if pendingOfferLoaded[guid] and not force then
        return pendingOfferCache[guid]
    end

    pendingOfferLoaded[guid] = true
    pendingOfferCache[guid] = nil

    local query = CharDBQuery(
        "SELECT offer_1, offer_2, offer_3 FROM spelldraft_pending_offer " ..
        "WHERE player_guid = " .. guid
    )
    if not query then
        return nil
    end

    local offer = {}
    for column = 0, 2 do
        local spellId = query:GetUInt32(column)
        if spellId and spellId > 0 then
            table.insert(offer, spellId)
        end
    end

    if #offer > 0 then
        pendingOfferCache[guid] = offer
    end
    return pendingOfferCache[guid]
end

local function SavePendingOffer(player, offer)
    local guid = player:GetGUIDLow()
    local one = offer[1] or 0
    local two = offer[2] or 0
    local three = offer[3] or 0
    local level = player:GetLevel() or 1

    pendingOfferLoaded[guid] = true
    pendingOfferCache[guid] = offer

    CharDBExecute(string.format(
        "REPLACE INTO spelldraft_pending_offer " ..
        "(player_guid, offer_1, offer_2, offer_3, offered_level) " ..
        "VALUES (%u, %u, %u, %u, %u)",
        guid, one, two, three, level
    ))
end

local function ClearPendingOffer(guid)
    pendingOfferLoaded[guid] = true
    pendingOfferCache[guid] = nil
    CharDBExecute(
        "DELETE FROM spelldraft_pending_offer WHERE player_guid = " .. guid
    )
end

local function PlayerHasAnyRank(player, entry)
    if player:HasSpell(entry.id) then
        return true
    end

    for _, rank in ipairs(entry.ranks or {}) do
        if rank.id ~= entry.id and player:HasSpell(rank.id) then
            return true
        end
    end
    return false
end

local function RollRarity()
    local roll = math.random() * 100.0
    local cumulative = 0.0
    for rarity = 0, 4 do
        cumulative = cumulative + (RARITY_DISTRIBUTION[rarity] or 0)
        if roll < cumulative then
            return rarity
        end
    end
    return 0
end

local function PickCandidate(candidates, picked, preferredRarity)
    local matching = {}
    local fallback = {}

    for _, entry in ipairs(candidates) do
        if not picked[entry.id] then
            table.insert(fallback, entry)
            if entry.rarity == preferredRarity then
                table.insert(matching, entry)
            end
        end
    end

    local source = #matching > 0 and matching or fallback
    if #source == 0 then
        return nil
    end
    return source[math.random(1, #source)]
end

local function GenerateOffer(player)
    local state = LoadDraftedState(player:GetGUIDLow(), false)
    local queryLevel = EligibilityLevel(player)
    local candidates = {}

    for _, entry in ipairs(SPELL_POOL) do
        if entry.minLevel <= queryLevel
            and not state.set[entry.id]
            and not PlayerHasAnyRank(player, entry) then
            table.insert(candidates, entry)
        end
    end

    local offer = {}
    local picked = {}
    local take = math.min(OFFER_SIZE, #candidates)

    for _ = 1, take do
        local entry = PickCandidate(candidates, picked, RollRarity())
        if not entry then
            break
        end
        picked[entry.id] = true
        table.insert(offer, entry.id)
    end

    return offer
end

local function SendCompatibilityState(player)
    -- The historical addon calls this state "prestiged". In Aventureros it
    -- simply means that native class-10 SpellDraft is enabled.
    player:SendAddonMessage("SpellChoiceStatus", "prestiged", 0, player)
    player:SendAddonMessage("SpellChoiceBansLeft", "0", 0, player)
    player:SendAddonMessage("SpellChoiceBans", "", 0, player)
    player:SendAddonMessage("SpellChoiceRerolls", "0", 0, player)
    player:SendAddonMessage("SpellChoiceUnlimitedReroll", "0", 0, player)
    player:SendAddonMessage("SpellChoiceDrafts", tostring(DraftsRemaining(player)), 0, player)
end

local function SendOffer(player, offer)
    local rarityParts = {}
    local classParts = {}

    for _, spellId in ipairs(offer) do
        local entry = POOL_BY_ID[spellId]
        table.insert(rarityParts, tostring(entry and entry.rarity or 0))
        table.insert(classParts, tostring(entry and entry.classSet or 0))
    end

    player:SendAddonMessage("SpellChoiceIsTalent", "0", 0, player)
    player:SendAddonMessage("SpellChoice", table.concat(offer, ","), 0, player)
    player:SendAddonMessage("SpellChoiceRarities", table.concat(rarityParts, ","), 0, player)
    player:SendAddonMessage("SpellChoiceClasses", table.concat(classParts, ","), 0, player)
end

local function OfferIsCurrent(player, offer)
    if not offer or #offer == 0 then
        return false
    end

    local state = LoadDraftedState(player:GetGUIDLow(), false)
    for _, spellId in ipairs(offer) do
        local entry = POOL_BY_ID[spellId]
        if not entry or state.set[spellId] then
            return false
        end
    end
    return true
end

local function EnsureAndSendOffer(player)
    if not IsAdventurer(player) then
        return
    end

    SendCompatibilityState(player)

    if DraftsRemaining(player) <= 0 then
        ClearPendingOffer(player:GetGUIDLow())
        player:SendAddonMessage("SpellChoiceClose", "", 0, player)
        return
    end

    local guid = player:GetGUIDLow()
    local offer = LoadPendingOffer(guid, false)
    if not OfferIsCurrent(player, offer) then
        ClearPendingOffer(guid)
        offer = GenerateOffer(player)
        if #offer == 0 then
            player:SendBroadcastMessage(
                "SpellDraft: no quedan habilidades elegibles en el catalogo real."
            )
            player:SendAddonMessage("SpellChoiceClose", "", 0, player)
            return
        end
        SavePendingOffer(player, offer)
    end

    SendOffer(player, offer)
end

local function OfferContains(offer, spellId)
    if not offer then
        return false
    end
    for _, offeredId in ipairs(offer) do
        if offeredId == spellId then
            return true
        end
    end
    return false
end

local function LearnDraftedEntry(player, entry)
    if not entry then
        return
    end

    -- A card always grants its root rank, even when the stock trainer would
    -- normally teach that root above the player's current level. The low-level
    -- draft intentionally sees the class pool up through level 20.
    if not player:HasSpell(entry.id) then
        player:LearnSpell(entry.id)
    end

    -- Higher ranks follow normal player level progression after the ability was
    -- drafted. Do not use the level-20 eligibility floor for rank upgrades.
    local level = player:GetLevel() or 1
    local best = entry.id
    for _, rank in ipairs(entry.ranks or {}) do
        if rank.id == entry.id or rank.level <= level then
            best = rank.id
        end
    end

    if best ~= entry.id and not player:HasSpell(best) then
        player:LearnSpell(best)
    end
end

local function RestoreAndUpgradeDraftedSpells(player)
    if not IsAdventurer(player) then
        return
    end

    local state = LoadDraftedState(player:GetGUIDLow(), false)
    for spellId, _ in pairs(state.set) do
        LearnDraftedEntry(player, POOL_BY_ID[spellId])
    end
end

local function AcceptPick(player, spellId)
    if not IsAdventurer(player) then
        return
    end

    local guid = player:GetGUIDLow()
    local offer = LoadPendingOffer(guid, false)
    if not OfferContains(offer, spellId) then
        player:SendBroadcastMessage("SpellDraft: esa carta no pertenece a tu oferta actual.")
        EnsureAndSendOffer(player)
        return
    end

    local entry = POOL_BY_ID[spellId]
    if not entry then
        ClearPendingOffer(guid)
        EnsureAndSendOffer(player)
        return
    end

    local state = LoadDraftedState(guid, false)
    if state.set[spellId] then
        ClearPendingOffer(guid)
        EnsureAndSendOffer(player)
        return
    end

    if DraftsRemaining(player) <= 0 then
        ClearPendingOffer(guid)
        player:SendAddonMessage("SpellChoiceClose", "", 0, player)
        return
    end

    local draftIndex = state.count + 1
    local level = player:GetLevel() or 1

    -- Update session state before queueing the DB write so the next offer never
    -- races CharacterDatabase.Execute.
    state.set[spellId] = true
    state.count = draftIndex

    CharDBExecute(string.format(
        "INSERT IGNORE INTO spelldraft_drafted_spells " ..
        "(player_guid, spell_id, draft_index, picked_level) VALUES (%u, %u, %u, %u)",
        guid, spellId, draftIndex, level
    ))

    LearnDraftedEntry(player, entry)
    player:CastSpell(player, 24312, true)
    player:RemoveAura(24312)

    ClearPendingOffer(guid)
    SendCompatibilityState(player)

    if DraftsRemaining(player) > 0 then
        EnsureAndSendOffer(player)
    else
        player:SendAddonMessage("SpellChoiceClose", "", 0, player)
    end
end

local function OnProtocolWhisper(_, player, msg, _, _, receiver)
    if not IsAdventurer(player) or not msg then
        return
    end

    -- SAY is the canonical hidden transport in Aventureros. The receiver check
    -- remains only for the legacy self-whisper compatibility listener.
    if receiver and receiver:GetGUIDLow() ~= player:GetGUIDLow() then
        return
    end

    msg = msg:gsub("%s+$", "")
    if msg:sub(1, 2) ~= "SC" then
        return
    end

    if msg == "SC_CHECK" then
        EnsureAndSendOffer(player)
        return false
    end

    local picked = msg:match("^SC:(%d+)$")
    if picked then
        AcceptPick(player, tonumber(picked))
        return false
    end

    -- Rerolls and bans are intentionally postponed until the real base pool is
    -- proven. Keep the old addon stable by explicitly denying those requests.
    if msg == "SC_REROLL" then
        player:SendAddonMessage("SpellChoiceRerollDenied", "0", 0, player)
        return false
    end

    if msg:match("^SC_BAN:") then
        player:SendAddonMessage("SpellChoiceBanDenied", "0", 0, player)
        return false
    end
end

local function OnLogin(_, player)
    if not IsAdventurer(player) then
        return
    end

    local guid = player:GetGUIDLow()
    LoadDraftedState(guid, true)
    LoadPendingOffer(guid, true)
    RestoreAndUpgradeDraftedSpells(player)
end

local function OnLogout(_, player)
    if not player then
        return
    end

    local guid = player:GetGUIDLow()
    draftedCache[guid] = nil
    pendingOfferCache[guid] = nil
    pendingOfferLoaded[guid] = nil
end

local function OnLevelChanged(_, player)
    if not IsAdventurer(player) then
        return
    end

    RestoreAndUpgradeDraftedSpells(player)

    local guid = player:GetGUIDLow()
    CreateLuaEvent(function()
        local current = GetPlayerByGUID(guid)
        if current and current:IsInWorld() and IsAdventurer(current) then
            EnsureAndSendOffer(current)
        end
    end, 1000, 1)
end

RegisterPlayerEvent(18, OnProtocolWhisper) -- PLAYER_EVENT_ON_CHAT (SC transport)
RegisterPlayerEvent(19, OnProtocolWhisper) -- PLAYER_EVENT_ON_WHISPER (legacy compatibility)
RegisterPlayerEvent(3, OnLogin)            -- PLAYER_EVENT_ON_LOGIN
RegisterPlayerEvent(4, OnLogout)           -- PLAYER_EVENT_ON_LOGOUT
RegisterPlayerEvent(13, OnLevelChanged)    -- PLAYER_EVENT_ON_LEVEL_CHANGE

print(
    "[Aventureros de Azeroth] Real SpellDraft engine loaded: " ..
    tostring(#SPELL_POOL) .. " root abilities, 10 drafts/level."
)

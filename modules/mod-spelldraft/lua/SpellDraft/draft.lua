-- Minimal native Adventurer SpellDraft loop.
--
-- This is intentionally small and independent from the historical prestige
-- system. It speaks the existing SpellChoice addon protocol so the current
-- client UI can be used while the new server-side draft engine is rebuilt in
-- clean layers.

local CLASS_ADVENTURER = 10
local STARTING_DRAFTS = 5
local OFFER_SIZE = 3

-- SpellClassSet values are the values expected by the historical client UI:
-- Mage 3, Warrior 4, Warlock 5, Priest 6, Druid 7, Rogue 8, Hunter 9,
-- Paladin 10, Shaman 11, Death Knight 15.
--
-- This is only the bootstrap pool. The full canonical pool/rarity database is
-- migrated separately after the end-to-end draft loop is proven on this core.
local SPELL_POOL = {
    { id = 78,    rarity = 0, classSet = 4,  minLevel = 1 }, -- Heroic Strike
    { id = 100,   rarity = 0, classSet = 4,  minLevel = 4 }, -- Charge
    { id = 133,   rarity = 0, classSet = 3,  minLevel = 1 }, -- Fireball
    { id = 116,   rarity = 0, classSet = 3,  minLevel = 4 }, -- Frostbolt
    { id = 686,   rarity = 0, classSet = 5,  minLevel = 1 }, -- Shadow Bolt
    { id = 172,   rarity = 0, classSet = 5,  minLevel = 4 }, -- Corruption
    { id = 585,   rarity = 0, classSet = 6,  minLevel = 1 }, -- Smite
    { id = 2050,  rarity = 0, classSet = 6,  minLevel = 1 }, -- Lesser Heal
    { id = 5176,  rarity = 0, classSet = 7,  minLevel = 1 }, -- Wrath
    { id = 5185,  rarity = 0, classSet = 7,  minLevel = 1 }, -- Healing Touch
    { id = 1752,  rarity = 0, classSet = 8,  minLevel = 1 }, -- Sinister Strike
    { id = 53,    rarity = 0, classSet = 8,  minLevel = 4 }, -- Backstab
    { id = 2973,  rarity = 0, classSet = 9,  minLevel = 1 }, -- Raptor Strike
    { id = 3044,  rarity = 0, classSet = 9,  minLevel = 6 }, -- Arcane Shot
    { id = 635,   rarity = 0, classSet = 10, minLevel = 1 }, -- Holy Light
    { id = 19740, rarity = 0, classSet = 10, minLevel = 4 }, -- Blessing of Might
    { id = 403,   rarity = 0, classSet = 11, minLevel = 1 }, -- Lightning Bolt
    { id = 331,   rarity = 0, classSet = 11, minLevel = 1 }, -- Healing Wave
}

local POOL_BY_ID = {}
for _, entry in ipairs(SPELL_POOL) do
    POOL_BY_ID[entry.id] = entry
end

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
    return STARTING_DRAFTS + math.max(0, (player:GetLevel() or 1) - 1)
end

local function CountDrafted(guid)
    local query = CharDBQuery(
        "SELECT COUNT(*) FROM spelldraft_drafted_spells WHERE player_guid = " .. guid
    )
    if not query then
        return 0
    end
    return query:GetUInt32(0)
end

local function LoadDraftedSet(guid)
    local drafted = {}
    local query = CharDBQuery(
        "SELECT spell_id FROM spelldraft_drafted_spells WHERE player_guid = " .. guid
    )
    if not query then
        return drafted
    end

    repeat
        drafted[query:GetUInt32(0)] = true
    until not query:NextRow()

    return drafted
end

local function DraftsRemaining(player)
    return math.max(0, ExpectedDrafts(player) - CountDrafted(player:GetGUIDLow()))
end

local function LoadPendingOffer(guid)
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

    if #offer == 0 then
        return nil
    end
    return offer
end

local function SavePendingOffer(player, offer)
    local guid = player:GetGUIDLow()
    local one = offer[1] or 0
    local two = offer[2] or 0
    local three = offer[3] or 0
    local level = player:GetLevel() or 1

    CharDBExecute(string.format(
        "REPLACE INTO spelldraft_pending_offer " ..
        "(player_guid, offer_1, offer_2, offer_3, offered_level) " ..
        "VALUES (%u, %u, %u, %u, %u)",
        guid, one, two, three, level
    ))
end

local function ClearPendingOffer(guid)
    CharDBExecute(
        "DELETE FROM spelldraft_pending_offer WHERE player_guid = " .. guid
    )
end

local function GenerateOffer(player)
    local guid = player:GetGUIDLow()
    local drafted = LoadDraftedSet(guid)
    local level = player:GetLevel() or 1
    local candidates = {}

    for _, entry in ipairs(SPELL_POOL) do
        if entry.minLevel <= level
            and not drafted[entry.id]
            and not player:HasSpell(entry.id) then
            table.insert(candidates, entry.id)
        end
    end

    -- Partial Fisher-Yates: randomize only as far as the requested offer.
    local take = math.min(OFFER_SIZE, #candidates)
    for i = 1, take do
        local j = math.random(i, #candidates)
        candidates[i], candidates[j] = candidates[j], candidates[i]
    end

    local offer = {}
    for i = 1, take do
        table.insert(offer, candidates[i])
    end
    return offer
end

local function SendCompatibilityState(player)
    -- The historical addon calls this state "prestiged". In the new project it
    -- simply means that native Adventurer SpellDraft is enabled for this player.
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
    local offer = LoadPendingOffer(guid)
    if not offer then
        offer = GenerateOffer(player)
        if #offer == 0 then
            player:SendBroadcastMessage(
                "SpellDraft: no quedan hechizos elegibles en el pool bootstrap."
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

local function RestoreDraftedSpells(player)
    if not IsAdventurer(player) then
        return
    end

    local guid = player:GetGUIDLow()
    local query = CharDBQuery(
        "SELECT spell_id FROM spelldraft_drafted_spells " ..
        "WHERE player_guid = " .. guid .. " ORDER BY draft_index"
    )
    if not query then
        return
    end

    repeat
        local spellId = query:GetUInt32(0)
        if spellId > 0 and not player:HasSpell(spellId) then
            player:LearnSpell(spellId)
        end
    until not query:NextRow()
end

local function AcceptPick(player, spellId)
    if not IsAdventurer(player) then
        return
    end

    local guid = player:GetGUIDLow()
    local offer = LoadPendingOffer(guid)
    if not OfferContains(offer, spellId) then
        player:SendBroadcastMessage("SpellDraft: esa carta no pertenece a tu oferta actual.")
        EnsureAndSendOffer(player)
        return
    end

    if DraftsRemaining(player) <= 0 then
        ClearPendingOffer(guid)
        player:SendAddonMessage("SpellChoiceClose", "", 0, player)
        return
    end

    local draftIndex = CountDrafted(guid) + 1
    local level = player:GetLevel() or 1

    CharDBExecute(string.format(
        "INSERT IGNORE INTO spelldraft_drafted_spells " ..
        "(player_guid, spell_id, draft_index, picked_level) VALUES (%u, %u, %u, %u)",
        guid, spellId, draftIndex, level
    ))

    if not player:HasSpell(spellId) then
        player:LearnSpell(spellId)
        -- Same harmless spellbook refresh used by the historical implementation.
        player:CastSpell(player, 24312, true)
        player:RemoveAura(24312)
    end

    ClearPendingOffer(guid)
    SendCompatibilityState(player)

    if DraftsRemaining(player) > 0 then
        EnsureAndSendOffer(player)
    else
        player:SendAddonMessage("SpellChoiceClose", "", 0, player)
    end
end

local function OnProtocolWhisper(_, player, msg, _, _, _)
    if not IsAdventurer(player) or not msg then
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

    -- Phase 1 deliberately has no rerolls/bans. Keep the old client stable by
    -- explicitly denying those requests instead of silently doing nothing.
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
    RestoreDraftedSpells(player)
end

local function OnLevelChanged(_, player)
    if not IsAdventurer(player) then
        return
    end

    local guid = player:GetGUIDLow()
    CreateLuaEvent(function()
        local current = GetPlayerByGUID(guid)
        if current and current:IsInWorld() and IsAdventurer(current) then
            EnsureAndSendOffer(current)
        end
    end, 1000, 1)
end

RegisterPlayerEvent(19, OnProtocolWhisper) -- PLAYER_EVENT_ON_WHISPER
RegisterPlayerEvent(3, OnLogin)            -- PLAYER_EVENT_ON_LOGIN
RegisterPlayerEvent(13, OnLevelChanged)    -- PLAYER_EVENT_ON_LEVEL_CHANGE

print("[Aventureros de Azeroth] Minimal SpellDraft offer/pick engine loaded.")

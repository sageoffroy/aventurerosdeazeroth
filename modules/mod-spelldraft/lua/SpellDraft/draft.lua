-- Native Adventurer SpellDraft loop.
--
-- The protocol/persistence layer is intentionally independent from the old
-- prestige implementation. The ability pool itself is generated from the live
-- WotLK DBCs plus the curated rarity/class metadata from the historical addon.

local CLASS_ADVENTURER = 10
local CUSTOM_SPELL_OFFSET = 200000
local CUSTOM_SPELL_MAX = 299999
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

-- Gameplay tuning belongs in SpellDraft.conf, not in the Lua implementation.
local SPELLDRAFT_ENABLED = ConfigBoolean("SpellDraft.Enable", true)

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

local STARTING_REROLLS = ConfigNumber("SpellDraft.StartingRerolls", 3, 0, 10000, true)
local STARTING_BANS = ConfigNumber("SpellDraft.StartingBans", 3, 0, 10000, true)
local REROLLS_PER_LEVEL = ConfigNumber("SpellDraft.RerollsPerLevel", 0, 0, 1000, true)
local BANS_PER_LEVEL = ConfigNumber("SpellDraft.BansPerLevel", 0, 0, 1000, true)

local PROTECTION_ENABLED = ConfigBoolean("SpellDraft.Protection.Enable", true)
local STARTING_PROTECTIONS = ConfigNumber(
    "SpellDraft.StartingProtections", 3, 0, 10000, true
)
local PROTECTIONS_PER_DRAFT = ConfigNumber(
    "SpellDraft.ProtectionPerDraft", 0, 0, 1000, true
)

local OFFER_SIZE = ConfigNumber(
    "SpellDraft.OfferSize", 5, 1, MAX_PERSISTED_OFFER_SIZE, true
)
local LOW_LEVEL_POOL_FLOOR = ConfigNumber(
    "SpellDraft.LowLevelPoolFloor", 20, 1, 80, true
)

local scriptPath = debug.getinfo(1).source:sub(2)
local parentPath = scriptPath:match("(.+[/\\])") or ""
if not SpellDraftCatalog then
    dofile(parentPath .. "catalog.lua")
end

local SPELL_POOL = SpellDraftCatalog or {}
local TEACH_MAP = SpellDraftTeachMap or {}
local TEACH_TEAM_MAP = SpellDraftTeachTeamMap or {}
local GENERATED_RARITY_DISTRIBUTION = SpellDraftRarityDistribution or {
    [0] = 70.0,
    [1] = 20.0,
    [2] = 7.0,
    [3] = 2.5,
    [4] = 0.5,
}
local RARITY_DISTRIBUTION = {
    [0] = ConfigNumber(
        "SpellDraft.Rarity.Common",
        GENERATED_RARITY_DISTRIBUTION[0] or 70.0,
        0,
        nil,
        false
    ),
    [1] = ConfigNumber(
        "SpellDraft.Rarity.Uncommon",
        GENERATED_RARITY_DISTRIBUTION[1] or 20.0,
        0,
        nil,
        false
    ),
    [2] = ConfigNumber(
        "SpellDraft.Rarity.Rare",
        GENERATED_RARITY_DISTRIBUTION[2] or 7.0,
        0,
        nil,
        false
    ),
    [3] = ConfigNumber(
        "SpellDraft.Rarity.Epic",
        GENERATED_RARITY_DISTRIBUTION[3] or 2.5,
        0,
        nil,
        false
    ),
    [4] = ConfigNumber(
        "SpellDraft.Rarity.Legendary",
        GENERATED_RARITY_DISTRIBUTION[4] or 0.5,
        0,
        nil,
        false
    ),
}

if #SPELL_POOL == 0 then
    error("SpellDraft real catalog is empty or missing")
end

local POOL_BY_ID = {}
for _, entry in ipairs(SPELL_POOL) do
    POOL_BY_ID[entry.id] = entry
end

local TAUGHT_ROOTS = {}
for _, taught in pairs(TEACH_MAP) do
    for _, nativeRoot in ipairs(taught) do
        TAUGHT_ROOTS[nativeRoot] = true
    end
end
for _, taughtByTeam in pairs(TEACH_TEAM_MAP) do
    for _, taught in pairs(taughtByTeam) do
        for _, nativeRoot in ipairs(taught) do
            TAUGHT_ROOTS[nativeRoot] = true
        end
    end
end

local function NativeRootForRuntimeId(spellId)
    if spellId >= CUSTOM_SPELL_OFFSET and spellId <= CUSTOM_SPELL_MAX then
        return spellId - CUSTOM_SPELL_OFFSET
    end
    return spellId
end

local function EntryForNativeRoot(nativeRoot)
    return POOL_BY_ID[nativeRoot]
        or POOL_BY_ID[CUSTOM_SPELL_OFFSET + nativeRoot]
end

local function IsTaughtEntry(entry)
    return entry and TAUGHT_ROOTS[NativeRootForRuntimeId(entry.id)] == true
end

local function ListContains(values, expected)
    for _, value in ipairs(values or {}) do
        if value == expected then
            return true
        end
    end
    return false
end

local function EligibilityRulesMet(player, entry)
    if not player or not entry then
        return false
    end

    local races = entry.races or {}
    if #races > 0 and not ListContains(races, player:GetRace()) then
        return false
    end

    local teams = entry.teams or {}
    if #teams > 0 and not ListContains(teams, player:GetTeam()) then
        return false
    end

    return true
end

local function TaughtRootsForPlayer(player, nativeRoot)
    local roots = {}
    local seen = {}

    local function Append(values)
        for _, taughtRoot in ipairs(values or {}) do
            if not seen[taughtRoot] then
                seen[taughtRoot] = true
                table.insert(roots, taughtRoot)
            end
        end
    end

    Append(TEACH_MAP[nativeRoot])

    local byTeam = TEACH_TEAM_MAP[nativeRoot]
    if byTeam and player then
        Append(byTeam[player:GetTeam()])
    end

    return roots
end

-- ALE database Execute calls are queued. Keep authoritative per-session caches
-- so fast picks cannot race the async INSERT/REPLACE before the next offer is
-- generated. The character DB remains the persistent source across logins.
local draftedCache = {}
local pendingOfferCache = {}
local pendingOfferLoaded = {}
local draftResourceCache = {}
local bannedSpellCache = {}

math.randomseed(os.time())
math.random()
math.random()
math.random()

local function IsBotPlayer(player)
    return player and player.IsBot ~= nil and player:IsBot()
end

local function IsAdventurer(player)
    return SPELLDRAFT_ENABLED
        and player
        and player:GetClass() == CLASS_ADVENTURER
        and not IsBotPlayer(player)
end

local function ExpectedDrafts(player)
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

local function SaveDraftResources(guid, state)
    draftResourceCache[guid] = state

    CharDBExecute(string.format(
        "UPDATE spelldraft_draft_resources SET " ..
        "rerolls_left = %u, bans_left = %u, resource_level = %u, " ..
        "protections_left = %u, protected_spell_id = %u, " ..
        "protection_drafts_awarded = %u, protection_initialized = %u " ..
        "WHERE player_guid = %u",
        state.rerolls,
        state.bans,
        state.resourceLevel,
        state.protections,
        state.protectedSpellId,
        state.protectionDraftsAwarded,
        state.protectionInitialized,
        guid
    ))
end

local function LoadDraftResources(player, force)
    local guid = player:GetGUIDLow()
    if draftResourceCache[guid] and not force then
        return draftResourceCache[guid]
    end

    local currentLevel = math.max(1, player:GetLevel() or 1)
    local currentExpectedDrafts = ExpectedDrafts(player)
    local state = {
        rerolls = STARTING_REROLLS,
        bans = STARTING_BANS,
        resourceLevel = currentLevel,
        protections = STARTING_PROTECTIONS,
        protectedSpellId = 0,
        protectionDraftsAwarded = currentExpectedDrafts,
        protectionInitialized = 1,
    }

    local query = CharDBQuery(
        "SELECT rerolls_left, bans_left, resource_level, protections_left, " ..
        "protected_spell_id, protection_drafts_awarded, protection_initialized " ..
        "FROM spelldraft_draft_resources WHERE player_guid = " .. guid
    )

    if query then
        state.rerolls = query:GetUInt32(0)
        state.bans = query:GetUInt32(1)
        state.resourceLevel = math.max(1, query:GetUInt32(2))
        state.protections = query:GetUInt32(3)
        state.protectedSpellId = query:GetUInt32(4)
        state.protectionDraftsAwarded = query:GetUInt32(5)
        state.protectionInitialized = query:GetUInt32(6)

        -- Existing characters from before the protection feature receive the
        -- configured starting stock once, without retroactive per-draft gains.
        if state.protectionInitialized == 0 then
            state.protections = STARTING_PROTECTIONS
            state.protectedSpellId = 0
            state.protectionDraftsAwarded = currentExpectedDrafts
            state.protectionInitialized = 1
            draftResourceCache[guid] = state
            SaveDraftResources(guid, state)
        end
    else
        CharDBExecute(string.format(
            "INSERT IGNORE INTO spelldraft_draft_resources " ..
            "(player_guid, rerolls_left, bans_left, resource_level, " ..
            "protections_left, protected_spell_id, protection_drafts_awarded, " ..
            "protection_initialized) VALUES (%u, %u, %u, %u, %u, 0, %u, 1)",
            guid,
            STARTING_REROLLS,
            STARTING_BANS,
            currentLevel,
            STARTING_PROTECTIONS,
            currentExpectedDrafts
        ))
    end

    draftResourceCache[guid] = state
    return state
end

local function GrantProgressionResources(player)
    local guid = player:GetGUIDLow()
    local state = LoadDraftResources(player, false)
    local currentLevel = math.max(1, player:GetLevel() or 1)
    local changed = false

    if currentLevel > state.resourceLevel then
        local gainedLevels = currentLevel - state.resourceLevel
        state.rerolls = state.rerolls + gainedLevels * REROLLS_PER_LEVEL
        state.bans = state.bans + gainedLevels * BANS_PER_LEVEL
        state.resourceLevel = currentLevel
        changed = true
    end

    local currentExpectedDrafts = ExpectedDrafts(player)
    if currentExpectedDrafts > state.protectionDraftsAwarded then
        local gainedDrafts = currentExpectedDrafts - state.protectionDraftsAwarded
        if PROTECTION_ENABLED then
            state.protections = state.protections
                + gainedDrafts * PROTECTIONS_PER_DRAFT
        end
        state.protectionDraftsAwarded = currentExpectedDrafts
        changed = true
    end

    if changed then
        SaveDraftResources(guid, state)
    end
    return state
end

local function LoadBannedState(guid, force)
    if bannedSpellCache[guid] and not force then
        return bannedSpellCache[guid]
    end

    local state = {
        set = {},
        list = {},
    }

    local query = CharDBQuery(
        "SELECT spell_id FROM spelldraft_banned_spells " ..
        "WHERE player_guid = " .. guid .. " ORDER BY spell_id"
    )

    if query then
        repeat
            local spellId = query:GetUInt32(0)
            if spellId > 0 and not state.set[spellId] then
                state.set[spellId] = true
                table.insert(state.list, spellId)
            end
        until not query:NextRow()
    end

    bannedSpellCache[guid] = state
    return state
end

local function BannedListString(state)
    local values = {}
    for _, spellId in ipairs(state.list or {}) do
        table.insert(values, tostring(spellId))
    end
    return table.concat(values, ",")
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
        "SELECT offer_1, offer_2, offer_3, offer_4, offer_5, offer_size " ..
        "FROM spelldraft_pending_offer WHERE player_guid = " .. guid
    )
    if not query then
        return nil
    end

    local storedOfferSize = query:GetUInt32(5)
    if storedOfferSize ~= OFFER_SIZE then
        return nil
    end

    local offer = {}
    for column = 0, MAX_PERSISTED_OFFER_SIZE - 1 do
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
    local four = offer[4] or 0
    local five = offer[5] or 0
    local level = player:GetLevel() or 1

    pendingOfferLoaded[guid] = true
    pendingOfferCache[guid] = offer

    CharDBExecute(string.format(
        "REPLACE INTO spelldraft_pending_offer " ..
        "(player_guid, offer_1, offer_2, offer_3, offer_4, offer_5, " ..
        "offer_size, offered_level) " ..
        "VALUES (%u, %u, %u, %u, %u, %u, %u, %u)",
        guid, one, two, three, four, five, OFFER_SIZE, level
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

local function AddCapabilitiesFromEntry(player, entry, capabilities, visited)
    if not entry or visited[entry.id] then
        return
    end

    visited[entry.id] = true

    for _, capability in ipairs(entry.grants or {}) do
        capabilities[capability] = true
    end

    local nativeRoot = NativeRootForRuntimeId(entry.id)
    for _, taughtRoot in ipairs(TaughtRootsForPlayer(player, nativeRoot)) do
        AddCapabilitiesFromEntry(
            player,
            EntryForNativeRoot(taughtRoot),
            capabilities,
            visited
        )
    end
end

local function BuildCapabilities(player, state)
    local capabilities = {}
    local visited = {}

    for spellId, _ in pairs(state.set or {}) do
        AddCapabilitiesFromEntry(
            player,
            POOL_BY_ID[spellId],
            capabilities,
            visited
        )
    end

    return capabilities
end

-- Multiple requires tags are alternatives. Any one capability unlocks the card.
local function RequirementsMet(entry, capabilities)
    local requirements = entry.requires or {}
    if #requirements == 0 then
        return true
    end

    for _, capability in ipairs(requirements) do
        if capabilities[capability] then
            return true
        end
    end
    return false
end

local function RollRarity()
    local total = 0.0
    for rarity = 0, 4 do
        total = total + (RARITY_DISTRIBUTION[rarity] or 0)
    end

    if total <= 0 then
        return 0
    end

    local roll = math.random() * total
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

local function BuildCandidates(player, excluded, allowExcludedSpellId)
    excluded = excluded or {}

    local guid = player:GetGUIDLow()
    local state = LoadDraftedState(guid, false)
    local banned = LoadBannedState(guid, false)
    local capabilities = BuildCapabilities(player, state)
    local queryLevel = EligibilityLevel(player)
    local candidates = {}

    for _, entry in ipairs(SPELL_POOL) do
        local excludedByOffer = excluded[entry.id]
            and entry.id ~= allowExcludedSpellId

        if entry.minLevel <= queryLevel
            and not IsTaughtEntry(entry)
            and EligibilityRulesMet(player, entry)
            and RequirementsMet(entry, capabilities)
            and not state.set[entry.id]
            and not banned.set[entry.id]
            and not excludedByOffer
            and not PlayerHasAnyRank(player, entry) then
            table.insert(candidates, entry)
        end
    end

    return candidates
end

local function GenerateOffer(player, excluded, forcedSpellId)
    forcedSpellId = tonumber(forcedSpellId) or 0
    local candidates = BuildCandidates(
        player,
        excluded,
        forcedSpellId > 0 and forcedSpellId or nil
    )

    local offer = {}
    local picked = {}
    local forcedIncluded = false

    if forcedSpellId > 0 then
        for _, entry in ipairs(candidates) do
            if entry.id == forcedSpellId then
                picked[entry.id] = true
                table.insert(offer, entry.id)
                forcedIncluded = true
                break
            end
        end
    end

    local take = math.min(OFFER_SIZE, #candidates)
    while #offer < take do
        local entry = PickCandidate(candidates, picked, RollRarity())
        if not entry then
            break
        end
        picked[entry.id] = true
        table.insert(offer, entry.id)
    end

    return offer, forcedIncluded
end

local function SendCompatibilityState(player)
    local guid = player:GetGUIDLow()
    local resources = GrantProgressionResources(player)
    local banned = LoadBannedState(guid, false)

    player:SendAddonMessage("SpellChoiceStatus", "prestiged", 0, player)
    player:SendAddonMessage(
        "SpellChoiceBansLeft", tostring(resources.bans), 0, player
    )
    player:SendAddonMessage(
        "SpellChoiceBans", BannedListString(banned), 0, player
    )
    player:SendAddonMessage(
        "SpellChoiceRerolls", tostring(resources.rerolls), 0, player
    )
    player:SendAddonMessage("SpellChoiceUnlimitedReroll", "0", 0, player)
    player:SendAddonMessage(
        "SpellChoiceProtectionEnabled",
        PROTECTION_ENABLED and "1" or "0",
        0,
        player
    )
    player:SendAddonMessage(
        "SpellChoiceProtections", tostring(resources.protections), 0, player
    )
    player:SendAddonMessage(
        "SpellChoiceProtected", tostring(resources.protectedSpellId), 0, player
    )
    player:SendAddonMessage(
        "SpellChoiceDrafts", tostring(DraftsRemaining(player)), 0, player
    )
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
    player:SendAddonMessage(
        "SpellChoiceRarities", table.concat(rarityParts, ","), 0, player
    )
    player:SendAddonMessage(
        "SpellChoiceClasses", table.concat(classParts, ","), 0, player
    )
end

local function OfferIsCurrent(player, offer)
    if not offer or #offer == 0 then
        return false
    end

    local guid = player:GetGUIDLow()
    local state = LoadDraftedState(guid, false)
    local banned = LoadBannedState(guid, false)
    local capabilities = BuildCapabilities(player, state)

    for _, spellId in ipairs(offer) do
        local entry = POOL_BY_ID[spellId]
        if not entry
            or IsTaughtEntry(entry)
            or not EligibilityRulesMet(player, entry)
            or state.set[spellId]
            or banned.set[spellId]
            or not RequirementsMet(entry, capabilities) then
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
        local resources = GrantProgressionResources(player)
        if resources.protectedSpellId > 0 then
            resources.protections = resources.protections + 1
            resources.protectedSpellId = 0
            SaveDraftResources(player:GetGUIDLow(), resources)
            SendCompatibilityState(player)
        end
        ClearPendingOffer(player:GetGUIDLow())
        player:SendAddonMessage("SpellChoiceClose", "", 0, player)
        return
    end

    local guid = player:GetGUIDLow()
    local offer = LoadPendingOffer(guid, false)
    if not OfferIsCurrent(player, offer) then
        ClearPendingOffer(guid)

        local resources = GrantProgressionResources(player)
        local forcedSpellId = PROTECTION_ENABLED
            and resources.protectedSpellId
            or 0
        local forcedIncluded
        offer, forcedIncluded = GenerateOffer(player, nil, forcedSpellId)

        if #offer == 0 then
            if forcedSpellId > 0 then
                resources.protections = resources.protections + 1
                resources.protectedSpellId = 0
                SaveDraftResources(guid, resources)
                SendCompatibilityState(player)
            end
            player:SendBroadcastMessage(
                "SpellDraft: no quedan habilidades elegibles en el catalogo real."
            )
            player:SendAddonMessage("SpellChoiceClose", "", 0, player)
            return
        end

        SavePendingOffer(player, offer)

        -- A protected card is held only until the next real draft offer. Once
        -- it has been delivered, the hold is consumed and the card is normal.
        if forcedSpellId > 0 then
            if not forcedIncluded then
                resources.protections = resources.protections + 1
            end
            resources.protectedSpellId = 0
            SaveDraftResources(guid, resources)
            SendCompatibilityState(player)
        end
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

local function LearnEntryRanks(player, entry)
    if not entry then
        return
    end

    if not player:HasSpell(entry.id) then
        player:LearnSpell(entry.id)
    end

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

local function LearnDraftedEntry(player, entry)
    if not entry then
        return
    end

    local visited = {}

    local function LearnRecursive(current)
        if not current or visited[current.id] then
            return
        end

        visited[current.id] = true
        LearnEntryRanks(player, current)

        local nativeRoot = NativeRootForRuntimeId(current.id)
        for _, taughtRoot in ipairs(TaughtRootsForPlayer(player, nativeRoot)) do
            local taughtEntry = EntryForNativeRoot(taughtRoot)

            if taughtEntry then
                LearnRecursive(taughtEntry)
            elseif not player:HasSpell(taughtRoot) then
                player:LearnSpell(taughtRoot)
            end
        end
    end

    LearnRecursive(entry)
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
        player:SendBroadcastMessage(
            "SpellDraft: esa carta no pertenece a tu oferta actual."
        )
        EnsureAndSendOffer(player)
        return
    end

    local entry = POOL_BY_ID[spellId]
    if not entry or IsTaughtEntry(entry) then
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

    local capabilities = BuildCapabilities(player, state)
    if not EligibilityRulesMet(player, entry)
        or not RequirementsMet(entry, capabilities) then
        ClearPendingOffer(guid)
        EnsureAndSendOffer(player)
        return
    end

    if DraftsRemaining(player) <= 0 then
        ClearPendingOffer(guid)
        player:SendAddonMessage("SpellChoiceClose", "", 0, player)
        return
    end

    local resources = GrantProgressionResources(player)
    if resources.protectedSpellId == spellId then
        -- Picking the protected card itself consumes the protection normally;
        -- there is nothing left to carry into the next offer.
        resources.protectedSpellId = 0
        SaveDraftResources(guid, resources)
    end

    local draftIndex = state.count + 1
    local level = player:GetLevel() or 1

    state.set[spellId] = true
    state.count = draftIndex

    CharDBExecute(string.format(
        "INSERT IGNORE INTO spelldraft_drafted_spells " ..
        "(player_guid, spell_id, draft_index, picked_level) " ..
        "VALUES (%u, %u, %u, %u)",
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
        resources = GrantProgressionResources(player)
        if resources.protectedSpellId > 0 then
            resources.protections = resources.protections + 1
            resources.protectedSpellId = 0
            SaveDraftResources(guid, resources)
            SendCompatibilityState(player)
        end
        player:SendAddonMessage("SpellChoiceClose", "", 0, player)
    end
end

local function HandleReroll(player)
    local guid = player:GetGUIDLow()
    local resources = GrantProgressionResources(player)

    if resources.rerolls <= 0 then
        player:SendAddonMessage("SpellChoiceRerollDenied", "0", 0, player)
        return
    end

    local oldOffer = LoadPendingOffer(guid, false)
    if not oldOffer or #oldOffer == 0 then
        EnsureAndSendOffer(player)
        return
    end

    local excluded = {}
    for _, spellId in ipairs(oldOffer) do
        excluded[spellId] = true
    end

    -- Protection also pins the card through rerolls, but the protection itself
    -- is not consumed until a draft pick advances to the next selection.
    local forcedSpellId = PROTECTION_ENABLED
        and resources.protectedSpellId
        or 0
    local newOffer = GenerateOffer(player, excluded, forcedSpellId)

    if #newOffer == 0 then
        newOffer = GenerateOffer(player, nil, forcedSpellId)
    end

    if #newOffer == 0 then
        EnsureAndSendOffer(player)
        return
    end

    resources.rerolls = resources.rerolls - 1
    SaveDraftResources(guid, resources)

    SavePendingOffer(player, newOffer)
    SendCompatibilityState(player)
    SendOffer(player, newOffer)
end

local function HandleBan(player, spellId)
    local guid = player:GetGUIDLow()
    local resources = GrantProgressionResources(player)
    local banned = LoadBannedState(guid, false)
    local offer = LoadPendingOffer(guid, false)

    if resources.protectedSpellId == spellId then
        player:SendAddonMessage("SpellChoiceBanDenied", "protected", 0, player)
        return
    end

    if resources.bans <= 0
        or not OfferContains(offer, spellId)
        or banned.set[spellId] then
        player:SendAddonMessage("SpellChoiceBanDenied", "0", 0, player)
        return
    end

    banned.set[spellId] = true
    table.insert(banned.list, spellId)

    CharDBExecute(string.format(
        "INSERT IGNORE INTO spelldraft_banned_spells " ..
        "(player_guid, spell_id) VALUES (%u, %u)",
        guid, spellId
    ))

    resources.bans = resources.bans - 1
    SaveDraftResources(guid, resources)

    SendCompatibilityState(player)
    player:SendAddonMessage(
        "SpellChoiceBanAccepted", tostring(spellId), 0, player
    )
end

local function HandleReplaceBanned(player)
    local guid = player:GetGUIDLow()
    local offer = LoadPendingOffer(guid, false)

    if not offer or #offer == 0 then
        EnsureAndSendOffer(player)
        return
    end

    local banned = LoadBannedState(guid, false)
    local excluded = {}

    for _, spellId in ipairs(offer) do
        if not banned.set[spellId] then
            excluded[spellId] = true
        end
    end

    local candidates = BuildCandidates(player, excluded)
    local picked = {}
    local replacement = {}

    for _, spellId in ipairs(offer) do
        if banned.set[spellId] then
            local entry = PickCandidate(candidates, picked, RollRarity())
            if entry then
                picked[entry.id] = true
                table.insert(replacement, entry.id)
            end
        else
            table.insert(replacement, spellId)
        end
    end

    if #replacement == 0 then
        ClearPendingOffer(guid)
        EnsureAndSendOffer(player)
        return
    end

    SavePendingOffer(player, replacement)
    SendCompatibilityState(player)
    SendOffer(player, replacement)
end

local function HandleProtect(player, spellId)
    if not PROTECTION_ENABLED then
        player:SendAddonMessage("SpellChoiceProtectDenied", "disabled", 0, player)
        return
    end

    -- Protection is meaningful only when another draft remains after the
    -- current pick. Prevent wasting the final protection on the last choice.
    if DraftsRemaining(player) <= 1 then
        player:SendAddonMessage("SpellChoiceProtectDenied", "last", 0, player)
        return
    end

    local guid = player:GetGUIDLow()
    local offer = LoadPendingOffer(guid, false)
    local banned = LoadBannedState(guid, false)
    if not OfferContains(offer, spellId) or banned.set[spellId] then
        player:SendAddonMessage("SpellChoiceProtectDenied", "invalid", 0, player)
        return
    end

    local resources = GrantProgressionResources(player)

    if resources.protectedSpellId == spellId then
        -- Clicking the active protection again cancels it and refunds the use.
        resources.protectedSpellId = 0
        resources.protections = resources.protections + 1
    elseif resources.protectedSpellId > 0 then
        -- Moving an already-paid protection to another card costs nothing.
        resources.protectedSpellId = spellId
    elseif resources.protections > 0 then
        resources.protections = resources.protections - 1
        resources.protectedSpellId = spellId
    else
        player:SendAddonMessage("SpellChoiceProtectDenied", "empty", 0, player)
        return
    end

    SaveDraftResources(guid, resources)
    SendCompatibilityState(player)
end

local function OnProtocolWhisper(_, player, msg, _, _, receiver)
    if not IsAdventurer(player) or not msg then
        return
    end

    if receiver and receiver:GetGUIDLow() ~= player:GetGUIDLow() then
        return
    end

    if AventurerosTalentDraft
        and AventurerosTalentDraft.HandleProtocolMessage(player, msg) then
        return false
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

    if msg == "SC_REROLL" then
        HandleReroll(player)
        return false
    end

    local bannedSpellId = msg:match("^SC_BAN:(%d+)$")
    if bannedSpellId then
        HandleBan(player, tonumber(bannedSpellId))
        return false
    end

    local protectedSpellId = msg:match("^SC_PROTECT:(%d+)$")
    if protectedSpellId then
        HandleProtect(player, tonumber(protectedSpellId))
        return false
    end

    if msg == "SC_REPLACE_BANNED" then
        HandleReplaceBanned(player)
        return false
    end
end

local function OnLogin(_, player)
    if not IsAdventurer(player) then
        return
    end

    local guid = player:GetGUIDLow()
    LoadDraftedState(guid, true)
    LoadDraftResources(player, true)
    GrantProgressionResources(player)
    LoadBannedState(guid, true)
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
    draftResourceCache[guid] = nil
    bannedSpellCache[guid] = nil
end

local function OnLevelChanged(_, player)
    if not IsAdventurer(player) then
        return
    end

    GrantProgressionResources(player)
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

print(string.format(
    "[Aventureros de Azeroth] Real SpellDraft engine loaded: %u root abilities, " ..
    "%u starting drafts, first extra at level %u, every %u level(s), " ..
    "%u rerolls, %u bans, %u protections, %u-card offers.",
    #SPELL_POOL,
    STARTING_DRAFTS,
    FIRST_ADDITIONAL_DRAFT_LEVEL,
    LEVELS_PER_DRAFT,
    STARTING_REROLLS,
    STARTING_BANS,
    STARTING_PROTECTIONS,
    OFFER_SIZE
))

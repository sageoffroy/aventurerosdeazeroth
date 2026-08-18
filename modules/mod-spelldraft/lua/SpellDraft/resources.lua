-- SpellDraft resource pools for the native Adventurer class.
--
-- Adventurer itself stays a normal class-10 container. SpellDraft owns the
-- classless resource behavior so abilities can consume mana, rage, energy or
-- runic power regardless of the character's original class identity.

local CLASS_ADVENTURER = 10
local POWER_MANA = 0
local POWER_RAGE = 1
local POWER_ENERGY = 3
local POWER_RUNIC_POWER = 6

local RAGE_MAX = 1000        -- 100 Rage in the WotLK UI (x10 internal scale)
local ENERGY_MAX = 100       -- 1:1 scale
local RUNIC_POWER_MAX = 1000 -- 100 Runic Power in the WotLK UI (x10 scale)
local PRIMARY_POWER = POWER_RAGE
local TICK_INTERVAL_MS = 2000

local LANGUAGE_COMMON = 98
local LANGUAGE_ORCISH = 109
local LANGUAGE_DWARVEN = 111
local LANGUAGE_DARNASSIAN = 113
local LANGUAGE_TAURAHE = 115
local LANGUAGE_THALASSIAN = 137
local LANGUAGE_GNOMISH = 313
local LANGUAGE_TROLL = 315
local LANGUAGE_GUTTERSPEAK = 673
local LANGUAGE_DRAENEI = 759

local tickerByGuid = {}

local function IsAdventurer(player)
    return player and player:GetClass() == CLASS_ADVENTURER
end

local function SetLanguageSkill(player, skillId)
    player:SetSkill(skillId, 1, 300, 300)
end

local function EnsurePlayerLanguages(player)
    if not IsAdventurer(player) then
        return
    end

    local race = player:GetRace()

    if race == 1 then -- Human
        SetLanguageSkill(player, LANGUAGE_COMMON)
    elseif race == 2 then -- Orc
        SetLanguageSkill(player, LANGUAGE_ORCISH)
    elseif race == 3 then -- Dwarf
        SetLanguageSkill(player, LANGUAGE_COMMON)
        SetLanguageSkill(player, LANGUAGE_DWARVEN)
    elseif race == 4 then -- Night Elf
        SetLanguageSkill(player, LANGUAGE_COMMON)
        SetLanguageSkill(player, LANGUAGE_DARNASSIAN)
    elseif race == 5 then -- Undead
        SetLanguageSkill(player, LANGUAGE_ORCISH)
        SetLanguageSkill(player, LANGUAGE_GUTTERSPEAK)
    elseif race == 6 then -- Tauren
        SetLanguageSkill(player, LANGUAGE_ORCISH)
        SetLanguageSkill(player, LANGUAGE_TAURAHE)
    elseif race == 7 then -- Gnome
        SetLanguageSkill(player, LANGUAGE_COMMON)
        SetLanguageSkill(player, LANGUAGE_GNOMISH)
    elseif race == 8 then -- Troll
        SetLanguageSkill(player, LANGUAGE_ORCISH)
        SetLanguageSkill(player, LANGUAGE_TROLL)
    elseif race == 10 then -- Blood Elf
        SetLanguageSkill(player, LANGUAGE_ORCISH)
        SetLanguageSkill(player, LANGUAGE_THALASSIAN)
    elseif race == 11 then -- Draenei
        SetLanguageSkill(player, LANGUAGE_COMMON)
        SetLanguageSkill(player, LANGUAGE_DRAENEI)
    end
end

local function ApplyResourcePools(player)
    if not IsAdventurer(player) or not player:IsInWorld() then
        return
    end

    player:SetMaxPower(POWER_RAGE, RAGE_MAX)
    player:SetMaxPower(POWER_ENERGY, ENERGY_MAX)
    player:SetMaxPower(POWER_RUNIC_POWER, RUNIC_POWER_MAX)

    -- Keep the historical SpellDraft mana curve. Mana remains available even
    -- though Rage is the visible primary resource.
    local intellect = player:GetStat(3) or 20
    local level = player:GetLevel() or 1
    local customMana = 150 + level * 50 + intellect * 15

    if player:GetMaxPower(POWER_MANA) < customMana then
        player:SetMaxPower(POWER_MANA, customMana)
        player:SetPower(customMana, POWER_MANA)
    end

    if player:GetPowerType() ~= PRIMARY_POWER then
        player:SetPowerType(PRIMARY_POWER)
    end
end

local function StopTicker(guid)
    local eventId = tickerByGuid[guid]
    if not eventId then
        return
    end

    RemoveEventById(eventId)
    tickerByGuid[guid] = nil
end

local function StartTicker(player)
    if not IsAdventurer(player) then
        return
    end

    local guid = player:GetGUIDLow()
    if tickerByGuid[guid] then
        return
    end

    tickerByGuid[guid] = CreateLuaEvent(function()
        local current = GetPlayerByGUID(guid)
        if not current or not current:IsInWorld() then
            StopTicker(guid)
            return
        end

        if not IsAdventurer(current) then
            StopTicker(guid)
            return
        end

        if current:GetPowerType() ~= PRIMARY_POWER then
            current:SetPowerType(PRIMARY_POWER)
        end
    end, TICK_INTERVAL_MS, 0)
end

local function RebuildResources(_, player)
    if not IsAdventurer(player) then
        return
    end

    EnsurePlayerLanguages(player)
    ApplyResourcePools(player)
    StartTicker(player)
end

local function OnLogin(_, player)
    if not IsAdventurer(player) then
        return
    end

    -- Repair faction/racial language skills immediately. Class 10 does not use
    -- the normal class-start language path, and missing Common/Orcish makes the
    -- client reject addon/chat traffic with "You don't know that language".
    EnsurePlayerLanguages(player)

    local guid = player:GetGUIDLow()
    CreateLuaEvent(function()
        local current = GetPlayerByGUID(guid)
        if not current or not current:IsInWorld() then
            return
        end

        EnsurePlayerLanguages(current)
        ApplyResourcePools(current)
        StartTicker(current)
    end, 2000, 1)
end

local function OnLogout(_, player)
    if not player then
        return
    end

    StopTicker(player:GetGUIDLow())
end

RegisterPlayerEvent(3, OnLogin)           -- PLAYER_EVENT_ON_LOGIN
RegisterPlayerEvent(4, OnLogout)          -- PLAYER_EVENT_ON_LOGOUT
RegisterPlayerEvent(13, RebuildResources) -- PLAYER_EVENT_ON_LEVEL_CHANGE
RegisterPlayerEvent(28, RebuildResources) -- PLAYER_EVENT_ON_MAP_CHANGE
RegisterPlayerEvent(35, RebuildResources) -- PLAYER_EVENT_ON_REPOP
RegisterPlayerEvent(36, RebuildResources) -- PLAYER_EVENT_ON_RESURRECT

print("[Aventureros de Azeroth] SpellDraft resources and language repair loaded for Adventurer class 10.")

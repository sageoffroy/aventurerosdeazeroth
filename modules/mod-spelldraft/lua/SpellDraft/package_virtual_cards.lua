-- Virtual SpellDraft package cards exist only as draft presentation records.
-- The draft loop learns the card before walking its TeachMap, so remove the
-- presentation spell immediately while leaving the drafted-card DB state and
-- all taught abilities intact.

local PLAYER_EVENT_ON_LOGIN = 3
local PLAYER_EVENT_ON_LEARN_SPELL = 44

local VIRTUAL_PACKAGE_SPELLS = {
    [190001] = true, -- Maestro de Portales
}

local function RemoveVirtualPackageSpell(_, player, spellId)
    if not player or not VIRTUAL_PACKAGE_SPELLS[spellId] then
        return
    end

    if player:HasSpell(spellId) then
        player:RemoveSpell(spellId)
    end
end

local function RemoveStaleVirtualPackageSpells(_, player)
    if not player then
        return
    end

    for spellId, _ in pairs(VIRTUAL_PACKAGE_SPELLS) do
        if player:HasSpell(spellId) then
            player:RemoveSpell(spellId)
        end
    end
end

RegisterPlayerEvent(PLAYER_EVENT_ON_LEARN_SPELL, RemoveVirtualPackageSpell)
RegisterPlayerEvent(PLAYER_EVENT_ON_LOGIN, RemoveStaleVirtualPackageSpells)

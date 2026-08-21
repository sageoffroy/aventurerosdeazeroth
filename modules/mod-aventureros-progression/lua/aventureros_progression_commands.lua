-- Aventureros de Azeroth - temporary progression commands.
--
-- AzerothCore routes '.' and '!' commands through ALE's
-- PLAYER_EVENT_ON_COMMAND hook before reporting an unknown command. Use that
-- real command path instead of pretending ordinary chat is a command.

local CLASS_ADVENTURER = 10

local function isBot(player)
    return player and player.IsBot ~= nil and player:IsBot()
end

local function isAdventurer(player)
    return player and player:GetClass() == CLASS_ADVENTURER and not isBot(player)
end

local function normalize(command)
    return (command or ""):gsub("^%s+", ""):gsub("%s+$", "")
end

local function showShop(player)
    local progression = AventurerosProgression
    if not progression or not progression.GetTalentCatalog then
        player:SendBroadcastMessage("[Metaprogresión] El módulo todavía no está disponible.")
        return
    end

    player:SendBroadcastMessage(string.format(
        "[Metaprogresión] Honor de cuenta: %u",
        progression.GetHonor(player)
    ))
    player:SendBroadcastMessage("[Metaprogresión] Familias de talento:")

    for _, entry in ipairs(progression.GetTalentCatalog() or {}) do
        local status
        if entry.starter then
            status = "BÁSICO"
        elseif progression.IsTalentUnlocked(player, entry.id) then
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
        "[Metaprogresión] Comprar: .talentos comprar <id>"
    )
end

local function handleCommand(_, player, command, _)
    if not player or not isAdventurer(player) or not command then
        return
    end

    local cmd = normalize(command)

    if cmd == "talentos" then
        showShop(player)
        return false
    end

    local talentId = cmd:match("^talentos%s+comprar%s+([%w_%-]+)$")
    if talentId then
        if not AventurerosProgression then
            player:SendBroadcastMessage("[Metaprogresión] El módulo todavía no está disponible.")
            return false
        end

        local ok, reason = AventurerosProgression.UnlockTalentWithHonor(player, talentId)
        if ok then
            player:SendBroadcastMessage(
                "[Metaprogresión] Familia desbloqueada para toda la cuenta."
            )
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

        showShop(player)
        return false
    end

    local grant = cmd:match("^talentos%s+darhonor%s+(%d+)$")
    if grant and player:IsGM() then
        if AventurerosProgression then
            local total = AventurerosProgression.GrantHonor(player, tonumber(grant))
            player:SendBroadcastMessage(string.format(
                "[Metaprogresión] TEST: Honor de cuenta = %u",
                total
            ))
        end
        return false
    end

    if cmd == "talentos sincronizar" then
        if AventurerosDungeonRewards and AventurerosDungeonRewards.CheckAccount then
            local reward = AventurerosDungeonRewards.CheckAccount(player)
            player:SendBroadcastMessage(string.format(
                "[Metaprogresión] Sincronización completa. Honor acreditado: %u",
                reward or 0
            ))
        else
            player:SendBroadcastMessage(
                "[Metaprogresión] El adaptador de Dungeon Master todavía no está disponible."
            )
        end
        return false
    end
end

RegisterPlayerEvent(42, handleCommand)

print("[Aventureros de Azeroth] Progression command hook loaded: .talentos")

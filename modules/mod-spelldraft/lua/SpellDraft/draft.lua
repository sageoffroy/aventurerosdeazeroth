-- Aventureros de Azeroth
--
-- Thin integration wrapper around the stable SpellDraft engine.  The original
-- draft implementation is kept byte-for-byte in draft_core.inc; this file only
-- bridges account talent metaprogression into its player-event callbacks.
-- Keeping the bridge small makes future merges from the class-audit branches
-- much less conflict-prone.

local scriptPath = debug.getinfo(1).source:sub(2)
local parentPath = scriptPath:match("(.+[/\\])") or ""

if not SpellDraftTalents then
    dofile(parentPath .. "talents.lua")
end

local NativeRegisterPlayerEvent = RegisterPlayerEvent

local function RegisterWrapped(eventId, callback, shots)
    local wrapped = callback

    if eventId == 18 or eventId == 19 then
        wrapped = function(...)
            local player = select(2, ...)
            local msg = select(3, ...)

            if SpellDraftTalents and player and msg then
                if SpellDraftTalents.HandleChat(player, msg) then
                    return false
                end

                if SpellDraftTalents.HandleProtocolMessage(player, msg) then
                    return false
                end
            end

            local result = callback(...)

            if SpellDraftTalents and player and msg
                and (msg == "SC_CHECK" or msg:match("^SC:%d+$")) then
                SpellDraftTalents.ScheduleMaybeSend(player, 250, 3)
            end

            return result
        end
    elseif eventId == 3 then
        wrapped = function(...)
            local player = select(2, ...)
            local result = callback(...)
            if SpellDraftTalents and player then
                SpellDraftTalents.OnLogin(player)
            end
            return result
        end
    elseif eventId == 4 then
        wrapped = function(...)
            local player = select(2, ...)
            if SpellDraftTalents and player then
                SpellDraftTalents.OnLogout(player)
            end
            return callback(...)
        end
    elseif eventId == 13 then
        wrapped = function(...)
            local player = select(2, ...)
            local result = callback(...)
            if SpellDraftTalents and player then
                SpellDraftTalents.OnLevelChanged(player)
            end
            return result
        end
    end

    if shots ~= nil then
        return NativeRegisterPlayerEvent(eventId, wrapped, shots)
    end
    return NativeRegisterPlayerEvent(eventId, wrapped)
end

RegisterPlayerEvent = RegisterWrapped
local ok, err = pcall(dofile, parentPath .. "draft_core.inc")
RegisterPlayerEvent = NativeRegisterPlayerEvent

if not ok then
    error(err)
end

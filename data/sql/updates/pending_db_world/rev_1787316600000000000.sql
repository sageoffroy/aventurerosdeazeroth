-- Preserve WotLK Rend behavior for the normalized rankless card.
-- The normalized script keeps the native weapon/AP formula and maps the
-- native rank-9+ (>75% health) bonus to its equivalent player-level breakpoint.
DELETE FROM `spell_script_names`
WHERE `spell_id` = 200772
  AND `ScriptName` = 'spell_spelldraft_warr_rend';

INSERT INTO `spell_script_names` (`spell_id`, `ScriptName`)
VALUES (200772, 'spell_spelldraft_warr_rend');

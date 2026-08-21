-- Preserve WotLK Heroic Strike behavior for the normalized rankless card.
-- Explicit normalized bindings take precedence over native-root inheritance.
DELETE FROM `spell_script_names`
WHERE `spell_id` = 200078
  AND `ScriptName` = 'spell_spelldraft_warr_heroic_strike';

INSERT INTO `spell_script_names` (`spell_id`, `ScriptName`)
VALUES (200078, 'spell_spelldraft_warr_heroic_strike');

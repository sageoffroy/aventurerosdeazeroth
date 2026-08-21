-- Preserve native spell_threat semantics for normalized Warrior cards.
-- flatMod is level-dependent and is supplied by spell_spelldraft_warr_flat_threat.
-- pctMod/apPctMod remain static native mechanics and stay in spell_threat so
-- AzerothCore's normal damage/AP threat paths continue to own them.

DELETE FROM `spell_threat`
WHERE `entry` IN (200078, 200845, 201464, 206343, 206572, 207386, 223922, 257755);

INSERT INTO `spell_threat` (`entry`, `flatMod`, `pctMod`, `apPctMod`) VALUES
(200078, 0, 1.00, 0.00),  -- Heroic Strike
(200845, 0, 1.00, 0.00),  -- Cleave
(201464, 0, 1.00, 0.00),  -- Slam
(206343, 0, 1.85, 0.00),  -- Thunder Clap
(206572, 0, 1.00, 0.00),  -- Revenge
(207386, 0, 1.00, 0.05),  -- Sunder Armor
(223922, 0, 1.00, 0.00),  -- Shield Slam
(257755, 0, 1.50, 0.00);  -- Heroic Throw

DELETE FROM `spell_script_names`
WHERE `spell_id` IN (200078, 200845, 201464, 206343, 206572, 207386, 223922, 257755)
  AND `ScriptName` = 'spell_spelldraft_warr_flat_threat';

INSERT INTO `spell_script_names` (`spell_id`, `ScriptName`) VALUES
(200078, 'spell_spelldraft_warr_flat_threat'),
(200845, 'spell_spelldraft_warr_flat_threat'),
(201464, 'spell_spelldraft_warr_flat_threat'),
(206343, 'spell_spelldraft_warr_flat_threat'),
(206572, 'spell_spelldraft_warr_flat_threat'),
(207386, 'spell_spelldraft_warr_flat_threat'),
(223922, 'spell_spelldraft_warr_flat_threat'),
(257755, 'spell_spelldraft_warr_flat_threat');

-- Exact normalized bindings take precedence over native-root fallback. Slam's
-- native family has spell_warr_slam on root -1464, so repeat that binding on
-- the normalized ID alongside the generic flat-threat script.
DELETE FROM `spell_script_names`
WHERE `spell_id` = 201464
  AND `ScriptName` = 'spell_warr_slam';

INSERT INTO `spell_script_names` (`spell_id`, `ScriptName`)
VALUES (201464, 'spell_warr_slam');

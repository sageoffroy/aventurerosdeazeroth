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

-- Execute has a rank-specific DamageMultiplier for extra Rage. The normalized
-- script replaces the native family script so the base effect curve and the
-- damage-per-extra-Rage curve both follow the player's level.
DELETE FROM `spell_script_names`
WHERE `spell_id` = 205308
  AND `ScriptName` IN ('spell_warr_execute', 'spell_spelldraft_warr_execute');

INSERT INTO `spell_script_names` (`spell_id`, `ScriptName`)
VALUES (205308, 'spell_spelldraft_warr_execute');

-- AP coefficients in spell_bonus_data are also keyed by exact native IDs.
-- These four Warrior coefficients are invariant across their native rank
-- families, so copying them to the rankless runtime IDs preserves the WotLK
-- formula without introducing another interpolation path.
DELETE FROM `spell_bonus_data`
WHERE `entry` IN (206343, 206572, 257755, 264382);

INSERT INTO `spell_bonus_data`
(`entry`, `direct_bonus`, `dot_bonus`, `ap_bonus`, `ap_dot_bonus`, `comments`) VALUES
(206343, 0, 0, 0.12, 0, 'Aventureros normalized Warrior - Thunder Clap'),
(206572, 0, 0, 0.31, 0, 'Aventureros normalized Warrior - Revenge'),
(257755, 0, 0, 0.50, 0, 'Aventureros normalized Warrior - Heroic Throw'),
(264382, 0, 0, 0.50, 0, 'Aventureros normalized Warrior - Shattering Throw');

-- Spell-group membership is keyed by exact spell IDs too. Copy the native
-- Warrior roots whose buffs/debuffs participate in exclusive stacking groups.
-- Parent groups that reference these group IDs automatically continue to work.
DELETE FROM `spell_group`
WHERE (`id` = 1003 AND `spell_id` = 206673)
   OR (`id` = 1059 AND `spell_id` = 206343)
   OR (`id` = 1062 AND `spell_id` = 201160)
   OR (`id` = 1091 AND `spell_id` = 200469);

INSERT INTO `spell_group` (`id`, `spell_id`) VALUES
(1003, 206673), -- Battle Shout
(1059, 206343), -- Thunder Clap attack-speed slow
(1062, 201160), -- Demoralizing Shout attack-power reduction
(1091, 200469); -- Commanding Shout stamina/health-buff group

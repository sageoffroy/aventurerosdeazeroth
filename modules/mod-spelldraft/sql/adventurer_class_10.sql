-- Native SpellDraft Adventurer class (CLASS_ADVENTURER = 10).
--
-- World-side creation data for the native class-10 implementation.
-- Spell/racial baselines themselves are installed silently by AdventurerClass.cpp
-- during PLAYERHOOK_ON_CREATE and immediately persisted before first login.

SET @ADVENTURER_CLASS := 10;
SET @ADVENTURER_CLASS_MASK := 512; -- 1 << (10 - 1)

-- ---------------------------------------------------------------------------
-- 1. Valid race/class creation rows
--    playercreateinfo in current AzerothCore contains only race/class, starting
--    map/zone, position and orientation. Character model/display data comes from
--    DBCs and must NOT be written here.
--
--    Reuse each race's Warrior start when available. Blood Elf has no stock
--    Warrior in WotLK 3.3.5a, so use its Paladin starting position instead.
-- ---------------------------------------------------------------------------
DELETE FROM `playercreateinfo` WHERE `class` = @ADVENTURER_CLASS;

INSERT INTO `playercreateinfo`
(`race`, `class`, `map`, `zone`, `position_x`, `position_y`, `position_z`, `orientation`)
SELECT
    src.`race`, @ADVENTURER_CLASS, src.`map`, src.`zone`,
    src.`position_x`, src.`position_y`, src.`position_z`, src.`orientation`
FROM `playercreateinfo` AS src
WHERE
    (src.`class` = 1 AND src.`race` IN (1,2,3,4,5,6,7,8,11))
    OR (src.`class` = 2 AND src.`race` = 10);

-- ---------------------------------------------------------------------------
-- 2. Neutral 1-80 class stats
--    Average the eight normal non-DK classes. Base mana averages only mana
--    users so zero-mana physical classes do not drag the value down.
-- ---------------------------------------------------------------------------
DELETE FROM `player_class_stats` WHERE `Class` = @ADVENTURER_CLASS;

INSERT INTO `player_class_stats`
(`Class`, `Level`, `BaseHP`, `BaseMana`, `Strength`, `Agility`, `Stamina`, `Intellect`, `Spirit`)
SELECT
    @ADVENTURER_CLASS,
    `Level`,
    CAST(ROUND(AVG(`BaseHP`)) AS UNSIGNED),
    CAST(ROUND(AVG(CASE WHEN `Class` IN (2,5,7,8,9,11) THEN `BaseMana` END)) AS UNSIGNED),
    CAST(ROUND(AVG(`Strength`)) AS UNSIGNED),
    CAST(ROUND(AVG(`Agility`)) AS UNSIGNED),
    CAST(ROUND(AVG(`Stamina`)) AS UNSIGNED),
    CAST(ROUND(AVG(`Intellect`)) AS UNSIGNED),
    CAST(ROUND(AVG(`Spirit`)) AS UNSIGNED)
FROM `player_class_stats`
WHERE `Class` IN (2,3,4,5,7,8,9,11)
GROUP BY `Level`;

-- ---------------------------------------------------------------------------
-- 3. Universal equipment/weapon skill lines available to class 10.
--    Racial and language skills remain race-driven through AzerothCore's stock
--    classMask=0 rows.
-- ---------------------------------------------------------------------------
DELETE FROM `playercreateinfo_skills` WHERE `classMask` = @ADVENTURER_CLASS_MASK;

INSERT INTO `playercreateinfo_skills` (`raceMask`, `classMask`, `skill`, `rank`, `comment`) VALUES
(0,512,43,0,'Adventurer - Swords'),
(0,512,44,0,'Adventurer - Axes'),
(0,512,45,0,'Adventurer - Bows'),
(0,512,46,0,'Adventurer - Guns'),
(0,512,54,0,'Adventurer - Maces'),
(0,512,55,0,'Adventurer - Two-Handed Swords'),
(0,512,95,0,'Adventurer - Defense'),
(0,512,136,0,'Adventurer - Staves'),
(0,512,160,0,'Adventurer - Two-Handed Maces'),
(0,512,162,0,'Adventurer - Unarmed'),
(0,512,172,0,'Adventurer - Two-Handed Axes'),
(0,512,173,0,'Adventurer - Daggers'),
(0,512,176,0,'Adventurer - Thrown'),
(0,512,226,0,'Adventurer - Crossbows'),
(0,512,228,0,'Adventurer - Wands'),
(0,512,229,0,'Adventurer - Polearms'),
(0,512,293,0,'Adventurer - Plate Mail'),
(0,512,413,0,'Adventurer - Mail'),
(0,512,414,0,'Adventurer - Leather'),
(0,512,415,0,'Adventurer - Cloth'),
(0,512,433,0,'Adventurer - Shield'),
(0,512,473,0,'Adventurer - Fist Weapons');

-- Clean up any rows from the first class-10 migration draft. The C++ creation
-- hook owns these spells now, which guarantees they are learned while the Player
-- is still out of world regardless of PlayerStart.AllSpells configuration.
DELETE FROM `playercreateinfo_spell_custom` WHERE `classmask` = @ADVENTURER_CLASS_MASK;

-- ---------------------------------------------------------------------------
-- 4. Action bar: deliberately start with Attack only. No Warrior abilities.
-- ---------------------------------------------------------------------------
DELETE FROM `playercreateinfo_action` WHERE `class` = @ADVENTURER_CLASS;

INSERT INTO `playercreateinfo_action` (`race`,`class`,`button`,`action`,`type`)
SELECT `race`, @ADVENTURER_CLASS, 0, 6603, 0
FROM `playercreateinfo`
WHERE `class` = @ADVENTURER_CLASS;

-- ---------------------------------------------------------------------------
-- 5. Neutral DBC-derived class coefficients in the world DB mirrors.
--    Class 10 occupies zero-based class slot 9 in 100-row class blocks
--    (IDs 900..999), and the tenth 32-rating block (IDs 289..320).
-- ---------------------------------------------------------------------------

-- Base agility/intellect crit coefficients. ID is zero-based class slot.
INSERT INTO `gtchancetomeleecritbase_dbc` (`ID`,`Data`)
SELECT 9, AVG(`Data`)
FROM `gtchancetomeleecritbase_dbc`
WHERE `ID` IN (1,2,3,4,6,7,8,10)
ON DUPLICATE KEY UPDATE `Data` = VALUES(`Data`);

INSERT INTO `gtchancetospellcritbase_dbc` (`ID`,`Data`)
SELECT 9, AVG(`Data`)
FROM `gtchancetospellcritbase_dbc`
WHERE `ID` IN (1,2,3,4,6,7,8,10)
ON DUPLICATE KEY UPDATE `Data` = VALUES(`Data`);

-- Agility -> melee/ranged crit curve.
DROP TEMPORARY TABLE IF EXISTS `tmp_adventurer_melee_crit`;
CREATE TEMPORARY TABLE `tmp_adventurer_melee_crit` AS
SELECT MOD(`ID`,100) AS `slot`, AVG(`Data`) AS `Data`
FROM `gtchancetomeleecrit_dbc`
WHERE FLOOR(`ID`/100)+1 IN (2,3,4,5,7,8,9,11)
GROUP BY MOD(`ID`,100);

INSERT INTO `gtchancetomeleecrit_dbc` (`ID`,`Data`)
SELECT 900+`slot`, `Data` FROM `tmp_adventurer_melee_crit`
ON DUPLICATE KEY UPDATE `Data`=VALUES(`Data`);
DROP TEMPORARY TABLE `tmp_adventurer_melee_crit`;

-- Intellect -> spell crit curve.
DROP TEMPORARY TABLE IF EXISTS `tmp_adventurer_spell_crit`;
CREATE TEMPORARY TABLE `tmp_adventurer_spell_crit` AS
SELECT MOD(`ID`,100) AS `slot`, AVG(`Data`) AS `Data`
FROM `gtchancetospellcrit_dbc`
WHERE FLOOR(`ID`/100)+1 IN (2,3,4,5,7,8,9,11)
GROUP BY MOD(`ID`,100);

INSERT INTO `gtchancetospellcrit_dbc` (`ID`,`Data`)
SELECT 900+`slot`, `Data` FROM `tmp_adventurer_spell_crit`
ON DUPLICATE KEY UPDATE `Data`=VALUES(`Data`);
DROP TEMPORARY TABLE `tmp_adventurer_spell_crit`;

-- Combat rating conversion: 32 rows per class, one-based IDs.
DROP TEMPORARY TABLE IF EXISTS `tmp_adventurer_ratings`;
CREATE TEMPORARY TABLE `tmp_adventurer_ratings` AS
SELECT MOD(`ID`-1,32)+1 AS `slot`, AVG(`Data`) AS `Data`
FROM `gtoctclasscombatratingscalar_dbc`
WHERE FLOOR((`ID`-1)/32)+1 IN (2,3,4,5,7,8,9,11)
GROUP BY MOD(`ID`-1,32)+1;

INSERT INTO `gtoctclasscombatratingscalar_dbc` (`ID`,`Data`)
SELECT 288+`slot`, `Data` FROM `tmp_adventurer_ratings`
ON DUPLICATE KEY UPDATE `Data`=VALUES(`Data`);
DROP TEMPORARY TABLE `tmp_adventurer_ratings`;

-- Passive health regeneration.
DROP TEMPORARY TABLE IF EXISTS `tmp_adventurer_regen_hp`;
CREATE TEMPORARY TABLE `tmp_adventurer_regen_hp` AS
SELECT MOD(`ID`,100) AS `slot`, AVG(`Data`) AS `Data`
FROM `gtoctregenhp_dbc`
WHERE FLOOR(`ID`/100)+1 IN (2,3,4,5,7,8,9,11)
GROUP BY MOD(`ID`,100);

INSERT INTO `gtoctregenhp_dbc` (`ID`,`Data`)
SELECT 900+`slot`, `Data` FROM `tmp_adventurer_regen_hp`
ON DUPLICATE KEY UPDATE `Data`=VALUES(`Data`);
DROP TEMPORARY TABLE `tmp_adventurer_regen_hp`;

DROP TEMPORARY TABLE IF EXISTS `tmp_adventurer_regen_hp_spt`;
CREATE TEMPORARY TABLE `tmp_adventurer_regen_hp_spt` AS
SELECT MOD(`ID`,100) AS `slot`, AVG(`Data`) AS `Data`
FROM `gtregenhpperspt_dbc`
WHERE FLOOR(`ID`/100)+1 IN (2,3,4,5,7,8,9,11)
GROUP BY MOD(`ID`,100);

INSERT INTO `gtregenhpperspt_dbc` (`ID`,`Data`)
SELECT 900+`slot`, `Data` FROM `tmp_adventurer_regen_hp_spt`
ON DUPLICATE KEY UPDATE `Data`=VALUES(`Data`);
DROP TEMPORARY TABLE `tmp_adventurer_regen_hp_spt`;

-- Mana regeneration: class 10 receives the normal Paladin mana-user curve.
INSERT INTO `gtregenmpperspt_dbc` (`ID`,`Data`)
SELECT 800 + `ID`, `Data`
FROM `gtregenmpperspt_dbc`
WHERE `ID` BETWEEN 100 AND 199
ON DUPLICATE KEY UPDATE `Data`=VALUES(`Data`);

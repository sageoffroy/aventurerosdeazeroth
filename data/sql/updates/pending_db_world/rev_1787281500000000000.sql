-- Aventureros de Azeroth: one Mana Sapphire for the full level 1-80 journey.
-- Conjure Mana Gem is normalized to create/recharge item 33312 at every level.
-- Its native item-use spell 42987 is replaced by deterministic helper 242987,
-- whose native-rank anchor curve lives in the canonical SpellDraft scaling TSV.

UPDATE `item_template`
SET
    `RequiredLevel` = 1,
    `spellid_1` = 242987
WHERE `entry` = 33312;

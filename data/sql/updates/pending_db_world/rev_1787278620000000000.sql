-- Aventureros de Azeroth: one level-scaled Mage refreshment for the full 1-80 journey.
-- Runtime restoration is scaled by reviewed internal helper spells in the canonical
-- SpellDraft custom_spell_scaling.tsv; therefore the item itself can be usable at
-- every level without exposing its original level-74 restoration values.

UPDATE `item_template`
SET `RequiredLevel` = 1
WHERE `entry` = 43518;

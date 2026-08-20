-- Aventureros SpellDraft: configurable offer size (up to 5) and level-based resources.

ALTER TABLE `spelldraft_pending_offer`
    ADD COLUMN `offer_4` INT UNSIGNED NOT NULL DEFAULT 0 AFTER `offer_3`,
    ADD COLUMN `offer_5` INT UNSIGNED NOT NULL DEFAULT 0 AFTER `offer_4`,
    ADD COLUMN `offer_size` TINYINT UNSIGNED NOT NULL DEFAULT 3 AFTER `offer_5`;

ALTER TABLE `spelldraft_draft_resources`
    ADD COLUMN `resource_level` TINYINT UNSIGNED NOT NULL DEFAULT 1 AFTER `bans_left`;

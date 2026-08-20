-- Aventureros SpellDraft: consumable card protection carried into the next draft.

ALTER TABLE `spelldraft_draft_resources`
    ADD COLUMN `protections_left` SMALLINT UNSIGNED NOT NULL DEFAULT 0 AFTER `bans_left`,
    ADD COLUMN `protected_spell_id` INT UNSIGNED NOT NULL DEFAULT 0 AFTER `protections_left`,
    ADD COLUMN `protection_drafts_awarded` SMALLINT UNSIGNED NOT NULL DEFAULT 0 AFTER `protected_spell_id`,
    ADD COLUMN `protection_initialized` TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER `protection_drafts_awarded`;

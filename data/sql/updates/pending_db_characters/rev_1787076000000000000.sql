-- Minimal persistent state for the native Adventurer SpellDraft loop.
-- This intentionally does not reuse the historical prestige_stats/drafted_spells
-- schema from wowrandom. The new project owns a small, explicit draft state.

CREATE TABLE IF NOT EXISTS `spelldraft_drafted_spells` (
    `player_guid` INT UNSIGNED NOT NULL,
    `spell_id` INT UNSIGNED NOT NULL,
    `draft_index` SMALLINT UNSIGNED NOT NULL,
    `picked_level` TINYINT UNSIGNED NOT NULL,
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`player_guid`, `spell_id`),
    KEY `idx_spelldraft_drafted_spells_guid_order` (`player_guid`, `draft_index`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `spelldraft_pending_offer` (
    `player_guid` INT UNSIGNED NOT NULL,
    `offer_1` INT UNSIGNED NOT NULL DEFAULT 0,
    `offer_2` INT UNSIGNED NOT NULL DEFAULT 0,
    `offer_3` INT UNSIGNED NOT NULL DEFAULT 0,
    `offered_level` TINYINT UNSIGNED NOT NULL DEFAULT 1,
    `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`player_guid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

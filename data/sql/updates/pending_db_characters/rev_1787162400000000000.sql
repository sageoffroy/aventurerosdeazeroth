-- Aventureros SpellDraft: persistent rerolls and permanent card bans.

CREATE TABLE IF NOT EXISTS `spelldraft_draft_resources` (
    `player_guid` INT UNSIGNED NOT NULL,
    `rerolls_left` SMALLINT UNSIGNED NOT NULL,
    `bans_left` SMALLINT UNSIGNED NOT NULL,
    `updated_at` TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`player_guid`)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `spelldraft_banned_spells` (
    `player_guid` INT UNSIGNED NOT NULL,
    `spell_id` INT UNSIGNED NOT NULL,
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`player_guid`, `spell_id`),
    KEY `idx_spelldraft_banned_spells_guid` (`player_guid`)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

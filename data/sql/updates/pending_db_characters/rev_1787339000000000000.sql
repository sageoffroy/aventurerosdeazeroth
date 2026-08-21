-- Aventureros de Azeroth
-- Metaprogresion independiente por cuenta + talentos por superviviente.

CREATE TABLE IF NOT EXISTS `aventureros_account_progress` (
    `account_id` INT UNSIGNED NOT NULL,
    `honor` INT UNSIGNED NOT NULL DEFAULT 0,
    `highest_roguelike_tier` SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    `runs_completed` INT UNSIGNED NOT NULL DEFAULT 0,
    `updated_at` TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`account_id`)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `aventureros_account_talents` (
    `account_id` INT UNSIGNED NOT NULL,
    `talent_id` VARCHAR(64) NOT NULL,
    `unlocked_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`account_id`, `talent_id`),
    KEY `idx_aventureros_account_talents_account` (`account_id`)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `aventureros_character_talents` (
    `player_guid` INT UNSIGNED NOT NULL,
    `talent_id` VARCHAR(64) NOT NULL,
    `talent_rank` TINYINT UNSIGNED NOT NULL,
    `talent_spell_id` INT UNSIGNED NOT NULL,
    `talent_index` SMALLINT UNSIGNED NOT NULL,
    `picked_level` TINYINT UNSIGNED NOT NULL,
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`player_guid`, `talent_id`, `talent_rank`),
    UNIQUE KEY `uq_aventureros_character_talent_index`
        (`player_guid`, `talent_index`),
    KEY `idx_aventureros_character_talents_guid` (`player_guid`)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `aventureros_pending_talent_offer` (
    `player_guid` INT UNSIGNED NOT NULL,
    `offer_1` INT UNSIGNED NOT NULL DEFAULT 0,
    `offer_2` INT UNSIGNED NOT NULL DEFAULT 0,
    `offer_3` INT UNSIGNED NOT NULL DEFAULT 0,
    `offer_4` INT UNSIGNED NOT NULL DEFAULT 0,
    `offer_5` INT UNSIGNED NOT NULL DEFAULT 0,
    `offer_size` TINYINT UNSIGNED NOT NULL DEFAULT 3,
    `offered_level` TINYINT UNSIGNED NOT NULL DEFAULT 1,
    `updated_at` TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`player_guid`)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `aventureros_dm_reward_checkpoint` (
    `player_guid` INT UNSIGNED NOT NULL,
    `account_id` INT UNSIGNED NOT NULL,
    `roguelike_floors_credited` INT UNSIGNED NOT NULL DEFAULT 0,
    `highest_tier_seen` INT UNSIGNED NOT NULL DEFAULT 0,
    `roguelike_runs_seen` INT UNSIGNED NOT NULL DEFAULT 0,
    `updated_at` TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`player_guid`),
    KEY `idx_aventureros_dm_reward_checkpoint_account` (`account_id`)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

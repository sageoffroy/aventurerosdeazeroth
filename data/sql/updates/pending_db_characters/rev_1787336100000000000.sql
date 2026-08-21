-- Aventureros de Azeroth
-- Checkpoint del puente Dungeon Master -> Honor de cuenta.
--
-- Evita acreditar dos veces el mismo progreso roguelike aunque ALE procese
-- las escrituras de CharacterDB de forma asincrona.

CREATE TABLE IF NOT EXISTS `spelldraft_dm_reward_checkpoint` (
    `player_guid` INT UNSIGNED NOT NULL,
    `account_id` INT UNSIGNED NOT NULL,
    `roguelike_floors_credited` INT UNSIGNED NOT NULL DEFAULT 0,
    `highest_tier_seen` INT UNSIGNED NOT NULL DEFAULT 0,
    `roguelike_runs_seen` INT UNSIGNED NOT NULL DEFAULT 0,
    `updated_at` TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`player_guid`),
    KEY `idx_spelldraft_dm_reward_checkpoint_account` (`account_id`)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

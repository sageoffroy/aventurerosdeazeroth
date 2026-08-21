# Dungeon Master -> Honor de cuenta

Este puente conecta el progreso persistido por `mod-dungeon-master` con la
metaprogresión de talentos de SpellDraft sin modificar el submódulo.

## Fuente de verdad

Dungeon Master ya guarda por personaje:

```text
dm_roguelike_player_stats.total_floors_cleared
```

Ese contador solo se consolida cuando termina la run roguelike. SpellDraft
observa el delta y lo convierte en Honor de cuenta.

No se usa `dm_player_stats.completed_runs` porque Dungeon Master también lo
incrementa durante pisos roguelike; combinar ambos produciría pago doble.

## Recompensa inicial

```text
10 Honor por piso roguelike completado
```

Configurable en:

```ini
SpellDraft.MetaProgression.DungeonMaster.Enable = 1
SpellDraft.MetaProgression.RoguelikeHonorPerFloor = 10
SpellDraft.MetaProgression.DungeonMaster.PollSeconds = 5
```

Los valores son provisionales de balance.

## Persistencia

El puente usa:

```text
spelldraft_dm_reward_checkpoint
```

Cada fila conserva:

- `player_guid`
- `account_id`
- pisos roguelike ya acreditados
- tier máximo visto
- runs vistas

El mapping `player_guid -> account_id` permite que un superviviente nuevo cobre
progreso pendiente de otro superviviente de la misma cuenta aunque el anterior
ya no esté conectado.

La primera vez que un personaje aparece después de instalar el puente, sus
estadísticas existentes se toman como baseline. No se acredita Honor retroactivo
por runs de desarrollo anteriores.

## Flujo

```text
termina run roguelike
       ↓
Dungeon Master actualiza dm_roguelike_player_stats
       ↓
dm_rewards.lua detecta pisos nuevos
       ↓
actualiza checkpoint
       ↓
SpellDraftTalents.GrantAccountHonor(...)
       ↓
Honor visible + saldo persistente de cuenta
```

## Prueba manual

Con un Aventurero:

1. Ejecutar una run roguelike y completar al menos un piso.
2. Terminar la run por wipe o salida normal.
3. Esperar hasta el siguiente poll (por defecto 5 segundos).
4. Debe aparecer el mensaje `+N Honor de cuenta`.
5. `!talentos` debe mostrar el nuevo saldo.
6. Crear/entrar con otro superviviente de la misma cuenta y confirmar el mismo Honor.

Forzar chequeo inmediato:

```text
!talentos sincronizar
```

La compra de familias sigue siendo:

```text
!talentos comprar <id>
```

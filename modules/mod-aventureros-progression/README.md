# mod-aventureros-progression

Metaprogresion persistente de **Aventureros de Azeroth**.

## Responsabilidad

Este modulo es el unico dueño de:

- Honor de cuenta;
- talentos desbloqueados por cuenta;
- tienda temporal de talentos;
- elecciones `Talento (N)` por superviviente;
- checkpoint de recompensas de Dungeon Master;
- mejor tier y runs roguelike persistentes de la cuenta.

No modifica el codigo de `mod-dungeon-master` y no contiene el motor de
habilidades de `mod-spelldraft`.

## Fronteras

```text
mod-dungeon-master
  -> persiste progreso roguelike

mod-aventureros-progression
  -> lee deltas de progreso
  -> acredita Honor por cuenta
  -> administra unlocks
  -> administra Talento (N)

mod-spelldraft
  -> administra solamente habilidades / cartas normales
```

`feature/mod-dungeon-master` no debe modificar archivos de `mod-spelldraft`.

## Integracion con SpellDraft

El addon usa el mismo transporte `SC:*` para habilidades y talentos. Por eso la
rama `agent/integration-testing` necesita un unico punto de delegacion antes de
que SpellDraft procese el mensaje:

```lua
if AventurerosTalentDraft
    and AventurerosTalentDraft.HandleProtocolMessage(player, msg) then
    return false
end
```

`AventurerosTalentDraft.HandleProtocolMessage()` devuelve `false` siempre que
haya habilidades normales pendientes, por lo que SpellDraft conserva prioridad.

No hace falta enganchar el level-up de SpellDraft: este modulo espera por su
cuenta hasta que `spelldraft_drafted_spells` alcance el numero esperado y recien
entonces abre `Talento (N)`.

## Progresion inicial

- nivel 10: `Talento (1)`;
- nivel 12: `Talento (2)`;
- nivel 14: `Talento (3)`;
- ...;
- nivel 80: `Talento (36)`.

Los talentos elegidos se guardan por `player_guid`. El Honor y los unlocks se
guardan por `account_id`.

## Honor y Dungeon Master

El adaptador usa exclusivamente:

```text
dm_roguelike_player_stats.total_floors_cleared
```

No usa `dm_player_stats.completed_runs`, porque Dungeon Master incrementa esa
estadistica tambien en pisos roguelike y produciria pagos duplicados.

Valor inicial de balance:

```text
10 Honor por piso roguelike
```

El checkpoint conserva `player_guid -> account_id`; por eso un superviviente
nuevo puede cobrar progreso pendiente de uno anterior de la misma cuenta.

## Comandos temporales de prueba

```text
!talentos
!talentos comprar <id>
!talentos darhonor 500       # solo GM
!talentos sincronizar
```

La tienda por chat es provisoria. La API de cuenta queda separada para poder
moverla luego a un NPC/UI sin tocar el motor de talentos.

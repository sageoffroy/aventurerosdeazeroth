# Guerrero — Auditoría SpellDraft

Este archivo conserva las decisiones de diseño e implementación de Guerrero durante la auditoría clase por clase. La fuente técnica continúa siendo el código y los JSON del módulo.

## Estado

- **REVISANDO**: decisión e implementación preparadas; falta la pasada final en juego.
- Las habilidades enseñadas por una postura no cuentan como cartas independientes del draft.

---

## Bloque 1 — Posturas

| Raíz nativa | Carta runtime | Habilidad | Rareza | Otorga | Enseña |
| ---: | ---: | --- | --- | --- | --- |
| `2457` | `202457` | Battle Stance / Actitud de batalla | Poco común (`1`) | `stance.battle` | `100` Charge / Cargar |
| `71` | `200071` | Defensive Stance / Actitud defensiva | Poco común (`1`) | `stance.defensive` | `355` Taunt / Provocar |
| `2458` | `202458` | Berserker Stance / Actitud rabiosa | Rara (`2`) | `stance.berserker` | `20252` Intercept / Interceptar + `1680` Whirlwind / Torbellino |

### Decisión cerrada para este bloque

- Actitud de batalla entrega **Cargar** gratis.
- Actitud defensiva entrega **Provocar** gratis.
- Actitud rabiosa entrega **Interceptar + Torbellino** gratis.
- Las cuatro habilidades enseñadas no deben aparecer como elecciones independientes mientras formen parte de estos paquetes.
- La rareza de Actitud rabiosa se corrige de **Épica (`3`)** a **Rara (`2`)**. Batalla y Defensiva permanecen **Poco comunes (`1`)**.

### Implementación técnica

`card_dependencies.json` ya contiene los tres `grants` de postura y sus `teaches`:

- `2457 -> teaches [100]`
- `71 -> teaches [355]`
- `2458 -> teaches [20252, 1680]`

No hace falta duplicar estas habilidades en `spell_exclusions.json`: `draft.lua` construye `TAUGHT_ROOTS` desde `SpellDraftTeachMap` / `SpellDraftTeachTeamMap` y descarta cualquier entrada enseñada al generar o validar una oferta.

`card_rarity_overrides.json` deja este bloque en:

- `2457 = 1` — Poco común.
- `71 = 1` — Poco común.
- `2458 = 2` — Rara.

## Validación pendiente

En la pasada integral de Guerrero confirmar en juego que:

1. cada postura aparece con la rareza correcta;
2. al aprender la postura se aprenden inmediatamente sus habilidades asociadas;
3. Cargar, Provocar, Interceptar y Torbellino no aparecen como cartas independientes;
4. cambiar de postura habilita correctamente las habilidades que dependen de `stance.battle`, `stance.defensive` o `stance.berserker`.

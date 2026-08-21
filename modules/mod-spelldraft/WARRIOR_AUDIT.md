# Guerrero — Auditoría SpellDraft

Este archivo conserva las decisiones de diseño e implementación de Guerrero durante la auditoría clase por clase. La fuente técnica continúa siendo el código y los JSON del módulo.

## Estado

- **REVISANDO**: decisión e implementación preparadas; falta la pasada final en juego.
- Las habilidades enseñadas por una postura no cuentan como cartas independientes del draft.

## Regla de normalización de Guerrero

Las habilidades de Guerrero no se rediseñan para compensar el DPS actual del Adventurer. Se conserva la mecánica WotLK original y se reemplaza solamente la progresión por rangos por una curva continua 1-80:

1. cada rango oficial es un anchor exacto;
2. entre anchors se interpola linealmente con redondeo al entero más cercano, igual que en el normalizador canónico usado para Mago;
3. después del último rango oficial el valor queda plano hasta nivel 80;
4. costes, requisitos de arma/postura, flags, siguiente ataque, cooldowns y demás mecánicas permanecen originales salvo una decisión explícita documentada;
5. valores externos a Spell.dbc que cambien por rango —por ejemplo `spell_threat`— también deben normalizarse y comprobarse;
6. una habilidad no se considera preparada si conserva el número principal pero pierde una mecánica de scripts de AzerothCore.

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

### Validación pendiente

En la pasada integral de Guerrero confirmar en juego que:

1. cada postura aparece con la rareza correcta;
2. al aprender la postura se aprenden inmediatamente sus habilidades asociadas;
3. Cargar, Provocar, Interceptar y Torbellino no aparecen como cartas independientes;
4. cambiar de postura habilita correctamente las habilidades que dependen de `stance.battle`, `stance.defensive` o `stance.berserker`.

---

## 200078 — Heroic Strike / Golpe heroico — REVISANDO

### Decisión

Se conserva íntegramente la identidad WotLK:

- `Next Melee` / siguiente ataque cuerpo a cuerpo;
- requiere arma cuerpo a cuerpo/mano principal;
- coste fijo de **15 de ira**;
- GCD `0`;
- daño físico de arma más el bonus numérico del rango;
- amenaza elevada;
- desde el rango 10, originalmente aprendido en nivel 66, conserva el bonus de daño contra objetivos Dazed.

La carta rankless usa raíz nativa `78` y runtime determinista `200078`.

### Cadena oficial

`78 -> 284 -> 285 -> 1608 -> 11564 -> 11565 -> 11566 -> 11567 -> 25286 -> 29707 -> 30324 -> 47449 -> 47450`.

### Comparación exacta de anchors

El daño principal se normaliza con el pipeline canónico `profiled_native_rank_anchors`. Los anchors oficiales se copian literalmente, por lo que la desviación en cada nivel de rango es cero.

La amenaza fija no vive en Spell.dbc sino en `spell_threat`; también se reconstruye con esos mismos niveles como anchors y la misma interpolación lineal/redondeo.

| Rango | Spell nativo | Nivel | Daño oficial | Daño normalizado | Desv. | Amenaza oficial | Amenaza normalizada | Desv. |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | `78` | 1 | 11 | 11 | 0 (0.00%) | 5 | 5 | 0 (0.00%) |
| 2 | `284` | 8 | 21 | 21 | 0 (0.00%) | 10 | 10 | 0 (0.00%) |
| 3 | `285` | 16 | 32 | 32 | 0 (0.00%) | 16 | 16 | 0 (0.00%) |
| 4 | `1608` | 24 | 44 | 44 | 0 (0.00%) | 22 | 22 | 0 (0.00%) |
| 5 | `11564` | 32 | 60 | 60 | 0 (0.00%) | 31 | 31 | 0 (0.00%) |
| 6 | `11565` | 40 | 93 | 93 | 0 (0.00%) | 48 | 48 | 0 (0.00%) |
| 7 | `11566` | 48 | 136 | 136 | 0 (0.00%) | 70 | 70 | 0 (0.00%) |
| 8 | `11567` | 56 | 178 | 178 | 0 (0.00%) | 92 | 92 | 0 (0.00%) |
| 9 | `25286` | 60 | 201 | 201 | 0 (0.00%) | 104 | 104 | 0 (0.00%) |
| 10 | `29707` | 66 | 234 | 234 | 0 (0.00%) | 121 | 121 | 0 (0.00%) |
| 11 | `30324` | 70 | 317 | 317 | 0 (0.00%) | 164 | 164 | 0 (0.00%) |
| 12 | `47449` | 72 | 432 | 432 | 0 (0.00%) | 224 | 224 | 0 (0.00%) |
| 13 | `47450` | 76 | 495 | 495 | 0 (0.00%) | 259 | 259 | 0 (0.00%) |
| — | — | 80 | 495 | 495 | 0 (0.00%) | 259 | 259 | 0 (0.00%) |

**Resultado de anchors:** daño `13/13` exactos y amenaza `13/13` exactos. Desviación máxima en anchors: **0.00%**.

### Dazed

Los rangos 1-9 no tienen el bonus. AzerothCore enlaza `spell_warr_heroic_strike` sólo a los rangos 10-13 (`29707`, `30324`, `47449`, `47450`) y aplica la misma regla WotLK de **+35%** cuando el objetivo cumple la detección de Dazed.

El runtime `200078` no podía heredar esa lógica desde la raíz `78`, porque la raíz no tiene ese `spell_script_names`. Se corrigió sin adelantar el efecto:

- el script normalizado se enlaza explícitamente a `200078`;
- el +35% empieza únicamente en **nivel 66**;
- se reutiliza la misma detección de auras Dazed/Snare que AzerothCore;
- antes de nivel 66 no se aplica ningún bonus Dazed.

Los textos oficiales de los rangos altos muestran como referencia `+82`, `+111`, `+151` y `+173` para los niveles 66, 70, 72 y 76 respectivamente; la implementación normalizada no inventa una segunda curva, sino que conserva la fórmula nativa del 35%.

### Amenaza

Los `flatMod` oficiales de `spell_threat` son:

`5, 10, 16, 22, 31, 48, 70, 92, 104, 121, 164, 224, 259`.

Como `200078` no pertenece a la cadena nativa de rangos, AzerothCore no puede resolver automáticamente esos registros. `WarriorNormalizedSpells.cpp` aplica la amenaza fija normalizada al impacto, usando exactamente los anchors anteriores, interpolación lineal al entero más cercano y valor plano `259` desde nivel 76 hasta 80. `pctMod` permanece `1` y `apPctMod` permanece `0`, igual que todos los rangos oficiales de Golpe heroico.

### Compatibilidad general de SpellScript

Se ajustó la compatibilidad de `SpellScriptLoader.cpp`: para un ID normalizado `200000-299999`, un binding explícito al ID runtime tiene prioridad; si no existe, continúa el fallback a `runtime - 200000` usado por Mago. Esto permite conservar mecánicas que Blizzard/AzerothCore enlazan sólo a rangos tardíos sin romper la herencia general ya implementada.

### Validación pendiente en juego

No se pretende usar el DPS total del Adventurer como referencia de balance. En la pasada final sólo hace falta confirmar funcionalmente:

1. que `200078` sigue siendo un ataque `Next Melee`;
2. que consume 15 de ira y conserva los requisitos de arma;
3. que los valores mostrados/aplicados en niveles de anchor coinciden;
4. que el bonus Dazed no aparece antes de 66 y sí funciona desde 66;
5. que la amenaza adicional se aplica una sola vez por impacto.

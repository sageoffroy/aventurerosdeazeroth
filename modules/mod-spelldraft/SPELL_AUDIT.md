# SpellDraft — Registro de auditoría de hechizos

Este archivo es el registro humano de decisiones, cambios y estado de prueba de los hechizos de **Aventureros de Azeroth**.

La fuente técnica sigue siendo el código/JSON correspondiente; este documento explica **qué decidimos y por qué**, para no perder contexto durante la auditoría clase por clase.

## Estados

- **APROBADO**: diseño + implementación + prueba en juego cerrados.
- **REVISANDO**: decisión tomada o implementación hecha, pero falta validación final en juego.
- **PENDIENTE**: todavía no auditado.
- **STANDBY**: se investigó, pero se pospone para no bloquear la auditoría.
- **FUERA**: no debe aparecer como carta independiente.

---

# Mago

## APROBADO

### 190001 — Maestro de Portales

**Estado:** APROBADO

Decisión final:

- Una sola carta reemplaza los Portales individuales de Mago.
- La carta queda aprendida como **pasiva visible en el libro de hechizos**, pero no como habilidad activa.
- Enseña sólo los Portales correspondientes a la facción del personaje, más Dalaran.
- Alianza y Horda reciben su versión correcta de Shattrath; nunca ambas.
- Los Portales enseñados no requieren componentes.
- Los Teleports y Portals individuales de Mago quedan fuera del pool.
- Se conserva como icono de referencia `Portal: Stormwind` (`10059`).

Reglas de facción verificadas en juego.

### 18960 — Teleport: Moonglade

**Estado:** regla técnica/lore aplicada

- Debe usar el ID **nativo `18960`**, no un clon normalizado, porque el destino depende de `spell_target_position` asociado al ID nativo.
- Sólo puede aparecer para **Elfos de la Noche**.

---

## REVISANDO

### 201459 — Intelecto Arcano

**Estado:** REVISANDO

Diseño decidido:

- Mantener la **identidad, nombre e icono de Intelecto Arcano**.
- Mantener su bonificación/escalado de Intelecto dentro del pipeline normal.
- Adoptar la practicidad de **Luminosidad Arcana (`23028`)**:
  - afecta al grupo/banda;
  - duración de **1 hora**;
  - sin componente.
- `23028 Luminosidad Arcana` queda **FUERA** como carta independiente.

Pruebas realizadas:

- Primera prueba en juego: el aura duró **30 minutos**.
- Causa: `CustomSpellScaling.cpp` reaplicaba al casteo la duración de `custom_spell_scaling.tsv`, que todavía conservaba los 30 minutos originales de la familia de Intelecto Arcano. Modificar sólo `Spell.dbc` no alcanzaba.
- Corrección aplicada: la mutación revisada fija explícitamente `3600000 ms` en la columna de duración del scaling runtime de `201459`, manteniendo el escalado numérico normal intacto.
- Segunda prueba en juego: **1 hora confirmada** sobre el propio personaje.
- La propagación a **grupo/banda** queda pendiente de una prueba con otro jugador; técnicamente el comportamiento estructural se copia de `23028 Luminosidad Arcana`.

Prueba directa:

```text
.learn 201459
```

### 190002 — Resguardo Elemental

**Estado:** REVISANDO

Decisión de diseño:

- Una sola carta reemplaza a **Resguardo de Fuego** y **Resguardo de Escarcha** como elecciones independientes del draft.
- Al elegirla se aprenden las dos habilidades activas normalizadas:
  - `200543` — Resguardo de Fuego (raíz nativa `543`).
  - `206143` — Resguardo de Escarcha (raíz nativa `6143`).
- La carta `190002 Resguardo Elemental` queda como marcador pasivo en el libro de hechizos; las dos habilidades enseñadas son las que se usan activamente.
- Los resguardos individuales quedan fuera del pool como elecciones independientes porque pertenecen al `TeachMap` del paquete.
- Usa como icono de referencia el de `Fire Ward (543)`.
- Rareza configurada temporalmente como **Uncommon**; se revisará en la pasada final de balance.

Problemas detectados y correcciones aplicadas:

- La primera carta no mostraba a la derecha los iconos/cuadritos de las habilidades que enseña. La inspección del AddOn real mostró que ya existía una UI canónica para cartas con `teaches` (`patch_client_teaches_ui.py`). En vez de mantener un segundo overlay, se amplió ese mismo sistema para leer también `card_packages.json`, incluidos los `teaches_by_team`. Así cartas normales y paquetes usan los mismos cuadritos, tooltips y límite visual de cuatro slots con `+N`.
- La carta mostraba **`Rango 1`** porque `190002` clonaba el subtexto localizado de `Fire Ward`. La finalización genérica de cartas-paquete (`finalize_package_cards.py`) borra los campos Rank/Rango heredados y valida que todos los marcadores sean rankless.
- `6143 Frost Ward` estaba fuera de la cohorte normalizada original. La cohorte canónica se amplió hasta primer rango de **nivel 22**, por lo que Frost Ward ahora usa el ID determinista `206143` y el mismo pipeline de interpolación por nivel que el resto de hechizos normalizados. El self-test dejó de fijar mágicamente el valor 20 y valida que el cap configurado sea válido, para permitir que la cohorte siga creciendo durante la auditoría sin desactivar controles.

Falta repetir la prueba visual/funcional en juego y confirmar:

1. la carta ya no muestra `Rango 1`;
2. aparecen los dos cuadritos a la derecha;
3. al elegirla se aprenden `200543` y `206143`.

---

## PENDIENTES DE AUDITORÍA

Por ahora **no se consideran aprobados** aunque estén presentes en la whitelist de prueba:

- `200116` — Frostbolt
- `200133` — Fireball
- `200168` — Frost Armor
- `200604` — Dampen Magic
- `201008` — Amplify Magic

### Bloques de diseño pendientes

- **Amplify Magic + Dampen Magic**: decidir si quedan separados o se comprimen.
- **Armaduras** (`Frost Armor`, `Ice Armor`, `Mage Armor`, `Molten Armor`): conservar como elecciones de build salvo evidencia en contrario.
- Duplicados de `Molten Armor` requieren inspección técnica antes de decidir.

---

## STANDBY

### 55342 — Mirror Image

**Estado:** STANDBY

Se investigó el escalado de daño de las copias y sus hechizos de soporte, pero se pospuso para no bloquear la auditoría de Mago.

No retomar salvo decisión explícita.

---

## Decisiones de diseño futuras ya acordadas

- **Maestro de Festines**: comprimir `Conjure Food + Conjure Water + Conjure Refreshment` en una sola carta/paquete.
- `43987 Ritual of Refreshment`: **FUERA**.

---

## Regla de trabajo de la auditoría

Se audita **una clase por vez** y se aplica código inmediatamente al cerrar cada decisión relevante:

1. Inventario.
2. Diseño.
3. Funcionamiento/prueba.
4. Balance.

La whitelist de auditoría sólo sirve para acelerar las pruebas; no reemplaza el catálogo completo ni sus dependencias.

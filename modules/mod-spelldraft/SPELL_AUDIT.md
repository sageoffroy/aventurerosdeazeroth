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

### 190002 — Resguardo Elemental

**Estado:** APROBADO

Decisión final:

- Una sola carta reemplaza a **Resguardo de Fuego** y **Resguardo de Escarcha** como elecciones independientes del draft.
- Al elegirla se aprenden las dos habilidades activas normalizadas:
  - `200543` — Resguardo de Fuego (raíz nativa `543`).
  - `206143` — Resguardo de Escarcha (raíz nativa `6143`).
- La carta `190002 Resguardo Elemental` queda como marcador pasivo en el libro de hechizos; las dos habilidades enseñadas son las que se usan activamente.
- Los resguardos individuales quedan fuera del pool como elecciones independientes porque pertenecen al `TeachMap` del paquete.
- Rareza configurada temporalmente como **Uncommon**; se revisará en la pasada final de balance.

Correcciones cerradas durante la prueba:

- La UI canónica de `teaches` (`patch_client_teaches_ui.py`) se amplió para leer también `card_packages.json`, incluidos los `teaches_by_team`. Así cartas normales y paquetes usan los mismos cuadritos y tooltips.
- La carta heredaba `Rango 1` de `Fire Ward`; `finalize_package_cards.py` elimina ese subtexto de todos los marcadores de paquete.
- `6143 Frost Ward` entró al pipeline canónico de normalización al ampliar la cohorte hasta primer rango de nivel 22, y usa el ID determinista `206143`.
- Prueba funcional en juego confirmada: el paquete funciona correctamente y enseña los dos resguardos.

Pendiente **sólo cosmético**: se preparó el icono `Spell_ElementalArmor.tga`, pero el override visual de la carta todavía no lo toma. Esto no bloquea la aprobación funcional y se resolverá más adelante junto con los iconos personalizados.

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

### 190003 — Manipulación Mágica

**Estado:** REVISANDO

Decisión de diseño:

- Una sola carta comprime **Amplificar magia** y **Atenuar magia**.
- Al elegirla se aprenden las dos habilidades activas normalizadas:
  - `201008` — Amplificar magia (raíz nativa `1008`).
  - `200604` — Atenuar magia (raíz nativa `604`).
- Las dos habilidades dejan de aparecer como elecciones independientes del draft porque pasan a pertenecer al `TeachMap` del paquete.
- La carta `190003 Manipulación Mágica` queda como marcador pasivo/rankless y usa `Amplify Magic (1008)` como fuente temporal de icono/presentación.
- Rareza temporal: **Uncommon**; se revisará junto con el balance final.
- La UI canónica de `teaches` debe mostrar los dos cuadritos a la derecha automáticamente, igual que Resguardo Elemental.

Falta prueba funcional en juego antes de aprobarla.

---

## PENDIENTES DE AUDITORÍA

Por ahora **no se consideran aprobados** aunque estén presentes en la whitelist de prueba:

- `200116` — Frostbolt
- `200133` — Fireball
- `200168` — Frost Armor

### Bloques de diseño pendientes

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

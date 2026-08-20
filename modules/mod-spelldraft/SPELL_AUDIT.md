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

- Primera prueba en juego: el comportamiento grupal funcionó, pero el aura duró **30 minutos**.
- Causa: `CustomSpellScaling.cpp` reaplicaba al casteo la duración de `custom_spell_scaling.tsv`, que todavía conservaba los 30 minutos originales de la familia de Intelecto Arcano. Modificar sólo `Spell.dbc` no alcanzaba.
- Corrección aplicada: la mutación revisada fija explícitamente `3600000 ms` en la columna de duración del scaling runtime de `201459`, manteniendo el escalado numérico normal intacto.

Falta repetir la prueba en juego y confirmar **1 hora** antes de marcarlo APROBADO.

Prueba directa:

```text
.learn 201459
```

---

## PENDIENTES DE AUDITORÍA

Por ahora **no se consideran aprobados** aunque estén presentes en la whitelist de prueba:

- `200116` — Frostbolt
- `200133` — Fireball
- `200168` — Frost Armor
- `200543` — Fire Ward
- `6143` — Frost Ward
- `200604` — Dampen Magic
- `201008` — Amplify Magic

### Bloques de diseño pendientes

- **Fire Ward + Frost Ward**: decidir si quedan separados o se comprimen en una carta/paquete.
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

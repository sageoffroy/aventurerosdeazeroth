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

## Contador funcional del pool auditado

El contador principal mide **elecciones/cartas del draft**, no la cantidad de hechizos internos que una carta paquete puede enseñar. Así una carta como `Resguardo Elemental` cuenta una sola vez para medir la composición real del pool.

Categorías primarias:

- **Daño**: función principal causar daño.
- **Sanación**: recuperar vida.
- **Defensa**: mitigación, absorción, armadura, resistencias o supervivencia personal.
- **Soporte**: buffs/debuffs, mejoras de grupo, manipulación de estadísticas o recursos de combate.
- **Utilidad/Otras**: viaje, invocaciones, creación de objetos y herramientas especiales.

### Mago — contador actual

| Categoría | Cartas | Estado actual |
| --- | ---: | --- |
| Daño | 2 | `200116 Frostbolt`, `200133 Fireball` — APROBADO |
| Sanación | 0 | — |
| Defensa | 4 | `190002 Resguardo Elemental`, `207302 Ice Armor`, `206117 Mage Armor`, `230482 Molten Armor` — APROBADO |
| Soporte | 2 | `190003 Manipulación Mágica` — APROBADO; `201459 Intelecto Arcano` — REVISANDO |
| Utilidad/Otras | 2 | `190001 Maestro de Portales` — APROBADO; `190004 Maestro de Festines` — REVISANDO |
| **Total** | **10** | **8 APROBADAS + 2 REVISANDO** |

`18960 Teleport: Moonglade` es una regla especial racial/lore y no se suma todavía al contador del pool auditado. `55342 Mirror Image` está en STANDBY y tampoco se cuenta hasta retomar su auditoría.

Este bloque debe actualizarse cada vez que una carta se aprueba, se elimina, se empaqueta o cambia de función primaria.

## APROBADO

### 190001 — Maestro de Portales

**Estado:** APROBADO

- Una sola carta reemplaza los Portales individuales de Mago.
- Marcador pasivo visible en el libro de hechizos.
- Enseña sólo los Portales correspondientes a la facción del personaje, más Dalaran.
- Alianza y Horda reciben su versión correcta de Shattrath; nunca ambas.
- Sin componentes.
- Teleports y Portals individuales quedan fuera del pool.
- Reglas de facción verificadas en juego.

### 190002 — Resguardo Elemental

**Estado:** APROBADO

- Reemplaza a Resguardo de Fuego y Resguardo de Escarcha como elecciones independientes.
- Enseña `200543` Resguardo de Fuego y `206143` Resguardo de Escarcha.
- Marcador pasivo/rankless.
- Rareza temporal: Uncommon.
- Funcionamiento confirmado en juego.
- Pendiente sólo cosmético: icono personalizado `Spell_ElementalArmor.tga`.

### 190003 — Manipulación Mágica

**Estado:** APROBADO

- Comprime Amplificar magia y Atenuar magia.
- Enseña `201008` y `200604`.
- Marcador pasivo/rankless.
- Icono decidido: `Spell_Holy_Serendipity`, heredado de `63731 Serendipity`.
- Rareza temporal: Uncommon.
- Funcionamiento confirmado en juego.

### 200116 — Frostbolt

**Estado:** APROBADO

- Hechizo de daño normalizado por el pipeline canónico.
- Daño visible y daño real coinciden en la prueba.
- Tiempo de casteo y ralentización funcionan correctamente.

### 200133 — Fireball

**Estado:** APROBADO

- Hechizo de daño normalizado por el pipeline canónico.
- Daño directo y DoT funcionan correctamente.
- Tooltip y valores reales fueron confirmados en juego.

### Armaduras de Mago

**Estado:** APROBADO

- `Frost Armor` raíz `168` queda FUERA como carta independiente.
- `207302 Ice Armor`, `206117 Mage Armor` y `230482 Molten Armor` quedan como tres elecciones distintas de build.
- Las tres son rankless y usan el pipeline canónico desde nivel 1.
- `34913` es el helper reactivo interno de Molten Armor y nunca es carta.
- `230482` fue corregida para disparar el helper normalizado `234913`, evitando el daño nativo de nivel alto en nivel 1.
- El tooltip de Molten Armor fue corregido para mostrar el daño escalado del helper; a nivel 1 refleja aproximadamente 4 p. y el popup muestra el mismo valor.
- Las tres armaduras fueron verificadas funcionalmente en juego.

### 18960 — Teleport: Moonglade

**Estado:** regla técnica/lore aplicada

- Usa el ID nativo `18960`, porque el destino depende de `spell_target_position` asociado al ID nativo.
- Sólo puede aparecer para Elfos de la Noche.

---

## REVISANDO

### 201459 — Intelecto Arcano

**Estado:** REVISANDO

- Mantiene identidad, nombre, icono y escalado de Intelecto Arcano.
- Adopta el targeting de grupo/banda de `23028 Luminosidad Arcana`.
- Duración fija de 1 hora.
- Sin componente.
- `23028` queda FUERA como carta independiente.
- 1 hora confirmada sobre el propio personaje.
- Falta únicamente validar propagación a otro miembro de grupo/banda.

Prueba directa:

```text
.learn 201459
```

### 190004 — Maestro de Festines

**Estado:** REVISANDO

Diseño decidido:

- Una sola carta de utilidad comprime las tres líneas de creación de alimento/bebida del Mago.
- Enseña:
  - `200587` — Crear comida, raíz nativa `587`.
  - `205504` — Crear agua, raíz nativa `5504`.
  - `242955` — Crear refrigerio, raíz nativa `42955`.
- Marcador pasivo/rankless.
- `43987 Ritual of Refreshment` queda FUERA explícitamente y no forma parte del paquete.
- Rareza temporal: Uncommon.
- Icono/fuente visual actual: `42955 Conjure Refreshment`.
- Falta prueba en el draft real para confirmar que la carta enseña las tres habilidades.

---

## STANDBY

### 55342 — Mirror Image

**Estado:** STANDBY

Se investigó el escalado de daño de las copias y sus hechizos de soporte, pero se pospuso para no bloquear la auditoría de Mago.

No retomar salvo decisión explícita.

---

## Regla de trabajo de la auditoría

Se audita **una clase por vez** y se aplica código inmediatamente al cerrar cada decisión relevante:

1. Inventario.
2. Diseño.
3. Funcionamiento/prueba.
4. Balance.

La whitelist de auditoría sólo sirve para acelerar las pruebas; no reemplaza el catálogo completo ni sus dependencias.

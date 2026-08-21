# SpellDraft — Registro de auditoría de hechizos

Este archivo registra decisiones, implementación y estado de validación de **Aventureros de Azeroth** durante la auditoría clase por clase.

La fuente técnica sigue siendo el código/JSON correspondiente. Este documento conserva el criterio humano para no volver a discutir decisiones ya cerradas.

## Estados

- **APROBADO**: diseño + implementación + prueba en juego cerrados.
- **REVISANDO**: diseño/implementación avanzados; falta validación final o existe un bug conocido.
- **PENDIENTE**: todavía no auditado.
- **STANDBY**: investigado pero pospuesto para no bloquear la clase.
- **FUERA**: no debe aparecer como elección independiente.

## Modalidad de trabajo actual

Mientras no haya acceso al juego se continúa la auditoría sin pruebas manuales: inventario, decisiones, compatibilidad técnica y código. Cada clase queda técnicamente preparada y permanece **REVISANDO** hasta una única pasada integral en juego. Después de esa pasada se corrigen los defectos juntos y se cierra la clase.

---

# Mago

## Contador funcional del pool

El contador mide **elecciones/cartas reales del draft**, no hechizos internos enseñados por paquetes.

| Categoría | Cantidad |
| --- | ---: |
| Daño | 12 |
| Sanación | 0 |
| Defensa | 6 |
| Soporte | 9 |
| Utilidad/Otras | 5 |
| **Total** | **32** |

Estado actual: **7 APROBADAS + 25 REVISANDO**.

`18960 Teleport: Moonglade` es una regla racial/lore especial y no entra todavía en este contador. `55342 Mirror Image` permanece en STANDBY y tampoco cuenta.

Las categorías primarias están almacenadas también en `audit_pool.json`, para que el contador no dependa sólo de este documento.

## Inventario completo actualmente seleccionado

### Daño — 12

- `200116` Frostbolt — APROBADO
- `200133` Fireball — APROBADO
- `205143` Arcane Missiles — REVISANDO
- `201449` Arcane Explosion — REVISANDO
- `230451` Arcane Blast — REVISANDO
- `202136` Fire Blast — REVISANDO
- `202120` Flamestrike — REVISANDO
- `202948` Scorch — REVISANDO
- `244614` Frostfire Bolt — REVISANDO
- `200010` Blizzard — REVISANDO
- `200120` Cone of Cold — REVISANDO
- `230455` Ice Lance — REVISANDO

### Defensa — 6

- `190002` Resguardo Elemental — APROBADO
- `207302` Ice Armor — APROBADO
- `230482` Molten Armor — APROBADO
- `206117` Mage Armor — REVISANDO por bugs conocidos
- `201463` Mana Shield — REVISANDO
- `245438` Ice Block — REVISANDO

### Soporte — 9

- `190003` Manipulación Mágica — APROBADO
- `201459` Arcane Intellect — REVISANDO
- `200118` Polymorph — REVISANDO
- `200122` Frost Nova — REVISANDO
- `200475` Remove Curse — REVISANDO
- `202139` Counterspell — REVISANDO
- `212051` Evocation — REVISANDO
- `230449` Spellsteal — REVISANDO
- `200759` Conjure Mana Gem — REVISANDO

### Utilidad/Otras — 5

- `190001` Maestro de Portales — APROBADO
- `242955` Conjure Refreshment — REVISANDO
- `200130` Slow Fall — REVISANDO
- `201953` Blink — REVISANDO
- `200066` Invisibility — REVISANDO

---

## Decisiones cerradas / implementadas

### 190001 — Maestro de Portales — APROBADO

- Una sola carta reemplaza Portales individuales.
- Marcador pasivo.
- Enseña sólo portales de la facción correspondiente más Dalaran.
- Nunca entrega ambas versiones de Shattrath.
- Sin componentes.
- Teleports/Portals individuales fuera del pool.

### 190002 — Resguardo Elemental — APROBADO

- Enseña `200543` Resguardo de Fuego y `206143` Resguardo de Escarcha.
- Marcador pasivo/rankless.
- Funcionamiento confirmado.
- Pendiente sólo cosmético: icono personalizado.

### 190003 — Manipulación Mágica — APROBADO

- Enseña `201008` Amplificar magia y `200604` Atenuar magia.
- Marcador pasivo/rankless.
- Icono decidido: `Spell_Holy_Serendipity`.
- Funcionamiento confirmado.

### 200116 — Frostbolt — APROBADO

Daño, casteo y ralentización confirmados contra tooltip/runtime.

### 200133 — Fireball — APROBADO

Daño directo, DoT y tooltip confirmados.

### 205143 — Arcane Missiles — REVISANDO

- Se conserva como ataque canalizado independiente.
- El canal raíz `5143` no contiene el daño de los proyectiles: dispara la familia interna rankeada raíz `7268`.
- Se añadió una solución general para helpers internos rankeados declarados en `normalize_trigger_spells`: si el helper no es una carta y por eso no fue normalizado por el catálogo, se genera automáticamente su clon determinista usando la familia nativa completa y el mismo pipeline canónico.
- Para Misiles Arcanos: `7268 -> 207268`.
- `205143` se remapea para disparar `207268`; el helper queda interno y FUERA del pool.
- La curva 1-80 del helper usa `custom_spell_scaling.tsv`, no un runtime paralelo.
- La pasada final debe validar duración del canal, un proyectil por segundo, cantidad de impactos, daño por proyectil, tooltip, críticos/procs y que `207268` nunca sea carta.

### 207302 — Ice Armor — APROBADO

- `Frost Armor` raíz `168` queda FUERA como carta independiente.
- Ice Armor representa esa línea defensiva y escala desde nivel 1.

### 230482 — Molten Armor — APROBADO

- Helper nativo `34913` nunca es carta.
- El runtime `230482` dispara helper normalizado `234913`.
- Se eliminó el daño nativo de nivel alto a nivel 1.
- Tooltip y daño real del helper quedaron alineados.

### 201459 — Arcane Intellect — REVISANDO

- Conserva identidad/icono/escalado de Arcane Intellect.
- Adopta targeting de grupo/banda de Arcane Brilliance `23028`.
- Duración fija de 1 hora.
- Sin componente.
- `23028` FUERA.
- Falta validar propagación sobre otro miembro de grupo/banda en la pasada final.

### 200130 — Slow Fall — REVISANDO

- Continúa como carta de utilidad independiente.
- Se elimina el requisito de `Light Feather`: una elección aleatoria del draft debe ser autosuficiente y no depender de abastecer un reactivo legado.
- Pendiente validación final en juego.

### 242955 — Conjure Refreshment — REVISANDO

- Es la única carta de comida/bebida.
- `200587` Conjure Food, `205504` Conjure Water y `43987 Ritual of Refreshment` quedan FUERA.
- Crea `43518 Conjured Mana Pie` para todo nivel 1-80.
- El item queda usable desde nivel 1.
- Helpers internos:
  - salud `61829 -> 261829`
  - maná `61830 -> 261830`
- Los helpers usan el mismo `custom_spell_scaling.tsv` que el resto de hechizos.
- Anchors reproducen Mana Biscuit / Mana Pie / Mana Strudel y extrapolan hacia nivel 1 con la regla canónica.
- Pendiente pasada final en juego.

### 200759 — Conjure Mana Gem — REVISANDO

Diseño implementado:

- Una sola carta reemplaza la progresión de gemas por rango.
- El runtime adopta el comportamiento de `42985` y crea/recarga un único `33312 Mana Sapphire` con 3 cargas desde nivel 1.
- El item queda usable desde nivel 1 y su spell de uso pasa de `42987` a helper determinista `242987`.
- El helper usa **rangos min/max**, no un promedio fijo, y se integra al mismo `custom_spell_scaling.tsv`.
- Anchors nativos preservados:
  - L28 `390-410`
  - L38 `585-615`
  - L48 `829-871`
  - L58 `1073-1127`
  - L68 `2340-2460`
  - L77 `3330-3500`
- L1 usa `39-41` por la misma regla de offset bajo nivel; L77-L80 queda plano al último rango nativo.
- Pendiente pasada final en juego.

---

## Compatibilidad general descubierta durante Mago

### Runtime 1-80

`custom_spells.json` tenía selección de primeras filas hasta nivel 80 pero `runtime_max_level` todavía estaba en 60. Se corrigió a **80**. Esto es un arreglo global para todas las clases, no una excepción del Mago.

### Herencia de SpellScript/AuraScript

Los clones DBC `200000 + native_root` conservaban estructura del hechizo, pero `spell_script_names` del world DB sigue indexado por ID nativo. Por lo tanto habilidades como Arcane Blast, Arcane Missiles, Mana Shield, Frostfire Bolt, Wards, Molten Armor y Mana Gem podían perder lógica C++ aunque el DBC pareciera correcto.

Se añadió una compatibilidad **general** en `SpellScriptLoader.cpp`:

- para IDs `200000-299999`, el lookup de `spell_script_names` se hace contra `spellId - 200000`;
- el script se inicializa con el ID runtime real, para que vea el `SpellInfo` normalizado;
- los paquetes `190xxx` no participan.

Así no se agregan aliases SQL spell por spell. La solución servirá automáticamente para las demás clases.

### Helpers internos rankeados

`ensure_reviewed_internal_helpers.py` completa un hueco general del normalizador:

- una carta puede ser sólo un wrapper/canal y ejecutar su magnitud real mediante otra familia de hechizos;
- esas familias internas no aparecen como cartas y por eso el normalizador de catálogo no necesariamente las selecciona;
- cuando una mutación revisada declara `normalize_trigger_spells`, el preparador genera automáticamente cualquier helper faltante como `200000 + native_root` usando su `spell_ranks` canónico;
- sus curvas 1-80 y perfiles terminan en los mismos `custom_spell_scaling.tsv` / `custom_spell_profiles.resolved.json`;
- la mutación existente sigue siendo la dueña del remapeo del trigger del padre.

Misiles Arcanos `7268 -> 207268` es el primer caso que aprovecha esta generalización; Molten Armor `34913 -> 234913` también queda cubierto cuando corresponda.

### Consumibles escalables

`apply_reviewed_consumable_scaling.py` se generalizó para soportar:

- helpers disparados por un wrapper;
- helpers usados directamente por un item;
- anchors de valor fijo;
- anchors con rango aleatorio min/max.

Todos terminan en el mismo TSV/runtime canónico.

---

## Bugs conocidos para la pasada final

### 206117 — Mage Armor

La habilidad funciona pero permanece REVISANDO:

1. El efecto visual queda colgado/persistente después de desaparecer o ser sustituido.
2. El tooltip muestra `2-1 p.` de resistencia mágica cuando el valor real observado es **1 p. fijo** a ese nivel.

Hay que separar el bug visual del bug de presentación numérica y corregir ambos antes de aprobarla.

### 201459 — Arcane Intellect

Falta confirmar propagación real a otro miembro de grupo/banda.

---

## STANDBY

### 55342 — Mirror Image

Se investigó el escalado de las copias pero el experimento no quedó satisfactorio. No retomar hasta decisión explícita.

---

## Regla de auditoría

Por cada clase:

1. inventario completo;
2. decisiones de diseño (queda / paquete / fuera / especial / standby);
3. implementación técnica, prefiriendo mecanismos generales;
4. una pasada integral en juego;
5. correcciones finales;
6. balance y cierre de la clase.

Regla general adicional: una variante puramente cosmética no ocupa una elección separada del draft.

La whitelist acelera la auditoría pero no reemplaza el catálogo completo ni sus dependencias.

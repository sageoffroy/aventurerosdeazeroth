# Mago — pasada final integral

Este archivo prepara la única sesión de prueba manual que se hará al volver al juego. Hasta entonces, todas las habilidades nuevas permanecen REVISANDO aunque su diseño/código estén terminados.

## Objetivo

Validar las 32 elecciones reales del pool de Mago en una sola pasada, corregir bugs juntos y cerrar la clase antes de abrir la siguiente.

## Bloque A — daño

Aprender para prueba directa:

```text
.learn 200116
.learn 200133
.learn 205143
.learn 201449
.learn 230451
.learn 202136
.learn 202120
.learn 202948
.learn 244614
.learn 200010
.learn 200120
.learn 230455
```

Comprobar por habilidad: tooltip vs daño real, coste de maná, tiempo de casteo/canalización, duración/DoT cuando corresponda y mecánica secundaria nativa (ralentización, stacks, área, etc.). Frostbolt y Fireball ya están aprobadas; se revalidan sólo como control de regresión.

## Bloque B — defensa

```text
.learn 200543
.learn 206143
.learn 207302
.learn 230482
.learn 206117
.learn 201463
.learn 245438
```

`190002 Resguardo Elemental` debe probarse además desde el draft real porque `.learn 190002` no valida el TeachMap del paquete.

Comprobar reemplazo mutuo de armaduras, absorciones, duración y cancelación visual. En `206117 Mage Armor` revisar específicamente los dos bugs abiertos: efecto visual persistente y tooltip `2-1` en vez de valor fijo.

## Bloque C — soporte/control

```text
.learn 201008
.learn 200604
.learn 201459
.learn 200118
.learn 200122
.learn 200475
.learn 202139
.learn 212051
.learn 230449
.learn 200759
```

`190003 Manipulación Mágica` debe validarse también desde el draft real.

Comprobar Polymorph/DR y ruptura por daño, Frost Nova y root, Remove Curse, interrupción de Counterspell, canal completo de Evocation, robo real de buff con Spellsteal y creación/recarga de Mana Sapphire con `200759`.

Para `201459 Arcane Intellect`, formar grupo con otro personaje y confirmar propagación a grupo/banda además de la duración de 1 hora.

## Bloque D — utilidad

```text
.learn 200130
.learn 201953
.learn 200066
.learn 242955
```

`190001 Maestro de Portales` se prueba únicamente desde el draft real para validar facción/TeachMap.

Comprobar Slow Fall sin Light Feather, Blink y limpieza de roots/stuns, Invisibility y cancelación esperada, y Conjure Refreshment con comida usable desde nivel 1 y recuperación escalada.

## Casos especiales

- `55342 Mirror Image`: STANDBY; no probar salvo que se reabra explícitamente.
- `18960 Teleport: Moonglade`: regla racial/lore separada; sólo Elfo de la Noche.
- `Frost Armor 168`: fuera; Ice Armor representa esa línea.
- `Conjure Food 587`, `Conjure Water 5504`, `Ritual of Refreshment 43987`: fuera.
- Arcane Brilliance `23028`: fuera; Arcane Intellect absorbe su targeting grupal.
- Helpers internos (`234913`, `242987`, `261829`, `261830`): nunca son cartas.

## Criterio de cierre

Una carta pasa a APROBADO sólo cuando:

1. aparece/enseña lo correcto;
2. su tooltip coincide razonablemente con runtime;
3. conserva mecánica nativa relevante;
4. escala de forma razonable en nivel bajo y alto;
5. no deja efectos/auras/objetos rotos;
6. no requiere una carta redundante ya absorbida por otra.

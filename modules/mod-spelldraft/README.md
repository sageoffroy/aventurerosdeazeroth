# SpellDraft

SpellDraft es el sistema de progresión sin clases de
**Aventureros de Azeroth**, basado en AzerothCore WotLK 3.3.5a.

## Estado

Bootstrap inicial.

Todavía NO implementa:

- Adventurer / class ID 10
- draft de habilidades
- cartas
- hechizos personalizados
- DBC personalizados
- patches MPQ
- AddOn del cliente

Esas piezas se incorporarán progresivamente sobre esta base.

## Arquitectura

SpellDraft es un módulo normal de AzerothCore:

    modules/mod-spelldraft/

La lógica que necesite scripting dinámico utilizará:

    modules/mod-ale/

No se utilizarán instaladores que modifiquen silenciosamente archivos del core.

Los cambios necesarios sobre AzerothCore deberán quedar versionados
explícitamente en el repositorio Aventureros de Azeroth.

## Directorios

    src/     integración C++ con AzerothCore
    lua/     lógica dinámica ejecutada mediante ALE
    conf/    configuración del servidor

## Principios

1. Un solo sistema SpellDraft.
2. No crear pipelines paralelos.
3. No editar DBC binarios manualmente.
4. No parchear archivos C++ mediante búsquedas/reemplazos durante instalación.
5. Todo cambio al core debe existir como código normal en Git.
6. main permanece estable.
7. Desarrollo en ramas agent/* hasta ser probado.

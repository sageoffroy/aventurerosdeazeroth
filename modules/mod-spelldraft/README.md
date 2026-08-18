# SpellDraft

SpellDraft es el sistema de progresión sin clases de **Aventureros de Azeroth** sobre AzerothCore WotLK 3.3.5a.

## Estado actual

La primera base nativa ya existe y compila:

- `mod-ale` integrado y fijado a una revisión conocida.
- `mod-spelldraft` cargado como módulo estático normal de AzerothCore.
- clase nativa `CLASS_ADVENTURER = 10`.
- Adventurer disponible como base para todas las razas jugables.
- baseline de armas, armaduras, raciales, idiomas, equitación y acciones universales.
- parcheador DBC único para servidor y cliente.
- SQL re-aplicable registrado en `data/sql/custom/db_world/`.
- generador seguro del par de MPQ del cliente.

El sistema de cartas/draft todavía se desarrollará encima de esta base.

## Adventurer

La clase 10 es el contenedor técnico universal. SpellDraft controla la build.

Baseline de nivel 1:

- Worn Short Sword — item 25
- Worn Wooden Shield — item 2362
- Worn Short Bow — item 2504
- Rough Arrow — item 2512
- Riding 75 — skill 762
- Apprentice Riding — spell 33388
- Brown Horse — spell 458
- Auto Shot — spell 75
- Shoot — spell 5019
- Throw — spell 2764
- Dodge / Parry / Block
- todas las proficiencias de armas y armaduras
- raciales e idiomas de la raza elegida

Ver `ADVENTURER.md` para la definición funcional.

## Arquitectura

```text
modules/mod-spelldraft/
├── src/              integración nativa C++
├── lua/              lógica dinámica mediante ALE
├── conf/             configuración
├── client-baseline/  baseline GlueXML congelado
├── sql/              documentación de la ubicación SQL activa
└── tools/            builders, instaladores y validadores
```

La **única fuente SQL activa** de Adventurer es:

```text
data/sql/custom/db_world/spelldraft_adventurer_class_10.sql
```

AzerothCore incluye `$/data/sql/custom/db_world` como fuente `CUSTOM` en `updates_include`, por lo que no mantenemos una segunda copia SQL dentro del módulo.

## Pipeline DBC y cliente

Una sola transformación (`patch_adventurer_class_dbcs.py`) define los DBC de clase 10 para servidor y cliente. No se editan DBC binarios a mano.

El builder de cliente es autosuficiente: usa el baseline versionado en `client-baseline/` y produce dos archivos deliberadamente distintos:

```text
Data/patch-Z.mpq
Data/esES/patch-esES-z.mpq
```

El primero contiene GlueXML; el segundo contiene los DBC Adventurer. Esta separación evita el layout duplicado que daba problemas al cliente 3.3.5a.

## Primera ejecución

Antes de arrancar el servidor puede correrse, sin modificar nada:

```bash
python3 modules/mod-spelldraft/tools/check_first_run.py
```

La secuencia completa está documentada en `FIRST_RUN.md`.

## Principios

1. Un solo sistema SpellDraft.
2. Un solo pipeline DBC para servidor y cliente.
3. Una sola fuente SQL activa.
4. No editar binarios DBC a mano.
5. No usar un `install.sh` que parchee silenciosamente el core.
6. Los cambios al core quedan versionados explícitamente.
7. `main` permanece estable.
8. El desarrollo continúa en ramas `agent/*` hasta ser probado.

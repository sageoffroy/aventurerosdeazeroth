# Primera ejecución de Adventurer

Esta guía describe la primera prueba integrada de **Aventureros de Azeroth** con `CLASS_ADVENTURER = 10`.

El core ya fue compilado correctamente con AzerothCore + ALE + SpellDraft + Adventurer. Los pasos de esta guía preparan configuración, SQL/DBC y cliente; **no requieren recompilar C++**.

## 1. Actualizar la rama local

```bash
cd ~/aventurerosdeazeroth
git pull
```

Seguir en:

```text
agent/spelldraft-bootstrap
```

No cambiar a `main`.

## 2. Chequeo del proyecto

Antes de modificar datos locales:

```bash
python3 modules/mod-spelldraft/tools/validate_repo_assets.py
python3 modules/mod-spelldraft/tools/check_first_run.py
```

Ambos chequeos son de solo lectura.

## 3. Preparación automática recomendada

El layout local recomendado es:

```text
env/dist/
├── bin/
│   ├── authserver
│   └── worldserver
├── etc/
└── data/
    ├── dbc/
    ├── maps/
    ├── vmaps/
    └── mmaps/
```

Si `env/dist/data/dbc` contiene estos cuatro DBC:

```text
ChrClasses.dbc
CharBaseInfo.dbc
CharStartOutfit.dbc
SkillRaceClassInfo.dbc
```

la preparación completa se hace con **un solo comando**, indicando dónde está el cliente WoW:

```bash
python3 modules/mod-spelldraft/tools/prepare_first_run.py \
  --client-dir /mnt/c/RUTA/AL/WOW \
  --locale esES
```

Ese comando, en orden:

1. ejecuta el self-test del proyecto antes de modificar nada;
2. crea los `.conf` que falten sin pisar ninguno existente;
3. configura `DataDir` a `env/dist/data` solamente si acaba de crear `worldserver.conf`;
4. genera los DBC de Adventurer;
5. instala exactamente esos mismos DBC en `env/dist/data/dbc`;
6. genera `Data/patch-Z.mpq` para GlueXML;
7. genera `Data/esES/patch-esES-z.mpq` para los DBC del cliente;
8. hace backup de patches/DBC existentes una sola vez;
9. instala los MPQ en el cliente;
10. borra únicamente `Cache/WDB` del cliente;
11. ejecuta nuevamente el chequeo de primera ejecución.

No inicia MySQL, `authserver` ni `worldserver`.

### Si los DBC limpios están en otro lugar

```bash
python3 modules/mod-spelldraft/tools/prepare_first_run.py \
  --client-dir /mnt/c/RUTA/AL/WOW \
  --dbc-src /RUTA/A/DBC_LIMPIOS \
  --locale esES
```

El destino del servidor sigue siendo `env/dist/data/dbc` salvo que se indique otro `--server-data-dir`.

## 4. Pipeline del cliente

El builder es autosuficiente. El baseline conocido de `CharacterCreate.lua` vive en:

```text
modules/mod-spelldraft/client-baseline/Interface/GlueXML/CharacterCreate.lua
```

No necesita `wowrandom` durante el uso normal.

Los archivos generados quedan en:

```text
modules/mod-spelldraft/build/adventurer-client-patch/Data/patch-Z.mpq
modules/mod-spelldraft/build/adventurer-client-patch/Data/esES/patch-esES-z.mpq
modules/mod-spelldraft/build/adventurer-client-patch/manifest.json
```

Los dos MPQ son deliberadamente distintos: el root contiene GlueXML y el locale contiene DBC. No volver al layout duplicado que podía provocar ERROR #132 en el cliente 3.3.5a.

## 5. SQL de Adventurer

Hay una sola fuente SQL activa en esta rama:

```text
data/sql/updates/pending_db_world/rev_1787027400000000000.sql
```

Es un update pendiente normal de AzerothCore, por lo que `worldserver` lo descubre mediante el updater estándar. La configuración stock actual usa:

```ini
Updates.EnableDatabases = 7
Updates.AutoSetup = 1
```

No se mantiene una copia paralela en `data/sql/custom` ni dentro del módulo.

## 6. Configuración runtime

Los archivos reales esperados son:

```text
env/dist/etc/authserver.conf
env/dist/etc/worldserver.conf
env/dist/etc/modules/mod_ale.conf
env/dist/etc/modules/SpellDraft.conf
```

Para crearlos de forma segura desde sus `.dist`, sin sobrescribir existentes:

```bash
python3 modules/mod-spelldraft/tools/prepare_runtime_configs.py \
  --data-dir ~/aventurerosdeazeroth/env/dist/data
```

SpellDraft debe quedar habilitado:

```ini
SpellDraft.Enable = 1
```

## 7. Arrancar el servidor

Una vez disponibles base de datos y datos runtime:

Terminal 1:

```bash
cd ~/aventurerosdeazeroth/env/dist/bin
./authserver
```

Terminal 2:

```bash
cd ~/aventurerosdeazeroth/env/dist/bin
./worldserver
```

No continuar al cliente si `worldserver` muestra un error de SQL, DBC, maps/vmaps/mmaps o conexión a la base. Corregir la causa primero.

## 8. Primera validación dentro del juego

Crear **un personaje nuevo**. No reutilizar uno creado antes del patch.

Debe cumplirse:

- sólo Adventurer es una clase válida para cada raza jugable;
- class ID real = 10;
- Worn Short Sword (25);
- Worn Wooden Shield (2362);
- Worn Short Bow (2504);
- Rough Arrow (2512);
- Riding 75;
- Apprentice Riding (33388);
- Brown Horse (458);
- Auto Shot (75);
- Shoot (5019);
- Throw (2764);
- raciales correctos de la raza;
- idiomas correctos de la raza;
- Dodge / Parry / Block;
- proficiencias universales de armas y armaduras.

## 9. Si algo falla

No editar DBC ni SQL a mano. Guardar:

- últimas líneas de `authserver` / `worldserver`;
- mensaje de creación del personaje;
- `modules/mod-spelldraft/build/adventurer-client-patch/manifest.json`;
- resultado observado en el cliente.

El pipeline se corrige en los builders y se vuelve a generar.

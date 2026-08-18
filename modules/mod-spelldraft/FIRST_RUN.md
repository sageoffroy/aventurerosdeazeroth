# Primera ejecución de Adventurer

Esta guía describe la primera prueba integrada de **Aventureros de Azeroth** con `CLASS_ADVENTURER = 10`.

## Qué ya está compilado

El binario probado en esta rama contiene:

- AzerothCore actual
- mod-ale
- mod-spelldraft
- CLASS_ADVENTURER = 10
- baseline nativo de Adventurer

Los cambios posteriores de esta guía son SQL, DBC y MPQ; no requieren recompilar el core.

## 1. Actualizar la rama local

```bash
cd ~/aventurerosdeazeroth
git pull
```

No cambiar a `main`.

## 2. Preparar DBC + patch de cliente

Se necesita un directorio con los DBC 3.3.5a limpios/extractados que contenga:

```text
ChrClasses.dbc
CharBaseInfo.dbc
CharStartOutfit.dbc
SkillRaceClassInfo.dbc
```

Ejemplo:

```bash
python3 modules/mod-spelldraft/tools/build_adventurer_client_patch.py \
  --dbc-src /RUTA/A/DBC_LIMPIOS \
  --server-dbc-dir /RUTA/DBC_DEL_SERVIDOR \
  --locale esES
```

El comando aplica exactamente la misma transformación a los DBC del servidor y del cliente.

Salida esperada:

```text
modules/mod-spelldraft/build/adventurer-client-patch/Data/patch-Z.mpq
modules/mod-spelldraft/build/adventurer-client-patch/Data/esES/patch-esES-z.mpq
modules/mod-spelldraft/build/adventurer-client-patch/manifest.json
```

El builder conserva backups `.pre-adventurer.bak` si modifica DBC existentes del servidor.

### GlueXML

El baseline conocido de `CharacterCreate.lua` ya está versionado dentro del propio proyecto:

```text
modules/mod-spelldraft/client-baseline/Interface/GlueXML/CharacterCreate.lua
```

Su procedencia está documentada en `client-baseline/README.md`. El builder transforma ese baseline en memoria y genera el MPQ de manera determinista; **no necesita `wowrandom` ni otro repositorio durante el uso normal**.

Si alguna vez se quiere probar otro baseline 3.3.5a, puede pasarse explícitamente:

```text
--character-create-lua /ruta/CharacterCreate.lua
```

## 3. Instalar el patch en el cliente

Con el cliente accesible desde WSL, por ejemplo `/mnt/c/Juegos/WoW`, ejecutar:

```bash
python3 modules/mod-spelldraft/tools/install_adventurer_client_patch.py \
  --client-dir /mnt/c/RUTA/AL/WOW \
  --patch-dir modules/mod-spelldraft/build/adventurer-client-patch \
  --locale esES
```

El instalador:

- copia `Data/patch-Z.mpq`
- copia `Data/esES/patch-esES-z.mpq`
- respalda un patch previo una sola vez
- borra únicamente `Cache/WDB`

No toca otros MPQ del cliente.

## 4. Base de datos world

La **única fuente SQL activa** de Adventurer está en:

```text
data/sql/custom/db_world/spelldraft_adventurer_class_10.sql
```

AzerothCore incluye oficialmente `$/data/sql/custom/db_world` como fuente `CUSTOM` mediante `updates_include`, y `worldserver.conf.dist` trae por defecto:

```ini
Updates.EnableDatabases = 7
Updates.AutoSetup = 1
```

Por lo tanto, con una instalación normal el `worldserver` puede descubrir/aplicar ese SQL. Si el actualizador está deshabilitado en la configuración real, importar ese archivo manualmente en `acore_world` antes de crear el personaje.

## 5. Datos runtime del servidor

`worldserver.conf.dist` usa por defecto:

```ini
DataDir = "."
```

Eso significa que el directorio desde el que se lance `worldserver` debe poder resolver sus datos (`dbc`, `maps`, `vmaps`, `mmaps`) según la configuración efectiva. Antes de la primera ejecución conviene correr:

```bash
python3 modules/mod-spelldraft/tools/check_first_run.py
```

El chequeo no modifica nada; solamente informa qué falta y qué rutas encontró.

## 6. Configuración

Después de instalar por primera vez, crear los `.conf` reales desde sus `.dist` si todavía no existen:

```text
env/dist/etc/authserver.conf
env/dist/etc/worldserver.conf
env/dist/etc/modules/mod_ale.conf
env/dist/etc/modules/SpellDraft.conf
```

SpellDraft debe quedar:

```ini
SpellDraft.Enable = 1
```

## 7. Primera validación dentro del juego

Crear **un personaje nuevo**. No reutilizar un personaje creado antes del patch.

Debe ocurrir lo siguiente:

- sólo Adventurer es una clase válida para cada raza jugable
- class ID real = 10
- Worn Short Sword (25)
- Worn Wooden Shield (2362)
- Worn Short Bow (2504)
- Rough Arrow (2512)
- Riding 75
- Apprentice Riding (33388)
- Brown Horse (458)
- Auto Shot (75)
- Shoot (5019)
- Throw (2764)
- raciales correctos de la raza
- idiomas correctos de la raza
- Dodge / Parry / Block
- proficiencias universales de armas y armaduras

## 8. Si algo falla

No modificar DBC ni SQL a mano. Guardar:

- últimas líneas de `worldserver`
- mensaje de creación del personaje
- `manifest.json` del patch
- resultado observado en el cliente

El pipeline se corrige en los builders y se vuelve a generar.

# WotLK GlueXML baseline

Este directorio conserva únicamente el baseline de `CharacterCreate.lua` que necesita el builder de Adventurer.

Origen histórico validado:

- repositorio de referencia: `sageoffroy/wowrandom`
- commit congelado: `8e2c3c8c89d857164e33dda7db2cccd185467cdb`
- blob original `CharacterCreate.lua`: `d940b49c21231d8333b5c45e2a026c5504c4bbd5`

El archivo se versiona aquí para que **Aventureros de Azeroth sea autosuficiente**. El builder no necesita el repositorio viejo durante el uso normal.

No editar este baseline para cambiar la lógica de Adventurer. Los cambios funcionales deben hacerse en `tools/build_adventurer_client_patch.py`, que transforma el baseline de forma determinista al generar `patch-Z.mpq`.

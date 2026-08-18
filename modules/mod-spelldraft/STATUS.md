# Estado de SpellDraft

Estado de la rama `agent/spelldraft-bootstrap` antes de la primera prueba integrada.

## Confirmado

- [x] AzerothCore actual compila.
- [x] `mod-ale` compila e instala sus extensiones.
- [x] `mod-spelldraft` es detectado como módulo estático.
- [x] `CLASS_ADVENTURER = 10` compila en el core.
- [x] `AdventurerClass.cpp` compila dentro de `worldserver`.
- [x] `authserver` fue instalado correctamente.
- [x] `worldserver` fue instalado correctamente.
- [x] `SpellDraft.conf.dist` fue instalado.
- [x] bootstrap Lua fue instalado.
- [x] baseline obligatorio de Adventurer está versionado.
- [x] SQL de world está versionado como update pendiente normal de AzerothCore.
- [x] builder DBC usa una única transformación para servidor y cliente.
- [x] builder MPQ usa payload root/locale separado.
- [x] builder del cliente es autosuficiente: no necesita `wowrandom`.
- [x] instalador del cliente conserva backups y limpia solamente `Cache/WDB`.
- [x] existe un self-test estático del pipeline.
- [x] existe CI específica para el self-test y el linter SQL.
- [x] la capa de recursos classless fue separada del viejo monolito y migrada a `lua/SpellDraft/resources.lua`.
- [x] los cambios Lua pueden stagedarse al runtime sin recompilar C++.

## Falta validar localmente / dentro del juego

- [ ] disponibilidad de `dbc/maps/vmaps/mmaps` en el runtime local.
- [ ] bases `acore_auth`, `acore_characters`, `acore_world` instaladas y accesibles.
- [ ] updater aplicando el update pendiente de Adventurer.
- [ ] `worldserver` cargando los DBC modificados de clase 10.
- [ ] ALE cargando `SpellDraft/resources.lua` sin errores.
- [ ] Rage visible + pools de Mana/Energy/Runic disponibles para class 10.
- [ ] cliente 3.3.5a cargando el par de MPQ sin ERROR #132.
- [ ] una única clase válida por cada raza en creación de personaje.
- [ ] creación real de un personaje Adventurer ID 10.
- [ ] outfit: espada 25, escudo 2362, arco 2504 y flechas 2512.
- [ ] Riding 75 + Apprentice Riding 33388 + Brown Horse 458.
- [ ] Auto Shot 75 + Shoot 5019 + Throw 2764.
- [ ] raciales e idiomas correctos.
- [ ] todas las proficiencias, Dodge, Parry y Block.

## SpellDraft jugable

La migración completa del motor de cartas todavía no está terminada. El sistema histórico fue localizado y estudiado, pero mezcla draft, prestige, tienda, talentos, rerolls, consumibles y Mystic Enchants en archivos grandes.

La migración nueva separa las responsabilidades:

1. estado/persistencia del draft;
2. **recursos classless del Adventurer — migrado**;
3. pool y reglas de elegibilidad;
4. generación de ofertas;
5. aprendizaje/reemplazo de spells;
6. protocolo con el AddOn de cartas;
7. UI del AddOn;
8. prestige/shop/enchants como sistemas opcionales posteriores.

No se copiará el monolito histórico a ciegas. La primera prueba integrada valida primero la plataforma nativa (clase 10 + recursos + DBC + SQL + cliente) sobre la que se montará el motor de cartas.

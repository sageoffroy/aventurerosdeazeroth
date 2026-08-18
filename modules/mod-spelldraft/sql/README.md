# SpellDraft SQL

El SQL activo de SpellDraft/Adventurer no se duplica dentro del módulo.

La fuente única para la base `world` es:

```text
data/sql/custom/db_world/spelldraft_adventurer_class_10.sql
```

Esa ubicación es parte del pipeline `CUSTOM` oficial de AzerothCore y es descubierta mediante `updates_include`.

Si se cambia la definición SQL de Adventurer, se modifica **solamente** ese archivo.

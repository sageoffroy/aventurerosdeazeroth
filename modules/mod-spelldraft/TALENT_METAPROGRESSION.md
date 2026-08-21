# SpellDraft - Talentos y metaprogresión

Primer corte funcional del sistema de metaprogresión de **Aventureros de Azeroth**.

## Separación de progresiones

- **Habilidades:** siguen perteneciendo al SpellDraft normal y a la vida actual.
- **Talentos:** una elección en nivel 10 y luego cada 2 niveles hasta 80.
- **Honor:** saldo persistente por `account_id`.
- **Familias desbloqueadas:** persistentes por `account_id`.
- **Rangos elegidos:** persistentes solamente por `player_guid`.

La muerte/eliminación de un superviviente no elimina el Honor ni las familias que la cuenta compró.

## Flujo de nivel

Con la configuración inicial:

- nivel 1: 3 elecciones de habilidad;
- nivel 5: +1 habilidad;
- nivel 10: +1 habilidad y, después de resolverla, `Talento (1)`;
- nivel 12: `Talento (2)`;
- nivel 14: `Talento (3)`;
- ...;
- nivel 80: `Talento (36)`.

Si un personaje acumula elecciones de habilidad pendientes, los talentos esperan hasta que termine de resolver el draft normal.

## Protocolo

Las habilidades siguen enviando:

```text
SpellChoiceIsTalent = 0
```

Las ofertas del nuevo sistema envían:

```text
SpellChoiceIsTalent = 1
```

La respuesta del addon sigue siendo `SC:<spell_id>`. El wrapper `draft.lua` decide si esa respuesta pertenece al draft normal o a una oferta de talento.

## Catálogo v1

El primer catálogo usa talentos pasivos nativos de WotLK exclusivamente para validar el circuito completo. Está separado en `talent_catalog.lua` para poder sustituirlos por talentos genéricos/custom sin rediseñar el motor ni la base de datos.

Tres familias están desbloqueadas desde el inicio. Las restantes se compran con Honor de cuenta.

## Comandos temporales de prueba

Mostrar saldo y catálogo:

```text
!talentos
```

Comprar una familia:

```text
!talentos comprar divine_intellect
```

Solo GM, para pruebas mientras Dungeon Master todavía no entrega Honor:

```text
!talentos darhonor 500
```

El comando de prueba se elimina cuando Dungeon Master sea la fuente real de la moneda.

## Persistencia

Update de `acore_characters`:

```text
data/sql/updates/pending_db_characters/rev_1787334300000000000.sql
```

Tablas:

- `spelldraft_account_progress`
- `spelldraft_account_talents`
- `spelldraft_character_talents`
- `spelldraft_pending_talent_offer`

## Pendiente después de validar este corte

1. Reemplazar los talentos nativos prototipo por talentos genéricos propios.
2. Conectar recompensas de Dungeon Master/Roguelike al Honor de cuenta.
3. Llevar la compra de talentos a una UI/NPC definitiva.
4. Retirar el grimorio viejo de SpellDraft.

-- Aventureros de Azeroth - catalogo de metaprogresion.
--
-- Este archivo define que familias de talento existen para la cuenta y cuanto
-- cuesta desbloquearlas. No define como se aprenden ni como se ofrecen: eso
-- pertenece al motor de talento por vida.

if AventurerosProgressionCatalog then
    return
end

AventurerosProgressionCatalog = {
    {
        id = "precision",
        label = "Precisión",
        starter = true,
        cost = 0,
    },
    {
        id = "cruelty",
        label = "Crueldad",
        starter = true,
        cost = 0,
    },
    {
        id = "anticipation",
        label = "Anticipación",
        starter = true,
        cost = 0,
    },
    {
        id = "divine_intellect",
        label = "Intelecto divino",
        starter = false,
        cost = 100,
    },
    {
        id = "deflection",
        label = "Desvío",
        starter = false,
        cost = 125,
    },
    {
        id = "toughness",
        label = "Dureza",
        starter = false,
        cost = 150,
    },
    {
        id = "divine_strength",
        label = "Fuerza divina",
        starter = false,
        cost = 150,
    },
    {
        id = "benediction",
        label = "Benedicción",
        starter = false,
        cost = 175,
    },
}

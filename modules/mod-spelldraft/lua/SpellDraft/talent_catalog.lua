-- Aventureros de Azeroth - primer catálogo de talentos de metaprogresión.
--
-- Esta versión usa pasivos nativos de WotLK como prueba funcional del circuito
-- cuenta -> desbloqueo -> oferta Talento (N) -> rango por personaje.
-- Cuando definamos los talentos genéricos definitivos, este archivo es la pieza
-- que cambia; la persistencia y el motor no necesitan rediseñarse.

SpellDraftTalentCatalog = {
    {
        id = "precision",
        label = "Precisión",
        starter = true,
        cost = 0,
        ranks = {13705, 13832, 13843, 13844, 13845},
    },
    {
        id = "cruelty",
        label = "Crueldad",
        starter = true,
        cost = 0,
        ranks = {12320, 12852, 12853, 12855, 12856},
    },
    {
        id = "anticipation",
        label = "Anticipación",
        starter = true,
        cost = 0,
        ranks = {20096, 20097, 20098, 20099, 20100},
    },
    {
        id = "divine_intellect",
        label = "Intelecto divino",
        starter = false,
        cost = 100,
        ranks = {20257, 20258, 20259, 20260, 20261},
    },
    {
        id = "deflection",
        label = "Desvío",
        starter = false,
        cost = 125,
        ranks = {16462, 16463, 16464, 16465, 16466},
    },
    {
        id = "toughness",
        label = "Dureza",
        starter = false,
        cost = 150,
        ranks = {20143, 20144, 20145, 20146, 20147},
    },
    {
        id = "divine_strength",
        label = "Fuerza divina",
        starter = false,
        cost = 150,
        ranks = {20262, 20263, 20264, 20265, 20266},
    },
    {
        id = "benediction",
        label = "Benedicción",
        starter = false,
        cost = 175,
        ranks = {20101, 20102, 20103, 20104, 20105},
    },
}

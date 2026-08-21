-- Aventureros de Azeroth - talentos ofrecibles por vida.
--
-- Solo define familias y rangos de spell. El desbloqueo/costo por cuenta vive
-- en catalog.lua y la economia vive en account.lua.

if AventurerosTalentCatalog then
    return
end

AventurerosTalentCatalog = {
    {
        id = "precision",
        label = "Precisión",
        ranks = {13705, 13832, 13843, 13844, 13845},
    },
    {
        id = "cruelty",
        label = "Crueldad",
        ranks = {12320, 12852, 12853, 12855, 12856},
    },
    {
        id = "anticipation",
        label = "Anticipación",
        ranks = {20096, 20097, 20098, 20099, 20100},
    },
    {
        id = "divine_intellect",
        label = "Intelecto divino",
        ranks = {20257, 20258, 20259, 20260, 20261},
    },
    {
        id = "deflection",
        label = "Desvío",
        ranks = {16462, 16463, 16464, 16465, 16466},
    },
    {
        id = "toughness",
        label = "Dureza",
        ranks = {20143, 20144, 20145, 20146, 20147},
    },
    {
        id = "divine_strength",
        label = "Fuerza divina",
        ranks = {20262, 20263, 20264, 20265, 20266},
    },
    {
        id = "benediction",
        label = "Benedicción",
        ranks = {20101, 20102, 20103, 20104, 20105},
    },
}

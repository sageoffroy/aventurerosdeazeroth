#ifndef AVENTUREROS_CUSTOM_SPELL_THREAT_H
#define AVENTUREROS_CUSTOM_SPELL_THREAT_H

#include "Define.h"

class Player;

void ConfigureCustomSpellThreat(bool enabled);
bool GetCustomSpellThreatRule(
    Player const* player,
    uint32 spellId,
    int32& flatMod,
    float& pctMod,
    float& apPctMod);

#endif

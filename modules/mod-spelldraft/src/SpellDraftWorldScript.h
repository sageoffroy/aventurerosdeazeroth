#ifndef AVENTUREROS_SPELLDRAFT_WORLD_SCRIPT_H
#define AVENTUREROS_SPELLDRAFT_WORLD_SCRIPT_H

#include "WorldScript.h"

class SpellDraftWorldScript : public WorldScript
{
public:
    SpellDraftWorldScript()
        : WorldScript("SpellDraftWorldScript", {
            WORLDHOOK_ON_AFTER_CONFIG_LOAD
        })
    {
    }

    void OnAfterConfigLoad(bool reload) override;
};

void AddSpellDraftScripts();

#endif

#ifndef AVENTUREROS_SPELLDRAFT_WORLD_SCRIPT_H
#define AVENTUREROS_SPELLDRAFT_WORLD_SCRIPT_H

#include "WorldScript.h"

class SpellDraftWorldScript : public WorldScript
{
public:
    SpellDraftWorldScript()
        : WorldScript("SpellDraftWorldScript", {
            WORLDHOOK_ON_AFTER_CONFIG_LOAD,
            WORLDHOOK_ON_STARTUP
        })
    {
    }

    void OnAfterConfigLoad(bool reload) override;
    void OnStartup() override;
};

void AddSpellDraftScripts();

#endif

#include "SpellDraftWorldScript.h"

#include "CustomSpellScaling.h"
#include "Configuration/Config.h"
#include "Log.h"

namespace
{
bool SpellDraftEnabled()
{
    return sConfigMgr->GetOption<bool>("SpellDraft.Enable", true);
}
}

void SpellDraftWorldScript::OnAfterConfigLoad(bool reload)
{
    if (!reload)
        return;

    bool const enabled = SpellDraftEnabled();
    ConfigureCustomSpellScaling(enabled);
    LOG_INFO(
        "module.SpellDraft",
        "Aventureros de Azeroth: SpellDraft config reloaded. Enabled: {}.",
        enabled
    );
}

void SpellDraftWorldScript::OnStartup()
{
    bool const enabled = SpellDraftEnabled();
    ConfigureCustomSpellScaling(enabled);
    LOG_INFO(
        "module.SpellDraft",
        "Aventureros de Azeroth: SpellDraft bootstrap loaded. Enabled: {}.",
        enabled
    );
}

void AddSpellDraftScripts()
{
    new SpellDraftWorldScript();
}

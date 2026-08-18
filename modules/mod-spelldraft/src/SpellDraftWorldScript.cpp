#include "SpellDraftWorldScript.h"

#include "Configuration/Config.h"
#include "Log.h"

void SpellDraftWorldScript::OnAfterConfigLoad(bool reload)
{
    bool const enabled =
        sConfigMgr->GetOption<bool>("SpellDraft.Enable", true);

    LOG_INFO(
        "module.SpellDraft",
        "Aventureros de Azeroth: SpellDraft bootstrap loaded. Enabled: {}. Reload: {}.",
        enabled,
        reload
    );
}

void AddSpellDraftScripts()
{
    new SpellDraftWorldScript();
}

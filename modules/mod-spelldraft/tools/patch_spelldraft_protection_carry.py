#!/usr/bin/env python3
"""Fix SpellDraft protection carry semantics in the staged Lua runtime.

A protected card belongs to the next *real* draft, not merely the next offer
that exists immediately. Therefore protection must survive periods where the
character has zero drafts available and only be consumed when a later draft
actually delivers the protected card.
"""

from __future__ import annotations

from pathlib import Path


class ProtectionCarryPatchError(RuntimeError):
    pass


PATCHES = (
    (
        "zero-draft cleanup",
        '''    if DraftsRemaining(player) <= 0 then\n        local resources = GrantProgressionResources(player)\n        if resources.protectedSpellId > 0 then\n            resources.protections = resources.protections + 1\n            resources.protectedSpellId = 0\n            SaveDraftResources(player:GetGUIDLow(), resources)\n            SendCompatibilityState(player)\n        end\n        ClearPendingOffer(player:GetGUIDLow())\n        player:SendAddonMessage("SpellChoiceClose", "", 0, player)\n        return\n    end\n''',
        '''    if DraftsRemaining(player) <= 0 then\n        -- A protected card may legitimately wait while the character has no\n        -- draft available. Keep protectedSpellId persisted until the next real\n        -- offer is earned.\n        ClearPendingOffer(player:GetGUIDLow())\n        player:SendAddonMessage("SpellChoiceClose", "", 0, player)\n        return\n    end\n''',
    ),
    (
        "last-pick cleanup",
        '''    if DraftsRemaining(player) > 0 then\n        EnsureAndSendOffer(player)\n    else\n        resources = GrantProgressionResources(player)\n        if resources.protectedSpellId > 0 then\n            resources.protections = resources.protections + 1\n            resources.protectedSpellId = 0\n            SaveDraftResources(guid, resources)\n            SendCompatibilityState(player)\n        end\n        player:SendAddonMessage("SpellChoiceClose", "", 0, player)\n    end\n''',
        '''    if DraftsRemaining(player) > 0 then\n        EnsureAndSendOffer(player)\n    else\n        -- If this was the last currently available draft, a paid protection\n        -- remains attached to its card until progression grants another draft.\n        player:SendAddonMessage("SpellChoiceClose", "", 0, player)\n    end\n''',
    ),
    (
        "last-draft denial",
        '''    -- Protection is meaningful only when another draft remains after the\n    -- current pick. Prevent wasting the final protection on the last choice.\n    if DraftsRemaining(player) <= 1 then\n        player:SendAddonMessage("SpellChoiceProtectDenied", "last", 0, player)\n        return\n    end\n\n''',
        '''    -- Protection may be used on the last currently available draft. If no\n    -- immediate draft remains, the protected card waits in persistence until\n    -- progression grants the next real draft offer.\n\n''',
    ),
)


def patch_protection_carry(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    changed = False

    for label, old, new in PATCHES:
        old_count = text.count(old)
        new_count = text.count(new)

        if old_count == 1:
            text = text.replace(old, new, 1)
            changed = True
            continue

        if old_count == 0 and new_count == 1:
            continue

        raise ProtectionCarryPatchError(
            f"{path}: {label}: expected one old block or one patched block; "
            f"found old={old_count}, patched={new_count}"
        )

    if changed:
        path.write_text(text, encoding="utf-8")

    verify = path.read_text(encoding="utf-8")
    forbidden = (
        'SpellChoiceProtectDenied", "last"',
        "resources.protections = resources.protections + 1\n            resources.protectedSpellId = 0\n            SaveDraftResources(player:GetGUIDLow(), resources)",
    )
    for marker in forbidden:
        if marker in verify:
            raise ProtectionCarryPatchError(
                f"{path}: stale protection-carry behavior remains: {marker!r}"
            )

    return changed


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("runtime", type=Path)
    args = parser.parse_args()

    try:
        changed = patch_protection_carry(args.runtime.expanduser().resolve())
    except ProtectionCarryPatchError as exc:
        raise SystemExit(f"SpellDraft protection carry patch aborted: {exc}") from exc

    print(
        "SpellDraft protection carry "
        + ("patched" if changed else "already valid")
    )

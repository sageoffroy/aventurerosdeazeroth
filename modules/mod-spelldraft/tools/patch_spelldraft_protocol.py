#!/usr/bin/env python3
"""Move SpellDraft client commands off self-whispers.

The historical addon sends SC_* commands by whispering the current character.
That transport is fragile on stock AzerothCore and can fail with "player not
found" even though the character is online. Aventureros uses normal SAY chat as
a hidden transport instead: ALE intercepts PLAYER_EVENT_ON_CHAT before the
message is broadcast and the same Lua protocol handler consumes it.

This tool patches only generated/runtime files and the installed loose addon.
No C++ rebuild is required.
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path


class ProtocolPatchError(RuntimeError):
    pass


SERVER_OLD = "RegisterPlayerEvent(19, OnProtocolWhisper) -- PLAYER_EVENT_ON_WHISPER"
SERVER_NEW = (
    "RegisterPlayerEvent(18, OnProtocolWhisper) -- PLAYER_EVENT_ON_CHAT (SC transport)\n"
    "RegisterPlayerEvent(19, OnProtocolWhisper) -- PLAYER_EVENT_ON_WHISPER (legacy compatibility)"
)

CLIENT_SEND_RE = re.compile(
    r',\s*"WHISPER",\s*GetFactionLanguage\(\),\s*(?:target|UnitName\("player"\))\)'
)


def patch_server_runtime(path: Path) -> int:
    if not path.is_file():
        raise ProtocolPatchError(f"SpellDraft runtime not found: {path}")

    text = path.read_text(encoding="utf-8")
    if SERVER_NEW in text:
        changed = 0
    else:
        count = text.count(SERVER_OLD)
        if count != 1:
            raise ProtocolPatchError(
                f"{path}: expected exactly one legacy whisper registration, found {count}"
            )
        text = text.replace(SERVER_OLD, SERVER_NEW, 1)
        path.write_text(text, encoding="utf-8")
        changed = 1

    checked = path.read_text(encoding="utf-8")
    if "RegisterPlayerEvent(18, OnProtocolWhisper)" not in checked:
        raise ProtocolPatchError(f"{path}: PLAYER_EVENT_ON_CHAT bridge was not installed")
    if "RegisterPlayerEvent(19, OnProtocolWhisper)" not in checked:
        raise ProtocolPatchError(f"{path}: legacy whisper compatibility was lost")
    return changed


def patch_client_addon(path: Path) -> int:
    if not path.is_file():
        raise ProtocolPatchError(f"SpellDraft client addon not found: {path}")

    text = path.read_text(encoding="utf-8")
    output: list[str] = []
    changed = 0

    for line in text.splitlines(keepends=True):
        if 'SendChatMessage("SC' in line and '"WHISPER"' in line:
            patched, count = CLIENT_SEND_RE.subn(', "SAY")', line)
            if count != 1:
                raise ProtocolPatchError(
                    f"{path}: unsupported SC whisper form: {line.strip()}"
                )
            line = patched
            changed += 1
        output.append(line)

    patched_text = "".join(output)
    legacy_lines = [
        line.strip()
        for line in patched_text.splitlines()
        if 'SendChatMessage("SC' in line and '"WHISPER"' in line
    ]
    if legacy_lines:
        raise ProtocolPatchError(
            f"{path}: SC self-whispers remain after patch: " + "; ".join(legacy_lines)
        )

    if 'SendChatMessage("SC_CHECK", "SAY")' not in patched_text:
        raise ProtocolPatchError(f"{path}: SC_CHECK SAY transport not found after patch")
    if 'SendChatMessage("SC:" .. spellID, "SAY")' not in patched_text:
        raise ProtocolPatchError(f"{path}: card-pick SAY transport not found after patch")

    if changed:
        backup = path.with_name(path.name + ".aventureros-original")
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(patched_text, encoding="utf-8")

    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--install-dir", required=True, type=Path)
    parser.add_argument("--client-dir", required=True, type=Path)
    args = parser.parse_args()

    install = args.install_dir.expanduser().resolve()
    client = args.client_dir.expanduser().resolve()
    runtime = install / "bin" / "lua_scripts" / "SpellDraft" / "draft.lua"
    addon = client / "Interface" / "AddOns" / "SpellDraft" / "SpellChoice.lua"

    try:
        server_changed = patch_server_runtime(runtime)
        client_changed = patch_client_addon(addon)
    except ProtocolPatchError as exc:
        raise SystemExit(f"SpellDraft protocol patch aborted: {exc}") from exc

    print("SpellDraft protocol transport validated:")
    print(
        "  server runtime: "
        + ("patched PLAYER_EVENT_ON_CHAT bridge" if server_changed else "already patched")
    )
    print(
        "  client addon:   "
        + (f"patched {client_changed} SC self-whisper call(s) to hidden SAY" if client_changed else "already patched")
    )
    print("  legacy server whisper listener retained for compatibility")
    print("  no C++ rebuild required")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Move Mystic Enchant client/server self-whispers to hidden SAY transport.

The historical SpellDraft random-enchant UI talks to the current character via
self-whispers. Stock AzerothCore can reject those messages with "player not
found" during login. Aventureros keeps the legacy whisper listener for
compatibility but adds PLAYER_EVENT_ON_CHAT and sends SDRE_* traffic through SAY,
which ALE consumes and suppresses before normal chat broadcast.

This patches only installed/runtime Lua and the loose client addon. No C++
rebuild or DBC regeneration is required.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


class PatchError(RuntimeError):
    pass


SERVER_OLD = "RegisterPlayerEvent(19, OnWhisper)             -- PLAYER_EVENT_ON_WHISPER"
SERVER_NEW = (
    "RegisterPlayerEvent(18, OnWhisper)             -- PLAYER_EVENT_ON_CHAT (SDRE transport)\n"
    "    RegisterPlayerEvent(19, OnWhisper)             -- PLAYER_EVENT_ON_WHISPER (legacy compatibility)"
)

CLIENT_RETOOLTIP_OLD = 'SendChatMessage("SDRE_SYNC", "WHISPER", nil, UnitName("player"))'
CLIENT_RETOOLTIP_NEW = 'SendChatMessage("SDRE_SYNC", "SAY")'

CLIENT_RESERVICES_OLD = 'SendChatMessage(msg, "WHISPER", nil, UnitName("player"))'
CLIENT_RESERVICES_NEW = 'SendChatMessage(msg, "SAY")'


def backup_once(path: Path) -> None:
    backup = path.with_name(path.name + ".aventureros-original")
    if not backup.exists():
        shutil.copy2(path, backup)


def replace_once(path: Path, old: str, new: str, label: str) -> bool:
    if not path.is_file():
        raise PatchError(f"missing {label}: {path}")

    text = path.read_text(encoding="utf-8")
    if new in text:
        return False

    count = text.count(old)
    if count != 1:
        raise PatchError(f"{path}: expected one {label} pattern, found {count}")

    backup_once(path)
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


def patch_server(path: Path) -> bool:
    changed = replace_once(path, SERVER_OLD, SERVER_NEW, "SDRE server listener")
    checked = path.read_text(encoding="utf-8")
    if "RegisterPlayerEvent(18, OnWhisper)" not in checked:
        raise PatchError(f"{path}: SDRE PLAYER_EVENT_ON_CHAT listener missing")
    if "RegisterPlayerEvent(19, OnWhisper)" not in checked:
        raise PatchError(f"{path}: legacy SDRE whisper listener missing")
    return changed


def patch_client(retooltip: Path, reservices: Path) -> int:
    changed = 0
    if replace_once(
        retooltip,
        CLIENT_RETOOLTIP_OLD,
        CLIENT_RETOOLTIP_NEW,
        "RETooltip SDRE_SYNC transport",
    ):
        changed += 1
    if replace_once(
        reservices,
        CLIENT_RESERVICES_OLD,
        CLIENT_RESERVICES_NEW,
        "REServices SDRE transport",
    ):
        changed += 1

    for path in (retooltip, reservices):
        checked = path.read_text(encoding="utf-8")
        if '"SDRE_' in checked and '"WHISPER"' in checked:
            # RETooltip has a literal SDRE_* call; REServices routes through
            # SendServer(msg), so the generic sender validation above is the
            # authoritative check for that file.
            if path == retooltip:
                raise PatchError(f"{path}: SDRE self-whisper still present")

    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--install-dir", required=True, type=Path)
    parser.add_argument("--client-dir", required=True, type=Path)
    args = parser.parse_args()

    install = args.install_dir.expanduser().resolve()
    client = args.client_dir.expanduser().resolve()

    server = install / "bin" / "lua_scripts" / "SpellDraft" / "spelldraft_re.lua"
    addon = client / "Interface" / "AddOns" / "SpellDraft"
    retooltip = addon / "RETooltip.lua"
    reservices = addon / "REServices.lua"

    try:
        server_changed = patch_server(server)
        client_changed = patch_client(retooltip, reservices)
    except PatchError as exc:
        raise SystemExit(f"SpellDraft SDRE protocol patch aborted: {exc}") from exc

    print("SpellDraft Mystic Enchant protocol validated:")
    print(
        "  server runtime: "
        + ("patched hidden SAY listener" if server_changed else "already patched")
    )
    print(
        "  client addon:   "
        + (f"patched {client_changed} SDRE sender file(s)" if client_changed else "already patched")
    )
    print("  legacy whisper listener retained for compatibility")
    print("  restart worldserver and fully restart WoW to test")
    print("  no C++ rebuild / DBC / MPQ regeneration required")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Stage versioned SpellDraft Lua files into an installed ALE runtime."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from patch_spelldraft_protocol import ProtocolPatchError, patch_server_runtime

TOOLS = Path(__file__).resolve().parent
MODULE = TOOLS.parent
REPO = MODULE.parents[1]
DEFAULT_INSTALL = REPO / "env" / "dist"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--install-dir", type=Path, default=DEFAULT_INSTALL)
    args = parser.parse_args()

    install = args.install_dir.expanduser().resolve()
    source = MODULE / "lua"
    destination = install / "bin" / "lua_scripts"

    if not source.is_dir():
        raise SystemExit(f"SpellDraft Lua source directory not found: {source}")
    if not (install / "bin" / "worldserver").is_file():
        raise SystemExit(f"Installed worldserver not found under: {install / 'bin'}")

    copied = 0
    for path in sorted(source.rglob("*.lua")):
        relative = path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied += 1
        print(f"STAGE: {relative}")

    runtime_draft = destination / "SpellDraft" / "draft.lua"
    try:
        protocol_changed = patch_server_runtime(runtime_draft)
    except ProtocolPatchError as exc:
        raise SystemExit(f"SpellDraft runtime protocol patch aborted: {exc}") from exc

    print(
        "STAGE: SpellDraft protocol CHAT bridge "
        + ("patched" if protocol_changed else "already valid")
    )
    print(f"SpellDraft Lua runtime staged: {copied} file(s) -> {destination}")


if __name__ == "__main__":
    main()

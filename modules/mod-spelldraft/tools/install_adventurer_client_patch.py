#!/usr/bin/env python3
"""Install generated Adventurer MPQs into a local WoW 3.3.5a client safely."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def backup_once(path: Path) -> None:
    if not path.exists():
        return
    backup = path.with_name(path.name + ".pre-adventurer.bak")
    if not backup.exists():
        shutil.copy2(path, backup)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client-dir", required=True, type=Path,
                        help="WoW 3.3.5a client directory containing Wow.exe and Data/")
    parser.add_argument("--patch-dir", required=True, type=Path,
                        help="Output directory created by build_adventurer_client_patch.py")
    parser.add_argument("--locale", default="esES")
    args = parser.parse_args()

    client = args.client_dir.expanduser().resolve()
    patch_dir = args.patch_dir.expanduser().resolve()

    wow_exe = client / "Wow.exe"
    if not wow_exe.is_file():
        wow_exe = client / "wow.exe"
    if not wow_exe.is_file():
        raise SystemExit(f"Not a WoW client directory: no Wow.exe in {client}")

    source_root = patch_dir / "Data" / "patch-Z.mpq"
    source_locale = patch_dir / "Data" / args.locale / f"patch-{args.locale}-z.mpq"
    if not source_root.is_file() or not source_locale.is_file():
        raise SystemExit(
            "Generated patch pair not found. Expected:\n"
            f"  {source_root}\n"
            f"  {source_locale}"
        )

    target_root = client / "Data" / "patch-Z.mpq"
    target_locale = client / "Data" / args.locale / f"patch-{args.locale}-z.mpq"
    target_locale.parent.mkdir(parents=True, exist_ok=True)

    backup_once(target_root)
    backup_once(target_locale)
    shutil.copy2(source_root, target_root)
    shutil.copy2(source_locale, target_locale)

    # WoW caches DBC-derived client data. Removing WDB is safe; the client
    # recreates it on the next launch. Do not delete any broader client data.
    wdb = client / "Cache" / "WDB"
    if wdb.exists():
        shutil.rmtree(wdb)

    print("Adventurer client patch installed:")
    print(f"  {target_root}")
    print(f"  {target_locale}")
    print("  Cache/WDB cleared")


if __name__ == "__main__":
    main()

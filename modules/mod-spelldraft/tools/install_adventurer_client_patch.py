#!/usr/bin/env python3
"""Install generated Adventurer MPQs into a local WoW 3.3.5a client safely.

Client patch ownership is fixed by project convention:

* P is reserved for SpellDraft UI/assets.
* Z is reserved for Aventureros de Azeroth / Adventurer DBC + GlueXML.

This installer owns only the Z pair. It never falls back to another suffix and
never overwrites an unexpected file occupying that reserved slot.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

OWNER_MANIFEST = ".aventureros-spelldraft.json"
ADVENTURER_SUFFIX = "Z"
SPELLDRAFT_SUFFIX = "P"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative_to_client(path: Path, client: Path) -> str:
    return path.relative_to(client).as_posix()


def load_owner_manifest(client: Path) -> dict | None:
    path = client / OWNER_MANIFEST
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Invalid {OWNER_MANIFEST}: {exc}") from exc
    if data.get("owner") != "Aventureros de Azeroth / SpellDraft":
        raise SystemExit(
            f"Refusing to trust {path}: owner marker does not match SpellDraft"
        )
    return data


def verify_existing_owned_file(target: Path, expected_hash: str | None) -> None:
    if not target.exists():
        return
    if not target.is_file():
        raise SystemExit(f"Reserved patch target is not a file: {target}")
    if not expected_hash:
        raise SystemExit(
            "Reserved Adventurer patch slot is already occupied and there is no "
            f"SpellDraft ownership record:\n  {target}\nNothing was overwritten."
        )
    actual = sha256(target)
    if actual != expected_hash:
        raise SystemExit(
            "Reserved Adventurer patch changed outside SpellDraft. Refusing to overwrite:\n"
            f"  {target}\n"
            f"  manifest sha256: {expected_hash}\n"
            f"  current  sha256: {actual}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--client-dir",
        required=True,
        type=Path,
        help="WoW 3.3.5a client directory containing Wow.exe and Data/",
    )
    parser.add_argument(
        "--patch-dir",
        required=True,
        type=Path,
        help="Output directory created by build_adventurer_client_patch.py",
    )
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
            "Generated Adventurer patch pair not found. Expected:\n"
            f"  {source_root}\n"
            f"  {source_locale}"
        )

    target_root = client / "Data" / f"patch-{ADVENTURER_SUFFIX}.mpq"
    target_locale = (
        client / "Data" / args.locale / f"patch-{args.locale}-{ADVENTURER_SUFFIX.lower()}.mpq"
    )
    target_locale.parent.mkdir(parents=True, exist_ok=True)

    previous = load_owner_manifest(client)
    if previous:
        if previous.get("locale") != args.locale:
            raise SystemExit(
                f"Existing SpellDraft install uses locale {previous.get('locale')!r}; "
                f"requested {args.locale!r}."
            )
        verify_existing_owned_file(target_root, previous.get("root_sha256"))
        verify_existing_owned_file(target_locale, previous.get("locale_sha256"))
    else:
        verify_existing_owned_file(target_root, None)
        verify_existing_owned_file(target_locale, None)

    shutil.copy2(source_root, target_root)
    shutil.copy2(source_locale, target_locale)

    manifest = {
        "owner": "Aventureros de Azeroth / SpellDraft",
        "version": 2,
        "locale": args.locale,
        "reserved_slots": {
            "spelldraft": SPELLDRAFT_SUFFIX,
            "aventureros": ADVENTURER_SUFFIX,
        },
        "root_patch": relative_to_client(target_root, client),
        "root_sha256": sha256(target_root),
        "locale_patch": relative_to_client(target_locale, client),
        "locale_sha256": sha256(target_locale),
        "generated_root_sha256": sha256(source_root),
        "generated_locale_sha256": sha256(source_locale),
    }
    (client / OWNER_MANIFEST).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # WoW caches DBC-derived client data. Removing WDB is safe; the client
    # recreates it on the next launch. Do not delete any broader client data.
    wdb = client / "Cache" / "WDB"
    if wdb.exists():
        shutil.rmtree(wdb)

    print("Adventurer client patch installed in the reserved Z slot:")
    print(f"  {target_root}")
    print(f"  {target_locale}")
    print(f"  P remains reserved for SpellDraft assets: patch-{SPELLDRAFT_SUFFIX}.mpq")
    print(f"  ownership manifest: {client / OWNER_MANIFEST}")
    print("  Cache/WDB cleared")


if __name__ == "__main__":
    main()

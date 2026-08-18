#!/usr/bin/env python3
"""Install generated Adventurer MPQs into a local WoW 3.3.5a client safely.

The client may already contain many visual/UI MPQs. Never overwrite a patch we
do not own. The generated archives keep their canonical build names, while the
installer chooses the highest free single-letter patch suffix in the live
client and records ownership in a small manifest at the client root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import string
from pathlib import Path

OWNER_MANIFEST = ".aventureros-spelldraft.json"
PATCH_SUFFIXES = tuple(reversed(string.ascii_uppercase))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def existing_names(directory: Path) -> set[str]:
    if not directory.is_dir():
        return set()
    return {entry.name.lower() for entry in directory.iterdir() if entry.is_file()}


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


def owned_target(client: Path, manifest: dict, key: str) -> Path:
    relative = manifest.get(key)
    if not isinstance(relative, str) or not relative:
        raise SystemExit(f"Invalid {OWNER_MANIFEST}: missing {key}")
    target = (client / Path(relative)).resolve()
    try:
        target.relative_to(client)
    except ValueError as exc:
        raise SystemExit(f"Invalid {OWNER_MANIFEST}: {key} escapes client root") from exc
    return target


def verify_owned_file(target: Path, expected_hash: str | None) -> None:
    if not target.exists():
        return
    if not target.is_file():
        raise SystemExit(f"Owned patch target is not a file: {target}")
    if not expected_hash:
        raise SystemExit(f"Refusing to overwrite {target}: manifest has no previous hash")
    actual = sha256(target)
    if actual != expected_hash:
        raise SystemExit(
            "Refusing to overwrite a patch whose contents changed outside SpellDraft:\n"
            f"  {target}\n"
            f"  manifest sha256: {expected_hash}\n"
            f"  current  sha256: {actual}"
        )


def choose_free_pair(client: Path, locale: str, forced_suffix: str | None) -> tuple[str, Path, Path]:
    root_dir = client / "Data"
    locale_dir = root_dir / locale
    root_names = existing_names(root_dir)
    locale_names = existing_names(locale_dir)

    suffixes = PATCH_SUFFIXES
    if forced_suffix:
        suffix = forced_suffix.upper()
        if len(suffix) != 1 or suffix not in string.ascii_uppercase:
            raise SystemExit("--suffix must be one letter A-Z")
        suffixes = (suffix,)

    for suffix in suffixes:
        root_name = f"patch-{suffix}.mpq"
        locale_name = f"patch-{locale}-{suffix.lower()}.mpq"
        if root_name.lower() in root_names or locale_name.lower() in locale_names:
            continue
        return suffix, root_dir / root_name, locale_dir / locale_name

    if forced_suffix:
        raise SystemExit(
            f"Patch suffix {forced_suffix.upper()} is already occupied in root or locale. "
            "Choose another suffix or omit --suffix for automatic selection."
        )
    raise SystemExit(
        "No free single-letter patch pair remains (A-Z). Nothing was overwritten."
    )


def list_existing_patches(client: Path, locale: str) -> tuple[list[str], list[str]]:
    root = client / "Data"
    locale_dir = root / locale
    root_patches = sorted(
        entry.name
        for entry in root.glob("*.mpq")
        if entry.is_file() and entry.name.lower().startswith("patch-")
    )
    locale_patches = sorted(
        entry.name
        for entry in locale_dir.glob("*.mpq")
        if entry.is_file() and entry.name.lower().startswith(f"patch-{locale.lower()}-")
    )
    return root_patches, locale_patches


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
    parser.add_argument(
        "--suffix",
        help="Optional single-letter live patch suffix (A-Z). Default: highest free pair.",
    )
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

    root_patches, locale_patches = list_existing_patches(client, args.locale)
    print(f"Existing root patch MPQs: {len(root_patches)}")
    for name in root_patches:
        print(f"  Data/{name}")
    print(f"Existing {args.locale} patch MPQs: {len(locale_patches)}")
    for name in locale_patches:
        print(f"  Data/{args.locale}/{name}")

    previous = load_owner_manifest(client)
    if previous:
        if previous.get("locale") != args.locale:
            raise SystemExit(
                f"Existing SpellDraft install uses locale {previous.get('locale')!r}; "
                f"requested {args.locale!r}. Uninstall/migrate it explicitly first."
            )
        target_root = owned_target(client, previous, "root_patch")
        target_locale = owned_target(client, previous, "locale_patch")
        verify_owned_file(target_root, previous.get("root_sha256"))
        verify_owned_file(target_locale, previous.get("locale_sha256"))
        suffix = previous.get("suffix", "?")
        print(f"Updating existing SpellDraft-owned patch pair (suffix {suffix}).")
    else:
        suffix, target_root, target_locale = choose_free_pair(
            client,
            args.locale,
            args.suffix,
        )
        print(f"Selected free SpellDraft patch suffix: {suffix}")

    target_root.parent.mkdir(parents=True, exist_ok=True)
    target_locale.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_root, target_root)
    shutil.copy2(source_locale, target_locale)

    manifest = {
        "owner": "Aventureros de Azeroth / SpellDraft",
        "version": 1,
        "locale": args.locale,
        "suffix": suffix,
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

    print("Adventurer client patch installed without overwriting existing MPQs:")
    print(f"  {target_root}")
    print(f"  {target_locale}")
    print(f"  ownership manifest: {client / OWNER_MANIFEST}")
    print("  Cache/WDB cleared")


if __name__ == "__main__":
    main()

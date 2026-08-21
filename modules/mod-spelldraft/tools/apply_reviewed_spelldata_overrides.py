#!/usr/bin/env python3
"""Add reviewed project card metadata missing from historical SpellDraft SpellData.lua.

The historical addon metadata remains the primary curated source. This tool only
adds explicitly reviewed abilities listed in reviewed_spelldata_overrides.json;
it never broadens eligibility to arbitrary DBC spells.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
MODULE = TOOLS_DIR.parent
DEFAULT_OVERRIDES = MODULE / "reviewed_spelldata_overrides.json"
ENTRY_RE = re.compile(r"\[(\d+)\]\s*=\s*\{\s*rarity\s*=\s*(-?\d+)\s*,\s*class\s*=\s*\"([^\"]+)\"")
CLOSING_RE = re.compile(r"^\s*}\s*;?\s*$", re.MULTILINE)


class OverrideError(RuntimeError):
    pass


def lua_quote(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", " ")
        .replace("\n", " ")
    )


def load_overrides(path: Path) -> list[dict]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OverrideError(f"cannot read {path}: {exc}") from exc

    if raw.get("schema_version") != 1 or not isinstance(raw.get("spells"), list):
        raise OverrideError(f"{path}: expected schema_version=1 and spells[]")

    result: list[dict] = []
    seen: set[int] = set()
    for entry in raw["spells"]:
        if not isinstance(entry, dict):
            raise OverrideError(f"{path}: every override must be an object")
        spell_id = entry.get("id")
        rarity = entry.get("rarity")
        class_name = entry.get("class")
        name = entry.get("name")
        reason = entry.get("reason")
        if isinstance(spell_id, bool) or not isinstance(spell_id, int) or spell_id <= 0:
            raise OverrideError(f"{path}: invalid spell id {spell_id!r}")
        if spell_id in seen:
            raise OverrideError(f"{path}: duplicate spell id {spell_id}")
        if isinstance(rarity, bool) or not isinstance(rarity, int) or not 0 <= rarity <= 4:
            raise OverrideError(f"{path}: spell {spell_id} rarity must be 0..4")
        if not isinstance(class_name, str) or not class_name:
            raise OverrideError(f"{path}: spell {spell_id} needs class")
        if not isinstance(name, str) or not name:
            raise OverrideError(f"{path}: spell {spell_id} needs name")
        if not isinstance(reason, str) or not reason:
            raise OverrideError(f"{path}: spell {spell_id} needs reason")
        result.append(entry)
        seen.add(spell_id)
    return result


def patch_spell_data(path: Path, overrides: list[dict]) -> tuple[int, int]:
    if not path.is_file():
        raise OverrideError(f"SpellData.lua not found: {path}")

    text = path.read_text(encoding="utf-8", errors="replace")
    existing = {int(match.group(1)) for match in ENTRY_RE.finditer(text)}
    missing = [entry for entry in overrides if int(entry["id"]) not in existing]
    if not missing:
        return 0, len(overrides)

    closings = list(CLOSING_RE.finditer(text))
    if not closings:
        raise OverrideError(f"{path}: could not find SpellData table closing brace")
    closing = closings[-1]

    prefix = text[:closing.start()]
    stripped = prefix.rstrip()
    trailing = prefix[len(stripped):]
    if stripped and not stripped.endswith(","):
        prefix = stripped + "," + trailing

    payload = ""
    if prefix and not prefix.endswith("\n"):
        payload += "\n"
    payload += "\n  -- Aventureros reviewed metadata overrides\n"
    for entry in missing:
        payload += (
            f'  [{int(entry["id"])}] = {{ rarity = {int(entry["rarity"])}, '
            f'class = "{lua_quote(str(entry["class"]))}", '
            f'name = "{lua_quote(str(entry["name"]))}" }},\n'
        )

    backup = path.with_suffix(path.suffix + ".pre-aventureros-reviewed.bak")
    if not backup.exists():
        shutil.copy2(path, backup)

    path.write_text(prefix + payload + text[closing.start():], encoding="utf-8")

    verify = path.read_text(encoding="utf-8", errors="replace")
    final_ids = {int(match.group(1)) for match in ENTRY_RE.finditer(verify)}
    absent = sorted(int(entry["id"]) for entry in overrides if int(entry["id"]) not in final_ids)
    if absent:
        raise OverrideError("reviewed metadata failed to install: " + ", ".join(map(str, absent)))

    return len(missing), len(overrides)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spell-data", required=True, type=Path)
    parser.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES)
    args = parser.parse_args()

    try:
        overrides = load_overrides(args.overrides.expanduser().resolve())
        added, total = patch_spell_data(args.spell_data.expanduser().resolve(), overrides)
    except OverrideError as exc:
        raise SystemExit(f"Reviewed SpellData override aborted: {exc}") from exc

    print(f"Reviewed SpellData metadata validated: total={total}, newly_added={added}")
    for entry in overrides:
        print(
            f'  {int(entry["id"])} {entry["name"]}: '
            f'class={entry["class"]}, rarity={int(entry["rarity"])}'
        )


if __name__ == "__main__":
    main()

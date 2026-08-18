#!/usr/bin/env python3
"""Shared loader for manually reviewed SpellDraft source exclusions."""

from __future__ import annotations

import json
from pathlib import Path

MODULE = Path(__file__).resolve().parent.parent
DEFAULT_EXCLUSIONS = MODULE / "spell_exclusions.json"


class ExclusionError(RuntimeError):
    pass


def load_excluded_spell_ids(path: Path = DEFAULT_EXCLUSIONS) -> set[int]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ExclusionError(f"missing reviewed spell exclusions: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ExclusionError(f"invalid reviewed spell exclusions {path}: {exc}") from exc

    if raw.get("version") != 1:
        raise ExclusionError(f"{path}: expected exclusions version 1")
    spells = raw.get("spells")
    if not isinstance(spells, list):
        raise ExclusionError(f"{path}: spells must be a list")

    ids: set[int] = set()
    for entry in spells:
        if not isinstance(entry, dict) or "id" not in entry or not entry.get("reason"):
            raise ExclusionError(f"{path}: every exclusion needs id + reason")
        spell_id = int(entry["id"])
        if spell_id <= 0 or spell_id in ids:
            raise ExclusionError(f"{path}: invalid/duplicate spell id {spell_id}")
        ids.add(spell_id)
    return ids

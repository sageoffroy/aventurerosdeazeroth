#!/usr/bin/env python3
"""Print semantic native-rank anchors for normalized custom spells."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
DEFAULT_PROFILES = REPO / "env/dist/data/spelldraft/custom_spell_profiles.resolved.json"


class ReportError(RuntimeError):
    pass


def load_profiles(path: Path) -> dict[int, dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReportError(f"profile registry not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ReportError(f"invalid profile registry {path}: {exc}") from exc

    if not isinstance(data, dict) or int(data.get("version", 0)) != 2:
        raise ReportError(f"{path}: expected profile registry version 2")
    spells = data.get("spells")
    if not isinstance(spells, list):
        raise ReportError(f"{path}: spells must be a list")

    result: dict[int, dict[str, Any]] = {}
    for spell in spells:
        if not isinstance(spell, dict):
            continue
        spell_id = int(spell["id"])
        result[spell_id] = spell
    return result


def amount_text(anchor: dict[str, Any], field: str) -> str:
    amount = anchor.get(field)
    if not isinstance(amount, dict):
        return "-"
    minimum = int(amount["min"])
    maximum = int(amount["max"])
    return str(minimum) if minimum == maximum else f"{minimum}-{maximum}"


def seconds_text(ms: Any) -> str:
    if ms is None:
        return "-"
    value = int(ms) / 1000.0
    return f"{value:g}s"


def print_spell(spell: dict[str, Any]) -> None:
    spell_id = int(spell["id"])
    source_id = int(spell["clone_from"])
    name = str(spell.get("name") or f"Spell {spell_id}")
    profile = str(spell.get("profile") or "generic")
    anchors = spell.get("anchors")
    if not isinstance(anchors, list) or not anchors:
        raise ReportError(f"custom spell {spell_id} has no anchors")

    print(f"{spell_id} {name} <- {source_id} | profile={profile}")
    print("| Nivel | Spell nativo | Daño directo | DoT total | Duración | Tick | Cast |")
    print("|---:|---:|---:|---:|---:|---:|---:|")
    for anchor in anchors:
        if not isinstance(anchor, dict):
            continue
        print(
            f"| {int(anchor['level'])} | {int(anchor['source_spell_id'])} | "
            f"{amount_text(anchor, 'direct')} | {amount_text(anchor, 'dot_total')} | "
            f"{seconds_text(anchor.get('duration_ms'))} | "
            f"{seconds_text(anchor.get('tick_ms'))} | "
            f"{seconds_text(anchor.get('cast_ms'))} |"
        )
    print()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("ids", nargs="+", type=int, help="Custom 201xxx spell IDs")
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    args = parser.parse_args()

    try:
        profiles = load_profiles(args.profiles.expanduser().resolve())
        for spell_id in args.ids:
            spell = profiles.get(spell_id)
            if spell is None:
                raise ReportError(f"custom spell {spell_id} is not present in profile registry")
            print_spell(spell)
    except (KeyError, TypeError, ValueError, ReportError) as exc:
        raise SystemExit(f"Profiled spell report aborted: {exc}") from exc


if __name__ == "__main__":
    main()

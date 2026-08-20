#!/usr/bin/env python3
"""Validate generated project-card and owner-scaled summon extensions."""

from __future__ import annotations

import argparse
import json
import re
import struct
from dataclasses import dataclass
from pathlib import Path

from generate_normalized_spells import EFFECT_TYPE, effect_range
from patch_adventurer_class_dbcs import read_dbc, u32

MODULE = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY = MODULE / "custom_spells.json"
DEFAULT_EXTENSIONS = MODULE / "project_spell_extensions.json"
ALIAS_FILENAME = "AventurerosCustomSpellData.lua"
SPELL_ID = 0
CAST_TIME_INDEX = 28
SPELL_EFFECT_SCHOOL_DAMAGE = 2


class ValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class EffectRange:
    minimum: int
    maximum: int


@dataclass(frozen=True)
class RuntimeRow:
    cast_ms: int
    effects: tuple[EffectRange | None, EffectRange | None, EffectRange | None]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)
    print(f"OK: {message}")


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{path}: expected a JSON object")
    return value


def dbc_rows(path: Path) -> dict[int, bytearray]:
    _fields, _record_size, records, _strings, _trailing = read_dbc(path)
    return {u32(row, SPELL_ID): row for row in records}


def cast_times(path: Path) -> dict[int, int]:
    fields, record_size, records, _strings, _trailing = read_dbc(path)
    if fields < 2 or record_size != fields * 4:
        raise ValidationError(f"{path}: unexpected SpellCastTimes.dbc layout")
    return {u32(row, 0): max(0, struct.unpack_from("<i", row, 4)[0]) for row in records}


def direct_effect_index(row: bytearray, spell_id: int) -> int:
    matches = [
        index for index in range(3)
        if u32(row, EFFECT_TYPE + index) == SPELL_EFFECT_SCHOOL_DAMAGE
    ]
    if len(matches) != 1:
        raise ValidationError(f"spell {spell_id}: expected exactly one SCHOOL_DAMAGE effect")
    return matches[0]


def parse_scaling(path: Path) -> dict[int, dict[int, RuntimeRow]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValidationError(f"cannot read scaling TSV {path}: {exc}") from exc

    result: dict[int, dict[int, RuntimeRow]] = {}
    for line_number, raw in enumerate(lines, 1):
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        parts = raw.split()
        if len(parts) != 10:
            raise ValidationError(f"{path}:{line_number}: expected 10 fields")
        try:
            spell_id = int(parts[0])
            level = int(parts[1])
            cast_ms = int(parts[2])
            effects: list[EffectRange | None] = []
            for index in range(3):
                low = parts[4 + index * 2]
                high = parts[5 + index * 2]
                if low == "x" and high == "x":
                    effects.append(None)
                elif low == "x" or high == "x":
                    raise ValueError("partial x")
                else:
                    effects.append(EffectRange(int(low), int(high)))
        except ValueError as exc:
            raise ValidationError(f"{path}:{line_number}: malformed row") from exc
        levels = result.setdefault(spell_id, {})
        if level in levels:
            raise ValidationError(f"duplicate scaling row {spell_id}:{level}")
        levels[level] = RuntimeRow(cast_ms, (effects[0], effects[1], effects[2]))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dbc-dir", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--scaling", required=True, type=Path)
    parser.add_argument("--client-dir", required=True, type=Path)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--extensions", type=Path, default=DEFAULT_EXTENSIONS)
    args = parser.parse_args()

    try:
        registry = load_json(args.registry.expanduser().resolve())
        extensions = load_json(args.extensions.expanduser().resolve())
        max_level = int(registry.get("runtime_max_level", 0))
        require(max_level == 80, "project runtime covers levels 1-80")

        cards = extensions.get("cards", [])
        supports = extensions.get("owner_scaled_support_spells", [])
        require(isinstance(cards, list) and isinstance(supports, list), "extension lists are valid")

        mirror = [card for card in cards if int(card.get("spell_id", 0)) == 55342]
        require(len(mirror) == 1, "Mirror Image 55342 is declared exactly once")
        require(int(mirror[0]["rarity"]) == 3, "Mirror Image is Epic")
        require(int(mirror[0]["min_level"]) == 1, "Mirror Image is draftable from level 1")

        catalog_path = args.catalog.expanduser().resolve()
        catalog_text = catalog_path.read_text(encoding="utf-8")
        mirror_lines = re.findall(r'^\s*\{ id = 55342,.*$', catalog_text, re.MULTILINE)
        require(len(mirror_lines) == 1, "runtime catalog contains Mirror Image exactly once")
        require("rarity = 3" in mirror_lines[0], "runtime Mirror Image rarity is Epic")
        require("classSet = 3" in mirror_lines[0], "runtime Mirror Image origin is Mage")
        require("minLevel = 1" in mirror_lines[0], "runtime Mirror Image has no level gate")

        dbc_dir = args.dbc_dir.expanduser().resolve()
        rows = dbc_rows(dbc_dir / "Spell.dbc")
        casts = cast_times(dbc_dir / "SpellCastTimes.dbc")
        runtime = parse_scaling(args.scaling.expanduser().resolve())

        for support in supports:
            spell_id = int(support["spell_id"])
            label = str(support.get("label") or spell_id)
            dbc = rows.get(spell_id)
            require(dbc is not None, f"{label} exists in Spell.dbc")
            levels = runtime.get(spell_id, {})
            require(set(levels) == set(range(1, max_level + 1)), f"{label} has 80 owner-level rows")

            effect_index = direct_effect_index(dbc, spell_id)
            native = effect_range(dbc, effect_index)
            reference_level = int(support["reference_level"])
            reference = levels[reference_level].effects[effect_index]
            require(
                reference == EffectRange(native.minimum, native.maximum),
                f"{label} reproduces native damage at level {reference_level}",
            )

            native_cast = casts.get(u32(dbc, CAST_TIME_INDEX), 0)
            require(
                all(row.cast_ms == native_cast for row in levels.values()),
                f"{label} preserves native cast time ({native_cast} ms)",
            )

        addon_dir = args.client_dir.expanduser().resolve() / "Interface" / "AddOns" / "SpellDraft"
        alias_path = addon_dir / ALIAS_FILENAME
        alias_text = alias_path.read_text(encoding="utf-8")
        require(
            re.search(r'^SpellDraftData\[55342\]\s*=\s*\{', alias_text, re.MULTILINE) is not None,
            "client Grimoire metadata contains Mirror Image 55342",
        )

        cpp = (MODULE / "src" / "CustomSpellScaling.cpp").read_text(encoding="utf-8")
        require("ALLSPELLHOOK_ON_CAST" in cpp, "runtime registers all-unit spell hook")
        require(
            "GetCharmerOrOwnerPlayerOrPlayerItself" in cpp,
            "summon support scaling resolves the owning player",
        )
        require(
            "PLAYERHOOK_ON_SPELL_CAST" in cpp,
            "existing player custom-spell hook remains intact",
        )
    except (KeyError, TypeError, ValueError, OSError, ValidationError) as exc:
        raise SystemExit(f"Project spell extension validation aborted: {exc}") from exc

    print("\nALL PROJECT SPELL EXTENSIONS VALIDATED")


if __name__ == "__main__":
    main()

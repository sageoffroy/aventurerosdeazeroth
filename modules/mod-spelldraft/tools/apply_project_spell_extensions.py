#!/usr/bin/env python3
"""Apply explicit Aventureros cards and owner-scaled summon support spells.

This is a post-generation enrichment step over the canonical SpellDraft assets:

* the runtime catalog gains explicitly authored native cards that are absent from
  the historical SpellDraft metadata (Mirror Image is the first one);
* the existing profile-aware scaling TSV gains native support spells cast by an
  owned summon/guardian. Their level curve is derived from an already normalized
  player spell and keyed to the owning player's level at runtime;
* the historical Grimoire metadata alias file gains entries for project-authored
  native cards so the client can render them without relying on localized names.

There is still one runtime scaling table and one runtime resolver. Native pets,
demons and guardians remain untouched unless one of their spell IDs is explicitly
listed in project_spell_extensions.json.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from generate_normalized_spells import EFFECT_TYPE, effect_range
from patch_adventurer_class_dbcs import read_dbc, u32

MODULE = Path(__file__).resolve().parent.parent
DEFAULT_EXTENSIONS = MODULE / "project_spell_extensions.json"
DEFAULT_REGISTRY = MODULE / "custom_spells.json"
ALIAS_FILENAME = "AventurerosCustomSpellData.lua"
SPELL_ID = 0
CAST_TIME_INDEX = 28
SPELL_LEVEL = 39
SPELL_EFFECT_SCHOOL_DAMAGE = 2
CATALOG_LINE_RE = re.compile(
    r'^\s*\{ id = (\d+), rarity = (-?\d+), classSet = (\d+), minLevel = (\d+), '
    r'name = "((?:\\.|[^"])*)", '
    r'((?:grants = \{.*?\}, requires = \{.*?\}, synergy = \{.*?\}, )?)'
    r'ranks = \{.*\} \},\s*$'
)


class ExtensionError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeRange:
    minimum: int
    maximum: int


@dataclass(frozen=True)
class RuntimeRow:
    spell_id: int
    level: int
    cast_ms: int
    duration_ms: int
    effects: tuple[RuntimeRange | None, RuntimeRange | None, RuntimeRange | None]


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ExtensionError(f"{label} not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ExtensionError(f"invalid {label} {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ExtensionError(f"{label} must be a JSON object: {path}")
    return data


def validate_extensions(data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if int(data.get("schema_version", 0)) != 1:
        raise ExtensionError("project spell extensions must use schema_version=1")

    cards = data.get("cards", [])
    supports = data.get("owner_scaled_support_spells", [])
    if not isinstance(cards, list) or not isinstance(supports, list):
        raise ExtensionError("cards and owner_scaled_support_spells must be lists")

    card_ids: set[int] = set()
    for index, card in enumerate(cards):
        if not isinstance(card, dict):
            raise ExtensionError(f"cards[{index}] must be an object")
        try:
            spell_id = int(card["spell_id"])
            rarity = int(card["rarity"])
            class_set = int(card["class_set"])
            class_name = str(card["class"]).strip()
            min_level = int(card["min_level"])
            name = str(card["name"]).strip()
        except (KeyError, TypeError, ValueError) as exc:
            raise ExtensionError(f"cards[{index}] is malformed") from exc
        if spell_id <= 0 or spell_id in card_ids:
            raise ExtensionError(f"duplicate/invalid project card spell ID {spell_id}")
        if (
            rarity < 0 or rarity > 4 or class_set <= 0 or min_level <= 0
            or not class_name or not name
        ):
            raise ExtensionError(f"invalid project card metadata for {spell_id}")
        card_ids.add(spell_id)

    support_ids: set[int] = set()
    for index, support in enumerate(supports):
        if not isinstance(support, dict):
            raise ExtensionError(f"owner_scaled_support_spells[{index}] must be an object")
        try:
            spell_id = int(support["spell_id"])
            source_root = int(support["derive_from_root"])
            reference_level = int(support["reference_level"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ExtensionError(f"owner_scaled_support_spells[{index}] is malformed") from exc
        if spell_id <= 0 or source_root <= 0 or reference_level <= 0:
            raise ExtensionError(f"invalid owner-scaled support metadata at index {index}")
        if spell_id in support_ids:
            raise ExtensionError(f"duplicate owner-scaled support spell ID {spell_id}")
        support_ids.add(spell_id)

    return cards, supports


def dbc_rows(path: Path) -> dict[int, bytearray]:
    _fields, _record_size, records, _strings, _trailing = read_dbc(path)
    return {u32(row, SPELL_ID): row for row in records}


def cast_time_map(path: Path) -> dict[int, int]:
    fields, record_size, records, _strings, _trailing = read_dbc(path)
    if fields < 2 or record_size != fields * 4:
        raise ExtensionError(f"{path}: unexpected SpellCastTimes.dbc layout")
    return {u32(row, 0): max(0, struct.unpack_from("<i", row, 4)[0]) for row in records}


def lua_quote(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", " ")
        .replace("\n", " ")
    )


def project_card_line(card: dict[str, Any], spell_rows: dict[int, bytearray]) -> str:
    spell_id = int(card["spell_id"])
    row = spell_rows.get(spell_id)
    if row is None:
        raise ExtensionError(f"project card {spell_id} is missing from Spell.dbc")
    native_level = max(1, u32(row, SPELL_LEVEL))
    return (
        '  { id = %d, rarity = %d, classSet = %d, minLevel = %d, '
        'name = "%s", grants = {}, requires = {}, synergy = {}, '
        'ranks = { { id = %d, level = %d } } },'
        % (
            spell_id,
            int(card["rarity"]),
            int(card["class_set"]),
            int(card["min_level"]),
            lua_quote(str(card["name"])),
            spell_id,
            native_level,
        )
    )


def apply_catalog_cards(
    catalog_path: Path,
    cards: list[dict[str, Any]],
    spell_rows: dict[int, bytearray],
) -> int:
    if not catalog_path.is_file():
        raise ExtensionError(f"runtime catalog not found: {catalog_path}")

    lines = catalog_path.read_text(encoding="utf-8").splitlines()
    try:
        catalog_start = next(i for i, line in enumerate(lines) if line.strip() == "SpellDraftCatalog = {")
        catalog_end = next(i for i in range(catalog_start + 1, len(lines)) if lines[i].strip() == "}")
    except StopIteration as exc:
        raise ExtensionError(f"{catalog_path}: SpellDraftCatalog block not found") from exc

    existing: dict[int, int] = {}
    for index in range(catalog_start + 1, catalog_end):
        match = CATALOG_LINE_RE.match(lines[index])
        if match:
            existing[int(match.group(1))] = index

    changed = 0
    additions: list[str] = []
    for card in cards:
        spell_id = int(card["spell_id"])
        desired = project_card_line(card, spell_rows)
        if spell_id in existing:
            index = existing[spell_id]
            if lines[index] != desired:
                lines[index] = desired
                changed += 1
        else:
            additions.append(desired)
            changed += 1

    if additions:
        lines[catalog_end:catalog_end] = additions

    catalog_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    final_text = catalog_path.read_text(encoding="utf-8")
    for card in cards:
        spell_id = int(card["spell_id"])
        matches = re.findall(rf'^\s*\{{ id = {spell_id}, rarity =', final_text, re.MULTILINE)
        if len(matches) != 1:
            raise ExtensionError(f"project card {spell_id} must appear exactly once in runtime catalog")
    return changed


def parse_runtime(path: Path) -> tuple[list[str], dict[int, dict[int, RuntimeRow]]]:
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise ExtensionError(f"runtime scaling TSV not found: {path}") from exc

    header = [line for line in raw_lines if not line.strip() or line.lstrip().startswith("#")]
    rows: dict[int, dict[int, RuntimeRow]] = {}
    for line_number, raw in enumerate(raw_lines, 1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) != 10:
            raise ExtensionError(f"{path}:{line_number}: expected 10 scaling fields")
        try:
            spell_id = int(parts[0])
            level = int(parts[1])
            cast_ms = int(parts[2])
            duration_ms = int(parts[3])
            effects: list[RuntimeRange | None] = []
            for effect_index in range(3):
                low = parts[4 + effect_index * 2]
                high = parts[5 + effect_index * 2]
                if low == "x" and high == "x":
                    effects.append(None)
                elif low == "x" or high == "x":
                    raise ValueError("partial x range")
                else:
                    minimum = int(low)
                    maximum = int(high)
                    if maximum < minimum:
                        raise ValueError("reversed effect range")
                    effects.append(RuntimeRange(minimum, maximum))
        except ValueError as exc:
            raise ExtensionError(f"{path}:{line_number}: malformed scaling row") from exc
        levels = rows.setdefault(spell_id, {})
        if level in levels:
            raise ExtensionError(f"duplicate scaling row {spell_id}:{level}")
        levels[level] = RuntimeRow(
            spell_id,
            level,
            cast_ms,
            duration_ms,
            (effects[0], effects[1], effects[2]),
        )
    return header, rows


def school_damage_index(row: bytearray, spell_id: int) -> int:
    matches = [
        index for index in range(3)
        if u32(row, EFFECT_TYPE + index) == SPELL_EFFECT_SCHOOL_DAMAGE
    ]
    if len(matches) != 1:
        raise ExtensionError(
            f"support/source spell {spell_id} must have exactly one SCHOOL_DAMAGE effect; got {matches}"
        )
    return matches[0]


def rounded(value: float) -> int:
    if value >= 0:
        return int(math.floor(value + 0.5))
    return -int(math.floor(abs(value) + 0.5))


def derive_support_rows(
    supports: list[dict[str, Any]],
    registry: dict[str, Any],
    spell_rows: dict[int, bytearray],
    runtime: dict[int, dict[int, RuntimeRow]],
    cast_times: dict[int, int],
) -> dict[int, dict[int, RuntimeRow]]:
    max_level = int(registry.get("runtime_max_level", 0))
    offset = int(registry.get("custom_id_offset", 0))
    if max_level <= 0 or offset <= 0:
        raise ExtensionError("custom_spells.json has invalid runtime_max_level/custom_id_offset")

    generated: dict[int, dict[int, RuntimeRow]] = {}
    for support in supports:
        spell_id = int(support["spell_id"])
        source_root = int(support["derive_from_root"])
        reference_level = int(support["reference_level"])
        label = str(support.get("label") or spell_id)
        if reference_level > max_level:
            raise ExtensionError(
                f"{label}: reference level {reference_level} exceeds runtime max {max_level}"
            )

        support_dbc = spell_rows.get(spell_id)
        source_dbc = spell_rows.get(source_root)
        if support_dbc is None or source_dbc is None:
            raise ExtensionError(f"{label}: support/source spell missing from Spell.dbc")

        support_effect = school_damage_index(support_dbc, spell_id)
        support_cast_ms = cast_times.get(u32(support_dbc, CAST_TIME_INDEX), 0)
        source_effect = school_damage_index(source_dbc, source_root)
        source_custom_id = offset + source_root
        source_levels = runtime.get(source_custom_id)
        if source_levels is None:
            raise ExtensionError(
                f"{label}: normalized source {source_custom_id} (root {source_root}) is absent from scaling TSV"
            )
        expected_levels = set(range(1, max_level + 1))
        if set(source_levels) != expected_levels:
            raise ExtensionError(f"{label}: source {source_custom_id} does not cover levels 1-{max_level}")

        source_reference = source_levels[reference_level].effects[source_effect]
        if source_reference is None or source_reference.minimum == 0 or source_reference.maximum == 0:
            raise ExtensionError(f"{label}: source reference damage is missing/zero")

        native = effect_range(support_dbc, support_effect)
        native_reference = RuntimeRange(native.minimum, native.maximum)
        minimum_ratio = native_reference.minimum / source_reference.minimum
        maximum_ratio = native_reference.maximum / source_reference.maximum

        levels: dict[int, RuntimeRow] = {}
        for level in range(1, max_level + 1):
            source_range = source_levels[level].effects[source_effect]
            if source_range is None:
                raise ExtensionError(f"{label}: source damage missing at level {level}")

            if level == reference_level:
                derived = native_reference
            else:
                minimum = rounded(source_range.minimum * minimum_ratio)
                maximum = rounded(source_range.maximum * maximum_ratio)
                if native_reference.minimum > 0:
                    minimum = max(1, minimum)
                if native_reference.maximum > 0:
                    maximum = max(1, maximum)
                derived = RuntimeRange(min(minimum, maximum), max(minimum, maximum))

            effects: list[RuntimeRange | None] = [None, None, None]
            effects[support_effect] = derived
            levels[level] = RuntimeRow(
                spell_id=spell_id,
                level=level,
                cast_ms=support_cast_ms,
                duration_ms=0,
                effects=(effects[0], effects[1], effects[2]),
            )

        if levels[reference_level].effects[support_effect] != native_reference:
            raise ExtensionError(f"{label}: reference level does not reproduce native support damage")
        generated[spell_id] = levels
        print(
            f"  {label}: native {native_reference.minimum}-{native_reference.maximum} at {reference_level}; "
            f"source {source_custom_id} ratio={minimum_ratio:.6f}/{maximum_ratio:.6f}"
        )

    return generated


def render_runtime_row(row: RuntimeRow) -> str:
    values = [str(row.spell_id), str(row.level), str(row.cast_ms), str(row.duration_ms)]
    for effect in row.effects:
        if effect is None:
            values.extend(["x", "x"])
        else:
            values.extend([str(effect.minimum), str(effect.maximum)])
    return " ".join(values)


def apply_support_scaling(
    scaling_path: Path,
    supports: list[dict[str, Any]],
    registry: dict[str, Any],
    spell_rows: dict[int, bytearray],
    cast_times: dict[int, int],
) -> int:
    header, runtime = parse_runtime(scaling_path)
    support_ids = {int(spec["spell_id"]) for spec in supports}
    for spell_id in support_ids:
        runtime.pop(spell_id, None)

    generated = derive_support_rows(supports, registry, spell_rows, runtime, cast_times)
    runtime.update(generated)

    lines = [
        line for line in header
        if line.strip()
        and line.strip() != "# Native owner-scaled support spells are explicit project extensions."
    ]
    if not lines:
        lines = [
            "# Aventureros de Azeroth profile-aware normalized spell scaling v2",
            "# spell_id level cast_ms duration_ms e0_min e0_max e1_min e1_max e2_min e2_max",
        ]
    lines.append("# Native owner-scaled support spells are explicit project extensions.")
    for spell_id in sorted(runtime):
        for level in sorted(runtime[spell_id]):
            lines.append(render_runtime_row(runtime[spell_id][level]))
    scaling_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    max_level = int(registry["runtime_max_level"])
    check_header, check_runtime = parse_runtime(scaling_path)
    _ = check_header
    for spell_id in support_ids:
        levels = check_runtime.get(spell_id, {})
        if set(levels) != set(range(1, max_level + 1)):
            raise ExtensionError(f"owner-scaled support {spell_id} is incomplete after write")
    return len(support_ids) * max_level


def metadata_line(card: dict[str, Any]) -> str:
    return (
        'SpellDraftData[%d] = { rarity = %d, class = "%s", name = "%s" }'
        % (
            int(card["spell_id"]),
            int(card["rarity"]),
            lua_quote(str(card["class"])),
            lua_quote(str(card["name"])),
        )
    )


def apply_client_metadata(client_dir: Path, cards: list[dict[str, Any]]) -> int:
    addon_dir = client_dir / "Interface" / "AddOns" / "SpellDraft"
    alias_path = addon_dir / ALIAS_FILENAME
    toc_path = addon_dir / "SpellDraft.toc"
    if not alias_path.is_file():
        raise ExtensionError(
            f"{alias_path} not found; run patch_spelldraft_grimoire.py / prepare_first_run.py first"
        )
    if not toc_path.is_file():
        raise ExtensionError(f"SpellDraft TOC not found: {toc_path}")

    original = alias_path.read_text(encoding="utf-8")
    lines = original.splitlines()
    project_ids = {int(card["spell_id"]) for card in cards}
    patterns = [re.compile(rf'^SpellDraftData\[{spell_id}\]\s*=') for spell_id in project_ids]
    lines = [
        line for line in lines
        if not any(pattern.match(line.strip()) for pattern in patterns)
    ]
    if lines and lines[-1].strip():
        lines.append("")
    lines.append("-- Project-authored native cards absent from historical SpellData.lua.")
    for card in cards:
        lines.append(metadata_line(card))
    lines.append("")
    desired = "\n".join(lines)
    alias_path.write_text(desired, encoding="utf-8")

    toc_lines = [line.strip() for line in toc_path.read_text(encoding="utf-8").splitlines()]
    if ALIAS_FILENAME not in toc_lines:
        raise ExtensionError(f"{toc_path}: {ALIAS_FILENAME} is not loaded")

    final = alias_path.read_text(encoding="utf-8")
    for card in cards:
        if metadata_line(card) not in final:
            raise ExtensionError(f"client metadata missing project card {card['spell_id']}")
    return len(cards)


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
        extensions = load_json(args.extensions.expanduser().resolve(), "project spell extensions")
        cards, supports = validate_extensions(extensions)
        registry = load_json(args.registry.expanduser().resolve(), "custom spell registry")
        dbc_dir = args.dbc_dir.expanduser().resolve()
        spell_rows = dbc_rows(dbc_dir / "Spell.dbc")
        cast_times = cast_time_map(dbc_dir / "SpellCastTimes.dbc")

        print("Project spell extensions:")
        catalog_changes = apply_catalog_cards(
            args.catalog.expanduser().resolve(), cards, spell_rows
        )
        print(f"  project cards: {len(cards)} ({catalog_changes} catalog rows changed)")

        support_rows = apply_support_scaling(
            args.scaling.expanduser().resolve(), supports, registry, spell_rows, cast_times
        )
        print(f"  owner-scaled support rows: {support_rows}")

        metadata_count = apply_client_metadata(
            args.client_dir.expanduser().resolve(), cards
        )
        print(f"  client project metadata entries: {metadata_count}")
    except (KeyError, TypeError, ValueError, OSError, ExtensionError) as exc:
        raise SystemExit(f"Project spell extension aborted: {exc}") from exc

    print("  runtime model: player custom spells + explicit native summon support spells share one TSV")
    print("  undeclared pet/guardian spells retain normal AzerothCore behavior")


if __name__ == "__main__":
    main()

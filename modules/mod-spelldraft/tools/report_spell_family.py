#!/usr/bin/env python3
"""Print comparable SpellDraft spell data from the live generated runtime.

This avoids manual screenshots when validating normalized spell families.
The report reads the same DBC/scaling assets used by the server and can also
compute percentage mana costs with the Adventurer base-mana formula.
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

MAGIC = b"WDBC"
HEADER = struct.Struct("<4sIIII")

REPO = Path(__file__).resolve().parents[3]
DEFAULT_DBC_DIR = REPO / "env" / "dist" / "data" / "dbc"
DEFAULT_SCALING = REPO / "env" / "dist" / "data" / "spelldraft" / "custom_spell_scaling.tsv"

# WotLK 3.3.5a Spell.dbc field indices.
SPELL_ID = 0
CAST_TIME_INDEX = 28
DURATION_INDEX = 40
POWER_TYPE = 41
MANA_COST = 42
MANA_COST_PER_LEVEL = 43
MANA_PER_SECOND = 44
MANA_PER_SECOND_PER_LEVEL = 45
RANGE_INDEX = 46
EFFECT_TYPE = 71
EFFECT_DIE_SIDES = 74
EFFECT_REAL_POINTS_PER_LEVEL = 77
EFFECT_BASE_POINTS = 80
EFFECT_AURA = 95
EFFECT_AMPLITUDE = 98
EFFECT_TRIGGER_SPELL = 116
NAME_FIRST = 136
NAME_LAST = 151
DESCRIPTION_FIRST = 170
DESCRIPTION_LAST = 185
TOOLTIP_FIRST = 187
TOOLTIP_LAST = 202
MANA_COST_PERCENTAGE = 204

# Prefer esMX, then esES, then any populated locale slot.
NAME_LOCALE_PREFERENCE = (143, 142)
DESCRIPTION_LOCALE_PREFERENCE = (177, 176)
TOOLTIP_LOCALE_PREFERENCE = (194, 193)

EFFECT_NAMES = {
    0: "NONE",
    2: "SCHOOL_DAMAGE",
    3: "DUMMY",
    6: "APPLY_AURA",
    8: "POWER_DRAIN",
    9: "HEALTH_LEECH",
    10: "HEAL",
    17: "WEAPON_DAMAGE_NOSCHOOL",
    27: "PERSISTENT_AREA_AURA",
    30: "ENERGIZE",
    58: "WEAPON_DAMAGE",
    64: "TRIGGER_SPELL",
    62: "POWER_BURN",
    121: "NORMALIZED_WEAPON_DMG",
    136: "HEAL_PCT",
    137: "ENERGIZE_PCT",
    141: "FORCE_CAST_WITH_VALUE",
    142: "TRIGGER_SPELL_WITH_VALUE",
    148: "TRIGGER_MISSILE_WITH_VALUE",
}


class ReportError(RuntimeError):
    pass


def read_dbc(path: Path):
    data = path.read_bytes()
    if len(data) < HEADER.size:
        raise ReportError(f"DBC too small: {path}")
    magic, count, fields, record_size, string_size = HEADER.unpack_from(data)
    if magic != MAGIC:
        raise ReportError(f"Not a WDBC file: {path}")
    records_start = HEADER.size
    records_end = records_start + count * record_size
    strings_end = records_end + string_size
    if strings_end > len(data):
        raise ReportError(f"DBC header exceeds file size: {path}")
    records = [
        data[records_start + i * record_size : records_start + (i + 1) * record_size]
        for i in range(count)
    ]
    return fields, record_size, records, data[records_end:strings_end]


def u32(row: bytes, field: int) -> int:
    return struct.unpack_from("<I", row, field * 4)[0]


def i32(row: bytes, field: int) -> int:
    return struct.unpack_from("<i", row, field * 4)[0]


def f32(row: bytes, field: int) -> float:
    return struct.unpack_from("<f", row, field * 4)[0]


def string_at(strings: bytes, offset: int) -> str:
    if offset <= 0 or offset >= len(strings):
        return ""
    end = strings.find(b"\0", offset)
    if end < 0:
        return ""
    return strings[offset:end].decode("utf-8", "replace")


def localized_text(row: bytes, strings: bytes, preferred: tuple[int, ...], first: int, last: int) -> str:
    for field in preferred:
        value = string_at(strings, u32(row, field))
        if value:
            return value
    for field in range(first, last + 1):
        value = string_at(strings, u32(row, field))
        if value:
            return value
    return ""


def rows_by_id(path: Path):
    fields, record_size, rows, strings = read_dbc(path)
    return fields, record_size, {u32(row, 0): row for row in rows}, strings


def load_scaling(path: Path):
    result: dict[
        tuple[int, int],
        tuple[int, int, list[tuple[int, int] | None]],
    ] = {}
    if not path.is_file():
        return result
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        parts = raw.split()
        if len(parts) == 9:
            cast_ms = -1
            duration = int(parts[2])
            effect_offset = 3
        elif len(parts) == 10:
            cast_ms = int(parts[2])
            duration = int(parts[3])
            effect_offset = 4
        else:
            continue
        spell_id = int(parts[0])
        level = int(parts[1])
        effects: list[tuple[int, int] | None] = []
        for index in range(3):
            lo = parts[effect_offset + index * 2]
            hi = parts[effect_offset + index * 2 + 1]
            effects.append(None if lo == "x" else (int(lo), int(hi)))
        result[(spell_id, level)] = (cast_ms, duration, effects)
    return result


def mana_from_intellect(intellect: int) -> int:
    if intellect < 20:
        return intellect
    return 20 + 15 * (intellect - 20)


def format_seconds(ms: int) -> str:
    if ms <= 0:
        return "instant"
    value = ms / 1000.0
    return f"{value:g}s"


def clean_description(text: str) -> str:
    return " ".join(text.replace("|n", " ").split())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("ids", nargs="+", type=int, help="Spell IDs to compare")
    parser.add_argument("--level", type=int, default=1)
    parser.add_argument("--dbc-dir", type=Path, default=DEFAULT_DBC_DIR)
    parser.add_argument("--scaling", type=Path, default=DEFAULT_SCALING)
    parser.add_argument("--max-mana", type=int, help="Adventurer current maximum mana")
    parser.add_argument("--intellect", type=int, help="Adventurer current intellect")
    args = parser.parse_args()

    dbc_dir = args.dbc_dir.expanduser().resolve()
    required = ["Spell.dbc", "SpellRange.dbc", "SpellCastTimes.dbc", "SpellDuration.dbc"]
    missing = [name for name in required if not (dbc_dir / name).is_file()]
    if missing:
        raise SystemExit("Missing DBC(s): " + ", ".join(missing))

    _, _, spells, spell_strings = rows_by_id(dbc_dir / "Spell.dbc")
    _, _, ranges, _ = rows_by_id(dbc_dir / "SpellRange.dbc")
    _, _, casts, _ = rows_by_id(dbc_dir / "SpellCastTimes.dbc")
    _, _, durations, _ = rows_by_id(dbc_dir / "SpellDuration.dbc")
    scaling = load_scaling(args.scaling.expanduser().resolve())

    base_mana = None
    if args.max_mana is not None or args.intellect is not None:
        if args.max_mana is None or args.intellect is None:
            raise SystemExit("--max-mana and --intellect must be supplied together")
        base_mana = max(0, args.max_mana - mana_from_intellect(args.intellect))
        print(
            f"Adventurer mana: MaxMana={args.max_mana} Int={args.intellect} "
            f"ManaFromIntellect={mana_from_intellect(args.intellect)} BaseMana={base_mana}"
        )
        print()

    print(f"SpellDraft family report - level {args.level}")
    print()
    print("| ID | Nombre | Maná | Alcance | Cast | Valores runtime | Duración | Efectos |")
    print("|---:|---|---:|---:|---:|---|---:|---|")

    descriptions: list[tuple[int, str, str]] = []

    for spell_id in args.ids:
        row = spells.get(spell_id)
        if row is None:
            print(f"| {spell_id} | MISSING | - | - | - | - | - | - |")
            continue

        name = localized_text(row, spell_strings, NAME_LOCALE_PREFERENCE, NAME_FIRST, NAME_LAST) or f"Spell {spell_id}"
        description = localized_text(
            row, spell_strings, DESCRIPTION_LOCALE_PREFERENCE, DESCRIPTION_FIRST, DESCRIPTION_LAST
        )
        tooltip = localized_text(row, spell_strings, TOOLTIP_LOCALE_PREFERENCE, TOOLTIP_FIRST, TOOLTIP_LAST)
        descriptions.append((spell_id, name, clean_description(description or tooltip)))

        fixed_cost = u32(row, MANA_COST)
        pct_cost = u32(row, MANA_COST_PERCENTAGE)
        per_level = u32(row, MANA_COST_PER_LEVEL)
        if base_mana is not None and i32(row, POWER_TYPE) == 0:
            computed = fixed_cost + (base_mana * pct_cost // 100)
            mana = str(computed)
            detail = []
            if pct_cost:
                detail.append(f"{pct_cost}% base")
            if fixed_cost:
                detail.append(f"+{fixed_cost}")
            if per_level:
                detail.append(f"+{per_level}/lvl")
            if detail:
                mana += " (" + " ".join(detail) + ")"
        else:
            pieces = []
            if fixed_cost:
                pieces.append(str(fixed_cost))
            if pct_cost:
                pieces.append(f"{pct_cost}% base")
            if per_level:
                pieces.append(f"{per_level}/lvl")
            mana = " + ".join(pieces) if pieces else "0"

        range_row = ranges.get(u32(row, RANGE_INDEX))
        if range_row:
            hostile_max = f32(range_row, 3)
            friendly_max = f32(range_row, 4)
            maximum = max(hostile_max, friendly_max)
            range_text = f"{maximum:g}m"
        else:
            range_text = "0m"

        cast_row = casts.get(u32(row, CAST_TIME_INDEX))
        native_cast_ms = i32(cast_row, 1) if cast_row else 0

        scaling_row = scaling.get((spell_id, args.level))
        if scaling_row:
            runtime_cast, runtime_duration, runtime_effects = scaling_row
            cast_ms = runtime_cast if runtime_cast >= 0 else native_cast_ms
            runtime_values = []
            for index, amount in enumerate(runtime_effects):
                if amount is not None:
                    runtime_values.append(f"e{index}={amount[0]}-{amount[1]}")
            runtime_text = ", ".join(runtime_values) if runtime_values else "-"
        else:
            cast_ms = native_cast_ms
            runtime_duration = 0
            runtime_text = "-"
        cast_text = format_seconds(cast_ms)

        duration_row = durations.get(u32(row, DURATION_INDEX))
        native_duration = abs(i32(duration_row, 1)) if duration_row else 0
        effective_duration = runtime_duration or native_duration
        duration_text = format_seconds(effective_duration) if effective_duration else "-"

        effects = []
        for index in range(3):
            effect_type = u32(row, EFFECT_TYPE + index)
            if not effect_type:
                continue
            aura = u32(row, EFFECT_AURA + index)
            trigger = u32(row, EFFECT_TRIGGER_SPELL + index)
            amplitude = u32(row, EFFECT_AMPLITUDE + index)
            label = EFFECT_NAMES.get(effect_type, str(effect_type))
            extra = []
            if aura:
                extra.append(f"aura={aura}")
            if trigger:
                extra.append(f"trigger={trigger}")
            if amplitude:
                extra.append(f"tick={amplitude/1000:g}s")
            effects.append(f"e{index}:{label}" + ("(" + ",".join(extra) + ")" if extra else ""))
        effect_text = "; ".join(effects) if effects else "-"

        print(
            f"| {spell_id} | {name} | {mana} | {range_text} | {cast_text} | "
            f"{runtime_text} | {duration_text} | {effect_text} |"
        )

    print()
    print("Descripciones DBC:")
    for spell_id, name, text in descriptions:
        print(f"- {spell_id} {name}: {text or '<sin descripción>'}")


if __name__ == "__main__":
    main()

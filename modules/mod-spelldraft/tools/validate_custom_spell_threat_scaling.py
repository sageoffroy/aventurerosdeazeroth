#!/usr/bin/env python3
"""Validate normalized threat rules against native spell_threat anchors."""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

from generate_spelldraft_catalog import parse_spell_ranks
from patch_adventurer_class_dbcs import read_dbc, u32

SPELL_ID = 0
SPELL_LEVEL = 39
THREAT_ROW_RE = re.compile(
    r"\(\s*(\d+)\s*,\s*(NULL|-?\d+)\s*,\s*"
    r"(-?(?:\d+(?:\.\d*)?|\.\d+))\s*,\s*"
    r"(-?(?:\d+(?:\.\d*)?|\.\d+))\s*\)"
)


class ValidateError(RuntimeError):
    pass


@dataclass(frozen=True)
class ThreatValue:
    flat: int
    pct: float
    ap_pct: float


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise ValidateError(f"cannot load {path}: {exc}") from exc


def parse_native(path: Path) -> dict[int, ThreatValue]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError as exc:
        raise ValidateError(f"missing spell_threat SQL: {path}") from exc

    result: dict[int, ThreatValue] = {}
    for spell_id, flat, pct, ap_pct in THREAT_ROW_RE.findall(text):
        result[int(spell_id)] = ThreatValue(
            0 if flat == "NULL" else int(flat),
            float(pct),
            float(ap_pct),
        )
    if not result:
        raise ValidateError(f"no spell_threat rows parsed from {path}")
    return result


def parse_runtime(path: Path) -> dict[tuple[int, int], ThreatValue]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise ValidateError(f"missing normalized threat file: {path}") from exc

    result: dict[tuple[int, int], ThreatValue] = {}
    for line_no, raw in enumerate(lines, 1):
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        parts = raw.split()
        if len(parts) != 5:
            raise ValidateError(f"{path}:{line_no}: expected 5 fields")
        try:
            spell_id = int(parts[0])
            level = int(parts[1])
            value = ThreatValue(int(parts[2]), float(parts[3]), float(parts[4]))
        except ValueError as exc:
            raise ValidateError(f"{path}:{line_no}: malformed numeric value") from exc
        key = (spell_id, level)
        if key in result:
            raise ValidateError(f"{path}:{line_no}: duplicate {spell_id}:{level}")
        result[key] = value
    return result


def spell_levels(path: Path) -> dict[int, int]:
    _fields, _record_size, records, _strings, _trailing = read_dbc(path)
    return {u32(row, SPELL_ID): max(1, u32(row, SPELL_LEVEL)) for row in records}


def close(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=0.0, abs_tol=1e-6)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dbc-dir", required=True, type=Path)
    parser.add_argument("--resolved", required=True, type=Path)
    parser.add_argument("--spell-ranks", required=True, type=Path)
    parser.add_argument("--spell-threat", required=True, type=Path)
    parser.add_argument("--scaling", required=True, type=Path)
    args = parser.parse_args()

    try:
        resolved = load_json(args.resolved.expanduser().resolve())
        spells = resolved.get("spells")
        if not isinstance(spells, list) or not spells:
            raise ValidateError("resolved registry has no spells")

        _root_by_spell, ranks_by_root = parse_spell_ranks(
            args.spell_ranks.expanduser().resolve()
        )
        levels = spell_levels(args.dbc_dir.expanduser().resolve() / "Spell.dbc")
        native = parse_native(args.spell_threat.expanduser().resolve())
        runtime = parse_runtime(args.scaling.expanduser().resolve())

        checked = 0
        families = 0
        for spell in spells:
            custom_id = int(spell["id"])
            root = int(spell["clone_from"])
            family_has_threat = False
            for _rank, native_id in ranks_by_root.get(root, [(1, root)]):
                expected = native.get(native_id)
                if expected is None:
                    continue
                level = levels.get(native_id)
                if level is None:
                    raise ValidateError(f"native spell {native_id} missing from Spell.dbc")
                actual = runtime.get((custom_id, level))
                if actual is None:
                    raise ValidateError(
                        f"{custom_id} root {root}: missing runtime threat at native anchor level {level}"
                    )
                if (
                    actual.flat != expected.flat
                    or not close(actual.pct, expected.pct)
                    or not close(actual.ap_pct, expected.ap_pct)
                ):
                    raise ValidateError(
                        f"{custom_id} root {root} level {level}: expected "
                        f"flat={expected.flat} pct={expected.pct} ap={expected.ap_pct}, got "
                        f"flat={actual.flat} pct={actual.pct} ap={actual.ap_pct}"
                    )
                checked += 1
                family_has_threat = True
            if family_has_threat:
                families += 1

        if checked == 0:
            raise ValidateError("no explicit native threat anchors were validated")
    except ValidateError as exc:
        raise SystemExit(f"Normalized threat validation failed: {exc}") from exc

    print(
        f"Normalized threat validation OK: {checked} native anchors across "
        f"{families} normalized families, max anchor deviation 0.00%"
    )


if __name__ == "__main__":
    main()

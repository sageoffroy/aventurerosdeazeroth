#!/usr/bin/env python3
"""Generate level-aware threat rules for normalized SpellDraft cards.

AzerothCore's spell_threat table is keyed by native spell IDs. Rankless
Aventureros clones use deterministic 200000+root IDs, so they would otherwise
lose native flat threat, threat multipliers, and AP threat coefficients.

This generator resolves every normalized family, reads the explicit native
spell_threat rows, and emits one rule per player level. Native threat rows are
exact anchors; absolute flat threat uses the same level-offset + piecewise
linear integer interpolation as spell magnitudes, while dimensionless
coefficients stay constant below the first anchor and interpolate linearly only
when native rows actually vary.
"""

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


class ThreatError(RuntimeError):
    pass


@dataclass(frozen=True)
class ThreatValue:
    flat: int
    pct: float
    ap_pct: float


@dataclass(frozen=True)
class ThreatAnchor:
    spell_id: int
    level: int
    value: ThreatValue


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ThreatError(f"missing JSON: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ThreatError(f"invalid JSON in {path}: {exc}") from exc


def parse_threat(path: Path) -> dict[int, ThreatValue]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError as exc:
        raise ThreatError(f"missing spell_threat SQL: {path}") from exc

    result: dict[int, ThreatValue] = {}
    for spell_id, flat, pct, ap_pct in THREAT_ROW_RE.findall(text):
        sid = int(spell_id)
        if sid in result:
            raise ThreatError(f"duplicate spell_threat entry {sid}")
        result[sid] = ThreatValue(
            0 if flat == "NULL" else int(flat),
            float(pct),
            float(ap_pct),
        )
    if not result:
        raise ThreatError(f"no spell_threat rows parsed from {path}")
    return result


def spell_levels(path: Path) -> dict[int, int]:
    _fields, _record_size, records, _strings, _trailing = read_dbc(path)
    return {u32(row, SPELL_ID): max(1, u32(row, SPELL_LEVEL)) for row in records}


def signed_scaled(value: int, ratio: float) -> int:
    if value == 0:
        return 0
    magnitude = max(1, int(math.floor(abs(value) * ratio + 0.5)))
    return magnitude if value > 0 else -magnitude


def linear_int(left: int, right: int, t: float) -> int:
    value = left + (right - left) * t
    if value >= 0:
        return int(math.floor(value + 0.5))
    return -int(math.floor(abs(value) + 0.5))


def linear_float(left: float, right: float, t: float) -> float:
    return left + (right - left) * t


def value_at(
    anchors: list[ThreatAnchor],
    level: int,
    low_level_offset: float,
) -> ThreatValue:
    points = sorted(anchors, key=lambda item: item.level)
    first = points[0]

    if level < first.level:
        # Flat threat is an absolute magnitude, so it follows the canonical
        # low-level offset rule. pct/ap coefficients describe mechanics and
        # therefore stay fixed instead of being weakened below the first rank.
        ratio = (level + low_level_offset) / (first.level + low_level_offset)
        return ThreatValue(
            signed_scaled(first.value.flat, ratio),
            first.value.pct,
            first.value.ap_pct,
        )

    if level >= points[-1].level:
        return points[-1].value

    for index in range(len(points) - 1):
        left = points[index]
        right = points[index + 1]
        if left.level <= level <= right.level:
            span = right.level - left.level
            t = 0.0 if span == 0 else (level - left.level) / span
            return ThreatValue(
                linear_int(left.value.flat, right.value.flat, t),
                linear_float(left.value.pct, right.value.pct, t),
                linear_float(left.value.ap_pct, right.value.ap_pct, t),
            )

    raise ThreatError(f"failed to interpolate threat at level {level}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dbc-dir", required=True, type=Path)
    parser.add_argument("--resolved", required=True, type=Path)
    parser.add_argument("--spell-ranks", required=True, type=Path)
    parser.add_argument("--spell-threat", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-level", type=int, default=80)
    parser.add_argument("--low-level-offset", type=float, default=2.0)
    args = parser.parse_args()

    dbc_dir = args.dbc_dir.expanduser().resolve()
    resolved_path = args.resolved.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if args.max_level <= 0:
        raise SystemExit("--max-level must be positive")

    try:
        resolved = load_json(resolved_path)
        spells = resolved.get("spells")
        if not isinstance(spells, list) or not spells:
            raise ThreatError(f"{resolved_path}: expected non-empty spells list")

        _root_by_spell, ranks_by_root = parse_spell_ranks(
            args.spell_ranks.expanduser().resolve()
        )
        levels = spell_levels(dbc_dir / "Spell.dbc")
        threat = parse_threat(args.spell_threat.expanduser().resolve())

        lines = [
            "# custom_spell_threat_scaling.tsv v1",
            "# spell_id\tlevel\tflat_mod\tpct_mod\tap_pct_mod",
        ]
        family_count = 0
        anchor_count = 0

        for spell in sorted(spells, key=lambda item: int(item["id"])):
            custom_id = int(spell["id"])
            root = int(spell["clone_from"])
            rank_rows = ranks_by_root.get(root, [(1, root)])
            anchors: list[ThreatAnchor] = []

            for _rank, native_id in rank_rows:
                value = threat.get(native_id)
                if value is None:
                    continue
                native_level = levels.get(native_id)
                if native_level is None:
                    raise ThreatError(
                        f"native threat spell {native_id} for root {root} is missing from Spell.dbc"
                    )
                anchors.append(ThreatAnchor(native_id, native_level, value))

            if not anchors:
                continue

            # Multiple explicit rows at the same level are collapsed only when
            # their semantics agree; conflicting data should fail loudly.
            by_level: dict[int, ThreatAnchor] = {}
            for anchor in anchors:
                previous = by_level.get(anchor.level)
                if previous and previous.value != anchor.value:
                    raise ThreatError(
                        f"root {root}: conflicting threat anchors at level {anchor.level}"
                    )
                by_level[anchor.level] = anchor
            anchors = [by_level[level] for level in sorted(by_level)]

            for level in range(1, args.max_level + 1):
                value = value_at(anchors, level, args.low_level_offset)
                lines.append(
                    f"{custom_id}\t{level}\t{value.flat}\t"
                    f"{value.pct:.6f}\t{value.ap_pct:.6f}"
                )

            family_count += 1
            anchor_count += len(anchors)

        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except ThreatError as exc:
        raise SystemExit(f"Normalized threat generation aborted: {exc}") from exc

    print(
        f"Normalized threat scaling generated: {family_count} families, "
        f"{anchor_count} explicit native anchors, levels 1-{args.max_level}"
    )
    print(f"  output: {output}")


if __name__ == "__main__":
    main()

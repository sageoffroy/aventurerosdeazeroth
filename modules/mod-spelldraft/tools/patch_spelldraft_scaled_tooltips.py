#!/usr/bin/env python3
"""Install compact client tooltip scaling for normalized 201xxx spells.

The server already derives per-level runtime values from native WoW rank anchors
and writes them to custom_spell_scaling.tsv. The resolved registry preserves the
same native anchors. This tool keeps the client compact: it writes only those
anchors plus a small Lua interpolator instead of serializing 60 rows per spell.

Before touching the client it recomputes every resolved effect with the exact
Python interpolation used by generate_normalized_spells.py and verifies the
result against the server TSV. The loose addon therefore cannot silently drift
from gameplay values.
"""

from __future__ import annotations

import argparse
import json
import shutil
import struct
from dataclasses import dataclass
from pathlib import Path

from generate_normalized_spells import AmountRange, interpolate_ranges
from patch_adventurer_class_dbcs import read_dbc, u32

MODULE = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY = MODULE / "custom_spells.json"

DATA_FILENAME = "AventurerosSpellScaling.lua"
COMPAT_FILENAME = "AventurerosScaledTooltipCompat.lua"
LEGACY_FILENAMES = {"CustomSpellScaling.lua", "SpellDamageCurves.lua"}
TOOLTIP_FILENAME = "ScaledSpellTooltips.lua"

SPELL_ID = 0
EFFECT_DIE_SIDES = 74
EFFECT_BASE_POINTS = 80
EFFECT_AMPLITUDE = 98

DIRECT_DAMAGE_EFFECTS = {2}  # SPELL_EFFECT_SCHOOL_DAMAGE
PERIODIC_DAMAGE_AURA = 3    # SPELL_AURA_PERIODIC_DAMAGE


class TooltipPatchError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeRow:
    duration_ms: int
    effects: tuple[AmountRange | None, AmountRange | None, AmountRange | None]


@dataclass(frozen=True)
class ClientCurve:
    spell_id: int
    source_id: int
    effect_index: int
    static_base_points: int
    static_die_sides: int
    direct_anchors: tuple[tuple[int, AmountRange], ...]
    dot_anchors: tuple[tuple[int, AmountRange], ...] | None
    duration_anchors: tuple[tuple[int, int], ...]
    periodic_amplitude_ms: int
    max_level: int

    @property
    def profile(self) -> str:
        if self.dot_anchors and self.periodic_amplitude_ms > 0 and self.duration_anchors:
            return "spell_damage_with_dots"
        return "spell_damage"


def i32(row: bytes | bytearray, field: int) -> int:
    return struct.unpack_from("<i", row, field * 4)[0]


def load_json(path: Path, label: str) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise TooltipPatchError(f"{label} not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise TooltipPatchError(f"invalid {label} {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise TooltipPatchError(f"{label} must contain a JSON object: {path}")
    return data


def load_low_level_offset(registry_path: Path) -> float:
    data = load_json(registry_path, "custom spell registry")
    scaling = data.get("scaling")
    if not isinstance(scaling, dict) or "low_level_offset" not in scaling:
        raise TooltipPatchError(f"{registry_path}: scaling.low_level_offset is missing")
    try:
        return float(scaling["low_level_offset"])
    except (TypeError, ValueError) as exc:
        raise TooltipPatchError(f"{registry_path}: invalid scaling.low_level_offset") from exc


def load_runtime_scaling(path: Path) -> dict[int, dict[int, RuntimeRow]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise TooltipPatchError(f"server scaling TSV not found: {path}") from exc

    result: dict[int, dict[int, RuntimeRow]] = {}
    for line_number, raw in enumerate(lines, 1):
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        parts = raw.split()
        if len(parts) != 9:
            raise TooltipPatchError(f"{path}:{line_number}: expected 9 fields")
        try:
            spell_id = int(parts[0])
            level = int(parts[1])
            duration_ms = int(parts[2])
            effects: list[AmountRange | None] = []
            for index in range(3):
                low = parts[3 + index * 2]
                high = parts[4 + index * 2]
                if low == "x" and high == "x":
                    effects.append(None)
                elif low == "x" or high == "x":
                    raise ValueError("partial x range")
                else:
                    effects.append(AmountRange(int(low), int(high)))
        except ValueError as exc:
            raise TooltipPatchError(f"{path}:{line_number}: malformed scaling row") from exc

        spell_rows = result.setdefault(spell_id, {})
        if level in spell_rows:
            raise TooltipPatchError(f"{path}:{line_number}: duplicate {spell_id}:{level}")
        spell_rows[level] = RuntimeRow(duration_ms, tuple(effects))  # type: ignore[arg-type]
    return result


def parse_resolved(
    resolved_path: Path,
) -> tuple[int, list[dict], list[tuple[int, int]]]:
    data = load_json(resolved_path, "resolved custom spell registry")
    try:
        max_level = int(data["runtime_max_level"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TooltipPatchError(f"{resolved_path}: runtime_max_level is invalid") from exc

    spells = data.get("spells")
    if not isinstance(spells, list) or not spells:
        raise TooltipPatchError(f"{resolved_path}: expected a non-empty spells list")

    aliases: list[tuple[int, int]] = []
    seen: set[int] = set()
    for index, spell in enumerate(spells):
        if not isinstance(spell, dict):
            raise TooltipPatchError(f"{resolved_path}: spells[{index}] must be an object")
        try:
            spell_id = int(spell["id"])
            source_id = int(spell["clone_from"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TooltipPatchError(f"{resolved_path}: malformed spells[{index}]") from exc
        if not 200000 <= spell_id <= 299999:
            raise TooltipPatchError(f"custom spell ID outside 200000-299999: {spell_id}")
        if spell_id in seen:
            raise TooltipPatchError(f"duplicate custom spell ID: {spell_id}")
        seen.add(spell_id)
        aliases.append((spell_id, source_id))

    aliases.sort()
    return max_level, spells, aliases


def effect_anchors(effect: dict, label: str) -> tuple[tuple[int, AmountRange], ...]:
    raw_anchors = effect.get("anchors")
    if not isinstance(raw_anchors, list) or not raw_anchors:
        raise TooltipPatchError(f"{label}: expected non-empty anchors")
    result: list[tuple[int, AmountRange]] = []
    previous_level = 0
    for index, anchor in enumerate(raw_anchors):
        if not isinstance(anchor, dict):
            raise TooltipPatchError(f"{label}: anchors[{index}] must be an object")
        try:
            level = int(anchor["level"])
            minimum = int(anchor["min"])
            maximum = int(anchor["max"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TooltipPatchError(f"{label}: malformed anchors[{index}]") from exc
        if level <= previous_level or maximum < minimum:
            raise TooltipPatchError(f"{label}: invalid anchor ordering/range at level {level}")
        result.append((level, AmountRange(minimum, maximum)))
        previous_level = level
    return tuple(result)


def spell_rows_by_id(dbc_path: Path) -> dict[int, bytearray]:
    fields, record_size, records, _strings, _trailing = read_dbc(dbc_path)
    if fields < 101 or record_size != fields * 4:
        raise TooltipPatchError(
            f"{dbc_path}: unexpected Spell.dbc layout {fields} fields / {record_size} bytes"
        )
    return {u32(row, SPELL_ID): row for row in records}


def duration_anchors(rows: dict[int, RuntimeRow], max_level: int) -> tuple[tuple[int, int], ...]:
    anchors: list[tuple[int, int]] = []
    previous: int | None = None
    for level in range(1, max_level + 1):
        row = rows.get(level)
        if row is None:
            raise TooltipPatchError(f"runtime scaling is missing level {level}")
        if previous is None or row.duration_ms != previous:
            anchors.append((level, row.duration_ms))
            previous = row.duration_ms
    if anchors and all(value == 0 for _, value in anchors):
        return ()
    return tuple(anchors)


def validate_effect_parity(
    spell_id: int,
    effect_index: int,
    anchors: tuple[tuple[int, AmountRange], ...],
    max_level: int,
    low_level_offset: float,
    runtime_rows: dict[int, RuntimeRow],
) -> None:
    levels = interpolate_ranges(list(anchors), max_level, low_level_offset)
    for level, expected in enumerate(levels, 1):
        row = runtime_rows.get(level)
        if row is None:
            raise TooltipPatchError(f"server TSV missing {spell_id}:{level}")
        actual = row.effects[effect_index]
        if actual != expected:
            raise TooltipPatchError(
                f"server/client scaling mismatch for {spell_id} effect {effect_index} level {level}: "
                f"anchors={expected.minimum}-{expected.maximum}, "
                f"TSV={actual.minimum if actual else 'x'}-{actual.maximum if actual else 'x'}"
            )


def build_curves(
    spells: list[dict],
    max_level: int,
    low_level_offset: float,
    runtime: dict[int, dict[int, RuntimeRow]],
    dbc_rows: dict[int, bytearray],
) -> list[ClientCurve]:
    curves: list[ClientCurve] = []

    for spell in spells:
        spell_id = int(spell["id"])
        source_id = int(spell["clone_from"])
        runtime_rows = runtime.get(spell_id)
        if runtime_rows is None:
            raise TooltipPatchError(f"server TSV has no rows for custom spell {spell_id}")
        if len(runtime_rows) != max_level:
            raise TooltipPatchError(
                f"server TSV has {len(runtime_rows)} rows for {spell_id}; expected {max_level}"
            )

        raw_effects = spell.get("effects")
        if not isinstance(raw_effects, list):
            raise TooltipPatchError(f"resolved spell {spell_id}: effects must be a list")

        parsed_effects: list[tuple[dict, tuple[tuple[int, AmountRange], ...]]] = []
        for raw_effect in raw_effects:
            if not isinstance(raw_effect, dict):
                raise TooltipPatchError(f"resolved spell {spell_id}: malformed effect")
            try:
                effect_index = int(raw_effect["index"])
            except (KeyError, TypeError, ValueError) as exc:
                raise TooltipPatchError(f"resolved spell {spell_id}: invalid effect index") from exc
            if effect_index not in (0, 1, 2):
                raise TooltipPatchError(f"resolved spell {spell_id}: effect index outside 0-2")
            anchors = effect_anchors(raw_effect, f"spell {spell_id} effect {effect_index}")
            validate_effect_parity(
                spell_id,
                effect_index,
                anchors,
                max_level,
                low_level_offset,
                runtime_rows,
            )
            parsed_effects.append((raw_effect, anchors))

        direct = next(
            (
                (effect, anchors)
                for effect, anchors in parsed_effects
                if int(effect.get("effect_type", 0)) in DIRECT_DAMAGE_EFFECTS
            ),
            None,
        )
        if direct is None:
            continue

        direct_effect, direct_anchors = direct
        direct_index = int(direct_effect["index"])
        periodic = next(
            (
                (effect, anchors)
                for effect, anchors in parsed_effects
                if int(effect.get("aura_type", 0)) == PERIODIC_DAMAGE_AURA
            ),
            None,
        )

        dbc_row = dbc_rows.get(spell_id)
        if dbc_row is None:
            raise TooltipPatchError(f"custom spell {spell_id} is missing from Spell.dbc")

        dot_anchors: tuple[tuple[int, AmountRange], ...] | None = None
        periodic_amplitude_ms = 0
        if periodic is not None:
            periodic_effect, dot_anchors = periodic
            periodic_index = int(periodic_effect["index"])
            periodic_amplitude_ms = u32(dbc_row, EFFECT_AMPLITUDE + periodic_index)

        curves.append(
            ClientCurve(
                spell_id=spell_id,
                source_id=source_id,
                effect_index=direct_index,
                static_base_points=i32(dbc_row, EFFECT_BASE_POINTS + direct_index),
                static_die_sides=i32(dbc_row, EFFECT_DIE_SIDES + direct_index),
                direct_anchors=direct_anchors,
                dot_anchors=dot_anchors,
                duration_anchors=duration_anchors(runtime_rows, max_level),
                periodic_amplitude_ms=periodic_amplitude_ms,
                max_level=max_level,
            )
        )

    curves.sort(key=lambda item: item.spell_id)
    return curves


def lua_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return repr(value)


def render_amount_anchors(anchors: tuple[tuple[int, AmountRange], ...]) -> str:
    return "{" + ", ".join(
        f"{{{level}, {amount.minimum}, {amount.maximum}}}" for level, amount in anchors
    ) + "}"


def render_duration_anchors(anchors: tuple[tuple[int, int], ...]) -> str:
    return "{" + ", ".join(f"{{{level}, {value}}}" for level, value in anchors) + "}"


def render_data_lua(
    aliases: list[tuple[int, int]],
    curves: list[ClientCurve],
    max_level: int,
    low_level_offset: float,
) -> str:
    lines = [
        "-- Auto-generated by Aventureros de Azeroth.",
        "-- Compact native-rank anchors; no 1..60 curve tables are serialized.",
        "SpellDraft = SpellDraft or {}",
        "SpellDraftCustomSpellAliases = {}",
        "SpellDraftCustomScaling = {}",
        "SpellDraftDamageCurves = {}",
        "",
        f"local AVENTUREROS_MAX_LEVEL = {max_level}",
        f"local AVENTUREROS_LOW_LEVEL_OFFSET = {lua_number(low_level_offset)}",
        "",
        "local function RoundInt(value)",
        "  if value >= 0 then return math.floor(value + 0.5) end",
        "  return -math.floor(math.abs(value) + 0.5)",
        "end",
        "",
        "local function SignedScaled(value, ratio)",
        "  if value == 0 then return 0 end",
        "  local magnitude = math.max(1, math.floor(math.abs(value) * ratio + 0.5))",
        "  if value > 0 then return magnitude end",
        "  return -magnitude",
        "end",
        "",
        "local function BuildPoints(anchors)",
        "  if not anchors or #anchors == 0 then return {} end",
        "  if anchors[1][1] <= 1 then return anchors end",
        "",
        "  local first = anchors[1]",
        "  local ratio = (1 + AVENTUREROS_LOW_LEVEL_OFFSET) / (first[1] + AVENTUREROS_LOW_LEVEL_OFFSET)",
        "  local points = {{1, SignedScaled(first[2], ratio), SignedScaled(first[3], ratio)}}",
        "  for i = 1, #anchors do points[#points + 1] = anchors[i] end",
        "  return points",
        "end",
        "",
        "local function Interpolate(points, level)",
        "  if level <= points[1][1] then return points[1][2], points[1][3] end",
        "  if level >= points[#points][1] then return points[#points][2], points[#points][3] end",
        "",
        "  for i = 1, #points - 1 do",
        "    local left = points[i]",
        "    local right = points[i + 1]",
        "    if level >= left[1] and level <= right[1] then",
        "      local t = (level - left[1]) / (right[1] - left[1])",
        "      local minimum = RoundInt(left[2] + (right[2] - left[2]) * t)",
        "      local maximum = RoundInt(left[3] + (right[3] - left[3]) * t)",
        "      if maximum < minimum then minimum, maximum = maximum, minimum end",
        "      return minimum, maximum",
        "    end",
        "  end",
        "end",
        "",
        "local function MakeRanges(anchors)",
        "  local points = BuildPoints(anchors)",
        "  return setmetatable({}, {",
        "    __index = function(cache, requestedLevel)",
        "      local level = tonumber(requestedLevel)",
        "      if not level then return nil end",
        "      level = math.floor(level)",
        "      if level < 1 then level = 1 end",
        "      if level > AVENTUREROS_MAX_LEVEL then level = AVENTUREROS_MAX_LEVEL end",
        "      local minimum, maximum = Interpolate(points, level)",
        "      if minimum == nil then return nil end",
        "      local value = {minimum, maximum}",
        "      rawset(cache, requestedLevel, value)",
        "      return value",
        "    end,",
        "  })",
        "end",
        "",
        "local function StepValue(anchors, level)",
        "  if not anchors or #anchors == 0 then return 0 end",
        "  local value = anchors[1][2]",
        "  for i = 2, #anchors do",
        "    if level < anchors[i][1] then break end",
        "    value = anchors[i][2]",
        "  end",
        "  return value",
        "end",
        "",
        "local function MakeDots(amountAnchors, durationAnchors, amplitudeMs)",
        "  if not amountAnchors or not durationAnchors or amplitudeMs <= 0 then return nil end",
        "  local points = BuildPoints(amountAnchors)",
        "  return setmetatable({}, {",
        "    __index = function(cache, requestedLevel)",
        "      local level = tonumber(requestedLevel)",
        "      if not level then return nil end",
        "      level = math.floor(level)",
        "      if level < 1 then level = 1 end",
        "      if level > AVENTUREROS_MAX_LEVEL then level = AVENTUREROS_MAX_LEVEL end",
        "      local minimum, maximum = Interpolate(points, level)",
        "      if minimum == nil or minimum ~= maximum then return nil end",
        "      local durationMs = StepValue(durationAnchors, level)",
        "      if durationMs <= 0 then return nil end",
        "      local ticks = math.floor(durationMs / amplitudeMs)",
        "      if ticks <= 0 then return nil end",
        "      local value = {total = minimum * ticks, duration = durationMs / 1000}",
        "      rawset(cache, requestedLevel, value)",
        "      return value",
        "    end,",
        "  })",
        "end",
        "",
    ]

    for custom_id, source_id in aliases:
        lines.append(f"SpellDraftCustomSpellAliases[{custom_id}] = {source_id}")

    lines.extend([
        "",
        "function SpellDraft.GetCustomSpellSourceID(spellID)",
        "  return SpellDraftCustomSpellAliases[tonumber(spellID)]",
        "end",
        "",
        "local function AddDamageCurve(spellID, profile, effectIndex, staticBase, staticDie, directAnchors, dotAnchors, durationAnchors, amplitudeMs)",
        "  SpellDraftCustomScaling[spellID] = {",
        "    profile = profile,",
        "    baseLevel = 1,",
        "    maxLevel = AVENTUREROS_MAX_LEVEL,",
        "    effects = {{",
        "      index = effectIndex + 1,",
        "      basePoints = staticBase,",
        "      dieSides = staticDie,",
        "      realPointsPerLevel = 0,",
        "    }},",
        "  }",
        "",
        "  local curve = {",
        "    profile = profile,",
        "    maxLevel = AVENTUREROS_MAX_LEVEL,",
        "    anchors = directAnchors,",
        "    ranges = MakeRanges(directAnchors),",
        "  }",
        "  if dotAnchors and durationAnchors and amplitudeMs > 0 then",
        "    curve.dotAnchors = dotAnchors",
        "    curve.durationAnchors = durationAnchors",
        "    curve.dots = MakeDots(dotAnchors, durationAnchors, amplitudeMs)",
        "  end",
        "  SpellDraftDamageCurves[spellID] = curve",
        "end",
        "",
    ])

    for curve in curves:
        dot = "nil" if curve.dot_anchors is None else render_amount_anchors(curve.dot_anchors)
        durations = (
            "nil" if not curve.duration_anchors else render_duration_anchors(curve.duration_anchors)
        )
        lines.append(
            "AddDamageCurve("
            f"{curve.spell_id}, \"{curve.profile}\", {curve.effect_index}, "
            f"{curve.static_base_points}, {curve.static_die_sides}, "
            f"{render_amount_anchors(curve.direct_anchors)}, {dot}, {durations}, "
            f"{curve.periodic_amplitude_ms})"
        )

    lines.append("")
    return "\n".join(lines)


def render_compat_lua() -> str:
    return """-- Auto-generated by Aventureros de Azeroth.
-- Extends the historical tooltip formatter for custom spells whose native
-- description renders a single static number instead of a min-max range.
SpellDraft = SpellDraft or {}

local BaseFormatScaledSpellDescription = SpellDraft.FormatScaledSpellDescription

local function EscapePattern(text)
  return tostring(text):gsub("(%W)", "%%%1")
end

local function ReplaceToken(text, token, replacement)
  if token == nil or token == "" then return nil end
  local pattern = "%f[%d]" .. EscapePattern(token) .. "%f[%D]"
  local changed, count = text:gsub(pattern, replacement, 1)
  if count > 0 then return changed end
  return nil
end

if BaseFormatScaledSpellDescription then
  function SpellDraft.FormatScaledSpellDescription(spellID, text, level)
    local updated = BaseFormatScaledSpellDescription(spellID, text, level)
    if not text or updated ~= text then return updated end

    local id = tonumber(spellID)
    local curve = SpellDraftDamageCurves and SpellDraftDamageCurves[id]
    if not curve or not curve.ranges then return updated end

    local currentLevel = tonumber(level) or UnitLevel("player") or 1
    local current = curve.ranges[currentLevel]
    if not current then return updated end

    local replacement = tostring(current[1])
    if current[2] ~= current[1] then
      replacement = replacement .. "-" .. tostring(current[2])
    end

    local meta = SpellDraftCustomScaling and SpellDraftCustomScaling[id]
    local effect = meta and meta.effects and meta.effects[1]
    if not effect then return updated end

    local base = tonumber(effect.basePoints) or 0
    local die = tonumber(effect.dieSides) or 0
    local tokens = {}
    if die > 0 then
      local minimum = base + 1
      local maximum = base + die
      tokens = {
        tostring(minimum) .. "-" .. tostring(maximum),
        tostring(maximum) .. "-" .. tostring(minimum),
        tostring(minimum),
        tostring(maximum),
      }
    else
      tokens = {
        tostring(base + 1) .. "-" .. tostring(base),
        tostring(base) .. "-" .. tostring(base + 1),
        tostring(base),
        tostring(base + 1),
      }
    end

    for _, token in ipairs(tokens) do
      local changed = ReplaceToken(updated, token, replacement)
      if changed then return changed end
    end
    return updated
  end
end
"""


def patch_toc(toc_path: Path) -> bool:
    if not toc_path.is_file():
        raise TooltipPatchError(f"SpellDraft TOC not found: {toc_path}")

    original = toc_path.read_text(encoding="utf-8")
    removable = LEGACY_FILENAMES | {DATA_FILENAME, COMPAT_FILENAME}
    lines = [line for line in original.splitlines() if line.strip() not in removable]

    try:
        tooltip_index = next(i for i, line in enumerate(lines) if line.strip() == TOOLTIP_FILENAME)
    except StopIteration as exc:
        raise TooltipPatchError(f"{toc_path}: {TOOLTIP_FILENAME} entry not found") from exc

    lines.insert(tooltip_index, DATA_FILENAME)
    lines.insert(tooltip_index + 2, COMPAT_FILENAME)
    patched = "\n".join(lines) + "\n"
    if patched == original:
        return False

    backup = toc_path.with_name(toc_path.name + ".aventureros-original")
    if not backup.exists():
        shutil.copy2(toc_path, backup)
    toc_path.write_text(patched, encoding="utf-8")
    return True


def validate_install(addon_dir: Path, aliases: list[tuple[int, int]], curves: list[ClientCurve]) -> None:
    toc_path = addon_dir / "SpellDraft.toc"
    data_path = addon_dir / DATA_FILENAME
    compat_path = addon_dir / COMPAT_FILENAME
    toc_lines = [line.strip() for line in toc_path.read_text(encoding="utf-8").splitlines()]

    for legacy in LEGACY_FILENAMES:
        if legacy in toc_lines:
            raise TooltipPatchError(f"{toc_path}: legacy per-level curve file still loads: {legacy}")
    for filename in (DATA_FILENAME, TOOLTIP_FILENAME, COMPAT_FILENAME):
        if toc_lines.count(filename) != 1:
            raise TooltipPatchError(f"{toc_path}: expected exactly one {filename} entry")
    if toc_lines.index(DATA_FILENAME) + 1 != toc_lines.index(TOOLTIP_FILENAME):
        raise TooltipPatchError(f"{DATA_FILENAME} must load immediately before {TOOLTIP_FILENAME}")
    if toc_lines.index(COMPAT_FILENAME) != toc_lines.index(TOOLTIP_FILENAME) + 1:
        raise TooltipPatchError(f"{COMPAT_FILENAME} must load immediately after {TOOLTIP_FILENAME}")

    data_text = data_path.read_text(encoding="utf-8")
    if "ranges = {" in data_text:
        raise TooltipPatchError(f"{data_path}: serialized per-level range table detected")
    missing_aliases = [
        custom_id for custom_id, source_id in aliases
        if f"SpellDraftCustomSpellAliases[{custom_id}] = {source_id}" not in data_text
    ]
    if missing_aliases:
        raise TooltipPatchError(
            "generated tooltip aliases missing: " + ", ".join(str(value) for value in missing_aliases[:10])
        )
    missing_curves = [
        curve.spell_id for curve in curves
        if f"AddDamageCurve({curve.spell_id}," not in data_text
    ]
    if missing_curves:
        raise TooltipPatchError(
            "generated damage anchors missing: " + ", ".join(str(value) for value in missing_curves[:10])
        )
    if not compat_path.is_file() or "BaseFormatScaledSpellDescription" not in compat_path.read_text(encoding="utf-8"):
        raise TooltipPatchError(f"tooltip compatibility file was not installed correctly: {compat_path}")


def patch_client(
    client_dir: Path,
    resolved_path: Path,
    scaling_path: Path,
    dbc_dir: Path,
    registry_path: Path,
) -> tuple[int, int, int, bool]:
    addon_dir = client_dir / "Interface" / "AddOns" / "SpellDraft"
    if not addon_dir.is_dir():
        raise TooltipPatchError(f"SpellDraft addon directory not found: {addon_dir}")

    max_level, spells, aliases = parse_resolved(resolved_path)
    low_level_offset = load_low_level_offset(registry_path)
    runtime = load_runtime_scaling(scaling_path)
    dbc_rows = spell_rows_by_id(dbc_dir / "Spell.dbc")
    curves = build_curves(spells, max_level, low_level_offset, runtime, dbc_rows)
    if not curves:
        raise TooltipPatchError("resolved registry contains no direct-damage custom spells")

    data_path = addon_dir / DATA_FILENAME
    compat_path = addon_dir / COMPAT_FILENAME
    desired_data = render_data_lua(aliases, curves, max_level, low_level_offset)
    desired_compat = render_compat_lua()

    changed = False
    if not data_path.is_file() or data_path.read_text(encoding="utf-8") != desired_data:
        data_path.write_text(desired_data, encoding="utf-8")
        changed = True
    if not compat_path.is_file() or compat_path.read_text(encoding="utf-8") != desired_compat:
        compat_path.write_text(desired_compat, encoding="utf-8")
        changed = True
    if patch_toc(addon_dir / "SpellDraft.toc"):
        changed = True

    validate_install(addon_dir, aliases, curves)
    anchor_count = sum(len(curve.direct_anchors) for curve in curves)
    return len(aliases), len(curves), anchor_count, changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client-dir", required=True, type=Path)
    parser.add_argument("--resolved", required=True, type=Path)
    parser.add_argument("--scaling", required=True, type=Path)
    parser.add_argument("--dbc-dir", required=True, type=Path)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    args = parser.parse_args()

    try:
        aliases, curves, anchors, changed = patch_client(
            args.client_dir.expanduser().resolve(),
            args.resolved.expanduser().resolve(),
            args.scaling.expanduser().resolve(),
            args.dbc_dir.expanduser().resolve(),
            args.registry.expanduser().resolve(),
        )
    except TooltipPatchError as exc:
        raise SystemExit(f"SpellDraft compact tooltip patch aborted: {exc}") from exc

    print("SpellDraft compact tooltip scaling validated:")
    print(f"  aliases: {aliases} custom 201xxx -> native roots")
    print(f"  direct-damage spells: {curves}")
    print(f"  serialized native anchors: {anchors} (not {curves * 60} per-level rows)")
    print("  parity: native anchors reproduce every server TSV level exactly")
    print(f"  status: {'patched' if changed else 'already valid'}")
    print(f"  client data: {DATA_FILENAME}")
    print(f"  tooltip compatibility: {COMPAT_FILENAME}")
    print("  legacy CustomSpellScaling.lua / SpellDamageCurves.lua: no longer loaded")
    print("  no C++ rebuild required")


if __name__ == "__main__":
    main()

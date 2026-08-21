#!/usr/bin/env python3
"""Install a final client tooltip pass that can rewrite multiple damage ranges per paragraph.

Some localized WotLK descriptions keep direct damage and periodic total in the
same GameTooltip text line. The older profiled repair replaced at most one
range per line, so spells such as Frostfire Bolt could show a corrected direct
range while leaving a stale direct-derived range in the DoT clause.

This installer adds a small Lua pass after AventurerosProfiledTooltip.lua. The
extra TOC entry is intentionally unknown to the main profile patcher, so later
profile regenerations preserve it on the same client.
"""

from __future__ import annotations

import argparse
from pathlib import Path

FILENAME = "AventurerosMultiRangeTooltipFix.lua"
PROFILE_FILENAME = "AventurerosProfiledTooltip.lua"
TOC_FILENAME = "SpellDraft.toc"

LUA = r'''-- Aventureros de Azeroth: final multi-range tooltip repair.
SpellDraft = SpellDraft or {}

local RANGE_PATTERNS = {
  { pattern = "[dD]e%s+%d+%s+a%s+%d+%s*%-%s*%d+", style = "spanish" },
  { pattern = "[dD]e%s+%d+%s+a%s+%d+", style = "spanish" },
  { pattern = "%d+%s+to%s+%d+%s*%-%s*%d+", style = "english" },
  { pattern = "%d+%s+to%s+%d+", style = "english" },
  { pattern = "%d+%s*%-%s*%d+", style = "compact" },
}

local function TooltipSpellID(tip)
  if not tip or not tip.GetSpell then return nil end
  local _name, second, third = tip:GetSpell()
  local id = tonumber(third) or tonumber(second)
  if not id then return nil end
  if not SpellDraftCustomSpellAliases or not SpellDraftCustomSpellAliases[id] then return nil end
  return id
end

local function OrderedPair(minimum, maximum)
  minimum = tonumber(minimum)
  maximum = tonumber(maximum)
  if not minimum or not maximum then return nil, nil end
  if maximum < minimum then minimum, maximum = maximum, minimum end
  return minimum, maximum
end

local function ReplacementText(minimum, maximum, style)
  minimum, maximum = OrderedPair(minimum, maximum)
  if not minimum then return nil end
  if minimum == maximum then return tostring(minimum) end
  if style == "spanish" then
    return "de " .. tostring(minimum) .. " a " .. tostring(maximum)
  end
  if style == "english" then
    return tostring(minimum) .. " to " .. tostring(maximum)
  end
  return tostring(minimum) .. "-" .. tostring(maximum)
end

local function FindNextRange(text, startAt)
  local bestStart, bestEnd, bestStyle
  startAt = startAt or 1
  for _, entry in ipairs(RANGE_PATTERNS) do
    local first, last = text:find(entry.pattern, startAt)
    if first and (
      not bestStart
      or first < bestStart
      or (first == bestStart and last > bestEnd)
    ) then
      bestStart = first
      bestEnd = last
      bestStyle = entry.style
    end
  end
  return bestStart, bestEnd, bestStyle
end

local function RewriteRangesInText(text, replacements, replacementIndex)
  local changed = false
  local searchFrom = 1
  local index = replacementIndex

  while index <= #replacements do
    local first, last, style = FindNextRange(text, searchFrom)
    if not first then break end

    local pair = replacements[index]
    local replacement = ReplacementText(pair[1], pair[2], style)
    if not replacement then break end

    text = text:sub(1, first - 1) .. replacement .. text:sub(last + 1)
    searchFrom = first + #replacement
    index = index + 1
    changed = true
  end

  return text, index, changed
end

local function UpdateMultiRangeTooltip(tip)
  local spellID = TooltipSpellID(tip)
  if not spellID then return end

  local curve = SpellDraftDamageCurves and SpellDraftDamageCurves[spellID]
  if not curve or not curve.ranges then return end

  local level = UnitLevel("player") or 1
  local direct = curve.ranges[level]
  if not direct then return end

  local replacements = {
    { direct[1], direct[2] },
  }

  local dot = curve.dots and curve.dots[level]
  if dot and tonumber(dot.total) then
    local total = tonumber(dot.total)
    replacements[#replacements + 1] = { total, total }
  end

  local name = tip:GetName()
  if not name then return end

  local replacementIndex = 1
  local count = tip:NumLines() or 0
  for i = 2, count do
    if replacementIndex > #replacements then break end
    local left = _G[name .. "TextLeft" .. i]
    if left then
      local text = left:GetText()
      if text then
        local updated, nextIndex, changed = RewriteRangesInText(
          text,
          replacements,
          replacementIndex
        )
        if changed then left:SetText(updated) end
        replacementIndex = nextIndex
      end
    end
  end
end

local function HookTooltip(tip)
  if tip and tip.HookScript then
    tip:HookScript("OnTooltipSetSpell", UpdateMultiRangeTooltip)
  end
end

HookTooltip(GameTooltip)
HookTooltip(ItemRefTooltip)
'''


def install(client_dir: Path) -> tuple[bool, bool]:
    addon = client_dir / "Interface" / "AddOns" / "SpellDraft"
    if not addon.is_dir():
        raise SystemExit(f"SpellDraft addon directory not found: {addon}")

    output = addon / FILENAME
    lua_changed = not output.is_file() or output.read_text(encoding="utf-8") != LUA
    if lua_changed:
        output.write_text(LUA, encoding="utf-8")

    toc_path = addon / TOC_FILENAME
    if not toc_path.is_file():
        raise SystemExit(f"SpellDraft TOC not found: {toc_path}")

    original = toc_path.read_text(encoding="utf-8")
    lines = [line for line in original.splitlines() if line.strip() != FILENAME]
    try:
        profile_index = next(i for i, line in enumerate(lines) if line.strip() == PROFILE_FILENAME)
    except StopIteration as exc:
        raise SystemExit(f"{PROFILE_FILENAME} entry not found in {toc_path}") from exc

    lines.insert(profile_index + 1, FILENAME)
    patched = "\n".join(lines) + "\n"
    toc_changed = patched != original
    if toc_changed:
        toc_path.write_text(patched, encoding="utf-8")

    return lua_changed, toc_changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client-dir", required=True, type=Path)
    args = parser.parse_args()

    lua_changed, toc_changed = install(args.client_dir.expanduser().resolve())
    print("Aventureros multi-range tooltip fix installed:")
    print(f"  lua: {'updated' if lua_changed else 'already current'}")
    print(f"  toc: {'updated' if toc_changed else 'already current'}")
    print("  direct + DoT ranges in the same tooltip paragraph are rewritten independently")
    print("  min/max endpoints are always ordered before display")


if __name__ == "__main__":
    main()

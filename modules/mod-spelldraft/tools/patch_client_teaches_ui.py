#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

BEGIN_MARKER = "-- SPELLDRAFT_TEACHES_UI_BEGIN"
END_MARKER = "-- SPELLDRAFT_TEACHES_UI_END"
CALL_MARKER = "        -- SPELLDRAFT_TEACHES_UI_UPDATE\n        UpdateTeachSlots(btn, spellID)\n"

CUSTOM_SPELL_OFFSET = 200000
CUSTOM_SPELL_MAX = 299999


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Instala en el SpellChoice.lua vivo la UI de habilidades asociadas "
            "usando card_dependencies.json como fuente de verdad."
        )
    )
    parser.add_argument(
        "--client-dir",
        required=True,
        help="Raíz del cliente WoW 3.3.5a, por ejemplo /mnt/c/Games/World of Warcraft 3.3.5a",
    )
    return parser.parse_args()


def load_teaches(repo_root: Path) -> dict[int, list[int]]:
    dependencies_path = repo_root / "modules/mod-spelldraft/card_dependencies.json"
    data = json.loads(dependencies_path.read_text(encoding="utf-8"))

    teaches: dict[int, list[int]] = {}
    for root_text, meta in data.get("cards", {}).items():
        taught = meta.get("teaches") or []
        if taught:
            teaches[int(root_text)] = [int(spell_id) for spell_id in taught]
    return teaches


def build_lua_block(teaches: dict[int, list[int]]) -> str:
    table_lines = []
    for root in sorted(teaches):
        ids = ", ".join(str(spell_id) for spell_id in teaches[root])
        table_lines.append(f"  [{root}] = {{{ids}}},")

    table_body = "\n".join(table_lines)

    return f'''{BEGIN_MARKER}
-- Generated from modules/mod-spelldraft/card_dependencies.json.
-- Do not hand-maintain the associations here: rerun patch_client_teaches_ui.py.
local SPELLDRAFT_TEACHES_BY_NATIVE_ROOT = {{
{table_body}
}}

local TEACH_SLOT_COUNT = 4
local TEACH_SLOT_SIZE = 46
local TEACH_ICON_SIZE = 34
local TEACH_SLOT_X = 188
local TEACH_SLOT_Y = -78
local TEACH_SLOT_STEP = 42

local function GetCardNativeRoot(spellID)
  spellID = tonumber(spellID) or 0
  if spellID >= {CUSTOM_SPELL_OFFSET} and spellID <= {CUSTOM_SPELL_MAX} then
    return spellID - {CUSTOM_SPELL_OFFSET}
  end
  return spellID
end

local function EnsureTeachSlots(btn)
  if btn.teachSlots then
    return
  end

  btn.teachSlots = {{}}

  for slotIndex = 1, TEACH_SLOT_COUNT do
    local slot = CreateFrame("Button", nil, btn)
    slot:SetWidth(TEACH_SLOT_SIZE)
    slot:SetHeight(TEACH_SLOT_SIZE)
    slot:SetPoint(
      "TOPLEFT",
      btn,
      "TOPLEFT",
      TEACH_SLOT_X,
      TEACH_SLOT_Y - ((slotIndex - 1) * TEACH_SLOT_STEP)
    )
    slot:SetFrameLevel(btn:GetFrameLevel() + 10)

    local square = slot:CreateTexture(nil, "BACKGROUND")
    square:SetAllPoints(slot)
    square:SetTexture(
      "Interface\\AddOns\\SpellDraft\\Textures\\SQUARE.tga"
    )
    slot.square = square

    local icon = slot:CreateTexture(nil, "ARTWORK")
    icon:SetWidth(TEACH_ICON_SIZE)
    icon:SetHeight(TEACH_ICON_SIZE)
    icon:SetPoint("CENTER", slot, "CENTER", 0, 0)
    slot.icon = icon

    local more = slot:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    more:SetPoint("BOTTOMRIGHT", slot, "BOTTOMRIGHT", -2, 2)
    more:SetJustifyH("RIGHT")
    more:SetTextColor(1.0, 0.82, 0.0)
    more:SetShadowOffset(1, -1)
    more:SetShadowColor(0, 0, 0, 1)
    slot.more = more

    slot:SetScript("OnEnter", function(self)
      local taughtID = self.taughtSpellID
      if taughtID and taughtID > 0 then
        GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
        GameTooltip:SetHyperlink("spell:" .. taughtID)
        GameTooltip:AddLine(
          "También aprenderás esta habilidad",
          0.35,
          1.0,
          0.35
        )
        GameTooltip:Show()
      end
    end)

    slot:SetScript("OnLeave", function()
      GameTooltip:Hide()
    end)

    slot:SetScript("OnClick", function()
      -- Visual information only. The parent card remains the selectable action.
    end)

    slot:Hide()
    btn.teachSlots[slotIndex] = slot
  end
end

local function UpdateTeachSlots(btn, cardSpellID)
  EnsureTeachSlots(btn)

  local nativeRoot = GetCardNativeRoot(cardSpellID)
  local teaches = SPELLDRAFT_TEACHES_BY_NATIVE_ROOT[nativeRoot] or {{}}

  for slotIndex = 1, TEACH_SLOT_COUNT do
    local slot = btn.teachSlots[slotIndex]
    local taughtID = teaches[slotIndex]

    if taughtID then
      local _, _, taughtIcon = GetSpellInfo(taughtID)

      slot.taughtSpellID = taughtID
      slot.more:SetText("")

      if taughtIcon then
        -- Reuse the same CustomIcons lookup as the main card icon.
        slot.icon:SetTexture(GetCardIcon(taughtID, taughtIcon))
      else
        slot.icon:SetTexture("Interface\\Icons\\INV_Misc_QuestionMark")
      end

      if slotIndex == TEACH_SLOT_COUNT and #teaches > TEACH_SLOT_COUNT then
        slot.more:SetText("+" .. (#teaches - TEACH_SLOT_COUNT))
      end

      slot:Show()
    else
      slot.taughtSpellID = nil
      slot.more:SetText("")
      slot:Hide()
    end
  end
end
{END_MARKER}

'''


def strip_previous_patch(text: str) -> str:
    if BEGIN_MARKER in text:
        begin = text.index(BEGIN_MARKER)
        end = text.index(END_MARKER, begin) + len(END_MARKER)
        while end < len(text) and text[end] in "\r\n":
            end += 1
        text = text[:begin] + text[end:]

    text = text.replace(CALL_MARKER, "")
    return text


def patch_spellchoice(text: str, lua_block: str) -> str:
    text = strip_previous_patch(text)

    show_marker = "-- Show spell choices to the player"
    if show_marker not in text:
        raise RuntimeError(
            "No se encontró el marcador de ShowSpellChoices; no se modificó el addon."
        )

    text = text.replace(show_marker, lua_block + show_marker, 1)

    layout_call = "        ApplySpellChoiceCardLayout(btn)\n"
    if layout_call not in text:
        raise RuntimeError(
            "No se encontró ApplySpellChoiceCardLayout(btn); no se modificó el addon."
        )

    text = text.replace(
        layout_call,
        layout_call + "\n" + CALL_MARKER,
        1,
    )

    return text


def main() -> None:
    args = parse_args()

    script_path = Path(__file__).resolve()
    repo_root = script_path.parents[3]

    client_dir = Path(args.client_dir).expanduser().resolve()
    addon_dir = client_dir / "Interface/AddOns/SpellDraft"
    lua_path = addon_dir / "SpellChoice.lua"
    square_path = addon_dir / "Textures/SQUARE.tga"

    if not lua_path.is_file():
        raise SystemExit(f"No existe: {lua_path}")

    if not square_path.is_file():
        raise SystemExit(
            f"No existe {square_path}. Copiá SQUARE.tga a Textures antes de instalar la UI."
        )

    teaches = load_teaches(repo_root)
    if 1515 not in teaches:
        raise SystemExit(
            "card_dependencies.json no contiene teaches para Domesticar bestia (1515)."
        )

    original = lua_path.read_text(encoding="utf-8")
    patched = patch_spellchoice(original, build_lua_block(teaches))

    backup_path = lua_path.with_suffix(".lua.pre-teaches.bak")
    if not backup_path.exists():
        shutil.copy2(lua_path, backup_path)

    lua_path.write_text(patched, encoding="utf-8")

    print(f"OK: {lua_path}")
    print(f"Backup: {backup_path}")
    print(
        "Domesticar bestia (1515): "
        + ", ".join(str(spell_id) for spell_id in teaches[1515])
    )
    print(f"Asociaciones instaladas: {len(teaches)}")
    print("Slots visibles por carta: 4 (el cuarto muestra +N si hay más).")


if __name__ == "__main__":
    main()

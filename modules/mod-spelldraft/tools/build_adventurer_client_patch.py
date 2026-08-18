#!/usr/bin/env python3
"""Build the WotLK 3.3.5a client patch for native Adventurer class ID 10.

The builder keeps the root and locale MPQs intentionally disjoint:

* Data/patch-Z.mpq contains only the GlueXML override.
* Data/<locale>/patch-<locale>-z.mpq contains only patched DBC files.

This avoids mounting identical payloads twice, which previously caused unstable
3.3.5a clients. The DBC transformation itself is shared with the server-side
patcher so client and server always receive the same class definition.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from mpq_writer import write_mpq
from patch_adventurer_class_dbcs import (
    patch_charbaseinfo,
    patch_charstartoutfit,
    patch_chrclasses,
    patch_skillraceclassinfo,
    validate_charbaseinfo,
    validate_charstartoutfit,
)

MODULE = Path(__file__).resolve().parent.parent
LEGACY_REPO = "https://github.com/sageoffroy/wowrandom.git"
LEGACY_COMMIT = "8e2c3c8c89d857164e33dda7db2cccd185467cdb"
LEGACY_GLUE_PATH = "client-patch/Interface/GlueXML/CharacterCreate.lua"

DBC_NAMES = (
    "ChrClasses.dbc",
    "CharBaseInfo.dbc",
    "CharStartOutfit.dbc",
    "SkillRaceClassInfo.dbc",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_character_create_baseline(explicit: Path | None) -> bytes:
    """Load the known-good GlueXML baseline.

    Prefer an explicitly supplied file, then a future vendored baseline. Until
    that baseline is fully migrated into this repository, fall back to the
    frozen legacy commit. The fallback uses the user's normal Git credentials
    and fetches only that single commit.
    """

    if explicit:
        path = explicit.expanduser().resolve()
        if not path.is_file():
            raise SystemExit(f"GlueXML baseline not found: {path}")
        return path.read_bytes()

    bundled = MODULE / "client-baseline" / "Interface" / "GlueXML" / "CharacterCreate.lua"
    if bundled.is_file():
        return bundled.read_bytes()

    with tempfile.TemporaryDirectory(prefix="spelldraft-glue-") as td:
        repo = Path(td) / "legacy"
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "remote", "add", "origin", LEGACY_REPO],
            check=True,
        )
        try:
            subprocess.run(
                [
                    "git", "-C", str(repo), "fetch", "-q", "--depth", "1",
                    "origin", LEGACY_COMMIT,
                ],
                check=True,
            )
            return subprocess.check_output(
                ["git", "-C", str(repo), "show", f"FETCH_HEAD:{LEGACY_GLUE_PATH}"]
            )
        except subprocess.CalledProcessError as exc:
            raise SystemExit(
                "Could not obtain the frozen CharacterCreate.lua baseline. "
                "Make sure your GitHub credentials can read sageoffroy/wowrandom, "
                "or pass --character-create-lua with an extracted baseline."
            ) from exc


def replace_lua_function(text: str, start_marker: str, next_marker: str, replacement: str) -> str:
    start = text.find(start_marker)
    if start < 0:
        raise SystemExit(f"GlueXML patch: missing {start_marker}")
    end = text.find(next_marker, start)
    if end < 0:
        raise SystemExit(f"GlueXML patch: missing function boundary {next_marker}")
    return text[:start] + replacement.rstrip() + "\n\n" + text[end:]


def adventurer_character_create_lua(baseline: bytes) -> bytes:
    text = baseline.decode("utf-8")

    old = "local TECHNICAL_CLASS_ID = 1; -- Warrior; hidden from the player."
    new = "local ADVENTURER_CLASS_INDEX = nil;"
    if old not in text:
        raise SystemExit("GlueXML baseline does not contain the expected technical-class marker")
    text = text.replace(old, new, 1)

    start = text.find("local function SelectTechnicalClassForCurrentRace()")
    end = text.find("function CharacterCreate_OnLoad(self)", start)
    if start < 0 or end < 0:
        raise SystemExit("GlueXML patch: missing SelectTechnicalClassForCurrentRace")

    text = text[:start] + """local function ResolveOnlyValidClassForCurrentRace()
\tlocal selectedRace = GetSelectedRace();
\tlocal found = nil;
\tlocal validCount = 0;

\tfor classIndex=1, CharacterCreate.numClasses do
\t\tif ( IsRaceClassValid(selectedRace, classIndex) ) then
\t\t\tfound = classIndex;
\t\t\tvalidCount = validCount + 1;
\t\tend
\tend

\tif ( validCount ~= 1 ) then
\t\tmessage(\"SpellDraft error: se esperaba exactamente 1 clase valida para esta raza, pero hay \"..validCount..\". Revisa CharBaseInfo.dbc.\");
\t\treturn nil;
\tend

\treturn found;
end

local function SelectTechnicalClassForCurrentRace()
\tADVENTURER_CLASS_INDEX = ResolveOnlyValidClassForCurrentRace();
\tif ( not ADVENTURER_CLASS_INDEX ) then
\t\treturn nil;
\tend

\tSetSelectedClass(ADVENTURER_CLASS_INDEX);
\tSetCharacterClass(ADVENTURER_CLASS_INDEX);
\treturn ADVENTURER_CLASS_INDEX;
end

""" + text[end:]

    text = replace_lua_function(
        text,
        "function CharacterCreateEnumerateClasses(...)",
        "function SetCharacterRace(id)",
        """function CharacterCreateEnumerateClasses(...)
\tCharacterCreate.numClasses = select(\"#\", ...)/3;
\tADVENTURER_CLASS_INDEX = nil;
\tHideClassSelectionUI();
end""",
    )

    text = replace_lua_function(
        text,
        "function SetCharacterClass(id)",
        "function CharacterCreate_OnChar()",
        """function SetCharacterClass(id)
\tCharacterCreate.selectedClass = id;

\tlocal className, classFileName = GetSelectedClass();
\tlocal abilityIndex = 0;
\tlocal tempText = _G[\"CLASS_INFO_\"..classFileName..abilityIndex];
\tabilityText = \"\";
\twhile ( tempText ) do
\t\tabilityText = abilityText..tempText..\"\\n\\n\";
\t\tabilityIndex = abilityIndex + 1;
\t\ttempText = _G[\"CLASS_INFO_\"..classFileName..abilityIndex];
\tend

\tlocal coords = CLASS_ICON_TCOORDS[classFileName] or CLASS_ICON_TCOORDS[\"WARRIOR\"];
\tCharacterCreateClassIcon:SetTexCoord(coords[1], coords[2], coords[3], coords[4]);
\tCharacterCreateClassLabel:SetText(className);
\tCharacterCreateClassRolesText:SetText(abilityText);
\tCharacterCreateClassText:SetText(GetFlavorText(\"CLASS_\"..strupper(classFileName), GetSelectedSex())..\"|n|n\");
\tCharacterCreateClassScrollFrameScrollBar:SetValue(0);
end""",
    )

    old_create = """\telse
\t\tCreateCharacter(CharacterCreateNameEdit:GetText());
\tend"""
    new_create = """\telse
\t\tif ( not SelectTechnicalClassForCurrentRace() ) then
\t\t\treturn;
\t\tend
\t\tCreateCharacter(CharacterCreateNameEdit:GetText());
\tend"""
    if old_create not in text:
        raise SystemExit("GlueXML patch: could not guard CharacterCreate_Okay")
    text = text.replace(old_create, new_create, 1)

    return text.encode("utf-8")


def copy_patched_server_dbcs(work: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for name in DBC_NAMES:
        source = work / name
        if not source.is_file():
            continue
        target = destination / name
        if target.exists():
            backup = target.with_name(target.name + ".pre-adventurer.bak")
            if not backup.exists():
                shutil.copy2(target, backup)
        shutil.copy2(source, target)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dbc-src", required=True, type=Path,
                        help="Directory containing clean/extracted 3.3.5a DBC files")
    parser.add_argument("--output-dir", type=Path,
                        default=MODULE / "build" / "adventurer-client-patch")
    parser.add_argument("--locale", default="esES",
                        help="Client locale directory, default: esES")
    parser.add_argument("--server-dbc-dir", type=Path,
                        help="Optional live server DBC directory to receive the same patched DBCs")
    parser.add_argument("--character-create-lua", type=Path,
                        help="Optional extracted CharacterCreate.lua baseline")
    args = parser.parse_args()

    source = args.dbc_src.expanduser().resolve()
    missing = [name for name in DBC_NAMES if not (source / name).is_file()]
    if missing:
        raise SystemExit("Missing DBC input(s): " + ", ".join(missing))

    output = args.output_dir.expanduser().resolve()
    data_dir = output / "Data"
    root_output = data_dir / "patch-Z.mpq"
    locale_output = data_dir / args.locale / f"patch-{args.locale}-z.mpq"

    baseline = load_character_create_baseline(args.character_create_lua)

    with tempfile.TemporaryDirectory(prefix="spelldraft-adventurer-") as td:
        work = Path(td)
        for name in DBC_NAMES:
            shutil.copy2(source / name, work / name)

        patch_chrclasses(work / "ChrClasses.dbc")
        patch_charbaseinfo(work / "CharBaseInfo.dbc")
        patch_charstartoutfit(work / "CharStartOutfit.dbc")
        patch_skillraceclassinfo(work / "SkillRaceClassInfo.dbc")
        validate_charbaseinfo(work / "CharBaseInfo.dbc")
        validate_charstartoutfit(work / "CharStartOutfit.dbc")

        root_files = {
            "Interface\\GlueXML\\CharacterCreate.lua": adventurer_character_create_lua(baseline),
        }
        locale_files = {
            f"DBFilesClient\\{name}": (work / name).read_bytes()
            for name in DBC_NAMES
        }

        root_output.parent.mkdir(parents=True, exist_ok=True)
        locale_output.parent.mkdir(parents=True, exist_ok=True)
        write_mpq(root_output, root_files)
        write_mpq(locale_output, locale_files)

        if args.server_dbc_dir:
            copy_patched_server_dbcs(work, args.server_dbc_dir.expanduser().resolve())

    manifest = {
        "class_id": 10,
        "locale": args.locale,
        "root_patch": str(root_output),
        "root_sha256": sha256(root_output),
        "locale_patch": str(locale_output),
        "locale_sha256": sha256(locale_output),
        "dbc_source": str(source),
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    if manifest["root_sha256"] == manifest["locale_sha256"]:
        raise SystemExit("Safety check failed: root and locale MPQs are byte-identical")

    print("Adventurer client patch built successfully:")
    print(f"  root:   {root_output}")
    print(f"  locale: {locale_output}")
    print("  validation: exactly one Adventurer class per playable race")
    if args.server_dbc_dir:
        print(f"  server DBCs updated: {args.server_dbc_dir.expanduser().resolve()}")


if __name__ == "__main__":
    main()

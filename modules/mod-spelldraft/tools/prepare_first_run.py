#!/usr/bin/env python3
"""Prepare server DBCs, configs, Lua runtime and client MPQs for first run.

This orchestrates only the safe tooling already present in mod-spelldraft. It
does NOT start MySQL, authserver or worldserver and it does NOT rebuild C++.
Before changing any local runtime file it runs the repository self-test.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
MODULE = TOOLS_DIR.parent
REPO = MODULE.parents[1]
DEFAULT_INSTALL = REPO / "env" / "dist"
DEFAULT_OUTPUT = MODULE / "build" / "adventurer-client-patch"
DEFAULT_LOCALE = "esMX"
REQUIRED_DBCS = (
    "ChrClasses.dbc",
    "CharBaseInfo.dbc",
    "CharStartOutfit.dbc",
    "SkillRaceClassInfo.dbc",
    "Spell.dbc",
    "SpellCastTimes.dbc",
    "SpellDuration.dbc",
    "SkillLine.dbc",
    "SkillLineAbility.dbc",
    "Talent.dbc",
)


def run(*args: str) -> None:
    print()
    print("+", " ".join(args))
    subprocess.run(args, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--client-dir",
        required=True,
        type=Path,
        help="WoW 3.3.5a client root (directory containing Wow.exe)",
    )
    parser.add_argument("--install-dir", type=Path, default=DEFAULT_INSTALL)
    parser.add_argument(
        "--server-data-dir",
        type=Path,
        help="Runtime game-data directory; default: <install>/data",
    )
    parser.add_argument(
        "--dbc-src",
        type=Path,
        help="Prepared/extracted DBC source; default: <server-data-dir>/dbc",
    )
    parser.add_argument("--locale", default=DEFAULT_LOCALE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    install = args.install_dir.expanduser().resolve()
    data_dir = (
        args.server_data_dir.expanduser().resolve()
        if args.server_data_dir
        else install / "data"
    )
    server_dbc = data_dir / "dbc"
    dbc_src = (
        args.dbc_src.expanduser().resolve()
        if args.dbc_src
        else server_dbc
    )
    client = args.client_dir.expanduser().resolve()
    output = args.output_dir.expanduser().resolve()

    missing = [name for name in REQUIRED_DBCS if not (dbc_src / name).is_file()]
    if missing:
        raise SystemExit(
            f"DBC source is incomplete: {dbc_src}\nMissing: " + ", ".join(missing)
        )

    wow = client / "Wow.exe"
    if not wow.is_file():
        wow = client / "wow.exe"
    if not wow.is_file():
        raise SystemExit(f"WoW client not found in {client}")

    spell_data = client / "Interface" / "AddOns" / "SpellDraft" / "SpellData.lua"
    if not spell_data.is_file():
        raise SystemExit(
            "Historical SpellDraft metadata not found in the current client: "
            f"{spell_data}\n"
            "The real-pool migration needs SpellData.lua for the curated rarity/class mapping."
        )

    runtime_catalog = install / "bin" / "lua_scripts" / "SpellDraft" / "catalog.lua"
    normalized_data = data_dir / "spelldraft"
    normalized_resolved = normalized_data / "custom_spells.resolved.json"
    normalized_profiles = normalized_data / "custom_spell_profiles.resolved.json"
    normalized_scaling = normalized_data / "custom_spell_scaling.tsv"

    print("=== Aventureros de Azeroth: preparacion primera ejecucion ===")
    print(f"install:       {install}")
    print(f"server data:   {data_dir}")
    print(f"DBC source:    {dbc_src}")
    print(f"client:        {client}")
    print(f"locale:        {args.locale}")
    print(f"SpellData:     {spell_data}")

    run(sys.executable, str(TOOLS_DIR / "validate_repo_assets.py"))

    run(
        sys.executable,
        str(TOOLS_DIR / "prepare_runtime_configs.py"),
        "--install-dir",
        str(install),
        "--data-dir",
        str(data_dir),
    )

    run(
        sys.executable,
        str(TOOLS_DIR / "stage_lua_runtime.py"),
        "--install-dir",
        str(install),
    )

    # Select rank families and create one 201xxx DBC clone per family. The
    # reviewed wrapper delegates the clone/effect work to
    # generate_normalized_spells.py; this first pass also writes generic effect
    # anchors used as the safe fallback for profiles not specialized yet.
    run(
        sys.executable,
        str(TOOLS_DIR / "generate_reviewed_normalized_spells.py"),
        "--dbc-dir",
        str(dbc_src),
        "--spell-data",
        str(spell_data),
        "--resolved-output",
        str(normalized_resolved),
        "--scaling-output",
        str(normalized_scaling),
    )

    # Strip inherited rank/skill semantics. The old conservative cast-time
    # choice is intentionally overwritten by the profile stage immediately
    # below; the custom DBC fallback becomes the native root/rank-1 cast again.
    run(
        sys.executable,
        str(TOOLS_DIR / "finalize_normalized_spell_dbcs.py"),
        "--dbc-dir",
        str(dbc_src),
        "--resolved",
        str(normalized_resolved),
    )

    # Resolve profile-aware native anchors. damage_with_dot spells explicitly
    # carry direct damage, total DoT, duration and cast time. All profiles get
    # interpolated cast/duration values; un-specialized effects retain the
    # generic effect-curve fallback. This overwrites the runtime TSV with v2.
    run(
        sys.executable,
        str(TOOLS_DIR / "generate_profiled_spell_scaling.py"),
        "--dbc-dir",
        str(dbc_src),
        "--resolved",
        str(normalized_resolved),
        "--scaling-output",
        str(normalized_scaling),
        "--profiles-output",
        str(normalized_profiles),
    )

    # Fail before packaging if a native rank anchor does not round-trip exactly
    # through the profile runtime representation.
    run(
        sys.executable,
        str(TOOLS_DIR / "validate_profiled_spell_scaling.py"),
        "--profiles",
        str(normalized_profiles),
        "--scaling",
        str(normalized_scaling),
        "--dbc-dir",
        str(dbc_src),
    )

    # Build the canonical native draft pool first. SpellData.lua is used only
    # as the authored rarity/class map; levels, passivity, skill-line scope,
    # talent exclusion and rank chains come from live/current data.
    run(
        sys.executable,
        str(TOOLS_DIR / "generate_spelldraft_catalog.py"),
        "--dbc-dir",
        str(dbc_src),
        "--spell-data",
        str(spell_data),
        "--output",
        str(runtime_catalog),
    )

    # Remove reviewed false roots entirely, then strictly replace every selected
    # native root with its rankless 201xxx card.
    run(
        sys.executable,
        str(TOOLS_DIR / "apply_reviewed_normalized_catalog.py"),
        "--catalog",
        str(runtime_catalog),
        "--resolved",
        str(normalized_resolved),
    )

    # The historical Grimoire recognizes only IDs present in SpellData.lua.
    run(
        sys.executable,
        str(TOOLS_DIR / "patch_spelldraft_grimoire.py"),
        "--client-dir",
        str(client),
        "--resolved",
        str(normalized_resolved),
    )

    # Install the same semantic native-rank anchors in the loose addon. The
    # client interpolates direct damage, total DoT, duration and cast time from
    # anchors instead of serializing 60 rows per spell.
    run(
        sys.executable,
        str(TOOLS_DIR / "patch_spelldraft_profiled_tooltips.py"),
        "--client-dir",
        str(client),
        "--profiles",
        str(normalized_profiles),
        "--dbc-dir",
        str(dbc_src),
    )

    # The stock 3.3.5a client does not expose native combo-point packet state to
    # GetComboPoints() for custom class ID 10.
    run(
        sys.executable,
        str(TOOLS_DIR / "patch_spelldraft_combo_ui.py"),
        "--client-dir",
        str(client),
    )

    # AzerothCore only loads the stock playercreateinfo_skills language/racial
    # rows when SkillRaceClassInfo.dbc also authorizes the race/class pair.
    run(
        sys.executable,
        str(TOOLS_DIR / "patch_adventurer_native_race_skills.py"),
        str(dbc_src),
    )

    # Z is the sole Aventureros client patch family. Besides class DBCs it now
    # packages the same normalized Spell.dbc + SkillLineAbility.dbc used by the
    # server so client spell IDs/tooltips cannot drift.
    run(
        sys.executable,
        str(TOOLS_DIR / "build_adventurer_client_patch.py"),
        "--dbc-src",
        str(dbc_src),
        "--server-dbc-dir",
        str(server_dbc),
        "--output-dir",
        str(output),
        "--locale",
        args.locale,
    )

    run(
        sys.executable,
        str(TOOLS_DIR / "install_adventurer_client_patch.py"),
        "--client-dir",
        str(client),
        "--patch-dir",
        str(output),
        "--locale",
        args.locale,
    )

    run(
        sys.executable,
        str(TOOLS_DIR / "check_first_run.py"),
        "--install-dir",
        str(install),
        "--dbc-src",
        str(dbc_src),
        "--client-dir",
        str(client),
        "--locale",
        args.locale,
    )

    print()
    print("Preparacion completa.")
    print("SpellDraft real catalog generated from live DBCs.")
    print("Reviewed early-game native spell families replaced by normalized 201xxx cards.")
    print("Profile-aware anchors generated: damage/effects + DoT total + duration + cast time.")
    print("Normalized 201xxx metadata aliases installed for the SpellDraft Grimoire.")
    print("Compact profile-aware tooltips installed; legacy per-level client curves disabled.")
    print("Adventurer combo-point client compatibility installed for Blizzard ComboFrame.")
    print("No se inicio MySQL, authserver ni worldserver.")
    print("Este script no recompila C++; el puente de cast-time debe estar compilado en worldserver.")


if __name__ == "__main__":
    main()

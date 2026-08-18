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
        help="Clean/extracted DBC source; default: <server-data-dir>/dbc",
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

    print("=== Aventureros de Azeroth: preparacion primera ejecucion ===")
    print(f"install:       {install}")
    print(f"server data:   {data_dir}")
    print(f"DBC source:    {dbc_src}")
    print(f"client:        {client}")
    print(f"locale:        {args.locale}")

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

    # AzerothCore only loads the stock playercreateinfo_skills language/racial
    # rows when SkillRaceClassInfo.dbc also authorizes the race/class pair.
    # Extend those existing DBC masks to native class 10 before packaging the
    # same DBC into both the server runtime and the client Z patch.
    run(
        sys.executable,
        str(TOOLS_DIR / "patch_adventurer_native_race_skills.py"),
        str(dbc_src),
    )

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
    print("No se inicio MySQL, authserver ni worldserver.")
    print("No fue necesario recompilar el core.")


if __name__ == "__main__":
    main()

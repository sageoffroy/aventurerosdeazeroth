#!/usr/bin/env python3
"""Run the canonical first-run preparation and then project spell extensions.

This wrapper intentionally delegates the established DBC/catalog/client pipeline
to prepare_first_run.py. Only after that pipeline has generated and validated its
normal assets does it enrich the same runtime catalog/scaling TSV/addon metadata
with project_spell_extensions.json.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
MODULE = TOOLS.parent
REPO = MODULE.parents[1]
DEFAULT_INSTALL = REPO / "env" / "dist"
DEFAULT_OUTPUT = MODULE / "build" / "adventurer-client-patch"
DEFAULT_LOCALE = "esMX"


def run(*args: str) -> None:
    print()
    print("+", " ".join(args))
    subprocess.run(args, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client-dir", required=True, type=Path)
    parser.add_argument("--install-dir", type=Path, default=DEFAULT_INSTALL)
    parser.add_argument("--server-data-dir", type=Path)
    parser.add_argument("--dbc-src", type=Path)
    parser.add_argument("--locale", default=DEFAULT_LOCALE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    prepare_args = [
        sys.executable,
        str(TOOLS / "prepare_first_run.py"),
        "--client-dir",
        str(args.client_dir),
        "--install-dir",
        str(args.install_dir),
        "--locale",
        args.locale,
        "--output-dir",
        str(args.output_dir),
    ]
    if args.server_data_dir:
        prepare_args.extend(["--server-data-dir", str(args.server_data_dir)])
    if args.dbc_src:
        prepare_args.extend(["--dbc-src", str(args.dbc_src)])
    run(*prepare_args)

    install = args.install_dir.expanduser().resolve()
    data_dir = (
        args.server_data_dir.expanduser().resolve()
        if args.server_data_dir
        else install / "data"
    )
    dbc_dir = (
        args.dbc_src.expanduser().resolve()
        if args.dbc_src
        else data_dir / "dbc"
    )
    client = args.client_dir.expanduser().resolve()

    run(
        sys.executable,
        str(TOOLS / "apply_project_spell_extensions.py"),
        "--dbc-dir",
        str(dbc_dir),
        "--catalog",
        str(install / "bin" / "lua_scripts" / "SpellDraft" / "catalog.lua"),
        "--scaling",
        str(data_dir / "spelldraft" / "custom_spell_scaling.tsv"),
        "--client-dir",
        str(client),
    )

    print()
    print("Project spell extensions applied on top of the canonical prepared assets.")
    print("Mirror Image is now a native Epic draft card available from level 1.")
    print("Its Frostbolt/Fire Blast support spells scale from the owning player's level.")
    print("No undeclared pet/guardian spell is modified by the extension layer.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Prepare Aventureros runtime, then apply SpellDraft packages, reviewed mutations and audit pool."""

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

    install = args.install_dir.expanduser().resolve()
    data_dir = (
        args.server_data_dir.expanduser().resolve()
        if args.server_data_dir
        else install / "data"
    )
    server_dbc = data_dir / "dbc"
    dbc_src = args.dbc_src.expanduser().resolve() if args.dbc_src else server_dbc
    client = args.client_dir.expanduser().resolve()
    output = args.output_dir.expanduser().resolve()
    runtime_catalog = install / "bin" / "lua_scripts" / "SpellDraft" / "catalog.lua"
    resolved = data_dir / "spelldraft" / "custom_spells.resolved.json"
    scaling = data_dir / "spelldraft" / "custom_spell_scaling.tsv"

    prepare_args = [
        sys.executable,
        str(TOOLS_DIR / "prepare_first_run.py"),
        "--client-dir",
        str(client),
        "--install-dir",
        str(install),
        "--locale",
        args.locale,
        "--output-dir",
        str(output),
    ]
    if args.server_data_dir:
        prepare_args.extend(["--server-data-dir", str(data_dir)])
    if args.dbc_src:
        prepare_args.extend(["--dbc-src", str(dbc_src)])
    run(*prepare_args)

    run(
        sys.executable,
        str(TOOLS_DIR / "apply_card_packages.py"),
        "--dbc-dir",
        str(dbc_src),
        "--catalog",
        str(runtime_catalog),
        "--resolved",
        str(resolved),
    )

    # Package cards clone a native spell only for icon/presentation. Strip any
    # inherited localized Rank 1 / Rango 1 subtext so the virtual card itself is
    # visibly rankless, just like normalized custom abilities.
    run(
        sys.executable,
        str(TOOLS_DIR / "finalize_package_cards.py"),
        "--dbc-dir",
        str(dbc_src),
    )

    # Reviewed special cases mutate the already-normalized runtime card without
    # creating a second scaling path. Numeric amounts stay owned by the normalizer.
    # If the reviewed design changes duration, the same stage patches the duration
    # column in the canonical runtime scaling table so C++ cannot reapply the old
    # native-family duration at cast time.
    run(
        sys.executable,
        str(TOOLS_DIR / "apply_reviewed_spell_mutations.py"),
        "--dbc-dir",
        str(dbc_src),
        "--catalog",
        str(runtime_catalog),
        "--resolved",
        str(resolved),
        "--scaling",
        str(scaling),
    )

    # The audit whitelist is deliberately applied only to the generated runtime
    # catalog. Source metadata and dependency entries remain intact and are
    # restored automatically by the next preparation run.
    run(
        sys.executable,
        str(TOOLS_DIR / "apply_audit_pool.py"),
        "--catalog",
        str(runtime_catalog),
    )

    # prepare_first_run already built the client patch once. Build/install it
    # again so the final MPQ contains package cards and reviewed DBC mutations.
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
    print("Preparacion con paquetes y mutaciones revisadas completa.")
    print("Maestro de Portales: carta pasiva Epic nivel 1, icono Portal: Stormwind.")
    print("Ensenia solo los Portales de la faccion del personaje, mas Dalaran.")
    print("Los Portales no requieren componentes; Teleports/Portals individuales quedan fuera del pool.")
    print("Teleport: Moonglade usa el ID nativo y solo es elegible para Elfos de la Noche.")
    print("Arcane Intellect conserva identidad/escalado, usa comportamiento grupal y fuerza duracion runtime de 1 hora.")
    print("Las cartas-paquete son marcadores sin rango visible (sin Rank 1 / Rango 1 heredado).")
    print("Audit pool: si audit_pool.json esta habilitado, solo ofrece su whitelist.")


if __name__ == "__main__":
    main()

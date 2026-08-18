#!/usr/bin/env python3
"""Non-destructive readiness check for the first Aventureros de Azeroth run."""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
MODULE = TOOLS_DIR.parent
REPO = MODULE.parents[1]
DEFAULT_INSTALL = REPO / "env" / "dist"
REQUIRED_GAME_DATA = ("dbc", "maps", "vmaps", "mmaps")
REQUIRED_ADVENTURER_DBCS = (
    "ChrClasses.dbc",
    "CharBaseInfo.dbc",
    "CharStartOutfit.dbc",
    "SkillRaceClassInfo.dbc",
)


def mark(ok: bool) -> str:
    return "OK" if ok else "FALTA"


def parse_data_dir(config: Path) -> str | None:
    if not config.is_file():
        return None
    pattern = re.compile(r'^\s*DataDir\s*=\s*["\']?(.+?)["\']?\s*$')
    for raw in config.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = pattern.match(raw)
        if match:
            return match.group(1).strip().strip('"\'')
    return None


def game_data_score(path: Path) -> tuple[int, list[str]]:
    found = [name for name in REQUIRED_GAME_DATA if (path / name).is_dir()]
    return len(found), found


def candidate_data_dirs(install: Path, configured: str | None) -> list[Path]:
    candidates: list[Path] = []
    bin_dir = install / "bin"

    if configured:
        configured_path = Path(configured).expanduser()
        if configured_path.is_absolute():
            candidates.append(configured_path)
        else:
            # worldserver is normally launched from env/dist/bin. Resolve the
            # configured relative path there first, but also report common
            # extraction layouts so the checker remains useful before config.
            candidates.append((bin_dir / configured_path).resolve())

    candidates.extend(
        [
            bin_dir,
            bin_dir / "data",
            install / "data",
            REPO / "game-data",
        ]
    )

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--install-dir", type=Path, default=DEFAULT_INSTALL)
    parser.add_argument("--dbc-src", type=Path,
                        help="Optional clean/extracted DBC source to validate")
    parser.add_argument("--client-dir", type=Path,
                        help="Optional WoW 3.3.5a client directory to validate")
    args = parser.parse_args()

    install = args.install_dir.expanduser().resolve()
    bin_dir = install / "bin"
    etc_dir = install / "etc"
    module_conf_dir = etc_dir / "modules"

    print("=== Aventureros de Azeroth: chequeo de primera ejecucion ===")
    print(f"repo:    {REPO}")
    print(f"install: {install}")
    print()

    binaries = ("worldserver", "authserver")
    print("BINARIOS")
    for name in binaries:
        path = bin_dir / name
        print(f"  [{mark(path.is_file())}] {path}")
    print()

    config_pairs = (
        (etc_dir / "worldserver.conf", etc_dir / "worldserver.conf.dist"),
        (etc_dir / "authserver.conf", etc_dir / "authserver.conf.dist"),
        (module_conf_dir / "SpellDraft.conf", module_conf_dir / "SpellDraft.conf.dist"),
        (module_conf_dir / "mod_ale.conf", module_conf_dir / "mod_ale.conf.dist"),
    )

    print("CONFIGURACION")
    for live, dist in config_pairs:
        if live.is_file():
            print(f"  [OK] {live}")
        elif dist.is_file():
            print(f"  [FALTA .conf] {live}  (existe {dist.name})")
        else:
            print(f"  [FALTA] {live} y su .dist")
    print()

    world_conf = etc_dir / "worldserver.conf"
    if not world_conf.is_file():
        world_conf = etc_dir / "worldserver.conf.dist"
    configured_data_dir = parse_data_dir(world_conf)

    print("DATOS DEL JUEGO")
    print(f"  DataDir configurado: {configured_data_dir!r} ({world_conf})")
    ranked = []
    for candidate in candidate_data_dirs(install, configured_data_dir):
        score, found = game_data_score(candidate)
        ranked.append((score, candidate, found))
    ranked.sort(key=lambda item: item[0], reverse=True)

    best_score, best_path, best_found = ranked[0]
    for score, candidate, found in ranked:
        if score:
            missing = [name for name in REQUIRED_GAME_DATA if name not in found]
            print(
                f"  [{score}/4] {candidate}"
                + (f"  faltan: {', '.join(missing)}" if missing else "  COMPLETO")
            )
    if best_score == 0:
        print("  [FALTA] no encontre dbc/maps/vmaps/mmaps en las rutas habituales")
    print()

    sql = REPO / "data" / "sql" / "custom" / "db_world" / "spelldraft_adventurer_class_10.sql"
    print("SPELLDRAFT / ADVENTURER")
    print(f"  [{mark(sql.is_file())}] SQL custom: {sql}")
    baseline = MODULE / "client-baseline" / "Interface" / "GlueXML" / "CharacterCreate.lua"
    print(f"  [{mark(baseline.is_file())}] GlueXML baseline: {baseline}")
    for script in (
        "build_adventurer_client_patch.py",
        "install_adventurer_client_patch.py",
        "patch_adventurer_class_dbcs.py",
        "mpq_writer.py",
    ):
        path = TOOLS_DIR / script
        print(f"  [{mark(path.is_file())}] {script}")
    print()

    if args.dbc_src:
        dbc_src = args.dbc_src.expanduser().resolve()
        print("DBC SOURCE")
        print(f"  {dbc_src}")
        for name in REQUIRED_ADVENTURER_DBCS:
            print(f"  [{mark((dbc_src / name).is_file())}] {name}")
        print()

    if args.client_dir:
        client = args.client_dir.expanduser().resolve()
        wow = client / "Wow.exe"
        if not wow.is_file():
            wow = client / "wow.exe"
        print("CLIENTE")
        print(f"  [{mark(wow.is_file())}] Wow.exe: {wow}")
        print(f"  [{mark((client / 'Data').is_dir())}] Data/: {client / 'Data'}")
        print()

    mysql = shutil.which("mysql") or shutil.which("mariadb")
    print("BASE DE DATOS")
    if mysql:
        print(f"  [OK] cliente MySQL/MariaDB disponible: {mysql}")
    else:
        print("  [AVISO] no encontre mysql/mariadb CLI en PATH")
    print("  El chequeo NO intenta conectarse ni modifica ninguna base de datos.")
    print()

    if best_score == len(REQUIRED_GAME_DATA):
        print(f"Mejor DataDir detectado: {best_path}")
    else:
        print("Todavia faltan datos runtime o hay que indicarle al servidor su ubicacion.")


if __name__ == "__main__":
    main()

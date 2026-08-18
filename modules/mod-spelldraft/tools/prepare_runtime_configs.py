#!/usr/bin/env python3
"""Create missing runtime .conf files from installed .conf.dist templates.

This helper is intentionally conservative: it never overwrites an existing
configuration file. Optional DataDir replacement is applied only to a config
created during the current invocation.
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
MODULE = TOOLS_DIR.parent
REPO = MODULE.parents[1]
DEFAULT_INSTALL = REPO / "env" / "dist"

CONFIGS = (
    ("etc/authserver.conf.dist", "etc/authserver.conf"),
    ("etc/worldserver.conf.dist", "etc/worldserver.conf"),
    ("etc/modules/mod_ale.conf.dist", "etc/modules/mod_ale.conf"),
    ("etc/modules/SpellDraft.conf.dist", "etc/modules/SpellDraft.conf"),
)


def set_data_dir(path: Path, data_dir: Path) -> None:
    text = path.read_text(encoding="utf-8")
    replacement = f'DataDir = "{data_dir}"'
    updated, count = re.subn(
        r'^\s*DataDir\s*=.*$',
        replacement,
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise SystemExit(f"Could not find exactly one DataDir setting in {path}")
    path.write_text(updated, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--install-dir", type=Path, default=DEFAULT_INSTALL)
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="Set DataDir only if worldserver.conf is created by this run",
    )
    args = parser.parse_args()

    install = args.install_dir.expanduser().resolve()
    created: set[Path] = set()

    for source_rel, target_rel in CONFIGS:
        source = install / source_rel
        target = install / target_rel

        if target.exists():
            print(f"KEEP: {target}")
            continue
        if not source.is_file():
            raise SystemExit(f"Missing installed template: {source}")

        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        created.add(target)
        print(f"CREATE: {target}")

    world_conf = install / "etc" / "worldserver.conf"
    if args.data_dir:
        data_dir = args.data_dir.expanduser().resolve()
        if world_conf in created:
            set_data_dir(world_conf, data_dir)
            print(f"SET: DataDir = {data_dir}")
        else:
            print(
                "KEEP: worldserver.conf already existed, so --data-dir was not "
                "applied. Edit the existing file explicitly if needed."
            )

    spell_conf = install / "etc" / "modules" / "SpellDraft.conf"
    if spell_conf.is_file():
        text = spell_conf.read_text(encoding="utf-8")
        if "SpellDraft.Enable = 1" in text:
            print("OK: SpellDraft.Enable = 1")
        else:
            print("AVISO: revisar SpellDraft.Enable en SpellDraft.conf")

    print("Runtime config preparation complete. Existing configs were not overwritten.")


if __name__ == "__main__":
    main()

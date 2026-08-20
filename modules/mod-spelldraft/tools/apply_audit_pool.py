#!/usr/bin/env python3
"""Restrict the generated SpellDraft offer pool to the temporary audit whitelist."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
DEFAULT_AUDIT_POOL = TOOLS_DIR.parent / "audit_pool.json"


class AuditPoolError(RuntimeError):
    pass


def load_audit_pool(path: Path) -> tuple[bool, set[int]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditPoolError(f"cannot read {path}: {exc}") from exc

    if raw.get("version") != 1:
        raise AuditPoolError(f"{path}: expected version=1")

    enabled = bool(raw.get("enabled", False))
    spells = raw.get("spells")
    if not isinstance(spells, list):
        raise AuditPoolError(f"{path}: spells must be a list")

    ids: set[int] = set()
    for entry in spells:
        if not isinstance(entry, dict) or "id" not in entry:
            raise AuditPoolError(f"{path}: every spell needs an id")
        spell_id = entry["id"]
        if isinstance(spell_id, bool) or not isinstance(spell_id, int) or spell_id <= 0:
            raise AuditPoolError(f"{path}: invalid spell id {spell_id!r}")
        if spell_id in ids:
            raise AuditPoolError(f"{path}: duplicate spell id {spell_id}")
        ids.add(spell_id)

    if enabled and not ids:
        raise AuditPoolError("audit pool is enabled but the whitelist is empty")

    return enabled, ids


def patch_catalog(path: Path, allowed_ids: set[int]) -> tuple[int, int]:
    lines = path.read_text(encoding="utf-8").splitlines()
    entry_re = re.compile(r"^(\s*\{ id = (\d+),.*? minLevel = )(\d+)(,.*)$")
    requires_re = re.compile(r"requires = \{[^}]*\}")

    found: set[int] = set()
    blocked = 0
    result: list[str] = []

    for line in lines:
        match = entry_re.match(line)
        if not match:
            result.append(line)
            continue

        spell_id = int(match.group(2))
        if spell_id in allowed_ids:
            found.add(spell_id)
            result.append(line)
            continue

        # Keep the entry physically present so TeachMap/dependency resolution can
        # still find it, but make it impossible to offer while audit mode is on.
        line = f"{match.group(1)}999{match.group(4)}"
        line, count = requires_re.subn(
            'requires = { "__spelldraft_audit_blocked__" }',
            line,
            count=1,
        )
        if count != 1:
            raise AuditPoolError(
                f"catalog entry {spell_id}: could not replace requires table"
            )
        blocked += 1
        result.append(line)

    missing = sorted(allowed_ids - found)
    if missing:
        raise AuditPoolError(
            "audit whitelist IDs missing from generated catalog: "
            + ", ".join(str(value) for value in missing)
        )

    path.write_text("\n".join(result) + "\n", encoding="utf-8")
    return len(found), blocked


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--audit-pool", type=Path, default=DEFAULT_AUDIT_POOL)
    args = parser.parse_args()

    try:
        enabled, allowed_ids = load_audit_pool(args.audit_pool.expanduser().resolve())
        if not enabled:
            print("SpellDraft audit whitelist disabled; full generated pool preserved.")
            return
        allowed, blocked = patch_catalog(
            args.catalog.expanduser().resolve(),
            allowed_ids,
        )
    except AuditPoolError as exc:
        raise SystemExit(f"SpellDraft audit pool aborted: {exc}") from exc

    print(
        f"SpellDraft audit whitelist active: allowed={allowed}, blocked={blocked}"
    )
    print("  allowed IDs: " + ", ".join(str(value) for value in sorted(allowed_ids)))


if __name__ == "__main__":
    main()

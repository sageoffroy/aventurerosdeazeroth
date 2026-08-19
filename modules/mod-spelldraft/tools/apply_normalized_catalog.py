#!/usr/bin/env python3
"""Replace selected native SpellDraft cards with normalized 201xxx cards.

Input catalog.lua is produced by generate_spelldraft_catalog.py. The resolved
registry is produced by generate_normalized_spells.py from the exact same base
eligibility rules. This stage performs a strict one-for-one replacement:

* the native root card is removed;
* its custom 201xxx card inherits name, rarity and class origin;
* the custom card has one rank (itself) at level 1;
* every selected native family must be replaced exactly once or generation
  aborts.

Native higher ranks were never cards in the production catalog; they remain only
inside Spell.dbc as anchor/source data for the normalizer.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

CATALOG_LINE_RE = re.compile(
    r'^\s*\{ id = (\d+), rarity = (-?\d+), classSet = (\d+), minLevel = (\d+), '
    r'name = "((?:\\.|[^"])*)", '
    r'((?:grants = \{.*?\}, requires = \{.*?\}, synergy = \{.*?\}, )?)'
    r'ranks = \{.*\} \},\s*$'
)


class ReplaceError(RuntimeError):
    pass


def lua_quote(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", " ")
        .replace("\n", " ")
    )


def load_replacements(path: Path) -> dict[int, dict[str, object]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReplaceError(f"resolved custom spell registry not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ReplaceError(f"invalid resolved custom spell registry {path}: {exc}") from exc

    spells = data.get("spells")
    if not isinstance(spells, list) or not spells:
        raise ReplaceError(f"{path}: expected a non-empty spells list")

    replacements: dict[int, dict[str, object]] = {}
    custom_ids: set[int] = set()
    for index, spell in enumerate(spells):
        if not isinstance(spell, dict):
            raise ReplaceError(f"spells[{index}] must be an object")
        custom_id = int(spell["id"])
        source = int(spell["clone_from"])
        if not 200000 <= custom_id <= 299999:
            raise ReplaceError(f"custom spell {custom_id} is outside 200000-299999")
        if source in replacements:
            raise ReplaceError(f"native root {source} is replaced more than once")
        if custom_id in custom_ids:
            raise ReplaceError(f"custom spell ID {custom_id} is duplicated")
        replacements[source] = spell
        custom_ids.add(custom_id)
    return replacements


def replace_catalog(path: Path, replacements: dict[int, dict[str, object]]) -> tuple[int, int]:
    if not path.is_file():
        raise ReplaceError(f"SpellDraft runtime catalog not found: {path}")

    lines = path.read_text(encoding="utf-8").splitlines()
    found: dict[int, int] = {root: 0 for root in replacements}
    native_roots: set[int] = set()
    custom_ids = {int(spell["id"]) for spell in replacements.values()}
    output: list[str] = []
    catalog_entries = 0

    for line in lines:
        match = CATALOG_LINE_RE.match(line)
        if not match:
            output.append(line)
            continue

        root = int(match.group(1))
        catalog_entries += 1
        if root in custom_ids:
            raise ReplaceError(
                f"catalog already contains custom ID {root}; normalized replacement must run from native roots"
            )
        if root not in replacements:
            output.append(line)
            continue

        found[root] += 1
        native_roots.add(root)
        spell = replacements[root]

        # Do not trust duplicated metadata in the resolved JSON when the native
        # production catalog is the canonical source for current rarity/class.
        rarity = int(match.group(2))
        class_set = int(match.group(3))
        custom_id = int(spell["id"])
        name = str(spell.get("name") or "")
        if not name:
            # The catalog stores an already-Lua-escaped name. It is still safer
            # to retain that exact payload than to create a nameless card.
            escaped_name = match.group(5)
        else:
            escaped_name = lua_quote(name)

        dependency_fields = match.group(6) or ""

        output.append(
            '  { id = %d, rarity = %d, classSet = %d, minLevel = 1, '
            'name = "%s", %sranks = { { id = %d, level = 1 } } },'
            % (
                custom_id,
                rarity,
                class_set,
                escaped_name,
                dependency_fields,
                custom_id,
            )
        )

    missing = [root for root, count in found.items() if count == 0]
    duplicate = [root for root, count in found.items() if count != 1 and count > 0]
    if missing:
        raise ReplaceError(
            "selected normalized source root(s) were not cards in the generated catalog: "
            + ", ".join(str(root) for root in sorted(missing))
        )
    if duplicate:
        raise ReplaceError(
            "native source root(s) appeared more than once in catalog: "
            + ", ".join(str(root) for root in sorted(duplicate))
        )

    # Parse the transformed lines again rather than assuming replacement worked.
    final_ids: list[int] = []
    for line in output:
        match = CATALOG_LINE_RE.match(line)
        if match:
            final_ids.append(int(match.group(1)))
    leftover = sorted(native_roots & set(final_ids))
    missing_custom = sorted(custom_ids - set(final_ids))
    if leftover:
        raise ReplaceError(
            "native roots survived normalized catalog replacement: "
            + ", ".join(str(root) for root in leftover)
        )
    if missing_custom:
        raise ReplaceError(
            "custom normalized cards are missing after replacement: "
            + ", ".join(str(spell_id) for spell_id in missing_custom)
        )
    if len(final_ids) != catalog_entries:
        raise ReplaceError(
            f"catalog cardinality changed unexpectedly: {catalog_entries} -> {len(final_ids)}"
        )
    if len(final_ids) != len(set(final_ids)):
        raise ReplaceError("catalog contains duplicate card IDs after normalized replacement")

    path.write_text("\n".join(output) + "\n", encoding="utf-8")
    return catalog_entries, len(replacements)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--resolved", required=True, type=Path)
    args = parser.parse_args()

    try:
        replacements = load_replacements(args.resolved.expanduser().resolve())
        count, replaced = replace_catalog(args.catalog.expanduser().resolve(), replacements)
    except ReplaceError as exc:
        raise SystemExit(f"Normalized SpellDraft catalog replacement aborted: {exc}") from exc

    print(f"Normalized SpellDraft cards applied: {replaced} native roots -> 201xxx")
    print(f"  total catalog roots preserved: {count}")
    print("  validation: every selected native root is absent; every custom replacement is present")
    print(f"  output: {args.catalog.expanduser().resolve()}")


if __name__ == "__main__":
    main()

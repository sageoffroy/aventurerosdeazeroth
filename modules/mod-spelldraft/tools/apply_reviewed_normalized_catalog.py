#!/usr/bin/env python3
"""Prune reviewed false roots, then apply strict normalized replacements."""

from __future__ import annotations

import argparse
from pathlib import Path

from apply_normalized_catalog import CATALOG_LINE_RE, ReplaceError, load_replacements, replace_catalog
from reviewed_spell_exclusions import ExclusionError, load_excluded_spell_ids


class ReviewedReplaceError(RuntimeError):
    pass


def prune_catalog(path: Path, excluded: set[int]) -> int:
    if not path.is_file():
        raise ReviewedReplaceError(f"SpellDraft runtime catalog not found: {path}")

    lines = path.read_text(encoding="utf-8").splitlines()
    output: list[str] = []
    removed: set[int] = set()
    for line in lines:
        match = CATALOG_LINE_RE.match(line)
        if match and int(match.group(1)) in excluded:
            removed.add(int(match.group(1)))
            continue
        output.append(line)

    path.write_text("\n".join(output) + "\n", encoding="utf-8")

    final_ids = {
        int(match.group(1))
        for line in output
        if (match := CATALOG_LINE_RE.match(line))
    }
    leftover = sorted(excluded & final_ids)
    if leftover:
        raise ReviewedReplaceError(
            "reviewed excluded roots survived catalog pruning: "
            + ", ".join(str(value) for value in leftover)
        )
    return len(removed)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--resolved", required=True, type=Path)
    args = parser.parse_args()

    catalog = args.catalog.expanduser().resolve()
    resolved = args.resolved.expanduser().resolve()
    try:
        excluded = load_excluded_spell_ids()
        removed = prune_catalog(catalog, excluded)
        replacements = load_replacements(resolved)
        overlap = sorted(excluded & set(replacements))
        if overlap:
            raise ReviewedReplaceError(
                "reviewed exclusions were still selected for normalization: "
                + ", ".join(str(value) for value in overlap)
            )
        count, replaced = replace_catalog(catalog, replacements)
    except (ExclusionError, ReplaceError, ReviewedReplaceError) as exc:
        raise SystemExit(f"Reviewed normalized catalog application aborted: {exc}") from exc

    print(f"Reviewed false roots removed from draft catalog: {removed}")
    print(f"Normalized SpellDraft cards applied: {replaced} native roots -> 201xxx")
    print(f"  final catalog roots after pruning/replacement: {count}")
    print("  validation: reviewed internals absent; selected originals absent; custom replacements present")
    print(f"  output: {catalog}")


if __name__ == "__main__":
    main()

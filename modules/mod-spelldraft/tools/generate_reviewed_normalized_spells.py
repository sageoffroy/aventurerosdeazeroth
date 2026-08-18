#!/usr/bin/env python3
"""Run the normalized-spell generator after removing reviewed false roots.

The production catalog intentionally stays broad. This wrapper narrows the
initial <=20 normalization cohort by removing manually reviewed talent proc,
form-granted and duplicate helper rows before custom IDs are assigned.
"""

from __future__ import annotations

import generate_normalized_spells as generator
from reviewed_spell_exclusions import ExclusionError, load_excluded_spell_ids


def main() -> None:
    try:
        excluded = load_excluded_spell_ids()
    except ExclusionError as exc:
        raise SystemExit(f"Reviewed normalized-spell generation aborted: {exc}") from exc

    original_build_catalog = generator.build_catalog

    def reviewed_build_catalog(*args, **kwargs):
        catalog = original_build_catalog(*args, **kwargs)
        return [entry for entry in catalog if int(entry["id"]) not in excluded]

    generator.build_catalog = reviewed_build_catalog
    generator.main()


if __name__ == "__main__":
    main()

#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
DM="$ROOT/modules/mod-dungeon-master"
PATCH_DIR="$ROOT/patches/mod-dungeon-master"

if [[ ! -d "$DM/.git" && ! -f "$DM/.git" ]]; then
  echo "ERROR: falta el submodulo modules/mod-dungeon-master" >&2
  exit 1
fi

shopt -s nullglob
patches=("$PATCH_DIR"/*.patch)

if (( ${#patches[@]} == 0 )); then
  echo "No hay patches de Dungeon Master para aplicar."
  exit 0
fi

for patch in "${patches[@]}"; do
  name="$(basename "$patch")"

  if git -C "$DM" apply --check "$patch" >/dev/null 2>&1; then
    git -C "$DM" apply "$patch"
    echo "APLICADO: $name"
    continue
  fi

  if git -C "$DM" apply --reverse --check "$patch" >/dev/null 2>&1; then
    echo "OK: $name ya estaba aplicado"
    continue
  fi

  echo "ERROR: $name no aplica limpio sobre el estado actual del submodulo." >&2
  echo "No hice cambios parciales sobre ese patch." >&2
  exit 1
done

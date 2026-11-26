#!/usr/bin/env bash
# Carga datos de demostración llamando al comando `novvus seed` de cada módulo.
set -euo pipefail

for dir in /modules/*; do
  [ -f "$dir/module.py" ] || continue
  echo "== sembrando $(basename "$dir")"
  (cd "$dir" && novvus seed --org "$NOVVUS_ORG_ID")
done

echo "Datos de demostración cargados."

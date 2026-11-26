#!/usr/bin/env bash
# Comprobación rápida del entorno académico. Se ejecuta en el host con WSL:
#   bash academico/verificar.sh
set -euo pipefail

BASE="${BASE_URL:-http://localhost:8080}"

echo "== health de la pasarela"
curl -fsS "$BASE/health"; echo

echo "== recursos por módulo"
curl -fsS "$BASE/modulos" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); [print(k, r) for k,v in d.items() for r in v['recursos']]" \
  | while read -r modulo recurso; do
      total="$(curl -fsS "$BASE/api/$modulo/$recurso?limit=1&with_total=true" \
        | python3 -c 'import json,sys; print(json.load(sys.stdin).get("total"))')"
      printf '%-15s %-22s %s registros\n' "$modulo" "$recurso" "$total"
    done

echo "== esquemas en PostgreSQL"
docker compose exec -T postgres psql -U novvus -d novvus -c \
  "SELECT table_schema, count(*) AS tablas FROM information_schema.tables WHERE table_schema LIKE 'mod_%' GROUP BY 1 ORDER BY 1;"

echo "OK"

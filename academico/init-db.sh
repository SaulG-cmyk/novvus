#!/usr/bin/env bash
# Crea un esquema por módulo y aplica sus migraciones SQL en orden.
# Es idempotente: registra cada archivo aplicado en public.academico_applied.
# Los archivos de datos (sin prefijo numérico) se aplican al final, porque
# algunos insertan en esquemas de otros módulos.
set -euo pipefail

export PGPASSWORD="$POSTGRES_PASSWORD"
db() { psql -v ON_ERROR_STOP=1 -h postgres -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"; }

db -c "CREATE TABLE IF NOT EXISTS public.academico_applied (
    file TEXT NOT NULL,
    PRIMARY KEY (file)
);"

apply_file() {
  local dir="$1" file="$2"
  local id version key applied
  id="$(basename "$dir")"
  version="$(basename "$file")"
  key="$id/$version"

  applied="$(db -tAc "SELECT 1 FROM public.academico_applied WHERE file='$key'" | tr -d '[:space:]')"
  if [ "$applied" = "1" ]; then
    echo "   $version ya aplicada"
    return
  fi
  echo "   aplicando $version"
  { echo "SET search_path TO mod_$id;"; cat "$file"; } | db
  db -c "INSERT INTO public.academico_applied (file) VALUES ('$key');"
}

# 1. Crear todos los esquemas antes de ejecutar nada que pueda referirse a ellos.
for dir in /modules/*; do
  [ -d "$dir/migrations" ] || continue
  id="$(basename "$dir")"
  echo "== preparando mod_$id"
  db -c "CREATE SCHEMA IF NOT EXISTS mod_$id;"
  # La plataforma crea un rol propietario por módulo; los datos demo lo referencian.
  db -c "DO \$\$ BEGIN CREATE ROLE novvus_mod_${id}_owner NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END \$\$;"
done

# 2. Migraciones numeradas, en orden.
for dir in /modules/*; do
  [ -d "$dir/migrations" ] || continue
  echo "== migraciones de $(basename "$dir")"
  for file in "$dir"/migrations/[0-9][0-9][0-9][0-9]_*.sql; do
    [ -f "$file" ] || continue
    apply_file "$dir" "$file"
  done
done

# 3. Migraciones añadidas por el entorno académico (no existen en el paquete de la empresa).
for dir in /extra/*; do
  [ -d "$dir" ] || continue
  echo "== migraciones académicas de $(basename "$dir")"
  for file in "$dir"/*.sql; do
    [ -f "$file" ] || continue
    apply_file "$dir" "$file"
  done
done

# 4. Datos de demostración (pueden tocar varios esquemas).
for dir in /modules/*; do
  [ -d "$dir/migrations" ] || continue
  for file in "$dir"/migrations/*.sql; do
    [ -f "$file" ] || continue
    case "$(basename "$file")" in
      [0-9][0-9][0-9][0-9]_*) continue ;;
    esac
    echo "== datos de $(basename "$dir")"
    apply_file "$dir" "$file"
  done
done

# 5. Correcciones de datos de demostración (después de cargar los datos).
for dir in /fixes/*; do
  [ -d "$dir" ] || continue
  for file in "$dir"/*.sql; do
    [ -f "$file" ] || continue
    apply_file "$dir" "$file"
  done
done

echo "Base de datos lista."

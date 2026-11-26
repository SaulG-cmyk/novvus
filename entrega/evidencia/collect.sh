#!/usr/bin/env bash
# Recolecta evidencia del estado real de Docker para el paquete de entrega.
set -u

OUT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/docker-evidencia.txt
mkdir -p "$(dirname "$OUT")"
exec > "$OUT" 2>&1

MODIMG=""
for cand in novvus-runtime:local novvus-crm:0.2.20; do
  if docker image inspect "$cand" >/dev/null 2>&1; then MODIMG=$cand; break; fi
done

echo "# Evidencia de imágenes y contenedores"
echo
echo "Fecha: $(date -Is)"
echo "Host: $(uname -srm)"
echo "Distribución: $(. /etc/os-release && echo "$PRETTY_NAME")"
echo "Engine: $(docker version --format '{{.Server.Version}} · API {{.Server.APIVersion}} · {{.Server.Os}}/{{.Server.Arch}}')"
echo "Compose: $(docker compose version --short 2>/dev/null)"
echo

echo "## 1. Imágenes locales"
echo
docker images --digests --format 'table {{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.CreatedSince}}\t{{.Size}}\t{{.Digest}}'
echo

echo "## 2. Contenedores en ejecución"
echo
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
echo

echo "## 3. Salud declarada por cada contenedor"
echo
printf '%-30s %-26s %s\n' CONTENEDOR IMAGEN SALUD
for c in $(docker ps --format '{{.Names}}'); do
  img=$(docker inspect -f '{{.Config.Image}}' "$c")
  health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}sin healthcheck{{end}}' "$c")
  printf '%-30s %-26s %s\n' "$c" "$img" "$health"
done
echo

echo "## 4. Identidad de las imágenes del núcleo (digests)"
echo
for ref in ghcr.io/novvus/core:0.3.70 ghcr.io/novvus/web:0.3.70 ghcr.io/novvus/bootstrap:0.3.70 postgres:16-alpine; do
  echo "$ref"
  docker image inspect "$ref" --format '  ID:      {{.Id}}
  Creada:  {{.Created}}
  Digests: {{range .RepoDigests}}{{.}} {{end}}'
  echo
done

echo "## 5. Imagen local de los módulos"
echo
if [[ -n "$MODIMG" ]]; then
  echo "Imagen: $MODIMG"
  docker image inspect "$MODIMG" --format 'ID: {{.Id}}
Creada: {{.Created}}
Etiquetas: {{range .RepoTags}}{{.}} {{end}}
Arquitectura: {{.Os}}/{{.Architecture}}
Capas: {{len .RootFS.Layers}}'
  echo
  echo "Capas superiores (construcción local):"
  docker history --format '  {{.CreatedSince}}\t{{.Size}}\t{{.CreatedBy}}' "$MODIMG" | head -5
else
  echo "No hay imagen local de módulos (novvus-runtime:local o novvus-crm:0.2.20)."
fi
echo

echo "## 6. Composición declarada por los contenedores"
echo
for c in $(docker ps --format '{{.Names}}'); do
  files=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' "$c")
  svc=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.service"}}' "$c")
  project=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "$c")
  printf '%-30s %-24s %s\n' "$c" "$project/$svc" "$files"
done

# Novvus — entorno académico (Docker)

Versión autocontenida del proyecto para la materia de Docker. **No necesita acceso a
`ghcr.io/novvus`**: las imágenes que se usan son oficiales y públicas (`python`,
`postgres`, `nginx`) y todo el código de los módulos se construye desde este repositorio.

El paquete de la empresa (`LEEME.md`, `entrega/`) queda intacto: allí el núcleo es una imagen
comercial. Aquí se sustituye ese núcleo por una pasarela mínima escrita en este repo.

## Requisitos

- Docker Engine 24 o superior con Compose v2 (`docker compose version`).
- 4 GB de RAM libres y 3 GB de disco.
- No hace falta Python instalado en el host.

## Arranque

Desde la raíz del repositorio:

```bash
docker compose up --build
```

Espera a que los seis módulos estén `healthy`. Después abre:

- Interfaz web: <http://localhost:8081>
- API de la pasarela: <http://localhost:8080/modulos>

Para apagar y borrar los datos:

```bash
docker compose down -v
```

## Qué se levanta

| Servicio | Imagen | Función |
|---|---|---|
| `postgres` | `postgres:16-alpine` | Base de datos, volumen `pgdata`, healthcheck `pg_isready`. |
| `db-init` | `postgres:16-alpine` | Crea `mod_<módulo>` y aplica las migraciones SQL. Se ejecuta una vez; es idempotente. |
| `seed` | construida | Ejecuta `novvus seed` en los seis módulos. Se ejecuta una vez. |
| `auditorias`, `automatizacion`, `facturacion`, `inventario`, `logistica`, `reclutamiento` | construidas desde `Dockerfile.modulo` | Cada módulo es un contenedor FastAPI independiente en el puerto interno 8100. |
| `gateway` | construida | Firma las peticiones con HMAC y las enruta a `/api/<módulo>/…`. |
| `web` | `nginx:alpine` | Interfaz estática y proxy inverso de `/api/`. Publica el puerto 8081. |

Todos los servicios comparten la red `backend`. La base de datos no publica puertos: solo es
accesible desde la red. Los secretos y la organización de demostración están en
`academico/.env.demo`; **son valores de clase, no de producción**.

## Verificación

```bash
docker compose ps
curl -fsS http://localhost:8080/health
curl -fsS http://localhost:8080/modulos
curl -fsS 'http://localhost:8080/api/auditorias/audits?limit=3&with_total=true'
```

En la interfaz web, pulsar cualquier botón `GET <recurso>` muestra la respuesta real de la API,
incluido el total de registros. La comprobación completa se automatiza con:

```bash
bash academico/verificar.sh
```

Recorre los 24 recursos, consulta el total de registros de cada uno y lista los seis esquemas.

Para comprobar el aislamiento por esquema:

```bash
docker compose exec postgres psql -U novvus -d novvus -c '\dn'
docker compose exec postgres psql -U novvus -d novvus -c \
  "SELECT table_schema, count(*) FROM information_schema.tables WHERE table_schema LIKE 'mod_%' GROUP BY 1 ORDER BY 1;"
```

## Comandos útiles

```bash
docker compose logs -f gateway
docker compose logs -f facturacion
docker compose up --build --force-recreate
docker compose restart
docker compose down          # conserva pgdata
docker compose down -v       # borra también la base
```

## Cómo está construido

- `Dockerfile.modulo` recibe `MODULE` como argumento de build, instala el SDK desde `dev/sdk` y
  copia solo `dev/modules/<MODULE>`. No hay secretos ni código de la empresa dentro de la imagen.
- `academico/init-db.sh` aplica `dev/modules/*/migrations/*.sql` y guarda cada versión aplicada en
  `public.academico_applied`, para que reiniciar no duplique tablas.
- `academico/gateway.py` reproduce la firma interna (`x-novvus-signature`) que el SDK verifica en
  `dev/sdk/src/novvus_sdk/security.py`. Es la pieza que en producción aporta el kernel comercial.
- `.dockerignore` mantiene el contexto de build pequeño: excluye PDF, capturas, ZIP y `venv`.

## Límites deliberados

Esta capa es un ejercicio de Docker, no un clon del núcleo comercial:

- No hay usuarios, inicio de sesión ni permisos por rol: la pasarela usa una organización fija y
  concede `*` en la demostración.
- No hay eventos entre módulos ni modo agente.
- No se incluyen los módulos base `crm` y `projects`; sí los seis módulos propios del proyecto.
- El módulo `automatizacion` declara `Notification` pero no trae su migración: se añade una tabla
  mínima en `academico/migrations-extra/`. Los datos demo de `inventario` insertan `in` donde el
  modelo espera `in_`: se normaliza en `academico/data-fixes/`. Ninguno de estos archivos toca el
  código entregado a la empresa.
- La semilla original de logística crea almacén y transportista, pero no envíos; por eso algunos
  recursos muestran 0 registros.

Para la entrega a la empresa se mantiene `LEEME.md` y `entrega/`.

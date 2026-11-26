# novvus-sdk

La capa declarativa con la que se construyen todos los módulos de NOVVUS CORE.
Un módulo declara **modelos**, **permisos**, **eventos** y **endpoints**; el
SDK genera la API REST, aplica el aislamiento multi-tenant (RLS) y habla con
el kernel. Contrato completo: [docs/MODULE_CONTRACT.md](../docs/MODULE_CONTRACT.md).

## Instalación (desarrollo)

```bash
cd sdk
python -m venv .venv && .venv/Scripts/activate   # o source .venv/bin/activate
pip install -e ".[dev]"
```

## Escribe tu primer módulo en 10 minutos

### 1. Scaffolding (1 min)

```bash
novvus new-module inventario
cd inventario
```

Esto crea `novvus.toml` (manifiesto), `module.py` (modelo de ejemplo con CRUD
automático), `migrations/0001_init.sql` (DDL + políticas RLS generadas) y un
test de humo.

### 2. Declara tus modelos (3 min)

`module.py`:

```python
from sqlalchemy.orm import Mapped, mapped_column
from novvus_sdk import NovvusModel, NovvusModule

module = NovvusModule()

@module.model
class Product(NovvusModel):
    name: Mapped[str]
    sku: Mapped[str]
    stock: Mapped[int] = mapped_column(default=0)

app = module.create_app()
```

Cada modelo recibe automáticamente `id` (UUIDv7), `org_id` (tenant), 
`created_at`, `updated_at` y soft delete (`deleted_at`), su tabla con RLS, y
un CRUD completo bajo `/api/inventario/products`:

- `GET /api/inventario/products?limit=&cursor=&order_by=-created_at&sku=X` —
  paginación por cursor, filtros por igualdad y ordenamiento.
- `POST`, `GET /{id}`, `PATCH /{id}`, `DELETE /{id}` (soft delete).
- Permisos por convención: `inventario.products.read` / `.write`
  (personalizables o desactivables con `__novvus_api__`).

¿Endpoint custom? Usa el router del módulo con `@requires`:

```python
from novvus_sdk import requires

@module.router.get("/reports/low-stock")
@requires("inventario.products.read")
async def low_stock() -> dict: ...
```

### 3. Genera la migración (1 min)

```bash
novvus makemigration -m init      # 0001: DDL completo + RLS
# cambios posteriores: diff automático vía Alembic contra tu BD de desarrollo
NOVVUS_DATABASE_URL=... novvus makemigration -m add_price
```

### 4. Despliega en el kernel (2 min)

```bash
# registra manifiesto + migraciones, instala (crea esquema mod_inventario,
# aplica migraciones, registra permisos) y habilita:
novvus deploy --kernel http://localhost:8000 --token <JWT-admin>
# imprime el NOVVUS_SERVICE_TOKEN del módulo (una sola vez)
```

### 5. Corre el módulo (1 min)

```bash
export NOVVUS_SERVICE_TOKEN=nvk_...   # del paso anterior
novvus run                            # handshake con el kernel + FastAPI
```

El módulo queda accesible **solo** a través del gateway:
`http://localhost:8000/api/inventario/products`.

### 6. Datos demo (1 min)

```python
@module.seed
async def seed(session, org_id):
    session.add_all([Product(org_id=org_id, name="Café", sku="CAF-01")])
```

```bash
NOVVUS_DATABASE_URL=... novvus seed --org <uuid-de-tu-organización>
```

## Eventos

```python
# novvus.toml:  [events] emits = ["inventario.product.out_of_stock"]
#               listens = ["crm.opportunity.won"]

@module.on("crm.opportunity.won")
async def on_won(event, session):
    ...  # idempotente: el SDK descarta entregas duplicadas por event.id

await module.emit("inventario.product.out_of_stock", {"product_id": str(p.id)})
```

## Garantías que el SDK te da gratis

- **Tenant siempre**: cada petición corre en una transacción con
  `SET LOCAL app.org_id`; RLS hace imposible ver datos de otra organización.
- **org_id inyectado jamás**: los payloads con `org_id` se rechazan (422).
- **Solo el kernel te habla**: toda petición debe traer los headers internos
  firmados (HMAC) del gateway; lo demás es 401.
- **Idempotencia de eventos**: `@module.on` procesa cada evento una sola vez.

## Tests

```bash
docker compose up -d --wait   # en la raíz del monorepo
cd sdk
pytest                        # unitarios + integración con Postgres real
mypy && ruff check .
```

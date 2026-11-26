# Módulo CRM

Gestión de relaciones con clientes para NOVVUS CORE, construido **exclusivamente
con novvus-sdk**: empresas, contactos, leads, pipelines configurables,
oportunidades, actividades, etiquetas y reportes.

## Modelos y API

Cada modelo obtiene su tabla con RLS y su CRUD bajo `/api/crm/...`:
`companies`, `contacts`, `leads`, `pipelines`, `stages`, `opportunities`,
`activities`, `tags` (las tablas M2M de etiquetas no exponen CRUD directo).

### Endpoints de negocio

| Endpoint | Regla |
|----------|-------|
| `POST /api/crm/leads` | Crea el lead y emite `crm.lead.created`. |
| `POST /api/crm/leads/{id}/convert` | Crea la Opportunity en la primera etapa del pipeline (default o indicado), enlaza contacto/empresa y marca el lead `converted` con `converted_opportunity_id` (auditable, jamás se borra). Emite `crm.lead.converted`. |
| `POST /api/crm/opportunities/{id}/move` | Cambia de etapa (misma pipeline). Etapa won/lost registra `closed_at` + `is_won` y emite `crm.opportunity.won`/`lost`; siempre emite `crm.opportunity.stage_changed`. |
| `POST /api/crm/activities/{id}/complete` | Marca `done` + `completed_at`, emite `crm.activity.completed` (idempotente). |
| `GET/POST/DELETE /api/crm/{contacts\|opportunities}/{id}/tags[/{tag_id}]` | Etiquetado M2M. |
| `GET /api/crm/reports/pipeline` | Conteo y monto por etapa + totales open/won/lost. |
| `GET /api/crm/reports/conversion?start=&end=` | Leads, convertidos, perdidos y tasa del periodo. |

## Roles de ejemplo (mapeo de permisos)

| Permiso | Ventas | Gerente de ventas |
|---------|:------:|:-----------------:|
| `crm.companies.*`, `crm.contacts.*`, `crm.leads.*`, `crm.opportunities.*`, `crm.activities.*`, `crm.tags.*` | ✔ | ✔ |
| `crm.pipelines.read` | ✔ | ✔ |
| `crm.pipelines.manage` | ✖ | ✔ |
| `crm.reports.read` | ✖ | ✔ |

Los roles se crean por organización vía kernel (ver `requests.http`, pasos 1-2).

## Despliegue

```bash
cd modules/crm
novvus deploy --kernel http://127.0.0.1:8000 --token <JWT-admin>   # register+install+enable
NOVVUS_SERVICE_TOKEN=nvk_... novvus run --port 8110                # runtime + handshake
NOVVUS_DATABASE_URL=... novvus seed --org <uuid>                   # datos demo en español
```

El seed crea 20 empresas, 50 contactos, el "Pipeline de ventas" con 6 etapas
(Nuevo → Calificado → Propuesta → Negociación → Ganado/Perdido), 25
oportunidades repartidas, 15 leads, actividades y etiquetas.

## Tests

```bash
docker compose up -d --wait          # raíz del monorepo
cd modules/crm
../../sdk/.venv/Scripts/python -m pytest
```

Cubren: conversión de lead auditable, won/lost con `closed_at`, permisos por
rol (Ventas vs Gerente), aislamiento RLS entre organizaciones, reportes y seed.

## Flujo demostrable

`requests.http` contiene la colección completa: login → roles → crear lead →
convertir → mover por etapas → ganar → ver reporte.

## Cotizaciones (0.3.0)

Los conceptos entran por las acciones de la cotización (`Agregar concepto`, `Editar concepto`, `Quitar concepto`);
la auto-API de `quote_lines` es de solo lectura para que los totales nunca queden desfasados. Fórmulas
(`quotes.py`), con redondeo a centavos (half-up) por línea:

- `line_subtotal = round(cantidad × precio_unitario × (1 − descuento_línea / 100), 2)`
- `descontado = line_subtotal × (1 − descuento_global / 100)`
- `line_tax = round(descontado × tasa / 100, 2)` (la tasa se copia a la línea al agregarla: un cambio posterior del
  catálogo no reescribe cotizaciones emitidas)
- `line_total = round(descontado, 2) + line_tax`
- `subtotal = Σ line_subtotal`; `discount_total = Σ (bruto − line_subtotal) + round(subtotal × descuento_global / 100, 2)`;
  `tax_total = Σ line_tax`; `total = Σ line_total`.

Ciclo: `draft` → `send` → `sent` → `accept`/`reject` → `accepted`/`rejected`; el cron diario `crm.quotes_expire` pasa
a `expired` las enviadas con `valid_until` vencida. `Nueva versión` copia una cotización decidida o enviada como
borrador `version + 1` enlazado por `previous_id`. Los impuestos son del catálogo de la organización (`tax_rates`):
no se asume ninguna regla fiscal nacional.

## Centro de control comercial y reportes (0.3.0)

`views.dashboard` de oportunidades (`GET /api/crm/reports/dashboard`, panel de Inicio) y los reportes
`GET /api/crm/reports/{sales,forecast,activities,pipelines}` (más los heredados `pipeline` y `conversion`) salen de las
filas reales de la organización bajo RLS. Fórmulas (`reports.py`):

- Abiertas: `is_won IS NULL`. Valor del pipeline: Σ `amount` de las abiertas, por moneda.
- Probabilidad efectiva: la propia de la oportunidad si está fijada; si no, la de su etapa. Pronóstico ponderado:
  Σ `amount × probabilidad / 100` sobre las abiertas (es una ponderación configurable, no una predicción estadística).
- Ganadas / perdidas: cerradas por `is_won` dentro del periodo (`closed_at`; por defecto 90 días en el panel).
  Tasa de conversión: `ganadas / (ganadas + perdidas)`. Duración promedio: media de `closed_at − created_at`.
- Próximas a cerrar: abiertas con `expected_close_date` en los siguientes 30 días. Estancadas: abiertas sin actividad
  (`last_activity_at`, o `updated_at` si nunca hubo) en más de `crm.rotting_days` días (configuración, 14 por defecto).
- Actividades vencidas: pendientes con `due_date` anterior a ahora.
- Filtros de los reportes: `start`/`end` (periodo inclusivo), `owner_user_id`, `pipeline_id`.

## Integración con Proyectos (0.3.0)

`integration.py`: el CRM no ejecuta el motor de proyectos; usa la API pública de Proyectos con los permisos de servicio
del manifiesto. «Crear proyecto» (solo oportunidades ganadas) llama a `POST /api/projects/projects/actions/register`
con código, nombre, plantilla, fechas, presupuesto (valor de la oportunidad), cliente, contacto y oportunidad;
Proyectos valida el código único (idempotencia: repetir con el mismo código responde 409) y guarda el vínculo en
`project_links` (varios proyectos por oportunidad). «Ver proyectos» en oportunidades y empresas consulta
`GET /api/projects/reports/portfolio` y `project_links`. La creación automática al ganar la decide Proyectos
(`projects.create_on_won`, apagada por defecto). Sin Proyectos instalado, las acciones responden 503 con un mensaje
claro y el resto del CRM no cambia.

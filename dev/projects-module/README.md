# Módulo Proyectos

Segundo módulo de negocio de NOVVUS CORE. Existe para **demostrar que NOVVUS
es una plataforma y no un CRM con pasos extra**: se construye con el mismo SDK,
depende del CRM y colabora con él solo a través de contratos públicos.

## Interoperabilidad

- **Depende del CRM** (`[dependencies] modules = ["crm>=0.1"]`): el kernel no
  deja habilitar Projects si el CRM no está habilitado.
- **Escucha `crm.opportunity.won`**: al ganar una oportunidad, crea
  automáticamente un proyecto vinculado (con tareas iniciales) y emite
  `projects.project.created`.
- **Referencia al CRM solo por su API pública**: resuelve el nombre del
  contacto con `module.call("GET", "/api/crm/contacts/{id}")` a través del
  gateway, usando su token de servicio y el permiso declarado en
  `service_permissions = ["crm.contacts.read"]`. **Nunca** toca las tablas
  del CRM.

## Robustez (Fase 5)

- **Estado degradado explícito**: si el CRM se deshabilita, `GET /health`
  reporta `status: "degraded"` con la dependencia caída, pero Projects sigue
  sirviendo; la resolución de contacto degrada a vacío sin romperse.
- **Reproceso exactamente una vez**: si Projects estuvo caído, al volver
  procesa las entregas pendientes del bus. La idempotencia del SDK
  (`_processed_events`) más una restricción `UNIQUE(org_id, opportunity_id)`
  garantizan **un solo proyecto por oportunidad**, aun con reintentos o
  re-emisiones.

## Modelos

- `Project`: nombre, descripción, estado, referencias por id a la oportunidad/
  contacto/empresa del CRM y `contact_name` denormalizado.
- `Task`: título, estado (todo/doing/done), asignado, vencimiento.

## Correr

```bash
cd modules/projects
novvus deploy --kernel http://127.0.0.1:8000 --token <JWT>   # requiere el CRM habilitado
NOVVUS_SERVICE_TOKEN=nvk_... novvus run --port 8120
```

## Tests

```bash
docker compose up -d --wait
cd modules/projects && ../../sdk/.venv/Scripts/python -m pytest
```

Cubren: creación exactamente-una-vez desde el evento (entrega duplicada +
re-emisión), estado degradado explícito y aislamiento RLS entre organizaciones.

## Reglas, avance y salud (0.3.0)

`business.py` concentra el ciclo de vida (borrador → activo ⇄ pausado → concluido/cancelado → archivado; eliminación
solo de borradores, cancelados o archivados), la creación desde plantilla (instancias nuevas e independientes de fases,
procesos con etapas, actividades, dependencias e hitos), las transiciones de actividades (por hacer → en curso → en
revisión → hecha; bloqueo con causa; las predecesoras se comprueban por tipo: fin a inicio y inicio a inicio para
empezar, fin a fin e inicio a fin para terminar), las dependencias (se rechazan los ciclos), hitos, entregables con
aprobación (permiso `projects.approvals.decide`) y riesgos (puntuación = probabilidad × impacto con baja 1, media 2,
alta 3). Tras cada cambio se recalcula el proyecto.

`progress.py` (motor puro):

- Avance de una actividad: 100 si está hecha; con subtareas, `Σ(peso × avance) / Σ(peso)` de las subtareas no
  canceladas (su propio avance se ignora: nada se cuenta dos veces).
- Avance de una fase: media ponderada de sus actividades hoja no canceladas.
- Estrategias del proyecto: `tasks` = hojas hechas / hojas no canceladas; `weighted` = `Σ(peso de fase × avance de
  fase) / Σ(pesos)` sobre las fases con hojas (las hojas sin fase forman un grupo de peso 1); `milestones` = hitos
  alcanzados / hitos no cancelados. Pesos ≤ 0 no aportan al denominador.
- Avance planificado: proporción lineal entre inicio y conclusión estimada (línea base) cuando ambas fechas existen.
- Salud (independiente del avance y del estado): `blocked` si hay actividades abiertas bloqueadas; `delayed` si el
  proyecto, una actividad abierta o un hito pendiente pasó su fecha; `at_risk` si hay un riesgo materializado o abierto
  con puntuación ≥ 6; si no, `on_track`. Proyectos en borrador, concluidos, cancelados o archivados: `on_track`.

## Procesos y etapas (0.3.0)

`processes.py`: un proceso es un flujo con etapas ordenadas dentro de un proyecto (distinto de una fase, que agrupa
trabajo). «Iniciar» activa la primera etapa; «Avanzar etapa» cierra la actual solo si está aprobada (cuando
`requires_approval`), tiene evidencia (nota obligatoria cuando `required_evidence` o `exit_conditions` no están
vacías) y no tiene actividades abiertas; «Omitir etapa» exige el permiso `projects.approvals.decide` y un motivo, y se
registra como transición forzada; «Solicitar aprobación» crea una aprobación sobre la etapa actual. Todo movimiento
queda en `process_transitions`. El inspector (`views.process`, `GET /api/projects/processes/{id}/process`) expone los
tres pasos del proceso (definido, en ejecución, terminado) con paneles de etapas, etapa actual (condiciones,
evidencias, aprobación, actividades abiertas, qué falta para avanzar) e historial; un plazo vencido marca atención.

## Portafolio y reportes (0.3.0)

`portfolio.py`: `views.dashboard` de proyectos (`GET /api/projects/reports/dashboard`, panel de Inicio) y los reportes
`GET /api/projects/reports/portfolio` (filtros `status`, `kind`, `owner_user_id`, `company_id`; avance, línea base,
desviación, actividades abiertas y vencidas por proyecto) y `GET /api/projects/reports/workload` (carga por responsable,
filtro `project_id`). Fórmulas: activos/pausados/concluidos por estado; retrasados, en riesgo y bloqueados por salud de
los proyectos en curso; avance global = media del avance de los proyectos en curso, ponderada por presupuesto cuando
todos lo tienen; hitos próximos = pendientes de proyectos en curso que vencen en 30 días; actividades vencidas = abiertas
con fecha límite pasada.

## Integración (0.3.0)

- **CRM → Proyectos**: el CRM pide el proyecto con `POST /api/projects/projects/actions/register` (código único,
  plantilla opcional, `company_id`/`contact_id`/`opportunity_id` del CRM y sus nombres para mostrar). Proyectos crea el
  proyecto y la fila de `project_links` (varios proyectos por oportunidad). Con `projects.create_on_won` activo, el
  evento `crm.opportunity.won` crea además un proyecto automático (uno por oportunidad). El CRM consulta el avance con
  `GET /api/projects/reports/portfolio` y `GET /api/projects/project_links`.
- **Módulos especializados (punto de extensión futuro, p. ej. Operaciones)**: una actividad puede referenciar un
  trabajo ejecutado por otro módulo con `external_module`, `external_model` y `external_id` (solo identificadores;
  nunca tablas ajenas). Contrato previsto, sin implementar todavía: el módulo especializado emite eventos
  `<módulo>.<modelo>.updated` con `{id, status, progress, due_date, deliverables}` y Proyectos los escucha para
  reflejar responsable, estado, fechas, avance y entregables de la actividad vinculada; Proyectos nunca escribe en el
  módulo especializado. Requiere declarar el evento en `[events] listens` cuando exista.

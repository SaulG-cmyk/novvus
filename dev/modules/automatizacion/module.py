"""Automatización — módulo NOVVUS."""

from pathlib import Path
from uuid import UUID
from datetime import datetime, UTC
import json

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from novvus_sdk import NovvusModel, NovvusModule
from novvus_sdk.events import Event

from models import ALL_MODELS, Process, ProcessExecution, ProcessStep, ProcessLog, Notification

module = NovvusModule(Path(__file__).with_name("novvus.toml"))

for model in ALL_MODELS:
    module.model(model)

try:
    import business
    business.register(module)
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Catálogo conocido de eventos: etiqueta legible para el constructor visual
# y el "from" declarativo de cada proceso dentro del módulo.
# ---------------------------------------------------------------------------
EVENT_CATALOG: dict[str, str] = {
    "crm.quote.accepted": "Cotización aceptada (CRM)",
    "crm.opportunity.won": "Oportunidad ganada (CRM)",
    "crm.lead.created": "Nuevo prospecto (CRM)",
    "reclutamiento.candidate.hired": "Candidato contratado (Reclutamiento)",
    "logistica.shipment.delivered": "Envío entregado (Logística)",
    "auditorias.finding.created": "Hallazgo creado (Auditorías)",
    "projects.project.created": "Proyecto creado (Proyectos)",
}

# Catálogo de tipos de acción de pasos (paso desconocido -> se registra como informativo).
ACTION_CATALOG: dict[str, str] = {
    "send_email": "Enviar correo",
    "create_task": "Crear tarea",
    "create_record": "Crear registro",
    "get_record": "Obtener registro",
    "query": "Buscar registros",
    "webhook": "Llamada webhook",
    "notify": "Notificar responsable",
}

@module.on("crm.quote.accepted")
async def on_quote_accepted(event: Event, session: AsyncSession) -> None:
    await _handle_event(event, session, "Procesar cotización aceptada", f"Cotización {event.payload.get('quote_id')} aceptada. Total: {event.payload.get('total')} {event.payload.get('currency')}")

@module.on("crm.opportunity.won")
async def on_opportunity_won(event: Event, session: AsyncSession) -> None:
    await _handle_event(event, session, "Onboarding de oportunidad ganada", f"Oportunidad {event.payload.get('opportunity_id')} ganada. Contacto: {event.payload.get('contact_id')}")

@module.on("crm.lead.created")
async def on_lead_created(event: Event, session: AsyncSession) -> None:
    await _handle_event(event, session, "Seguimiento de nuevo lead", f"Lead {event.payload.get('lead_id')} creado desde {event.payload.get('source')}")

@module.on("reclutamiento.candidate.hired")
async def on_candidate_hired(event: Event, session: AsyncSession) -> None:
    await _handle_event(event, session, "Onboarding de candidato contratado", f"Candidato {event.payload.get('name')} contratado. Contacto: {event.payload.get('contact_id')}, Proyecto: {event.payload.get('project_id')}")

@module.on("logistica.shipment.delivered")
async def on_shipment_delivered(event: Event, session: AsyncSession) -> None:
    await _handle_event(event, session, "Confirmación de entrega", f"Envío {event.payload.get('reference')} entregado")

@module.on("auditorias.finding.created")
async def on_finding_created(event: Event, session: AsyncSession) -> None:
    await _handle_event(event, session, "Seguimiento de hallazgo", f"Hallazgo '{event.payload.get('title')}' creado. Severidad: {event.payload.get('severity')}")

@module.on("projects.project.created")
async def on_project_created(event: Event, session: AsyncSession) -> None:
    await _handle_event(event, session, "Notificación de nuevo proyecto", f"Proyecto {event.payload.get('project_id')} creado. Oportunidad: {event.payload.get('opportunity_id')}")

async def _handle_event(event: Event, session: AsyncSession, process_name: str, result_msg: str) -> None:
    process = await _ensure_process(event, session, process_name)
    execution = await _run_steps(
        event=event,
        session=session,
        process=process,
        result_msg=result_msg,
    )
    await module.emit("automatizacion.process.completed", {"process_id": str(process.id), "execution_id": str(execution.id)})


async def _ensure_process(event: Event, session: AsyncSession, process_name: str) -> Process:
    """El proceso se crea declarativamente si no existe: nombre + trigger por evento."""
    process = await session.scalar(
        select(Process).where(Process.name == process_name, Process.deleted_at.is_(None))
    )
    if process is None:
        process = Process(
            org_id=event.org_id,
            name=process_name,
            status="active",
            trigger_type="event",
            trigger_config=json.dumps({"event": event.event_type}),
        )
        session.add(process)
        await session.flush()
    return process


async def _run_steps(
    event: Event,
    session: AsyncSession,
    process: Process,
    result_msg: str,
) -> ProcessExecution:
    """Ejecuta cada paso activo del proceso y deja rastro en logs y en la ejecución."""
    started = datetime.now(tz=UTC)
    execution = ProcessExecution(
        org_id=event.org_id,
        process_id=process.id,
        process_name=process.name,
        status="completed",
        started_at=started,
        finished_at=started,
        result=result_msg,
        error="",
        triggered_by=None,
    )
    session.add(execution)
    await session.flush()

    steps = (
        await session.scalars(
            select(ProcessStep)
            .where(ProcessStep.process_id == process.id, ProcessStep.deleted_at.is_(None))
            .order_by(ProcessStep.position)
        )
    ).all()

    session.add(
        ProcessLog(
            org_id=event.org_id,
            execution_id=execution.id,
            process_name=process.name,
            level="info",
            message=f"Disparador {event.event_type} recibido",
            logged_at=started,
        )
    )
    for step in steps:
        if not step.is_active:
            session.add(
                ProcessLog(
                    org_id=event.org_id,
                    execution_id=execution.id,
                    process_name=process.name,
                    step_id=step.id,
                    level="debug",
                    message=f"{step.position}. {step.name} ({step.action_type}): omitido (inactivo)",
                    logged_at=started,
                )
            )
            continue
        label = ACTION_CATALOG.get(step.action_type, step.action_type)
        detail = step.action_config.strip()
        session.add(
            ProcessLog(
                org_id=event.org_id,
                execution_id=execution.id,
                process_name=process.name,
                step_id=step.id,
                level="info",
                message=f"{step.position}. {step.name} — {label}" + (f" · {detail}" if detail else ""),
                logged_at=started,
            )
        )
        if step.action_type == "notify":
            session.add(
                Notification(
                    org_id=event.org_id,
                    title=step.name,
                    message=detail or result_msg,
                    kind="info",
                    is_read=False,
                    link=f"/m/automatizacion/processes/{process.id}",
                )
            )
    session.add(
        ProcessLog(
            org_id=event.org_id,
            execution_id=execution.id,
            process_name=process.name,
            level="info",
            message=f"Proceso completado: {result_msg}",
            logged_at=started,
        )
    )
    session.add(
        Notification(
            org_id=event.org_id,
            title=f"Proceso completado: {process.name}",
            message=result_msg,
            kind="success",
            is_read=False,
            link=f"/m/automatizacion/processes/{process.id}",
        )
    )
    await session.flush()
    return execution

@module.seed
async def seed(session: AsyncSession, org_id: UUID) -> None:
    from models import Process, ProcessStep
    samples = [
        ("Onboarding de oportunidad ganada", "event", "crm.opportunity.won", "active",
         [("Crear proyecto en Proyectos", "create_record"), ("Notificar al responsable", "notify")]),
        ("Seguimiento de nuevo lead", "event", "crm.lead.created", "active",
         [("Crear actividad de seguimiento", "create_task"), ("Enviar correo de bienvenida", "send_email")]),
        ("Confirmación de entrega", "event", "logistica.shipment.delivered", "active",
         [("Cerrar hallazgos relacionados", "update_step"), ("Notificar al cliente", "notify")]),
        ("Proceso de ejemplo", "manual", None, "draft", []),
    ]
    for name, ttype, event, status, steps in samples:
        existing = await session.scalar(select(Process).where(Process.name == name, Process.deleted_at.is_(None)))
        if existing is not None:
            continue
        cfg = {"event": event} if event else {}
        process = Process(
            org_id=org_id, name=name, status=status, trigger_type=ttype,
            trigger_config=json.dumps(cfg),
        )
        session.add(process)
        await session.flush()
        for pos, (sname, action) in enumerate(steps, start=1):
            session.add(ProcessStep(
                org_id=org_id, process_id=process.id, name=sname, position=pos,
                action_type=action, action_config="{}", is_active=True,
            ))


app = module.create_app()


# --- Constructor visual: acciones en vivo montadas sobre la app del módulo ---
# La imagen empaquetada del módulo no incluye @module.action; estos
# handlers permiten servir el constructor por el proxy en
# /api/automatizacion/processes/{id}/actions/<accion>.
import business  # noqa: E402
from fastapi import Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

_ROUTE_ACTIONS = {
    "builder_view",
    "builder_update",
    "add_step",
    "update_step",
    "delete_step",
    "run",
}
_CRON_TOKENS = {"*", "0", "5", "10", "15", "30", "45"}


@app.api_route(
    "/api/automatizacion/processes/{process_id}/actions/{action}",
    methods=["POST"],
)
async def _builder_action(request: Request, process_id: str, action: str) -> JSONResponse:
    if action not in _ROUTE_ACTIONS:
        return JSONResponse({"detail": "Acción no válida"}, status_code=422)
    payload = {}
    if request.method == "POST":
        try:
            body = await request.json()
            payload = body if isinstance(body, dict) else {}
        except Exception:
            payload = {}
    try:
        record_id = UUID(process_id)
    except (ValueError, TypeError):
        return JSONResponse({"detail": "Proceso no encontrado"}, status_code=404)

    db = getattr(module, "db", None)
    if db is None:
        raise ValueError("module.db no está disponible")

    async def _route(session) -> JSONResponse:
        process = await session.scalar(
            select(Process).where(Process.id == record_id)
        )
        if process is None:
            return JSONResponse({"detail": "Proceso no encontrado"}, status_code=404)
        if action == "builder_view":
            result = await business.builder_view(session, process.id)
            return JSONResponse(result)
        if action == "builder_update":
            result = await business.builder_update(session, process.id, payload)
            return JSONResponse(result)
        if action == "add_step":
            result = await business.step_create(session, process.id, payload)
            return JSONResponse(result)
        if action == "update_step":
            result = await business.step_update(session, process.id, business._uuid(payload.get("step_id")), payload)
            return JSONResponse(result)
        if action == "delete_step":
            result = await business.step_delete(session, process.id, business._uuid(payload.get("step_id")))
            return JSONResponse(result)
        if action == "run":
            result = await business.manual_run(session, process.id, business._uuid(payload.get("user_id")))
            return JSONResponse(result)
        return JSONResponse({"detail": "Acción no válida"}, status_code=422)

    org_from_payload = business._uuid(payload.get("org_id"))
    async with db.tenant_session(org_from_payload or record_id) as session:
        return await _route(session)


# --- Bandeja unificada (workbench): reporte agregado de todos los módulos ---
from fastapi import Depends  # noqa: E402
from typing import Annotated  # noqa: E402

SessionDep = Annotated[AsyncSession, Depends(module.session_dependency())]


@app.get("/api/automatizacion/reports/workbench")
async def _workbench_report(session: SessionDep) -> dict:
    from novvus_sdk import current_context

    ctx = current_context()
    return await business.workbench(session, ctx.org_id)


@app.get("/api/automatizacion/reports/dashboard")
async def _dashboard_report(session: SessionDep) -> dict:
    from novvus_sdk import current_context

    ctx = current_context()
    return await business.dashboard(session, ctx.org_id)


@app.get("/api/automatizacion/reports/export/processes")
async def _export_processes(session: SessionDep):
    from fastapi.responses import PlainTextResponse
    csv = await business.export_processes_csv(session)
    return PlainTextResponse(csv, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=processes.csv"})

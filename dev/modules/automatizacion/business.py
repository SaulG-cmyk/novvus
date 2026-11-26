"""Business rules de Automatización: constructor visual de procesos.

Se lee el flujo completo de un proceso (disparador + pasos ordenados) y se
puede editar de forma guiada. La edición mantiene la configuración como JSON
en `trigger_config` / `action_config`, tal como la espera el orquestador.
"""

import asyncio
import json
import logging
from datetime import datetime, UTC
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models import Process, ProcessExecution, ProcessLog, ProcessStep, Notification

logger = logging.getLogger("automatizacion.business")

# Eventos conocidos que el kernel puede entregar a este módulo.
EVENT_CATALOG: dict[str, str] = {
    "crm.quote.accepted": "Cotización aceptada (CRM)",
    "crm.opportunity.won": "Oportunidad ganada (CRM)",
    "crm.lead.created": "Nuevo prospecto (CRM)",
    "reclutamiento.candidate.hired": "Candidato contratado (Reclutamiento)",
    "logistica.shipment.delivered": "Envío entregado (Logística)",
    "auditorias.finding.created": "Hallazgo creado (Auditorías)",
    "projects.project.created": "Proyecto creado (Proyectos)",
}

# Catálogo conocido de acciones de paso.
ACTION_CATALOG: dict[str, str] = {
    "send_email": "Enviar correo",
    "create_task": "Crear tarea",
    "create_record": "Crear registro",
    "get_record": "Obtener registro",
    "query": "Buscar registros",
    "webhook": "Llamada webhook",
    "notify": "Notificar responsable",
}

# Constantes usadas por el constructor visual.
TRIGGER_TYPES = ("event", "scheduled", "manual", "webhook")
PROCESS_STATUSES = ("active", "paused", "draft", "archived")


# ---- Exportación CSV ----
async def export_processes_csv(session: AsyncSession) -> str:
    rows = (await session.execute(
        text("SELECT id, name, status, trigger_type, description, created_at FROM mod_automatizacion.process WHERE deleted_at IS NULL ORDER BY name")
    )).all()
    lines = ["id,name,status,trigger_type,description,created_at"]
    for r in rows:
        def esc(v: Any) -> str:
            s = "" if v is None else str(v)
            if "," in s or '"' in s or "\n" in s:
                s = '"' + s.replace('"', '""') + '"'
            return s
        lines.append(",".join(esc(v) for v in r))
    return "\n".join(lines) + "\n"


# ---- Agregador de bandeja unificada (workbench) ----
async def _q(session: AsyncSession, sql: str, *args: Any) -> int:
    try:
        res = await session.execute(text(sql), *args)
        return int(res.scalar() or 0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("workbench query failed: %s :: %s", sql, exc)
        return 0


async def workbench(session: AsyncSession, org_id: UUID) -> dict[str, Any]:
    """Bandeja unificada de trabajo: agrega métricas de todos los módulos (en paralelo)."""
    items = []
    counts = {}

    async def crm() -> None:
        n = await _q(session, "SELECT COUNT(*) FROM mod_crm.activity WHERE deleted_at IS NULL AND status='pending' AND due_date < now()")
        counts["actividades_vencidas"] = n
        if n:
            items.append({"module": "crm", "label": "Actividades vencidas", "count": n, "path": "/m/crm/activities", "tone": "warning"})

    async def projects() -> None:
        n = await _q(session, "SELECT COUNT(*) FROM mod_projects.task WHERE deleted_at IS NULL AND status NOT IN ('done','closed') AND due_date < now()")
        counts["tareas_vencidas"] = n
        if n:
            items.append({"module": "projects", "label": "Tareas vencidas", "count": n, "path": "/m/projects/tasks", "tone": "warning"})

    async def reclutamiento() -> None:
        n = await _q(session, "SELECT COUNT(*) FROM mod_reclutamiento.interview WHERE deleted_at IS NULL AND date BETWEEN now() AND now() + interval '7 days'")
        counts["entrevistas_7d"] = n
        if n:
            items.append({"module": "reclutamiento", "label": "Entrevistas próximos 7 días", "count": n, "path": "/m/reclutamiento/interviews", "tone": "info"})

    async def logistica() -> None:
        n = await _q(session, "SELECT COUNT(*) FROM mod_logistica.shipment WHERE deleted_at IS NULL AND status IN ('draft','planned','in_transit')")
        counts["envios_pendientes"] = n
        if n:
            items.append({"module": "logistica", "label": "Envíos pendientes", "count": n, "path": "/m/logistica/shipments", "tone": "info"})

    async def auditorias() -> None:
        n = await _q(session, "SELECT COUNT(*) FROM mod_auditorias.audit_finding WHERE deleted_at IS NULL AND status NOT IN ('closed','accepted')")
        counts["hallazgos_abiertos"] = n
        if n:
            items.append({"module": "auditorias", "label": "Hallazgos abiertos", "count": n, "path": "/m/auditorias/audit_findings", "tone": "danger"})

    async def automatizacion() -> None:
        counts["procesos_activos"] = await _q(session, "SELECT COUNT(*) FROM mod_automatizacion.process WHERE deleted_at IS NULL AND status='active'")
        failed = await _q(session, "SELECT COUNT(*) FROM mod_automatizacion.process_execution WHERE deleted_at IS NULL AND status='failed' AND started_at > now() - interval '7 days'")
        counts["ejecuciones_fallidas_7d"] = failed
        if failed:
            items.append({"module": "automatizacion", "label": "Ejecuciones fallidas (7d)", "count": failed, "path": "/m/automatizacion/process_executions", "tone": "danger"})

    await asyncio.gather(crm(), projects(), reclutamiento(), logistica(), auditorias(), automatizacion())

    return {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "counts": counts,
        "items": items,
        "total_pending": sum(i["count"] for i in items),
    }


# ---- Reporte en formato dashboard (compatible con la imagen web actual) ----
async def dashboard(session: AsyncSession, org_id: UUID) -> dict[str, Any]:
    """Payload views.dashboard: métricas + colas derivadas de la bandeja unificada."""
    wb = await workbench(session, org_id)
    counts = wb["counts"]
    items = wb["items"]
    now = datetime.now(tz=UTC)

    def metric(label: str, value: Any, description: str, tone: str = "neutral") -> dict[str, Any]:
        return {"label": label, "value": value, "description": description, "tone": tone}

    metrics = [
        metric("Actividades vencidas", counts.get("actividades_vencidas", 0), "Pendientes cuya fecha ya pasó", "danger" if counts.get("actividades_vencidas") else "neutral"),
        metric("Tareas vencidas", counts.get("tareas_vencidas", 0), "Tareas de proyectos fuera de plazo", "danger" if counts.get("tareas_vencidas") else "neutral"),
        metric("Entrevistas (7d)", counts.get("entrevistas_7d", 0), "Entrevistas programadas en los próximos 7 días", "info"),
        metric("Envíos pendientes", counts.get("envios_pendientes", 0), "Borrador / planeado / en tránsito", "info"),
        metric("Hallazgos abiertos", counts.get("hallazgos_abiertos", 0), "Hallazgos no cerrados ni aceptados", "danger" if counts.get("hallazgos_abiertos") else "neutral"),
        metric("Procesos activos", counts.get("procesos_activos", 0), "Automatizaciones en ejecución", "info"),
        metric("Total pendiente", wb["total_pending"], "Elementos que requieren atención", "warning" if wb["total_pending"] else "success"),
    ]

    queues = []
    for it in items:
        queues.append({
            "title": it["label"],
            "description": f"{it['count']} elemento(s) pendiente(s)",
            "tone": it["tone"],
            "empty": f"Sin {it['label'].lower()}.",
            "total": it["count"],
            "items": [{"id": it["module"], "title": it["label"], "subtitle": f"{it['count']} pendiente(s)", "path": it["path"], "status": {"label": str(it["count"]), "tone": it["tone"]}, "updated_at": now.isoformat()}],
        })

    return {
        "generated_at": now.isoformat(),
        "metrics": metrics,
        "recent": {
            "title": "Bandeja unificada de trabajo",
            "description": "Elementos pendientes de todos los módulos",
            "path": "automatizacion",
            "empty": "Sin pendientes. Todo al día.",
            "items": [{"id": it["module"], "title": it["label"], "subtitle": f"{it['count']} pendiente(s)", "path": it["path"], "status": {"label": str(it["count"]), "tone": it["tone"]}, "updated_at": now.isoformat()} for it in items[:8]],
        },
        "queues": queues,
        "distribution": [{"label": it["label"], "value": it["count"], "tone": it["tone"]} for it in items],
    }


def _parse_json(value: str) -> dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _clean_json(value: str) -> dict[str, Any] | None:
    """Devuelve el dict o None si el JSON es inválido (error duro de validación)."""
    if not value:
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except (ValueError, TypeError):
        return None


async def _get_process(session: AsyncSession, process_id: UUID | None) -> Process | None:
    if process_id is None:
        return None
    return await session.scalar(
        select(Process).where(Process.id == process_id, Process.deleted_at.is_(None))
    )


async def _steps(session: AsyncSession, process_id: UUID) -> list[ProcessStep]:
    return list(
        (
            await session.scalars(
                select(ProcessStep)
                .where(ProcessStep.process_id == process_id, ProcessStep.deleted_at.is_(None))
                .order_by(ProcessStep.position)
            )
        ).all()
    )


async def _log(
    session: AsyncSession,
    org_id: UUID,
    execution_id: UUID,
    message: str,
    *,
    level: str = "info",
    step_id: UUID | None = None,
    process_name: str = "",
) -> None:
    if not process_name:
        process_name = (
            await session.scalar(
                select(ProcessExecution.process_name).where(ProcessExecution.id == execution_id)
            )
            or ""
        )
    session.add(
        ProcessLog(
            org_id=org_id,
            execution_id=execution_id,
            step_id=step_id,
            level=level,
            message=message,
            logged_at=datetime.now(tz=UTC),
            process_name=process_name,
        )
    )
    await session.flush()


async def builder_view(session: AsyncSession, process_id: UUID) -> dict[str, Any]:
    process = await _get_process(session, process_id)
    if process is None:
        raise HTTPException(status_code=404, detail="Proceso no encontrado")
    trigger = _parse_json(process.trigger_config)
    steps = await _steps(session, process.id)
    return {
        "process": {
            "id": str(process.id),
            "name": process.name,
            "description": process.description,
            "status": process.status,
            "trigger_type": process.trigger_type,
            "trigger_config": process.trigger_config,
            "owner_user_id": str(process.owner_user_id) if process.owner_user_id else None,
        },
        "trigger": {
            "type": process.trigger_type,
            "event": trigger.get("event"),
            "event_label": EVENT_CATALOG.get(trigger.get("event"), trigger.get("event")),
            "cron": trigger.get("cron"),
            "config": trigger,
        },
        "steps": [
            {
                "id": str(s.id),
                "position": s.position,
                "name": s.name,
                "action_type": s.action_type,
                "action_label": ACTION_CATALOG.get(s.action_type, s.action_type),
                "action_config": s.action_config,
                "config": _parse_json(s.action_config),
                "is_active": bool(s.is_active),
            }
            for s in steps
        ],
        "catalog": {
            "events": [{"value": k, "label": v} for k, v in EVENT_CATALOG.items()],
            "actions": [{"value": k, "label": v} for k, v in ACTION_CATALOG.items()],
            "trigger_types": list(TRIGGER_TYPES),
            "statuses": list(PROCESS_STATUSES),
        },
    }


async def builder_update(
    session: AsyncSession, process_id: UUID, body: dict[str, Any]
) -> dict[str, Any]:
    process = await _get_process(session, process_id)
    if process is None:
        raise HTTPException(status_code=404, detail="Proceso no encontrado")

    name = str(body.get("name") or "").strip()
    status = str(body.get("status") or "").strip()
    trigger_type = str(body.get("trigger_type") or "").strip()
    trigger_config = body.get("trigger_config")

    if name:
        process.name = name[:200]
    if status:
        if status not in PROCESS_STATUSES:
            raise HTTPException(status_code=422, detail={"status": "Estado inválido"})
        process.status = status
    if body.get("description") is not None:
        process.description = str(body["description"])[:4000]

    new_trigger: dict[str, Any] | None = None
    if trigger_config is not None:
        new_trigger = _clean_json(str(trigger_config))
        if new_trigger is None:
            raise HTTPException(status_code=422, detail={"trigger_config": "JSON inválido"})
    elif trigger_type and trigger_type != process.trigger_type:
        new_trigger = {}

    if trigger_type:
        if trigger_type not in TRIGGER_TYPES:
            raise HTTPException(status_code=422, detail={"trigger_type": "Tipo de disparador inválido"})
        process.trigger_type = trigger_type
    if new_trigger is not None:
        if process.trigger_type == "event" and not new_trigger.get("event"):
            raise HTTPException(
                status_code=422,
                detail={"trigger_config": "Un proceso por evento necesita el campos \"event\""},
            )
        process.trigger_config = json.dumps(new_trigger)

    await session.flush()
    return {"message": "Proceso actualizado", "view": await builder_view(session, process.id)}


async def step_create(
    session: AsyncSession, process_id: UUID, body: dict[str, Any]
) -> dict[str, Any]:
    process = await _get_process(session, process_id)
    if process is None:
        raise HTTPException(status_code=404, detail="Proceso no encontrado")
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail={"name": "El paso necesita un nombre"})
    action_type = str(body.get("action_type") or "").strip() or "notify"
    action_config = _clean_json(str(body.get("action_config") or ""))
    if action_config is None:
        raise HTTPException(status_code=422, detail={"action_config": "JSON inválido"})
    existing = await _steps(session, process.id)
    next_position = (max((s.position for s in existing), default=0)) + 1
    position = int(body.get("position") or next_position)
    step = ProcessStep(
        org_id=process.org_id,
        process_id=process.id,
        name=name[:200],
        position=position,
        action_type=action_type[:60],
        action_config=json.dumps(action_config),
        is_active=bool(body.get("is_active", True)),
    )
    session.add(step)
    await session.flush()
    return {"message": "Paso creado", "step_id": str(step.id)}


async def step_update(
    session: AsyncSession, process_id: UUID, step_id: UUID | None, body: dict[str, Any]
) -> dict[str, Any]:
    process = await _get_process(session, process_id)
    if process is None:
        raise HTTPException(status_code=404, detail="Proceso no encontrado")
    step = await session.scalar(
        select(ProcessStep).where(
            ProcessStep.id == step_id,
            ProcessStep.process_id == process.id,
            ProcessStep.deleted_at.is_(None),
        )
    )
    if step is None:
        raise HTTPException(status_code=404, detail="Paso no encontrado")
    if body.get("name") is not None:
        name = str(body["name"]).strip()
        if not name:
            raise HTTPException(status_code=422, detail={"name": "El paso necesita un nombre"})
        step.name = name[:200]
    if body.get("position") is not None:
        step.position = int(body["position"])
    if body.get("action_type") is not None:
        step.action_type = str(body["action_type"]).strip()[:60]
    if body.get("action_config") is not None:
        config = _clean_json(str(body["action_config"]))
        if config is None:
            raise HTTPException(status_code=422, detail={"action_config": "JSON inválido"})
        step.action_config = json.dumps(config)
    if body.get("is_active") is not None:
        step.is_active = bool(body["is_active"])
    await session.flush()
    return {"message": "Paso actualizado"}


async def step_delete(
    session: AsyncSession, process_id: UUID, step_id: UUID | None
) -> dict[str, Any]:
    process = await _get_process(session, process_id)
    if process is None:
        raise HTTPException(status_code=404, detail="Proceso no encontrado")
    step = await session.scalar(
        select(ProcessStep).where(
            ProcessStep.id == step_id,
            ProcessStep.process_id == process.id,
            ProcessStep.deleted_at.is_(None),
        )
    )
    if step is None:
        raise HTTPException(status_code=404, detail="Paso no encontrado")
    step.deleted_at = datetime.now(tz=UTC)
    await session.flush()
    return {"message": "Paso eliminado"}


async def step_choices(session: AsyncSession, process_id: UUID) -> list[dict[str, Any]]:
    steps = await _steps(session, process_id)
    return [
        {
            "value": str(s.id),
            "label": f"{s.position}. {s.name}",
            "description": ACTION_CATALOG.get(s.action_type, s.action_type),
        }
        for s in steps
    ]


async def manual_run(session: AsyncSession, process_id: UUID, user_id: UUID | None = None) -> dict[str, Any]:
    process = await _get_process(session, process_id)
    if process is None:
        raise HTTPException(status_code=404, detail="Proceso no encontrado")
    if process.status != "active":
        raise HTTPException(status_code=409, detail="Solo un proceso activo puede ejecutarse")

    started = datetime.now(tz=UTC)
    execution = ProcessExecution(
        org_id=process.org_id,
        process_id=process.id,
        process_name=process.name,
        status="completed",
        started_at=started,
        finished_at=started,
        result="Ejecución manual",
        triggered_by=user_id,
    )
    session.add(execution)
    await session.flush()
    await _log(session, process.org_id, execution.id, "Ejecución manual iniciada")

    steps = await _steps(session, process.id)
    if not steps:
        await _log(session, process.org_id, execution.id, "Sin pasos activos: nada que ejecutar", level="warn")
    for step in steps:
        label = ACTION_CATALOG.get(step.action_type, step.action_type)
        if not step.is_active:
            await _log(
                session, process.org_id, execution.id,
                f"{step.position}. {step.name} ({step.action_type}): omitido (inactivo)",
                level="debug", step_id=step.id,
            )
        else:
            detail = step.action_config.strip()
            await _log(
                session, process.org_id, execution.id,
                f"{step.position}. {step.name} — {label}" + (f" · {detail}" if detail else ""),
                step_id=step.id,
            )
            if step.action_type == "notify":
                session.add(
                    Notification(
                        org_id=process.org_id,
                        title=step.name,
                        message=detail or f"Proceso {process.name} ejecutado",
                        kind="info",
                        is_read=False,
                        link=f"/m/automatizacion/processes/{process.id}",
                    )
                )
    done_msg = (
        f"Proceso completado: {len(steps)} de {len(steps)} pasos ejecutados"
        if steps
        else "Proceso completado: sin pasos configurados"
    )
    await _log(session, process.org_id, execution.id, done_msg)
    session.add(
        Notification(
            org_id=process.org_id,
            title=f"Proceso completado: {process.name}",
            message=(f"Se ejecutaron {len(steps)} pasos del proceso." if steps else "El proceso no tiene pasos configurados."),
            kind="success",
            is_read=False,
            link=f"/m/automatizacion/processes/{process.id}",
        )
    )
    await session.flush()
    return {
        "message": f"Proceso {process.name} ejecutado",
        "execution_id": str(execution.id),
        "steps": len(steps),
    }


def register(module) -> None:
    # La imagen empaquetada del módulo no expone @module.action; la acción en
    # vivo se monta más abajo desde module.py con handlers propios. Se conserva
    # este registro para compatibilidad con SDK actuales (0.1.0). En SDK >=0.2
    # las acciones deben declararse en __novvus_views__['actions'], lo que no
    # aplica a este módulo, así que se omite para no romper el arranque.
    if not hasattr(module, "action"):
        return
    views = getattr(Process, "__novvus_views__", {}) or {}
    if not views.get("actions"):
        return

    @module.action(Process, "builder_view")
    async def builder_view_action(session: AsyncSession, _ctx: Any, process: Process, _body: dict[str, Any]) -> dict[str, Any]:
        return await builder_view(session, process.id)

    @module.action(Process, "builder_update")
    async def builder_update_action(session: AsyncSession, _ctx: Any, process: Process, body: dict[str, Any]) -> dict[str, Any]:
        return await builder_update(session, process.id, body)

    @module.action(Process, "add_step")
    async def add_step_action(session: AsyncSession, _ctx: Any, process: Process, body: dict[str, Any]) -> dict[str, Any]:
        return await step_create(session, process.id, body)

    @module.action(Process, "update_step")
    async def update_step_action(session: AsyncSession, _ctx: Any, process: Process, body: dict[str, Any]) -> dict[str, Any]:
        return await step_update(session, process.id, _uuid(body.get("step_id")), body)

    @module.action(Process, "delete_step")
    async def delete_step_action(session: AsyncSession, _ctx: Any, process: Process, body: dict[str, Any]) -> dict[str, Any]:
        return await step_delete(session, process.id, _uuid(body.get("step_id")))

    @module.action(Process, "run")
    async def run_action(session: AsyncSession, ctx: Any, process: Process, _body: dict[str, Any]) -> dict[str, Any]:
        return await manual_run(session, process.id, ctx.user_id)

    @module.action_options(Process, "delete_step")
    async def delete_step_options(session: AsyncSession, _ctx: Any, process: Process, _body: dict[str, Any]) -> dict[str, Any]:
        return {"step_id": await step_choices(session, process.id)}

    @module.action_options(Process, "update_step")
    async def update_step_options(session: AsyncSession, _ctx: Any, process: Process, _body: dict[str, Any]) -> dict[str, Any]:
        return {"step_id": await step_choices(session, process.id)}
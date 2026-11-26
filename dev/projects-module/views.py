"""Generic-view declarations layered on the Projects models (docs/VIEWS.md §8b-§8g).

Same split as the CRM: models.py describes data, views.py describes what the
shell renders (badges, counters, tabs, related panels, stage indicators).
`declare()` must run BEFORE the models are registered.
"""

from typing import Any

from models import (
    Approval,
    Deliverable,
    Milestone,
    Phase,
    Process,
    ProcessStage,
    Project,
    Risk,
    Task,
    TaskDependency,
    Template,
)

try:
    from novvus_sdk import VIEW_KEYS
except Exception:  # an older SDK: no 8j keys
    VIEW_KEYS = frozenset()
_8J = "choices" in VIEW_KEYS

try:
    from novvus_sdk import NAV_KEYS
except ImportError:
    NAV_KEYS = frozenset()
# 8k: Gantt over the tasks (SDK 0.2.16).
_8K = "timeline" in VIEW_KEYS
TASK_TIMELINE = {
    "start_field": "start_date",
    "end_field": "due_date",
    "title": "title",
    "progress_field": "progress",
    "group_field": "project_id",
    "dependencies": {
        "model": "task_dependencies",
        "predecessor_field": "predecessor_id",
        "successor_field": "successor_id",
        "kind_field": "kind",
    },
}

PROJECT_STATUS_TONES = {
    "draft": "neutral",
    "active": "info",
    "paused": "warning",
    "completed": "success",
    "cancelled": "danger",
    "archived": "neutral",
}
HEALTH_TONES = {
    "on_track": "success",
    "at_risk": "warning",
    "delayed": "danger",
    "blocked": "danger",
}
PRIORITY_TONES = {"low": "neutral", "medium": "info", "high": "warning", "critical": "danger"}
PHASE_STATUS_TONES = {
    "pending": "neutral",
    "active": "info",
    "done": "success",
    "cancelled": "danger",
}
PROCESS_STATUS_TONES = {
    "pending": "neutral",
    "running": "info",
    "done": "success",
    "cancelled": "danger",
}
STAGE_STATUS_TONES = {
    "pending": "neutral",
    "active": "info",
    "done": "success",
    "skipped": "warning",
}
TASK_STATUS_TONES = {
    "todo": "neutral",
    "doing": "info",
    "blocked": "danger",
    "review": "warning",
    "done": "success",
    "cancelled": "neutral",
}
MILESTONE_TONES = {
    "pending": "info",
    "reached": "success",
    "missed": "danger",
    "cancelled": "neutral",
}
DELIVERABLE_TONES = {
    "pending": "neutral",
    "in_progress": "info",
    "submitted": "warning",
    "approved": "success",
    "rejected": "danger",
    "delivered": "success",
}
RISK_LEVEL_TONES = {"low": "neutral", "medium": "warning", "high": "danger"}
RISK_STATUS_TONES = {
    "open": "warning",
    "mitigating": "info",
    "materialized": "danger",
    "closed": "success",
}
APPROVAL_TONES = {"pending": "warning", "approved": "success", "rejected": "danger"}

LEVEL_LABELS = {"low": "Baja", "medium": "Media", "high": "Alta"}
PRIORITY_LABELS = {**LEVEL_LABELS, "critical": "Crítica"}
KIND_LABELS = {
    "internal": "Interno",
    "administrative": "Administrativo",
    "technology": "Tecnológico",
    "industrial": "Industrial",
    "service": "De servicios",
    "other": "Otro",
}
STRATEGY_LABELS = {
    "tasks": "Por actividades completadas",
    "weighted": "Ponderado por pesos",
    "milestones": "Por hitos alcanzados",
}
CHOICE_LABELS: dict[str, dict[str, dict[str, str]]] = {
    "projects": {
        "kind": KIND_LABELS,
        "status": {
            "draft": "Borrador",
            "active": "Activo",
            "paused": "Pausado",
            "completed": "Concluido",
            "cancelled": "Cancelado",
            "archived": "Archivado",
        },
        "health": {
            "on_track": "En tiempo",
            "at_risk": "En riesgo",
            "delayed": "Retrasado",
            "blocked": "Bloqueado",
        },
        "priority": PRIORITY_LABELS,
        "progress_strategy": STRATEGY_LABELS,
    },
    "templates": {"kind": KIND_LABELS, "progress_strategy": STRATEGY_LABELS},
    "phases": {
        "status": {
            "pending": "Pendiente",
            "active": "Activa",
            "done": "Terminada",
            "cancelled": "Cancelada",
        }
    },
    "processes": {
        "status": {
            "pending": "Pendiente",
            "running": "En ejecución",
            "done": "Terminado",
            "cancelled": "Cancelado",
        }
    },
    "process_stages": {
        "status": {
            "pending": "Pendiente",
            "active": "Activa",
            "done": "Terminada",
            "skipped": "Omitida",
        }
    },
    "tasks": {
        "status": {
            "todo": "Por hacer",
            "doing": "En curso",
            "blocked": "Bloqueada",
            "review": "En revisión",
            "done": "Hecha",
            "cancelled": "Cancelada",
        },
        "priority": PRIORITY_LABELS,
    },
    "milestones": {
        "status": {
            "pending": "Pendiente",
            "reached": "Alcanzado",
            "missed": "Incumplido",
            "cancelled": "Cancelado",
        }
    },
    "deliverables": {
        "status": {
            "pending": "Pendiente",
            "in_progress": "En elaboración",
            "submitted": "Entregado para revisión",
            "approved": "Aprobado",
            "rejected": "Rechazado",
            "delivered": "Entregado",
        }
    },
    "risks": {
        "probability": LEVEL_LABELS,
        "impact": LEVEL_LABELS,
        "status": {
            "open": "Identificado",
            "mitigating": "En mitigación",
            "materialized": "Materializado",
            "closed": "Cerrado",
        },
    },
    "approvals": {
        "status": {"pending": "Pendiente", "approved": "Aprobada", "rejected": "Rechazada"},
        "target_kind": {
            "deliverable": "Entregable",
            "milestone": "Hito",
            "stage": "Etapa de proceso",
            "task": "Actividad",
        },
    },
}

PROJECT_STAGES = {
    "field": "status",
    "steps": [
        {"label": "Borrador", "values": ["draft"]},
        {"label": "En ejecución", "values": ["active", "paused"]},
        {"label": "Concluido", "values": ["completed", "archived"]},
    ],
}
TASK_STAGES = {
    "field": "status",
    "steps": [
        {"label": "Por hacer", "values": ["todo", "blocked"]},
        {"label": "En curso", "values": ["doing"]},
        {"label": "En revisión", "values": ["review"]},
        {"label": "Hecha", "values": ["done"]},
    ],
}
PROCESS_STAGES = {
    "field": "status",
    "steps": [
        {"label": "Pendiente", "values": ["pending"]},
        {"label": "En ejecución", "values": ["running"]},
        {"label": "Terminado", "values": ["done"]},
    ],
}


def _choices(resource: str, field: str) -> list[dict[str, str]]:
    return [{"value": k, "label": v} for k, v in CHOICE_LABELS[resource][field].items()]


PROJECT_ACTIONS: list[dict[str, Any]] = [
    {
        "name": "register",
        "label": "Nuevo proyecto",
        "scope": "collection",
        "variant": "primary",
        "permission": "projects.projects.write",
        "validate": True,
        "success": "open",
        "help": "Código único; con plantilla se generan fases, procesos, actividades e hitos",
        "fields": [
            {"name": "code", "label": "Código", "type": "string", "required": True},
            {"name": "name", "label": "Nombre", "type": "string", "required": True},
            {
                "name": "kind",
                "label": "Tipo",
                "type": "choice",
                "choices": _choices("projects", "kind"),
            },
            {
                "name": "priority",
                "label": "Prioridad",
                "type": "choice",
                "default": "medium",
                "choices": _choices("projects", "priority"),
            },
            {"name": "template_id", "label": "Plantilla", "type": "choice", "options": True},
            {"name": "start_date", "label": "Inicio", "type": "date"},
            {"name": "due_date", "label": "Conclusión estimada", "type": "date"},
            {"name": "budget", "label": "Presupuesto", "type": "number"},
            {"name": "currency", "label": "Moneda", "type": "string", "default": "MXN"},
            {
                "name": "progress_strategy",
                "label": "Estrategia de avance",
                "type": "choice",
                "choices": _choices("projects", "progress_strategy"),
                "help": "Vacío = la de la plantilla, o por actividades completadas",
            },
            {
                "name": "company_id",
                "label": "Cliente (id del CRM)",
                "type": "string",
                "help": "Opcional; se vincula por identificador del CRM",
            },
            {"name": "opportunity_id", "label": "Oportunidad (id del CRM)", "type": "string"},
            {"name": "company_name", "label": "Cliente (nombre)", "type": "string"},
            {"name": "contact_id", "label": "Contacto (id del CRM)", "type": "string"},
            {"name": "contact_name", "label": "Contacto (nombre)", "type": "string"},
            {"name": "opportunity_name", "label": "Oportunidad (nombre)", "type": "string"},
            {"name": "description", "label": "Descripción", "type": "text"},
        ],
    },
    {
        "name": "activate",
        "label": "Iniciar",
        "variant": "primary",
        "confirm": "¿Poner el proyecto en ejecución?",
    },
    {"name": "pause", "label": "Pausar", "confirm": "¿Pausar el proyecto?"},
    {
        "name": "complete",
        "label": "Concluir",
        "variant": "primary",
        "help": "Con actividades abiertas solo se concluye forzando",
        "fields": [
            {
                "name": "force",
                "label": "Concluir aunque queden actividades abiertas",
                "type": "boolean",
                "default": False,
            }
        ],
    },
    {"name": "recompute", "label": "Recalcular avance y salud", "secondary": True},
    {
        "name": "cancel",
        "label": "Cancelar proyecto",
        "variant": "destructive",
        "secondary": True,
        "confirm": "¿Cancelar el proyecto?",
    },
    {
        "name": "archive",
        "label": "Archivar",
        "secondary": True,
        "permission": "projects.projects.delete",
        "confirm": "¿Archivar el proyecto? Solo concluidos o cancelados.",
    },
    {
        "name": "restore",
        "label": "Restaurar",
        "secondary": True,
        "permission": "projects.projects.delete",
    },
    {
        "name": "remove",
        "label": "Eliminar",
        "variant": "destructive",
        "secondary": True,
        "permission": "projects.projects.delete",
        "success": "open",
        "help": "Solo borradores, cancelados o archivados; se pierden fases, actividades e hitos",
        "fields": [
            {
                "name": "force",
                "label": "Eliminar aunque tenga actividades completadas",
                "type": "boolean",
                "default": False,
            }
        ],
    },
]

PROJECT_STATUS_ACTION: dict[str, Any] = {
    "name": "set_status",
    "label": "Cambiar estado",
    "help": "Pasa por las reglas del ciclo de vida (iniciar, pausar, concluir, cancelar, archivar)",
    "fields": [
        {
            "name": "status",
            "label": "Estado",
            "type": "choice",
            "required": True,
            "choices": _choices("projects", "status"),
        }
    ],
}
RISK_STATUS_ACTION: dict[str, Any] = {
    "name": "set_status",
    "label": "Cambiar estado",
    "fields": [
        {
            "name": "status",
            "label": "Estado",
            "type": "choice",
            "required": True,
            "choices": _choices("risks", "status"),
        }
    ],
}

PHASE_ACTIONS: list[dict[str, Any]] = [
    {
        "name": "set_status",
        "label": "Cambiar estado",
        "variant": "primary",
        "fields": [
            {
                "name": "status",
                "label": "Estado",
                "type": "choice",
                "required": True,
                "choices": _choices("phases", "status"),
            }
        ],
    },
    {
        "name": "reorder",
        "label": "Mover de posición",
        "secondary": True,
        "fields": [
            {
                "name": "position",
                "label": "Nueva posición (0 = primera)",
                "type": "number",
                "required": True,
            }
        ],
    },
]

TASK_ACTIONS: list[dict[str, Any]] = [
    {
        "name": "set_status",
        "label": "Cambiar estado",
        "variant": "primary",
        "help": "Por hacer → en curso → en revisión → hecha; las predecesoras deben cumplirse",
        "fields": [
            {
                "name": "status",
                "label": "Estado",
                "type": "choice",
                "required": True,
                "choices": [c for c in _choices("tasks", "status") if c["value"] != "blocked"],
            },
            {
                "name": "force",
                "label": "Ignorar predecesoras pendientes",
                "type": "boolean",
                "default": False,
            },
        ],
    },
    {
        "name": "set_progress",
        "label": "Registrar avance",
        "fields": [
            {"name": "progress", "label": "Avance (%)", "type": "number", "required": True},
            {
                "name": "logged_hours",
                "label": "Horas a registrar",
                "type": "number",
                "help": "Se suman a las horas registradas",
            },
        ],
    },
    {
        "name": "assign",
        "label": "Asignar responsable",
        "fields": [
            {
                "name": "user_id",
                "label": "Usuario (id)",
                "type": "string",
                "help": "Vacío = asignármela a mí",
            }
        ],
    },
    {
        "name": "add_dependency",
        "label": "Agregar dependencia",
        "validate": True,
        "help": "No avanzará hasta que la predecesora cumpla; se rechazan los ciclos",
        "fields": [
            {
                "name": "predecessor_id",
                "label": "Depende de",
                "type": "choice",
                "required": True,
                "options": True,
            },
            {
                "name": "kind",
                "label": "Tipo",
                "type": "choice",
                "default": "finish_to_start",
                "choices": [
                    {"value": "finish_to_start", "label": "Fin a inicio"},
                    {"value": "start_to_start", "label": "Inicio a inicio"},
                    {"value": "finish_to_finish", "label": "Fin a fin"},
                    {"value": "start_to_finish", "label": "Inicio a fin"},
                ],
            },
            {"name": "lag_days", "label": "Desfase (días)", "type": "number", "default": 0},
        ],
    },
    {
        "name": "block",
        "label": "Bloquear",
        "variant": "destructive",
        "fields": [
            {"name": "reason", "label": "Causa del bloqueo", "type": "text", "required": True}
        ],
    },
    {"name": "unblock", "label": "Desbloquear", "confirm": "¿Desbloquear la actividad?"},
    {
        "name": "request_approval",
        "label": "Solicitar aprobación",
        "secondary": True,
        "fields": [{"name": "approver_user_id", "label": "Aprobador (id)", "type": "string"}],
    },
]

DEPENDENCY_ACTIONS: list[dict[str, Any]] = [
    {
        "name": "remove",
        "label": "Quitar dependencia",
        "variant": "destructive",
        "confirm": "¿Quitar la dependencia?",
    },
]

MILESTONE_ACTIONS: list[dict[str, Any]] = [
    {
        "name": "reach",
        "label": "Marcar alcanzado",
        "variant": "primary",
        "confirm": "¿Registrar el hito como alcanzado?",
    },
    {"name": "miss", "label": "Marcar incumplido", "variant": "destructive", "secondary": True},
    {"name": "reopen", "label": "Volver a pendiente", "secondary": True},
]

DELIVERABLE_ACTIONS: list[dict[str, Any]] = [
    {"name": "start", "label": "Iniciar elaboración"},
    {
        "name": "submit",
        "label": "Enviar a aprobación",
        "variant": "primary",
        "fields": [{"name": "approver_user_id", "label": "Aprobador (id)", "type": "string"}],
    },
    {
        "name": "deliver",
        "label": "Entregar",
        "confirm": "¿Registrar la entrega? Requiere aprobación previa.",
    },
]

APPROVAL_ACTIONS: list[dict[str, Any]] = [
    {
        "name": "approve",
        "label": "Aprobar",
        "variant": "primary",
        "permission": "projects.approvals.decide",
        "fields": [{"name": "note", "label": "Nota", "type": "text"}],
    },
    {
        "name": "reject",
        "label": "Rechazar",
        "variant": "destructive",
        "permission": "projects.approvals.decide",
        "fields": [{"name": "note", "label": "Motivo", "type": "text", "required": True}],
    },
]

RISK_ACTIONS: list[dict[str, Any]] = [
    {
        "name": "assess",
        "label": "Evaluar",
        "variant": "primary",
        "help": "Puntuación = probabilidad x impacto (baja 1, media 2, alta 3); 6 o más alerta",
        "fields": [
            {
                "name": "probability",
                "label": "Probabilidad",
                "type": "choice",
                "choices": _choices("risks", "probability"),
            },
            {
                "name": "impact",
                "label": "Impacto",
                "type": "choice",
                "choices": _choices("risks", "impact"),
            },
            {"name": "mitigation", "label": "Plan de mitigación", "type": "text"},
            {"name": "review_date", "label": "Próxima revisión", "type": "date"},
        ],
    },
    {
        "name": "materialize",
        "label": "Se materializó",
        "variant": "destructive",
        "fields": [{"name": "description", "label": "Qué ocurrió", "type": "text"}],
    },
    {"name": "close", "label": "Cerrar", "secondary": True, "confirm": "¿Cerrar el riesgo?"},
]


PROCESS_ACTIONS: list[dict[str, Any]] = [
    {
        "name": "start",
        "label": "Iniciar proceso",
        "variant": "primary",
        "fields": [{"name": "note", "label": "Nota", "type": "text"}],
    },
    {
        "name": "advance",
        "label": "Avanzar etapa",
        "variant": "primary",
        "validate": True,
        "help": "Cierra la etapa actual (aprobación, evidencias, actividades) y abre la siguiente",
        "fields": [
            {
                "name": "note",
                "label": "Nota o evidencia",
                "type": "text",
                "help": "Obligatoria cuando la etapa exige evidencia o condiciones de salida",
            }
        ],
    },
    {
        "name": "request_approval",
        "label": "Solicitar aprobación de la etapa",
        "fields": [{"name": "approver_user_id", "label": "Aprobador (id)", "type": "string"}],
    },
    {
        "name": "skip",
        "label": "Omitir etapa",
        "variant": "destructive",
        "secondary": True,
        "permission": "projects.approvals.decide",
        "help": "Autorización explícita: queda en el historial como transición forzada",
        "fields": [{"name": "note", "label": "Motivo", "type": "text", "required": True}],
    },
    {
        "name": "cancel",
        "label": "Cancelar proceso",
        "variant": "destructive",
        "secondary": True,
        "fields": [{"name": "note", "label": "Motivo", "type": "text"}],
    },
]


def _related(
    model: str,
    field: str,
    label: str,
    columns: list[str],
    order: str = "-created_at",
    limit: int = 50,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "model": model,
        "field": field,
        "label": label,
        "columns": columns,
        "order": order,
        "limit": limit,
        **extra,
    }


def _merge(model: Any, **patch: Any) -> None:
    views = dict(model.__novvus_views__)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(views.get(key), dict):
            views[key] = {**views[key], **value}
        else:
            views[key] = value
    model.__novvus_views__ = views


TASK_COLUMNS = [
    "title",
    "status",
    "priority",
    "assigned_user_id",
    "due_date",
    "progress",
    "is_blocked",
]


PROJECT_ACTIONS.append(PROJECT_STATUS_ACTION)
RISK_ACTIONS.append(RISK_STATUS_ACTION)


def declare() -> None:
    if "icon" in NAV_KEYS:
        for model, icon in (
            (Project, "folder-kanban"), (Phase, "layers"), (Process, "flow-branch"),
            (Task, "list-todo"), (Milestone, "flag"), (Deliverable, "package"),
            (Risk, "warning"), (Approval, "quality"), (Template, "file-text"),
        ):
            _merge(model, nav={"icon": icon})
    _merge(TaskDependency, actions=DEPENDENCY_ACTIONS)
    if _8J:
        for model in (
            Project,
            Template,
            Phase,
            Process,
            ProcessStage,
            Task,
            Milestone,
            Deliverable,
            Risk,
            Approval,
        ):
            _merge(model, choices=CHOICE_LABELS[model.resource_name()])
    _merge(
        Project,
        **({"kanban": {"action": "set_status"}} if _8J else {}),
        actions=PROJECT_ACTIONS,
        **(
            {
                "dashboard": {
                    "path": "reports/dashboard",
                    "title": "Portafolio de proyectos",
                    "order": 20,
                }
            }
            if "dashboard" in VIEW_KEYS
            else {}
        ),
        list={
            "badges": {
                "status": PROJECT_STATUS_TONES,
                "health": HEALTH_TONES,
                "priority": PRIORITY_TONES,
            },
            "counters": ["status", "health"],
        },
        related=[
            _related(
                "phases",
                "project_id",
                "Fases",
                ["position", "name", "status", "owner_user_id", "due_date", "progress"],
                "position",
            ),
            _related(
                "processes",
                "project_id",
                "Procesos",
                ["name", "phase_id", "status", "owner_user_id", "due_date"],
                "position",
            ),
            _related(
                "tasks",
                "project_id",
                "Actividades",
                ["title", "phase_id", *TASK_COLUMNS[1:]],
                "due_date",
                200,
            ),
            _related(
                "milestones",
                "project_id",
                "Hitos",
                ["name", "phase_id", "due_date", "owner_user_id", "status"],
                "due_date",
            ),
            _related(
                "deliverables",
                "project_id",
                "Entregables",
                ["name", "milestone_id", "status", "owner_user_id", "due_date"],
                "due_date",
            ),
            _related(
                "risks",
                "project_id",
                "Riesgos",
                ["title", "probability", "impact", "score", "status", "owner_user_id"],
                "-score",
            ),
            _related(
                "approvals",
                "project_id",
                "Aprobaciones",
                ["target_label", "target_kind", "approver_user_id", "status", "decided_at"],
            ),
            _related("project_members", "project_id", "Equipo", ["user_id", "role"], "role"),
            _related(
                "project_links",
                "project_id",
                "Oportunidades vinculadas",
                ["opportunity_name", "opportunity_id", "created_at"],
            ),
        ],
        form={
            "stages": PROJECT_STAGES,
            "tabs": [
                {"label": "Resumen", "rows": Project.__novvus_views__["form"]["layout"]},
                {"label": "Fases y procesos", "related": ["phases", "processes"]},
                {"label": "Actividades", "related": ["tasks"]},
                {"label": "Hitos y entregables", "related": ["milestones", "deliverables"]},
                {"label": "Riesgos y aprobaciones", "related": ["risks", "approvals"]},
                {"label": "Equipo y cliente", "related": ["project_members", "project_links"]},
                {"label": "Archivos y notas", "attachments": True, "chatter": True},
            ],
        },
    )
    _merge(
        Phase,
        actions=PHASE_ACTIONS,
        list={"badges": {"status": PHASE_STATUS_TONES}, "counters": ["status"]},
        related=[
            _related("tasks", "phase_id", "Actividades", TASK_COLUMNS, "due_date", 200),
            _related(
                "processes",
                "phase_id",
                "Procesos",
                ["name", "status", "owner_user_id", "due_date"],
                "position",
            ),
            _related(
                "milestones",
                "phase_id",
                "Hitos",
                ["name", "due_date", "owner_user_id", "status"],
                "due_date",
            ),
        ],
        form={
            "tabs": [
                {"label": "Datos", "rows": Phase.__novvus_views__["form"]["layout"]},
                {"label": "Actividades", "related": ["tasks"]},
                {"label": "Procesos e hitos", "related": ["processes", "milestones"]},
                {"label": "Notas", "chatter": True},
            ]
        },
    )
    _merge(
        Process,
        actions=PROCESS_ACTIONS,
        **(
            {"process": {"path": "processes", "summary": "running"}}
            if "process" in VIEW_KEYS
            else {}
        ),
        list={"badges": {"status": PROCESS_STATUS_TONES}, "counters": ["status"]},
        related=[
            _related(
                "process_stages",
                "process_id",
                "Etapas",
                [
                    "position",
                    "name",
                    "status",
                    "owner_user_id",
                    "is_mandatory",
                    "requires_approval",
                    "due_date",
                ],
                "position",
            ),
            _related(
                "tasks",
                "process_id",
                "Actividades",
                ["title", "stage_id", *TASK_COLUMNS[1:]],
                "due_date",
                200,
            ),
            _related(
                "process_transitions",
                "process_id",
                "Historial",
                ["created_at", "from_stage_id", "to_stage_id", "user_id", "forced", "note"],
            ),
        ],
        form={
            "stages": PROCESS_STAGES,
            "tabs": [
                {"label": "Datos", "rows": Process.__novvus_views__["form"]["layout"]},
                {"label": "Etapas", "related": ["process_stages"]},
                {"label": "Actividades", "related": ["tasks"]},
                {"label": "Historial", "related": ["process_transitions"]},
                {"label": "Notas", "chatter": True},
            ],
        },
    )
    _merge(ProcessStage, list={"badges": {"status": STAGE_STATUS_TONES}})
    _merge(
        Task,
        **({"kanban": {"action": "set_status"}} if _8J else {}),
        actions=TASK_ACTIONS,
        **({"timeline": TASK_TIMELINE} if _8K else {}),
        list={
            "badges": {"status": TASK_STATUS_TONES, "priority": PRIORITY_TONES},
            "counters": ["status", "priority"],
        },
        related=[
            _related("tasks", "parent_id", "Subtareas", TASK_COLUMNS, "position", 100),
            _related(
                "task_participants",
                "task_id",
                "Participantes",
                ["user_id", "created_at"],
                "created_at",
            ),
            _related(
                "deliverables", "task_id", "Entregables", ["name", "status", "due_date"], "due_date"
            ),
            _related(
                "task_dependencies",
                "successor_id",
                "Depende de",
                ["predecessor_id", "kind", "lag_days"],
                "created_at",
            ),
        ],
        form={
            "stages": TASK_STAGES,
            "tabs": [
                {"label": "Datos", "rows": Task.__novvus_views__["form"]["layout"]},
                {"label": "Subtareas", "related": ["tasks"]},
                {"label": "Dependencias", "related": ["task_dependencies"]},
                {
                    "label": "Participantes y entregables",
                    "related": ["task_participants", "deliverables"],
                },
                {"label": "Archivos y notas", "attachments": True, "chatter": True},
            ],
        },
    )
    _merge(
        Milestone,
        actions=MILESTONE_ACTIONS,
        list={"badges": {"status": MILESTONE_TONES}, "counters": ["status"]},
    )
    _merge(
        Deliverable,
        actions=DELIVERABLE_ACTIONS,
        calendar={"date_field": "due_date", "title": "name"},
        list={"badges": {"status": DELIVERABLE_TONES}, "counters": ["status"]},
    )
    _merge(
        Risk,
        **({"kanban": {"action": "set_status"}} if _8J else {}),
        actions=RISK_ACTIONS,
        list={
            "badges": {
                "probability": RISK_LEVEL_TONES,
                "impact": RISK_LEVEL_TONES,
                "status": RISK_STATUS_TONES,
            },
            "counters": ["status"],
        },
    )
    _merge(
        Approval,
        actions=APPROVAL_ACTIONS,
        list={"badges": {"status": APPROVAL_TONES}, "counters": ["status", "target_kind"]},
    )
    _merge(
        Template,
        related=[
            _related(
                "template_phases",
                "template_id",
                "Fases",
                ["position", "name", "weight", "duration_days"],
                "position",
            ),
            _related(
                "template_processes",
                "template_id",
                "Procesos",
                ["position", "name", "template_phase_id"],
                "position",
            ),
            _related(
                "template_tasks",
                "template_id",
                "Actividades",
                [
                    "position",
                    "title",
                    "template_phase_id",
                    "offset_days",
                    "duration_days",
                    "weight",
                ],
                "position",
                200,
            ),
            _related(
                "template_milestones",
                "template_id",
                "Hitos",
                ["name", "template_phase_id", "offset_days", "weight"],
                "offset_days",
            ),
            _related(
                "template_dependencies",
                "template_id",
                "Dependencias",
                ["predecessor_id", "successor_id", "kind", "lag_days"],
                "created_at",
            ),
        ],
        form={
            "tabs": [
                {"label": "Datos", "rows": Template.__novvus_views__["form"]["layout"]},
                {"label": "Fases y procesos", "related": ["template_phases", "template_processes"]},
                {"label": "Actividades", "related": ["template_tasks", "template_dependencies"]},
                {"label": "Hitos", "related": ["template_milestones"]},
            ]
        },
    )

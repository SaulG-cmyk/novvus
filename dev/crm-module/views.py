"""Generic-view declarations layered on the CRM models (docs/VIEWS.md §8b-§8g).

Kept apart from models.py the way an operations-style module keeps its
`actions.py`: the data model stays readable, and everything the shell renders
(badges, counters, tabs, related panels, stage indicators, actions) lives here.
`declare()` must run BEFORE the models are registered (the SDK validates
`__novvus_views__` at registration).
"""

from typing import Any

from models import (
    Activity,
    Company,
    Contact,
    Lead,
    LostReason,
    Opportunity,
    Pipeline,
    Product,
    Quote,
    QuoteLine,
    Stage,
    Tag,
    TaxRate,
)

try:
    from novvus_sdk import VIEW_KEYS
except Exception:  # an older SDK: no 8j keys
    VIEW_KEYS = frozenset()
# 8j (SDK 0.2.16): labelled enum options and kanban drops routed through a record action.
_8J = "choices" in VIEW_KEYS

try:
    from novvus_sdk import NAV_KEYS
except ImportError:
    NAV_KEYS = frozenset()

CHOICE_LABELS: dict[str, dict[str, dict[str, str]]] = {
    "companies": {
        "kind": {
            "customer": "Cliente",
            "prospect": "Prospecto",
            "partner": "Socio",
            "supplier": "Proveedor",
            "other": "Otro",
        },
        "status": {
            "prospect": "Prospecto",
            "active": "Activa",
            "inactive": "Inactiva",
            "lost": "Perdida",
        },
    },
    "contacts": {
        "kind": {
            "decision_maker": "Decisor",
            "influencer": "Influenciador",
            "user": "Usuario",
            "technical": "Técnico",
            "administrative": "Administrativo",
            "other": "Otro",
        },
        "status": {"active": "Activo", "inactive": "Inactivo"},
    },
    "leads": {
        "source": {
            "manual": "Captura manual",
            "form": "Formulario",
            "referral": "Referido",
            "website": "Sitio web",
            "event": "Evento",
            "partner": "Socio",
            "campaign": "Campaña",
            "other": "Otra",
        },
        "status": {
            "new": "Nuevo",
            "contacted": "Contactado",
            "qualified": "Calificado",
            "unqualified": "No calificado",
            "lost": "Perdido",
            "converted": "Convertido",
        },
    },
    "opportunities": {"priority": {"low": "Baja", "medium": "Media", "high": "Alta"}},
    "activities": {
        "type": {
            "call": "Llamada",
            "meeting": "Reunión",
            "email": "Correo",
            "task": "Tarea",
            "followup": "Seguimiento",
            "reminder": "Recordatorio",
        },
        "status": {"pending": "Pendiente", "done": "Hecha", "cancelled": "Cancelada"},
        "priority": {"low": "Baja", "medium": "Media", "high": "Alta"},
    },
    "quotes": {
        "status": {
            "draft": "Borrador",
            "sent": "Enviada",
            "accepted": "Aceptada",
            "rejected": "Rechazada",
            "expired": "Vencida",
        }
    },
}

LINE_FIELDS: list[dict[str, Any]] = [
    {
        "name": "product_id",
        "label": "Producto o servicio",
        "type": "choice",
        "options": True,
        "help": "Del catálogo; deja vacío para un concepto libre",
    },
    {
        "name": "description",
        "label": "Descripción",
        "type": "string",
        "help": "Si hay producto, por defecto su nombre",
    },
    {"name": "quantity", "label": "Cantidad", "type": "number", "default": 1},
    {
        "name": "unit_price",
        "label": "Precio unitario",
        "type": "number",
        "help": "Vacío = precio de lista del producto",
    },
    {"name": "discount_percent", "label": "Descuento (%)", "type": "number", "default": 0},
    {
        "name": "tax_rate_id",
        "label": "Impuesto",
        "type": "choice",
        "options": True,
        "help": "Vacío = el impuesto del producto, o ninguno",
    },
]

QUOTE_ACTIONS: list[dict[str, Any]] = [
    {
        "name": "add_line",
        "label": "Agregar concepto",
        "variant": "primary",
        "help": "Solo en borrador; los totales se recalculan en el servidor",
        "validate": True,
        "success": "show",
        "fields": LINE_FIELDS,
    },
    {
        "name": "send",
        "label": "Marcar como enviada",
        "confirm": "¿Marcar la cotización como enviada? Ya no podrá editarse.",
    },
    {
        "name": "accept",
        "label": "Registrar aceptación",
        "variant": "primary",
        "fields": [{"name": "notes", "label": "Notas de la aceptación", "type": "text"}],
    },
    {
        "name": "reject",
        "label": "Registrar rechazo",
        "variant": "destructive",
        "fields": [
            {"name": "notes", "label": "Motivo del rechazo", "type": "text", "required": True}
        ],
    },
    {"name": "new_version", "label": "Nueva versión", "secondary": True, "success": "open"},
    {
        "name": "remove",
        "label": "Eliminar borrador",
        "variant": "destructive",
        "secondary": True,
        "confirm": "¿Eliminar esta cotización? Solo se eliminan borradores.",
        "success": "open",
    },
    {
        "name": "recalculate",
        "label": "Recalcular totales",
        "secondary": True,
        "help": "Tras cambiar el descuento global en el formulario",
    },
]

QUOTE_LINE_ACTIONS: list[dict[str, Any]] = [
    {"name": "edit", "label": "Editar concepto", "variant": "primary", "fields": LINE_FIELDS},
    {
        "name": "remove",
        "label": "Quitar concepto",
        "variant": "destructive",
        "confirm": "¿Quitar este concepto?",
    },
]

COMPANY_FIELDS: list[dict[str, Any]] = [
    {"name": "name", "label": "Nombre comercial", "type": "string", "required": True},
    {"name": "legal_name", "label": "Razón social", "type": "string"},
    {
        "name": "tax_id_kind",
        "label": "Tipo de identificación fiscal",
        "type": "string",
        "help": "RFC, NIT, CUIT, VAT… según el país de la empresa",
    },
    {"name": "tax_id", "label": "Identificación fiscal", "type": "string"},
    {"name": "industry", "label": "Industria", "type": "string"},
    {
        "name": "kind",
        "label": "Tipo",
        "type": "choice",
        "default": "prospect",
        "choices": [
            {"value": k, "label": v} for k, v in CHOICE_LABELS["companies"]["kind"].items()
        ],
    },
    {
        "name": "status",
        "label": "Estado comercial",
        "type": "choice",
        "default": "prospect",
        "choices": [
            {"value": k, "label": v} for k, v in CHOICE_LABELS["companies"]["status"].items()
        ],
    },
    {"name": "email", "label": "Correo", "type": "string"},
    {"name": "phone", "label": "Teléfono", "type": "string"},
    {"name": "website", "label": "Sitio web", "type": "string"},
    {"name": "address", "label": "Dirección", "type": "string"},
    {"name": "city", "label": "Ciudad", "type": "string"},
    {"name": "region", "label": "Estado o región", "type": "string"},
    {"name": "postal_code", "label": "Código postal", "type": "string"},
    {"name": "country", "label": "País (ISO, p. ej. MX)", "type": "string"},
    {"name": "notes", "label": "Notas", "type": "text"},
]

COMPANY_ACTIONS: list[dict[str, Any]] = [
    {
        "name": "register",
        "label": "Nueva empresa",
        "scope": "collection",
        "variant": "primary",
        "permission": "crm.companies.write",
        "validate": True,
        "success": "open",
        "help": "Comprueba duplicados por nombre, identificación fiscal y correo",
        "fields": COMPANY_FIELDS,
    },
    {
        "name": "update_dedup",
        "label": "Corregir identificación",
        "secondary": True,
        "validate": True,
        "help": "Nombre, identificación fiscal y correo con la comprobación de duplicados",
        "fields": [
            {"name": "name", "label": "Nombre comercial", "type": "string"},
            {"name": "tax_id", "label": "Identificación fiscal", "type": "string"},
            {"name": "email", "label": "Correo", "type": "string"},
        ],
    },
]

CONTACT_ACTIONS: list[dict[str, Any]] = [
    {
        "name": "register",
        "label": "Nuevo contacto",
        "scope": "collection",
        "variant": "primary",
        "permission": "crm.contacts.write",
        "validate": True,
        "success": "open",
        "help": "Comprueba duplicados por correo y teléfonos antes de registrar",
        "fields": [
            {"name": "name", "label": "Nombre", "type": "string", "required": True},
            {"name": "company_id", "label": "Empresa", "type": "choice", "options": True},
            {"name": "job_title", "label": "Puesto", "type": "string"},
            {"name": "department", "label": "Departamento", "type": "string"},
            {
                "name": "kind",
                "label": "Clasificación",
                "type": "choice",
                "default": "other",
                "choices": [
                    {"value": k, "label": v} for k, v in CHOICE_LABELS["contacts"]["kind"].items()
                ],
            },
            {"name": "email", "label": "Correo", "type": "string"},
            {"name": "email_secondary", "label": "Correo secundario", "type": "string"},
            {"name": "phone", "label": "Teléfono", "type": "string"},
            {"name": "mobile", "label": "Móvil", "type": "string"},
            {"name": "responsibilities", "label": "Responsabilidades", "type": "text"},
            {"name": "notes", "label": "Notas", "type": "text"},
        ],
    },
    {
        "name": "link_company",
        "label": "Vincular con otra empresa",
        "help": "Una persona puede actuar por varias empresas; la principal es la de la ficha",
        "fields": [
            {
                "name": "company_id",
                "label": "Empresa",
                "type": "choice",
                "required": True,
                "options": True,
            },
            {"name": "role", "label": "Rol en esa empresa", "type": "string"},
            {
                "name": "is_primary",
                "label": "Hacerla la empresa principal",
                "type": "boolean",
                "default": False,
            },
        ],
    },
]

LEAD_ACTIONS: list[dict[str, Any]] = [
    {
        "name": "register",
        "label": "Nuevo prospecto",
        "scope": "collection",
        "variant": "primary",
        "permission": "crm.leads.write",
        "validate": True,
        "success": "open",
        "help": "Captura manual; si la persona o la empresa ya existen, elígelas para no duplicar",
        "fields": [
            {
                "name": "title",
                "label": "Título",
                "type": "string",
                "help": "Vacío = nombre de la persona o empresa",
            },
            {
                "name": "source",
                "label": "Fuente",
                "type": "choice",
                "default": "manual",
                "choices": [
                    {"value": k, "label": v} for k, v in CHOICE_LABELS["leads"]["source"].items()
                ],
            },
            {
                "name": "contact_id",
                "label": "Contacto existente",
                "type": "choice",
                "options": True,
            },
            {"name": "company_id", "label": "Empresa existente", "type": "choice", "options": True},
            {
                "name": "person_name",
                "label": "Nombre de la persona (si no existe)",
                "type": "string",
            },
            {"name": "company_name", "label": "Empresa (texto, si no existe)", "type": "string"},
            {"name": "email", "label": "Correo", "type": "string"},
            {"name": "phone", "label": "Teléfono", "type": "string"},
            {"name": "need", "label": "Necesidad identificada", "type": "text"},
            {"name": "estimated_value", "label": "Valor potencial", "type": "number", "default": 0},
            {"name": "currency", "label": "Moneda", "type": "string", "default": "MXN"},
            {"name": "notes", "label": "Notas", "type": "text"},
        ],
    },
    {
        "name": "mark_contacted",
        "label": "Marcar contactado",
        "confirm": "¿Registrar que ya se contactó al prospecto?",
    },
    {
        "name": "qualify",
        "label": "Calificar",
        "variant": "primary",
        "fields": [
            {"name": "qualified", "label": "Cumple el perfil", "type": "boolean", "default": True},
            {"name": "notes", "label": "Notas de calificación", "type": "text"},
        ],
    },
    {
        "name": "convert",
        "label": "Convertir en oportunidad",
        "variant": "primary",
        "validate": True,
        "success": "open",
        "help": "Crea la oportunidad en la primera etapa; reutiliza empresa y contacto existentes",
        "fields": [
            {
                "name": "name",
                "label": "Nombre de la oportunidad",
                "type": "string",
                "help": "Vacío = «Oportunidad de …»",
            },
            {
                "name": "amount",
                "label": "Valor estimado",
                "type": "number",
                "help": "Vacío = valor potencial del prospecto",
            },
            {"name": "currency", "label": "Moneda", "type": "string"},
            {
                "name": "pipeline_id",
                "label": "Pipeline",
                "type": "choice",
                "options": True,
                "help": "Vacío = pipeline predeterminado",
            },
            {"name": "expected_close_date", "label": "Cierre estimado", "type": "date"},
            {
                "name": "priority",
                "label": "Prioridad",
                "type": "choice",
                "default": "medium",
                "choices": [
                    {"value": k, "label": v}
                    for k, v in CHOICE_LABELS["opportunities"]["priority"].items()
                ],
            },
        ],
    },
    {
        "name": "mark_lost",
        "label": "Marcar perdido",
        "variant": "destructive",
        "secondary": True,
        "fields": [{"name": "notes", "label": "Motivo", "type": "text", "required": True}],
    },
]

CLOSING_ACTIONS: list[dict[str, Any]] = [
    {
        "name": "win",
        "label": "Marcar ganada",
        "variant": "primary",
        "permission": "crm.opportunities.write",
        "fields": [{"name": "notes", "label": "Nota", "type": "text"}],
    },
    {
        "name": "lose",
        "label": "Marcar perdida",
        "variant": "destructive",
        "permission": "crm.opportunities.write",
        "fields": [
            {
                "name": "lost_reason_id",
                "label": "Motivo de pérdida",
                "type": "choice",
                "options": True,
            },
            {"name": "notes", "label": "Detalle", "type": "text"},
        ],
    },
    {
        "name": "reopen",
        "label": "Reabrir",
        "secondary": True,
        "confirm": "¿Reabrir la oportunidad en su última etapa abierta?",
    },
]

ACTIVITY_ACTIONS: list[dict[str, Any]] = [
    {
        "name": "complete",
        "label": "Completar",
        "variant": "primary",
        "fields": [{"name": "outcome", "label": "Resultado", "type": "text"}],
    },
    {
        "name": "reschedule",
        "label": "Reprogramar",
        "fields": [{"name": "due_date", "label": "Nueva fecha", "type": "date", "required": True}],
    },
    {
        "name": "cancel",
        "label": "Cancelar",
        "variant": "destructive",
        "secondary": True,
        "fields": [{"name": "outcome", "label": "Motivo", "type": "text"}],
    },
]

OPPORTUNITY_ACTIONS: list[dict[str, Any]] = [
    {
        "name": "move",
        "label": "Mover de etapa",
        "permission": "crm.opportunities.write",
        "help": "Cambia la etapa; ganada o perdida cierran la oportunidad y quedan en el historial",
        "fields": [
            {
                "name": "stage_id",
                "label": "Etapa",
                "type": "choice",
                "required": True,
                "options": True,
                "help": "Etapas del pipeline de esta oportunidad",
            },
            {
                "name": "note",
                "label": "Nota",
                "type": "text",
                "help": "Opcional; queda en el historial de etapas",
            },
        ],
    },
]

STATUS_TONES = {"prospect": "info", "active": "success", "inactive": "neutral", "lost": "danger"}
KIND_TONES = {
    "customer": "success",
    "prospect": "info",
    "partner": "warning",
    "supplier": "neutral",
    "other": "neutral",
}
CONTACT_KIND_TONES = {
    "decision_maker": "success",
    "influencer": "info",
    "user": "neutral",
    "technical": "warning",
    "administrative": "neutral",
    "other": "neutral",
}
CONTACT_STATUS_TONES = {"active": "success", "inactive": "neutral"}
LEAD_STATUS_TONES = {
    "new": "info",
    "contacted": "info",
    "qualified": "success",
    "unqualified": "neutral",
    "lost": "danger",
    "converted": "success",
}
PRIORITY_TONES = {"low": "neutral", "medium": "info", "high": "danger"}
ACTIVITY_STATUS_TONES = {"pending": "warning", "done": "success", "cancelled": "neutral"}
ACTIVITY_TYPE_TONES = {
    "call": "info",
    "meeting": "info",
    "email": "neutral",
    "task": "neutral",
    "followup": "warning",
    "reminder": "warning",
}
QUOTE_STATUS_TONES = {
    "draft": "neutral",
    "sent": "info",
    "accepted": "success",
    "rejected": "danger",
    "expired": "warning",
}

LEAD_STAGES = {
    "field": "status",
    "steps": [
        {"label": "Nuevo", "values": ["new"]},
        {"label": "Contactado", "values": ["contacted"]},
        {"label": "Calificado", "values": ["qualified"]},
        {"label": "Convertido", "values": ["converted"]},
    ],
}
QUOTE_STAGES = {
    "field": "status",
    "steps": [
        {"label": "Borrador", "values": ["draft"]},
        {"label": "Enviada", "values": ["sent"]},
        {"label": "Aceptada", "values": ["accepted"]},
    ],
}


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


INTEGRATION_ACTIONS: list[dict[str, Any]] = [
    {
        "name": "create_project",
        "label": "Crear proyecto",
        "variant": "primary",
        "permission": "crm.opportunities.write",
        "validate": True,
        "success": "show",
        "help": "Solo ganadas: Proyectos crea el proyecto vinculado al cliente y a la oportunidad",
        "fields": [
            {"name": "code", "label": "Código del proyecto", "type": "string", "required": True},
            {
                "name": "name",
                "label": "Nombre",
                "type": "string",
                "help": "Vacío = nombre de la oportunidad",
            },
            {"name": "template_id", "label": "Plantilla", "type": "choice", "options": True},
            {"name": "start_date", "label": "Inicio", "type": "date"},
            {"name": "due_date", "label": "Conclusión estimada", "type": "date"},
            {
                "name": "use_amount_as_budget",
                "label": "Usar el valor como presupuesto",
                "type": "boolean",
                "default": True,
            },
        ],
    },
    {
        "name": "projects_summary",
        "label": "Ver proyectos",
        "secondary": True,
        "success": "show",
        "permission": "crm.opportunities.read",
        "help": "Resumen de los proyectos vinculados, consultado a Proyectos",
    },
]

COMPANY_PROJECTS_ACTION: dict[str, Any] = {
    "name": "projects_summary",
    "label": "Ver proyectos",
    "secondary": True,
    "success": "show",
    "permission": "crm.companies.read",
    "help": "Resumen de los proyectos del cliente, consultado a Proyectos",
}


def _status_action(resource: str, help_text: str) -> dict[str, Any]:
    """Record action the kanban runs on drop (§8j); also usable from the form."""
    return {
        "name": "set_status",
        "label": "Cambiar estado",
        "help": help_text,
        "fields": [
            {
                "name": "status",
                "label": "Estado",
                "type": "choice",
                "required": True,
                "choices": [
                    {"value": k, "label": v} for k, v in CHOICE_LABELS[resource]["status"].items()
                ],
            }
        ],
    }


LEAD_STATUS_ACTION = _status_action(
    "leads", "Nuevo → contactado → calificado; convertir solo por su acción"
)
ACTIVITY_STATUS_ACTION = _status_action(
    "activities", "Hecha completa, cancelada cancela, pendiente reabre"
)
QUOTE_STATUS_ACTION = _status_action("quotes", "Borrador → enviada → aceptada o rechazada")


OPPORTUNITY_ACTIONS.extend(CLOSING_ACTIONS)
OPPORTUNITY_ACTIONS.extend(INTEGRATION_ACTIONS)
COMPANY_ACTIONS.append(COMPANY_PROJECTS_ACTION)
LEAD_ACTIONS.append(LEAD_STATUS_ACTION)
ACTIVITY_ACTIONS.append(ACTIVITY_STATUS_ACTION)
QUOTE_ACTIONS.append(QUOTE_STATUS_ACTION)


def declare() -> None:
    if "icon" in NAV_KEYS:
        for model, icon in (
            (Company, "building"), (Contact, "contact"), (Opportunity, "bar-chart"),
            (Lead, "user-plus"), (Activity, "calendar"), (Quote, "file-text"),
            (Pipeline, "flow-linear"), (Stage, "layers"), (Tag, "tag"),
            (LostReason, "circle-x"), (Product, "package"), (TaxRate, "percent"),
        ):
            _merge(model, nav={"icon": icon})
    if _8J:
        for model in (Company, Contact, Lead, Opportunity, Activity, Quote):
            _merge(model, choices=CHOICE_LABELS[model.resource_name()])
    _merge(
        Company,
        actions=COMPANY_ACTIONS,
        list={
            "badges": {"status": STATUS_TONES, "kind": KIND_TONES},
            "counters": ["status", "kind"],
        },
        related=[
            _related(
                "contacts",
                "company_id",
                "Contactos",
                ["name", "job_title", "email", "phone", "kind"],
                "name",
            ),
            _related(
                "opportunities",
                "company_id",
                "Oportunidades",
                ["name", "stage_id", "amount", "currency", "expected_close_date", "owner_user_id"],
            ),
            _related(
                "activities",
                "company_id",
                "Actividades",
                ["title", "type", "status", "due_date", "assigned_user_id"],
                "due_date",
            ),
            _related(
                "quotes",
                "company_id",
                "Cotizaciones",
                ["number", "version", "status", "total", "currency", "valid_until"],
            ),
            _related(
                "leads",
                "company_id",
                "Prospectos",
                ["title", "status", "source", "estimated_value", "owner_user_id"],
            ),
        ],
        form={
            "tabs": [
                {"label": "Datos", "rows": Company.__novvus_views__["form"]["layout"]},
                {"label": "Contactos", "related": ["contacts"]},
                {"label": "Oportunidades", "related": ["opportunities", "leads"]},
                {"label": "Cotizaciones", "related": ["quotes"]},
                {"label": "Actividades", "related": ["activities"]},
                {"label": "Archivos y notas", "attachments": True, "chatter": True},
            ]
        },
    )
    _merge(
        Contact,
        actions=CONTACT_ACTIONS,
        list={
            "badges": {"kind": CONTACT_KIND_TONES, "status": CONTACT_STATUS_TONES},
            "counters": ["kind", "status"],
        },
        related=[
            _related(
                "contact_companies",
                "contact_id",
                "Otras empresas",
                ["company_id", "role", "is_primary"],
                "role",
            ),
            _related(
                "opportunities",
                "contact_id",
                "Oportunidades",
                ["name", "stage_id", "amount", "currency", "expected_close_date"],
            ),
            _related(
                "activities",
                "contact_id",
                "Actividades",
                ["title", "type", "status", "due_date", "assigned_user_id"],
                "due_date",
            ),
            _related(
                "quotes",
                "contact_id",
                "Cotizaciones",
                ["number", "version", "status", "total", "currency"],
            ),
        ],
        form={
            "tabs": [
                {"label": "Datos", "rows": Contact.__novvus_views__["form"]["layout"]},
                {"label": "Empresas", "related": ["contact_companies"]},
                {"label": "Oportunidades", "related": ["opportunities", "quotes"]},
                {"label": "Actividades", "related": ["activities"]},
                {"label": "Archivos y notas", "attachments": True, "chatter": True},
            ]
        },
    )
    _merge(
        Lead,
        **({"kanban": {"action": "set_status"}} if _8J else {}),
        actions=LEAD_ACTIONS,
        list={"badges": {"status": LEAD_STATUS_TONES}, "counters": ["status", "source"]},
        related=[
            _related(
                "activities",
                "lead_id",
                "Actividades",
                ["title", "type", "status", "due_date", "assigned_user_id"],
                "due_date",
            ),
        ],
        form={
            "stages": LEAD_STAGES,
            "tabs": [
                {"label": "Datos", "rows": Lead.__novvus_views__["form"]["layout"]},
                {"label": "Actividades", "related": ["activities"]},
                {"label": "Archivos y notas", "attachments": True, "chatter": True},
            ],
        },
    )
    _merge(
        Opportunity,
        actions=OPPORTUNITY_ACTIONS,
        **({"kanban": {"action": "move"}} if _8J else {}),
        **(
            {
                "dashboard": {
                    "path": "reports/dashboard",
                    "title": "Centro de control comercial",
                    "order": 10,
                }
            }
            if "dashboard" in VIEW_KEYS
            else {}
        ),
        list={"badges": {"priority": PRIORITY_TONES}, "counters": ["priority"]},
        related=[
            _related(
                "opportunity_lines",
                "opportunity_id",
                "Productos y servicios",
                ["product_id", "description", "quantity", "unit_price"],
                "created_at",
            ),
            _related(
                "activities",
                "opportunity_id",
                "Actividades",
                ["title", "type", "status", "due_date", "assigned_user_id"],
                "due_date",
            ),
            _related(
                "quotes",
                "opportunity_id",
                "Cotizaciones",
                ["number", "version", "status", "total", "currency", "valid_until"],
            ),
            _related(
                "opportunity_stage_logs",
                "opportunity_id",
                "Historial de etapas",
                ["created_at", "from_stage_id", "to_stage_id", "user_id", "note"],
            ),
        ],
        form={
            "tabs": [
                {"label": "Datos", "rows": Opportunity.__novvus_views__["form"]["layout"]},
                {"label": "Productos", "related": ["opportunity_lines"]},
                {"label": "Cotizaciones", "related": ["quotes"]},
                {"label": "Actividades", "related": ["activities"]},
                {"label": "Historial", "related": ["opportunity_stage_logs"]},
                {"label": "Archivos y notas", "attachments": True, "chatter": True},
            ]
        },
    )
    _merge(
        Activity,
        **({"kanban": {"action": "set_status"}} if _8J else {}),
        actions=ACTIVITY_ACTIONS,
        list={
            "badges": {
                "status": ACTIVITY_STATUS_TONES,
                "type": ACTIVITY_TYPE_TONES,
                "priority": PRIORITY_TONES,
            },
            "counters": ["status", "type"],
        },
    )
    _merge(QuoteLine, actions=QUOTE_LINE_ACTIONS)
    _merge(
        Quote,
        **({"kanban": {"action": "set_status"}} if _8J else {}),
        actions=QUOTE_ACTIONS,
        list={"badges": {"status": QUOTE_STATUS_TONES}, "counters": ["status"]},
        related=[
            _related(
                "quote_lines",
                "quote_id",
                "Conceptos",
                [
                    "position",
                    "product_id",
                    "description",
                    "quantity",
                    "unit_price",
                    "discount_percent",
                    "line_total",
                ],
                "position",
                100,
            ),
        ],
        form={
            "stages": QUOTE_STAGES,
            "tabs": [
                {"label": "Datos", "rows": Quote.__novvus_views__["form"]["layout"]},
                {"label": "Conceptos", "related": ["quote_lines"]},
                {"label": "Archivos y notas", "attachments": True, "chatter": True},
            ],
        },
    )
    _merge(Product, list={"counters": ["is_active"]})
    _merge(
        Pipeline,
        related=[
            _related(
                "stages",
                "pipeline_id",
                "Etapas",
                ["position", "name", "probability", "is_won", "is_lost"],
                "position",
            )
        ],
        form={
            "tabs": [
                {"label": "Datos", "rows": Pipeline.__novvus_views__["form"]["layout"]},
                {"label": "Etapas", "related": ["stages"]},
            ]
        },
    )

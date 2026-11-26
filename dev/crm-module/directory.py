"""Directory and funnel rules: companies, contacts, leads, opportunity closing
and activity completion, all as record/collection actions of the generic views.

Companies and contacts are registered through validated collection actions
(the generic create is disabled) so duplicates are caught in the server before
they exist: same fiscal id, same e-mail/phone, or the same normalised name.
Leads are captured, qualified and converted here; conversion reuses existing
companies/contacts instead of duplicating them.
"""

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from business import change_stage
from fastapi import HTTPException
from models import (
    Activity,
    ActivityStatus,
    Company,
    CompanyKind,
    CompanyStatus,
    Contact,
    ContactCompany,
    ContactKind,
    Lead,
    LeadStatus,
    LostReason,
    Opportunity,
    Pipeline,
    Priority,
    Stage,
)
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from novvus_sdk import NovvusModule


def norm(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _uuid(value: Any, field: str) -> UUID | None:
    if value in (None, ""):
        return None
    try:
        return UUID(str(value))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=f"{field} must be an id") from error


def _money(value: Any, field: str) -> Decimal:
    try:
        number = Decimal(str(value if value not in (None, "") else "0"))
    except InvalidOperation as error:
        raise HTTPException(status_code=422, detail=f"{field} must be a number") from error
    if number < 0:
        raise HTTPException(status_code=422, detail=f"{field} must not be negative")
    return number


def _enum(enum_cls: type, value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    try:
        return enum_cls(str(value))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=f"invalid value {value!r}") from error


async def _one(session: AsyncSession, model: type, item_id: UUID | None, name: str) -> Any:
    if item_id is None:
        return None
    row = await session.scalar(select(model).where(model.id == item_id, model.deleted_at.is_(None)))
    if row is None:
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return row


# ---------------------------------------------------------------------------
# Duplicate detection (shared by validators and handlers)
# ---------------------------------------------------------------------------


async def company_duplicates(
    session: AsyncSession, body: dict[str, Any], exclude: UUID | None = None
) -> dict[str, str]:
    errors: dict[str, str] = {}
    name = norm(body.get("name"))
    tax_id = norm(body.get("tax_id"))
    email = norm(body.get("email"))
    conditions = []
    if name:
        conditions.append(func.lower(Company.name) == name)
    if tax_id:
        conditions.append(func.lower(Company.tax_id) == tax_id)
    if email:
        conditions.append(func.lower(Company.email) == email)
    if not conditions:
        return errors
    query = select(Company).where(or_(*conditions), Company.deleted_at.is_(None))
    if exclude is not None:
        query = query.where(Company.id != exclude)
    for row in (await session.scalars(query)).all():
        if tax_id and norm(row.tax_id) == tax_id:
            errors["tax_id"] = f"Ya existe «{row.name}» con esta identificación fiscal"
        elif email and norm(row.email) == email:
            errors["email"] = f"Ya existe «{row.name}» con este correo"
        elif name and norm(row.name) == name:
            errors["name"] = f"Ya existe una empresa llamada «{row.name}»"
    return errors


async def contact_duplicates(
    session: AsyncSession, body: dict[str, Any], exclude: UUID | None = None
) -> dict[str, str]:
    errors: dict[str, str] = {}
    email = norm(body.get("email"))
    phones = {norm(body.get(k)).replace(" ", "") for k in ("phone", "mobile")} - {""}
    conditions = []
    if email:
        conditions.append(func.lower(Contact.email) == email)
    for phone in phones:
        conditions.append(func.replace(Contact.phone, " ", "") == phone)
        conditions.append(func.replace(Contact.mobile, " ", "") == phone)
    if not conditions:
        return errors
    query = select(Contact).where(or_(*conditions), Contact.deleted_at.is_(None))
    if exclude is not None:
        query = query.where(Contact.id != exclude)
    for row in (await session.scalars(query)).all():
        if email and norm(row.email) == email:
            errors["email"] = f"Ya existe «{row.name}» con este correo"
        else:
            errors["phone"] = f"Ya existe «{row.name}» con este teléfono"
    return errors


async def find_company(session: AsyncSession, name: str) -> Company | None:
    if not norm(name):
        return None
    return await session.scalar(
        select(Company).where(func.lower(Company.name) == norm(name), Company.deleted_at.is_(None))
    )


async def find_contact(session: AsyncSession, email: str, name: str) -> Contact | None:
    if norm(email):
        found = await session.scalar(
            select(Contact).where(
                func.lower(Contact.email) == norm(email), Contact.deleted_at.is_(None)
            )
        )
        if found is not None:
            return found
    if norm(name):
        return await session.scalar(
            select(Contact).where(
                func.lower(Contact.name) == norm(name), Contact.deleted_at.is_(None)
            )
        )
    return None


# ---------------------------------------------------------------------------
# Option providers
# ---------------------------------------------------------------------------


async def company_options(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(Company).where(Company.deleted_at.is_(None)).order_by(Company.name).limit(200)
        )
    ).all()
    return [{"value": "", "label": "—"}] + [
        {"value": str(c.id), "label": c.name, "description": c.industry or c.legal_name}
        for c in rows
    ]


async def contact_options(
    session: AsyncSession, company_id: UUID | None = None
) -> list[dict[str, Any]]:
    query = select(Contact).where(Contact.deleted_at.is_(None)).order_by(Contact.name).limit(200)
    if company_id is not None:
        query = query.where(Contact.company_id == company_id)
    rows = (await session.scalars(query)).all()
    return [{"value": "", "label": "—"}] + [
        {"value": str(c.id), "label": c.name, "description": c.email or c.job_title} for c in rows
    ]


async def pipeline_options(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(Pipeline).where(Pipeline.deleted_at.is_(None)).order_by(Pipeline.name)
        )
    ).all()
    return [
        {
            "value": str(p.id),
            "label": p.name,
            "description": "predeterminado" if p.is_default else "",
        }
        for p in rows
    ]


async def lost_reason_options(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(LostReason)
            .where(LostReason.is_active.is_(True), LostReason.deleted_at.is_(None))
            .order_by(LostReason.name)
        )
    ).all()
    return [{"value": "", "label": "—"}] + [{"value": str(r.id), "label": r.name} for r in rows]


# ---------------------------------------------------------------------------
# Conversion (shared by the endpoint in business.py and the action)
# ---------------------------------------------------------------------------


async def convert_lead(
    module: NovvusModule,
    session: AsyncSession,
    lead: Lead,
    *,
    name: str | None,
    amount: Decimal,
    currency: str,
    pipeline_id: UUID | None,
    expected_close_date: date | None,
    priority: Priority,
    org_id: UUID,
    user_id: UUID | None,
) -> Opportunity:
    if lead.status == LeadStatus.converted:
        raise HTTPException(status_code=409, detail="lead is already converted")
    if lead.status in (LeadStatus.lost, LeadStatus.unqualified):
        raise HTTPException(
            status_code=409, detail="a lost or unqualified lead cannot be converted"
        )

    if pipeline_id is not None:
        pipeline = await _one(session, Pipeline, pipeline_id, "pipeline")
    else:
        pipeline = await session.scalar(
            select(Pipeline).where(Pipeline.is_default, Pipeline.deleted_at.is_(None))
        )
        if pipeline is None:
            raise HTTPException(
                status_code=422,
                detail="no default pipeline; pass pipeline_id or mark one as default",
            )
    first_stage = await session.scalar(
        select(Stage)
        .where(
            Stage.pipeline_id == pipeline.id,
            Stage.is_won.is_(False),
            Stage.is_lost.is_(False),
            Stage.deleted_at.is_(None),
        )
        .order_by(Stage.position)
        .limit(1)
    )
    if first_stage is None:
        raise HTTPException(status_code=422, detail="pipeline has no open stages")

    # Reuse the directory: the captured company/person become records only if they do not exist.
    company = await _one(session, Company, lead.company_id, "company")
    if company is None and lead.company_name:
        company = await find_company(session, lead.company_name)
        if company is None:
            company = Company(
                org_id=org_id,
                name=lead.company_name.strip(),
                kind=CompanyKind.prospect,
                status=CompanyStatus.prospect,
                owner_user_id=lead.owner_user_id,
            )
            session.add(company)
            await session.flush()
        lead.company_id = company.id
    contact = await _one(session, Contact, lead.contact_id, "contact")
    if contact is None and (lead.person_name or lead.email):
        contact = await find_contact(session, lead.email, lead.person_name)
        if contact is None:
            contact = Contact(
                org_id=org_id,
                name=(lead.person_name or lead.email).strip(),
                email=lead.email,
                phone=lead.phone,
                company_id=company.id if company else None,
                owner_user_id=lead.owner_user_id,
            )
            session.add(contact)
            await session.flush()
        lead.contact_id = contact.id

    if not name:
        related = contact or company
        name = (
            module._("Oportunidad de {name}").format(name=related.name)
            if related
            else (lead.title or module._("Oportunidad de lead"))
        )
    opportunity = Opportunity(
        org_id=org_id,
        name=name,
        description=lead.need,
        amount=amount or lead.estimated_value,
        currency=currency or lead.currency,
        pipeline_id=pipeline.id,
        stage_id=first_stage.id,
        expected_close_date=expected_close_date,
        owner_user_id=lead.owner_user_id or user_id,
        contact_id=contact.id if contact else None,
        company_id=company.id if company else None,
        priority=priority,
    )
    session.add(opportunity)
    await session.flush()
    lead.status = LeadStatus.converted
    lead.converted_opportunity_id = opportunity.id
    await session.flush()
    await session.refresh(opportunity)
    await module.emit(
        "crm.lead.converted",
        {"lead_id": str(lead.id), "opportunity_id": str(opportunity.id)},
    )
    return opportunity


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


COMPANY_TEXT = (
    "legal_name",
    "tax_id_kind",
    "tax_id",
    "industry",
    "email",
    "phone",
    "website",
    "address",
    "city",
    "region",
    "postal_code",
    "notes",
)
CONTACT_TEXT = (
    "email",
    "email_secondary",
    "phone",
    "mobile",
    "job_title",
    "department",
    "responsibilities",
    "notes",
)


def register(module: NovvusModule) -> None:
    # ---- companies ---------------------------------------------------------
    @module.action(Company, "register")
    async def register_company(
        session: AsyncSession, ctx: Any, _record: Any, body: dict[str, Any]
    ) -> dict[str, Any]:
        errors = await company_duplicates(session, body)
        if errors:
            raise HTTPException(status_code=422, detail=errors)
        company = Company(
            org_id=ctx.org_id,
            name=str(body["name"]).strip(),
            country=str(body.get("country") or "").strip().upper()[:2],
            kind=_enum(CompanyKind, body.get("kind"), CompanyKind.prospect),
            status=_enum(CompanyStatus, body.get("status"), CompanyStatus.prospect),
            owner_user_id=ctx.user_id,
            **{k: str(body.get(k) or "").strip() for k in COMPANY_TEXT},
        )
        session.add(company)
        await session.flush()
        return {
            "message": module._("Empresa registrada"),
            "record": {"model": "companies", "id": str(company.id)},
        }

    @module.action_validator(Company, "register")
    async def register_company_validate(
        session: AsyncSession, ctx: Any, _record: Any, body: dict[str, Any]
    ) -> dict[str, str]:
        return await company_duplicates(session, body)

    @module.action(Company, "update_dedup")
    async def update_company(
        session: AsyncSession, ctx: Any, company: Company, body: dict[str, Any]
    ) -> dict[str, Any]:
        """Edit the identifying fields with the same duplicate rules as registration."""
        merged = {
            "name": body.get("name") or company.name,
            "tax_id": body.get("tax_id", company.tax_id),
            "email": body.get("email", company.email),
        }
        errors = await company_duplicates(session, merged, exclude=company.id)
        if errors:
            raise HTTPException(status_code=422, detail=errors)
        company.name = str(merged["name"]).strip()
        company.tax_id = str(merged["tax_id"] or "").strip()
        company.email = str(merged["email"] or "").strip()
        await session.flush()
        return {"message": module._("Empresa actualizada")}

    @module.action_validator(Company, "update_dedup")
    async def update_company_validate(
        session: AsyncSession, ctx: Any, company: Company, body: dict[str, Any]
    ) -> dict[str, str]:
        merged = {
            "name": body.get("name") or company.name,
            "tax_id": body.get("tax_id", company.tax_id),
            "email": body.get("email", company.email),
        }
        return await company_duplicates(session, merged, exclude=company.id)

    # ---- contacts ----------------------------------------------------------
    @module.action(Contact, "register")
    async def register_contact(
        session: AsyncSession, ctx: Any, _record: Any, body: dict[str, Any]
    ) -> dict[str, Any]:
        errors = await contact_duplicates(session, body)
        if errors:
            raise HTTPException(status_code=422, detail=errors)
        company_id = _uuid(body.get("company_id"), "company_id")
        await _one(session, Company, company_id, "company")
        contact = Contact(
            org_id=ctx.org_id,
            name=str(body["name"]).strip(),
            kind=_enum(ContactKind, body.get("kind"), ContactKind.other),
            company_id=company_id,
            owner_user_id=ctx.user_id,
            **{k: str(body.get(k) or "").strip() for k in CONTACT_TEXT},
        )
        session.add(contact)
        await session.flush()
        if company_id is not None:
            session.add(
                ContactCompany(
                    org_id=ctx.org_id,
                    contact_id=contact.id,
                    company_id=company_id,
                    role=contact.job_title,
                    is_primary=True,
                )
            )
            await session.flush()
        return {
            "message": module._("Contacto registrado"),
            "record": {"model": "contacts", "id": str(contact.id)},
        }

    @module.action_validator(Contact, "register")
    async def register_contact_validate(
        session: AsyncSession, ctx: Any, _record: Any, body: dict[str, Any]
    ) -> dict[str, str]:
        return await contact_duplicates(session, body)

    @module.action_options(Contact, "register")
    async def register_contact_options(
        session: AsyncSession, ctx: Any, _record: Any, body: dict[str, Any]
    ) -> dict[str, Any]:
        return {"company_id": await company_options(session)}

    @module.action(Contact, "link_company")
    async def link_company(
        session: AsyncSession, ctx: Any, contact: Contact, body: dict[str, Any]
    ) -> dict[str, Any]:
        company_id = _uuid(body.get("company_id"), "company_id")
        if company_id is None:
            raise HTTPException(status_code=422, detail={"company_id": "Elige una empresa"})
        company = await _one(session, Company, company_id, "company")
        existing = await session.scalar(
            select(ContactCompany).where(
                ContactCompany.contact_id == contact.id, ContactCompany.company_id == company.id
            )
        )
        if existing is None:
            existing = ContactCompany(
                org_id=ctx.org_id, contact_id=contact.id, company_id=company.id
            )
            session.add(existing)
        existing.role = str(body.get("role") or existing.role or "")[:120]
        existing.is_primary = bool(body.get("is_primary"))
        if existing.is_primary:
            contact.company_id = company.id
        await session.flush()
        return {
            "message": module._("Contacto vinculado con {company}").format(company=company.name)
        }

    @module.action_options(Contact, "link_company")
    async def link_company_options(
        session: AsyncSession, ctx: Any, contact: Contact, body: dict[str, Any]
    ) -> dict[str, Any]:
        return {"company_id": await company_options(session)}

    # ---- leads -------------------------------------------------------------
    @module.action(Lead, "register")
    async def register_lead(
        session: AsyncSession, ctx: Any, _record: Any, body: dict[str, Any]
    ) -> dict[str, Any]:
        contact_id = _uuid(body.get("contact_id"), "contact_id")
        company_id = _uuid(body.get("company_id"), "company_id")
        contact = await _one(session, Contact, contact_id, "contact")
        company = await _one(session, Company, company_id, "company")
        if contact is not None and company is None and contact.company_id is not None:
            company_id = contact.company_id
        lead = Lead(
            org_id=ctx.org_id,
            title=str(body.get("title") or "").strip()
            or (
                contact.name
                if contact
                else str(body.get("person_name") or body.get("company_name") or "Prospecto")
            ),
            source=_enum(
                type(Lead.source.default.arg), body.get("source"), Lead.source.default.arg
            ),
            person_name=str(body.get("person_name") or "").strip(),
            company_name=str(body.get("company_name") or "").strip(),
            email=str(body.get("email") or "").strip(),
            phone=str(body.get("phone") or "").strip(),
            contact_id=contact_id,
            company_id=company_id,
            owner_user_id=ctx.user_id,
            need=str(body.get("need") or "").strip(),
            estimated_value=_money(body.get("estimated_value"), "estimated_value"),
            currency=str(body.get("currency") or "MXN").upper()[:3],
            notes=str(body.get("notes") or "").strip(),
        )
        session.add(lead)
        await session.flush()
        await module.emit(
            "crm.lead.created", {"lead_id": str(lead.id), "source": lead.source.value}
        )
        return {
            "message": module._("Prospecto registrado"),
            "record": {"model": "leads", "id": str(lead.id)},
        }

    @module.action_validator(Lead, "register")
    async def register_lead_validate(
        session: AsyncSession, ctx: Any, _record: Any, body: dict[str, Any]
    ) -> dict[str, str]:
        """Not an error to capture someone already known, but point at the record to reuse."""
        errors: dict[str, str] = {}
        if not body.get("contact_id") and body.get("email"):
            known = await find_contact(session, str(body["email"]), "")
            if known is not None:
                errors["email"] = f"«{known.name}» ya es contacto: elígelo en el campo Contacto"
        if not body.get("company_id") and body.get("company_name"):
            known_company = await find_company(session, str(body["company_name"]))
            if known_company is not None:
                errors["company_name"] = (
                    f"«{known_company.name}» ya existe: elígela en el campo Empresa"
                )
        try:
            _money(body.get("estimated_value"), "estimated_value")
        except HTTPException as error:
            errors["estimated_value"] = str(error.detail)
        return errors

    @module.action_options(Lead, "register")
    async def register_lead_options(
        session: AsyncSession, ctx: Any, _record: Any, body: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "contact_id": await contact_options(session),
            "company_id": await company_options(session),
        }

    @module.action(Lead, "qualify")
    async def qualify(
        session: AsyncSession, ctx: Any, lead: Lead, body: dict[str, Any]
    ) -> dict[str, Any]:
        if lead.status in (LeadStatus.converted, LeadStatus.lost):
            raise HTTPException(status_code=409, detail="the lead is already closed")
        lead.status = (
            LeadStatus.qualified
            if body.get("qualified", True) is not False
            else LeadStatus.unqualified
        )
        if body.get("notes"):
            lead.notes = (lead.notes + "\n" if lead.notes else "") + str(body["notes"])
        await session.flush()
        return {
            "message": module._("Prospecto calificado")
            if lead.status == LeadStatus.qualified
            else module._("Prospecto descartado")
        }

    @module.action(Lead, "mark_contacted")
    async def mark_contacted(
        session: AsyncSession, ctx: Any, lead: Lead, body: dict[str, Any]
    ) -> dict[str, Any]:
        if lead.status != LeadStatus.new:
            raise HTTPException(status_code=409, detail="only a new lead becomes contacted")
        lead.status = LeadStatus.contacted
        await session.flush()
        return {"message": module._("Prospecto marcado como contactado")}

    @module.action(Lead, "mark_lost")
    async def mark_lost(
        session: AsyncSession, ctx: Any, lead: Lead, body: dict[str, Any]
    ) -> dict[str, Any]:
        if lead.status == LeadStatus.converted:
            raise HTTPException(status_code=409, detail="a converted lead cannot be lost")
        lead.status = LeadStatus.lost
        lead.notes = (lead.notes + "\n" if lead.notes else "") + str(body.get("notes") or "")
        await session.flush()
        return {"message": module._("Prospecto perdido")}

    @module.action(Lead, "convert")
    async def convert(
        session: AsyncSession, ctx: Any, lead: Lead, body: dict[str, Any]
    ) -> dict[str, Any]:
        close = body.get("expected_close_date")
        opportunity = await convert_lead(
            module,
            session,
            lead,
            name=str(body.get("name") or "").strip() or None,
            amount=_money(body.get("amount"), "amount"),
            currency=str(body.get("currency") or "").upper()[:3],
            pipeline_id=_uuid(body.get("pipeline_id"), "pipeline_id"),
            expected_close_date=date.fromisoformat(str(close)) if close else None,
            priority=_enum(Priority, body.get("priority"), Priority.medium),
            org_id=ctx.org_id,
            user_id=ctx.user_id,
        )
        return {
            "message": module._("Oportunidad «{name}» creada").format(name=opportunity.name),
            "record": {"model": "opportunities", "id": str(opportunity.id)},
        }

    @module.action_validator(Lead, "convert")
    async def convert_validate(
        session: AsyncSession, ctx: Any, lead: Lead, body: dict[str, Any]
    ) -> dict[str, str]:
        errors: dict[str, str] = {}
        if lead.status == LeadStatus.converted:
            errors["name"] = "Este prospecto ya fue convertido"
        elif lead.status in (LeadStatus.lost, LeadStatus.unqualified):
            errors["name"] = "Un prospecto perdido o descartado no se convierte"
        try:
            _money(body.get("amount"), "amount")
        except HTTPException as error:
            errors["amount"] = str(error.detail)
        if not body.get("pipeline_id"):
            default = await session.scalar(
                select(Pipeline).where(Pipeline.is_default, Pipeline.deleted_at.is_(None))
            )
            if default is None:
                errors["pipeline_id"] = "No hay pipeline predeterminado: elige uno"
        return errors

    @module.action_options(Lead, "convert")
    async def convert_options(
        session: AsyncSession, ctx: Any, lead: Lead, body: dict[str, Any]
    ) -> dict[str, Any]:
        return {"pipeline_id": await pipeline_options(session)}

    @module.action(Lead, "set_status")
    async def lead_set_status(
        session: AsyncSession, ctx: Any, lead: Lead, body: dict[str, Any]
    ) -> dict[str, Any]:
        """Kanban drops on the lead board: every column change obeys the funnel rules."""
        target = _enum(LeadStatus, body.get("status"), lead.status)
        if target == lead.status:
            return {"message": module._("Sin cambios")}
        if lead.status == LeadStatus.converted:
            raise HTTPException(status_code=409, detail="a converted lead does not change")
        if target == LeadStatus.converted:
            raise HTTPException(
                status_code=409, detail="use «Convertir en oportunidad» to convert a lead"
            )
        if target == LeadStatus.contacted and lead.status != LeadStatus.new:
            raise HTTPException(status_code=409, detail="only a new lead becomes contacted")
        lead.status = target
        await session.flush()
        return {"message": module._("Prospecto {status}").format(status=target.value)}

    @module.action(Activity, "set_status")
    async def activity_set_status(
        session: AsyncSession, ctx: Any, activity: Activity, body: dict[str, Any]
    ) -> dict[str, Any]:
        """Kanban drops on the activity board: done completes, cancelled cancels, pending
        reopens."""
        target = _enum(ActivityStatus, body.get("status"), activity.status)
        if target == activity.status:
            return {"message": module._("Sin cambios")}
        if target == ActivityStatus.done:
            return await complete(session, ctx, activity, body)
        if target == ActivityStatus.cancelled:
            return await cancel(session, ctx, activity, body)
        activity.status = ActivityStatus.pending
        activity.completed_at = None
        await session.flush()
        return {"message": module._("Actividad pendiente de nuevo")}

    # ---- opportunities: closing --------------------------------------------
    async def _closing_stage(session: AsyncSession, opportunity: Opportunity, won: bool) -> Stage:
        flag = Stage.is_won if won else Stage.is_lost
        stage = await session.scalar(
            select(Stage)
            .where(
                Stage.pipeline_id == opportunity.pipeline_id,
                flag.is_(True),
                Stage.deleted_at.is_(None),
            )
            .order_by(Stage.position)
            .limit(1)
        )
        if stage is None:
            raise HTTPException(
                status_code=422, detail="the pipeline has no closing stage of that kind"
            )
        return stage

    @module.action(Opportunity, "win")
    async def win(
        session: AsyncSession, ctx: Any, opportunity: Opportunity, body: dict[str, Any]
    ) -> dict[str, Any]:
        if opportunity.is_won is not None:
            raise HTTPException(status_code=409, detail="the opportunity is already closed")
        stage = await _closing_stage(session, opportunity, won=True)
        await change_stage(module, session, opportunity, stage, note=str(body.get("notes") or ""))
        return {"message": module._("Oportunidad ganada")}

    @module.action(Opportunity, "lose")
    async def lose(
        session: AsyncSession, ctx: Any, opportunity: Opportunity, body: dict[str, Any]
    ) -> dict[str, Any]:
        if opportunity.is_won is not None:
            raise HTTPException(status_code=409, detail="the opportunity is already closed")
        reason = await _one(
            session, LostReason, _uuid(body.get("lost_reason_id"), "lost_reason_id"), "lost reason"
        )
        stage = await _closing_stage(session, opportunity, won=False)
        opportunity.lost_reason_id = reason.id if reason else None
        opportunity.lost_notes = str(body.get("notes") or "")[:2000]
        await change_stage(module, session, opportunity, stage, note=reason.name if reason else "")
        return {"message": module._("Oportunidad perdida")}

    @module.action_options(Opportunity, "lose")
    async def lose_options(
        session: AsyncSession, ctx: Any, opportunity: Opportunity, body: dict[str, Any]
    ) -> dict[str, Any]:
        return {"lost_reason_id": await lost_reason_options(session)}

    @module.action(Opportunity, "reopen")
    async def reopen(
        session: AsyncSession, ctx: Any, opportunity: Opportunity, body: dict[str, Any]
    ) -> dict[str, Any]:
        if opportunity.is_won is None:
            raise HTTPException(status_code=409, detail="the opportunity is open")
        stage = await session.scalar(
            select(Stage)
            .where(
                Stage.pipeline_id == opportunity.pipeline_id,
                Stage.is_won.is_(False),
                Stage.is_lost.is_(False),
                Stage.deleted_at.is_(None),
            )
            .order_by(Stage.position.desc())
            .limit(1)
        )
        if stage is None:
            raise HTTPException(status_code=422, detail="pipeline has no open stages")
        opportunity.lost_reason_id = None
        opportunity.lost_notes = ""
        await change_stage(
            module, session, opportunity, stage, note=str(body.get("notes") or "reabierta")
        )
        return {"message": module._("Oportunidad reabierta")}

    # ---- activities ----------------------------------------------------------
    @module.action(Activity, "complete")
    async def complete(
        session: AsyncSession, ctx: Any, activity: Activity, body: dict[str, Any]
    ) -> dict[str, Any]:
        if activity.status == ActivityStatus.done:
            raise HTTPException(status_code=409, detail="the activity is already done")
        activity.status = ActivityStatus.done
        activity.completed_at = datetime.now(tz=UTC)
        activity.outcome = str(body.get("outcome") or "")[:2000]
        if activity.opportunity_id is not None:
            opportunity = await session.scalar(
                select(Opportunity).where(Opportunity.id == activity.opportunity_id)
            )
            if opportunity is not None:
                opportunity.last_activity_at = activity.completed_at
        await session.flush()
        await module.emit(
            "crm.activity.completed", {"activity_id": str(activity.id), "type": activity.type.value}
        )
        return {"message": module._("Actividad completada")}

    @module.action(Activity, "cancel")
    async def cancel(
        session: AsyncSession, ctx: Any, activity: Activity, body: dict[str, Any]
    ) -> dict[str, Any]:
        if activity.status != ActivityStatus.pending:
            raise HTTPException(status_code=409, detail="only a pending activity can be cancelled")
        activity.status = ActivityStatus.cancelled
        activity.outcome = str(body.get("outcome") or "")[:2000]
        await session.flush()
        return {"message": module._("Actividad cancelada")}

    @module.action(Activity, "reschedule")
    async def reschedule(
        session: AsyncSession, ctx: Any, activity: Activity, body: dict[str, Any]
    ) -> dict[str, Any]:
        if activity.status != ActivityStatus.pending:
            raise HTTPException(
                status_code=409, detail="only a pending activity can be rescheduled"
            )
        due = body.get("due_date")
        if not due:
            raise HTTPException(status_code=422, detail={"due_date": "Indica la nueva fecha"})
        activity.due_date = datetime.combine(date.fromisoformat(str(due)), datetime.min.time())
        await session.flush()
        return {"message": module._("Actividad reprogramada")}

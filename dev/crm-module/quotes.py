"""Quotes: server-side arithmetic, versions and the sent/accepted/rejected cycle.

Lines are never written through the generic CRUD (create/update/delete are
disabled on `quote_lines`): they enter through the quote's actions so every
change recomputes the totals in the same transaction. Formulas (documented in
modules/crm/README.md):

    line_gross      = quantity x unit_price
    line_subtotal   = round(line_gross x (1 - line_discount / 100), 2)
    discounted      = line_subtotal x (1 - quote_discount / 100)
    line_tax        = round(discounted x tax_rate / 100, 2)
    line_total      = round(discounted, 2) + line_tax
    quote.subtotal       = Σ line_subtotal
    quote.discount_total = Σ (line_gross - line_subtotal)
                           + round(subtotal x quote_discount / 100, 2)
    quote.tax_total      = Σ line_tax
    quote.total          = Σ line_total

Tax rates are snapshotted on the line (`tax_rate`) so later catalog changes
never rewrite an issued quote.
"""

from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from models import Product, Quote, QuoteLine, QuoteStatus, TaxRate
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from novvus_sdk import NovvusModule, current_context

CENT = Decimal("0.01")
MAX_PERCENT = Decimal("100")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _decimal(
    value: Any, field: str, *, minimum: Decimal | None = None, maximum: Decimal | None = None
) -> Decimal:
    try:
        number = Decimal(str(value if value not in (None, "") else "0"))
    except InvalidOperation as error:
        raise HTTPException(status_code=422, detail=f"{field} must be a number") from error
    if minimum is not None and number < minimum:
        raise HTTPException(status_code=422, detail=f"{field} must be at least {minimum}")
    if maximum is not None and number > maximum:
        raise HTTPException(status_code=422, detail=f"{field} must be at most {maximum}")
    return number


def compute_line(line: QuoteLine, quote_discount: Decimal) -> None:
    gross = line.quantity * line.unit_price
    line.line_subtotal = money(gross * (MAX_PERCENT - line.discount_percent) / MAX_PERCENT)
    discounted = line.line_subtotal * (MAX_PERCENT - quote_discount) / MAX_PERCENT
    line.line_tax = money(discounted * line.tax_rate / MAX_PERCENT)
    line.line_total = money(discounted) + line.line_tax


def compute_quote(quote: Quote, lines: list[QuoteLine]) -> None:
    discount = quote.discount_percent or Decimal("0")
    subtotal = Decimal("0")
    line_discounts = Decimal("0")
    tax_total = Decimal("0")
    total = Decimal("0")
    for line in lines:
        compute_line(line, discount)
        subtotal += line.line_subtotal
        line_discounts += money(line.quantity * line.unit_price) - line.line_subtotal
        tax_total += line.line_tax
        total += line.line_total
    quote.subtotal = money(subtotal)
    quote.discount_total = money(line_discounts + money(subtotal * discount / MAX_PERCENT))
    quote.tax_total = money(tax_total)
    quote.total = money(total)


async def _lines(session: AsyncSession, quote_id: UUID) -> list[QuoteLine]:
    return list(
        (
            await session.scalars(
                select(QuoteLine)
                .where(QuoteLine.quote_id == quote_id, QuoteLine.deleted_at.is_(None))
                .order_by(QuoteLine.position, QuoteLine.created_at)
            )
        ).all()
    )


async def recompute(session: AsyncSession, quote: Quote) -> None:
    compute_quote(quote, await _lines(session, quote.id))
    await session.flush()


def _editable(quote: Quote) -> None:
    if quote.status != QuoteStatus.draft:
        raise HTTPException(
            status_code=409, detail="only a draft quote can change; create a new version"
        )


async def _tax(session: AsyncSession, tax_rate_id: Any, fallback: TaxRate | None) -> TaxRate | None:
    if tax_rate_id in (None, ""):
        return fallback
    try:
        wanted = UUID(str(tax_rate_id))
    except ValueError as error:
        raise HTTPException(status_code=422, detail="tax_rate_id must be a tax rate") from error
    rate = await session.scalar(
        select(TaxRate).where(TaxRate.id == wanted, TaxRate.deleted_at.is_(None))
    )
    if rate is None:
        raise HTTPException(status_code=404, detail="tax rate not found")
    return rate


async def _apply_line_body(session: AsyncSession, line: QuoteLine, body: dict[str, Any]) -> None:
    """Shared by «Agregar concepto» and «Editar concepto»: product defaults, then explicit
    values."""
    product: Product | None = None
    if body.get("product_id"):
        try:
            product_id = UUID(str(body["product_id"]))
        except ValueError as error:
            raise HTTPException(status_code=422, detail="product_id must be a product") from error
        product = await session.scalar(
            select(Product).where(Product.id == product_id, Product.deleted_at.is_(None))
        )
        if product is None:
            raise HTTPException(status_code=404, detail="product not found")
        line.product_id = product.id
        if not body.get("description"):
            line.description = product.name
        if body.get("unit_price") in (None, ""):
            line.unit_price = product.list_price
    if body.get("description"):
        line.description = str(body["description"])[:500]
    if not line.description:
        raise HTTPException(status_code=422, detail="description is required without a product")
    if "quantity" in body and body["quantity"] not in (None, ""):
        line.quantity = _decimal(body["quantity"], "quantity", minimum=Decimal("0.001"))
    if "unit_price" in body and body["unit_price"] not in (None, ""):
        line.unit_price = _decimal(body["unit_price"], "unit_price", minimum=Decimal("0"))
    if "discount_percent" in body and body["discount_percent"] not in (None, ""):
        line.discount_percent = _decimal(
            body["discount_percent"], "discount_percent", minimum=Decimal("0"), maximum=MAX_PERCENT
        )
    default_tax = None
    if product is not None and product.tax_rate_id is not None:
        default_tax = await session.scalar(select(TaxRate).where(TaxRate.id == product.tax_rate_id))
    rate = await _tax(session, body.get("tax_rate_id"), default_tax)
    if rate is not None:
        line.tax_rate_id = rate.id
        line.tax_rate = rate.rate
    elif body.get("tax_rate_id") == "" or (product is None and "tax_rate_id" in body):
        line.tax_rate_id = None
        line.tax_rate = Decimal("0")


async def _product_options(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(Product)
            .where(Product.is_active.is_(True), Product.deleted_at.is_(None))
            .order_by(Product.name)
        )
    ).all()
    return [
        {
            "value": str(p.id),
            "label": f"{p.sku} · {p.name}",
            "description": f"{p.list_price} {p.currency} por {p.unit}",
        }
        for p in rows
    ]


async def _tax_options(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(TaxRate)
            .where(TaxRate.is_active.is_(True), TaxRate.deleted_at.is_(None))
            .order_by(TaxRate.name)
        )
    ).all()
    return [{"value": "", "label": "Sin impuesto"}] + [
        {"value": str(t.id), "label": f"{t.name} ({t.rate} %)"} for t in rows
    ]


def register(module: NovvusModule) -> None:
    @module.action(Quote, "add_line")
    async def add_line(
        session: AsyncSession, ctx: Any, quote: Quote, body: dict[str, Any]
    ) -> dict[str, Any]:
        _editable(quote)
        position = await session.scalar(
            select(func.coalesce(func.max(QuoteLine.position), 0)).where(
                QuoteLine.quote_id == quote.id
            )
        )
        line = QuoteLine(org_id=ctx.org_id, quote_id=quote.id, position=int(position or 0) + 1)
        await _apply_line_body(session, line, body)
        session.add(line)
        await session.flush()
        await recompute(session, quote)
        return {
            "message": module._("Concepto agregado; total {total} {currency}").format(
                total=quote.total, currency=quote.currency
            )
        }

    @module.action_options(Quote, "add_line")
    async def add_line_options(
        session: AsyncSession, ctx: Any, quote: Quote, body: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "product_id": await _product_options(session),
            "tax_rate_id": await _tax_options(session),
        }

    @module.action_validator(Quote, "add_line")
    async def add_line_validate(
        session: AsyncSession, ctx: Any, quote: Quote, body: dict[str, Any]
    ) -> dict[str, str]:
        errors: dict[str, str] = {}
        if quote.status != QuoteStatus.draft:
            errors["description"] = "Solo un borrador admite conceptos; crea una nueva versión"
        for field, minimum, maximum in (
            ("quantity", Decimal("0.001"), None),
            ("unit_price", Decimal("0"), None),
            ("discount_percent", Decimal("0"), MAX_PERCENT),
        ):
            value = body.get(field)
            if value in (None, ""):
                continue
            try:
                _decimal(value, field, minimum=minimum, maximum=maximum)
            except HTTPException as error:
                errors[field] = str(error.detail)
        return errors

    @module.action(QuoteLine, "edit")
    async def edit_line(
        session: AsyncSession, ctx: Any, line: QuoteLine, body: dict[str, Any]
    ) -> dict[str, Any]:
        quote = await session.scalar(select(Quote).where(Quote.id == line.quote_id))
        if quote is None:
            raise HTTPException(status_code=404, detail="quote not found")
        _editable(quote)
        await _apply_line_body(session, line, body)
        await session.flush()
        await recompute(session, quote)
        return {
            "message": module._("Concepto actualizado; total {total} {currency}").format(
                total=quote.total, currency=quote.currency
            )
        }

    @module.action_options(QuoteLine, "edit")
    async def edit_line_options(
        session: AsyncSession, ctx: Any, line: QuoteLine, body: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "product_id": await _product_options(session),
            "tax_rate_id": await _tax_options(session),
        }

    @module.action(QuoteLine, "remove")
    async def remove_line(
        session: AsyncSession, ctx: Any, line: QuoteLine, body: dict[str, Any]
    ) -> dict[str, Any]:
        quote = await session.scalar(select(Quote).where(Quote.id == line.quote_id))
        if quote is None:
            raise HTTPException(status_code=404, detail="quote not found")
        _editable(quote)
        await session.delete(line)
        await session.flush()
        await recompute(session, quote)
        return {
            "message": module._("Concepto quitado; total {total} {currency}").format(
                total=quote.total, currency=quote.currency
            )
        }

    @module.action(Quote, "recalculate")
    async def recalculate(
        session: AsyncSession, ctx: Any, quote: Quote, body: dict[str, Any]
    ) -> dict[str, Any]:
        """After editing the quote's own discount or currency through the form."""
        _editable(quote)
        await recompute(session, quote)
        return {
            "message": module._("Totales recalculados: {total} {currency}").format(
                total=quote.total, currency=quote.currency
            )
        }

    @module.action(Quote, "send")
    async def send(
        session: AsyncSession, ctx: Any, quote: Quote, body: dict[str, Any]
    ) -> dict[str, Any]:
        if quote.status != QuoteStatus.draft:
            raise HTTPException(status_code=409, detail="only a draft quote can be sent")
        if not await _lines(session, quote.id):
            raise HTTPException(status_code=422, detail="a quote needs at least one line")
        await recompute(session, quote)
        quote.status = QuoteStatus.sent
        quote.sent_at = datetime.now(tz=UTC)
        if quote.issued_at is None:
            quote.issued_at = date.today()
        await session.flush()
        await module.emit("crm.quote.sent", _payload(quote))
        return {
            "message": module._(
                "Cotización enviada (registrada como enviada; el envío lo hace el equipo)"
            )
        }

    @module.action(Quote, "accept")
    async def accept(
        session: AsyncSession, ctx: Any, quote: Quote, body: dict[str, Any]
    ) -> dict[str, Any]:
        return await _decide(
            module,
            session,
            quote,
            QuoteStatus.accepted,
            body,
            "crm.quote.accepted",
            "Cotización aceptada",
        )

    @module.action(Quote, "reject")
    async def reject(
        session: AsyncSession, ctx: Any, quote: Quote, body: dict[str, Any]
    ) -> dict[str, Any]:
        return await _decide(
            module,
            session,
            quote,
            QuoteStatus.rejected,
            body,
            "crm.quote.rejected",
            "Cotización rechazada",
        )

    @module.action(Quote, "new_version")
    async def new_version(
        session: AsyncSession, ctx: Any, quote: Quote, body: dict[str, Any]
    ) -> dict[str, Any]:
        if quote.status == QuoteStatus.draft:
            raise HTTPException(
                status_code=409, detail="the quote is still a draft: edit it instead"
            )
        latest = await session.scalar(
            select(func.max(Quote.version)).where(
                Quote.number == quote.number, Quote.deleted_at.is_(None)
            )
        )
        copy = Quote(
            org_id=ctx.org_id,
            number=quote.number,
            version=int(latest or quote.version) + 1,
            previous_id=quote.id,
            title=quote.title,
            status=QuoteStatus.draft,
            company_id=quote.company_id,
            contact_id=quote.contact_id,
            opportunity_id=quote.opportunity_id,
            owner_user_id=ctx.user_id or quote.owner_user_id,
            currency=quote.currency,
            valid_until=quote.valid_until,
            discount_percent=quote.discount_percent,
            notes=quote.notes,
            terms=quote.terms,
        )
        session.add(copy)
        await session.flush()
        for line in await _lines(session, quote.id):
            session.add(
                QuoteLine(
                    org_id=ctx.org_id,
                    quote_id=copy.id,
                    position=line.position,
                    product_id=line.product_id,
                    description=line.description,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    discount_percent=line.discount_percent,
                    tax_rate_id=line.tax_rate_id,
                    tax_rate=line.tax_rate,
                )
            )
        await session.flush()
        await recompute(session, copy)
        return {
            "message": module._("Versión {version} creada como borrador").format(
                version=copy.version
            ),
            "record": {"model": "quotes", "id": str(copy.id)},
        }

    @module.action(Quote, "set_status")
    async def set_status(
        session: AsyncSession, ctx: Any, quote: Quote, body: dict[str, Any]
    ) -> dict[str, Any]:
        """Kanban drops on the quote board map to the cycle: draft → sent → accepted/rejected."""
        try:
            target = QuoteStatus(str(body.get("status") or quote.status.value))
        except ValueError as error:
            raise HTTPException(status_code=422, detail="unknown status") from error
        if target == quote.status:
            return {"message": module._("Sin cambios")}
        if target == QuoteStatus.sent:
            return await send(session, ctx, quote, body)
        if target == QuoteStatus.accepted:
            return await accept(session, ctx, quote, body)
        if target == QuoteStatus.rejected:
            return await reject(session, ctx, quote, body)
        raise HTTPException(
            status_code=409,
            detail="a quote only moves forward: send it, then record the decision",
        )

    @module.action(Quote, "remove")
    async def remove(
        session: AsyncSession, ctx: Any, quote: Quote, body: dict[str, Any]
    ) -> dict[str, Any]:
        if quote.status != QuoteStatus.draft:
            raise HTTPException(status_code=409, detail="only a draft quote can be deleted")
        await session.delete(quote)
        await session.flush()
        return {"message": module._("Cotización eliminada"), "path": "quotes"}

    @module.cron("crm.quotes_expire")
    async def expire(session: AsyncSession) -> None:
        """Sent quotes past `valid_until` become expired (no decision recorded)."""
        rows = (
            await session.scalars(
                select(Quote).where(
                    Quote.status == QuoteStatus.sent,
                    Quote.valid_until.is_not(None),
                    Quote.valid_until < date.today(),
                    Quote.deleted_at.is_(None),
                )
            )
        ).all()
        for quote in rows:
            quote.status = QuoteStatus.expired
        await session.flush()


def _payload(quote: Quote) -> dict[str, Any]:
    return {
        "quote_id": str(quote.id),
        "number": quote.number,
        "version": quote.version,
        "total": str(quote.total),
        "currency": quote.currency,
        "opportunity_id": str(quote.opportunity_id) if quote.opportunity_id else None,
        "company_id": str(quote.company_id) if quote.company_id else None,
    }


async def _decide(
    module: NovvusModule,
    session: AsyncSession,
    quote: Quote,
    status: QuoteStatus,
    body: dict[str, Any],
    event: str,
    message: str,
) -> dict[str, Any]:
    if quote.status != QuoteStatus.sent:
        raise HTTPException(status_code=409, detail="only a sent quote can be accepted or rejected")
    quote.status = status
    quote.decided_at = datetime.now(tz=UTC)
    quote.decision_notes = str(body.get("notes") or "")[:2000]
    await session.flush()
    await module.emit(event, _payload(quote))
    return {"message": module._(message)}


def expire_now(quote: Quote) -> bool:
    """Pure check used by tests and reports: a sent quote past its validity is expired."""
    return (
        quote.status == QuoteStatus.sent
        and quote.valid_until is not None
        and quote.valid_until < date.today()
    )


__all__ = [
    "compute_line",
    "compute_quote",
    "current_context",
    "expire_now",
    "money",
    "recompute",
    "register",
]

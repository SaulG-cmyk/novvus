"""Demo seed: 20 empresas, 50 contactos, pipeline por defecto de 6 etapas,
oportunidades repartidas, leads y actividades. Determinista (random con
semilla fija) para que las demos sean reproducibles."""

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from models import (
    Activity,
    ActivityStatus,
    ActivityType,
    Company,
    CompanyKind,
    CompanyStatus,
    Contact,
    ContactKind,
    ContactTag,
    Lead,
    LeadSource,
    LeadStatus,
    LostReason,
    Opportunity,
    Pipeline,
    Priority,
    Product,
    Quote,
    QuoteLine,
    QuoteStatus,
    Stage,
    Tag,
    TaxRate,
)
from quotes import compute_quote
from sqlalchemy.ext.asyncio import AsyncSession

COMPANIES = [
    ("Grupo Altiplano", "Manufactura"),
    ("Cafetalera del Sureste", "Alimentos y bebidas"),
    ("TecnoSoluciones MX", "Tecnología"),
    ("Constructora Real del Norte", "Construcción"),
    ("Farmacéutica Andrade", "Salud"),
    ("Logística Pacífico", "Transporte"),
    ("Textiles La Nueva Era", "Textil"),
    ("Energía Solar del Bajío", "Energía"),
    ("Distribuidora El Roble", "Comercio mayorista"),
    ("Agroindustrias Valle Verde", "Agroindustria"),
    ("Editorial Faro", "Medios"),
    ("Hotelera Costa Dorada", "Turismo"),
    ("Aceros Monterrey Industrial", "Metalurgia"),
    ("Consultores Zenit", "Servicios profesionales"),
    ("Panificadora San Cristóbal", "Alimentos y bebidas"),
    ("Vidriería Cristal Azul", "Manufactura"),
    ("Transportes Águila Real", "Transporte"),
    ("Laboratorios Vida Plena", "Salud"),
    ("Inmobiliaria Torre Alta", "Bienes raíces"),
    ("Escuela de Idiomas Global", "Educación"),
]

FIRST_NAMES = [
    "María",
    "José",
    "Ana",
    "Luis",
    "Carmen",
    "Jorge",
    "Lucía",
    "Miguel",
    "Sofía",
    "Carlos",
    "Valentina",
    "Ricardo",
    "Fernanda",
    "Andrés",
    "Paola",
    "Héctor",
    "Daniela",
    "Raúl",
    "Gabriela",
    "Emilio",
    "Ximena",
    "Arturo",
    "Renata",
    "Sergio",
    "Mariana",
]
LAST_NAMES = [
    "García",
    "Hernández",
    "López",
    "Martínez",
    "Rodríguez",
    "Pérez",
    "Sánchez",
    "Ramírez",
    "Flores",
    "Torres",
    "Vázquez",
    "Mendoza",
    "Castillo",
    "Romero",
    "Núñez",
    "Ibarra",
    "Salazar",
    "Cervantes",
]
JOB_TITLES = [
    "Directora General",
    "Gerente de Compras",
    "Director de Operaciones",
    "Coordinadora de TI",
    "Jefe de Almacén",
    "Gerente Comercial",
    "Directora de Finanzas",
    "Responsable de Logística",
]

STAGES = [
    # (nombre, posición, probabilidad, is_won, is_lost)
    ("Nuevo", 1, 10, False, False),
    ("Calificado", 2, 25, False, False),
    ("Propuesta", 3, 50, False, False),
    ("Negociación", 4, 75, False, False),
    ("Ganado", 5, 100, True, False),
    ("Perdido", 6, 0, False, True),
]

TAGS = [("VIP", "#d4af37"), ("Caliente", "#e2554b"), ("Frío", "#5b8dd9"), ("Renovación", "#57a65a")]

LOST_REASONS = [
    "Precio",
    "Sin presupuesto",
    "Eligió a un competidor",
    "Sin respuesta",
    "Proyecto cancelado",
]

# Demo tax and catalog: the organization edits these in Configuración; no country rule is assumed.
TAX_RATES = [("IVA 16 %", "16", "MX", True), ("Exento", "0", "", False)]
PRODUCTS = [
    # (sku, nombre, unidad, precio, con impuesto)
    ("SRV-CONS", "Consultoría (hora)", "hora", "1500", True),
    ("SRV-IMPL", "Implementación", "proyecto", "85000", True),
    ("SRV-SOP", "Soporte mensual", "mes", "12000", True),
    ("SRV-CAP", "Capacitación (sesión)", "sesión", "6500", True),
    ("LIC-STD", "Licencia estándar (anual)", "licencia", "24000", True),
    ("LIC-PRO", "Licencia profesional (anual)", "licencia", "48000", True),
]


async def seed(session: AsyncSession, org_id: UUID) -> None:
    rng = random.Random(2026)
    now = datetime.now(tz=UTC)

    companies: list[Company] = []
    for index, (name, industry) in enumerate(COMPANIES):
        slug = name.lower().replace(" ", "")[:18]
        companies.append(
            Company(
                org_id=org_id,
                name=name,
                legal_name=f"{name} S.A. de C.V.",
                industry=industry,
                website=f"https://www.{slug}.mx",
                email=f"contacto@{slug}.mx",
                phone=f"+52 55 {1000 + index:04d} {2000 + index:04d}",
                address=f"Av. Reforma {100 + index * 7}",
                city="Ciudad de México",
                region="CDMX",
                country="MX",
                kind=CompanyKind.customer if index % 3 else CompanyKind.prospect,
                status=CompanyStatus.active if index % 3 else CompanyStatus.prospect,
            )
        )
    session.add_all(companies)
    await session.flush()

    contacts: list[Contact] = []
    for index in range(50):
        first = FIRST_NAMES[index % len(FIRST_NAMES)]
        last = LAST_NAMES[(index * 3) % len(LAST_NAMES)]
        company = companies[index % len(companies)]
        contacts.append(
            Contact(
                org_id=org_id,
                name=f"{first} {last}",
                email=f"{first}.{last}@{company.website.removeprefix('https://www.')}".lower(),
                phone=f"+52 55 {3000 + index:04d} {4000 + index:04d}",
                job_title=JOB_TITLES[index % len(JOB_TITLES)],
                kind=list(ContactKind)[index % len(ContactKind)],
                company_id=company.id,
            )
        )
    session.add_all(contacts)

    pipeline = Pipeline(org_id=org_id, name="Pipeline de ventas", is_default=True)
    session.add(pipeline)
    await session.flush()

    stages = [
        Stage(
            org_id=org_id,
            pipeline_id=pipeline.id,
            name=name,
            position=position,
            probability=probability,
            is_won=is_won,
            is_lost=is_lost,
        )
        for name, position, probability, is_won, is_lost in STAGES
    ]
    session.add_all(stages)

    tags = [Tag(org_id=org_id, name=name, color=color) for name, color in TAGS]
    session.add_all(tags)
    session.add_all(LostReason(org_id=org_id, name=name) for name in LOST_REASONS)
    tax_rates = [
        TaxRate(org_id=org_id, name=name, rate=Decimal(rate), country=country, is_default=default)
        for name, rate, country, default in TAX_RATES
    ]
    session.add_all(tax_rates)
    await session.flush()
    session.add_all(
        Product(
            org_id=org_id,
            sku=sku,
            name=name,
            unit=unit,
            list_price=Decimal(price),
            currency="MXN",
            tax_rate_id=tax_rates[0].id if taxed else None,
        )
        for sku, name, unit, price, taxed in PRODUCTS
    )
    await session.flush()

    open_stages = [s for s in stages if not s.is_won and not s.is_lost]
    won_stage = next(s for s in stages if s.is_won)
    lost_stage = next(s for s in stages if s.is_lost)

    opportunities: list[Opportunity] = []
    for index in range(25):
        contact = contacts[rng.randrange(len(contacts))]
        bucket = rng.random()
        if bucket < 0.6:
            stage = open_stages[rng.randrange(len(open_stages))]
            is_won, closed_at = None, None
        elif bucket < 0.85:
            stage, is_won = won_stage, True
            closed_at = now - timedelta(days=rng.randrange(3, 60))
        else:
            stage, is_won = lost_stage, False
            closed_at = now - timedelta(days=rng.randrange(3, 60))
        opportunities.append(
            Opportunity(
                org_id=org_id,
                name=f"Proyecto {COMPANIES[index % len(COMPANIES)][0]}",
                amount=Decimal(rng.randrange(30, 900)) * 1000,
                currency="MXN",
                pipeline_id=pipeline.id,
                stage_id=stage.id,
                expected_close_date=(now + timedelta(days=rng.randrange(10, 120))).date(),
                contact_id=contact.id,
                company_id=contact.company_id,
                priority=rng.choice(list(Priority)),
                is_won=is_won,
                closed_at=closed_at,
            )
        )
    session.add_all(opportunities)

    leads: list[Lead] = []
    for index in range(15):
        contact = contacts[(index * 2) % len(contacts)]
        status = LeadStatus.new if index % 3 else LeadStatus.qualified
        leads.append(
            Lead(
                org_id=org_id,
                title=f"Interés de {contact.name}",
                source=rng.choice(list(LeadSource)),
                status=status,
                person_name=contact.name,
                email=contact.email,
                contact_id=contact.id,
                company_id=contact.company_id,
                need="Automatizar el seguimiento comercial",
                estimated_value=Decimal(rng.randrange(20, 300)) * 1000,
                notes=f"Interesado en cotización #{1400 + index}",
            )
        )
    session.add_all(leads)
    await session.flush()

    activities: list[Activity] = []
    for index, opportunity in enumerate(opportunities[:12]):
        activities.append(
            Activity(
                org_id=org_id,
                type=rng.choice(list(ActivityType)),
                title=f"Seguimiento {opportunity.name}",
                due_date=now + timedelta(days=rng.randrange(1, 21)),
                status=ActivityStatus.pending if index % 2 else ActivityStatus.done,
                completed_at=None if index % 2 else now - timedelta(days=1),
                opportunity_id=opportunity.id,
            )
        )
    session.add_all(activities)

    session.add_all(
        ContactTag(org_id=org_id, contact_id=contacts[i].id, tag_id=tags[i % len(tags)].id)
        for i in range(0, 20, 2)
    )
    await session.flush()

    # Two quotes on open opportunities: one accepted (sent and decided), one still a draft.
    products = list(
        (
            await session.execute(Product.__table__.select().where(Product.org_id == org_id))
        ).mappings()
    )
    open_opportunities = [o for o in opportunities if o.is_won is None][:2]
    for index, opportunity in enumerate(open_opportunities):
        quote = Quote(
            org_id=org_id,
            number=f"COT-{now.year}-{index + 1:04d}",
            title=f"Propuesta {opportunity.name}",
            status=QuoteStatus.draft,
            company_id=opportunity.company_id,
            contact_id=opportunity.contact_id,
            opportunity_id=opportunity.id,
            currency=opportunity.currency,
            issued_at=now.date(),
            valid_until=(now + timedelta(days=30)).date(),
            discount_percent=Decimal("5") if index else Decimal("0"),
        )
        session.add(quote)
        await session.flush()
        lines = [
            QuoteLine(
                org_id=org_id,
                quote_id=quote.id,
                position=position + 1,
                product_id=product["id"],
                description=product["name"],
                quantity=Decimal(position + 1),
                unit_price=product["list_price"],
                discount_percent=Decimal("0"),
                tax_rate_id=product["tax_rate_id"],
                tax_rate=tax_rates[0].rate if product["tax_rate_id"] else Decimal("0"),
            )
            for position, product in enumerate(products[:3])
        ]
        session.add_all(lines)
        compute_quote(quote, lines)
        if index == 0:
            quote.status = QuoteStatus.accepted
            quote.sent_at = now - timedelta(days=5)
            quote.decided_at = now - timedelta(days=2)
            quote.decision_notes = "Aceptada por el cliente (seed)"
    await session.flush()

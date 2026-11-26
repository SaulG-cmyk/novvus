"""Reclutamiento — módulo NOVVUS."""

from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from novvus_sdk import NovvusModel, NovvusModule

from models import ALL_MODELS

module = NovvusModule(Path(__file__).with_name("novvus.toml"))

for model in ALL_MODELS:
    module.model(model)

# business.py is optional; create empty if not needed
try:
    import business
    business.register(module)
except ImportError:
    pass

@module.seed
async def seed(session: AsyncSession, org_id: UUID) -> None:
    from models import JobPosition, Candidate
    session.add_all([
        JobPosition(org_id=org_id, name="Desarrollador Python", department="TI", status="open", employment_type="full_time", location="Remoto"),
        Candidate(org_id=org_id, name="Juan Pérez", email="juan@test.com", status="new", source="LinkedIn"),
    ])

app = module.create_app()

"""Auditorías — módulo NOVVUS."""

from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from novvus_sdk import NovvusModel, NovvusModule

from models import ALL_MODELS

module = NovvusModule(Path(__file__).with_name("novvus.toml"))

for model in ALL_MODELS:
    module.model(model)

try:
    import business
    business.register(module)
except ImportError:
    pass

@module.seed
async def seed(session: AsyncSession, org_id: UUID) -> None:
    from models import Audit
    session.add(Audit(org_id=org_id, name="Auditoría interna Q4", audit_type="internal", status="planned"))

app = module.create_app()

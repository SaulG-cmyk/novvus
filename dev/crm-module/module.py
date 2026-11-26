"""CRM — NOVVUS module entry point.

Built exclusively with novvus-sdk: models get their tables (RLS included) and
CRUD API generated; business rules live in business.py; demo data in seed.py.
"""

from pathlib import Path

import business
import directory
import errors
import integration
import quotes
import reports
import seed as seed_module
import views
from models import ALL_MODELS

from novvus_sdk import NovvusModule

module = NovvusModule(Path(__file__).with_name("novvus.toml"))

# Badges, counters, tabs, related panels and stage indicators (views.py) are
# layered on the models BEFORE registration: the SDK validates them then.
views.declare()
for model in ALL_MODELS:
    module.model(model)

business.register(module)
directory.register(module)
quotes.register(module)
reports.register(module)
integration.register(module)
module.seed(seed_module.seed)

app = module.create_app()
errors.install(app)  # unique/foreign-key violations answer 409 with the field, never 500

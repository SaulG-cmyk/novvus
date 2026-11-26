"""novvus-sdk: declarative layer to build NOVVUS CORE business modules.

A module declares models, permissions, events and endpoints; the SDK
generates the REST API, enforces tenant isolation (RLS) and talks to the
kernel. Contracts: docs/MODULE_CONTRACT.md in the platform repository.

This package is the ONLY sanctioned import surface for module code
(ADR-001): everything a module needs is re-exported here, and
``scripts/check_sdk_imports.py`` rejects deep imports of SDK internals.
"""

from novvus_sdk.app import NovvusModule
from novvus_sdk.context import RequestContext, current_context
from novvus_sdk.contract import PLATFORM_API
from novvus_sdk.entitlement import (
    Entitlement,
    current_entitlement,
    enforce_feature,
    requires_feature,
)
from novvus_sdk.events import Event
from novvus_sdk.i18n import Translator
from novvus_sdk.manifest import Manifest
from novvus_sdk.meta import NAV_KEYS, VIEW_KEYS
from novvus_sdk.models import NovvusModel
from novvus_sdk.security import enforce, requires

__all__ = [
    "NAV_KEYS",
    "PLATFORM_API",
    "VIEW_KEYS",
    "Entitlement",
    "Event",
    "Manifest",
    "NovvusModel",
    "NovvusModule",
    "RequestContext",
    "Translator",
    "current_context",
    "current_entitlement",
    "enforce",
    "enforce_feature",
    "requires",
    "requires_feature",
]

__version__ = "0.2.20"

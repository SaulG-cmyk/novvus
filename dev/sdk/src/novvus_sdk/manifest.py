"""novvus.toml parsing and validation (mirror of the kernel-side rules)."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

from novvus_sdk.contract import (
    CHANNELS,
    MANIFEST_API_VERSION,
    MANIFEST_KIND,
    PLATFORM_API,
    RESTRICTED_MODES,
    SUPPORTED_PLATFORMS,
    UI_MODES,
    VISIBILITIES,
)

MODULE_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
RESERVED_IDS = {"core", "api", "internal", "novvus"}
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+].*)?$")
EVENT_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z0-9_]+\.[a-z0-9_]+$")


# --- Semver requirements (mirror of the kernel-side `semver::VersionReq`) ---
#
# `[compatibility] core` / `sdk` and dependency specs share the grammar of the
# Rust `semver` crate the kernel uses: comma-separated comparators, each an
# optional operator (`=`, `>`, `>=`, `<`, `<=`, `~`, `^`; none means caret)
# followed by a partial version (`1`, `1.2`, `1.2.3-pre`) or a wildcard
# (`1.*`, `1.2.x`, `*`). Matching follows the crate, including the rule that a
# pre-release version only satisfies a requirement when some comparator names
# the same major.minor.patch with a pre-release of its own.

_PRE_IDENT = r"(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
_PRERELEASE = rf"{_PRE_IDENT}(?:\.{_PRE_IDENT})*"
_BUILD = r"[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*"
_NUMERIC = r"0|[1-9]\d*"

# Full semver 2.0 version (build metadata parsed and ignored).
VERSION_RE = re.compile(
    rf"^(?P<major>{_NUMERIC})\.(?P<minor>{_NUMERIC})\.(?P<patch>{_NUMERIC})"
    rf"(?:-(?P<pre>{_PRERELEASE}))?(?:\+(?P<build>{_BUILD}))?$"
)

# One comparator of a requirement. A pre-release/build suffix is only legal
# after a numeric patch, and a numeric patch may not follow a wildcard minor.
COMPARATOR_RE = re.compile(
    rf"^(?P<op>>=|<=|=|>|<|~|\^)?\s*(?P<major>{_NUMERIC})"
    rf"(?:\.(?:(?P<minor>{_NUMERIC})|(?P<minor_wc>[*xX]))"
    rf"(?:\.(?:(?P<patch>{_NUMERIC})(?:-(?P<pre>{_PRERELEASE}))?(?:\+{_BUILD})?"
    rf"|(?P<patch_wc>[*xX])))?)?$"
)

# Same bound the kernel-side crate enforces on comparators per requirement.
MAX_COMPARATORS = 32


def _compare_prerelease(left: str, right: str) -> int:
    """Semver 2.0 precedence of two pre-release strings ("" is a release and
    sorts above any pre-release); -1, 0 or 1."""
    if left == right:
        return 0
    if not left:
        return 1
    if not right:
        return -1
    lhs, rhs = left.split("."), right.split(".")
    for a, b in zip(lhs, rhs, strict=False):
        a_num, b_num = a.isdigit(), b.isdigit()
        if a_num and b_num:
            if int(a) != int(b):
                return -1 if int(a) < int(b) else 1
        elif a_num != b_num:
            # Numeric identifiers sort below alphanumeric ones.
            return -1 if a_num else 1
        elif a != b:
            return -1 if a < b else 1
    if len(lhs) == len(rhs):
        return 0
    return -1 if len(lhs) < len(rhs) else 1


@dataclass(frozen=True)
class Version:
    """A parsed semver 2.0 version (build metadata dropped)."""

    major: int
    minor: int
    patch: int
    pre: str = ""

    @classmethod
    def parse(cls, text: str) -> Version:
        match = VERSION_RE.fullmatch(text.strip())
        if match is None:
            raise ValueError(f"version {text!r} is not valid semver")
        return cls(
            int(match["major"]), int(match["minor"]), int(match["patch"]), match["pre"] or ""
        )

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        return f"{base}-{self.pre}" if self.pre else base


@dataclass(frozen=True)
class Comparator:
    """One `<op><partial version>` clause; `op` is one of the operators above
    or `"*"` for a bare wildcard clause (`1.*`), which behaves like `=`."""

    op: str
    major: int
    minor: int | None
    patch: int | None
    pre: str

    @classmethod
    def parse(cls, text: str) -> Comparator:
        match = COMPARATOR_RE.fullmatch(text)
        if match is None:
            raise ValueError(f"unexpected comparator {text!r}")
        if match["minor_wc"] and match["patch"]:
            raise ValueError(f"unexpected numeric patch after wildcard in {text!r}")
        op = match["op"]
        wildcard = bool(match["minor_wc"] or match["patch_wc"])
        if op is None:
            op = "*" if wildcard else "^"
        minor = int(match["minor"]) if match["minor"] else None
        patch = int(match["patch"]) if match["patch"] else None
        return cls(op, int(match["major"]), minor, patch, match["pre"] or "")

    def matches(self, version: Version) -> bool:
        if self.op in ("=", "*"):
            return self._matches_exact(version)
        if self.op == ">":
            return self._matches_greater(version)
        if self.op == ">=":
            return self._matches_exact(version) or self._matches_greater(version)
        if self.op == "<":
            return self._matches_less(version)
        if self.op == "<=":
            return self._matches_exact(version) or self._matches_less(version)
        if self.op == "~":
            return self._matches_tilde(version)
        return self._matches_caret(version)

    def _matches_exact(self, version: Version) -> bool:
        if version.major != self.major:
            return False
        if self.minor is not None and version.minor != self.minor:
            return False
        if self.patch is not None and version.patch != self.patch:
            return False
        return version.pre == self.pre

    def _matches_greater(self, version: Version) -> bool:
        if version.major != self.major:
            return version.major > self.major
        if self.minor is None:
            return False
        if version.minor != self.minor:
            return version.minor > self.minor
        if self.patch is None:
            return False
        if version.patch != self.patch:
            return version.patch > self.patch
        return _compare_prerelease(version.pre, self.pre) > 0

    def _matches_less(self, version: Version) -> bool:
        if version.major != self.major:
            return version.major < self.major
        if self.minor is None:
            return False
        if version.minor != self.minor:
            return version.minor < self.minor
        if self.patch is None:
            return False
        if version.patch != self.patch:
            return version.patch < self.patch
        return _compare_prerelease(version.pre, self.pre) < 0

    def _matches_tilde(self, version: Version) -> bool:
        if version.major != self.major:
            return False
        if self.minor is not None and version.minor != self.minor:
            return False
        if self.patch is not None and version.patch != self.patch:
            return version.patch > self.patch
        return _compare_prerelease(version.pre, self.pre) >= 0

    def _matches_caret(self, version: Version) -> bool:
        if version.major != self.major:
            return False
        if self.minor is None:
            return True
        if self.patch is None:
            if self.major > 0:
                return version.minor >= self.minor
            return version.minor == self.minor
        if self.major > 0:
            if version.minor != self.minor:
                return version.minor > self.minor
            if version.patch != self.patch:
                return version.patch > self.patch
        elif self.minor > 0:
            if version.minor != self.minor:
                return False
            if version.patch != self.patch:
                return version.patch > self.patch
        elif version.minor != self.minor or version.patch != self.patch:
            return False
        return _compare_prerelease(version.pre, self.pre) >= 0

    def _pre_is_compatible(self, version: Version) -> bool:
        return (
            self.major == version.major
            and self.minor == version.minor
            and self.patch == version.patch
            and bool(self.pre)
        )


@dataclass(frozen=True)
class VersionRequirement:
    """A parsed requirement such as ">=0.2.0,<0.3.0", "^0.2" or "*"."""

    text: str
    comparators: tuple[Comparator, ...]

    @classmethod
    def parse(cls, text: str) -> VersionRequirement:
        source = text.strip()
        if not source:
            raise ValueError("empty string, expected a semver version requirement")
        if source in ("*", "x", "X"):
            return cls(source, ())
        clauses = [clause.strip() for clause in source.split(",")]
        if len(clauses) > MAX_COMPARATORS:
            raise ValueError(f"a requirement may have at most {MAX_COMPARATORS} comparators")
        if any(clause in ("*", "x", "X") for clause in clauses):
            raise ValueError("a wildcard requirement must be the only comparator")
        return cls(source, tuple(Comparator.parse(clause) for clause in clauses))

    def matches(self, version: Version | str) -> bool:
        if isinstance(version, str):
            version = Version.parse(version)
        if not all(comparator.matches(version) for comparator in self.comparators):
            return False
        if not version.pre:
            return True
        # A pre-release only satisfies a comparator that names the same
        # major.minor.patch with a pre-release tag of its own.
        return any(comparator._pre_is_compatible(version) for comparator in self.comparators)

    def __str__(self) -> str:
        return self.text


class ModuleSection(BaseModel):
    id: str
    name: str
    version: str
    description: str = ""

    @field_validator("id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        if not MODULE_ID_RE.match(value):
            raise ValueError(f"module id {value!r} must match ^[a-z][a-z0-9_]{{1,31}}$")
        if value in RESERVED_IDS:
            raise ValueError(f"module id {value!r} is reserved")
        return value

    @field_validator("version")
    @classmethod
    def _valid_version(cls, value: str) -> str:
        if not SEMVER_RE.match(value):
            raise ValueError(f"version {value!r} is not valid semver")
        return value


# --- Contract sections (ADR-001 Fase A; mirror of the kernel-side rules) ---
#
# Every section is optional so manifests written before the contract existed
# keep parsing unchanged; when present, values must be well formed and the
# cross-section rules in Manifest._validate_contract hold.

PUBLISHER_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
KEY_ID_RE = re.compile(r"^ed25519:[A-Za-z0-9._/-]{4,128}$")
IMAGE_COMPONENT_RE = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
IMAGE_PORT_RE = re.compile(r"^[0-9]+$")
PRODUCT_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_PRODUCT_ID_LEN = 64
FEATURE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


def _valid_image_reference(image: str) -> bool:
    """OCI image reference without tag or digest: lowercase path components
    separated by "/" (at least one "/"); only the first component may carry
    a ":port"; no "@digest"."""
    if "@" in image or "/" not in image:
        return False
    first, *rest = image.split("/")
    host, sep, port = first.partition(":")
    if sep and not IMAGE_PORT_RE.fullmatch(port):
        return False
    if not IMAGE_COMPONENT_RE.fullmatch(host):
        return False
    return all(":" not in part and IMAGE_COMPONENT_RE.fullmatch(part) for part in rest)


class ManifestSection(BaseModel):
    """`[manifest]` — contract header: which manifest contract this file
    follows. Absent means `novvus.dev/v1` / `module`."""

    api_version: str = MANIFEST_API_VERSION
    kind: str = MANIFEST_KIND

    @field_validator("api_version")
    @classmethod
    def _valid_api_version(cls, value: str) -> str:
        if value != MANIFEST_API_VERSION:
            raise ValueError(
                f"manifest api_version {value!r} is not supported "
                f"(expected {MANIFEST_API_VERSION!r})"
            )
        return value

    @field_validator("kind")
    @classmethod
    def _valid_kind(cls, value: str) -> str:
        if value != MANIFEST_KIND:
            raise ValueError(
                f"manifest kind {value!r} is not supported (expected {MANIFEST_KIND!r})"
            )
        return value


class PublisherSection(BaseModel):
    """`[publisher]` — the identity that develops and signs the module
    (Publisher != Customer, ADR-001 D9)."""

    # ^[a-z][a-z0-9-]{1,31}$ (e.g. "novvus", "novvus-enterprise").
    id: str
    name: str | None = None
    # Key that signs the package: "ed25519:<name-or-fingerprint>" (a customer
    # subkey reads "ed25519:novvus-enterprise/<customer>").
    key_id: str | None = None

    @field_validator("id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        if not PUBLISHER_ID_RE.fullmatch(value):
            raise ValueError(f"publisher id {value!r} must match ^[a-z][a-z0-9-]{{1,31}}$")
        return value

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("publisher name must not be empty")
        return value

    @field_validator("key_id")
    @classmethod
    def _valid_key_id(cls, value: str | None) -> str | None:
        if value is not None and not KEY_ID_RE.fullmatch(value):
            raise ValueError(
                f"publisher key_id {value!r} must have the form ed25519:<id> "
                "([A-Za-z0-9._/-], 4..128 chars)"
            )
        return value


class DistributionSection(BaseModel):
    """`[distribution]` — visibility, image and platforms of the module."""

    # "standard" (public registry) | "private" (customer registry).
    visibility: str = "standard"
    # OCI image reference without tag or digest (the tag is the module
    # version). Required for private modules.
    image: str | None = None
    # Subset of SUPPORTED_PLATFORMS, no duplicates.
    platforms: list[str] = Field(default_factory=list)
    # "stable" | "beta" (informational for the registry).
    channel: str = "stable"

    @field_validator("visibility")
    @classmethod
    def _valid_visibility(cls, value: str) -> str:
        if value not in VISIBILITIES:
            raise ValueError(f'distribution visibility {value!r} must be "standard" or "private"')
        return value

    @field_validator("image")
    @classmethod
    def _valid_image(cls, value: str | None) -> str | None:
        if value is not None and not _valid_image_reference(value):
            raise ValueError(
                f"distribution image {value!r} must be an OCI reference without tag "
                "or digest (e.g. ghcr.io/novvus/crm)"
            )
        return value

    @field_validator("platforms")
    @classmethod
    def _valid_platforms(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        for platform in value:
            if platform not in SUPPORTED_PLATFORMS:
                raise ValueError(
                    f"distribution platform {platform!r} is not supported "
                    f"(expected one of {list(SUPPORTED_PLATFORMS)!r})"
                )
            if platform in seen:
                raise ValueError(f"duplicate distribution platform {platform!r}")
            seen.add(platform)
        return value

    @field_validator("channel")
    @classmethod
    def _valid_channel(cls, value: str) -> str:
        if value not in CHANNELS:
            raise ValueError(f'distribution channel {value!r} must be "stable" or "beta"')
        return value


class CompatibilitySection(BaseModel):
    """`[compatibility]` — ranges of Core / SDK the module accepts. The kernel
    enforces `core` at register, install and migrate."""

    # Semver requirement on the Core version (e.g. ">=0.2.0,<0.3.0").
    core: str | None = None
    # Semver requirement on the SDK the module was built with (informational).
    sdk: str | None = None
    # Platform contract version the module consumes; must equal the served one.
    platform_api: int | None = None

    @field_validator("core", "sdk")
    @classmethod
    def _valid_requirement(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is not None:
            try:
                VersionRequirement.parse(value)
            except ValueError as error:
                raise ValueError(
                    f"compatibility {info.field_name} {value!r} is not a valid version "
                    f"requirement: {error}"
                ) from None
        return value

    @field_validator("platform_api")
    @classmethod
    def _valid_platform_api(cls, value: int | None) -> int | None:
        if value is not None and value != PLATFORM_API:
            raise ValueError(
                f"compatibility platform_api {value} is not served by this SDK "
                f"(serves {PLATFORM_API})"
            )
        return value


class EntitlementSection(BaseModel):
    """`[entitlement]` — whether using the module requires rights (licensing
    arrives in a later phase; the declaration is part of the contract)."""

    required: bool = False
    # Product / SKU id in the control plane. Required when `required`.
    product: str | None = None
    # Separately licensable capabilities (optional).
    features: list[str] = Field(default_factory=list)
    # Behavior when rights lapse. Contract v1 only knows "read-only".
    restricted_mode: str | None = None

    @field_validator("product")
    @classmethod
    def _valid_product(cls, value: str | None) -> str | None:
        if value is not None and (
            len(value) > MAX_PRODUCT_ID_LEN or not PRODUCT_ID_RE.fullmatch(value)
        ):
            raise ValueError(
                f"entitlement product {value!r} must match ^[a-z0-9]+(-[a-z0-9]+)*$ "
                f"(max {MAX_PRODUCT_ID_LEN} chars)"
            )
        return value

    @field_validator("features")
    @classmethod
    def _valid_features(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        for feature in value:
            if not FEATURE_NAME_RE.fullmatch(feature):
                raise ValueError(
                    f"entitlement feature {feature!r} must match ^[a-z][a-z0-9_]{{0,31}}$"
                )
            if feature in seen:
                raise ValueError(f"duplicate entitlement feature {feature!r}")
            seen.add(feature)
        return value

    @field_validator("restricted_mode")
    @classmethod
    def _valid_restricted_mode(cls, value: str | None) -> str | None:
        if value is not None and value not in RESTRICTED_MODES:
            raise ValueError(
                f"entitlement restricted_mode {value!r} is not supported in api_version "
                f'{MANIFEST_API_VERSION}: only "read-only" exists'
            )
        return value


class DataSection(BaseModel):
    """`[data]` — data policy declarations."""

    export: bool = True
    retention_days: int = 0

    @field_validator("retention_days")
    @classmethod
    def _valid_retention_days(cls, value: int) -> int:
        if value < 0:
            raise ValueError(f"data retention_days {value} must be >= 0")
        return value


class DependenciesSection(BaseModel):
    modules: list[str] = Field(default_factory=list)
    # Permissions of OTHER modules used in module→module service calls.
    service_permissions: list[str] = Field(default_factory=list)

    @field_validator("service_permissions")
    @classmethod
    def _valid_service_permissions(cls, value: list[str]) -> list[str]:
        for perm in value:
            parts = perm.split(".")
            if len(parts) != 3 or not all(parts):
                raise ValueError(
                    f"service permission {perm!r} must have the form module.resource.action"
                )
            if parts[0] == "core":
                raise ValueError(f"service permission {perm!r} may not target the kernel")
        return value


class PermissionDecl(BaseModel):
    key: str
    description: str = ""


# Longest role name a manifest may declare (mirror of the kernel-side cap).
MAX_ROLE_NAME_LEN = 64
# System roles the kernel creates with every organization; never declarable
# (compared case-insensitively, mirror of the kernel).
RESERVED_ROLE_NAMES = frozenset({"owner"})


class RoleDecl(BaseModel):
    """A role the kernel creates in every organization that enables the module
    (MODULE_CONTRACT.md §2.2b): only the module's own permissions, each one
    declared in `[[permissions]]`. Mirror of the kernel-side RoleDecl."""

    name: str
    description: str = ""
    permissions: list[str] = Field(default_factory=list)


class EventsSection(BaseModel):
    emits: list[str] = Field(default_factory=list)
    listens: list[str] = Field(default_factory=list)


class RuntimeSection(BaseModel):
    port: int | None = None
    healthcheck: str = "/health"


ICON_SLUG_RE = re.compile(r"^[a-z0-9-]{1,48}$")


class PresentationSection(BaseModel):
    """Descriptive metadata for the Apps store / dashboard (never affects the
    data plane). Mirror of the kernel-side PresentationSection."""

    display_name: str | None = None
    summary: str | None = None
    category: str | None = None
    icon: str | None = None
    accent: str | None = None
    publisher: str | None = None
    website: str | None = None
    license: str | None = None
    screenshots: list[str] = Field(default_factory=list)

    @field_validator("icon")
    @classmethod
    def _valid_icon(cls, value: str | None) -> str | None:
        if value is not None and not ICON_SLUG_RE.match(value):
            raise ValueError(f"presentation icon {value!r} must be a slug [a-z0-9-]")
        return value

    @field_validator("website")
    @classmethod
    def _valid_website(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("http://", "https://")):
            raise ValueError(f"presentation website {value!r} must be an http(s) URL")
        return value


class UiNavItem(BaseModel):
    path: str
    label: str
    icon: str | None = None
    permission: str | None = None
    exact: bool = False


class UiWidget(BaseModel):
    title: str
    description: str | None = None
    icon: str | None = None
    path: str
    permission: str | None = None


class UiSettingsSection(BaseModel):
    label: str
    description: str | None = None
    icon: str | None = None
    path: str
    permission: str | None = None


class UiSection(BaseModel):
    """Declarative UI contributions rendered by the shell (mirror of the
    kernel-side UiSection). Descriptive only; a module never ships shell code."""

    # "generic" (declarative views rendered by the shell, the only mode served
    # by platform_api 1) | "external" (module-served SPA in a sandboxed frame,
    # reserved for platform_api 2 and rejected today).
    mode: str = "generic"
    # Reserved for mode = "external"; its presence is rejected today.
    external: dict[str, Any] | None = None
    entry: str | None = None
    nav: list[UiNavItem] = Field(default_factory=list)
    dashboard: list[UiWidget] = Field(default_factory=list)
    settings: list[UiSettingsSection] = Field(default_factory=list)

    @field_validator("mode")
    @classmethod
    def _valid_mode(cls, value: str) -> str:
        if value == "external":
            raise ValueError(
                f'ui.mode "external" requires platform_api >= 2 (this SDK serves {PLATFORM_API})'
            )
        if value not in UI_MODES:
            raise ValueError(f'ui mode {value!r} must be "generic" or "external"')
        return value

    @field_validator("external")
    @classmethod
    def _reject_external(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is not None:
            raise ValueError(
                f"[ui.external] requires platform_api >= 2 (this SDK serves {PLATFORM_API})"
            )
        return value


CONFIG_FIELD_TYPES = {"string", "number", "boolean", "select"}


def _config_value_matches(field_type: str, value: Any) -> bool:
    """A config value matches its declared field type (bool is not a number)."""
    if field_type in ("string", "select"):
        return isinstance(value, str)
    if field_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if field_type == "boolean":
        return isinstance(value, bool)
    return False


class ConfigFieldDecl(BaseModel):
    """One declarative config field (mirror of the kernel-side ConfigFieldDecl).
    The kernel persists values per-org; the SDK reads/writes them typed."""

    key: str
    type: str
    label: str | None = None
    description: str | None = None
    default: Any = None
    options: list[str] = Field(default_factory=list)
    permission: str | None = None
    secret: bool = False


class CronJobDecl(BaseModel):
    """A scheduled job the kernel runs per enabled org (mirror of the kernel-side
    CronJobDecl)."""

    name: str
    interval_seconds: int
    description: str | None = None


# Extension field types allowed in v1 (docs/EXTENSIONS.md §2); `relation` and
# `json` are deliberately excluded.
EXT_FIELD_TYPES = {"string", "text", "integer", "decimal", "boolean", "date", "datetime"}

# Hard cap of extension fields one module may declare (docs/DECISIONS.md).
MAX_EXT_FIELDS = 32

# ^[a-z][a-z0-9_]{0,63}$ — same shape the kernel meta uses for field names
# (kernel-side valid_field_name, 64 chars max).
EXT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

# Operators that may follow the module id in a dependency spec ("crm>=1.0").
DEP_SPEC_SPLIT_RE = re.compile(r"[<>=^~!]")


def _dependency_module_id(spec: str) -> str:
    """The bare module id of a dependency spec like "crm" or "crm>=1.0"
    (mirror of the kernel-side parse_dependency)."""
    return DEP_SPEC_SPLIT_RE.split(spec, maxsplit=1)[0].strip()


class ExtensionFieldDecl(BaseModel):
    """One field this module contributes to a base model of a module it depends
    on (mirror of the kernel-side ExtensionFieldDecl, docs/EXTENSIONS.md §2).
    Data lives in the base module's `ext` JSONB column."""

    # `{module}.{model}` of the base model being extended.
    target: str
    # Key inside `ext['{extender}']`; must match EXT_NAME_RE.
    name: str
    # One of EXT_FIELD_TYPES (no relation/json in v1).
    type: str
    # es-MX source text (i18n pattern).
    label: str
    required: bool = False
    # Optional constraints: max_length, pattern, choices = [{value, label}].
    config: Any = None


class ExtensionUiDecl(BaseModel):
    """A form section this module contributes to a base generic view (mirror of
    the kernel-side ExtensionUiDecl)."""

    # `{module}.{model}.form` — the base generic view receiving the section.
    target: str
    # `after:{field}` of the base layout, or `section:end` (kernel default).
    slot: str = "section:end"
    # es-MX source text of the section heading.
    group_label: str
    # Extension fields (declared above, same target model) to render.
    fields: list[str]


class ExtensionsSection(BaseModel):
    """Cross-module extension contract (mirror of the kernel-side
    ExtensionsSection, docs/EXTENSIONS.md §2)."""

    fields: list[ExtensionFieldDecl] = Field(default_factory=list)
    ui: list[ExtensionUiDecl] = Field(default_factory=list)


class Manifest(BaseModel):
    # Contract header (ADR-001 Fase A); absent means novvus.dev/v1 / module.
    manifest: ManifestSection = Field(default_factory=ManifestSection)
    module: ModuleSection
    # Who develops and signs the module (Publisher != Customer, ADR-001 D9).
    publisher: PublisherSection | None = None
    # How the module is distributed: visibility, image, platforms.
    distribution: DistributionSection = Field(default_factory=DistributionSection)
    # Which Core / SDK / platform contract the module accepts.
    compatibility: CompatibilitySection = Field(default_factory=CompatibilitySection)
    # Whether using the module requires an entitlement.
    entitlement: EntitlementSection = Field(default_factory=EntitlementSection)
    # Data policy declarations (export, retention).
    data: DataSection = Field(default_factory=DataSection)
    dependencies: DependenciesSection = Field(default_factory=DependenciesSection)
    permissions: list[PermissionDecl] = Field(default_factory=list)
    roles: list[RoleDecl] = Field(default_factory=list)
    events: EventsSection = Field(default_factory=EventsSection)
    runtime: RuntimeSection = Field(default_factory=RuntimeSection)
    presentation: PresentationSection = Field(default_factory=PresentationSection)
    ui: UiSection = Field(default_factory=UiSection)
    config: list[ConfigFieldDecl] = Field(default_factory=list)
    cron: list[CronJobDecl] = Field(default_factory=list)
    extensions: ExtensionsSection = Field(default_factory=ExtensionsSection)

    @model_validator(mode="after")
    def _validate_contract(self) -> Manifest:
        """Cross-section rules of the contract (ADR-001 §5). Each section
        validates its own fields; this ties them together."""
        if self.distribution.visibility == "private":
            if self.compatibility.core is None:
                raise ValueError("private modules must declare [compatibility] core")
            if self.distribution.image is None:
                raise ValueError("private modules must declare [distribution] image")
        if self.entitlement.required:
            if self.compatibility.core is None:
                raise ValueError(
                    "modules with [entitlement] required = true must declare [compatibility] core"
                )
            if self.entitlement.product is None:
                raise ValueError(
                    "modules with [entitlement] required = true must declare [entitlement] product"
                )
        return self

    def core_requirement(self) -> VersionRequirement | None:
        """The `[compatibility] core` requirement, parsed (None when absent)."""
        if self.compatibility.core is None:
            return None
        return VersionRequirement.parse(self.compatibility.core)

    def is_compatible_with_core(self, version: str) -> bool:
        """Whether a Core of `version` (semver) satisfies `[compatibility]
        core`. A module without a declared range is accepted (manifests
        written before the contract existed)."""
        requirement = self.core_requirement()
        if requirement is None:
            return True
        return requirement.matches(Version.parse(version))

    @model_validator(mode="after")
    def _validate_cron(self) -> Manifest:
        module_id = self.module.id
        seen: set[str] = set()
        for job in self.cron:
            parts = job.name.split(".")
            if len(parts) < 2 or not all(parts):
                raise ValueError(f"cron name {job.name!r} must have the form module.name")
            if parts[0] != module_id:
                raise ValueError(
                    f"cron name {job.name!r} is outside the module namespace {module_id!r}"
                )
            if job.name in seen:
                raise ValueError(f"duplicate cron name {job.name!r}")
            seen.add(job.name)
            if job.interval_seconds < 1:
                raise ValueError(f"cron {job.name!r} interval_seconds must be >= 1")
        return self

    @model_validator(mode="after")
    def _validate_config(self) -> Manifest:
        module_id = self.module.id
        seen: set[str] = set()
        for field in self.config:
            parts = field.key.split(".")
            if len(parts) < 2 or not all(parts):
                raise ValueError(f"config key {field.key!r} must have the form module.name")
            if parts[0] != module_id:
                raise ValueError(
                    f"config key {field.key!r} is outside the module namespace {module_id!r}"
                )
            if field.key in seen:
                raise ValueError(f"duplicate config key {field.key!r}")
            seen.add(field.key)
            if field.type not in CONFIG_FIELD_TYPES:
                raise ValueError(
                    f"config field {field.key!r} has unknown type {field.type!r}"
                )
            if field.type == "select" and not field.options:
                raise ValueError(f"config select {field.key!r} must declare at least one option")
            if field.default is not None:
                if not _config_value_matches(field.type, field.default):
                    raise ValueError(
                        f"config default for {field.key!r} does not match type {field.type!r}"
                    )
                if field.type == "select" and field.default not in field.options:
                    raise ValueError(
                        f"config default for {field.key!r} must be one of its options"
                    )
            if field.permission is not None:
                pp = field.permission.split(".")
                if len(pp) != 3 or not all(pp):
                    raise ValueError(
                        f"config permission {field.permission!r} must have the form "
                        "module.resource.action"
                    )
                if pp[0] != module_id and field.permission != "core.modules.manage":
                    raise ValueError(
                        f"config permission {field.permission!r} is outside the module "
                        f"namespace {module_id!r}"
                    )
        return self

    @model_validator(mode="after")
    def _validate_ui(self) -> Manifest:
        module_id = self.module.id
        prefix = f"/{module_id}"

        def check_path(path: str) -> None:
            if path != prefix and not path.startswith(f"{prefix}/"):
                raise ValueError(
                    f"ui path {path!r} must live under the module namespace /{module_id}"
                )

        def check_icon(icon: str | None) -> None:
            if icon is not None and not ICON_SLUG_RE.match(icon):
                raise ValueError(f"ui icon {icon!r} must be a slug [a-z0-9-]")

        def check_permission(perm: str | None) -> None:
            if perm is None:
                return
            parts = perm.split(".")
            if len(parts) != 3 or not all(parts):
                raise ValueError(
                    f"ui permission {perm!r} must have the form module.resource.action"
                )
            if parts[0] != module_id:
                raise ValueError(
                    f"ui permission {perm!r} is outside the module namespace {module_id!r}"
                )

        if self.ui.entry is not None:
            check_path(self.ui.entry)
        for item in self.ui.nav:
            check_path(item.path)
            check_icon(item.icon)
            check_permission(item.permission)
        for widget in self.ui.dashboard:
            check_path(widget.path)
            check_icon(widget.icon)
            check_permission(widget.permission)
        for section in self.ui.settings:
            check_path(section.path)
            check_icon(section.icon)
            check_permission(section.permission)
        return self

    @model_validator(mode="after")
    def _validate_extensions(self) -> Manifest:
        """Mirror of the kernel-side validate_extensions: every target belongs
        to a DECLARED dependency, names/types are well formed, UI entries
        reference declared fields, and the hard cap holds."""
        module_id = self.module.id
        if not self.extensions.fields and not self.extensions.ui:
            return self
        if len(self.extensions.fields) > MAX_EXT_FIELDS:
            raise ValueError(f"a module may declare at most {MAX_EXT_FIELDS} extension fields")
        dependency_ids = {_dependency_module_id(spec) for spec in self.dependencies.modules}

        def parse_target(target: str) -> tuple[str, str]:
            module, sep, model = target.partition(".")
            if not sep:
                raise ValueError(f"extension target {target!r} must have the form module.model")
            if not MODULE_ID_RE.match(module) or not EXT_NAME_RE.match(model):
                raise ValueError(f"extension target {target!r} is malformed")
            if module == module_id:
                raise ValueError(
                    "a module extends OTHER modules; use regular columns for its own models"
                )
            if module not in dependency_ids:
                raise ValueError(
                    f"extension target {target!r} requires declaring {module!r} "
                    "in [dependencies] modules"
                )
            return module, model

        declared: dict[tuple[str, str], list[str]] = {}
        seen: set[tuple[str, str]] = set()
        for field in self.extensions.fields:
            module, model = parse_target(field.target)
            if not EXT_NAME_RE.match(field.name):
                raise ValueError(
                    f"extension field name {field.name!r} must match ^[a-z][a-z0-9_]{{0,63}}$"
                )
            if field.type not in EXT_FIELD_TYPES:
                raise ValueError(
                    f"extension field {field.name!r} has unknown type {field.type!r}"
                )
            if (field.target, field.name) in seen:
                raise ValueError(
                    f"duplicate extension field {field.name!r} for target {field.target!r}"
                )
            seen.add((field.target, field.name))
            if not field.label.strip():
                raise ValueError(f"extension field {field.name!r} needs a label")
            declared.setdefault((module, model), []).append(field.name)

        for entry in self.extensions.ui:
            target_model, sep, view = entry.target.rpartition(".")
            if not sep:
                raise ValueError(
                    f"extension ui target {entry.target!r} must have the form module.model.form"
                )
            if view != "form":
                raise ValueError(
                    f"extension ui target {entry.target!r}: only the form view "
                    "accepts contributions in v1"
                )
            known = declared.get(parse_target(target_model))
            if known is None:
                raise ValueError(
                    f"extension ui target {entry.target!r} has no declared fields"
                )
            for name in entry.fields:
                if name not in known:
                    raise ValueError(
                        f"extension ui references undeclared field {name!r} for {entry.target!r}"
                    )
            if entry.slot != "section:end":
                after = entry.slot.removeprefix("after:")
                if after == entry.slot or not EXT_NAME_RE.match(after):
                    raise ValueError(
                        f"extension ui slot {entry.slot!r} must be "
                        '"after:{field}" or "section:end"'
                    )
            if not entry.group_label.strip():
                raise ValueError("extension ui sections need a group_label")
        return self

    @model_validator(mode="after")
    def _validate_roles(self) -> Manifest:
        """[[roles]]: unique non-empty names of at most MAX_ROLE_NAME_LEN
        characters; at least one permission each, every one declared by this
        manifest in [[permissions]] and listed once (mirror of the kernel)."""
        declared = {perm.key for perm in self.permissions}
        names: set[str] = set()
        for role in self.roles:
            name = role.name.strip()
            if not name:
                raise ValueError("role name is required")
            if len(name) > MAX_ROLE_NAME_LEN:
                raise ValueError(
                    f"role name {name!r} is longer than {MAX_ROLE_NAME_LEN} characters"
                )
            if name.lower() in RESERVED_ROLE_NAMES:
                raise ValueError(f"role name {name!r} is reserved for a system role")
            if name in names:
                raise ValueError(f"duplicate role name {name!r}")
            names.add(name)
            if not role.permissions:
                raise ValueError(f"role {name!r} must grant at least one permission")
            seen: set[str] = set()
            for key in role.permissions:
                if key not in declared:
                    raise ValueError(
                        f"role {name!r} grants {key!r}, which this manifest does not "
                        "declare in [[permissions]]"
                    )
                if key in seen:
                    raise ValueError(f"role {name!r} lists permission {key!r} twice")
                seen.add(key)
        return self

    @model_validator(mode="after")
    def _validate_namespaces(self) -> Manifest:
        module_id = self.module.id
        for perm in self.permissions:
            parts = perm.key.split(".")
            if len(parts) != 3 or not all(parts):
                raise ValueError(
                    f"permission {perm.key!r} must have the form module.resource.action"
                )
            if parts[0] != module_id:
                raise ValueError(
                    f"permission {perm.key!r} is outside the module namespace {module_id!r}"
                )
        for event in self.events.emits:
            if not EVENT_RE.match(event) or not event.startswith(f"{module_id}."):
                raise ValueError(
                    f"emitted event {event!r} must have the form {module_id}.entity.action"
                )
        for event in self.events.listens:
            if not EVENT_RE.match(event):
                raise ValueError(
                    f"listened event {event!r} must have the form module.entity.action"
                )
        return self

    @classmethod
    def parse_toml(cls, source: str) -> Manifest:
        data: dict[str, Any] = tomllib.loads(source)
        return cls.model_validate(data)

    @classmethod
    def load(cls, path: Path) -> Manifest:
        return cls.parse_toml(path.read_text(encoding="utf-8"))

    def to_toml_string(self) -> str:
        # Round-trip is only needed for scaffolding; kernel receives the raw
        # file contents, never a re-serialization.
        raise NotImplementedError("send the raw novvus.toml content to the kernel")


def find_manifest(start: Path | None = None) -> Path:
    """Locate novvus.toml in `start` or its parents (like git does)."""
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        path = candidate / "novvus.toml"
        if path.is_file():
            return path
    raise FileNotFoundError("novvus.toml not found in this directory or any parent")

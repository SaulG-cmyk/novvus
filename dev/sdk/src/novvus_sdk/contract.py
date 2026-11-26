"""Version of the platform contract this SDK implements (frozen under ADR-001).

The kernel exposes the same number; a module built against one SDK line can
only run on a platform whose contract matches. It is reported through the
introspection endpoints (`/health`, `/_novvus/meta`) — never in the handshake
meta document, whose schema the kernel validates strictly.

The manifest constants below (ADR-001 Fase A) mirror the kernel-side
`novvus_common::contract`; the manifest parser validates against them.
"""

PLATFORM_API = 1

# `[manifest] api_version` values this SDK understands.
MANIFEST_API_VERSION = "novvus.dev/v1"

# `[manifest] kind` values this SDK understands.
MANIFEST_KIND = "module"

# Image platforms a module may declare in `[distribution] platforms`.
SUPPORTED_PLATFORMS = ("linux/amd64", "linux/arm64")

# `[distribution] visibility`: public registry vs. customer registry.
VISIBILITIES = ("standard", "private")

# `[distribution] channel` (informational for the registry).
CHANNELS = ("stable", "beta")

# `[entitlement] restricted_mode` values accepted by contract v1. Only
# read-only exists: `disabled` is deliberately not part of the contract until
# an organization-level export independent of the module runtime exists
# (ADR-001 D15).
RESTRICTED_MODES = ("read-only",)

# `[ui] mode`: `generic` is the only mode served by platform_api 1;
# `external` (module-served SPA in a sandboxed frame) is reserved for
# platform_api 2 and rejected today.
UI_MODES = ("generic", "external")

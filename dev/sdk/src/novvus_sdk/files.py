"""Attachment helper for module code (docs/FILES.md §6).

A thin, tenant-aware wrapper over the kernel's file APIs: modules never touch
the storage backend directly and may only manage attachments of their OWN
models (the kernel enforces both).

Usage inside a request or event handler::

    attachment = await module.files.attach(
        model="contacts", record_id=contact_id,
        filename="contrato.pdf", content=pdf_bytes,
    )
    listed = await module.files.list(model="contacts", record_id=contact_id)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from novvus_sdk.context import current_context

if TYPE_CHECKING:
    from novvus_sdk.app import NovvusModule
    from novvus_sdk.kernel import KernelClient


class FilesHelper:
    def __init__(self, module: NovvusModule) -> None:
        self._module = module

    def _kernel(self) -> KernelClient:
        kernel = self._module._kernel
        if kernel is None:
            raise RuntimeError("attachments require a kernel connection (offline mode)")
        return kernel

    def _org(self, org_id: UUID | None) -> UUID:
        return org_id or current_context().org_id

    async def attach(
        self,
        model: str,
        record_id: UUID,
        filename: str,
        content: bytes,
        org_id: UUID | None = None,
    ) -> dict[str, Any]:
        return await self._kernel().upload_file(
            self._org(org_id), self._module.id, model, record_id, filename, content
        )

    async def list(
        self, model: str, record_id: UUID, org_id: UUID | None = None
    ) -> list[dict[str, Any]]:
        return await self._kernel().list_files(
            self._org(org_id), self._module.id, model, record_id
        )

    async def download(self, attachment_id: UUID, org_id: UUID | None = None) -> bytes:
        return await self._kernel().download_file(self._org(org_id), attachment_id)

    async def delete(self, attachment_id: UUID, org_id: UUID | None = None) -> None:
        await self._kernel().delete_file(self._org(org_id), attachment_id)

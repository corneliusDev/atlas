"""Read-model protocols the HTTP layer depends on, beyond the frozen ``atlas.ports``.

``atlas.ports`` defines SearchService / GraphService only. The document view, progress tray,
vault list, health check and upload "unchanged" flag need small read-only ports too; they are
defined here (not in ports.py, which is a frozen contract) so routes can be tested with fakes.
"""

from __future__ import annotations

from typing import Protocol

from atlas.http.dto import DocumentDetail, HealthResponse, JobsStatusResponse, VaultDto
from atlas.types import ContentHash, DocumentId, VaultId, VaultPath


class DocumentReader(Protocol):
    def document(self, vault: VaultId, document_id: DocumentId) -> DocumentDetail | None: ...
    def exists(self, vault: VaultId, document_id: DocumentId) -> bool: ...


class JobsStatusReader(Protocol):
    def status(self, vault: VaultId, limit: int) -> JobsStatusResponse: ...


class VaultReader(Protocol):
    def vaults(self) -> list[VaultDto]: ...
    def exists(self, vault: VaultId) -> bool: ...


class HealthCheck(Protocol):
    def check(self) -> HealthResponse: ...


class ContentHashLookup(Protocol):
    """Satisfied structurally by ``DocumentRepository`` (its ``current_hash`` method)."""

    def current_hash(self, vault: VaultId, path: VaultPath) -> ContentHash | None: ...

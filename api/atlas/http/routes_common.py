"""Shared route plumbing: FastAPI dependencies that hand each route its port.

Every provider reads ``request.app.state.services`` (the ``AppServices`` given to
``create_app``) and returns the port or None. Routes validate their input first, then call
``need(port, what)`` which answers 501 when the port is not wired. Tests swap a port either by
building ``create_app(AppServices(search=fake))`` or with
``app.dependency_overrides[get_search_service] = lambda: fake``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, NoReturn, TypeVar
from uuid import UUID

from fastapi import HTTPException, Query, Request

from atlas.http.dto import ErrorResponse
from atlas.ports import GraphService, JobQueue, LinkFeedbackRepository, SearchService, VaultScanner
from atlas.read.protocols import ContentHashLookup, DocumentReader, HealthCheck, JobsStatusReader, VaultReader
from atlas.types import DocumentId, DocumentPair, VaultId

if TYPE_CHECKING:
    from atlas.http.app import AppServices

T = TypeVar("T")


@dataclass(frozen=True)
class UploadConfig:
    """Where uploads land (``<root>/<vault_id>/<VaultPath>``) and the per-file size cap (UP-7)."""

    root: Path
    max_file_bytes: int = 5 * 1024 * 1024

VaultParam = Annotated[UUID, Query(description="Vault id; defaults to the seeded default vault")]

ERR: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    501: {"model": ErrorResponse},
}


def not_implemented(what: str) -> NoReturn:
    raise HTTPException(status_code=501, detail=f"{what} not implemented yet")


def need(port: T | None, what: str) -> T:
    if port is None:
        not_implemented(what)
    return port


def parse_pair(a: UUID, b: UUID) -> DocumentPair:
    if a == b:
        raise HTTPException(status_code=400, detail="a and b must be different documents")
    return DocumentPair.of(DocumentId(a), DocumentId(b))


def require_vault(vaults: VaultReader | None, vault: VaultId) -> None:
    """404 for an unknown vault when a VaultReader is wired; otherwise trust the caller."""
    if vaults is not None and not vaults.exists(vault):
        raise HTTPException(status_code=404, detail="vault not found")


# ---- dependency providers ------------------------------------------------------------
def get_services(request: Request) -> AppServices:
    services: AppServices = request.app.state.services
    return services


def get_queue(request: Request) -> JobQueue | None:
    return get_services(request).queue


def get_scanner(request: Request) -> VaultScanner | None:
    return get_services(request).scanner


def get_search_service(request: Request) -> SearchService | None:
    return get_services(request).search


def get_graph_service(request: Request) -> GraphService | None:
    return get_services(request).graph


def get_feedback_repo(request: Request) -> LinkFeedbackRepository | None:
    return get_services(request).feedback


def get_document_reader(request: Request) -> DocumentReader | None:
    return get_services(request).documents


def get_jobs_reader(request: Request) -> JobsStatusReader | None:
    return get_services(request).jobs


def get_vault_reader(request: Request) -> VaultReader | None:
    return get_services(request).vaults


def get_health_check(request: Request) -> HealthCheck | None:
    return get_services(request).health


def get_hash_lookup(request: Request) -> ContentHashLookup | None:
    return get_services(request).hashes


def get_upload_config(request: Request) -> UploadConfig | None:
    return get_services(request).uploads

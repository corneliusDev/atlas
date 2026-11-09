"""Composition helper for the read side, for whoever owns the api composition root.

    from atlas.http.app import AppServices, create_app
    read = build_read_services(settings, connect_factory(settings.database_url), embedder, embeddings_ok)
    app = create_app(AppServices(queue=..., scanner=..., feedback=..., hashes=document_repo, **read.as_kwargs()))
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from atlas.config import Settings
from atlas.http.routes_common import UploadConfig
from atlas.ports import EmbeddingModel
from atlas.read.db import Connect
from atlas.read.documents import FileRoots, PgDocumentReader
from atlas.read.graph import PgGraphService
from atlas.read.health import PgHealthCheck
from atlas.read.jobs import PgJobsStatusReader
from atlas.read.search import PgSearchService
from atlas.read.vaults import PgVaultReader
from atlas.types import DEFAULT_VAULT_ID


@dataclass(frozen=True)
class ReadServices:
    search: PgSearchService
    graph: PgGraphService
    documents: PgDocumentReader
    jobs: PgJobsStatusReader
    vaults: PgVaultReader
    health: PgHealthCheck
    uploads: UploadConfig

    def as_kwargs(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


def build_read_services(
    settings: Settings,
    connect: Connect,
    embedder: EmbeddingModel,
    embeddings_ok: Callable[[], bool],
    version: str = "0.1.0",
) -> ReadServices:
    roots = FileRoots.from_settings(vault_root=settings.vault_root, uploads_root=settings.uploads_root)
    return ReadServices(
        search=PgSearchService(connect=connect, embedder=embedder),
        graph=PgGraphService(connect=connect),
        documents=PgDocumentReader(connect=connect, roots=roots),
        jobs=PgJobsStatusReader(connect=connect),
        vaults=PgVaultReader(connect=connect, vault_roots={DEFAULT_VAULT_ID: settings.vault_root}),
        health=PgHealthCheck(
            connect=connect,
            embeddings_ok=embeddings_ok,
            llm_model=None if settings.embeddings_only else settings.llm_model,
            version=version,
        ),
        uploads=UploadConfig(root=settings.uploads_root, max_file_bytes=settings.max_file_bytes),
    )

"""Runtime settings (env vars; .env supported)."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    database_url: str = "postgresql://atlas:atlas@localhost:5432/atlas"
    ollama_url: str = "http://localhost:11434"
    embedding_model: str = "nomic-embed-text"
    embedding_dim: int = 768
    embed_timeout_s: float = 60.0

    anthropic_api_key: str | None = None
    llm_model: str = Field(default="claude-opus-5-5", validation_alias="ATLAS_LLM_MODEL")
    llm_timeout_s: float = 120.0
    # Embeddings-only mode: no Anthropic calls; summaries/topics/reasons/labels stay empty.
    embeddings_only: bool = Field(default=False, validation_alias="ATLAS_EMBEDDINGS_ONLY")

    vault_root: Path = Path("/vault")  # read-only mount (origin="vault")
    uploads_root: Path = Path("/uploads")  # files land at <uploads_root>/<vault_id>/<VaultPath>
    max_file_bytes: int = 5 * 1024 * 1024

    link_top_k: int = 8
    link_threshold: float = 0.55
    knn_candidates: int = 24  # nearest_documents k before re-scoring
    topic_merge_threshold: float = 0.88
    job_lease_s: int = 300
    job_max_attempts: int = 3
    worker_poll_s: float = 1.0
    worker_concurrency: int = 2  # job threads per worker process (env WORKER_CONCURRENCY)

    def require_llm_key(self) -> None:
        """Called at api/worker startup: missing key is fatal unless embeddings-only."""
        if not self.embeddings_only and not self.anthropic_api_key:
            raise SystemExit("ANTHROPIC_API_KEY is required (or set ATLAS_EMBEDDINGS_ONLY=true)")


def get_settings() -> Settings:
    return Settings()

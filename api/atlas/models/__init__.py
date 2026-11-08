"""Model adapters for atlas.ports.EmbeddingModel / LanguageModel, plus a factory from Settings.

* ``OllamaEmbeddingModel`` (ollama.py): Ollama ``/api/embed``, nomic-embed-text, one instance per
  ``EmbeddingPurpose`` (DOCUMENT for indexing, QUERY for search).
* ``AnthropicLanguageModel`` (anthropic_llm.py): Claude via the official ``anthropic`` SDK.
* ``EmbeddingsOnlyLanguageModel`` (null.py): no-network LanguageModel for ATLAS_EMBEDDINGS_ONLY.
* ``BatchSummarizer`` (batch.py): optional Message Batches helper for bulk imports.

Wiring: the worker uses ``build_models(settings).document_embedder`` + ``.language_model``; the
api's SearchService uses ``.query_embedder``.
"""

from __future__ import annotations

from dataclasses import dataclass

import anthropic

from atlas.config import Settings
from atlas.models.anthropic_llm import AnthropicLanguageModel, RefusalFallback
from atlas.models.batch import BatchSummarizer, SummaryBatch
from atlas.models.null import EmbeddingsOnlyLanguageModel
from atlas.models.ollama import EmbeddingPurpose, OllamaEmbeddingModel
from atlas.ports import EmbeddingModel, LanguageModel

__all__ = [
    "AnthropicLanguageModel",
    "BatchSummarizer",
    "EmbeddingPurpose",
    "EmbeddingsOnlyLanguageModel",
    "ModelAdapters",
    "OllamaEmbeddingModel",
    "RefusalFallback",
    "SummaryBatch",
    "build_anthropic_client",
    "build_batch_summarizer",
    "build_embedding_model",
    "build_language_model",
    "build_models",
]


@dataclass(frozen=True)
class ModelAdapters:
    document_embedder: EmbeddingModel
    query_embedder: EmbeddingModel
    language_model: LanguageModel


def build_embedding_model(settings: Settings, purpose: EmbeddingPurpose) -> OllamaEmbeddingModel:
    return OllamaEmbeddingModel(
        settings.ollama_url,
        purpose,
        model=settings.embedding_model,
        dimensions=settings.embedding_dim,
        timeout_s=settings.embed_timeout_s,
    )


def build_anthropic_client(settings: Settings) -> anthropic.Anthropic:
    """The SDK resolves credentials from the environment (ANTHROPIC_API_KEY, ...) unless a key
    is configured explicitly. SDK retries (429/5xx/connection) stay at their default."""
    if settings.anthropic_api_key:
        return anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=settings.llm_timeout_s)
    return anthropic.Anthropic(timeout=settings.llm_timeout_s)


def build_language_model(settings: Settings) -> LanguageModel:
    if settings.embeddings_only:
        return EmbeddingsOnlyLanguageModel()
    return AnthropicLanguageModel(build_anthropic_client(settings), model=settings.llm_model)


def build_batch_summarizer(settings: Settings) -> BatchSummarizer | None:
    """None in embeddings-only mode (nothing may leave the machine)."""
    if settings.embeddings_only:
        return None
    return BatchSummarizer(build_anthropic_client(settings), model=settings.llm_model)


def build_models(settings: Settings) -> ModelAdapters:
    return ModelAdapters(
        document_embedder=build_embedding_model(settings, EmbeddingPurpose.DOCUMENT),
        query_embedder=build_embedding_model(settings, EmbeddingPurpose.QUERY),
        language_model=build_language_model(settings),
    )

"""EmbeddingModel adapter for Ollama's ``POST /api/embed`` (nomic-embed-text, 768-d).

nomic-embed-text is trained with task prefixes, so each adapter instance has a fixed
``EmbeddingPurpose``: the pipeline embeds chunks/summaries/topics with a DOCUMENT instance
("search_document: ") and the search route embeds queries with a QUERY instance
("search_query: "). The purpose is a constructor enum, not a per-call flag, so the port stays
``embed(texts)``.

Errors: connection failures, non-2xx responses (including "model not found", i.e. not pulled
yet) and malformed / wrong-dimension responses raise ``ModelUnavailableError``; httpx timeouts
raise ``ModelTimeoutError("embed")``.
"""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Any, Sequence

import httpx

from atlas.ports import ModelTimeoutError, ModelUnavailableError
from atlas.types import Embedding

DEFAULT_MODEL = "nomic-embed-text"
DEFAULT_DIM = 768
DEFAULT_BATCH_SIZE = 32


class EmbeddingPurpose(StrEnum):
    DOCUMENT = "document"
    QUERY = "query"

    @property
    def prefix(self) -> str:
        return "search_document: " if self is EmbeddingPurpose.DOCUMENT else "search_query: "


class OllamaEmbeddingModel:
    """Implements atlas.ports.EmbeddingModel. Pass ``client`` to inject a transport in tests."""

    def __init__(
        self,
        base_url: str,
        purpose: EmbeddingPurpose,
        *,
        model: str = DEFAULT_MODEL,
        dimensions: int = DEFAULT_DIM,
        timeout_s: float = 60.0,
        batch_size: int = DEFAULT_BATCH_SIZE,
        client: httpx.Client | None = None,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        self._purpose = purpose
        self._model = model
        self._dimensions = dimensions
        self._batch_size = batch_size
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_s, connect=min(5.0, timeout_s)),
        )
        self._base_url = base_url

    @property
    def purpose(self) -> EmbeddingPurpose:
        return self._purpose

    def close(self) -> None:
        self._client.close()

    def embed(self, texts: Sequence[str]) -> list[Embedding]:
        result: list[Embedding] = []
        for start in range(0, len(texts), self._batch_size):
            result.extend(self._embed_batch(texts[start : start + self._batch_size]))
        return result

    def _embed_batch(self, texts: Sequence[str]) -> list[Embedding]:
        payload = {
            "model": self._model,
            "input": [self._purpose.prefix + t for t in texts],
            "truncate": True,  # over-long input is cut to the model's context, not an error
        }
        try:
            response = self._client.post("/api/embed", json=payload)
        except httpx.TimeoutException as exc:
            raise ModelTimeoutError("embed", f"ollama timed out: {exc}") from exc
        except httpx.TransportError as exc:
            raise ModelUnavailableError(f"ollama unreachable at {self._base_url}: {exc}") from exc

        if response.status_code != 200:
            raise ModelUnavailableError(
                f"ollama /api/embed returned {response.status_code}: {_error_text(response)}"
                + (f" (run: ollama pull {self._model})" if response.status_code == 404 else "")
            )
        try:
            body: Any = response.json()
        except ValueError as exc:
            raise ModelUnavailableError(f"ollama returned non-JSON: {exc}") from exc
        vectors = body.get("embeddings") if isinstance(body, dict) else None
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            got = len(vectors) if isinstance(vectors, list) else "none"
            raise ModelUnavailableError(f"ollama returned {got} embeddings for {len(texts)} inputs")
        return [self._check(v) for v in vectors]

    def _check(self, vector: Any) -> Embedding:
        if not isinstance(vector, list) or len(vector) != self._dimensions:
            size = len(vector) if isinstance(vector, list) else type(vector).__name__
            raise ModelUnavailableError(
                f"ollama model {self._model} returned a {size}-d vector, expected {self._dimensions}"
            )
        out = tuple(float(x) for x in vector)
        if not all(math.isfinite(x) for x in out):
            raise ModelUnavailableError("ollama returned a non-finite embedding")
        return out


def _error_text(response: httpx.Response) -> str:
    try:
        body = response.json()
        if isinstance(body, dict) and "error" in body:
            return str(body["error"])
    except ValueError:
        pass
    return response.text[:200]

"""LanguageModel adapter backed by the Anthropic Messages API (official ``anthropic`` SDK).

One request per method, always ``client.messages.parse`` with a Pydantic output model
(structured outputs via ``output_config.format``), ``output_config.effort`` (default ``low``),
and the stable ``SYSTEM_PROMPT`` carrying a ``cache_control`` breakpoint. No sampling
parameters and no thinking budget are ever sent: Claude Opus 5.5 thinks adaptively and effort
is the only depth control.

Error contract (atlas.ports.LanguageModel):

* Enrichment failures never raise. ``stop_reason`` ``refusal`` / ``max_tokens``, output that
  fails validation, and 4xx errors a retry cannot fix (400/413/422) give the empty value:
  ``summarize`` -> NoteSummary(summary=""), list methods -> ``[]``.
* ``RateLimitError``, 5xx/529, auth/permission/model-not-found (a deployment problem the user
  must fix) and ``APIConnectionError`` -- all after the SDK's own retries -- raise
  ``ModelUnavailableError``. ``APITimeoutError`` (and HTTP 408) raises ``ModelTimeoutError``.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any, Literal, Sequence, TypeVar

import anthropic
import pydantic
from anthropic.types import TextBlockParam

from atlas.models.prompts import (
    SYSTEM_PROMPT,
    ClusterLabelsOut,
    LinkReasonsOut,
    SummaryOut,
    TopicsOut,
    empty_summary,
    explain_links_prompt,
    label_clusters_prompt,
    summarize_prompt,
    to_cluster_labels,
    to_link_reasons,
    to_note_summary,
    to_topic_mentions,
    topics_prompt,
)
from atlas.ports import ModelPortError, ModelTimeoutError, ModelUnavailableError
from atlas.types import (
    ClusterLabel,
    ClusterSample,
    LinkEvidence,
    LinkReason,
    ModelStep,
    NoteSummary,
    ParsedNote,
    TopicMention,
)

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_MAX_TOKENS = 16_000  # non-streaming ceiling; outputs here are a few hundred tokens
Effort = Literal["low", "medium", "high", "xhigh", "max"]

OutT = TypeVar("OutT", bound=pydantic.BaseModel)

# Server-side refusal fallback ("fallbacks": "default", beta server-side-fallback-2026-07-01).
# Only these models accept the scalar "default" form; others (e.g. Haiku) must not send it.
SERVER_FALLBACK_BETA = "server-side-fallback-2026-07-01"
SERVER_FALLBACK_MODELS = frozenset(
    {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-fable-5", "claude-sonnet-5-5"}
)

_UNAVAILABLE_STATUS = frozenset({401, 403, 404, 409, 429})


class RefusalFallback(StrEnum):
    """What to do when the model's safety classifier declines a request."""

    SERVER_DEFAULT = "server_default"  # let the API re-run it on Anthropic's recommended model
    NONE = "none"  # take the refusal as-is (-> empty enrichment)


def system_blocks() -> list[TextBlockParam]:
    return [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]


def port_error_for(step: ModelStep, exc: anthropic.APIError) -> ModelPortError | None:
    """Translate an SDK error (raised after the SDK's own retries) into the port exception to
    raise, or ``None`` when it is an enrichment failure that a retry cannot fix (400/413/422,
    unexpected response shape)."""
    if isinstance(exc, anthropic.APITimeoutError):
        return ModelTimeoutError(step, str(exc))
    if isinstance(exc, anthropic.APIConnectionError):
        return ModelUnavailableError(f"anthropic unreachable during {step}: {exc}")
    if isinstance(exc, anthropic.APIStatusError):
        if exc.status_code == 408:
            return ModelTimeoutError(step, str(exc))
        if exc.status_code >= 500 or exc.status_code in _UNAVAILABLE_STATUS:
            return ModelUnavailableError(f"anthropic {exc.status_code} during {step}: {exc.message}")
    return None


class AnthropicLanguageModel:
    """Implements atlas.ports.LanguageModel. Inject the client (tests pass a stub)."""

    def __init__(
        self,
        client: anthropic.Anthropic,
        *,
        model: str = DEFAULT_MODEL,
        effort: Effort = "low",
        max_tokens: int = DEFAULT_MAX_TOKENS,
        refusal_fallback: RefusalFallback = RefusalFallback.SERVER_DEFAULT,
    ) -> None:
        self._client = client
        self._model = model
        self._effort: Effort = effort
        self._max_tokens = max_tokens
        self._system = system_blocks()
        self._extra: dict[str, Any] = {}
        if refusal_fallback is RefusalFallback.SERVER_DEFAULT and model in SERVER_FALLBACK_MODELS:
            self._extra = {
                "extra_headers": {"anthropic-beta": SERVER_FALLBACK_BETA},
                "extra_body": {"fallbacks": "default"},
            }

    @property
    def model(self) -> str:
        return self._model

    # ---- LanguageModel ------------------------------------------------------------------
    def summarize(self, note: ParsedNote) -> NoteSummary:
        out = self._call("summarize", summarize_prompt(note), SummaryOut)
        return empty_summary(note) if out is None else to_note_summary(out, note.title)

    def extract_topics(self, note: ParsedNote) -> list[TopicMention]:
        out = self._call("topics", topics_prompt(note), TopicsOut)
        return [] if out is None else to_topic_mentions(out)

    def explain_links(self, pairs: Sequence[LinkEvidence]) -> list[LinkReason]:
        if not pairs:
            return []
        out = self._call("explain_links", explain_links_prompt(pairs), LinkReasonsOut)
        return [] if out is None else to_link_reasons(out, pairs)

    def label_clusters(self, samples: Sequence[ClusterSample]) -> list[ClusterLabel]:
        if not samples:
            return []
        out = self._call("label_clusters", label_clusters_prompt(samples), ClusterLabelsOut)
        return [] if out is None else to_cluster_labels(out, samples)

    # ---- the single request ---------------------------------------------------------------
    def _call(self, step: ModelStep, prompt: str, output: type[OutT]) -> OutT | None:
        try:
            response = self._client.messages.parse(
                model=self._model,
                max_tokens=self._max_tokens,
                system=self._system,
                messages=[{"role": "user", "content": prompt}],
                output_format=output,
                output_config={"effort": self._effort},
                **self._extra,
            )
        except pydantic.ValidationError as exc:
            # Truncated or refused text that isn't valid JSON for the schema.
            log.warning("llm %s: output failed validation, storing no enrichment: %s", step, exc.error_count())
            return None
        except anthropic.APIError as exc:
            raised = port_error_for(step, exc)
            if raised is not None:
                raise raised from exc
            log.warning("llm %s: request rejected, storing no enrichment: %s", step, exc)
            return None

        stop = response.stop_reason
        if stop == "refusal":
            category = getattr(response.stop_details, "category", None)
            log.info("llm %s: model declined (category=%s), storing no enrichment", step, category)
            return None
        if stop == "max_tokens":
            log.warning("llm %s: hit max_tokens=%d, storing no enrichment", step, self._max_tokens)
            return None
        parsed = response.parsed_output
        if parsed is None:
            log.warning("llm %s: no structured output in response (stop_reason=%s)", step, stop)
        return parsed

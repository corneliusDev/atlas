"""Optional bulk-import helper: note summaries through the Message Batches API (50% cheaper,
asynchronous, usually done within an hour). Isolated and unused by default; the worker can use
it for a large first import and hand the results to the pipeline later.

Flow: ``handle = summarizer.submit(notes)`` -> persist ``handle`` (it is a plain pydantic model)
-> ``summarizer.is_done(handle)`` until True -> ``summarizer.results(handle)``.

Requests use the same system prompt, effort and output schema as
``AnthropicLanguageModel.summarize``. Server-side refusal fallbacks are not sent (the Batches
API rejects them). Results are keyed by ``custom_id``, never by position; failed, refused,
truncated, expired or invalid items are omitted (the caller can fall back to
``AnthropicLanguageModel.summarize`` for those paths).
"""

from __future__ import annotations

import logging
from typing import Sequence

import anthropic
import pydantic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

from atlas.models.anthropic_llm import DEFAULT_MAX_TOKENS, DEFAULT_MODEL, Effort, port_error_for, system_blocks
from atlas.models.prompts import SummaryOut, summarize_prompt, to_note_summary
from atlas.ports import ModelPortError, ModelUnavailableError
from atlas.types import Frozen, NoteSummary, ParsedNote, VaultPath

log = logging.getLogger(__name__)

MAX_BATCH_REQUESTS = 100_000


class BatchItem(Frozen):
    custom_id: str
    path: VaultPath
    title: str


class SummaryBatch(Frozen):
    batch_id: str
    items: tuple[BatchItem, ...]


class BatchSummarizer:
    def __init__(
        self,
        client: anthropic.Anthropic,
        *,
        model: str = DEFAULT_MODEL,
        effort: Effort = "low",
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self._client = client
        self._model = model
        self._effort: Effort = effort
        self._max_tokens = max_tokens
        self._schema = anthropic.transform_schema(SummaryOut)

    def submit(self, notes: Sequence[ParsedNote]) -> SummaryBatch:
        if not notes:
            raise ValueError("submit needs at least one note")
        if len(notes) > MAX_BATCH_REQUESTS:
            raise ValueError(f"at most {MAX_BATCH_REQUESTS} notes per batch")
        items = tuple(BatchItem(custom_id=f"note-{i}", path=n.path, title=n.title) for i, n in enumerate(notes))
        requests = [
            Request(
                custom_id=item.custom_id,
                params=MessageCreateParamsNonStreaming(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    system=system_blocks(),
                    messages=[{"role": "user", "content": summarize_prompt(note)}],
                    output_config={
                        "effort": self._effort,
                        "format": {"type": "json_schema", "schema": self._schema},
                    },
                ),
            )
            for item, note in zip(items, notes, strict=True)
        ]
        try:
            batch = self._client.messages.batches.create(requests=requests)
        except anthropic.APIError as exc:
            raise port_error_for("summarize", exc) or _unavailable(exc) from exc
        return SummaryBatch(batch_id=batch.id, items=items)

    def is_done(self, handle: SummaryBatch) -> bool:
        try:
            batch = self._client.messages.batches.retrieve(handle.batch_id)
        except anthropic.APIError as exc:
            raise port_error_for("summarize", exc) or _unavailable(exc) from exc
        return batch.processing_status == "ended"

    def results(self, handle: SummaryBatch) -> dict[VaultPath, NoteSummary]:
        by_id = {item.custom_id: item for item in handle.items}
        out: dict[VaultPath, NoteSummary] = {}
        try:
            for entry in self._client.messages.batches.results(handle.batch_id):
                item = by_id.get(entry.custom_id)
                if item is None:
                    continue
                summary = self._summary_from(entry.result, item)
                if summary is not None:
                    out[item.path] = summary
        except anthropic.APIError as exc:
            raise port_error_for("summarize", exc) or _unavailable(exc) from exc
        return out

    @staticmethod
    def _summary_from(result: object, item: BatchItem) -> NoteSummary | None:
        if getattr(result, "type", None) != "succeeded":
            log.info("batch %s: %s", item.path, getattr(result, "type", "unknown"))
            return None
        message = getattr(result, "message")
        if message.stop_reason in ("refusal", "max_tokens"):
            log.info("batch %s: stop_reason=%s, no summary", item.path, message.stop_reason)
            return None
        text = next((b.text for b in message.content if b.type == "text"), None)
        if text is None:
            return None
        try:
            parsed = SummaryOut.model_validate_json(text)
        except pydantic.ValidationError:
            log.warning("batch %s: output failed validation", item.path)
            return None
        return to_note_summary(parsed, item.title)


def _unavailable(exc: anthropic.APIError) -> ModelPortError:
    return ModelUnavailableError(f"anthropic batches: {exc}")

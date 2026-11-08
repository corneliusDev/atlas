"""Factory, embeddings-only null object, Message Batches helper and the opt-in live smoke test."""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

import anthropic
import httpx2
import pytest

from atlas.config import Settings
from atlas.models import (
    AnthropicLanguageModel,
    BatchSummarizer,
    EmbeddingPurpose,
    EmbeddingsOnlyLanguageModel,
    OllamaEmbeddingModel,
    SummaryBatch,
    build_batch_summarizer,
    build_models,
)
from atlas.ports import LanguageModel, ModelUnavailableError
from atlas.types import ClusterId, ClusterSample, ContentHash, DocumentId, DocumentPair, LinkEvidence, ParsedNote, VaultPath


def note(path: str = "a.md", title: str = "A", body: str = "Pricing for the Pro tier.") -> ParsedNote:
    return ParsedNote(
        path=VaultPath(path), title=title, frontmatter={}, tags=(), wikilinks=(), headings=(),
        body=body, body_text=body, content_hash=ContentHash("0" * 64),
    )


# ---- factory ------------------------------------------------------------------------------
def test_factory_builds_ollama_and_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATLAS_EMBEDDINGS_ONLY", raising=False)
    s = Settings(ollama_url="http://ollama:11434", anthropic_api_key="sk-test", ATLAS_LLM_MODEL="claude-sonnet-5-5")  # type: ignore[call-arg]
    m = build_models(s)
    assert isinstance(m.document_embedder, OllamaEmbeddingModel) and m.document_embedder.purpose is EmbeddingPurpose.DOCUMENT
    assert isinstance(m.query_embedder, OllamaEmbeddingModel) and m.query_embedder.purpose is EmbeddingPurpose.QUERY
    assert isinstance(m.language_model, AnthropicLanguageModel) and m.language_model.model == "claude-sonnet-5-5"
    assert isinstance(build_batch_summarizer(s), BatchSummarizer)


def test_factory_default_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATLAS_LLM_MODEL", raising=False)
    monkeypatch.delenv("ATLAS_EMBEDDINGS_ONLY", raising=False)
    lm = build_models(Settings(anthropic_api_key="sk-test")).language_model
    assert isinstance(lm, AnthropicLanguageModel) and lm.model == "claude-opus-5-5"


def test_factory_embeddings_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATLAS_EMBEDDINGS_ONLY", "true")
    s = Settings()
    assert isinstance(build_models(s).language_model, EmbeddingsOnlyLanguageModel)
    assert build_batch_summarizer(s) is None


# ---- null object --------------------------------------------------------------------------
def test_embeddings_only_returns_empty_enrichment() -> None:
    lm: LanguageModel = EmbeddingsOnlyLanguageModel()
    s = lm.summarize(note(title="T"))
    assert (s.title, s.summary, s.tags) == ("T", "", ())
    assert lm.extract_topics(note()) == []
    pair = DocumentPair.of(DocumentId(uuid.uuid4()), DocumentId(uuid.uuid4()))
    assert lm.explain_links([LinkEvidence(pair=pair, a_title="a", b_title="b", a_passage="x", b_passage="y", score=0.9)]) == []
    assert lm.label_clusters([ClusterSample(cluster_id=ClusterId(uuid.uuid4()), titles=("a",), summaries=())]) == []


# ---- batch helper -------------------------------------------------------------------------
def _msg(text: str, stop: str = "end_turn") -> dict[str, Any]:
    return {
        "id": "msg", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": [{"type": "text", "text": text}], "stop_reason": stop, "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def _batch(status: str) -> dict[str, Any]:
    return {
        "id": "msgbatch_1", "type": "message_batch", "processing_status": status,
        "request_counts": {"processing": 0, "succeeded": 3, "errored": 1, "canceled": 0, "expired": 0},
        "created_at": "2026-11-08T00:00:00Z", "expires_at": "2026-11-09T00:00:00Z",
        "ended_at": None, "archived_at": None, "cancel_initiated_at": None,
        "results_url": "https://api.test/v1/messages/batches/msgbatch_1/results" if status == "ended" else None,
    }


class BatchApi:
    def __init__(self) -> None:
        self.created: dict[str, Any] | None = None
        self.status = "in_progress"

    def __call__(self, req: httpx2.Request) -> httpx2.Response:
        path = req.url.path
        if req.method == "POST" and path == "/v1/messages/batches":
            self.created = json.loads(req.content)
            return httpx2.Response(200, json=_batch("in_progress"))
        if path.endswith("/results"):
            lines = [
                {"custom_id": "note-1", "result": {"type": "succeeded", "message": _msg(json.dumps({"title": "B", "summary": "Two. Sentences.", "tags": ["X"]}))}},
                {"custom_id": "note-0", "result": {"type": "succeeded", "message": _msg(json.dumps({"title": "", "summary": "First.", "tags": []}))}},
                {"custom_id": "note-2", "result": {"type": "succeeded", "message": _msg('{"title": "tru', "max_tokens")}},
                {"custom_id": "note-3", "result": {"type": "errored", "error": {"type": "error", "error": {"type": "api_error", "message": "x"}}}},
                {"custom_id": "note-4", "result": {"type": "succeeded", "message": _msg("garbage")}},
            ]
            return httpx2.Response(200, text="\n".join(json.dumps(x) for x in lines), headers={"content-type": "application/binary"})
        if req.method == "GET":
            return httpx2.Response(200, json=_batch(self.status))
        return httpx2.Response(404, json={"type": "error", "error": {"type": "not_found_error", "message": path}})


def _client(handler: Any) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key="k", base_url="https://api.test", max_retries=0, http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))


def test_batch_submit_poll_results() -> None:
    api = BatchApi()
    bs = BatchSummarizer(_client(api))
    notes = [note(f"n{i}.md", f"Title {i}") for i in range(5)]
    handle = bs.submit(notes)
    assert handle.batch_id == "msgbatch_1"
    assert SummaryBatch.model_validate_json(handle.model_dump_json()) == handle  # persistable

    assert api.created is not None
    reqs = api.created["requests"]
    assert [r["custom_id"] for r in reqs] == [f"note-{i}" for i in range(5)]
    params = reqs[0]["params"]
    assert params["output_config"]["effort"] == "low" and params["output_config"]["format"]["type"] == "json_schema"
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
    for forbidden in ("temperature", "top_p", "thinking", "fallbacks"):
        assert forbidden not in params

    assert bs.is_done(handle) is False
    api.status = "ended"
    assert bs.is_done(handle) is True

    out = bs.results(handle)
    assert set(out) == {VaultPath("n0.md"), VaultPath("n1.md")}
    assert out[VaultPath("n1.md")].tags == ("x",)
    assert out[VaultPath("n0.md")].title == "Title 0"  # blank title falls back to the note's


def test_batch_errors_map_to_port_exceptions() -> None:
    bs = BatchSummarizer(_client(lambda _r: httpx2.Response(529, json={"type": "error", "error": {"type": "overloaded_error", "message": "busy"}})))
    with pytest.raises(ModelUnavailableError):
        bs.submit([note()])
    with pytest.raises(ValueError):
        bs.submit([])


# ---- opt-in live smoke test ---------------------------------------------------------------
@pytest.mark.skipif(
    os.environ.get("RUN_LIVE") != "1" or not os.environ.get("ANTHROPIC_API_KEY"),
    reason="live Anthropic call: set RUN_LIVE=1 and ANTHROPIC_API_KEY",
)
def test_live_anthropic_smoke() -> None:
    lm = AnthropicLanguageModel(anthropic.Anthropic(), model=os.environ.get("ATLAS_LLM_MODEL", "claude-opus-5-5"))
    n = note(title="Pricing", body="We compared seat-based and usage-based pricing for the Pro tier and chose usage-based billing.")
    s = lm.summarize(n)
    assert s.summary
    assert lm.extract_topics(n)

"""AnthropicLanguageModel against a real ``anthropic.Anthropic`` client whose HTTP transport is
mocked (httpx2.MockTransport, the SDK's HTTP library). This exercises the real SDK request
building, structured-output parsing and exception classes with canned API responses."""

from __future__ import annotations

import json
import uuid
from typing import Any, Callable

import anthropic
import httpx2
import pytest

from atlas.models.anthropic_llm import SERVER_FALLBACK_BETA, AnthropicLanguageModel, RefusalFallback
from atlas.models.prompts import MAX_NOTE_CHARS, SYSTEM_PROMPT
from atlas.ports import LanguageModel, ModelTimeoutError, ModelUnavailableError
from atlas.types import (
    ClusterId,
    ClusterSample,
    ContentHash,
    DocumentId,
    DocumentPair,
    LinkEvidence,
    ParsedNote,
    TopicKind,
    VaultPath,
)

Handler = Callable[[httpx2.Request], httpx2.Response]


def note(body: str = "We compared seat-based and usage-based pricing for the Pro tier.", title: str = "Pricing") -> ParsedNote:
    return ParsedNote(
        path=VaultPath("notes/pricing.md"),
        title=title,
        frontmatter={},
        tags=("pricing",),
        wikilinks=(),
        headings=(),
        body=body,
        body_text=body,
        content_hash=ContentHash("0" * 64),
    )


def message(payload: Any, *, stop_reason: str = "end_turn", text: str | None = None, **extra: Any) -> dict[str, Any]:
    content = [] if payload is None and text is None else [{"type": "text", "text": text if text is not None else json.dumps(payload)}]
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5},
        **extra,
    }


class Recorder:
    def __init__(self, respond: Callable[[httpx2.Request], httpx2.Response]) -> None:
        self.requests: list[httpx2.Request] = []
        self._respond = respond

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self._respond(request)

    @property
    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]


def make(respond: Handler, **kwargs: Any) -> tuple[AnthropicLanguageModel, Recorder]:
    rec = Recorder(respond)
    client = anthropic.Anthropic(
        api_key="test-key",
        base_url="https://api.test",
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(rec)),
    )
    return AnthropicLanguageModel(client, **kwargs), rec


def ok(payload: Any, **kw: Any) -> Handler:
    return lambda _req: httpx2.Response(200, json=message(payload, **kw))


def status(code: int, err_type: str = "api_error") -> Handler:
    return lambda _req: httpx2.Response(code, json={"type": "error", "error": {"type": err_type, "message": "boom"}})


def pair_of(i: int) -> DocumentPair:
    return DocumentPair.of(DocumentId(uuid.UUID(int=2 * i + 1)), DocumentId(uuid.UUID(int=2 * i + 2)))


def evidence(i: int) -> LinkEvidence:
    return LinkEvidence(pair=pair_of(i), a_title=f"A{i}", b_title=f"B{i}", a_passage="pricing tiers", b_passage="tier pricing", score=0.8)


def sample(i: int) -> ClusterSample:
    return ClusterSample(cluster_id=ClusterId(uuid.UUID(int=100 + i)), titles=(f"T{i}a", f"T{i}b"), summaries=("s1", "s2"))


# ---- protocol + request shape -------------------------------------------------------------
def test_satisfies_port() -> None:
    llm, _ = make(ok({}))
    port: LanguageModel = llm
    assert port is llm


def test_request_shape_structured_output_effort_cache_and_no_sampling_params() -> None:
    llm, rec = make(ok({"title": "Pricing", "summary": "One. Two.", "tags": []}))
    llm.summarize(note())
    req = rec.requests[0]
    body = rec.bodies[0]
    assert req.url.path == "/v1/messages"
    assert body["model"] == "claude-opus-5-5"
    assert body["output_config"]["effort"] == "low"
    fmt = body["output_config"]["format"]
    assert fmt["type"] == "json_schema" and set(fmt["schema"]["required"]) == {"title", "summary", "tags"}
    assert body["system"] == [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
    assert body["messages"][0]["role"] == "user" and "Task: summarize" in body["messages"][0]["content"]
    for forbidden in ("temperature", "top_p", "top_k", "thinking"):
        assert forbidden not in body
    # server-side refusal fallback is on by default for Opus 5.5
    assert body["fallbacks"] == "default"
    assert SERVER_FALLBACK_BETA in req.headers["anthropic-beta"]


def test_fallback_not_sent_when_disabled_or_model_unsupported() -> None:
    for kwargs in ({"refusal_fallback": RefusalFallback.NONE}, {"model": "claude-haiku-5-5"}):
        llm, rec = make(ok({"topics": []}), **kwargs)
        llm.extract_topics(note())
        assert "fallbacks" not in rec.bodies[0]
        assert SERVER_FALLBACK_BETA not in rec.requests[0].headers.get("anthropic-beta", "")


def test_system_prompt_is_identical_across_methods_for_caching() -> None:
    def respond(req: httpx2.Request) -> httpx2.Response:
        task = json.loads(req.content)["messages"][0]["content"]
        if "summarize" in task:
            return httpx2.Response(200, json=message({"title": "t", "summary": "s", "tags": []}))
        if "topics" in task:
            return httpx2.Response(200, json=message({"topics": []}))
        if "explain_links" in task:
            return httpx2.Response(200, json=message({"reasons": []}))
        return httpx2.Response(200, json=message({"labels": []}))

    llm, rec = make(respond)
    llm.summarize(note())
    llm.extract_topics(note())
    llm.explain_links([evidence(0)])
    llm.label_clusters([sample(0)])
    assert len(rec.requests) == 4  # one request per method
    assert len({json.dumps(b["system"]) for b in rec.bodies}) == 1


# ---- canned structured outputs ------------------------------------------------------------
def test_summarize_normalises_output() -> None:
    llm, _ = make(ok({"title": "  Pro  tier pricing ", "summary": "It compares models.\n It picks usage.", "tags": ["#Pricing", "SaaS Metrics", "pricing", ""]}))
    s = llm.summarize(note())
    assert s.title == "Pro tier pricing"
    assert s.summary == "It compares models. It picks usage."
    assert s.tags == ("pricing", "saas-metrics")


def test_summarize_blank_title_falls_back_to_note_title() -> None:
    llm, _ = make(ok({"title": " ", "summary": "x. y.", "tags": []}))
    assert llm.summarize(note(title="Mine")).title == "Mine"


def test_extract_topics_dedupes_clamps_and_maps_kind() -> None:
    llm, _ = make(
        ok(
            {
                "topics": [
                    {"name": "machine learning", "kind": "concept", "salience": 1.4, "aliases": ["ML", "machine learning"]},
                    {"name": "Machine Learning", "kind": "concept", "salience": 0.5, "aliases": []},
                    {"name": "Ada Lovelace", "kind": "person", "salience": -0.2, "aliases": []},
                    {"name": "Acme Corp", "kind": "org", "salience": 0.3, "aliases": []},
                    {"name": "  ", "kind": "concept", "salience": 0.3, "aliases": []},
                ]
            }
        )
    )
    topics = llm.extract_topics(note())
    assert [(t.name, t.kind, t.salience, t.aliases) for t in topics] == [
        ("machine learning", TopicKind.CONCEPT, 1.0, ("ML",)),
        ("Ada Lovelace", TopicKind.PERSON, 0.0, ()),
        ("Acme Corp", TopicKind.ORG, 0.3, ()),
    ]


def test_explain_links_matches_by_id_and_omits_unknown_or_missing() -> None:
    long_reason = "Both discuss " + "pricing " * 60
    llm, rec = make(
        ok(
            {
                "reasons": [
                    {"pair_id": "p2", "reason": "Both cover the Kyoto ryokan shortlist."},
                    {"pair_id": "p0", "reason": long_reason},
                    {"pair_id": "p9", "reason": "unknown id"},
                    {"pair_id": "p2", "reason": "duplicate"},
                ]
            }
        )
    )
    reasons = llm.explain_links([evidence(0), evidence(1), evidence(2)])
    assert [r.pair for r in reasons] == [pair_of(2), pair_of(0)]  # p1 omitted, order irrelevant
    assert reasons[0].reason == "Both cover the Kyoto ryokan shortlist."
    assert len(reasons[1].reason) <= 200 and reasons[1].reason.endswith("…")
    prompt = rec.bodies[0]["messages"][0]["content"]
    assert 'id="p0"' in prompt and 'id="p2"' in prompt and "A1" in prompt


def test_label_clusters_matches_by_id_and_limits_words() -> None:
    llm, _ = make(ok({"labels": [{"group_id": "g1", "label": "Japan Trip Planning And Logistics Extra"}, {"group_id": "g0", "label": "\"Pricing\""}]}))
    labels = llm.label_clusters([sample(0), sample(1)])
    assert {(lab.cluster_id, lab.label) for lab in labels} == {
        (sample(1).cluster_id, "Japan Trip Planning And"),
        (sample(0).cluster_id, "Pricing"),
    }


def test_empty_inputs_make_no_request() -> None:
    llm, rec = make(ok({}))
    assert llm.explain_links([]) == []
    assert llm.label_clusters([]) == []
    assert rec.requests == []


def test_long_note_is_capped_and_marked() -> None:
    llm, rec = make(ok({"topics": []}))
    llm.extract_topics(note(body="x" * (MAX_NOTE_CHARS + 500)))
    content = rec.bodies[0]["messages"][0]["content"]
    assert "[note truncated" in content and len(content) < MAX_NOTE_CHARS + 1000


# ---- stop_reason paths: never raise, empty enrichment -------------------------------------
@pytest.mark.parametrize(
    "handler",
    [
        ok(None, stop_reason="refusal", stop_details={"type": "refusal", "category": "cyber", "explanation": None}),
        ok({"title": "t", "summary": "s", "tags": []}, stop_reason="refusal"),
        ok(None, stop_reason="max_tokens", text='{"title": "Pri'),  # truncated JSON -> SDK ValidationError
        ok({"title": "t", "summary": "s", "tags": []}, stop_reason="max_tokens"),
        ok(None, text="not json at all"),
        ok({"wrong": "shape"}),
        ok(None),  # no content at all
    ],
)
def test_enrichment_failures_return_empty_values(handler: Handler) -> None:
    llm, _ = make(handler)
    s = llm.summarize(note(title="Kept"))
    assert s.summary == "" and s.tags == () and s.title == "Kept"
    assert llm.extract_topics(note()) == []
    assert llm.explain_links([evidence(0)]) == []
    assert llm.label_clusters([sample(0)]) == []


@pytest.mark.parametrize("code", [400, 413, 422])
def test_unfixable_request_errors_return_empty(code: int) -> None:
    llm, _ = make(status(code, "invalid_request_error"))
    assert llm.summarize(note()).summary == ""
    assert llm.extract_topics(note()) == []


# ---- transport/API errors: raise port exceptions ------------------------------------------
@pytest.mark.parametrize("code", [429, 500, 502, 503, 529, 401, 403, 404])
def test_retryable_and_deployment_errors_raise_unavailable(code: int) -> None:
    llm, _ = make(status(code))
    with pytest.raises(ModelUnavailableError) as info:
        llm.summarize(note())
    assert str(code) in info.value.detail


def test_connection_error_raises_unavailable() -> None:
    def boom(req: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=req)

    llm, _ = make(boom)
    with pytest.raises(ModelUnavailableError):
        llm.explain_links([evidence(0)])


@pytest.mark.parametrize(
    ("method", "step"),
    [("summarize", "summarize"), ("extract_topics", "topics"), ("explain_links", "explain_links"), ("label_clusters", "label_clusters")],
)
def test_timeout_raises_model_timeout_with_step(method: str, step: str) -> None:
    def slow(req: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=req)

    llm, _ = make(slow)
    arg: Any = {"summarize": note(), "extract_topics": note(), "explain_links": [evidence(0)], "label_clusters": [sample(0)]}[method]
    with pytest.raises(ModelTimeoutError) as info:
        getattr(llm, method)(arg)
    assert info.value.step == step


def test_http_408_raises_timeout() -> None:
    llm, _ = make(status(408, "timeout_error"))
    with pytest.raises(ModelTimeoutError):
        llm.label_clusters([sample(0)])


# ---- a hand-rolled stub client (no SDK transport at all) ----------------------------------
class _StubMessages:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _StubClient:
    def __init__(self, result: Any) -> None:
        self.messages = _StubMessages(result)


def test_stub_client_parsed_output_and_kwargs() -> None:
    from anthropic.types import ParsedMessage

    from atlas.models.prompts import SummaryOut

    parsed = ParsedMessage[SummaryOut].model_construct(
        **{**message(None), "content": [], "stop_reason": "end_turn"}
    )
    stub = _StubClient(parsed)
    llm = AnthropicLanguageModel(stub, model="claude-opus-5-5")  # type: ignore[arg-type]
    # no text block -> parsed_output None -> empty summary
    assert llm.summarize(note()).summary == ""
    call = stub.messages.calls[0]
    assert call["output_format"] is SummaryOut
    assert call["output_config"] == {"effort": "low"}
    assert "temperature" not in call and "top_p" not in call and "thinking" not in call

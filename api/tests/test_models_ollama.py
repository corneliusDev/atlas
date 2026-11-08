"""OllamaEmbeddingModel against httpx.MockTransport, plus an opt-in real-container check."""

from __future__ import annotations

import json
import os
from typing import Any, Callable

import httpx
import pytest

from atlas.models.ollama import EmbeddingPurpose, OllamaEmbeddingModel
from atlas.ports import EmbeddingModel, ModelTimeoutError, ModelUnavailableError

DIM = 768


def vec(seed: float) -> list[float]:
    return [seed] * DIM


class Recorder:
    def __init__(self, respond: Callable[[httpx.Request], httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._respond = respond

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._respond(request)

    @property
    def inputs(self) -> list[list[str]]:
        return [json.loads(r.content)["input"] for r in self.requests]


def echo(request: httpx.Request) -> httpx.Response:
    texts = json.loads(request.content)["input"]
    return httpx.Response(200, json={"model": "nomic-embed-text", "embeddings": [vec(float(len(t))) for t in texts]})


def make(respond: Callable[[httpx.Request], httpx.Response], purpose: EmbeddingPurpose = EmbeddingPurpose.DOCUMENT, **kw: Any) -> tuple[OllamaEmbeddingModel, Recorder]:
    rec = Recorder(respond)
    client = httpx.Client(base_url="http://ollama.test", transport=httpx.MockTransport(rec))
    return OllamaEmbeddingModel("http://ollama.test", purpose, client=client, **kw), rec


def test_satisfies_port() -> None:
    m, _ = make(echo)
    port: EmbeddingModel = m
    assert port is m


def test_document_prefix_model_and_endpoint() -> None:
    m, rec = make(echo)
    out = m.embed(["alpha", "beta"])
    req = rec.requests[0]
    body = json.loads(req.content)
    assert req.method == "POST" and req.url.path == "/api/embed"
    assert body["model"] == "nomic-embed-text"
    assert body["input"] == ["search_document: alpha", "search_document: beta"]
    assert len(out) == 2 and all(isinstance(v, tuple) and len(v) == DIM for v in out)
    assert out[0][0] == float(len("search_document: alpha"))


def test_query_prefix() -> None:
    m, rec = make(echo, EmbeddingPurpose.QUERY)
    m.embed(["pricing"])
    assert rec.inputs == [["search_query: pricing"]]


def test_batches_of_32_preserve_order() -> None:
    m, rec = make(echo)
    texts = [f"t{i:03d}" for i in range(70)]
    out = m.embed(texts)
    assert [len(b) for b in rec.inputs] == [32, 32, 6]
    assert [x.removeprefix("search_document: ") for b in rec.inputs for x in b] == texts
    assert len(out) == 70


def test_empty_input_makes_no_request() -> None:
    m, rec = make(echo)
    assert m.embed([]) == []
    assert rec.requests == []


def test_connection_error_raises_unavailable() -> None:
    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=req)

    m, _ = make(boom)
    with pytest.raises(ModelUnavailableError):
        m.embed(["x"])


@pytest.mark.parametrize("exc", [httpx.ReadTimeout, httpx.ConnectTimeout, httpx.PoolTimeout, httpx.WriteTimeout])
def test_timeouts_raise_model_timeout(exc: type[httpx.TimeoutException]) -> None:
    def slow(req: httpx.Request) -> httpx.Response:
        raise exc("slow", request=req)

    m, _ = make(slow)
    with pytest.raises(ModelTimeoutError) as info:
        m.embed(["x"])
    assert info.value.step == "embed"


def test_model_not_pulled_raises_unavailable_with_hint() -> None:
    m, _ = make(lambda _r: httpx.Response(404, json={"error": 'model "nomic-embed-text" not found, try pulling it first'}))
    with pytest.raises(ModelUnavailableError) as info:
        m.embed(["x"])
    assert "not found" in info.value.detail and "ollama pull nomic-embed-text" in info.value.detail


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="internal"),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"embeddings": [vec(1.0)]}),  # count mismatch for 2 inputs
        httpx.Response(200, json={"embeddings": [[1.0, 2.0], [1.0, 2.0]]}),  # wrong dimension
        httpx.Response(200, json={"nope": True}),
    ],
)
def test_bad_responses_raise_unavailable(response: httpx.Response) -> None:
    m, _ = make(lambda _r: response)
    with pytest.raises(ModelUnavailableError):
        m.embed(["a", "b"])


def test_rejects_bad_batch_size() -> None:
    with pytest.raises(ValueError):
        OllamaEmbeddingModel("http://x", EmbeddingPurpose.DOCUMENT, batch_size=0)


# ---- opt-in: real Ollama (e.g. docker run -p 11535:11434 ollama/ollama + pull nomic-embed-text)
OLLAMA_LIVE_URL = os.environ.get("ATLAS_TEST_OLLAMA_URL")


@pytest.mark.skipif(not OLLAMA_LIVE_URL, reason="set ATLAS_TEST_OLLAMA_URL to run against a real Ollama")
def test_live_ollama_embeddings() -> None:
    assert OLLAMA_LIVE_URL is not None
    docs = OllamaEmbeddingModel(OLLAMA_LIVE_URL, EmbeddingPurpose.DOCUMENT, timeout_s=120)
    query = OllamaEmbeddingModel(OLLAMA_LIVE_URL, EmbeddingPurpose.QUERY, timeout_s=120)
    d = docs.embed(["Usage-based pricing for the Pro tier", "Ryokan options in Kyoto for the spring trip"])
    (q,) = query.embed(["how should we price the pro plan"])
    assert all(len(v) == DIM for v in (*d, q))

    def cos(a: tuple[float, ...], b: tuple[float, ...]) -> float:
        num = sum(x * y for x, y in zip(a, b))
        return num / ((sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5))

    assert cos(q, d[0]) > cos(q, d[1])

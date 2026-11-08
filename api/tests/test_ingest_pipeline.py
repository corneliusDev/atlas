"""IngestPipelineImpl against the in-memory fakes: every branch of PRD Output 1."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

import pytest

from atlas.pipeline import FsFileReader, IngestPipelineImpl, PipelineConfig, content_hash_of
from atlas.ports import ModelTimeoutError, ModelUnavailableError
from atlas.testing.fakes import (
    FakeEmbeddingModel,
    FakeLanguageModel,
    InMemoryClusterRepository,
    InMemoryDocumentRepository,
)
from atlas.types import (
    DEFAULT_VAULT_ID,
    LinkEvidence,
    LinkReason,
    ModelTimeout,
    ModelUnavailable,
    NoteSummary,
    NotUtf8,
    ParsedNote,
    Recluster,
    Reclustered,
    Remove,
    Removed,
    Skipped,
    SkipReason,
    TopicKind,
    Upsert,
    VaultId,
    VaultPath,
    document_id_for,
    Indexed,
)

VAULT_DIR = Path(__file__).resolve().parents[2] / "samples" / "vault"
V = DEFAULT_VAULT_ID
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


@dataclass
class MemoryFiles:
    files: dict[tuple[str, str], bytes] = field(default_factory=dict)

    def put(self, path: str, text: str | bytes, origin: str = "vault") -> VaultPath:
        self.files[(origin, path)] = text.encode() if isinstance(text, str) else text
        return VaultPath(path)

    def read(self, vault: VaultId, path: VaultPath, origin: str) -> bytes | None:
        return self.files.get((origin, path))


@dataclass
class Harness:
    files: MemoryFiles
    docs: InMemoryDocumentRepository
    clusters: InMemoryClusterRepository
    embed: FakeEmbeddingModel
    llm: FakeLanguageModel
    pipeline: IngestPipelineImpl


def make(llm: FakeLanguageModel | None = None, files: object | None = None) -> Harness:
    mf = MemoryFiles()
    docs, clusters = InMemoryDocumentRepository(), InMemoryClusterRepository()
    embed, lang = FakeEmbeddingModel(), llm or FakeLanguageModel()
    pipeline = IngestPipelineImpl(
        files=files or mf,  # type: ignore[arg-type]
        documents=docs,
        clusters=clusters,
        embeddings=embed,
        language=lang,
        config=PipelineConfig(),
        clock=lambda: NOW,
    )
    return Harness(mf, docs, clusters, embed, lang, pipeline)


def upsert(path: str, origin: str = "vault") -> Upsert:
    return Upsert(vault=V, path=VaultPath(path), origin=origin)


NOTE = "---\ntags: [demo]\n---\n# Shared Ideas\n\nKnowledge graphs connect notes by meaning. #graphs\n\nSee [[Other Note#Part|other]].\n"


# ---- Upsert: new / unchanged / changed ----------------------------------------------------
def test_upsert_indexes_new_note_with_everything_in_the_aggregate() -> None:
    h = make()
    p = h.files.put("notes/a.md", NOTE)
    out = h.pipeline.run(upsert(p))
    assert isinstance(out, Indexed)
    assert out.document_id == document_id_for(V, p) and out.link_count == 0 and out.cluster_id is None
    agg = h.docs.docs[(V, p)]
    assert agg.content_hash == content_hash_of(NOTE.encode())
    assert agg.title == "Shared Ideas" and agg.origin == "vault" and agg.indexed_at == NOW
    assert agg.summary and agg.summary.startswith("Shared Ideas")
    assert {"demo", "graphs"} <= set(agg.tags)
    assert [(w.target_name, w.anchor) for w in agg.wiki_links] == [("Other Note", "Part")]
    tag_topics = {t.name for t in agg.topics if t.kind is TopicKind.TAG}
    assert tag_topics == {"demo", "graphs"}
    assert all(t.embedding is None for t in agg.topics if t.kind is TopicKind.TAG)
    assert all(t.embedding is not None for t in agg.topics if t.kind is not TopicKind.TAG)
    assert out.topic_count == len(agg.topics)
    assert len(agg.chunks) >= 1 and agg.chunks[0].heading_path == ("Shared Ideas",)
    assert agg.topic_merge_threshold == 0.88


def test_upsert_unchanged_hash_is_skipped_without_model_calls() -> None:
    h = make()
    p = h.files.put("a.md", NOTE)
    assert isinstance(h.pipeline.run(upsert(p)), Indexed)
    calls_before = (len(h.embed.calls), len(h.llm.calls))
    assert h.pipeline.run(upsert(p)) == Skipped(path=p, reason=SkipReason.UNCHANGED)
    assert (len(h.embed.calls), len(h.llm.calls)) == calls_before


def test_upsert_changed_file_reindexes_in_place_with_same_id() -> None:
    h = make()
    p = h.files.put("a.md", NOTE)
    first = h.pipeline.run(upsert(p))
    h.files.put("a.md", NOTE + "\nMore text.\n")
    second = h.pipeline.run(upsert(p))
    assert isinstance(first, Indexed) and isinstance(second, Indexed)
    assert first.document_id == second.document_id
    assert len(h.docs.docs) == 1
    assert h.docs.docs[(V, p)].content_hash == content_hash_of((NOTE + "\nMore text.\n").encode())


def test_upload_origin_is_read_and_recorded() -> None:
    h = make()
    p = h.files.put("up/a.md", NOTE, origin="upload")
    assert isinstance(h.pipeline.run(upsert(p, origin="upload")), Indexed)
    assert h.docs.docs[(V, p)].origin == "upload"


# ---- Superseded -------------------------------------------------------------------------------
class RacingLanguageModel(FakeLanguageModel):
    """Simulates another job saving a newer version of the file while this one runs."""

    docs: InMemoryDocumentRepository | None = None
    newer: object = None

    def summarize(self, note: ParsedNote) -> NoteSummary:
        if self.docs is not None and self.newer is not None:
            self.docs.docs[(V, note.path)] = self.newer  # type: ignore[assignment]
        return super().summarize(note)


def test_upsert_superseded_when_hash_changes_during_run() -> None:
    llm = RacingLanguageModel()
    h = make(llm=llm)
    p = h.files.put("a.md", NOTE)
    assert isinstance(h.pipeline.run(upsert(p)), Indexed)
    newer = h.docs.docs[(V, p)].model_copy(update={"content_hash": "f" * 64})
    llm.docs, llm.newer = h.docs, newer
    h.files.put("a.md", NOTE + "\nedit\n")
    assert h.pipeline.run(upsert(p)) == Skipped(path=p, reason=SkipReason.SUPERSEDED)
    assert h.docs.docs[(V, p)].content_hash == "f" * 64  # newer version untouched


# ---- Vanished / not UTF-8 ------------------------------------------------------------------------
def test_vanished_file_removes_document() -> None:
    h = make()
    p = h.files.put("a.md", NOTE)
    h.pipeline.run(upsert(p))
    del h.files.files[("vault", p)]
    assert h.pipeline.run(upsert(p)) == Removed(path=p)
    assert (V, p) not in h.docs.docs
    assert h.pipeline.run(upsert("never/existed.md")) == Removed(path=VaultPath("never/existed.md"))


def test_latin1_sample_is_not_utf8() -> None:
    h = make()
    rel = "cooking/recipes/Creme Brulee (latin1).md"
    p = h.files.put(rel, (VAULT_DIR / rel).read_bytes())
    assert h.pipeline.run(upsert(p)) == NotUtf8(path=p)
    assert h.docs.docs == {} and h.embed.calls == []


def test_bom_is_accepted() -> None:
    h = make()
    p = h.files.put("bom.md", b"\xef\xbb\xbf# Bom Title\n\nHello.\n")
    assert isinstance(h.pipeline.run(upsert(p)), Indexed)
    assert h.docs.docs[(V, p)].title == "Bom Title"


# ---- Model failures ---------------------------------------------------------------------------
def test_embedding_service_down_returns_model_unavailable() -> None:
    h = make()
    h.embed.fail_with = ModelUnavailableError("ollama unreachable")
    p = h.files.put("a.md", NOTE)
    assert h.pipeline.run(upsert(p)) == ModelUnavailable(detail="ollama unreachable")
    assert h.docs.docs == {}


def test_language_model_timeout_returns_model_timeout() -> None:
    h = make()
    h.llm.fail_with = ModelTimeoutError("summarize")
    p = h.files.put("a.md", NOTE)
    assert h.pipeline.run(upsert(p)) == ModelTimeout(step="summarize")
    assert h.docs.docs == {}


def test_recluster_with_language_model_down_returns_error() -> None:
    h = make()
    for i in range(4):
        h.pipeline.run(upsert(h.files.put(f"n{i}.md", f"# Note {i}\n\nbody {i}\n")))
    h.llm.fail_with = ModelUnavailableError("anthropic 529")
    assert h.pipeline.run(Recluster(vault=V)) == ModelUnavailable(detail="anthropic 529")
    assert h.clusters.assignments == {}


class BadOutputLanguageModel(FakeLanguageModel):
    """Enrichment failures per ports.py: empty summary, no topics, reasons omitted."""

    def summarize(self, note: ParsedNote) -> NoteSummary:
        return NoteSummary(title="", summary="")

    def extract_topics(self, note: ParsedNote) -> list:  # type: ignore[type-arg]
        return []

    def explain_links(self, pairs: Sequence[LinkEvidence]) -> list[LinkReason]:
        return []


def test_bad_llm_output_stores_none_and_never_fails() -> None:
    h = make(llm=BadOutputLanguageModel())
    a = h.files.put("a.md", "# Twin\n\nidentical body text\n")
    b = h.files.put("b.md", "# Twin\n\nidentical body text\n")
    h.pipeline.run(upsert(a))
    out = h.pipeline.run(upsert(b))
    assert isinstance(out, Indexed) and out.link_count == 1
    agg = h.docs.docs[(V, b)]
    assert agg.summary is None
    assert [t for t in agg.topics if t.kind is not TopicKind.TAG] == []
    assert agg.semantic_links[0].reason is None


# ---- Linking -----------------------------------------------------------------------------------
def test_similar_documents_get_semantic_link_with_reason_and_evidence() -> None:
    h = make()
    body = "# Twin\n\nKnowledge graphs connect notes by meaning.\n"
    a = h.files.put("a.md", body)
    b = h.files.put("b.md", body)
    c = h.files.put("c.md", "# Unrelated\n\nSourdough needs a lively starter.\n")
    h.pipeline.run(upsert(a))
    h.pipeline.run(upsert(c))
    out = h.pipeline.run(upsert(b))
    assert isinstance(out, Indexed) and out.link_count == 1
    (link,) = h.docs.docs[(V, b)].semantic_links
    ida, idb = document_id_for(V, a), document_id_for(V, b)
    assert {link.pair.a, link.pair.b} == {ida, idb}
    assert link.score > 0.99 and link.reason and "Twin" in link.reason
    chunk_a = h.docs.docs[(V, a)].chunks[0].id
    chunk_b = h.docs.docs[(V, b)].chunks[0].id
    assert link.evidence == ((chunk_a, chunk_b) if link.pair.a == ida else (chunk_b, chunk_a))


def test_title_falls_back_to_llm_suggestion_only_without_explicit_title() -> None:
    class Titler(FakeLanguageModel):
        def summarize(self, note: ParsedNote) -> NoteSummary:
            return NoteSummary(title="Suggested", summary="S.")

    h = make(llm=Titler())
    p1 = h.files.put("plain-name.md", "just text, no heading\n")
    p2 = h.files.put("h1.md", "# Real\n\ntext\n")
    h.pipeline.run(upsert(p1))
    h.pipeline.run(upsert(p2))
    assert h.docs.docs[(V, p1)].title == "Suggested"
    assert h.docs.docs[(V, p2)].title == "Real"


# ---- Remove ----------------------------------------------------------------------------------
def test_remove_is_idempotent() -> None:
    h = make()
    p = h.files.put("a.md", NOTE)
    h.pipeline.run(upsert(p))
    job = Remove(vault=V, path=p)
    assert h.pipeline.run(job) == Removed(path=p)
    assert h.pipeline.run(job) == Removed(path=p)
    assert h.docs.docs == {}


# ---- Recluster over the sample vault -----------------------------------------------------------
def test_sample_vault_index_then_recluster_then_new_doc_joins_cluster(tmp_path: Path) -> None:
    reader = FsFileReader(vault_root=VAULT_DIR, uploads_root=tmp_path)
    h = make(files=reader)
    outcomes = {}
    for f in sorted(VAULT_DIR.rglob("*.md")):
        rel = f.relative_to(VAULT_DIR).as_posix()
        outcomes[rel] = h.pipeline.run(upsert(rel))
    assert isinstance(outcomes["cooking/recipes/Creme Brulee (latin1).md"], NotUtf8)
    indexed = [o for o in outcomes.values() if isinstance(o, Indexed)]
    assert len(indexed) == 50
    welcome = h.docs.docs[(V, VaultPath("Welcome.md"))]
    assert "Competitor Teardown Q3" in {w.target_name for w in welcome.wiki_links}

    out = h.pipeline.run(Recluster(vault=V))
    assert isinstance(out, Reclustered) and out.cluster_count >= 2
    assignment = h.clusters.assignments[V]
    assert len(assignment.members) == 50
    labels = h.clusters.labels[V]
    assert {lab.cluster_id for lab in labels} == {c.cluster_id for c in assignment.centroids}
    assert "label_clusters" in h.llm.calls

    # Re-index after clustering: the doc is assigned to its nearest existing cluster.
    up = tmp_path / str(V) / "new.md"
    up.parent.mkdir(parents=True)
    up.write_text("# Fresh\n\nA fresh upload.\n")
    new = h.pipeline.run(upsert("new.md", origin="upload"))
    assert isinstance(new, Indexed)
    assert new.cluster_id in {c.cluster_id for c in assignment.centroids}


def test_recluster_empty_vault() -> None:
    h = make()
    assert h.pipeline.run(Recluster(vault=V)) == Reclustered(cluster_count=0)
    assert h.clusters.assignments[V].centroids == ()
    assert "label_clusters" not in h.llm.calls


def test_fs_reader_missing_and_escape(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    (tmp_path / "secret.md").write_text("x")
    (root / "link.md").symlink_to(tmp_path / "secret.md")
    reader = FsFileReader(vault_root=root, uploads_root=tmp_path / "uploads")
    assert reader.read(V, VaultPath("missing.md"), "vault") is None
    assert reader.read(V, VaultPath("link.md"), "vault") is None
    (root / "ok.md").write_text("ok")
    assert reader.read(V, VaultPath("ok.md"), "vault") == b"ok"


@pytest.mark.parametrize("step", ["embed", "summarize", "topics", "explain_links", "label_clusters"])
def test_every_timeout_step_maps_through(step: str) -> None:
    h = make()
    h.embed.fail_with = ModelTimeoutError(step)  # type: ignore[arg-type]
    p = h.files.put("a.md", NOTE)
    assert h.pipeline.run(upsert(p)) == ModelTimeout(step=step)

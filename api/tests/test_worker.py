"""Worker loop + FsVaultScanner against the in-memory fakes and the sample vault."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from atlas.pipeline import FsFileReader, IngestPipelineImpl, PipelineConfig
from atlas.testing.fakes import (
    FakeEmbeddingModel,
    FakeLanguageModel,
    InMemoryClusterRepository,
    InMemoryDocumentRepository,
    InMemoryJobQueue,
)
from atlas.types import (
    DEFAULT_VAULT_ID,
    IngestJob,
    IngestOutcome,
    JobState,
    ModelUnavailable,
    Recluster,
    Reclustered,
    Remove,
    Skipped,
    SkipReason,
    Upsert,
    VaultPath,
)
from atlas.worker import FsVaultScanner, Worker

VAULT_DIR = Path(__file__).resolve().parents[2] / "samples" / "vault"
V = DEFAULT_VAULT_ID


class Stack:
    def __init__(self, vault: Path, uploads: Path, max_file_bytes: int = 5 * 1024 * 1024) -> None:
        self.queue = InMemoryJobQueue()
        self.docs = InMemoryDocumentRepository()
        self.clusters = InMemoryClusterRepository()
        self.pipeline = IngestPipelineImpl(
            files=FsFileReader(vault, uploads),
            documents=self.docs,
            clusters=self.clusters,
            embeddings=FakeEmbeddingModel(),
            language=FakeLanguageModel(),
            config=PipelineConfig(),
        )
        self.scanner = FsVaultScanner(
            queue=self.queue, documents=self.docs, roots={V: vault}, max_file_bytes=max_file_bytes
        )

    def worker(self, concurrency: int = 2) -> Worker:
        return Worker(queue=self.queue, pipeline=self.pipeline, poll_s=0.01,
                      concurrency=concurrency, exit_when_idle=True)

    def drain(self, concurrency: int = 2) -> None:
        w = self.worker(concurrency)
        self.scanner.scan(V)
        w.run()

    def outcomes(self) -> list[IngestOutcome]:
        return [r.outcome for r in self.queue.rows if r.outcome is not None]

    def jobs(self) -> list[IngestJob]:
        return [r.job for r in self.queue.rows]


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    dst = tmp_path / "vault"
    shutil.copytree(VAULT_DIR, dst)
    return dst


def test_scan_sample_vault_enqueues_markdown_only(tmp_path: Path) -> None:
    s = Stack(VAULT_DIR, tmp_path)
    report = s.scanner.scan(V)
    md = [p for p in VAULT_DIR.rglob("*") if p.is_file() and p.suffix == ".md" and not p.name.startswith(".")]
    assert report.scanned == len(md) == report.upserts
    assert report.removes == report.unchanged == 0
    assert {f.reason for f in report.ignored} == {"not_markdown"}
    assert {Path(f.path).suffix for f in report.ignored} >= {".png", ".txt"}
    assert all(isinstance(j, Upsert) and j.origin == "vault" for j in s.jobs())


def test_full_run_then_rescan_is_all_unchanged(vault: Path, tmp_path: Path) -> None:
    s = Stack(vault, tmp_path / "uploads")
    s.drain(concurrency=3)
    assert s.docs.docs, "documents were indexed"
    assert s.clusters.centroids(V)
    reclusters = [o for o in s.outcomes() if isinstance(o, Reclustered)]
    assert len(reclusters) == 1
    counts = s.queue.counts()
    assert counts[JobState.PENDING] == counts[JobState.RUNNING] == 0
    assert counts[JobState.FAILED] == 1  # the latin-1 note: NotUtf8 is not retryable

    before = len(s.queue.rows)
    report = s.scanner.scan(V)
    # Indexed docs are unchanged; the latin-1 note never gets a stored hash, so every scan
    # re-enqueues it and the pipeline fails it NotUtf8 at once (non-retryable).
    assert report.removes == 0 and report.unchanged == len(s.docs.docs)
    assert [j.path for j in s.jobs()[before:] if isinstance(j, Upsert)] == ["cooking/recipes/Creme Brulee (latin1).md"]

    # Upsert jobs for unchanged files are Skipped(UNCHANGED) by the pipeline.
    path = next(iter(s.docs.docs))[1]
    out = s.pipeline.run(Upsert(vault=V, path=path, origin="vault"))
    assert isinstance(out, Skipped) and out.reason is SkipReason.UNCHANGED


def test_scan_enqueues_remove_for_deleted_vault_doc_but_not_uploads(vault: Path, tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    s = Stack(vault, uploads)
    s.drain()
    # an upload-origin doc must survive vault scans
    up = uploads / str(V) / "uploaded.md"
    up.parent.mkdir(parents=True)
    up.write_text("# Uploaded\n\nsomething uploaded by the user\n")
    s.pipeline.run(Upsert(vault=V, path=VaultPath("uploaded.md"), origin="upload"))
    assert (V, VaultPath("uploaded.md")) in s.docs.docs

    victim = vault / "Welcome.md"
    victim.unlink()
    before = len(s.queue.rows)
    report = s.scanner.scan(V)
    assert report.removes == 1
    new = [r.job for r in s.queue.rows[before:]]
    assert Remove(vault=V, path=VaultPath("Welcome.md")) in new
    assert not any(isinstance(j, Remove) and j.path == "uploaded.md" for j in new)


def test_changed_file_is_upserted_and_triggers_recluster(vault: Path, tmp_path: Path) -> None:
    s = Stack(vault, tmp_path / "uploads")
    s.drain()
    (vault / "Welcome.md").write_text("# Welcome\n\nCompletely new content about sourdough.\n")
    before = len(s.queue.rows)
    s.drain()
    new = [r for r in s.queue.rows[before:]]
    assert [r.job for r in new if isinstance(r.job, Upsert) and r.job.path == "Welcome.md"]
    assert any(isinstance(r.job, Recluster) and r.state is JobState.DONE for r in new)


def test_oversized_markdown_is_ignored(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    vault.mkdir()
    (vault / "small.md").write_text("# Small\n")
    (vault / "big.md").write_text("# Big\n" + "x" * 200)
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian" / "config.md").write_text("hidden")
    s = Stack(vault, tmp_path / "u", max_file_bytes=100)
    report = s.scanner.scan(V)
    assert report.scanned == 1 and report.upserts == 1
    assert [(f.path, f.reason) for f in report.ignored] == [("big.md", "too_large")]


class ExplodingPipeline:
    def run(self, job: IngestJob) -> IngestOutcome | ModelUnavailable:
        raise RuntimeError("boom")


def test_crashing_pipeline_job_is_failed_with_retry(tmp_path: Path) -> None:
    q = InMemoryJobQueue()
    q.enqueue(Upsert(vault=V, path=VaultPath("a.md"), origin="vault"))
    w = Worker(queue=q, pipeline=ExplodingPipeline(), poll_s=0.01, concurrency=1, exit_when_idle=True)
    w.run()
    row = q.rows[0]
    assert row.state is JobState.PENDING and row.attempts == 1  # retry scheduled with backoff
    assert isinstance(row.error, ModelUnavailable)


def test_stop_event_ends_run(tmp_path: Path) -> None:
    q = InMemoryJobQueue()
    w = Worker(queue=q, pipeline=ExplodingPipeline(), poll_s=0.01, concurrency=2)
    w.stop.set()
    w.run()  # returns promptly without exit_when_idle

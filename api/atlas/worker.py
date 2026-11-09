"""Worker process (`python -m atlas.worker`): VaultScanner + the job loop (PRD Output 1 / 4).

Loop contract:
  claim(lease) -> pipeline.run(job) -> complete(outcome) | fail(error) -> RetryDecision.
  Backoff and the attempt cap live in PgJobQueue (2**attempt * 10 s; max 3 attempts, then
  FAILED; non-retryable errors fail at once).
  When the queue drains (no job due, no thread busy): enqueue Recluster for every vault that
  changed since its last recluster (at most one pending per vault; the queue dedups it).
  On startup: settings.require_llm_key(), apply migrations, scan the default vault.

Concurrency: ``worker_concurrency`` threads share one pipeline (it is stateless) and one
connection pool. The work is I/O bound (Ollama, Anthropic, Postgres), so threads suffice; the
queue guarantees at most one running job per (vault, path).

Shutdown: SIGTERM / SIGINT stop claiming; in-flight jobs finish and are completed / failed.
A job killed mid-run is reclaimed after its lease expires.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import threading
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from types import FrameType
from typing import Mapping, Sequence, assert_never

from atlas.config import Settings, get_settings
from atlas.pipeline import content_hash_of
from atlas.ports import DocumentRepository, IngestPipeline, JobQueue
from atlas.types import (
    DEFAULT_VAULT_ID,
    ClaimedJob,
    GaveUp,
    IgnoredFile,
    IngestOutcome,
    Indexed,
    ModelTimeout,
    ModelUnavailable,
    NotUtf8,
    Recluster,
    Reclustered,
    Remove,
    Removed,
    RetryAt,
    ScanReport,
    Skipped,
    Upsert,
    VaultId,
    VaultPath,
    parse_vault_path,
)

log = logging.getLogger("atlas.worker")


# ---- VaultScanner ------------------------------------------------------------------------------
@dataclass(frozen=True)
class FsVaultScanner:
    """Implements ``atlas.ports.VaultScanner`` for vaults mounted on the local filesystem.

    Walks the vault root (hidden files / dirs such as ``.obsidian`` are skipped silently),
    lists non-Markdown, invalid-path and over-cap files as ignored, hashes each Markdown file's
    bytes exactly like the pipeline (``content_hash_of``) and enqueues an Upsert only when the
    hash differs from the stored one, plus a Remove for every stored vault-origin document that
    is no longer on disk (or no longer indexable). Never reads beyond hashing; never writes
    documents."""

    queue: JobQueue
    documents: DocumentRepository
    roots: Mapping[VaultId, Path]
    max_file_bytes: int = 5 * 1024 * 1024

    def scan(self, vault: VaultId) -> ScanReport:
        root = self.roots[vault].resolve()
        stored = self.documents.stored_hashes(vault, "vault")
        ignored: list[IgnoredFile] = []
        seen: set[VaultPath] = set()
        scanned = upserts = unchanged = 0

        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for name in sorted(filenames):
                if name.startswith("."):
                    continue
                full = Path(dirpath) / name
                rel = full.relative_to(root).as_posix()
                if full.suffix.lower() not in (".md", ".markdown"):
                    ignored.append(IgnoredFile(path=rel, reason="not_markdown"))
                    continue
                path = parse_vault_path(rel)
                try:
                    inside = full.resolve().is_relative_to(root) and full.is_file()
                except OSError:
                    inside = False
                if path is None or not inside:
                    ignored.append(IgnoredFile(path=rel, reason="invalid_path"))
                    continue
                try:
                    if full.stat().st_size > self.max_file_bytes:
                        ignored.append(IgnoredFile(path=rel, reason="too_large"))
                        continue
                    digest = content_hash_of(full.read_bytes())
                except OSError:
                    continue  # vanished or unreadable mid-scan; the next scan sees it again
                scanned += 1
                seen.add(path)
                if stored.get(path) == digest:
                    unchanged += 1
                else:
                    self.queue.enqueue(Upsert(vault=vault, path=path, origin="vault"))
                    upserts += 1

        gone = sorted(set(stored) - seen)
        for path in gone:
            self.queue.enqueue(Remove(vault=vault, path=path))
        return ScanReport(
            vault=vault,
            scanned=scanned,
            upserts=upserts,
            removes=len(gone),
            unchanged=unchanged,
            ignored=tuple(ignored),
        )


# ---- Worker loop ---------------------------------------------------------------------------------
@dataclass
class Worker:
    """Claims jobs and runs them through the pipeline on ``concurrency`` threads."""

    queue: JobQueue
    pipeline: IngestPipeline
    lease: timedelta = timedelta(minutes=5)
    poll_s: float = 1.0
    concurrency: int = 2
    exit_when_idle: bool = False
    stop: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _busy: int = 0
    _dirty: set[VaultId] = field(default_factory=set)
    _reclusters: set[VaultId] = field(default_factory=set)  # enqueued by us, not yet finished

    def mark_dirty(self, vault: VaultId) -> None:
        with self._lock:
            self._dirty.add(vault)

    # One iteration: True when a job was processed (or a recluster enqueued), False when idle.
    def step(self) -> bool:
        with self._lock:
            self._busy += 1
        try:
            claimed = self.queue.claim(self.lease)
            if claimed is not None:
                self._process(claimed)
                return True
        finally:
            with self._lock:
                self._busy -= 1
        return self._on_drained()

    def _on_drained(self) -> bool:
        with self._lock:
            if self._busy or not self._dirty:
                return False
            vaults, self._dirty = sorted(self._dirty, key=str), set()
        for vault in vaults:
            with self._lock:
                self._reclusters.add(vault)
            self.queue.enqueue(Recluster(vault=vault))
            log.info("queue drained: enqueued recluster for vault %s", vault)
        return True

    def _process(self, claimed: ClaimedJob) -> None:
        job = claimed.job
        label = job.kind if isinstance(job, Recluster) else f"{job.kind} {job.path}"
        try:
            result = self.pipeline.run(job, lambda stage: self.queue.report_stage(claimed.job_id, stage))
        except Exception as exc:  # repository / unexpected errors: retry with backoff
            log.exception("job %s (%s) crashed", claimed.job_id, label)
            result = ModelUnavailable(detail=f"internal error: {type(exc).__name__}: {exc}")

        match result:
            case Indexed() | Skipped() | Removed() | Reclustered():
                self.queue.complete(claimed.job_id, result)
                self._log_outcome(label, result)
                if isinstance(result, (Indexed, Removed)):
                    self.mark_dirty(job.vault)
            case ModelUnavailable() | ModelTimeout() | NotUtf8():
                decision = self.queue.fail(claimed.job_id, result)
                match decision:
                    case RetryAt(at=at, attempt=attempt):
                        log.warning("job %s (%s) failed attempt %d: %s; retry at %s",
                                    claimed.job_id, label, attempt, result, at.isoformat())
                        return  # a retried recluster stays in flight
                    case GaveUp(attempts=attempts):
                        log.error("job %s (%s) failed after %d attempt(s): %s",
                                  claimed.job_id, label, attempts, result)
                    case _:
                        assert_never(decision)
            case _:
                assert_never(result)
        if isinstance(job, Recluster):
            with self._lock:
                self._reclusters.discard(job.vault)

    @staticmethod
    def _log_outcome(label: str, outcome: IngestOutcome) -> None:
        match outcome:
            case Indexed(link_count=links, topic_count=topics):
                log.info("%s: indexed (%d links, %d topics)", label, links, topics)
            case Skipped(reason=reason):
                log.info("%s: skipped (%s)", label, reason.value)
            case Removed():
                log.info("%s: removed", label)
            case Reclustered(cluster_count=n):
                log.info("%s: %d clusters", label, n)
            case _:
                assert_never(outcome)

    def _loop(self) -> None:
        while not self.stop.is_set():
            try:
                worked = self.step()
            except Exception:  # database down etc.: back off and keep going
                log.exception("worker iteration failed")
                worked = False
            if worked:
                continue
            if self.exit_when_idle and self._idle():
                self.stop.set()
                return
            self.stop.wait(self.poll_s)

    def _idle(self) -> bool:
        with self._lock:
            return self._busy == 0 and not self._dirty and not self._reclusters

    def run(self) -> None:
        threads = [
            threading.Thread(target=self._loop, name=f"atlas-worker-{i}", daemon=True)
            for i in range(max(1, self.concurrency))
        ]
        for t in threads:
            t.start()
        for t in threads:
            while t.is_alive():
                t.join(timeout=0.5)


# ---- Wiring --------------------------------------------------------------------------------------
def _install_signal_handlers(stop: threading.Event) -> None:
    def handler(signum: int, _frame: FrameType | None) -> None:
        log.info("received signal %d: finishing in-flight jobs", signum)
        stop.set()

    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)


def _log_scan(report: ScanReport) -> None:
    log.info(
        "scan vault %s: %d markdown files, %d upserts, %d removes, %d unchanged, %d ignored",
        report.vault, report.scanned, report.upserts, report.removes, report.unchanged, len(report.ignored),
    )
    for f in report.ignored:
        log.info("  ignored %s (%s)", f.path, f.reason)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m atlas.worker")
    parser.add_argument("--no-scan", action="store_true", help="skip the startup vault scan")
    parser.add_argument("--exit-when-idle", action="store_true",
                        help="exit once no job is due and the final recluster has run")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per embed/LLM call is noise
    settings: Settings = get_settings()
    settings.require_llm_key()

    # Imported here so `--help` and unit tests need neither Postgres nor the SDK configured.
    from atlas.models import build_models
    from atlas.pipeline import FsFileReader, IngestPipelineImpl, PipelineConfig
    from atlas.store import PgClusterRepository, PgDocumentRepository, PgJobQueue, open_pool
    from atlas.store.migrate import migrate, wait_for_database

    wait_for_database(settings.database_url, 60.0)
    for name in migrate(settings.database_url):
        log.info("applied migration %s", name)

    concurrency = max(1, settings.worker_concurrency)
    pool = open_pool(settings.database_url, max_size=concurrency + 4)
    try:
        documents = PgDocumentRepository(pool)
        clusters = PgClusterRepository(pool)
        queue = PgJobQueue(pool, max_attempts=settings.job_max_attempts)
        models = build_models(settings)
        log.info("models: embeddings=%s via %s, language=%s",
                 settings.embedding_model, settings.ollama_url,
                 "disabled (ATLAS_EMBEDDINGS_ONLY)" if settings.embeddings_only else settings.llm_model)
        pipeline = IngestPipelineImpl(
            files=FsFileReader(settings.vault_root, settings.uploads_root),
            documents=documents,
            clusters=clusters,
            embeddings=models.document_embedder,  # never the query embedder (nomic task prefix)
            language=models.language_model,
            config=PipelineConfig.from_settings(settings),
        )
        worker = Worker(
            queue=queue,
            pipeline=pipeline,
            lease=timedelta(seconds=settings.job_lease_s),
            poll_s=settings.worker_poll_s,
            concurrency=concurrency,
            exit_when_idle=args.exit_when_idle,
        )
        _install_signal_handlers(worker.stop)

        vault = DEFAULT_VAULT_ID
        if not args.no_scan:
            scanner = FsVaultScanner(
                queue=queue, documents=documents, roots={vault: settings.vault_root},
                max_file_bytes=settings.max_file_bytes,
            )
            report = scanner.scan(vault)
            _log_scan(report)  # Indexed / Removed outcomes mark the vault dirty -> recluster on drain
        if not clusters.centroids(vault) and documents.all_document_vectors(vault):
            worker.mark_dirty(vault)  # e.g. a previous run stopped before its recluster

        log.info("worker started with %d thread(s)", concurrency)
        worker.run()
        log.info("worker stopped")
    finally:
        pool.close()


if __name__ == "__main__":
    main()

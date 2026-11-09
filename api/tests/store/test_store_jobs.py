"""PgJobQueue against real Postgres."""

from __future__ import annotations

import threading
import uuid
from datetime import timedelta

import pytest
from psycopg_pool import ConnectionPool
from store_helpers import V, add_vault, rows, scalar

from atlas import ports
from atlas.store import PgJobQueue
from atlas.types import (
    GaveUp,
    Indexed,
    JobId,
    ModelTimeout,
    ModelUnavailable,
    NotUtf8,
    Recluster,
    Remove,
    RetryAt,
    Upsert,
    VaultPath,
    document_id_for,
)

LEASE = timedelta(minutes=5)


def up(path: str) -> Upsert:
    return Upsert(vault=V, path=VaultPath(path), origin="vault")


@pytest.fixture
def queue(pool: ConnectionPool) -> PgJobQueue:
    return PgJobQueue(pool)


def _expire_leases(pool: ConnectionPool) -> None:
    with pool.connection() as conn:
        conn.execute("UPDATE jobs SET lease_until = now() - interval '1 second' WHERE state = 'running'")


def _make_due(pool: ConnectionPool) -> None:
    with pool.connection() as conn:
        conn.execute("UPDATE jobs SET run_after = now() - interval '1 second' WHERE state = 'pending'")


def test_satisfies_port(queue: PgJobQueue) -> None:
    _q: ports.JobQueue = queue


def test_enqueue_replaces_pending_for_same_path(queue: PgJobQueue, pool: ConnectionPool) -> None:
    j1 = queue.enqueue(up("a.md"))
    j2 = queue.enqueue(Remove(vault=V, path=VaultPath("a.md")))
    j3 = queue.enqueue(up("b.md"))
    assert j1 == j2 and j3 != j1
    assert rows(pool, "SELECT path, kind, state FROM jobs ORDER BY path") == [
        ("a.md", "remove", "pending"),
        ("b.md", "upsert", "pending"),
    ]
    claimed = queue.claim(LEASE)
    assert claimed is not None and claimed.job == Remove(vault=V, path=VaultPath("a.md")) and claimed.attempt == 1


def test_same_path_in_other_vault_is_separate(queue: PgJobQueue, pool: ConnectionPool) -> None:
    other = add_vault(pool)
    queue.enqueue(up("a.md"))
    queue.enqueue(Upsert(vault=other, path=VaultPath("a.md"), origin="upload"))
    assert scalar(pool, "SELECT count(*) FROM jobs") == 2


def test_recluster_at_most_one_pending_per_vault(queue: PgJobQueue, pool: ConnectionPool) -> None:
    other = add_vault(pool)
    a = queue.enqueue(Recluster(vault=V))
    b = queue.enqueue(Recluster(vault=V))
    c = queue.enqueue(Recluster(vault=other))
    assert a == b and c != a
    assert rows(pool, "SELECT dedup_key, path FROM jobs WHERE vault_id = %s", V) == [("__recluster__", None)]


def test_claim_complete_and_payload_round_trip(queue: PgJobQueue, pool: ConnectionPool) -> None:
    jid = queue.enqueue(up("a.md"))
    claimed = queue.claim(LEASE)
    assert claimed is not None
    assert claimed.job_id == jid and claimed.job == up("a.md") and claimed.attempt == 1
    assert queue.claim(LEASE) is None
    outcome = Indexed(document_id=document_id_for(V, VaultPath("a.md")), path=VaultPath("a.md"), link_count=2, topic_count=1, cluster_id=None)
    queue.complete(jid, outcome)
    state, stored, lease, finished = rows(pool, "SELECT state, outcome, lease_until, finished_at FROM jobs")[0]
    assert state == "done" and stored["kind"] == "indexed" and stored["link_count"] == 2
    assert lease is None and finished is not None
    assert queue.claim(LEASE) is None


def test_claim_order_is_fifo(queue: PgJobQueue) -> None:
    for p in ("1.md", "2.md", "3.md"):
        queue.enqueue(up(p))
    got = []
    while (c := queue.claim(LEASE)) is not None:
        assert isinstance(c.job, Upsert)
        got.append(c.job.path)
    assert got == ["1.md", "2.md", "3.md"]


def test_enqueue_while_running_waits_for_running_job(queue: PgJobQueue, pool: ConnectionPool) -> None:
    first = queue.enqueue(up("a.md"))
    claimed = queue.claim(LEASE)
    assert claimed is not None
    second = queue.enqueue(up("a.md"))  # file changed while indexing
    assert second != first
    assert queue.claim(LEASE) is None  # same key is running
    queue.complete(first, Indexed(document_id=document_id_for(V, VaultPath("a.md")), path=VaultPath("a.md"), link_count=0, topic_count=0, cluster_id=None))
    nxt = queue.claim(LEASE)
    assert nxt is not None and nxt.job_id == second


def test_fail_retries_with_backoff_then_gives_up(pool: ConnectionPool) -> None:
    queue = PgJobQueue(pool, max_attempts=3, base_backoff=timedelta(seconds=10))
    jid = queue.enqueue(up("a.md"))
    delays = []
    for attempt in (1, 2):
        c = queue.claim(LEASE)
        assert c is not None and c.attempt == attempt
        now = scalar(pool, "SELECT now()")
        d = queue.fail(jid, ModelUnavailable(detail="ollama down"))
        assert isinstance(d, RetryAt) and d.attempt == attempt
        delays.append((d.at - now).total_seconds())  # type: ignore[operator]
        assert queue.claim(LEASE) is None  # not due yet
        _make_due(pool)
    assert delays[0] == pytest.approx(20, abs=2) and delays[1] == pytest.approx(40, abs=2)
    c = queue.claim(LEASE)
    assert c is not None and c.attempt == 3
    assert queue.fail(jid, ModelTimeout(step="embed")) == GaveUp(attempts=3)
    state, err = rows(pool, "SELECT state, last_error FROM jobs")[0]
    assert state == "failed" and err == {"kind": "model_timeout", "step": "embed"}
    assert queue.claim(LEASE) is None


def test_non_retryable_gives_up_immediately(queue: PgJobQueue, pool: ConnectionPool) -> None:
    jid = queue.enqueue(up("a.md"))
    assert queue.claim(LEASE) is not None
    assert queue.fail(jid, NotUtf8(path=VaultPath("a.md"))) == GaveUp(attempts=1)
    assert scalar(pool, "SELECT state FROM jobs") == "failed"


def test_fail_unknown_job(queue: PgJobQueue) -> None:
    with pytest.raises(KeyError):
        queue.fail(JobId(uuid.uuid4()), ModelUnavailable(detail="x"))


def test_fail_with_newer_pending_job_defers_to_it(queue: PgJobQueue, pool: ConnectionPool) -> None:
    first = queue.enqueue(up("a.md"))
    assert queue.claim(LEASE) is not None
    second = queue.enqueue(up("a.md"))
    d = queue.fail(first, ModelUnavailable(detail="x"))
    assert isinstance(d, RetryAt)
    assert rows(pool, "SELECT id, state FROM jobs ORDER BY created_at") == [(first, "failed"), (second, "pending")]
    c = queue.claim(LEASE)
    assert c is not None and c.job_id == second


def test_enqueue_resets_backoff_of_pending_retry(queue: PgJobQueue, pool: ConnectionPool) -> None:
    jid = queue.enqueue(up("a.md"))
    assert queue.claim(LEASE) is not None
    queue.fail(jid, ModelUnavailable(detail="x"))
    assert queue.claim(LEASE) is None
    assert queue.enqueue(up("a.md")) == jid  # new content replaces the waiting retry
    c = queue.claim(LEASE)
    assert c is not None and c.job_id == jid and c.attempt == 1


def test_expired_lease_is_reclaimable(queue: PgJobQueue, pool: ConnectionPool) -> None:
    jid = queue.enqueue(up("a.md"))
    assert queue.claim(LEASE) is not None
    assert queue.claim(LEASE) is None
    _expire_leases(pool)
    again = queue.claim(LEASE)
    assert again is not None and again.job_id == jid and again.attempt == 2
    # the original worker finishing late does not clobber the new owner's row
    assert queue.fail(jid, ModelUnavailable(detail="late")) is not None


def test_expired_lease_with_newer_pending_is_dropped(queue: PgJobQueue, pool: ConnectionPool) -> None:
    first = queue.enqueue(up("a.md"))
    assert queue.claim(LEASE) is not None
    second = queue.enqueue(up("a.md"))
    _expire_leases(pool)
    c = queue.claim(LEASE)
    assert c is not None and c.job_id == second
    assert rows(pool, "SELECT id FROM jobs") == [(second,)]
    queue.complete(first, Indexed(document_id=document_id_for(V, VaultPath("a.md")), path=VaultPath("a.md"), link_count=0, topic_count=0, cluster_id=None))  # no-op


def test_expired_lease_on_last_attempt_fails(pool: ConnectionPool) -> None:
    queue = PgJobQueue(pool, max_attempts=2)
    queue.enqueue(up("a.md"))
    for _ in range(2):
        assert queue.claim(LEASE) is not None
        _expire_leases(pool)
    assert queue.claim(LEASE) is None
    assert scalar(pool, "SELECT state FROM jobs") == "failed"


def test_concurrent_claimers_never_get_the_same_job(pool: ConnectionPool) -> None:
    queue = PgJobQueue(pool)
    n_jobs, n_workers = 60, 8
    for i in range(n_jobs):
        queue.enqueue(up(f"notes/{i:03d}.md"))
    claimed: list[JobId] = []
    lock = threading.Lock()
    errors: list[BaseException] = []
    start = threading.Barrier(n_workers)

    def worker() -> None:
        try:
            start.wait()
            while (c := queue.claim(LEASE)) is not None:
                with lock:
                    claimed.append(c.job_id)
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(n_workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors
    assert len(claimed) == n_jobs
    assert len(set(claimed)) == n_jobs
    assert scalar(pool, "SELECT count(*) FROM jobs WHERE state = 'running' AND attempts = 1") == n_jobs


def test_concurrent_claimers_same_key(pool: ConnectionPool) -> None:
    """Racing enqueue + claim on one path never yields two running jobs for it."""
    queue = PgJobQueue(pool)
    stop = threading.Event()
    errors: list[BaseException] = []
    max_running = 0

    def producer() -> None:
        try:
            for _ in range(200):
                queue.enqueue(up("hot.md"))
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)
        finally:
            stop.set()

    def consumer() -> None:
        nonlocal max_running
        try:
            while not stop.is_set():
                c = queue.claim(LEASE)
                if c is None:
                    continue
                running = scalar(pool, "SELECT count(*) FROM jobs WHERE state = 'running'")
                max_running = max(max_running, int(running))  # type: ignore[call-overload]
                queue.complete(c.job_id, Indexed(document_id=document_id_for(V, VaultPath("hot.md")), path=VaultPath("hot.md"), link_count=0, topic_count=0, cluster_id=None))
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=producer)] + [threading.Thread(target=consumer) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors
    assert max_running <= 1
    assert scalar(pool, "SELECT count(*) FROM jobs WHERE state = 'pending'") in (0, 1)


# ---- live stage + ETA (migration 0002) -----------------------------------------------------
def test_report_stage_and_jobs_status_fields(queue: PgJobQueue, pool: ConnectionPool) -> None:
    from atlas.read.jobs import PgJobsStatusReader

    reader = PgJobsStatusReader(connect=pool.connection)
    queue.enqueue(up("a.md"))
    s = reader.status(V, 10)
    assert s.avg_seconds_per_file is None
    assert s.files[0].status == "queued" and s.files[0].stage is None and s.files[0].started_at is None

    claimed = queue.claim(LEASE)
    assert claimed is not None
    s = reader.status(V, 10)
    assert s.files[0].status == "indexing" and s.files[0].stage == "reading" and s.files[0].started_at is not None

    for stage in ("parsing", "embedding", "enriching", "linking", "saving"):
        queue.report_stage(claimed.job_id, stage)  # type: ignore[arg-type]
        assert reader.status(V, 10).files[0].stage == stage

    with pool.connection() as conn:  # make the attempt take a known 4 s
        conn.execute("UPDATE jobs SET started_at = now() - interval '4 seconds' WHERE id = %s", (claimed.job_id,))
    queue.complete(claimed.job_id, Indexed(document_id=document_id_for(V, VaultPath("a.md")), path=VaultPath("a.md"),
                                           link_count=0, topic_count=0, cluster_id=None))
    assert scalar(pool, "SELECT stage FROM jobs WHERE id = %s", claimed.job_id) is None
    queue.report_stage(claimed.job_id, "saving")  # no-op once the job is done
    assert scalar(pool, "SELECT stage FROM jobs WHERE id = %s", claimed.job_id) is None
    s = reader.status(V, 10)
    assert s.files[0].status == "linked" and s.files[0].stage is None and s.files[0].started_at is not None
    assert s.avg_seconds_per_file is not None and 3.9 < s.avg_seconds_per_file < 4.5


def test_avg_seconds_uses_only_recent_done_upserts(queue: PgJobQueue, pool: ConnectionPool) -> None:
    from atlas.read.jobs import ETA_SAMPLE, PgJobsStatusReader

    with pool.connection() as conn:
        # 20 recent 2 s upserts, one older 100 s upsert (outside the sample), a 50 s remove,
        # a failed upsert, and a legacy done row without started_at: only the 20 count.
        for i in range(ETA_SAMPLE):
            conn.execute(
                "INSERT INTO jobs (vault_id, kind, path, dedup_key, payload, state, started_at, finished_at)"
                " VALUES (%s, 'upsert', %s, %s, '{}', 'done', now() - interval '2 seconds', now())",
                (V, f"n{i}.md", f"n{i}.md"),
            )
        conn.execute(
            "INSERT INTO jobs (vault_id, kind, path, dedup_key, payload, state, started_at, finished_at) VALUES"
            " (%(v)s, 'upsert', 'old.md', 'old.md', '{}', 'done', now() - interval '1 hour 100 seconds', now() - interval '1 hour'),"
            " (%(v)s, 'remove', 'r.md', 'r.md', '{}', 'done', now() - interval '50 seconds', now()),"
            " (%(v)s, 'upsert', 'f.md', 'f.md', '{}', 'failed', now() - interval '50 seconds', now()),"
            " (%(v)s, 'upsert', 'legacy.md', 'legacy.md', '{}', 'done', NULL, now())",
            {"v": V},
        )
    avg = PgJobsStatusReader(connect=pool.connection).status(V, 50).avg_seconds_per_file
    assert avg is not None and abs(avg - 2.0) < 0.01


def test_report_stage_swallows_db_errors(pool: ConnectionPool) -> None:
    broken = PgJobQueue(pool)
    broken._pool = None  # type: ignore[assignment]  # any failure inside must not escape
    broken.report_stage(JobId(uuid.uuid4()), "reading")


def test_fail_clears_stage(queue: PgJobQueue, pool: ConnectionPool) -> None:
    queue.enqueue(up("a.md"))
    claimed = queue.claim(LEASE)
    assert claimed is not None
    queue.report_stage(claimed.job_id, "embedding")
    assert isinstance(queue.fail(claimed.job_id, ModelUnavailable(detail="down")), RetryAt)
    assert scalar(pool, "SELECT stage FROM jobs WHERE id = %s", claimed.job_id) is None

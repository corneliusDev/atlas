"""PgJobQueue: the jobs table as a queue (FOR UPDATE SKIP LOCKED + lease).

Rules (PRD Output 1 / migration 0001):
- At most one pending and one running job per (vault, dedup_key); dedup_key is the path for
  Upsert/Remove and ``'__recluster__'`` for Recluster. ``enqueue`` replaces a pending job's
  payload (so an old version can never overwrite a newer file) and resets its attempts.
- ``claim`` takes the oldest due pending job whose key has no running job, marks it running
  with a lease and increments ``attempts``. A running job whose lease expired is reclaimable:
  it goes back to pending (or is dropped when a newer pending job for the same key exists).
  A lease that expires on the final attempt marks the job failed (last_error stays as it was).
- ``fail`` -> ``RetryAt`` (exponential backoff: base * 2**attempts) while the error is
  retryable and attempts < max_attempts, else ``GaveUp``.
All timestamps come from the database clock.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import psycopg
from psycopg.types.json import Jsonb
from pydantic import TypeAdapter
from psycopg_pool import ConnectionPool

from atlas.types import (
    ClaimedJob,
    GaveUp,
    IngestError,
    IndexStage,
    IngestJob,
    IngestOutcome,
    JobId,
    Recluster,
    RetryAt,
    RetryDecision,
)

RECLUSTER_KEY = "__recluster__"

log = logging.getLogger("atlas.store.jobs")

_JOB: TypeAdapter[IngestJob] = TypeAdapter(IngestJob)
_OUTCOME: TypeAdapter[IngestOutcome] = TypeAdapter(IngestOutcome)
_ERROR: TypeAdapter[IngestError] = TypeAdapter(IngestError)


def dedup_key(job: IngestJob) -> str:
    return RECLUSTER_KEY if isinstance(job, Recluster) else job.path


class PgJobQueue:
    """Implements ports.JobQueue."""

    def __init__(
        self,
        pool: ConnectionPool,
        *,
        max_attempts: int = 3,
        base_backoff: timedelta = timedelta(seconds=10),
        max_backoff: timedelta = timedelta(hours=1),
    ) -> None:
        self._pool = pool
        self.max_attempts = max_attempts
        self.base_backoff = base_backoff
        self.max_backoff = max_backoff

    # ---- enqueue -------------------------------------------------------------------------
    def enqueue(self, job: IngestJob) -> JobId:
        job = _JOB.validate_python(job)
        payload = Jsonb(_JOB.dump_python(job, mode="json"))
        path = None if isinstance(job, Recluster) else job.path
        with self._pool.connection() as conn, conn.transaction():
            row = conn.execute(
                """
                INSERT INTO jobs (vault_id, kind, path, dedup_key, payload)
                VALUES (%(vault)s, %(kind)s, %(path)s, %(key)s, %(payload)s)
                ON CONFLICT (vault_id, dedup_key) WHERE state = 'pending' DO UPDATE SET
                    kind = EXCLUDED.kind,
                    path = EXCLUDED.path,
                    payload = EXCLUDED.payload,
                    attempts = 0,
                    run_after = now(),
                    last_error = NULL,
                    updated_at = now()
                RETURNING id
                """,
                {"vault": job.vault, "kind": job.kind, "path": path, "key": dedup_key(job), "payload": payload},
            ).fetchone()
        assert row is not None
        return JobId(row[0])

    # ---- claim ---------------------------------------------------------------------------
    def claim(self, lease: timedelta) -> ClaimedJob | None:
        with self._pool.connection() as conn:
            self._reclaim_expired(conn)
            try:
                with conn.transaction():
                    row = conn.execute(
                        """
                        WITH c AS (
                            SELECT j.id FROM jobs j
                            WHERE j.state = 'pending' AND j.run_after <= now()
                              AND NOT EXISTS (
                                  SELECT 1 FROM jobs r
                                  WHERE r.vault_id = j.vault_id AND r.dedup_key = j.dedup_key
                                    AND r.state = 'running')
                            ORDER BY j.run_after, j.created_at, j.id
                            LIMIT 1
                            FOR UPDATE OF j SKIP LOCKED
                        )
                        UPDATE jobs SET state = 'running', attempts = jobs.attempts + 1,
                                        lease_until = now() + %(lease)s, updated_at = now(),
                                        started_at = now(), stage = 'reading'
                        FROM c WHERE jobs.id = c.id
                        RETURNING jobs.id, jobs.payload, jobs.attempts, jobs.lease_until
                        """,
                        {"lease": lease},
                    ).fetchone()
            except psycopg.errors.UniqueViolation:
                # A job for the same key became running concurrently; try again next poll.
                return None
        if row is None:
            return None
        job_id, payload, attempts, lease_until = row
        return ClaimedJob(job_id=JobId(job_id), job=_JOB.validate_python(payload), attempt=attempts, lease_until=lease_until)

    def _reclaim_expired(self, conn: psycopg.Connection) -> None:
        try:
            with conn.transaction():
                conn.execute(
                    """
                    WITH expired AS (
                        SELECT id, vault_id, dedup_key, attempts FROM jobs
                        WHERE state = 'running' AND lease_until <= now()
                        FOR UPDATE SKIP LOCKED
                    ),
                    superseded AS (
                        DELETE FROM jobs USING expired e
                        WHERE jobs.id = e.id AND EXISTS (
                            SELECT 1 FROM jobs p
                            WHERE p.vault_id = e.vault_id AND p.dedup_key = e.dedup_key AND p.state = 'pending')
                        RETURNING jobs.id
                    )
                    UPDATE jobs SET
                        state = CASE WHEN e.attempts >= %(max)s THEN 'failed' ELSE 'pending' END,
                        finished_at = CASE WHEN e.attempts >= %(max)s THEN now() ELSE NULL END,
                        run_after = now(), lease_until = NULL, stage = NULL, updated_at = now()
                    FROM expired e
                    WHERE jobs.id = e.id AND e.id NOT IN (SELECT id FROM superseded)
                    """,
                    {"max": self.max_attempts},
                )
        except psycopg.errors.UniqueViolation:
            pass  # raced with an enqueue for the same key; the next claim retries

    # ---- complete / fail -------------------------------------------------------------------
    def complete(self, job_id: JobId, outcome: IngestOutcome) -> None:
        """Marks a running job done. No-op when the job is no longer running (its lease expired
        and it was reclaimed): the re-run is idempotent by content hash."""
        with self._pool.connection() as conn, conn.transaction():
            conn.execute(
                """
                UPDATE jobs SET state = 'done', outcome = %s, lease_until = NULL, stage = NULL,
                                finished_at = now(), updated_at = now()
                WHERE id = %s AND state = 'running'
                """,
                (Jsonb(_OUTCOME.dump_python(outcome, mode="json")), job_id),
            )

    def report_stage(self, job_id: JobId, stage: IndexStage) -> None:
        """Records the stage a running job is entering. One statement on its own pooled
        connection, committed immediately (never part of a document transaction); best-effort: a DB error is logged and swallowed so a
        progress write can never fail a job. No-op once the job is no longer running."""
        try:
            with self._pool.connection() as conn, conn.transaction():
                conn.execute(
                    "UPDATE jobs SET stage = %s WHERE id = %s AND state = 'running'",
                    (stage, job_id),
                )
        except Exception:  # noqa: BLE001 - progress is best-effort by design
            log.warning("could not record stage %s for job %s", stage, job_id, exc_info=True)

    def fail(self, job_id: JobId, error: IngestError) -> RetryDecision:
        err = Jsonb(_ERROR.dump_python(error, mode="json"))
        with self._pool.connection() as conn, conn.transaction():
            row = conn.execute(
                "SELECT vault_id, dedup_key, attempts, state, run_after FROM jobs WHERE id = %s FOR UPDATE",
                (job_id,),
            ).fetchone()
            if row is None:
                raise KeyError(job_id)
            vault_id, key, attempts, state, run_after = row
            if state != "running":
                # Lease expired and the job was reclaimed (or already finished): leave the row to
                # its current owner and report what will happen to it.
                if state == "failed":
                    return GaveUp(attempts=attempts)
                return RetryAt(at=run_after, attempt=attempts)
            if not type(error).retryable or attempts >= self.max_attempts:
                conn.execute(
                    """
                    UPDATE jobs SET state = 'failed', last_error = %s, lease_until = NULL, stage = NULL,
                                    finished_at = now(), updated_at = now()
                    WHERE id = %s
                    """,
                    (err, job_id),
                )
                return GaveUp(attempts=attempts)

            newer = conn.execute(
                "SELECT run_after FROM jobs WHERE vault_id = %s AND dedup_key = %s AND state = 'pending'"
                " AND id <> %s FOR UPDATE",
                (vault_id, key, job_id),
            ).fetchone()
            if newer is not None:
                # A newer job for the same key is already pending and supersedes this one: it
                # carries the latest payload and is the retry.
                conn.execute(
                    """
                    UPDATE jobs SET state = 'failed', last_error = %s, lease_until = NULL, stage = NULL,
                                    finished_at = now(), updated_at = now()
                    WHERE id = %s
                    """,
                    (err, job_id),
                )
                return RetryAt(at=newer[0], attempt=attempts)

            delay = min(self.base_backoff * (2**attempts), self.max_backoff)
            updated = conn.execute(
                """
                UPDATE jobs SET state = 'pending', last_error = %s, lease_until = NULL, stage = NULL,
                                run_after = now() + %s, updated_at = now()
                WHERE id = %s
                RETURNING run_after
                """,
                (err, delay, job_id),
            ).fetchone()
        assert updated is not None
        at: datetime = updated[0]
        return RetryAt(at=at, attempt=attempts)

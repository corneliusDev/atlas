"""Progress tray read model (UP-4): GET /api/jobs/status. Reads ``jobs`` only; never writes.

Per-file status is derived from the latest job row for the path (by created_at):
pending -> queued, running -> indexing, done -> linked, failed -> failed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import TypeAdapter, ValidationError

from atlas.http.dto import FileProgress, JobFailure, JobsStatusResponse
from atlas.read.db import Connect, fetch_all
from atlas.types import (
    FileStatus,
    IngestError,
    IngestOutcome,
    JobId,
    JobState,
    VaultId,
    VaultPath,
)

_ERROR = TypeAdapter[IngestError](IngestError)
_OUTCOME = TypeAdapter[IngestOutcome](IngestOutcome)

STATUS_OF: dict[JobState, FileStatus] = {
    JobState.PENDING: FileStatus.QUEUED,
    JobState.RUNNING: FileStatus.INDEXING,
    JobState.DONE: FileStatus.LINKED,
    JobState.FAILED: FileStatus.FAILED,
}

RECENT_FAILURES = 20
ETA_SAMPLE = 20  # avg_seconds_per_file: most recent done upserts


def _parse_error(raw: Any) -> IngestError | None:
    if raw is None:
        return None
    try:
        return _ERROR.validate_python(raw)
    except ValidationError:
        return None


def _parse_outcome(raw: Any) -> IngestOutcome | None:
    if raw is None:
        return None
    try:
        return _OUTCOME.validate_python(raw)
    except ValidationError:
        return None


@dataclass
class PgJobsStatusReader:
    """Implements ``atlas.read.protocols.JobsStatusReader``."""

    connect: Connect

    def status(self, vault: VaultId, limit: int) -> JobsStatusResponse:
        p = {"v": vault, "limit": limit, "failures": RECENT_FAILURES, "eta": ETA_SAMPLE}
        with self.connect() as conn:
            counts = {s: 0 for s in JobState}
            for r in fetch_all(conn, "SELECT state, count(*) AS n FROM jobs WHERE vault_id = %(v)s GROUP BY state", p):
                counts[JobState(r["state"])] = int(r["n"])
            files = fetch_all(
                conn,
                """
                SELECT * FROM (
                    SELECT DISTINCT ON (path) id, path, kind, state, attempts, last_error, outcome, updated_at,
                                              stage, started_at
                    FROM jobs
                    WHERE vault_id = %(v)s AND path IS NOT NULL
                    ORDER BY path, created_at DESC, updated_at DESC
                ) latest
                ORDER BY updated_at DESC, path
                LIMIT %(limit)s
                """,
                p,
            )
            failures = fetch_all(
                conn,
                "SELECT id, kind, path, last_error, attempts, coalesce(finished_at, updated_at) AS failed_at"
                " FROM jobs WHERE vault_id = %(v)s AND state = 'failed' AND last_error IS NOT NULL"
                " ORDER BY failed_at DESC LIMIT %(failures)s",
                p,
            )
            recluster = fetch_all(
                conn,
                "SELECT 1 AS x FROM jobs WHERE vault_id = %(v)s AND kind = 'recluster' AND state = 'pending' LIMIT 1",
                p,
            )

            avg = fetch_all(
                conn,
                """
                SELECT avg(extract(epoch FROM finished_at - started_at))::float8 AS s FROM (
                    SELECT started_at, finished_at FROM jobs
                    WHERE vault_id = %(v)s AND kind = 'upsert' AND state = 'done'
                      AND started_at IS NOT NULL AND finished_at IS NOT NULL
                    ORDER BY finished_at DESC
                    LIMIT %(eta)s
                ) recent
                """,
                p,
            )
        avg_seconds = avg[0]["s"] if avg and avg[0]["s"] is not None else None

        progress: list[FileProgress] = []
        for r in files:
            state = JobState(r["state"])
            progress.append(
                FileProgress(
                    job_id=JobId(r["id"]),
                    path=VaultPath(r["path"]),
                    kind=r["kind"],
                    status=STATUS_OF[state],
                    attempts=int(r["attempts"]),
                    error=_parse_error(r["last_error"]) if state is not JobState.DONE else None,
                    outcome=_parse_outcome(r["outcome"]) if state is JobState.DONE else None,
                    updated_at=r["updated_at"],
                    stage=r["stage"] if state is JobState.RUNNING else None,
                    started_at=r["started_at"] if state is not JobState.PENDING else None,  # queued: no current attempt
                )
            )
        recent: list[JobFailure] = []
        for r in failures:
            err = _parse_error(r["last_error"])
            if err is None:
                continue
            recent.append(
                JobFailure(
                    job_id=JobId(r["id"]),
                    kind=r["kind"],
                    path=VaultPath(r["path"]) if r["path"] else None,
                    error=err,
                    attempts=int(r["attempts"]),
                    failed_at=r["failed_at"],
                )
            )
        return JobsStatusResponse(
            vault=vault,
            counts=counts,
            files=progress,
            recent_failures=recent,
            recluster_pending=bool(recluster),
            idle=counts[JobState.PENDING] == 0 and counts[JobState.RUNNING] == 0,
            avg_seconds_per_file=float(avg_seconds) if avg_seconds is not None else None,
        )

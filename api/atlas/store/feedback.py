"""PgLinkFeedbackRepository: the only writer of link_feedback."""

from __future__ import annotations

import psycopg
from psycopg_pool import ConnectionPool

from atlas.types import DocumentPair, LinkVerdict, VaultId


class UnknownDocumentError(LookupError):
    """A feedback pair names a document that does not exist in the vault (http -> 404)."""


class PgLinkFeedbackRepository:
    """Implements ports.LinkFeedbackRepository. ``record`` is an idempotent upsert keyed by the
    ordered pair; re-recording the same verdict changes nothing but updated_at."""

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def record(self, vault: VaultId, pair: DocumentPair, verdict: LinkVerdict) -> None:
        try:
            with self._pool.connection() as conn, conn.transaction():
                cur = conn.execute(
                    """
                    INSERT INTO link_feedback (vault_id, doc_a, doc_b, verdict)
                    SELECT %(vault)s, %(a)s, %(b)s, %(verdict)s
                    WHERE (SELECT count(*) FROM documents
                           WHERE id IN (%(a)s, %(b)s) AND vault_id = %(vault)s) = 2
                    ON CONFLICT (doc_a, doc_b) DO UPDATE SET
                        verdict = EXCLUDED.verdict,
                        vault_id = EXCLUDED.vault_id,
                        updated_at = now()
                    """,
                    {"vault": vault, "a": pair.a, "b": pair.b, "verdict": verdict.value},
                )
                inserted = cur.rowcount
        except psycopg.errors.ForeignKeyViolation as exc:  # deleted concurrently
            raise UnknownDocumentError(f"unknown document in pair {pair.a} / {pair.b}") from exc
        if inserted != 1:
            raise UnknownDocumentError(f"documents {pair.a} / {pair.b} are not both in vault {vault}")

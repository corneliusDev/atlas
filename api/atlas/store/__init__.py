"""Postgres adapters: PgDocumentRepository, PgClusterRepository, PgLinkFeedbackRepository,
PgJobQueue; SQL migrations in store/migrations, applied by store/migrate.py.

Typical wiring (api / worker)::

    migrate(settings.database_url)  # atlas.store.migrate
    pool = open_pool(settings.database_url)
    docs = PgDocumentRepository(pool)
    queue = PgJobQueue(pool, max_attempts=settings.job_max_attempts)
"""

from atlas.store.clusters import PgClusterRepository
from atlas.store.documents import PgDocumentRepository
from atlas.store.feedback import PgLinkFeedbackRepository, UnknownDocumentError
from atlas.store.jobs import RECLUSTER_KEY, PgJobQueue, dedup_key
from atlas.store.pool import open_pool

__all__ = [
    "RECLUSTER_KEY",
    "PgClusterRepository",
    "PgDocumentRepository",
    "PgJobQueue",
    "PgLinkFeedbackRepository",
    "UnknownDocumentError",
    "dedup_key",
    "open_pool",
]

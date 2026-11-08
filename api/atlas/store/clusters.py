"""PgClusterRepository: clusters + documents.cluster_id / topics.cluster_id for a vault."""

from __future__ import annotations

from collections import Counter
from typing import Sequence

from psycopg_pool import ConnectionPool

from atlas.store.pool import from_vector, lock_vault, to_vector
from atlas.types import ClusterAssignment, ClusterCentroid, ClusterId, ClusterLabel, VaultId


class PgClusterRepository:
    """Implements ports.ClusterRepository."""

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def centroids(self, vault: VaultId) -> list[ClusterCentroid]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT id, centroid, color FROM clusters WHERE vault_id = %s ORDER BY id", (vault,)
            ).fetchall()
        return [ClusterCentroid(cluster_id=ClusterId(i), centroid=from_vector(c), color=col) for i, c, col in rows]

    def replace_clusters(self, vault: VaultId, assignment: ClusterAssignment, labels: Sequence[ClusterLabel]) -> None:
        """ONE transaction: the vault's clusters become exactly ``assignment.centroids`` (labels
        matched by cluster_id; missing label -> NULL), member documents get their cluster_id
        (None = unclustered), and each topic takes the most common cluster of its documents.
        Documents not listed in ``members`` (indexed after the snapshot) keep their cluster when
        it survives, else ON DELETE SET NULL clears it."""
        label_of = {lab.cluster_id: lab.label for lab in labels}
        sizes = Counter(m.cluster_id for m in assignment.members if m.cluster_id is not None)
        new_ids = [c.cluster_id for c in assignment.centroids]
        unknown = set(sizes) - set(new_ids)
        if unknown:
            raise ValueError(f"members reference clusters missing from centroids: {sorted(map(str, unknown))}")

        with self._pool.connection() as conn, conn.transaction():
            lock_vault(conn, vault)
            conn.execute(
                "DELETE FROM clusters WHERE vault_id = %s AND NOT id = ANY(%s::uuid[])", (vault, new_ids)
            )
            with conn.cursor() as cur:
                if assignment.centroids:
                    cur.executemany(
                        """
                        INSERT INTO clusters (id, vault_id, label, centroid, color, size)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            label = EXCLUDED.label, centroid = EXCLUDED.centroid,
                            color = EXCLUDED.color, size = EXCLUDED.size
                        """,
                        [
                            (
                                c.cluster_id,
                                vault,
                                label_of.get(c.cluster_id),
                                to_vector(c.centroid),
                                c.color,
                                sizes.get(c.cluster_id, 0),
                            )
                            for c in assignment.centroids
                        ],
                    )
                if assignment.members:
                    cur.executemany(
                        "UPDATE documents SET cluster_id = %s WHERE id = %s AND vault_id = %s",
                        [(m.cluster_id, m.document_id, vault) for m in assignment.members],
                    )
            conn.execute(
                """
                UPDATE topics t SET cluster_id = sub.cluster_id
                FROM (
                    SELECT DISTINCT ON (dt.topic_id) dt.topic_id, d.cluster_id
                    FROM document_topics dt JOIN documents d ON d.id = dt.document_id
                    WHERE d.vault_id = %(vault)s AND d.cluster_id IS NOT NULL
                    GROUP BY dt.topic_id, d.cluster_id
                    ORDER BY dt.topic_id, count(*) DESC, d.cluster_id
                ) sub
                WHERE t.id = sub.topic_id
                """,
                {"vault": vault},
            )
            conn.execute(
                """
                UPDATE topics t SET cluster_id = NULL
                WHERE t.vault_id = %(vault)s AND t.cluster_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM document_topics dt JOIN documents d ON d.id = dt.document_id
                    WHERE dt.topic_id = t.id AND d.cluster_id IS NOT NULL)
                """,
                {"vault": vault},
            )

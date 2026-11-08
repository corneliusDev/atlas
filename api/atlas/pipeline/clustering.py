from __future__ import annotations

from typing import Sequence

from atlas.types import ClusterAssignment, ClusterCentroid, ClusterId, DocumentVector, Embedding

# Fixed palette; cluster() assigns colors by cluster index (largest cluster first).
CLUSTER_PALETTE: tuple[str, ...] = (
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
    "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac",
)


def nearest_cluster(
    vector: Embedding,
    centroids: Sequence[ClusterCentroid],
    min_similarity: float = 0.0,
) -> ClusterId | None:
    """Cluster with highest cosine similarity to vector; None when there are no centroids or
    the best similarity is below min_similarity. Ties broken by cluster_id."""
    raise NotImplementedError


def cluster(vectors: Sequence[DocumentVector]) -> ClusterAssignment:
    """HDBSCAN (sklearn.cluster.HDBSCAN, min_cluster_size=max(3, n//50)) on L2-normalised doc
    vectors. Deterministic: input sorted by document_id first; ClusterId = uuid5 over the
    sorted member ids so stable memberships keep stable ids. Noise -> cluster_id None.
    Fewer than 3 vectors -> no clusters."""
    raise NotImplementedError

from __future__ import annotations

import math
import uuid
from typing import Sequence

import numpy as np
import numpy.typing as npt

from atlas.types import (
    ClusterAssignment,
    ClusterCentroid,
    ClusterId,
    DocumentCluster,
    DocumentId,
    DocumentVector,
    Embedding,
)

# Fixed palette; cluster() assigns colors by cluster index (largest cluster first).
CLUSTER_PALETTE: tuple[str, ...] = (
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
    "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac",
)

# Namespace for cluster ids. Never change it: cluster ids are persisted.
_CLUSTER_NS = uuid.UUID("0f6f3a52-2a55-4f0e-9a4c-2d1c3b8e7a61")
MIN_DOCUMENTS = 3  # fewer -> no clusters
KMEANS_BELOW = 12  # vaults smaller than this skip HDBSCAN and use KMeans directly
SEED = 0


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    va, vb = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    na, nb = float(np.linalg.norm(va)), float(np.linalg.norm(vb))
    return 0.0 if na == 0 or nb == 0 else float(va @ vb) / (na * nb)


def nearest_cluster(
    vector: Embedding,
    centroids: Sequence[ClusterCentroid],
    min_similarity: float = 0.0,
) -> ClusterId | None:
    """Cluster with highest cosine similarity to vector; None when there are no centroids or
    the best similarity is below min_similarity. Ties broken by cluster_id."""
    best: tuple[float, str, ClusterId] | None = None
    for c in centroids:
        sim = _cosine(vector, c.centroid)
        key = (-sim, str(c.cluster_id))
        if best is None or key < (best[0], best[1]):
            best = (-sim, str(c.cluster_id), c.cluster_id)
    if best is None or -best[0] < min_similarity:
        return None
    return best[2]


def _normalise(m: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    out: npt.NDArray[np.float64] = m / norms
    return out


def _kmeans_k(n: int) -> int:
    return max(2, min(len(CLUSTER_PALETTE), round(math.sqrt(n / 2))))


def _labels(x: npt.NDArray[np.float64]) -> npt.NDArray[np.int64]:
    """-1 = noise. HDBSCAN first (euclidean on unit vectors ~ cosine); KMeans fallback for tiny
    vaults or when HDBSCAN finds no structure."""
    from sklearn.cluster import HDBSCAN, KMeans

    n = x.shape[0]
    if n >= KMEANS_BELOW:
        hdb = HDBSCAN(min_cluster_size=max(3, n // 50), metric="euclidean", copy=True)
        labels = np.asarray(hdb.fit_predict(x), dtype=np.int64)
        if len(set(labels.tolist()) - {-1}) >= 2:
            return labels
    k = min(_kmeans_k(n), n)
    distinct = np.unique(np.round(x, 12), axis=0).shape[0]
    k = max(1, min(k, distinct))
    km = KMeans(n_clusters=k, random_state=SEED, n_init=10)
    return np.asarray(km.fit_predict(x), dtype=np.int64)


def cluster(vectors: Sequence[DocumentVector]) -> ClusterAssignment:
    """HDBSCAN (sklearn.cluster.HDBSCAN, min_cluster_size=max(3, n//50)) on L2-normalised doc
    vectors. Deterministic: input sorted by document_id first; ClusterId = uuid5 over the
    sorted member ids so stable memberships keep stable ids. Noise -> cluster_id None.
    Fewer than 3 vectors -> no clusters.

    Fallback: vaults with fewer than 12 documents, or where HDBSCAN finds fewer than two
    clusters, use KMeans (k = clamp(round(sqrt(n/2)), 2, 10), random_state=0); KMeans has no
    noise. Colors: palette index by cluster size desc (ties by cluster id), cycling."""
    ordered = sorted({v.document_id: v for v in vectors}.values(), key=lambda v: str(v.document_id))
    if len(ordered) < MIN_DOCUMENTS:
        return ClusterAssignment(
            centroids=(),
            members=tuple(DocumentCluster(document_id=v.document_id, cluster_id=None) for v in ordered),
        )
    x = _normalise(np.asarray([v.vector for v in ordered], dtype=np.float64))
    labels = _labels(x)

    groups: dict[int, list[int]] = {}
    for idx, label in enumerate(labels.tolist()):
        if label >= 0:
            groups.setdefault(label, []).append(idx)

    ids: dict[int, ClusterId] = {}
    for label, idxs in groups.items():
        key = ",".join(str(ordered[i].document_id) for i in idxs)
        ids[label] = ClusterId(uuid.uuid5(_CLUSTER_NS, key))

    by_size = sorted(groups, key=lambda lab: (-len(groups[lab]), str(ids[lab])))
    centroids: list[ClusterCentroid] = []
    for rank, label in enumerate(by_size):
        mean = x[groups[label]].mean(axis=0)
        norm = float(np.linalg.norm(mean)) or 1.0
        centroids.append(
            ClusterCentroid(
                cluster_id=ids[label],
                centroid=tuple(float(v) for v in mean / norm),
                color=CLUSTER_PALETTE[rank % len(CLUSTER_PALETTE)],
            )
        )

    members = tuple(
        DocumentCluster(
            document_id=DocumentId(v.document_id),
            cluster_id=ids[int(labels[i])] if labels[i] >= 0 else None,
        )
        for i, v in enumerate(ordered)
    )
    return ClusterAssignment(centroids=tuple(centroids), members=members)

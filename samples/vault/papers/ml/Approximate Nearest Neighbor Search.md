---
tags: [ml, vector-search]
created: 2026-10-01
---
# Approximate Nearest Neighbor Search

Exact KNN over millions of vectors is too slow, so we trade a little recall for a lot of speed.

## HNSW
Hierarchical Navigable Small World graphs: a layered proximity graph; search greedily descends
from sparse top layers to dense bottom layers. Great recall/latency trade-off; pgvector supports it.

## IVF
Partition vectors into lists around k-means centroids; search only the nearest lists.

## Parameters that matter
- `m` and `ef_construction` for HNSW build quality.
- `ef_search` at query time for recall.

Used by [[Retrieval-Augmented Generation]] and by our document linking. #vector-search

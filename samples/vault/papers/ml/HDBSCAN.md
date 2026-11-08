---
tags: [ml, clustering]
created: 2026-10-01
---
# HDBSCAN

Campello, Moulavi and Sander, 2013. Hierarchical density-based clustering.

## Why it's a good fit for document clustering

- No need to choose the number of clusters.
- Labels low-density points as noise instead of forcing them into a cluster.
- Works with arbitrary cluster shapes.

## Parameters

- `min_cluster_size`: the smallest group worth calling a theme.
- `min_samples`: how conservative the density estimate is.

On normalised embeddings, Euclidean distance is a monotone function of cosine distance, so
it works fine on [[Sentence-BERT]]-style vectors. #clustering #unsupervised

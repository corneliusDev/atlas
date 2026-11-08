---
tags: [ml, rag, paper]
created: 2026-10-01
---
# Retrieval-Augmented Generation

Lewis et al., 2020. Combine a parametric generator with a non-parametric retriever over a document index.

## Mechanism

1. Embed the query with a dense encoder.
2. Retrieve top-k passages with [[Approximate Nearest Neighbor Search]].
3. Condition generation on the passages.

## Notes

Retrieval quality dominates answer quality. Hybrid retrieval (keyword + dense) usually beats
either alone; see [[Hybrid Search with Reciprocal Rank Fusion]]. #retrieval #rag

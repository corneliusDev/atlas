---
tags: [ml, search, retrieval]
created: 2026-10-01
---
# Hybrid Search with Reciprocal Rank Fusion

Reciprocal Rank Fusion (Cormack et al., 2009) merges ranked lists without needing comparable scores:

score(d) = sum over lists of 1 / (k + rank(d)), with k = 60.

## Why it works

Keyword search (BM25 / tsvector) is precise on rare terms; dense retrieval handles paraphrase.
RRF rewards documents that rank well in both. Cheap, robust, no tuning beyond k.

Applied in [[Retrieval-Augmented Generation]] pipelines. #search #hybrid-search

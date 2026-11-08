---
tags: [ml, embeddings, paper]
created: 2026-10-01
---
# Sentence-BERT

Reimers and Gurevych, 2019. Fine-tunes [[BERT]] with a siamese network so that cosine similarity
between sentence embeddings is meaningful.

## Why we care

This is the idea behind our own semantic links: embed every chunk, compare with cosine similarity,
keep the closest neighbours. Modern embedding models like nomic-embed-text follow the same
contrastive recipe at larger scale. See [[Contrastive Learning]] and [[Approximate Nearest Neighbor Search]].
#embeddings #semantic-search

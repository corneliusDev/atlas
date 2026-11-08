---
tags: [ml, topic-modeling, nlp]
created: 2026-10-01
---
# Topic Modeling Survey

From LDA to embeddings.

## LDA
Documents are mixtures of topics; topics are distributions over words. Interpretable but
brittle on short texts.

## BERTopic
Embed documents, reduce with UMAP, cluster with [[HDBSCAN]], then extract topic words with
class-based TF-IDF. Much better on modern corpora.

## LLM topic extraction
Ask a language model for topics and entities directly, then merge near-duplicates by embedding
similarity ("ML" = "machine learning"). This is the approach Atlas uses. #topic-modeling

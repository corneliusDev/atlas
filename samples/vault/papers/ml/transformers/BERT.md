---
tags: [ml, transformers, nlp, paper]
created: 2026-10-01
---
# BERT

*Pre-training of Deep Bidirectional Transformers for Language Understanding* (Devlin et al., 2018).

- Encoder-only [[Attention Is All You Need|Transformer]].
- Masked language modelling: hide 15% of tokens and predict them.
- Next sentence prediction (later shown to be mostly unnecessary).

Fine-tuning a single pre-trained model beat task-specific architectures on GLUE and SQuAD.
Sentence embeddings derived from BERT power early semantic search; compare with
[[Sentence-BERT]]. #nlp #embeddings

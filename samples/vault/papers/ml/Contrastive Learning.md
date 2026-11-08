---
tags: [ml, representation-learning]
created: 2026-10-01
---
# Contrastive Learning

Learn representations by pulling positive pairs together and pushing negatives apart.

- **SimCLR**: augmentations of the same image are positives; large batches supply negatives.
- **InfoNCE loss**: a softmax over one positive and many negatives.
- In NLP, [[Sentence-BERT]] and later embedding models use contrastive objectives on
  question/answer or title/body pairs.

Temperature controls how hard the negatives are weighted. #embeddings #self-supervised

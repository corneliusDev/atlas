---
title: Attention Is All You Need
authors: [Vaswani, Shazeer, Parmar, Uszkoreit, Jones, Gomez, Kaiser, Polosukhin]
year: 2017
tags: [ml, transformers, paper]
---
# Attention Is All You Need

Introduces the **Transformer**: an encoder-decoder architecture built entirely from attention,
dropping recurrence and convolution.

## Key ideas

- Scaled dot-product attention: softmax(QK^T / sqrt(d_k)) V.
- Multi-head attention lets the model attend to different subspaces at once.
- Positional encodings (sinusoidal) inject order information.

## Why it matters

Parallelisable training made much larger models practical. Everything in [[BERT]] and
[[Scaling Laws for Neural Language Models]] builds on it. #attention #deep-learning

```python
def attention(q, k, v):
    return softmax(q @ k.T / sqrt(d)) @ v
```

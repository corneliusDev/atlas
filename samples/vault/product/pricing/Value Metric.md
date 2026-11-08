---
tags: [pricing]
created: 2026-10-01
---
# Value Metric

A value metric is the unit you charge for. Good ones grow with the value the customer gets,
are easy to predict, and are easy to measure on our side.

Candidates we considered:

| Metric | Grows with value | Predictable | Measurable |
| --- | --- | --- | --- |
| Seats | medium | high | high |
| Active seats | high | medium | high |
| Documents indexed | high | low | high |
| Queries | high | low | medium |

We chose **active seats** (a seat that logged in during the billing month). It keeps the
[[Pricing Strategy]] promise of never punishing adoption, because inactive seats are free.
Related: [[Usage-Based Add-On]].

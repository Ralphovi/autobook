---
created: 26.07.2026 19:00
type: index
tags:
  - index
  - proposal
---
# Proposals

How design change flows. A proposal carries motivation, design, alternatives
considered, and graduation criteria, and moves from `draft/` to `accepted/`.
An accepted proposal is frozen — supersede it rather than editing it.

Start one from [`../templates/proposal.md`](../templates/proposal.md).

## Draft

| # | Title | Tracking |
|---|-------|----------|
| [0001](draft/0001-gnucash-auto-booking-pipeline.md) | GnuCash auto-booking pipeline | — |

## Accepted

None yet.

---

Proposal 0001 is the whole system design and is deliberately still `draft`. It
becomes `accepted` when build order step 2 — corpus export, kNN, and the backtest
harness — has reported. That step exists precisely to test the proposal's central
premise: that the user's own booking history is dense and consistent enough for
nearest-neighbour classification to abstain reliably. If it is not, the design
changes rather than the threshold, and accepting the proposal beforehand would
freeze a decision the evidence has not yet supported.

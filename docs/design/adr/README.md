---
created: 26.07.2026 19:00
type: index
tags:
  - index
  - adr
---
# Architecture decision records

Numbered, immutable records of *why* a decision was made. An accepted ADR is
never edited — it is superseded by a later record that references it, and the
supersession is noted in this table. **This index is the authority on what
currently stands**, because the documents themselves cannot say that they have
been overtaken.

See [ADR-0001](0001-record-architecture-decisions.md) for the process and
[`../templates/adr.md`](../templates/adr.md) to start one.

| # | Title | Status | Notes |
|---|-------|--------|-------|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted | |
| [0002](0002-gpl-license-and-dco.md) | GPL-3.0-or-later, and the DCO | Accepted | Whole repo GPL; the PDCA harness stays Apache-2.0 |

## Decisions not yet recorded here

The system design in [proposal 0001](../proposals/draft/0001-gnucash-auto-booking-pipeline.md)
contains several settled choices that would each make a reasonable ADR — the
two-process boundary, the defer-to-GnuCash principle, kNN over the Bayes matcher,
and the permanent scope exclusions. They are deliberately left in the proposal
for now rather than pre-emptively split out. Extract one into an ADR when it is
first cited to settle an argument; that is the moment its rationale needs to
stand on its own, and doing it earlier is filing for its own sake.

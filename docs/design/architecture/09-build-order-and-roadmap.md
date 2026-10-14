---
created: 14.10.2026 23:50
type: architecture
status: living
tags:
  - architecture
  - roadmap
  - build-order
---
# 9. Build order and roadmap

> Living document. The governing records of the ordering are
> [proposal 0001](../proposals/draft/0001-gnucash-auto-booking-pipeline.md)
> (*Build order*) and
> [proposal 0002](../proposals/draft/0002-document-driven-booking-via-paperless.md)
> (§8, milestones D0–D4). This section is their merged, always-current summary
> and tracks build status.

The strategy (section 4.2): **test the premise first, then build in the order
that becomes useful earliest and safest.** Sequencing matters more than any
individual decision.

## The milestones

| # | Milestone | Proves / retires | Status |
|---|-----------|------------------|--------|
| 0 + D0 | Spikes | Bindings/GnuCash version pair; PostgreSQL URI with non-default port; whether KVP slot access is needed; paperless API surfaces (original download, checksum, custom field query, audit-log actor); document-link binding; statement form | planned |
| 1 | Scheduled Transactions for rent, salary, insurance, standing orders | Deletes work before automating it — plausibly a third of volume | user task, not code |
| 2 | Corpus export, kNN, backtest harness | **The premise**: history is dense and consistent enough for kNN to abstain reliably. No writes, no LLM, no GUI. **Proposal 0001 is accepted or reworked on this result.** | planned — first code |
| D2 | Linkage backtest | **The second premise**: linked bills resolve a meaningful share of the residual. Read-only. Decision point for D3–D4. | after 2 |
| 3 | Ingest, staging, dedup | Statements become staged rows with stable keys | planned |
| D1 | Statements from paperless | Paperless as a source loses nothing against files; balance check in place | after 3 |
| 4 | Correlation pass | No transfer booked twice | planned |
| 5 | Applier and assertions, on a restored copy | Writes are exact, idempotent, reversible | planned |
| D3 | Bill linking and document links | Links written correctly on create and `match_existing`; order-independent matching | after 5 |
| 6 | Text review file and launcher | **Usable** — before any GUI, LLM or distribution work | planned |
| 7 + D4 | Shadow mode, one month | Per-method, per-band precision (including document-keyed rules) that justifies every threshold | planned |
| 8 | Rules file, LLM tail, thresholds lowered on evidence | Unattended booking at measured precision | planned |
| 9 | GTK4 rule builder, category indirection, packaging | Distributable to other users | planned |

Steps 2 and D2 are the two **decision points**: if either premise fails, the
design changes before more is built on it.

## Stopping points

- After **6**: a working personal tool with manual review of everything.
- After **7/D4**: a tool with measured precision, worth trusting unattended.
- After **9**: a distributable tool.

## Where to start contributing

Before code exists: the spikes (step 0/D0) and fixtures — synthetic statements
and synthetic books for each backend. Once step 2 lands, normalisation profiles
for banks other than the reference ones are the most independent contribution,
and every profile comes with its own backtest numbers.

## Deferred, with seats reserved

Not built early, but the design leaves room for them:

- **Line-item splits from invoices** (proposal 0002 §9) — the split-specification
  format and the exact-sum rule already accommodate them.
- **Programmatic creation of simple fixed-amount scheduled transactions** — only
  after the guide-and-verify path is proven.
- **A TUI review interface** (Textual) — only if the text file repeatedly lacks
  information needed to decide.
- **Foreign-currency accounts** — the same two-split shape plus a rate; more
  tractable than securities.
- **Upstream**: the Bayes-seeding patch and an external-matcher hook in GnuCash
  (proposal 0001, *Parallel track*), independent of everything here.

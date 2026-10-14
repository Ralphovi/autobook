---
created: 14.10.2026 23:50
type: architecture
status: living
tags:
  - architecture
  - strategy
  - quality-goals
---
# 4. Solution strategy

> Living document. The bridge between the quality goals (section 1.3) and the
> building blocks (section 5).

| Quality goal | Strategy | Where |
|--------------|----------|-------|
| Ledger integrity | A single process links libgnucash; everything else cannot write to a book by construction. | section 5, AGENTS.md |
| | Money as integer cents end to end; `GncNumeric` built from integers, never `from_double`. | section 8.1 |
| | Idempotency through the transaction `num` field: re-running any batch after any crash is safe. | sections 6.5, 8.2 |
| | Writer runs only with GnuCash closed, by sequencing in a launcher, never by breaking a lock. | section 6.1 |
| | Post-apply assertions through the engine API: Imbalance zero, balances equal statement closing balances. | section 6.5 |
| | Defer structural work to GnuCash's own assistants; never create accounts or scheduled transactions. | proposal 0001 |
| | Statements are the reference: read from original files only, balance-checked on admission. | proposal 0002 §3 |
| Privacy | Redaction at the model-adapter boundary; documents never reach the adapter. | section 8.5 |
| | Staging holds IDs, amounts and dates for documents, never content. | proposal 0002 §7 |
| | Shared artifacts carry pattern → category only; user rules are a separate, personal file. | section 8.5 |
| Calibrated automation | Cascade **rules → kNN → LLM**, ordered for determinism, not cost. | section 5.2 |
| | kNN with two independent gates (neighbour distance, vote margin); fail either and fall through. | section 5.2 |
| | Bill linking on exact amount only, feeding rules — never kNN or the LLM. | proposal 0002 §4–5 |
| | Thresholds move on backtest and shadow-mode evidence, never on a single miss. | section 8.3 |
| Auditability | Every proposal records method, evidence and the version tuple that produced it. | section 8.3 |
| | Two failure tiers: per-row problems queue the row; batch-level anomalies write nothing. | section 8.2 |
| | Version gate: production refuses to run when anything that changes classification has changed since the last validated trial. | section 8.3 |
| Distributability | Pipeline is pure Python in a venv, testable with no GnuCash installed. | section 5 |
| | Category indirection: packs map patterns to categories; a derived mapping binds categories to each user's accounts. | section 5.2 |
| | No-AI mode and file-only (no paperless) mode are first-class configurations. | section 7 |

## 4.1 The shape in one paragraph

A **pipeline** process, which never imports GnuCash, reads statements and bills,
normalises memos, removes duplicates, pairs up transfers between the user's own
accounts, links bills, and proposes an account for each remaining row — from a
rule if one fires, from the user's own history if the nearest neighbours are both
close and in agreement, from a constrained model call otherwise, or not at all.
Everything lands in a **staging** store that is the audit trail, the correction
corpus and the undo list. A plain text **review file** lets the user settle the
residual with their editor. A separate **book process**, the only code that links
libgnucash, exports the corpus and the chart of accounts for the pipeline, and
writes approved rows into the book with their proposal ID in `num`, then checks
the result. A **launcher** sequences all of this before GnuCash opens, so the
writer never races the GUI.

## 4.2 Build strategy

**Test the premise before building on it.** The design's central bet is that a
user's own history is dense and consistent enough for nearest-neighbour
classification to abstain reliably. The first code is a read-only corpus export
and backtest that answers that question with no writes, no LLM and no GUI; if
the answer is no, the design changes rather than a threshold. Proposal 0002 adds
a second premise test of the same kind (does bill linking shrink the residual?)
before any document write path is built.

After that, build in the order that becomes **useful earliest and safest**:
ingest and staging, then the applier against a restored copy, then the text
review file — at which point the tool is usable — then a month of shadow mode
before anything books unattended. GUI and distribution work come last. Section 9
has the milestones.

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
| Ledger integrity | Nothing reaches the book that was not marked `a` in a review file the user saved. | sections 5.2, 6.1 |
| | A single process, the book process, links libgnucash; everything else cannot write to a book by construction. | section 5, AGENTS.md |
| | Money as integer cents end to end; `GncNumeric` built from integers, never from a float. | section 8.1 |
| | Idempotency through the proposal ID in the `num` of each transaction Autobook creates, and the staged GUID of each matched one: re-running any batch after any crash is safe. | sections 6.5, 8.2 |
| | `session.save()` after the last edit; a row counts as applied only after a read-back finds it. | section 6.5 |
| | Writer runs only with GnuCash closed, by sequencing in a launcher, never by breaking a lock. | section 6.1 |
| | Post-apply assertions through the engine API: the batch moved each source account by exactly the applied amounts, the statement closing balance reconciles, Imbalance is unchanged. | section 6.5 |
| | Defer structural work to GnuCash's own assistants; never create accounts or scheduled transactions. A row on a scheduled-transaction occurrence matches the instance or waits for it, never creates. | proposal 0001, section 6.3 |
| | Statements are the reference: read from original files only, balance-checked on admission. | proposal 0002 §3 |
| Privacy | Redaction at the model-adapter boundary; documents never reach the adapter. A local backend by default; a remote one gets only allowlisted tokens and account indices. | section 8.5 |
| | Staging holds IDs, amounts and dates for documents, never content. | proposal 0002 §7 |
| | Shared artifacts carry pattern → category only; user rules are a separate, personal file. | section 8.5 |
| Calibrated automation | Cascade **rules → kNN → LLM** (k-nearest-neighbour, then large language model), ordered for determinism, not cost, under one precedence table. | section 5.2 |
| | kNN with two independent gates (neighbour distance, vote margin); fail either and fall through. | section 5.2 |
| | Only gated rows are pre-marked `a`; LLM rows stay `?` until shadow mode has measured their precision. | section 5.2 |
| | Bill linking on exact amount and a confirmed correspondent association only, feeding rules — never kNN or the LLM. | proposal 0002 §4–5 |
| | Thresholds move on rolling-origin backtest and shadow-mode evidence, never on a single miss. | section 8.3 |
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
corpus and the undo list. A plain text **review file** lists every row, the
gated ones pre-marked `a`; the user settles the rest in their editor, and saving
the file is the approval. A separate **book process**, the only code that links
libgnucash, has two parts: an **exporter** that reads the corpus, the chart of
accounts, existing transactions and scheduled-transaction definitions in a
read-only session, and an **applier** that writes approved rows into the book
(created ones with their proposal ID in `num`), saves, and checks the result. A
**launcher** sequences all of this before GnuCash opens, so the writer never
races the GUI.

## 4.2 Build strategy

**Test the premise before building on it.** The design's central bet is that a
user's own history is dense and consistent enough for nearest-neighbour
classification to abstain reliably. The first code is a read-only corpus export
and backtest that answers that question with no writes, no LLM and no GUI; if
the answer is no, the design changes rather than a threshold. Proposal 0002 adds
a second premise test of the same kind (does bill linking shrink the residual?)
before any document write path is built.

After that, build in the order that lets the tool be **tried on real statements
earliest**, safely: ingest and staging, then the text review file. The loop
closes there. Until the applier exists, saving the review file only records
decisions to staging, so shadow mode is the default state rather than a phase to
schedule. Correlation comes before the applier, which arrives together with the
launcher on a restored copy; thresholds are lowered only on the shadow-mode
evidence gathered meanwhile. GUI and distribution work come last. Section 9 is
the governing execution order.

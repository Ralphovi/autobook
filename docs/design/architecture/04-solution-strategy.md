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
> building blocks (section 5). The design is
> [proposal 0005](../proposals/draft/0005-beancount-ledger.md).

| Quality goal | Strategy | Where |
|--------------|----------|-------|
| Ledger integrity | Nothing reaches the ledger that was not marked `a` in a review file the user saved. | sections 5.2, 6.1 |
| | One package, the ledger package, imports `beancount`; everything else reaches the ledger through four typed contracts and cannot write to it by construction. The linter enforces the import rule. | section 5, proposal 0005 §3 |
| | Autobook writes transactions only, and only into the owned file. It never changes an entry it did not create; nothing is written to an existing entry that a statement line matched. | proposal 0005 §10.1 |
| | Money as integer cents end to end; `Decimal` built from integers, never from a float, and printed with exactly two decimals. | section 8.1 |
| | Every posting carries an explicit amount, and Autobook checks itself that postings sum to exactly zero, because Beancount's own check is tolerant. | section 8.1 |
| | Idempotency through the proposal ID in the `autobook-id` metadata of each entry Autobook creates, and the staged content hash of each matched one: re-running any batch after any crash is safe. | sections 6.5, 8.2 |
| | Compare, then replace: nothing is written if any ledger file changed since it was read, and the replacement is a single atomic rename. There is no lock to take and none to break. | section 6.5 |
| | Read back after writing; a row counts as applied only after the read-back and every assertion have passed. On any failure the previous file is restored, so no batch is ever partly booked. | section 6.5 |
| | Post-apply assertions through the reader: no new load error, no byte outside the appended entries changed, each source account moved by exactly the applied amounts, the statement closing balance agrees. | section 6.5 |
| | The chart of accounts and the balance assertions stay the user's; Autobook never writes `open` or `balance`. A row whose account is not open on its date, or does not allow its currency, is queued. | proposal 0005 §1, §8.1 |
| | A transfer is booked once: correlation runs before classification, and the second side resolves to the entry the first side created. | section 5.2 |
| | A statement is admitted whole or not at all: parsed, checked for consistency, and balance-checked where it states balances. | section 6.2, proposal 0005 §5 |
| Privacy | Redaction at the model-adapter boundary; documents never reach the adapter. A local backend by default; a remote one gets only allowlisted tokens and account indices. | section 8.5 |
| | Staging holds IDs, amounts and dates for documents, never content. | proposal 0002 §7 |
| | Shared artifacts carry pattern → category only; user rules are a separate, personal file. | section 8.5 |
| Calibrated automation | Cascade **rules → kNN → LLM** (k-nearest-neighbour, then large language model), ordered for determinism, not cost, under one precedence table. | section 5.2 |
| | Rules come first and are mostly mined from the user's own history; a human accepts each one against a measurement on a held-out period. | proposal 0004 |
| | kNN with two independent gates (neighbour distance, vote margin); fail either and fall through. | section 5.2 |
| | Only gated rows are pre-marked `a`; LLM rows stay `?` until shadow mode has measured their precision. | section 5.2 |
| | Bill linking on exact amount and a confirmed correspondent association only, feeding rules — never kNN or the LLM. | proposal 0002 §4–5 |
| | Thresholds move on rolling-origin backtest and shadow-mode evidence, never on a single miss. | section 8.3 |
| Auditability | Every proposal records method, evidence and the version tuple that produced it. | section 8.3 |
| | Every created entry is plain text in the owned file with its proposal ID on it; `autobook undo` removes exactly what a batch created. | section 6.7 |
| | Two failure tiers: per-row problems queue the row; batch-level anomalies write nothing. | section 8.2 |
| | Version gate: production refuses to run when anything that changes classification has changed since the last validated trial. | section 8.3 |
| Distributability | Beancount is an ordinary dependency: one process, one install, and everything outside the ledger package testable against fixtures with no ledger on disk. | section 5 |
| | Autobook is handed OFX and is not the driver, so it is not tied to how one person gets statements. | section 3 |
| | Category indirection: packs map patterns to categories; a derived mapping binds categories to each user's accounts. | section 5.2 |
| | No-AI mode and no-paperless mode are first-class configurations. | section 7 |

## 4.1 The shape in one paragraph

Autobook is **one program in one process**. A separate **driver** hands it OFX
statement files. The **input** part parses each file and admits the statement
whole or not at all. The **pipeline** normalises memos, removes duplicates,
pairs up transfers between the user's own accounts, links bills, and proposes an
account for each remaining row — from a rule if one fires, from the user's own
history if the nearest neighbours are both close and in agreement, from a
constrained model call otherwise, or not at all. Everything lands in a
**staging** store that is the audit trail, the correction corpus and the undo
list. A plain text **review file** lists every row, the gated ones pre-marked
`a`; the user settles the rest, and saving the file is the approval. The
**ledger package**, the only code that imports `beancount`, has two parts: a
**reader** that yields the corpus, the chart of accounts and the existing
entries of the user's Beancount ledger, and a **writer** that appends approved
rows as transactions to the one **owned file** the ledger includes (each with
its proposal ID as `autobook-id` metadata), loads the ledger again, checks the
result, and puts the previous file back if any check fails. Nothing sequences
Autobook against other programs: there is no lock, so the writer compares every
ledger file with what it read before it replaces anything.

## 4.2 Build strategy

**Settle the ground first.** The licence change (ADR-0005) and a handful of
spikes about Beancount's behaviour, recorded as tests, come before anything
else (milestone B0); then the one-off conversion of the author's GnuCash book
(B1), which is also the point where proposal 0005 is accepted or reworked.

**Test the premise before building on it.** The design's central bet is that
rules mined from a user's own history decide the bulk of the lines at measured
precision, and that the history is dense and consistent enough for
nearest-neighbour classification to abstain reliably on the rest. The
corpus, rule mining and backtest answer that question with no writes and no
LLM; if the answer is no, the design changes rather than a threshold. Because
the corpus contract did not change, this can run on a corpus exported from the
GnuCash book and need not wait for the conversion. Proposal 0002 adds a second
premise test of the same kind (does bill linking shrink the residual?) before
any document write path is built.

After that, build in the order that lets the tool be **tried on real statements
earliest**, safely: OFX input, admission and staging, then the text review file
and the rules file. The loop closes there. Until the writer exists, saving the
review file only records decisions to staging, so shadow mode is the default
state rather than a phase to schedule. Correlation comes before the writer — a
writer without the correlation pass double-books every transfer — and the
writer is proved on synthetic ledgers; thresholds are lowered only on the
shadow-mode evidence gathered meanwhile. The LLM tail and distribution work
(category indirection, packs, packaging) come last. Section 9 is the governing
execution order.

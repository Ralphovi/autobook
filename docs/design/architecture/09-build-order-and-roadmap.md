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

> Living document. This section is the **single governing execution order** for
> building Autobook, and tracks build status. The build-order sections of
> [proposal 0001](../proposals/draft/0001-gnucash-auto-booking-pipeline.md)
> (*Build order*) and
> [proposal 0002](../proposals/draft/0002-document-driven-booking-via-paperless.md)
> (§8, milestones D0–D4) describe *what* each step contains and why; the order
> in which the steps are carried out is decided here.

The strategy (section 4.2): **test the premise first, then build in the order
that lets the tool be tried on real statements earliest, safely.** Sequencing
matters more than any individual decision.

## The execution order

Milestone IDs are those of the proposals (0001's steps 0–9, 0002's D0–D4,
[proposal 0003](../proposals/draft/0003-rules-first-mined-from-history.md)'s
R1–R2) and are referenced elsewhere; the table lists them in the order they are
built.

| Order | # | Milestone | Proves / retires | Status |
|-------|---|-----------|------------------|--------|
| 1 | 0 + D0 | Spikes | Bindings/GnuCash version pair; PostgreSQL URI with non-default port; paperless API surfaces (original download with `?version=`, checksum, custom field query, document history actor with `PAPERLESS_AUDIT_LOG_ENABLED`); document-link binding; whether every non-statement, non-bill document in paperless has an owner (the dedicated user's restriction depends on it); statement form (PDF or export). KVP (key-value pair) slot access is not needed on the `match_existing` path: no FITID / `online_id` stamp is written there (decided) | planned |
| 2 | 1 | Scheduled Transactions for rent, salary, insurance, standing orders | Deletes work before automating it — plausibly a third of volume | user task, not code |
| 3 | 2 + R1 | Corpus export (the book process's read-only exporter), rule mining, kNN, rolling-origin backtest harness | **The premise**: mined rules decide the head at measured held-out precision, and history is dense and consistent enough for kNN (k-nearest-neighbour) to abstain reliably on the **residual** the rules leave, measured on novel memos. No writes, no LLM (large language model), no GUI. **Decision point; proposals 0001 and 0003 are accepted or reworked on this result.** | planned — first code |
| 4 | D2 | Linkage backtest | **The second premise**: linked bills resolve a meaningful share of the residual. Read-only. **Decision point** for D3 and D4 (if it fails, proposal 0002 stops at D1); **proposal 0002 is accepted or revised on this report.** | planned |
| 5 | 3 | Ingest, staging, dedup | Statements become staged rows with stable keys | planned |
| 6 | 6 + R2 | Text review file (no launcher); rules file, rule engine and the candidate file for accepting mined rules | **The loop closes here**: real statements in, accepted rules first, proposals shown, decisions recorded. Until the applier exists, saving the review file records decisions to staging and writes nothing, so shadow mode is the default state | planned |
| 7 | D1 | Statements from paperless | Paperless as a source loses nothing against files; balance check in place | planned |
| 8 | 4 | Correlation pass | No transfer booked twice, within a batch or across batches | planned |
| 9 | 5 | Book process: applier, assertions and launcher, on a restored copy | Writes are exact, saved, confirmed by read-back, idempotent and reversible; the launcher always reaches `exec gnucash` | planned |
| 10 | D3 | Bill linking and document links | Links written correctly on create and `match_existing`; order-independent matching | planned |
| 11 | 7 + D4 | Shadow evidence | Per-method, per-band precision (document-keyed rules and `method=llm` included) that justifies every threshold. Continuous from step 6 on; closes when there is enough evidence | planned |
| 12 | 8 | LLM tail, LLM rule drafting, thresholds on evidence | Thresholds lowered on evidence: more rows pre-marked `a` at measured precision | planned |
| 13 | 9 | GTK4 rule builder, category indirection, packaging | Distributable to other users | planned |

Steps 2 and D2 are the two **decision points**: if either premise fails, the
design changes before more is built on it.

## Why this order

The proposals order their steps by information gained per hour. This order
optimises a related but different goal: **how soon the tool can be tried on
real statements**. The smallest loop that lets a user judge the tool is ingest →
classify → show the proposals: steps 2, 3 and 6. It needs no applier, no
correlation, no LLM and no GUI, so the review file moves ahead of the write
path. It does include the rules file (R2): its rules are mined from history and
accepted in a text file, so they cost no GUI, and they make the first loop
deterministic for the head of the volume (proposal 0003).

Some things keep their place for reasons that are not preference:

- **Step 2 stays first.** It is the only step that can invalidate the design
  rather than delay it: if history is too sparse or inconsistent for kNN to
  abstain reliably, the answer is a different design, not a lower threshold. It
  produces a backtest report over real history with no UI at all, so it costs
  the "try it early" goal nothing. D2 follows for the same reason.
- **Step 4 comes before step 5.** An applier that writes without the
  correlation pass double-books every transfer between the user's own accounts.
- **Step 9 stays last.** The rule builder's core panel is "propose a rule →
  backtest against history → show the verdict". That is backtest machinery with
  a window around it; built earlier it would be a GUI over fake data.

Two consequences follow:

- **Shadow mode is structural.** With the review file landing before the
  applier, there is no write path during early use, so shadow mode is the
  default state by construction rather than a month to schedule. Step 7/D4 now
  tracks the *evidence*, continuously, and closes when there is enough of it to
  justify step 8's thresholds. The decisions saved meanwhile are the correction
  corpus, so none of that work is thrown away.
- **The launcher moved from step 6 to step 5.** It sequences backup → read-only
  export → pipeline → review → apply → assert → `exec gnucash`; before the
  applier exists there is nothing to sequence.

This order folds in the reasoning of tracker issue #13.

## Stopping points

- After **6**: proposals for real statements, reviewed in the editor, decisions
  recorded; nothing written to the book.
- After **5** (with D3 for documents): a working personal tool — one save of the
  pre-filled review file books the batch.
- After **7/D4**: measured precision, enough to justify pre-marking more rows.
- After **9**: a distributable tool.

## Where to start contributing

Before code exists: the spikes (step 0/D0) and fixtures — synthetic statements
and synthetic books for each backend. Once step 2 lands, normalisation profiles
for banks other than the reference ones are the most independent contribution,
and every profile comes with its own backtest numbers.

## Deferred, with seats reserved

Not built early, but the design leaves room for them:

- **Line-item splits from invoices** (proposal 0002 §9) — the split-specification
  format and the exact-sum rule already accommodate them. They would also
  require amending the "splits are rules-tier only" MUST (AGENTS.md, proposal
  0001) through a **new ADR**, not just a proposal; the candidate is listed in
  the [ADR index](../adr/README.md).
- **Unattended (headless) runs** **[DEFERRED]** beyond v1 — approval is a save
  of the review file, so a run without an editor would need a different
  approval model (section 7.1).
- **Programmatic creation of simple fixed-amount scheduled transactions** — only
  after the guide-and-verify path is proven.
- **A TUI review interface** (Textual) — only if the text file repeatedly lacks
  information needed to decide.
- **Upstream**: the Bayes-seeding patch and an external-matcher hook in GnuCash
  (proposal 0001, *Parallel track*), independent of everything here.

**No seat for foreign-currency accounts.** Splits in a currency other than the
account's are a permanent exclusion, settled in proposal 0001 (ADR-0001 cites it
as an example of a decision to record, not re-argue). Proposal 0001 notes they would be more tractable to
revisit than securities (the same two-split shape plus a rate), but revisiting
needs a new ADR that supersedes that decision; it is listed as a candidate in
the [ADR index](../adr/README.md).

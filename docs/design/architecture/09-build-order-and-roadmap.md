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
> [proposal 0005](../proposals/draft/0005-beancount-ledger.md) (§16; the design),
> [proposal 0002](../proposals/draft/0002-document-driven-booking-via-paperless.md)
> (§8, milestones D0–D4) and
> [proposal 0004](../proposals/draft/0004-rules-first-mined-from-history.md)
> (milestones R1–R2) describe *what* each step contains and why; the order in
> which the steps are carried out is decided here.

The strategy (section 4.2): **test the premise first, then build in the order
that lets the tool be tried on real statements earliest, safely.** Sequencing
matters more than any individual decision.

## The execution order

Milestone IDs are those of the proposals: 0005's B0 and B1, the step numbers
2–9 it keeps from the earlier order, 0002's D2–D4 and 0004's R1–R2. They are
referenced elsewhere; the table lists them in the order they are built. The
step numbers are kept, with gaps, because the tracker's issues are named after
them (for example `5a — apply-in / apply-out contracts and idempotency
filter`). Some issue titles still name things this design dropped; what a step
contains is what this table and proposal 0005 say.

Terms used in the table: the **driver** is the separate program that gets
statements, converts them to OFX and calls Autobook's commands. The **ledger
package** is the only code that imports `beancount`; its **reader** loads the
ledger and its **writer** changes it. The **owned file** is the one ledger file
Autobook writes to. `coa`, `corpus`, `existing` and `apply-in` / `apply-out`
are the contracts between the ledger package and the rest (section 5.1).

| Order | # | Milestone | Proves / retires | Status |
|-------|---|-----------|------------------|--------|
| 1 | B0 | [ADR-0005](../adr/0005-relicense-gpl-2-or-later.md) accepted and the licence files changed. Spikes, recorded as tests: a reader that emits `coa` and `corpus` from a synthetic ledger; content-hash stability; the root-name options check; what Fava and common editors do when the owned file is replaced under them | The licence, and the facts the write path rests on | planned. ADR-0005 is Proposed; no code imports `beancount` yet. The `coa` contract in `contracts.py` still has the earlier GnuCash shape and changes here |
| 2 | B1 | Conversion of the GnuCash book (proposal 0005 §14): a full export, a writer that turns it into ledger files, a reviewed decision file, mechanical verification | The converted ledger equals the book. **Decision point: proposal 0005 is accepted or reworked.** | planned — human-run, attended |
| 3 | 2 + R1 | Corpus, rule mining, kNN, rolling-origin backtest harness. The `corpus` contract is unchanged, so this can run on a corpus from the GnuCash export and need not wait for B1 | **The premise**: mined rules decide the head at measured held-out precision, and history is dense and consistent enough for kNN (k-nearest-neighbour) to abstain reliably on the **residual** the rules leave, measured on novel memos. No writes, no LLM (large language model). **Decision point; proposal 0004 is accepted or reworked on this result.** | partly built. Implemented, with tests: the `corpus` contract (parse and serialise), the normaliser with its profiles, the kNN index with both gates, and the rolling-origin backtest with the token-Bayes control and the novel-stratum sweep, run as `python -m autobook.pipeline.trial backtest`. Not yet built: the reader that produces a corpus from a ledger, rule mining (R1), and the `autobook` command itself. The tests use synthetic corpora; no report on real history is recorded yet, so the decision is open |
| 4 | D0 + D2 | Paperless spikes for bills, then the linkage backtest | **The second premise**: linked bills resolve a meaningful share of the residual. Read-only. **Decision point** for D3 and D4; **proposal 0002 is accepted or revised on this report.** | planned |
| 5 | 3 | OFX input, admission, staging, dedup | Statements become staged lines with stable keys; a bad statement is rejected whole | planned |
| 6 | 6 + R2 | Review file with its strict parser; rules file, rule engine and the candidate file for accepting mined rules | **The loop closes here**: real statements in, accepted rules first, proposals shown, decisions recorded. Until the writer exists, `autobook decide` records the saved review file's decisions to staging and nothing is written, so shadow mode is the default state | planned |
| 7 | 4 | Correlation pass: transfers within and across batches, `match_existing` | No transfer booked twice, within a batch or across batches | planned |
| 8 | 5 | Ledger writer: `init`, apply, read-back, assertions, undo, the entry-format specification | Writes are exact, whole or nothing, confirmed by read-back, idempotent and reversible | planned |
| 9 | D3 | Bill linking; `autobook-doc` on created entries | Links are right and change nothing else; on a match nothing is written and the link is in staging only; order-independent matching | planned |
| 10 | 7 + D4 | Shadow evidence | Per-method, per-band precision (document-keyed rules and `method=llm` included) that justifies every threshold. Continuous from step 6 on; closes when there is enough evidence | planned |
| 11 | 8 | LLM tail, LLM rule drafting, thresholds on evidence | Thresholds lowered on evidence: more rows pre-marked `a` at measured precision | planned |
| 12 | 9 | Category indirection, packs, packaging | Usable by other people who keep a Beancount ledger | planned |

B1, step 2 and D2 are the **decision points**: if the conversion does not
reproduce the book, or either premise fails, the design changes before more is
built on it. Proposal 0005 is accepted when B0 and B1 have reported.

Dropped from the earlier order: step 0's GnuCash spikes, step 1 (Scheduled
Transactions; Beancount has none, and recurring debits are ordinary rule
candidates), D1 (statements from paperless, which is the driver's job now), and
the windows of step 9. The paperless spikes of proposal 0002's D0 that concern
bills (document history and its actor, custom-field queries, whether every
other document has an owner) are done with D2, before it reports. D0's spikes on
statement files and on setting a document link no longer apply.

**Tests.** Everything runs in `nox -s gate` against synthetic ledgers in
temporary directories, on every supported Python version. The Docker test
environment keeps paperless; its GnuCash image stays only for the export half
of the conversion and is removed with it. A real ledger, or a copy of one, is
opened only by a human, attended.

## Why this order

The proposals order their steps by information gained per hour. This order
optimises a related but different goal: **how soon the tool can be tried on
real statements**. The smallest loop that lets a user judge the tool is admit →
classify → show the proposals: steps 2, 3 and 6. It needs no writer, no
correlation and no LLM, so the review file moves ahead of the write path. It
does include the rules file (R2): its rules are mined from history and accepted
in a text file, and they make the first loop deterministic for the head of the
volume (proposal 0004).

Some things keep their place for reasons that are not preference:

- **B0 and B1 come first.** B0 settles the licence under which any code that
  imports `beancount` can be distributed, and records as tests the facts the
  write path rests on. B1 produces the ledger everything else reads: for the
  author, the booking history that rule mining and kNN learn from comes from
  the converted book. If the conversion cannot be verified, proposal 0005 is
  reworked, not patched.
- **Step 2 follows at once, and need not wait for B1.** It is the only step that
  can invalidate the classification design rather than delay it: if history is
  too sparse or inconsistent for kNN to abstain reliably, the answer is a
  different design, not a lower threshold. It produces a backtest report over
  real history with no review file and no writes, so it costs the "try it
  early" goal nothing. D2 follows for the same reason.
- **Step 4 comes before step 5.** A writer without the correlation pass
  double-books every transfer between the user's own accounts.
- **Step 9 stays last.** A pack is validated against the user's history with
  the same machinery that scores a candidate rule (proposal 0005 §15), and
  category mappings are derived from booked history. Built earlier, both would
  rest on fake data.

Two consequences follow:

- **Shadow mode is structural.** With the review file landing before the
  writer, there is no write path during early use, so shadow mode is the
  default state by construction rather than a month to schedule. Step 7/D4 now
  tracks the *evidence*, continuously, and closes when there is enough of it to
  justify step 8's thresholds. The decisions saved meanwhile are the correction
  corpus, so none of that work is thrown away.
- **Nothing in this order waits for the driver.** No Autobook command starts an
  editor or another program (section 5.5), so each step can be exercised by
  running the commands by hand on OFX files. The driver is built to its own
  plan (section 5.4).

This order folds in the reasoning of tracker issue #13 and the build order of
proposal 0005 (tracking issue #100).

## Stopping points

- After **6**: proposals for real statements, reviewed in the editor, decisions
  recorded; nothing written to the ledger.
- After **5** (with D3 for documents): a working personal tool — `autobook
  apply` with the saved review file books the batch.
- After **7/D4**: measured precision, enough to justify pre-marking more rows.
- After **9**: a tool other people can use.

## Where to start contributing

The spikes of B0 and fixtures: synthetic OFX statements and synthetic ledgers
that tests build in temporary directories. Normalisation profiles for banks
other than the reference ones are the most independent contribution; the
normaliser and the backtest exist, so every profile comes with its own backtest
numbers.

## Deferred, with seats reserved

Not built early, but the design leaves room for them:

- **Line-item splits from invoices** (proposal 0002 §9) — the split-specification
  format and the exact-sum rule already accommodate them. They would also
  require amending the "splits are rules-tier only" MUST (AGENTS.md, proposal
  0005 §6.1) through a **new ADR**, not just a proposal; the candidate is listed
  in the [ADR index](../adr/README.md).
- **Unattended runs** **[DEFERRED]** beyond v1 — approval is a save of the
  review file, so a run with nobody to save one would need a different approval
  model (section 7.1).
- **`balance` directives from statements** — a statement's closing balance is
  the bank's figure. Writing it as a `balance` directive once every line is
  applied would make the check permanent, and would put a standing error into
  the ledger whenever the user and the bank disagree. Not in v1 (proposal 0005,
  *Open questions*); it would also widen "transactions only".
- **A richer review surface** — none, a Fava extension, or a terminal UI.
  Decided at step 9 (order 12), on what the review file has turned out to lack
  (proposal 0005, *Open questions*).

Outside this order altogether:

- **The driver.** Getting statements, converting them to OFX with ofxstatement,
  deciding when to run, opening the review file in an editor and notifying the
  user belong to a separate project in its own repository, with its own plan
  (section 5.4). Whether OFX files and a producer string are enough of a
  contract, or `propose` should also take the original statement's checksum, is
  an open question of proposal 0005.

**No seat for foreign-currency accounts.** Postings in a currency other than
the account's are a permanent exclusion, settled before and restated in
proposal 0005 §1 (ADR-0001 cites it as an example of a decision to record, not
re-argue). They would need postings with a cost or a price, which break the
plain two-posting, one-currency shape everything is built on. Beancount
expresses them more easily than GnuCash did; that is not new evidence about
classification and does not reopen the exclusion. Revisiting needs a new ADR
that supersedes that decision; it is listed as a candidate in the
[ADR index](../adr/README.md).

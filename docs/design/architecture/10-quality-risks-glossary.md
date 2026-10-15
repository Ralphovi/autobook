---
created: 14.10.2026 23:50
type: architecture
status: living
tags:
  - architecture
  - quality
  - risks
  - glossary
  - testing
---
# 10–13. Quality, risks, glossary, and testing strategy

> Living document. Combines arc42 sections 10 (quality scenarios), 11 (risks and
> technical debt) and 12 (glossary), plus the testing strategy (section 13).

## 10. Quality scenarios

Concrete, measurable scenarios for the quality goals (section 1.3). Numbers
marked *T* are set from backtest and shadow-mode evidence, not chosen in advance.

| # | Scenario | Measure | Goal |
|---|----------|---------|------|
| Q1 | The book process crashes after committing some transactions | Re-running the batch creates no duplicates; no row is reported applied without a read-back; staging reconciles; Imbalance unchanged | 1 |
| Q2 | Both sides of a transfer are imported, in the same batch or in different batches | Exactly one transaction exists | 1 |
| Q3 | A mortgage payment falls on a scheduled-transaction (SX) occurrence | If GnuCash has created the instance, the bank row resolves as `match_existing` in its source account. If not yet — GnuCash creates instances at GUI start-up, after the apply — the row queues as "awaiting scheduled transaction" and resolves on a later run. Never a second transaction | 1 |
| Q4 | A plugin drops one line from a statement that carries balances | The balance check rejects the statement; nothing is staged from it | 1 |
| Q5 | The review file has a typo in an account name | The parse aborts with a line number; nothing is applied | 1 |
| Q6 | GnuCash is open when the writer starts | Nothing is written; no lock is broken | 1 |
| Q7 | A row is sent to a remote model backend | Only an allowlisted token, account indices, amount and sign leave the machine; a token not on the allowlist makes the large language model (LLM) abstain and nothing is sent — verified by test at the adapter boundary | 2 |
| Q8 | A batch is classified | Share of in-scope rows pre-marked `a` ≥ *T* at precision ≥ *T*, per method and confidence band, from shadow mode | 3 |
| Q9 | A merchant never seen before appears | kNN (k-nearest-neighbour) abstains (distance gate) rather than returning a confident guess; measured as error rate on the novel stratum of the rolling-origin backtest | 3 |
| Q10 | A bank changes its memo format | Coverage drop detected; batch refused with a specific reason; nothing wrong written | 3, 4 |
| Q11 | The user asks why a row was booked to an account | Staging shows method, rule ID or neighbours, document link and version tuple | 4 |
| Q12 | Last night's batch was wrong | Undo removes exactly the transactions the batch created (GUID staged as `create` and `num` equal to the proposal ID), the document links it added, and its paperless stamps | 4 |
| Q13 | A new user with an XML book and no paperless installs it | Full pipeline runs; document features are absent, nothing else degrades | 5 |
| Q14 | The user saves the review file after changing a pre-marked row from `a` to `?` | That row is not written; every row written has the account, amount and date the saved file showed | 1 |

## 11. Risks and technical debt

| Risk | Nature | Mitigation |
|------|--------|------------|
| The kNN premise fails on real history | Sparse or inconsistent bookings make abstention unreliable; the design depends on it | Step 2 tests it before anything else is built; the design changes, not a threshold |
| Silent mis-booking through drift | A bank or plugin change degrades precision while everything "works" | Coverage and LLM-fallback drift detection; version gate; balance checks |
| AI-applied paperless tags deciding accounts | A model decides by proxy through a document-keyed rule | Shadow mode per rule; audit-log provenance (proposal 0002 §5.2): the document history names an actor, `System` or none means machine, and a user accepting an AI suggestion is recorded as that user — so such rules are still shadowed |
| Bindings are thinly documented and change between GnuCash versions | Write-path surprises; deprecated session flags in examples | Spikes; restored-copy tests; upstream bug reports; friction log |
| Version skew between `python3-gnucash` and the book | An older binding cannot open an upgraded book; a newer one could upgrade it | Fail loudly on open; never write a book that would need a format upgrade |
| A shared pack mis-books the head of the market | One bad entry affects every user | Ambiguity flags (`AMAZON`, `PAYPAL`); signing or pinning; validation against each user's history before enabling |
| Review-file fatigue | A long pre-filled file gets saved unread, which approves rows without the gates | Keep the `?` rows few by design; pre-mark only gated rows, never LLM rows before their precision is measured; show evidence per row; shadow-mode numbers before lowering thresholds |
| Single maintainer | Bus factor of one | Design in-repo, conventions in AGENTS.md, gates mechanical |

### Conscious exclusions (not debt — decisions)

- Securities transactions — structural, not classification (proposal 0001).
- Splits denominated in a currency other than the account's — permanent, settled
  in proposal 0001; revisiting needs an ADR (section 9).
- Statement acquisition from banks and mail retrieval.
- Creating accounts, scheduled transactions or reconciled flags from code.
- Windows, until the bindings exist there or a maintainer for the build does.
- Collecting or pooling user transactions for any purpose.
- Autobook-side optical character recognition (OCR) or document extraction (proposal 0002 §1).
- Unattended (headless) booking — **[DEFERRED]** beyond v1, not excluded:
  approval is a save of the review file.

## 12. Glossary

| Term | Meaning |
|------|---------|
| Abstention | Declining to predict because the nearest neighbours are too far or disagree; the row falls through or queues. |
| Admission | Accepting a statement into staging: checksum verified, plugin run, balance check, row keys, overlap rule. All or nothing per statement; recorded as `admitted` or `rejected` with a reason. |
| Applier | The writing part of the book process (build step 5): creates or matches approved rows, saves, reads back, asserts. Also the name of the nox session and pytest marker that cover all book-process tests. |
| Approval | Saving the review file. Approves every row marked `a` in the saved file, as shown; nothing else reaches the book. |
| Balance check | At admission, the statement's lines must sum exactly to closing minus opening balance, in cents; where the format has no balances, recorded as not possible. |
| Batch | The rows processed in one run; the unit of refusal and of undo. |
| Book process | The only process that links libgnucash. Two parts: exporter and applier. The `gnucash` import ban, which applies to the pipeline, is lifted for it. |
| Category | A locale-neutral semantic label (`groceries`) that packs target instead of accounts. |
| CoA | Chart of accounts: the book's account tree. |
| Corpus | Two-split transactions used for kNN: `observed` rows from the book export, `corrected` rows from staging. |
| Correlation | Pairing the two sides of a transfer between the user's own accounts, within a batch or across batches (`transfers_pending`). |
| Correspondent association | A confirmed pairing of a paperless correspondent with a normalised merchant token, derived from history and kept in the user rules file. Required before a bill can link to a row. |
| Disposition | One of `create`, `create_split`, `match_existing`, `out_of_scope`, `queue`. |
| Document link | GnuCash's per-transaction link to an external document; here the paperless URL. |
| Document-keyed rule | A rule that tests document conditions (paperless correspondent, document type, tag) of a linked bill. `auto: false` by default. |
| Exporter | The read-only part of the book process (build step 2): exports corpus, CoA and `existing` (including SX definitions) in a `SESSION_READ_ONLY` session. |
| FITID | A statement's per-transaction ID, where the format has one. |
| kNN | k-nearest-neighbour classification over the user's own history. |
| KVP | Key-value pair: GnuCash's slot storage on book objects. Autobook does not write it. |
| Linkage backtest | Milestone D2: a read-only measurement of how many rows the cascade abstains on would gain a linked bill. A decision point. |
| Overlap rule | A statement whose period overlaps an admitted one is admitted only if every line in the overlap matches a staged line, counting duplicates. |
| Pack | A versioned, shareable set of pattern → category rules with no personal data. |
| PDCA | Plan-do-check-act; the out-of-tree development harness `autobook-pdca` is named after it. |
| Proposal ID | `AB-` plus a ULID, generated per staged row, distinct from the staging key. Written to `num` only on transactions Autobook creates; only values matching `^AB-[0-9A-HJKMNP-TV-Z]{26}$` count. |
| Provenance | Where a corpus row came from: `observed` (book) or `corrected` (review decision). Nothing else can enter the index. |
| Residual | Rows that need a human decision: those left at `?` in the review file. |
| Scenario 1 / 2 | Trial (read-only, backtests, rule building) / production (writes what a saved review file approved, gated). |
| Shadow mode | The classifier proposes while the user decides; produces precision data. The default state until the applier exists, and continuous evidence-gathering after. |
| Stamp | An optional paperless tag and custom field written to a linked bill for the user's convenience; never read back to decide anything. |
| Staging | The store between classification and writing; audit trail, corpus of corrections, undo list. |
| Statement source | Where statements come from: paperless or files, both first-class, feeding the same admission path. |
| SX | Scheduled transaction: a GnuCash recurring booking, instantiated at GUI start-up. |
| TF-IDF | Term frequency–inverse document frequency: the weighting of the character n-grams the kNN index is built on. |
| Version tuple | Everything that can change a classification, recorded per validated trial and required by production. |

## 13. Testing strategy

### 13.1 The principle: measure against the user's own history

Classification quality is measured by **rolling-origin backtest against the
corpus** (index from the rows before month m, test on month m), per method and
per confidence band, stratified by seen-before versus novel memos, with
token-Bayes as a negative control — never by impression. Thresholds and rules
are accepted on those numbers, gate thresholds on the novel stratum. Shadow mode
then measures the same thing on live data before any threshold pre-marks more
rows.

### 13.2 The tiers

| Tier | What | Where |
|------|------|-------|
| Unit and property tests | Normaliser, parser, review-file parser (round-trip, reordering, malformed input), money arithmetic (exact sums), bill matching (order independence) | `nox -s test`, no GnuCash, part of the gate |
| Boundary tests | The pipeline imports no `gnucash`; the model adapter cannot receive a raw memo or an account name, and a remote backend receives only allowlisted tokens; no float on monetary paths | Lint and tests in the gate |
| Book-process tests | Export (including SX definitions), create, split, `match_existing` (no `num`, no stamp), save and read-back per backend, idempotent re-run, undo (GUID and `num` both checked), assertions, document links — against synthetic books for XML, SQLite and PostgreSQL | `nox -s applier` (the name covers every book-process test, exporter included), local only, restored copies or synthetic books, never a real book |
| Backtest | Rolling-origin over a real corpus export, stratified seen/novel; leave-one-out only as an upper bound | Local, read-only; results reported, data never committed |
| Shadow mode | Parallel proposals, continuous until the evidence suffices | The reference deployment |

### 13.3 Test data

Fixtures are synthetic or derived from published format documentation. No
transaction from a real statement, even normalised, is ever committed —
normalised memos still carry names, IBANs and creditor IDs (CONTRIBUTING.md).

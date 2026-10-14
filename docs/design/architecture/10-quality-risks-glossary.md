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
| Q1 | The book process crashes after committing some transactions | Re-running the batch creates no duplicates; staging reconciles; Imbalance stays zero | 1 |
| Q2 | Both sides of a transfer are imported | Exactly one transaction exists | 1 |
| Q3 | A scheduled transaction already booked a mortgage payment | The bank row resolves as `match_existing`; no second transaction | 1 |
| Q4 | A plugin drops one line from a PDF statement | The balance check rejects the statement; nothing is staged from it | 1 |
| Q5 | The review file has a typo in an account name | The parse aborts with a line number; nothing is applied | 1 |
| Q6 | GnuCash is open when the writer starts | Nothing is written; no lock is broken | 1 |
| Q7 | A row is sent to the model backend | Only token, amount and sign leave the machine — verified by test at the adapter boundary | 2 |
| Q8 | A batch is classified | Unattended share of in-scope rows ≥ *T* at precision ≥ *T*, per method and confidence band, from shadow mode | 3 |
| Q9 | A merchant never seen before appears | kNN abstains (distance gate) rather than returning a confident guess; measured as error rate on novel-merchant rows | 3 |
| Q10 | A bank changes its memo format | Coverage drop detected; batch refused with a specific reason; nothing wrong written | 3, 4 |
| Q11 | The user asks why a row was booked to an account | Staging shows method, rule ID or neighbours, document link and version tuple | 4 |
| Q12 | Last night's batch was wrong | Undo by `num` removes exactly that batch's transactions and stamps | 4 |
| Q13 | A new user with an XML book and no paperless installs it | Full pipeline runs; document features are absent, nothing else degrades | 5 |

## 11. Risks and technical debt

| Risk | Nature | Mitigation |
|------|--------|------------|
| The kNN premise fails on real history | Sparse or inconsistent bookings make abstention unreliable; the design depends on it | Step 2 tests it before anything else is built; the design changes, not a threshold |
| Silent mis-booking through drift | A bank or plugin change degrades precision while everything "works" | Coverage and LLM-fallback drift detection; version gate; balance checks |
| AI-applied paperless tags deciding accounts | A model decides by proxy through a document-keyed rule | Shadow mode per rule; audit-log provenance if available (proposal 0002 §5.2) |
| Bindings are thinly documented and change between GnuCash versions | Write-path surprises; deprecated session flags in examples | Spikes; restored-copy tests; upstream bug reports; friction log |
| Version skew between `python3-gnucash` and the book | An older binding cannot open an upgraded book; a newer one could upgrade it | Fail loudly on open; never write a book that would need a format upgrade |
| A shared pack mis-books the head of the market | One bad entry affects every user | Ambiguity flags (`AMAZON`, `PAYPAL`); signing or pinning; validation against each user's history before enabling |
| Review-file fatigue | A long queue gets rubber-stamped, which is unattended booking without the gates | Keep the queue short by design; show evidence per row; shadow-mode numbers before lowering thresholds |
| Single maintainer | Bus factor of one | Design in-repo, conventions in AGENTS.md, gates mechanical |

### Conscious exclusions (not debt — decisions)

- Securities transactions — structural, not classification (proposal 0001).
- Splits denominated in a currency other than the account's.
- Statement acquisition from banks and mail retrieval.
- Creating accounts, scheduled transactions or reconciled flags from code.
- Windows, until the bindings exist there or a maintainer for the build does.
- Collecting or pooling user transactions for any purpose.
- Autobook-side OCR or document extraction (proposal 0002 §1).

## 12. Glossary

| Term | Meaning |
|------|---------|
| Abstention | Declining to predict because the nearest neighbours are too far or disagree; the row falls through or queues. |
| Batch | The rows processed in one run; the unit of refusal and of undo. |
| Book process | The only process that links libgnucash; exports and applies. |
| Category | A locale-neutral semantic label (`groceries`) that packs target instead of accounts. |
| Corpus | Two-split transactions exported from the book, tagged `observed` or `corrected`. |
| Correlation | Pairing the two sides of a transfer between the user's own accounts. |
| Disposition | One of `create`, `create_split`, `match_existing`, `out_of_scope`, `queue`. |
| Document link | GnuCash's per-transaction link to an external document; here the paperless URL. |
| FITID | A statement's per-transaction ID, where the format has one. |
| Pack | A versioned, shareable set of pattern → category rules with no personal data. |
| Residual | Rows that need a human decision. |
| Scenario 1 / 2 | Trial (read-only, backtests, rule building) / production (writes, gated). |
| Shadow mode | Classifier proposes in parallel while the user books by hand; produces precision data. |
| Staging | The store between classification and writing; audit trail, corpus of corrections, undo list. |
| Version tuple | Everything that can change a classification, recorded per validated trial and required by production. |

## 13. Testing strategy

### 13.1 The principle: measure against the user's own history

Classification quality is measured by **backtest against the corpus**, per
method and per confidence band, with token-Bayes as a negative control — never
by impression. Thresholds and rules are accepted on those numbers. Shadow mode
then measures the same thing on live data before anything books unattended.

### 13.2 The tiers

| Tier | What | Where |
|------|------|-------|
| Unit and property tests | Normaliser, parser, review-file parser (round-trip, reordering, malformed input), money arithmetic (exact sums), bill matching (order independence) | `nox -s test`, no GnuCash, part of the gate |
| Boundary tests | The pipeline imports no `gnucash`; the model adapter cannot receive a raw memo; no float on monetary paths | Lint and tests in the gate |
| Book-process tests | Create, split, `match_existing`, idempotent re-run, undo, assertions, document links — against synthetic books for XML, SQLite and PostgreSQL | `nox -s applier`, local only, restored copies or synthetic books, never a real book |
| Backtest | Leave-one-out over a real corpus export | Local, read-only; results reported, data never committed |
| Shadow mode | A month of parallel proposals | The reference deployment |

### 13.3 Test data

Fixtures are synthetic or derived from published format documentation. No
transaction from a real statement, even normalised, is ever committed —
normalised memos still carry names, IBANs and creditor IDs (CONTRIBUTING.md).

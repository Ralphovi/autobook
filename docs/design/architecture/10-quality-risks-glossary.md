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
> technical debt) and 12 (glossary), plus the testing strategy (section 13). The
> design is [proposal 0005](../proposals/draft/0005-beancount-ledger.md).

## 10. Quality scenarios

Concrete, measurable scenarios for the quality goals (section 1.3). Numbers
marked *T* are set from backtest and shadow-mode evidence, not chosen in advance.
The exit codes are those of the command line (section 5.5).

| # | Scenario | Measure | Goal |
|---|----------|---------|------|
| Q1 | Autobook crashes at any point between rendering the entries and marking the rows applied | Re-running the batch creates nothing twice; no row is reported applied without a read-back; staging reconciles; the ledger loads with no new error | 1 |
| Q2 | Both sides of a transfer are imported, in the same batch or in different batches | Exactly one entry exists | 1 |
| Q3 | A loan instalment arrives whose interest and principal change every period | The line is queued, never split by a guess. Once the user has written the entry by hand, the line resolves as `match_existing` in its source account. Never a second entry | 1 |
| Q4 | The OFX file handed over lacks one line of a statement that carries balances | The balance check rejects the statement (exit 7); nothing is staged from it; other statements in the same call proceed | 1 |
| Q5 | The review file has a typo in an account name | The parse aborts with a line number (exit 5); nothing is applied | 1 |
| Q6 | A ledger file changes during the run — the user saves an edit, or Fava writes — between Autobook's read and its replace | Nothing is written (exit 4); the changed file is untouched | 1 |
| Q7 | A row is sent to a remote model backend | Only an allowlisted token, account indices, amount and sign leave the machine; a token not on the allowlist makes the large language model (LLM) abstain and nothing is sent — verified by test at the adapter boundary | 2 |
| Q8 | A batch is classified | Share of in-scope rows pre-marked `a` ≥ *T* at precision ≥ *T*, per method and confidence band, from shadow mode | 3 |
| Q9 | A merchant never seen before appears | kNN (k-nearest-neighbour) abstains (distance gate) rather than returning a confident guess; measured as error rate on the novel stratum of the rolling-origin backtest | 3 |
| Q10 | A bank changes its memo format, or the driver's converter plugin is updated | Coverage drop detected, or the producer string differs from the validated version tuple; batch refused with a specific reason (exit 3); nothing wrong written | 3, 4 |
| Q11 | The user asks why a row was booked to an account | Staging shows method, rule ID or neighbours, linked document and version tuple; the entry in the ledger carries the row's proposal ID as `autobook-id` | 4 |
| Q12 | Last night's batch was wrong | `autobook undo` removes exactly the entries the batch created (`autobook-id` is the proposal ID of a row staged as `create` or `create_split` in that batch, and the entry is in the owned file) — also when unrelated entries were added to the owned file afterwards — and its paperless stamps; a matched row changes staging only | 4 |
| Q13 | A new user with a Beancount ledger and no paperless installs it | Full pipeline runs; document features are absent, nothing else degrades | 5 |
| Q14 | The user saves the review file after changing a pre-marked row from `a` to `?` | That row is not written; every row written has the account, amount and date the saved file showed | 1 |
| Q15 | One entry of an approved batch makes the ledger report a new error when it is loaded again | The previous content of the owned file is restored; every ledger file is byte-identical to before the run; nothing is marked applied (exit 6) | 1 |
| Q16 | A row's postings are off by one cent, or by half a cent | Autobook's own exact-sum check refuses the row in both cases, although Beancount would load the half-cent case | 1 |
| Q17 | The ledger already has errors before the run | The batch is still booked; only an error the first load did not report rolls it back | 1, 5 |
| Q18 | The owned file is not included by the main file, or its root-name options differ from the main file's | The run is refused (exit 4); nothing is written | 1 |
| Q19 | A proposal ID that staging holds as applied is no longer in the ledger | `autobook status` and the next run report it; the entry is not created again | 1, 4 |
| Q20 | The same OFX file is handed over twice | The second admission changes nothing: the statement's checksum is already recorded | 1 |

## 11. Risks and technical debt

| Risk | Nature | Mitigation |
|------|--------|------------|
| The kNN premise fails on real history | Sparse or inconsistent bookings make abstention unreliable; the design depends on it | Step 2 tests it before anything else is built; the design changes, not a threshold |
| Silent mis-booking through drift | A bank or a converter plugin change degrades precision while everything "works" | Coverage and LLM-fallback drift detection; version gate with the producer string; balance checks |
| An OFX file that is wrong but consistent | A conversion that drops a line and still states balances that add up, or states no balances, passes admission. Autobook cannot know how the file was produced | The closing-balance check catches a missing line only where a balance is stated; elsewhere only the user's own `balance` assertions do |
| A driver that changes memos | Classification degrades quietly: normalisation and every index assume the memo arrives unmodified | The drift gates and the producer string are the only defence |
| An edit lost under an open editor | If the owned file is open with unsaved changes when Autobook replaces it, the editor decides what happens on save; one that does not warn would overwrite the batch | `autobook status` and the next run report the missing IDs; nothing is re-created silently. What Fava and common editors do is a B0 spike |
| A matched entry edited afterwards | Its content hash changes and the claim is lost; a later line with the same amount in the window could match it. Two payments would then be one entry and the account short by one | The staged row stays `applied`, so nothing is proposed twice; a line that finds more than one candidate is queued; the closing-balance check catches the rest where a balance is stated |
| Tolerance | If the exact-sum check were skipped on some path, Beancount would accept a half-cent error | The check is Autobook's own, on every row before rendering; tested at one cent and at half a cent |
| Conversion decisions | A wrong choice for securities or zero-amount splits in the one-off GnuCash conversion produces a ledger that balances and is wrong. The comparison is exact for units; it does not prove a gain went to the right account | Those rows are listed for review, not sampled; the decisions are recorded in a file the user reviews |
| A plugin that rewrites entries | A user's Beancount plugin can change transactions at load time, so an entry may not read back as written | The batch rolls back: loud, but it blocks booking until resolved |
| Licence | A later Apache-2.0 or GPLv3 dependency would be a violation, not a ledger error (GPL-2.0-or-later once ADR-0005 is accepted) | A check on dependency licences in the gate, not a habit |
| AI-applied paperless tags deciding accounts | A model decides by proxy through a document-keyed rule | Shadow mode per rule; audit-log provenance (proposal 0002 §5.2): the document history names an actor, `System` or none means machine, and a user accepting an AI suggestion is recorded as that user — so such rules are still shadowed |
| A shared pack mis-books the head of the market | One bad entry affects every user | Ambiguity flags (`AMAZON`, `PAYPAL`); signing or pinning; validation against each user's history before enabling |
| Review-file fatigue | A long pre-filled file gets saved unread, which approves rows without the gates | Keep the `?` rows few by design; pre-mark only gated rows, never LLM rows before their precision is measured; show evidence per row; shadow-mode numbers before lowering thresholds |
| Single maintainer | Bus factor of one | Design in-repo, conventions in AGENTS.md, gates mechanical |

### Conscious exclusions (not debt — decisions)

- Securities transactions — structural, not classification (proposal 0005 §1).
- Postings denominated in a currency other than the account's — permanent,
  settled before and restated in proposal 0005 §1; revisiting needs an ADR
  (section 9).
- Statement acquisition from banks or a document store, mail retrieval, and
  conversion to OFX: the driver's. Autobook never imports or runs ofxstatement.
- Deciding when to run, opening the review file in an editor, and notifying the
  user: the driver's.
- Writing anything but transactions: no `open`, `close`, `balance`, `pad`,
  `price`, `commodity`, `plugin` or `include` from code, and nothing outside the
  owned file.
- Scheduled transactions and assistants: Beancount has neither and Autobook
  adds none.
- A second ledger format beside Beancount.
- Collecting or pooling user transactions for any purpose.
- Autobook-side optical character recognition (OCR) or document extraction (proposal 0002 §1).
- `balance` directives written from statement balances — not in v1 (an open
  question in proposal 0005).
- Unattended (headless) booking — **[DEFERRED]** beyond v1, not excluded:
  approval is a save of the review file.

## 12. Glossary

| Term | Meaning |
|------|---------|
| Abstention | Declining to predict because the nearest neighbours are too far or disagree; the row falls through or queues. |
| Admission | Accepting a statement into staging: the OFX file parses, every line has a date, an amount in whole cents and a currency, the account ID is configured, the currency is one the ledger account's `open` directive declares, the balance check passes, the overlap rule is satisfied. All or nothing per statement; recorded as `admitted` or `rejected` with a reason. |
| Approval | Saving the review file. Approves every row marked `a` in the saved file, as shown; nothing else reaches the ledger. |
| `autobook-id` | The metadata key under which a created entry carries its proposal ID. Written on entries Autobook creates and on nothing else. |
| Balance check | At admission, the statement's lines must sum exactly to closing minus opening balance, in cents; where the OFX file states no balances, recorded as not possible. After writing, the ledger's balance on the closing date must equal the stated closing balance minus the statement's lines not yet applied. |
| Batch | The rows processed in one run; the unit of refusal, of roll-back and of undo. Booked whole or not at all. |
| Category | A locale-neutral semantic label (`groceries`) that packs target instead of accounts. |
| CoA | Chart of accounts: the ledger's accounts, as declared by its `open` and `close` directives. Also the name of the reader's contract (`coa`) that lists them. |
| Content hash | The identity of a matched entry, which has no permanent identifier: Beancount's `hash_entry` with `exclude_meta=True`, over date, flag, payee, narration, tags, links and postings, excluding metadata and position. Stable across processes and when the entry moves; changes when the user edits the entry. |
| Corpus | Two-posting transactions used for kNN: `observed` rows from the reader's `corpus` contract, `corrected` rows from staging. |
| Correlation | Pairing the two sides of a transfer between the user's own accounts, within a batch or across batches (`transfers_pending`). |
| Correspondent association | A confirmed pairing of a paperless correspondent with a normalised merchant token, derived from history and kept in the user rules file. Required before a bill can link to a row. |
| Disposition | One of `create`, `create_split`, `match_existing`, `out_of_scope`, `queue`. |
| Document link | The paperless URL of a linked bill. On a created entry it is the metadata `autobook-doc`; for a matched entry it is kept in staging only, because nothing is written to a matched entry. |
| Document-keyed rule | A rule that tests document conditions (paperless correspondent, document type, tag) of a linked bill. `auto: false` by default. |
| Driver | The separate program, in its own repository, that gets statements, converts them to OFX with ofxstatement, decides when to run, calls Autobook's commands, opens the review file in an editor and notifies the user. Not part of Autobook. |
| Entry | A dated directive in the ledger; here almost always a transaction. A created entry is one Autobook wrote; a matched entry is one the user wrote that a statement line resolved to. |
| FITID | A statement's per-transaction ID in OFX. Trusted as the line's identity only where the configuration says the IDs are bank-supplied. |
| kNN | k-nearest-neighbour classification over the user's own history. |
| Ledger | The user's Beancount v3 plain-text ledger: a main file and every file it includes. |
| Ledger package | The only code that imports `beancount`: the reader and the writer. Everything else reaches the ledger through its contracts. |
| Line | One transaction line of a statement. Once staged it is a row. |
| Linkage backtest | Milestone D2: a read-only measurement of how many rows the cascade abstains on would gain a linked bill. A decision point. |
| Overlap rule | A statement whose period overlaps an admitted one is admitted only if every line in the overlap matches a staged line, counting duplicates. |
| Owned file | The one file Autobook may write, named in the configuration, created by `autobook init` and included by the user's main file. Holds transactions only, plus the root-name options in its header. |
| Pack | A versioned, shareable set of pattern → category rules with no personal data. |
| PDCA | Plan-do-check-act; the out-of-tree development harness `autobook-pdca` is named after it. |
| Producer string | An optional text the driver hands over per OFX file, for example the converter plugin's name and version. Recorded with the statement and part of the version tuple. |
| Proposal ID | `AB-` plus a ULID, generated per staged row, distinct from the staging key. Written as `autobook-id` only on entries Autobook creates; only values matching `^AB-[0-9A-HJKMNP-TV-Z]{26}$` count. |
| Provenance | Where a corpus row came from: `observed` (ledger) or `corrected` (review decision). Nothing else can enter the index. |
| Read-back | Loading the ledger again after the owned file was replaced and checking that every created row's proposal ID appears exactly once, with the approved date, accounts and amounts, and that every matched row's recorded entry is still present with its posting in the row's source account. A row is `applied` only after it and the assertions pass. |
| Reader | The half of the ledger package that loads the ledger and emits the `coa`, `corpus` and `existing` contracts. Every assertion goes through it. |
| Residual | Rows that need a human decision: those left at `?` in the review file. |
| Root-name options | Beancount's `name_assets` … `name_expenses` options, which rename the five root accounts. An included file does not inherit them, so the owned file's header repeats them and every run compares them with the main file's. |
| Scenario 1 / 2 | Trial (read-only, backtests, rule building) / production (writes what a saved review file approved, gated). |
| Shadow mode | The classifier proposes while the user decides; produces precision data. The default state until the writer exists, and continuous evidence-gathering after. |
| Source account | A ledger account that statements are booked from, configured per OFX account ID. |
| Stamp | An optional paperless tag and custom field (holding the proposal ID) written to a linked bill for the user's convenience; never read back to decide anything. |
| Staging | The store between classification and writing; audit trail, corpus of corrections, undo list. |
| Statement | One OFX file handed over by the driver: an account ID, a currency, a period, optionally balances, and lines. Admitted whole or not at all. |
| TF-IDF | Term frequency–inverse document frequency: the weighting of the character n-grams the kNN index is built on. |
| Version tuple | Everything that can change a classification, recorded per validated trial and required by production. |
| Writer | The half of the ledger package that changes the owned file: `init`, append by compare-then-atomic-replace, read-back, assertions, restore on failure, undo. |

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

Everything that touches a ledger runs in `nox -s gate`, against synthetic
ledgers the tests build in temporary directories, on every supported Python
version. Beancount is an ordinary dependency; no Docker image is needed for
ledger tests.

| Tier | What | Where |
|------|------|-------|
| Unit and property tests | Normaliser, OFX parser, review-file parser (round-trip, reordering, malformed input), money arithmetic (exact sums), bill matching (order independence) | `nox -s test`, part of the gate |
| Boundary tests | Only the ledger package imports `beancount`; nothing imports `ofxstatement` or `gnucash`; the model adapter cannot receive a raw memo or an account name, and a remote backend receives only allowlisted tokens; no float on monetary paths; runtime dependencies carry a licence compatible with GPLv2 | Lint and tests in the gate |
| Ledger-package tests | Reader contracts (`coa`, `corpus`, `existing`), content-hash stability, the root-name options check, `init`, create, split, `match_existing` (nothing written to the entry), compare-then-replace, read-back, restore on a failed read-back or assertion, idempotent re-run after a crash at each point, undo (ID and owned file both checked), `autobook-doc` on created entries | `nox -s gate`, synthetic ledgers in temporary directories; never a real ledger |
| Admission tests | Each rejection reason rejects the whole statement and stages nothing; the same file twice changes nothing | `nox -s gate`, synthetic OFX files |
| Live-paperless tests | Bill matching against a seeded paperless-ngx | `nox -s live`, in the Docker test environment (`testenv/`); not part of the gate |
| Conversion, export half | The one-off GnuCash conversion's export through `python3-gnucash` | `nox -s applier`, in the test environment's GnuCash image, which stays only for this and is removed with it |
| Backtest | Rolling-origin over a real corpus, stratified seen/novel; leave-one-out only as an upper bound | Local, read-only; results reported, data never committed |
| Shadow mode | Parallel proposals, continuous until the evidence suffices | The reference deployment |

A real ledger, or a copy of one, is opened only by a human, attended; unattended
runs touch only ledgers the tests build.

### 13.3 Test data

Fixtures are synthetic or derived from published format documentation. No
transaction from a real statement, even normalised, is ever committed —
normalised memos still carry names, IBANs and creditor IDs (CONTRIBUTING.md).

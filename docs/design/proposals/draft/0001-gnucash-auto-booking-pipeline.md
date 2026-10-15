---
created: 26.07.2026 00:00
type: proposal
status: draft
author: Eduard Ralph
tracking-issue:
tags:
  - proposal
  - gnucash
  - design
---

# GnuCash Auto-Booking Pipeline

> **Proposal 0001 — the whole system design.** Still `draft`: it becomes
> `accepted` when build order step 2 (corpus export, k-nearest-neighbours (kNN), backtest harness) has
> reported, because that step tests this document's central premise. See the
> [proposals index](../README.md) for why that ordering is deliberate.
>
> **Amended by [proposal 0002](0002-document-driven-booking-via-paperless.md)** —
> for the rows in its *Changes to proposal 0001* table, 0002 governs. 0002 is
> accepted separately: its trigger is the report of its linkage backtest (D2),
> just as this document's trigger is step 2's report.
>
> The order in which the steps are *executed* is set in
> [architecture chapter 9](../../architecture/09-build-order-and-roadmap.md);
> the *Build order* section below describes what each step contains.
>
> The hard rules this design implies for anyone writing code are restated as
> enforceable conventions in [`AGENTS.md`](../../../../AGENTS.md).

## Goal

Automate destination-account assignment for imported bank transactions so that
booking takes one save of a pre-filled review file, not per-transaction
interaction with GnuCash's import UI.

Target outcome: ~90–95% of transaction count proposed with enough confidence to
be pre-marked `a` (accept) in the review file; the residual reviewed in a
purpose-built interface, not GnuCash's matcher. **Approval is saving the review
file** (see *Review interface*): nothing reaches the book that was not marked `a`
in the saved file. Unattended runs with no editor are **[DEFERRED]** beyond v1.

The residual is not a modelling failure — it is genuinely ambiguous data (was
that Amazon order household or a gift?) that a bank statement does not contain
the information to resolve.

Secondary goal: distributable to other GnuCash users.

## Out of scope

Two genuine permanent exclusions, settled here. [ADR-0001](../../adr/0001-record-architecture-decisions.md)
names them as an example of a decision that must be recorded, not re-argued.
Revisiting either needs an ADR (both are listed as candidates in the ADR index), not a
proposal or a threshold change. Both
share a technical root: a GnuCash split
carries **value** (in the transaction currency) and **amount/quantity** (in the
split account's commodity). For ordinary transactions these are equal — hence
`SetValue(x); SetAmount(x)` in the applier. Both exclusions below break that
equality, and with it the pipeline's two-split / one-destination-account
representation.

### Securities transactions

Beyond value ≠ amount:

- **Commodity resolution.** Must exist in the book with correct namespace and
  ISIN/symbol. Auto-creating them is the account-creation problem, worse — price
  lookups depend on the namespace being right.
- **Lots.** Sales need lot assignment for capital-gains tracking; German taxation
  is FIFO, and misassignment silently misreports gains.
- **Embedded fees.** A broker buy is cash out = share value + order fee +
  Fremdkostenpauschale. Multi-split, not reliably derivable from the statement line.
- **Events with no cash flow.** Vorabpauschale is taxable with no bank line to
  import. Teilfreistellung and withheld KESt/Soli/Kirchensteuer sit outside
  anything the pipeline sees.

**Decisive argument:** there is no classification problem here. "Kauf 10 Stk
ISIN X" has no destination-account ambiguity — the work is structural, not
categorical. Excluding securities costs approximately none of the tool's value
while removing most of its complexity.

Revisiting would mean a separate subsystem (commodity resolution, lot policy, fee
decomposition), not a threshold change — and a new ADR first.

### Splits denominated in a currency other than the account's

Narrower than "FX" or "Revolut". Three cases, only two excluded:

| Case | Status |
|---|---|
| Foreign-currency spending debited in the book currency ($30 → €28.15) | **In scope.** FX happened at the bank; an ordinary EUR two-split arrives. Probably most Revolut volume. |
| Account denominated in a non-book currency (USD balance spent against EUR expense accounts) | Out. Needs rate handling. |
| Conversion between the user's own currency accounts (EUR→USD in Revolut) | Out — though it is a transfer, so the correlation pass already owns half of it. |

The original justification cited known GnuCash CSV importer problems with
multi-currency. **That evidence is void** — the CSV path was dropped. The
remaining reason is value ≠ amount plus the need for a rate source.

If a new ADR ever reopens it, it is more tractable than securities: same
two-split shape plus a rate, and GnuCash already has a price database to write
into.

### Handling out-of-scope rows

These still arrive through ofxstatement. They need explicit detection and an
`out_of_scope` disposition:

- Excluded from the review queue — otherwise every Scalable statement leaves a
  permanent residue of proposals that look like work and never resolve.
- **Excluded from coverage and drift metrics.** Otherwise the drift detector sees
  permanently low rules + k-nearest-neighbour (kNN) coverage and either misfires constantly or gets its
  threshold lowered until it stops catching real drift.
- Still recorded, so the user can see what was skipped.

## Not scope decisions

Two things previously listed here belong elsewhere:

- **Reconciliation, chart-of-accounts (CoA) creation, recurring bookings, loan amortisation** —
  deferred to GnuCash's own features, see *Design principle* below. (Never set the
  reconciled flag from code; reconciliation is the independent check on everything
  the pipeline does.)
- **Unknowable splits** — a data limitation, not a scope choice. Splitting a
  supermarket charge needs line-item receipt data the statement lacks.
  *Determinable* splits are in scope, see *Splits and match-to-existing*.

---

## Design principle: defer to GnuCash

Scope is **destination-account assignment for irregular transactions.** Everything
structural stays in GnuCash. Where GnuCash ships an assistant or feature that does
the job better, the tool detects the need and hands off — it does not reimplement.

Already deferred on this basis: reconciliation, chart-of-accounts creation
(New Account Hierarchy Assistant), recurring bookings (Scheduled Transactions),
loan amortisation (Mortgage & Loan Repayment Assistant).

This principle settles future scope questions by default: if GnuCash already does
it, guide the user to it and verify the result.

---

## Architecture

Two processes, JSON contract between them. Python throughout. Linux-first. GPL
(consequence of linking libgnucash).

```
┌─ BOOK PROCESS · exporter ────────────────────────────────┐
│  links libgnucash · SESSION_READ_ONLY · no writes        │
│  out: corpus, CoA, existing transactions, SX definitions │
└──────────────────────┬───────────────────────────────────┘
                       │  JSON: book state out
                       ▼
┌─ PIPELINE ───────────────────────────────────────────────┐
│  no libgnucash · no lock · runs anywhere                 │
│                                                          │
│  ofxstatement → normalise → dedup (FITID)                │
│    → correlate (transfers, SX, match_existing)           │
│    → classify → stage → review                           │
└──────────────────────┬───────────────────────────────────┘
                       │  JSON: rows approved in the saved review file
                       ▼
┌─ BOOK PROCESS · applier ─────────────────────────────────┐
│  links libgnucash · needs the book lock · few hundred LOC│
│                                                          │
│  approved rows → transactions → save → assert → read-back│
│  out: {proposal_id, tx_guid, status}                     │
└──────────────────────────────────────────────────────────┘
```

Correlation runs **before** classification: a row that is the second side of a
transfer or falls on a scheduled-transaction (SX) occurrence must never reach the
classifier (see *Correlation pass* and *Splits and match-to-existing*).

**The book process** is the only process that links libgnucash. It has two
parts: the **exporter**, read-only (`SESSION_READ_ONLY`), used from build step 2
for the corpus, the CoA, existing transactions and scheduled-transaction
definitions; and the **applier**, which writes, from build step 5. The ban on
importing `gnucash` applies to the **pipeline**; it is lifted for the whole book
process. The nox session and the pytest marker keep the name `applier`, and they
cover all book-process tests, exporter included.

**Why the boundary matters:**

- Pipeline is testable with no GnuCash installed and no book present.
- Solves the Linux venv problem (`python3-gnucash` lives in `dist-packages`;
  subprocess invocation sidesteps `--system-site-packages` entirely).
- Makes a future Windows port a component swap rather than a redesign.
- Language of the book process becomes a local decision, not a global one.

### Staging store

SQLite by default (`$XDG_DATA_HOME`), Postgres URI as a config option.
Postgres is fine personally but is a hard dependency for other users.

```
proposals(
  source_account, fitid_or_key,                -- PK (source_account, fitid_or_key)
  proposal_id,                                 -- AB- + ULID, see Idempotency
  post_date, amount, currency,
  raw_memo, normalised_memo,
  disposition,                                 -- create|create_split|match_existing|out_of_scope|queue
  queue_reason,                                -- why a row is queued, e.g. "awaiting scheduled transaction", "pending transfer"
  proposed_account, confidence, method,        -- rule | knn | llm
  rule_id,                                     -- the rule that fired, when method = rule
  status,                                      -- pending|approved|rejected|applied
  applied_tx_guid, human_correction,
  classifier_version, normaliser_version, ts
)

transfers_pending(
  counterpart_account, amount,                 -- integer cents
  window_start, window_end,                    -- date window for the second side
  proposal_id, tx_guid                         -- the first side; tx_guid once applied
)
```

`fitid_or_key` is the bank's FITID (financial institution transaction ID) only
when the ofxstatement plugin declares its `id` field bank-supplied. Synthesised
IDs (ofxstatement hashes date + memo + amount, so two identical card payments on
one day collide) are not FITIDs: those rows take the `(source_account, checksum,
ordinal)` key and the overlap rule from proposal 0002 §3.4. File ingest records
a `statements` row with the file's checksum, exactly as paperless ingest does
(0002 §7).

The staging key and the **proposal ID** are different things: the key
identifies the statement line; the proposal ID is generated once per staged row
and is what goes into a created transaction's `num`.

The staging table is the seam. It decouples classification from write mechanics,
provides the audit trail, the correction corpus, and the rollback list.

---

## Classification cascade

**rules → kNN → LLM** (large language model). In that order. Rationale is determinism and
auditability, *not* token cost — at a few hundred transactions/month an
all-LLM approach would cost cents. A rule that fires is explainable and
identical every run; a model call is not.

### 1. Rules

Versioned file, git-tracked, hand-owned. Model may *propose*; the human commits.
That commit is where determinism comes from.

Rule types (the full precedence table — creditor ID, document-keyed, ambiguity
flag, memo pattern, then kNN and LLM — is in
[proposal 0002 §5.1](0002-document-driven-booking-via-paperless.md#51-document-keyed-rule-conditions)
and governs everywhere):

1. **Exact identifier match** — SEPA Gläubiger-ID (creditor ID). Stable across
   memo reformatting, unique per company, exact. Covers most recurring German
   debits (insurance, utilities, telco, subscriptions) with certainty rather than
   probability. Also cleanly shareable: creditor IDs are registered business
   identifiers, so they carry no personal data.
2. **Pattern match** — memo regex.

Counterparty IBANs are the opposite case: may belong to individuals. Local only,
never in a shared pack.

**Split templates.** A rule may target a split specification rather than a single
account, for genuinely fixed-ratio cases:

```yaml
- id: versicherung-bundle
  match: {creditor_id: DE98ZZZ09999999999}
  splits:
    - {account: "Ausgaben:Versicherung:Haftpflicht", type: fixed, cents: 1250}
    - {account: "Ausgaben:Versicherung:Hausrat",     type: remainder}
```

Fixed amounts are **integer cents** (`cents: 1250`), never a decimal like
`12.50`: YAML reads that as a float, and the bindings would accept it through the
`GncNumeric(float)` constructor (see *Write path*).

Computed splits must sum **exactly** to the transaction total. Mismatch fails the
row loudly — never dump the difference into Imbalance.

> **Constraint: splits are rules-tier only.** kNN and the LLM may only ever return
> a single destination account. The corpus stays two-split-only (multi-split
> transactions are ambiguous labels), and a model guessing at split ratios inside
> a ledger is precisely the confident-wrongness the abstention design exists to
> prevent.

Rules are data, not code — YAML/TOML with id, priority, created-by (`llm`/`user`),
`auto`, and backtest score at acceptance time. `priority` orders rules **within**
a precedence tier only; it never lifts a rule into a higher tier. `auto` says
whether the rule's proposals may be pre-marked `a`: default `true`, except
document-keyed rules, which default to `false` (0002 §5.2). The rule builder
reports conflicts — two rules matching the same historical transaction with
different targets — between any two tiers, not only within one.

### 2. kNN

Not a service or a pretrained model. An index built from the user's own book at
runtime, in-process, CPU only, no network, no model download.

**Corpus:** two-split transactions where one split is in the source account →
`(normalised_memo, amount, sign, source_account) → destination_account`.
Skip multi-split transactions; ambiguous as labels, rare enough not to matter.
~30–60k rows for a decade of personal finance.

**Representation:** character n-gram TF-IDF (term frequency–inverse document
frequency; `char_wb`, 3–5).
Bank memos are not natural language — merchant tokens with noise, truncation,
inconsistent casing, German compounds. Char n-grams absorb that; word
tokenisation shatters on it.

```python
vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
X   = vec.fit_transform(corpus_memos)
nn  = NearestNeighbors(n_neighbors=15, metric="cosine").fit(X)
```

Sparse cosine over 50k vectors is sub-millisecond. **No FAISS, no vector DB.**
Rebuild the whole index each run — cheaper than any incremental scheme.

**Partitioning:** separate index per `(source_account, sign)`. The same token
means different things in different accounts; a credit must not match an
expense-account neighbour. Mirrors what GnuCash's own Bayes matcher does, and
is correct for the same reason.

Amount stays out of the distance metric — tie-breaker only.

**Two independent gates** before accepting a prediction:

- **Nearest-neighbour distance** under cutoff. A unanimous vote among distant
  neighbours is a sparse region of the space, not confidence. This gate is what
  stops confident errors on unseen merchants.
- **Vote margin** — winner's weighted share vs runner-up.

Fail either → fall through to LLM. Report both numbers in the review file.

**Recency weighting:** exponential decay, ~18-month half-life. People restructure
charts of accounts; a decision from four years ago should not outvote current
practice.

**Provenance tagging is structural, not disciplinary.** Every corpus row is
`observed` (from the book) or `corrected` (from review decisions — both are real
human decisions). Index construction filters on provenance. Synthetic rows cannot
enter. See *Open questions*.

**Cold start:** a new user contributes nothing here on day one. Not an issue for
an existing GnuCash user with years of history — which is most adopters.

### 3. LLM (tail only)

- Constrained label space: pass the account list, validate output against it,
  reject anything not in the tree. The check also rejects placeholder accounts
  and accounts of type Equity or Trading.
- Steering document: versioned, version logged per proposal. Do **not** put the
  account list in it — generate from the live CoA at runtime or it silently
  drifts out of sync with the book.
- Temperature pinned to 0. The model ID is recorded (it is in the version
  tuple).
- **An LLM proposal is always `?`** — never pre-marked `a` — until shadow mode
  has measured per-method precision for `method=llm`. Only then may a threshold
  pre-mark LLM rows.
- What a backend receives, and the default to a local one, is in *Model
  backend*.
- Also drafts rule candidates for review (see Scenario 1).

### Why kNN over GnuCash's Bayes matcher

Both learn memo→account associations and partition per source account. Differences:

| | GnuCash Bayes | This |
|---|---|---|
| State | KVP (key–value pair) slots in the book | Derived, rebuilt each run |
| Learns from | Imports only | Every booked transaction, incl. decades of hand entry |
| Recency | Monotonic counts; early errors vote forever | Decayed out |
| Explainability | Token-weight product | Actual neighbours: "45 times, most recently 3 weeks ago" |
| Abstention | Always returns a best guess | Distance = genuine "never seen this" |

Abstention is the real reason, not accuracy. In a system that pre-marks rows for
approval in one save, knowing when to abstain matters more than being right more often.

**Baseline worth running:** reimplement token-Bayes over the corpus (~30 lines)
as a negative control in the backtest. If kNN does not beat it by a clear margin
on real data, that is a useful result.

---

## Normalisation

Quality depends far more on memo preprocessing than on k or the metric.

Strip SEPA boilerplate (`EREF+`, `MREF+`, `CRED+`, `SVWZ+`, `ABWA+`), embedded
dates, card fragments, trailing sequence numbers. What survives is the merchant
token.

**Lives in the pipeline, not in the ofxstatement plugins.** Plugins convert
formats and preserve the raw memo. Otherwise normalisation cannot be changed and
re-backtested without touching four plugins — and it is the thing that gets tuned
most.

**Profiles are per source account, not per user.** Consorsbank is SEPA, Revolut is
multi-currency and partly not, PayPal has its own format. One user needs several
simultaneously.

Profiles load from a **user directory**, not only the installed package —
otherwise every new country needs a release and the maintainer becomes the
bottleneck on exactly the contributions most wanted. Same shape as ofxstatement
plugins.

Normaliser version belongs in the gate tuple: changing it changes what every
vector means.

---

## Correlation pass

**Not optional.** With Consorsbank, Revolut, Scalable and PayPal all feeding in,
every inter-account transfer appears in two statements. Import both sides and you
double-book; balances drift.

- Detect counterpart pairs across accounts, emit the transfer from one canonical
  side only.
- Runs **before** classification. Every transfer row first goes through a
  `match_existing` search in its own source account. The second side of a
  transfer whose first side was booked in an earlier batch resolves to the
  transaction that first side created — it has splits in both accounts — and is
  never booked again.
- A transfer's first side records a `transfers_pending` entry (counterpart
  account, amount, date window, its proposal ID and, once applied, its
  transaction GUID). An unmatched second side whose counterpart is pending is
  queued with reason "pending transfer" — never classified.
- **PayPal** is set by `paypal_mode`, default `"account"`:
  - `account`: PayPal is its own GnuCash account and its statement is imported.
    Bank lines to PayPal are **transfers**, resolved here, not expenses.
    Classifying them as expenses double-counts.
  - `pass_through`: PayPal statements are never imported. The bank line is
    classified by the merchant parsed from its memo (`PAYPAL .VENDORX` →
    `VENDORX`).

The staging table is the only component with a cross-account view, which is why
this lives there.

---

## Splits and match-to-existing

### Amortising loans belong in Scheduled Transactions, not in rules

A mortgage payment's interest/principal ratio changes every period. If the
pipeline held an amortisation schedule there would be **two sources of truth for
the loan**, and they would drift.

GnuCash's Mortgage & Loan Repayment Assistant already builds a scheduled
transaction (SX) with formulas that recompute per period. That is the correct home —
and it is already step 1 of the build order.

### Consequence: the applier needs a match path

If a scheduled transaction has already created the booking, the imported bank row
is **not** a new transaction — it is a match to an existing one. An applier that
only ever creates will double-book every mortgage payment: once by the SX, once by
the pipeline. Same failure as the transfer correlation problem, different cause.

Per-row disposition therefore has five outcomes:

```
create | create_split | match_existing | out_of_scope | queue
```

**`match_existing`:** search the row's **source** account — not the target
account; an SX transaction is often multi-split — for a transaction within a
tight window (±5 days — not GnuCash's generous ±42) with the same amount.
Candidates are transactions **not already claimed by Autobook** (created by it,
or recorded in staging as a match). Reconciliation state is not a filter: a user
who reconciles promptly would otherwise never get a match.

- Found, unambiguous → do not create. Record `applied_tx_guid` in staging and
  mark applied once a read-back confirms it. Autobook writes **nothing** to the
  matched transaction — no `num`, no FITID or `online_id` stamp. The one
  exception is a document link (proposal 0002 §6.1), and never over an existing
  one.
- Ambiguous or absent → queue. Never guess.

**Scheduled transactions are created after the launcher's apply.** GnuCash
creates SX instances in its Since-Last-Run step at GUI start-up, which comes
after Autobook has run. So the exporter also exports **SX definitions**
(template accounts, amounts, recurrence) in the `existing` contract. A statement
row in a source account whose amount and date (± the match window) fall on an SX
occurrence is **never `create`**: it is `match_existing` if the instance already
exists, otherwise `queue` with reason "awaiting scheduled transaction". It
resolves on a later run, after GnuCash has created the instance.

Generalises beyond mortgages: any other scheduled transaction, and anything the
user entered by hand before importing.

---

## Two scenarios

### Scenario 1 — trial / rule building

Never writes to the book. Read-only corpus export through the exporter, cached;
replayable any time, on any machine, with the desktop app open.
`SESSION_READ_ONLY` ignores the lock, so an export of an XML book while GnuCash
is open reads the last **saved** state, not unsaved edits in the GUI.

**Method is backtesting, not AI supervision.** Ground truth already exists in
years of hand-booked history. Calibration is **rolling-origin**: for each month
*m*, the index holds only rows before *m* and the test set is month *m*. This
yields per-method, per-cluster precision with no model in the loop, and it never
lets a row's own future vote for it. Results are reported in two strata — memo
seen before in the index, and novel — and the gate thresholds are set on the
**novel** stratum, because that is where confident errors happen. Leave-one-out
remains only as an upper bound and for the rule builder's quick "matches N
historical rows" verdict. Batched sparse matmul — seconds to a minute, cheap
enough to run routinely.

The LLM's role here is narrow and honest: characterising *why* a cohort fails,
and drafting candidate rules for review.

**GTK4 rule builder — the core panel:**

1. Cluster unmatched / low-confidence rows.
2. LLM proposes pattern + target for a cluster.
3. **Immediately backtest against history and show the verdict:** "matches 47
   historical transactions — 45 booked to `Expenses:Lebensmittel`, 2 to
   `Expenses:Haushalt`", with the 2 listed and clickable.
4. Accept / edit pattern (preview re-runs live) / reject.

This panel is the entire justification for building a GUI. It turns rule
acceptance from judgement into measurement, and makes the LLM structurally safe:
it can only propose things already scored against reality.

Build this before anything else in the UI. The rest is chrome.

**Assistant detection and handoff.** Cheap, since the corpus already exists.
Present as a coverage report *before* classification — "of 847 transactions, 312
are recurring and schedulable" — which turns build-order step 1 from advice into a
feature the tool performs.

| Detected | Hand off to |
|---|---|
| Recurring fixed-amount debit, no matching SX | Scheduled Transactions (pre-compute amount, interval, next date, counterparty) |
| Loan-shaped payment: stable recurring amount + existing liability account, especially booked entirely to one account | Mortgage & Loan Repayment Assistant |
| Thin or absent CoA | New Account Hierarchy Assistant |

**Verify the handoff.** After the user runs the assistant, re-scan and report
against the corpus: *"Scheduled transaction detected. Your last 12 mortgage
payments would now resolve as `match_existing` rather than being booked as
expenses."* Direct reuse of the backtest machinery, and the part no one else can
offer.

**Do not create scheduled transactions programmatically** (v1). A wrong frequency
or formula generates phantom transactions indefinitely, and for loans it
reproduces the amortisation logic — two sources of truth again. Guide, verify,
don't create. Simple fixed-amount SX creation is a reasonable later addition once
the guidance path is proven.

Name assistants and deep-link to the **versioned** online manual rather than
hardcoding menu paths — those move between versions and platforms, and a wrong
path is worse than none.

**Restraint:** threshold suggestions (6+ occurrences, stable amount, material
share of volume) and make each dismissible with the dismissal persisted. Some
users deliberately avoid scheduled transactions. A tool that nags about every
subscription gets its suggestions ignored wholesale — including the one that
mattered.

### Scenario 2 — production

Deterministic. Headless runs (no editor, no one to save the review file) are
**[DEFERRED]** beyond v1. In v1 "apply" means *apply what the saved review file
approved*: rows marked `a` in the saved file, with the account, amount and date
shown there. Two failure tiers:

**Per-row → queue it, batch proceeds.** Do not hold 58 confident bookings
hostage to 2 ambiguous ones. Per-row idempotency makes partial commits safe.
Triggers: confidence under threshold; no rule and kNN distance above cutoff;
proposed account absent from live CoA; amount/currency mismatching source; the
row falls on an SX occurrence whose instance does not exist yet; the row is the
second side of a pending transfer.

**Batch-level → write nothing (or undo).** Every trigger below except the last is checked
before the book is opened for writing. The post-apply assertions run after
`session.save()` (see *Write path*), so when one fails the batch is already in
the book: it is flagged and notified, and undo reverses it.
- Coverage drop (rules+kNN share below rolling baseline)
- LLM fallback rate spike — usually a changed bank memo format or a broken plugin
- Unusual share of proposals pointing at rarely-used accounts
- Parse errors above a small count
- Post-apply assertions failing

The first two are drift detection: they catch the failure where everything still
"works" and precision quietly degrades.

**Version gate.** Record per successful trial run: rule-file hash, prompt version,
model ID, kNN index version, normaliser version, ofxstatement plugin versions,
user's model config. Scenario 2 refuses to run if the current tuple differs from
the last validated one. Makes "go back to scenario 1" explicit rather than a
matter of discipline — and catches the silent case where a plugin update changes
normalisation and invalidates the index without any classifier code changing.

**A refusal must never block opening GnuCash.** Notify loudly, then open the app
anyway. Proposals stay pending; book by hand if needed. Books are not hostage to
a classifier that lost confidence in itself.

---

## Write path

```python
session = Session(book_uri, SessionOpenMode.SESSION_NORMAL_OPEN)
try:
    book = session.book
    for row in approved_create_rows:
        cur = row.src.GetCommodity()       # the source account's currency, never hard-coded
        # same commodity in both accounts, fraction 100 — else the row queues
        check_commodity(cur, row.dst.GetCommodity())
        tx = Transaction(book)
        tx.BeginEdit()
        tx.SetCurrency(cur)
        tx.SetDate(d, m, y)
        tx.SetDescription(desc)
        tx.SetNum(row.proposal_id)          # AB-<ULID>, only on transactions Autobook creates
        for acct, cents in ((row.src, row.cents), (row.dst, -row.cents)):
            s = Split(book)
            s.SetParent(tx)
            s.SetAccount(acct)
            s.SetValue(GncNumeric(cents, 100))
            s.SetAmount(GncNumeric(cents, 100))
        tx.CommitEdit()
    session.save()                          # XML: nothing persists before this
    run_post_apply_assertions(book)
finally:
    session.end()                           # releases the lock; does NOT save
read_back(approved_rows)                    # only now is a row reported applied
```

- Every mutation needs `BeginEdit` / `CommitEdit`.
- **`session.save()` after the last `CommitEdit`**, then the post-apply
  assertions, then `session.end()` in the `finally`. `end()` does not save
  (qofsession.h: `qof_session_end` "will not save the data to a file"; the
  Python `Session` docstring notes this is "always the case with the file
  backend"). Per backend: **XML** — nothing persists until `save()`, so a batch
  is all-or-nothing; **SQL** — each `CommitEdit` is durable, and `save()` is a
  harmless no-op.
- **Read-back before reporting.** A row is reported applied — in `apply-out` and
  as `applied` in staging — only after a read-back finds it. XML: reopen with
  `SESSION_READ_ONLY` and find its ID; SQL: an engine query for its ID.
- Amounts are `GncNumeric` rationals built from **integer cents**. Never floats.
  The bindings expose no `from_double`, but the `GncNumeric(float)` constructor
  accepts a float — do not let one reach it.
- **Currency from the source account.** Take the source account's commodity,
  verify both accounts share it and that its fraction is 100, and only then build
  `GncNumeric(cents, 100)`. No hard-coded EUR.
- `SESSION_NORMAL_OPEN` only. **Never `SESSION_BREAK_LOCK`** — that is how you
  corrupt a book by writing under a live GUI session. `SESSION_READ_ONLY` for
  the exporter, dry-run and inspection.
- `SessionOpenMode` replaces the deprecated `ignore_lock`/`is_new`/`force_new`
  booleans. Pre-5.x examples will use the old form.
- `session.end()` in a `finally`, unconditionally. A crashed applier that skips it
  leaves a stale lock.
- One session per run, not per transaction. Session open loads the book; pay it once.

### Idempotency

Two systems (book + staging), no distributed transaction. Crash between "committed
to book" and "marked applied" leaves unknown state.

Fix: proposal ID in the transaction's `num` field. The **proposal ID** is `AB-`
followed by a ULID (fits GnuCash's `num`), generated once per staged row and
stored in staging. It is distinct from the staging key. Only values matching
`^AB-[0-9A-HJKMNP-TV-Z]{26}$` count as Autobook IDs; anything else in `num` is
the user's and is ignored.

- **`num` is written only on transactions Autobook creates.** On a
  `match_existing` row Autobook never writes `num` and writes no FITID or
  `online_id` stamp; staging records `applied_tx_guid` instead.
- **Re-run.** Before each batch, find created rows by `num` and matched rows by
  their staging GUID (verified in the book); drop those already present, then
  apply. Makes the applier safely re-runnable after any failure mode.
- **Undo** — "undo last night" — deletes only transactions whose GUID is in
  staging with disposition `create` **and** whose `num` equals that row's
  proposal ID; both are asserted before each delete. Undo for a matched row
  removes only the document link Autobook added (proposal 0002 §6.1), never the
  transaction.

### Locking

Desktop GnuCash holds the lock for its entire session and has no reload-from-DB
command — anything written while it is open is invisible to it. **The applier runs
only when GnuCash is closed.**

Sequence rather than schedule. Wrap the launcher:

```bash
#!/bin/bash
# Deliberately no `set -e`: each step ends in `|| notify`, and the launcher
# always reaches `exec gnucash`.
review="${XDG_RUNTIME_DIR:-/run/user/$UID}/autobook/review.txt"

book_steps() {
    trap 'rm -f "$review"' EXIT              # the review file never outlives the run
    backup-book      || { notify "backup failed, nothing booked"; return; }
    autobook export  || { notify "read-only export failed"; return; }   # exporter, SESSION_READ_ONLY
    autobook propose || { notify "proposal run failed"; return; }
    autobook pending || return                                           # nothing to review
    (umask 077 && mkdir -p "${review%/*}" && autobook review-file > "$review") \
                     || { notify "review file failed"; return; }
    "$EDITOR" "$review" || { notify "editor failed, nothing booked"; return; }   # saving = approving every row marked `a`
    autobook apply --from "$review" || notify "booking failed"          # save, assert, read-back
}

( book_steps )      # in a subshell: nothing in it can skip the next line
exec gnucash "$@"
```

The review file lives at `$XDG_RUNTIME_DIR/autobook/review.txt`, mode 0600, and
is removed when the steps finish, however they finish. It holds counterparty
names; it does not belong in `/tmp`.

The applier cannot race the GUI because it exits before the GUI starts. No lock
polling, no deferral logic. **[DEFERRED]** beyond v1 — unattended runs: attempt
`SESSION_NORMAL_OPEN`, treat `ERR_BACKEND_LOCKED` (the `QofBackendError` value in
qofbackend.h) as deferred-exit-0, escalate after several consecutive deferrals.

### Assertions (post-apply)

Through the **engine API, not SQL** — SQL assertions do not exist for XML-backend
users. For each source account that has a statement in the batch:

1. **The batch moved the balance by exactly what it applied:** Δbalance caused
   by the batch == Σ(amounts of the rows applied).
2. **When the statement has a closing balance:** balance(source, closing date) ==
   closing balance − Σ(lines of that statement not yet applied — queued,
   `out_of_scope`, awaiting a scheduled transaction, pending transfer).
3. **The Imbalance account is unchanged** by the batch. (Not "zero": an existing
   Imbalance balance is the user's business, not this batch's.)

Non-zero exit → ntfy, batch flagged for review.

### Backups

Copy the file where the backend is a file. For a PostgreSQL book, the launcher
runs `pg_dump` when it is on `PATH`, with the database credentials taken from
the Secret Service; otherwise it warns (does not block). The real safety net is
that every batch is reversible through the `num` key and staging (see
*Idempotency*) — targeted, and better than a backup.

---

## Review interface

Plain text file in `$EDITOR`, `git rebase -i` idiom:

```
# id      st  date        amount    account                    description
#   knn: Lebensmittel .81 | Haushalt .07
a1f3e9    a   2026-07-14   -42,90   Expenses:Lebensmittel      REWE SAGT DANKE
9de441    ?   2026-07-16   -18,50   Expenses:Freizeit          PAYPAL .VENDORX
```

(IDs shortened for the example. The PayPal row shows `paypal_mode =
"pass_through"`; in the default `account` mode that bank line is a transfer to
the PayPal account, resolved by the correlation pass, and never appears here
with an expense account.)

Status: `a` accept, `?` needs decision, `s` skip, `x` reject (records negative
example). Change an account by typing over it.

**Saving the file is the approval.** The pipeline pre-marks `a` on rows that
passed the gates, and `?` on everything else. Saving the file approves every row
marked `a` in the saved file, with exactly the account, amount and date shown.
Nothing reaches the book that was not marked `a` in the saved file. Until the
applier exists (build step 5), saving records the decisions to staging only.

Why this over a custom UI: twenty years of editor muscle memory. Multi-cursor for
eight PayPal rows, `:%s/` when the classifier drifted, yank an account name from
three rows up, visual block select to accept a run. None of that exists in a
custom UI unless built, and it would be built worse. ~150 lines total.

- **Parse by ID, never by position.** Reordering, deleting, or sorting must not
  misalign. Unknown ID is an error, not a guess.
- **Strict parser, fail loudly.** Unknown status char, unparseable account,
  amount mismatch → abort the whole batch with a line number, apply nothing.
  Accounts validated against the live CoA at parse time so a typo stops the run
  instead of creating an Imbalance row.

Corrections fall out free: the diff between proposed and saved *is* the training
signal. Log both columns per row.

Escalate to a TUI (Textual) only if repeatedly wanting full memo / merchant
history / running balance before deciding. By then the required fields are known.

---

## Distribution

### Category indirection — the piece that makes shipping possible

A rule targeting `Expenses:Lebensmittel` is useless to anyone whose CoA is not
German and structured identically. Three layers:

1. **Bundled packs** map memo patterns → **semantic category** (`groceries`,
   `insurance`, `fuel`, `sepa_transfer`). Read-only, versioned, locale-scoped
   (`de-DE`, `en-US`), no account names anywhere. Category vocabulary is
   locale-neutral and shared; packs differ only in which patterns point where.
   A locale pack is pure data, no code.
2. **User's category → account mapping**, built once against their live CoA.
3. **User rules** may target accounts directly. Separate file. Never merged into
   the bundled set, never written back.

This also solves the privacy separation structurally: the file containing merchant
names from someone's statements is physically distinct from the file that ships.
Treat user rules as personal data; export is an explicit reviewed action.

### Onboarding: derive the mapping, don't ask for it

Most adopters are **not cold** — they have years of GnuCash history. Lead with
corpus extraction, not packs.

The mapping step (30-odd categories → their accounts) is where people give up.
Compute it instead: load the `de-DE` pack, match its patterns against their
history, look at where those transactions were actually booked.

```
groceries → Ausgaben:Lebensmittel   247 matches, 98% agreement  ✓
insurance → Ausgaben:Versicherungen  34 matches, 100%           ✓
fuel      → no matches                                          needs mapping
```

30 confirmations instead of 30 dropdown searches, derived from their own
behaviour, no LLM needed. **This is what makes packs worth having** — the pack is
a bridge between shared vocabulary and their private account tree, not primarily a
rule source.

Many-to-one is legal and normal: if someone never split out petrol,
`fuel → Ausgaben:Auto` is correct, not a compromise.

**Never auto-create accounts.** A CoA encodes how someone thinks about their
money and may map to tax categories a Steuerberater specified. Auto-created
accounts carry type, parent, placeholder flag, commodity — an expense account
typed as an asset does not error, it silently misreports forever, and removing
accounts with transactions is unpleasant. For a genuinely empty book, point at
GnuCash's own New Account Hierarchy assistant (it ships localized hierarchies)
and map to whatever they choose.

### Community contribution — filter-list model

Contribute **reviewed rules, never transactions.**

Normalised memos routinely still carry counterparty names, IBANs, creditor IDs,
employer names — and Art. 9 special-category data (medical providers, church tax,
union dues, party donations, lawyers, debt collection). Normalisation strips some
and cannot guarantee all. Collecting these makes the project a controller
processing special-category personal data, for a modest benefit. **Do not.**

Merchant *tokens* (`REWE`, `HUK-COBURG`, `Shell`) are business names, not personal
data. That is the line.

- Packs in a **separate repo**, versioned and released independently of the app.
- "Contribute" action in the rule builder emits only pattern + category — human
  reviewed at both ends, structurally incapable of carrying a transaction.
- PR-based merge; third-party pack URLs supported so new countries do not
  bottleneck on the maintainer.
- Precedent: uBlock filter lists; ofxstatement plugins.

**Two safety properties:**

- **Ambiguity flags.** `AMAZON`, `PAYPAL` → force `?`: *never pre-marked, always
  reviewed*, from day one. They rank above memo-pattern rules in the precedence
  table (0002 §5.1). A shared pack that confidently mis-books Amazon orders across the
  whole user base is the specific failure that would sink the mechanism.
- **Signing or explicit pinning.** A pack influences what gets written to books; a
  careless one is a supply-chain problem with financial consequences.

Bundled packs feed the **proposal** path, not bypass review.

**Validate packs against the user's own history before enabling** — same panel as
the rule builder: "matches 340 of your transactions, agrees 96%, here are the 14
disagreements." Inverts the trust model: a bad pack is caught locally by
measurement rather than by trusting the publisher.

**Bound the investment.** Packs are a cold-start accelerant. Within a few months a
user's own index dominates for everything they actually transact with. The head is
what packs cover and also what any individual learns fastest. Modest, well-designed
mechanism — not a research programme. If collective improvement is wanted later,
the safe version is pooled *statistics* (opt-in: how often a shipped rule was
accepted vs corrected), not pooled data.

Seed `de-DE` v0 from accepted personal rules plus the head of the German market
(supermarkets, energy, insurers, telcos, transport). LLM drafting candidates is
legitimate here — every entry is public business information to verify, not
personal data collected.

### Model backend

- **OpenAI-compatible chat completions with configurable `base_url`** as the
  primary adapter. Covers Ollama, llama.cpp, vLLM, OpenRouter, Mistral, most
  cloud vendors. Native adapters only where the compatible endpoint is lacking.
- **Fully supported no-AI mode.** Rules + kNN, no network. First-class
  configuration, not a degraded fallback — kNN over the user's own history does
  most of the work anyway. Many GnuCash users will not send financial data
  anywhere.
- **Local by default.** The default backend is local (Ollama, llama.cpp …). A
  remote backend is opt-in.
- **Redaction at the adapter boundary.** Send normalised merchant token, amount,
  sign — not the raw memo. Built in so no backend can see the unredacted string.
  Show the user exactly what leaves the machine.
- **What a remote backend receives** is narrower still: (a) only a token that
  matches a rule-pack entry or a user allowlist of business names — otherwise the
  LLM abstains and the row is queued; and (b) the account list as **numeric
  indices**, mapped back locally, never the account names. Amount and sign as
  above. Reason: novel counterparties are disproportionately doctors and
  lawyers, and account names such as `Kirchensteuer` are themselves Art. 9
  special-category data.
- Credentials in the Secret Service via libsecret, not the config file.

Config in `$XDG_CONFIG_HOME` as TOML, mirroring GnuCash's own convention
(`~/.config/gnucash`, `~/.local/share/gnucash`).

### Backend abstraction

libgnucash abstracts `xml://`, `sqlite3://`, `mysql://`, `postgres://` behind an
identical object API, including lock detection (`gnclock` row vs `.LCK` file).

**Where it leaks:** anything done via read-only SQL is unavailable for XML books —
idempotency check, Imbalance assertion, balance checks, lock inspection. All must
go through the engine API. Slower on large books, works everywhere.

---

## Platform support

**Linux first.** macOS possible if Homebrew's formula enables bindings — verify,
do not assume.

**Windows is deferred, accepted as a restriction.** The analysis:

- GnuCash itself runs on Windows and a large share of users are there.
- The Python bindings are **not installed on Windows**. Not a scheduling gap: asked
  on gnucash-devel (Nov 2023), John Ralls — who maintains the Windows build —
  answered there is no way to make that work with an installed package.
- Reason is structural: bindings compile against MSYS2's MinGW Python; a
  python.org Python cannot load a MinGW-built extension module (different C
  runtime/ABI). Shipping the `.pyd` helps nobody without the matching interpreter.
- **C++ does not solve this.** The Windows installer ships no headers, no import
  libraries, no stable ABI contract. A C++ applier also has to build libgnucash via
  `gnucash-on-windows` and ship its own DLLs — same VM, same rebuild treadmill,
  same version-skew hazard. It would also make *Linux* distribution worse (binary
  per distro/arch, against a C++ ABI with no stability promise) and gives up the
  REPL, which is how this barely-documented API is actually learned.
- Build friction if ever attempted: MSYS2/MinGW-W64 + jhbuild + Inno Setup;
  WebKitGtk dropped from MinGW64 years ago and maintained as a custom package;
  Harfbuzz must be pinned so `pacman -Syu` does not break Harfbuzz-ICU; no Windows
  CI action.

**The hazard if Windows is ever attempted:** bundled libgnucash version will not
match the user's installed GnuCash.

- Bundled *older* → fails to open an upgraded book. Clean, loud, harmless.
- Bundled *newer* → writes, book format upgrades, **their GnuCash can no longer
  open their own books.** This is the one that ends the project's reputation.

Guard: read book format version before opening for write, compare against a
maintained compatibility matrix, refuse anything requiring an upgrade. Pin to the
*oldest* supported release, not the newest. Enforced backup before write becomes
mandatory, not prudent.

The JSON boundary in v1 keeps this a component swap. Decide on the treadmill when
users ask and ideally when one of them will help maintain the build.

---

## Build order

Sequencing matters more than any individual decision here. This section says
*what* each step contains; the order they are **executed** in — interleaved with
proposal 0002's D-milestones — is set in
[architecture chapter 9](../../architecture/09-build-order-and-roadmap.md).

0. **Spikes** (an afternoon, against a restored copy): Postgres URI with
   non-default port; GnuCash/bindings version pair; whether KVP slot access is
   needed at all. For `match_existing` it is not: Autobook writes no FITID or
   `online_id` stamp on a matched transaction (see *Idempotency*).
1. **Scheduled Transactions** for rent, salary, insurance, standing orders — a
   task for the user, in GnuCash. Deleting work beats automating it — plausibly
   removes a third of volume before a line of code.
2. **Corpus export + kNN + backtest harness.** No writes; read-only export
   through the book process (the exporter). No LLM. Rolling-origin backtest,
   stratified seen/novel. Highest information per hour of anything on this list:
   it tells you whether the premise holds. If history turns out too sparse or
   inconsistent for kNN, the whole design changes. **Do this before committing
   to the rest.**
3. Ingest, staging, FITID dedup.
4. Correlation pass, including transfers across batches and SX occurrences.
5. Book process: applier + assertions + launcher wrapper, tested against a
   restored copy.
6. Text-file review (no launcher). **Useful at this point** — before any GTK,
   any LLM, any distribution work. Until the applier exists, saving the review
   file records the decisions to staging, so shadow mode is the default state.
7. **Shadow mode** — continuous; closes when there is enough evidence. Thresholds
   set so nothing is pre-marked. Keep booking by hand; classifier proposes in
   parallel. Costs nothing extra and produces the per-method,
   per-confidence-band precision data that justifies every threshold.
8. Rules file, LLM tail; thresholds lowered on evidence, so more rows are
   pre-marked.
9. GTK4 rule builder, category indirection, packaging.

---

## Rejected alternatives

Recorded to avoid re-litigating.

| Option | Why rejected |
|---|---|
| **CSV import with `Transfer Account`** | Structurally requires the import assistant + matcher on every batch. Discards the ease-of-use goal. (Was briefly favoured for dependency durability — wrong optimisation target.) Retained only as a possible degraded applier for platforms without bindings. |
| **piecash** | Stale: still 1.2.0, documented against the GnuCash 3.0 book format. Writes SQL directly rather than through the engine. Superseded by `python3-gnucash`. |
| **Seeding GnuCash's Bayes map from history** | Dead for own use — the pipeline pre-assigns the destination, so the matcher is never consulted. Survives only as a standalone upstream patch for users *not* running this tool. |
| **In-app GnuCash plugin** | Scheme extensions are report-shaped in practice; the import matcher is C++ with no registration API. Even with a hook: book is single-writer, LLM calls are latency-prone and failure-prone inside a modal dialog, and the staging table / audit trail / replay all disappear. |
| **Raw SQL against the book** | Schema coupling, no engine business logic, no XML support. |
| **C++ applier** | See Platform support. Does not solve Windows; makes Linux worse. |
| **Sentence embeddings for kNN** | Few hundred MB download, nondeterministic across versions, helps only for lexically-novel-but-semantically-familiar merchants — which fall through to the LLM anyway. Revisit only if the backtest shows failures dominated by that case. |
| **Pooled/shared kNN indices** | Label space is per-book; indices are not poolable. Sharing must happen at the semantic-category level, which is the pack mechanism. |
| **Collecting user transactions for a shared corpus** | Special-category personal data. Not worth it for a volunteer project. |

---

## Open questions

- **Synthetic corpus seeding (LLM-generated memo→account pairs).** Deferred, not
  decided. Concern: it destroys abstention (a synthetic neighbour makes a novel
  merchant look familiar) and invalidates the backtest (measuring agreement with a
  model's guesses rather than real decisions). If experimented with: measure
  **coverage gain vs error rate on rows that were previously abstentions**,
  separately — these pull in opposite directions and an aggregate number hides it.
  Provenance tagging makes the comparison possible; costs nothing now.
- Whether kNN beats token-Bayes by enough to justify itself (backtest will tell).
- macOS bindings availability via Homebrew.
- Whether booking ever happens from more than one machine (affects launcher
  placement vs. homelab applier with lock deferral). The homelab variant is an
  unattended run, **[DEFERRED]** beyond v1.

---

## Parallel track — upstream

Independent of everything above; the tool must remain fully functional if none of
it lands.

- **Bayes-seeding patch.** No AI, no new dependencies, closes an acknowledged gap
  (the matcher only learns during imports, never mines existing history). Useful on
  its own merits. Landing a patch establishes standing.
- **Friction log.** Record where the API forced workarounds while building. Worth
  more than a design document written in advance, and it probably will not be what
  was guessed here.
- **File bindings bugs with reproductions.** Improves the dependency and shows the
  maintainers the bindings have real users.
- **Eventual pitch, if adoption warrants:** the *Finance::Quote pattern applied to
  the import matcher* — GnuCash calls an external helper for account matching, owns
  none of the logic, ships none of the dependencies, takes on no AI. Points at a
  design the project already accepted and maintains, which is a far stronger frame
  than "make the matcher pluggable."

Process notes: enhancement requests go to Bugzilla (Severity=Enhancement,
Version=git-future); new features target the `future` branch; the project's own
guidance is that a report with a well-written patch is far more likely to land, and
there is boilerplate rejection text for unpatched proposals. Since Sept 2025
Bugzilla requires login even to *view* bugs and auto account creation is disabled —
request an account first; search engines can no longer index bug reports. Mailing
list archives are still indexed (`site:lists.gnucash.org`).

Expected failure mode is silence, not rejection. Small, concrete, patch-attached.

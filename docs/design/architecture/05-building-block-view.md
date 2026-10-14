---
created: 14.10.2026 23:50
type: architecture
status: living
tags:
  - architecture
  - building-blocks
---
# 5. Building block view

> Living document. Describes the designed decomposition; package and module
> names are provisional until the code exists **[OPEN]**. Diagram source:
> [`diagrams/c4-container.mermaid`](diagrams/c4-container.mermaid).

## 5.1 Three processes and one store

| Block | Runs as | May link libgnucash | Purpose |
|-------|---------|---------------------|---------|
| **Pipeline** | Python in a virtualenv | **No — enforced by the gate** | Everything from statement to approved proposal |
| **Book process** | System Python (`python3-gnucash` in `dist-packages`) | Yes, and nothing else does | Every read from and write to a book |
| **Launcher** | Shell wrapper around `gnucash` | No | Sequencing: backup, run, review, apply, assert, open GnuCash |
| **Staging store** | SQLite in `$XDG_DATA_HOME` (default) or a PostgreSQL URI | — | Audit trail, correction corpus, undo list; the seam between classification and writing |

The split between pipeline and book process is load-bearing (proposal 0001,
*Why the boundary matters*): it keeps the pipeline testable with no GnuCash
installed and no book present, sidesteps the `dist-packages` virtualenv problem,
and makes a future Windows port a component swap.

### The JSON contracts

All communication between pipeline and book process is JSON on stdin/stdout or
in files under the staging directory. Each contract is versioned; widening one is
a documented change that updates this section in the same PR.

| Contract | Direction | Carries |
|----------|-----------|---------|
| `corpus` | book → pipeline | Two-split transactions: `(normalised-able raw memo, amount_cents, sign, source_account, destination_account, post_date, provenance)`. Read-only session. |
| `coa` | book → pipeline | The live account tree: full names, types, placeholder flags, commodities. |
| `existing` | book → pipeline | `num` values already present (idempotency), and per account the unreconciled transactions eligible for `match_existing` in a date window. |
| `apply-in` | pipeline → book | Approved rows: `proposal_id`, disposition, source and destination (or split specification), `amount_cents`, currency, date, description, optional `doc_link`, optional `match_guid`. |
| `apply-out` | book → pipeline | Per row `{proposal_id, tx_guid, status}`; per batch the assertion results. |

**[OPEN]** Whether `existing` is a separate call or folded into the applier's own
pre-batch check. Proposal 0001 places the `match_existing` search in the applier;
exporting candidates instead would let the review file show them. Decide when
the applier is built.

## 5.2 Pipeline components

### Statement source

An interface with two implementations: **paperless** (proposal 0002 §3) and
**files**. Both yield `(original bytes, checksum, source_account, plugin)` to the
same admission path, so the plugins cannot tell where a statement came from. The
paperless source resolves statements through an explicit mapping of
correspondent and document type to source account; unmapped statements are
reported, never guessed.

### Admission and dedup

Runs the mapped ofxstatement plugin, applies the **balance check** where the
format has balances, and assigns row keys: FITID where present, otherwise
`(source_account, original_checksum, line_ordinal)` plus the period-overlap rule.
A statement that fails admission is rejected whole and recorded; other
statements proceed.

### Normaliser

Strips SEPA boilerplate (`EREF+`, `MREF+`, `CRED+`, `SVWZ+`, `ABWA+`), dates, card
fragments and sequence numbers until the merchant token remains. **Profiles are
per source account**, loaded from the installed package and from a user
directory, so a new bank or country does not need a release. The normaliser
version is part of the version gate tuple.

### Correlator

The only component with a cross-account view. Pairs the two sides of transfers
between the user's own accounts and emits the transfer from one canonical side;
matches PayPal lines to their funding transaction as transfers, not expenses.
Without it every transfer is booked twice.

### Bill matcher (proposal 0002)

Reads bill metadata from paperless and links bills to bank rows **batch-wide**:
exact amount in cents, date within an asymmetric window, compatible
correspondent; a link exists only when the pairing is one-to-one. It changes no
amount, date or account. Its only downstream effect is to make document
conditions (correspondent, document type, tag) available to rules, and a
`doc_link` available to the applier.

### Classifier

The cascade, in order:

1. **Rules.** A versioned, git-tracked file owned by the user, plus bundled
   packs. Precedence: exact identifier (SEPA creditor ID), then document
   conditions, then memo pattern. Rules may target a split specification;
   they are the only tier that may.
2. **kNN.** Character n-gram TF-IDF (`char_wb`, 3–5) over the user's own corpus,
   one index per `(source_account, sign)`, cosine distance, exponential recency
   decay (~18-month half-life), rebuilt every run in-process. A prediction is
   accepted only if the **nearest-neighbour distance** is under its cutoff **and**
   the **vote margin** clears its threshold. Corpus rows are tagged `observed` or
   `corrected`; nothing else can enter.
3. **LLM tail.** Through the model adapter only, with the live account list as
   the label space; output outside the tree is rejected. Optional.

A row nothing accepts goes to `queue`. kNN and the LLM return a single account,
never a split.

**Category indirection.** Bundled packs map patterns to semantic categories
(`groceries`, `insurance`), not accounts. A per-user category → account mapping
binds them, derived from history and confirmed by the user.

### Model adapter

The redaction boundary. Accepts a normalised merchant token, amount and sign;
cannot be handed a raw memo, an IBAN or document content by its type signature.
OpenAI-compatible with a configurable `base_url`; credentials from the Secret
Service. Absent entirely in no-AI mode.

### Disposition

Assigns each row one of `create | create_split | match_existing | out_of_scope |
queue`. Out-of-scope rows (securities, split-currency) are recorded and visible
but excluded from the queue and from coverage and drift metrics.

### Batch gate

Decides whether anything is written at all: coverage below a rolling baseline,
LLM-fallback spike, unusual share of rarely used accounts, parse errors above a
small count, a changed version tuple, paperless unreachable. Any of these writes
nothing and notifies; the launcher still opens GnuCash.

### Review file

Generates a `git rebase -i`-style text file and parses it back **by ID, never by
position**, strictly: an unknown ID, status character, account or an amount
change aborts the whole parse with a line number. Corrections are recorded as
`corrected` corpus rows.

### Trial tooling (scenario 1)

Never touches a book except through a read-only corpus export. Contains the
leave-one-out **backtest** (per method, per confidence band, token-Bayes as a
negative control), the **rule builder** (cluster, propose, backtest immediately,
accept — GTK4 eventually, CLI first), the **assistant detector** (recurring
debits and loan-shaped payments handed to GnuCash's assistants), the **pack
validator**, and from proposal 0002 the **linkage backtest**.

### Staging store

```
statements(original_checksum PK, paperless_doc_id, source_account, plugin,
           plugin_version, period_start, period_end, opening_balance,
           closing_balance, balance_check, admitted_ts)

proposals(fitid_or_key PK, source_account, post_date, amount, currency,
          raw_memo, normalised_memo,
          proposed_account, confidence, method, rule_id,
          disposition, status,            -- pending|approved|rejected|applied
          applied_tx_guid, human_correction,
          statement_checksum, doc_id, doc_match, doc_candidates,
          classifier_version, normaliser_version, ts)
```

Amounts are integer cents. Document fields are IDs and counts, never content.

## 5.3 Book process components

| Component | Responsibility |
|-----------|----------------|
| **Session manager** | Opens with `SESSION_NORMAL_OPEN` for writes and `SESSION_READ_ONLY` for export and dry-run; never `SESSION_BREAK_LOCK`; one session per run; `session.end()` in `finally`. Treats `QOF_BACKEND_LOCKED` as "deferred" in unattended runs. |
| **Exporter** | Produces `corpus`, `coa` and `existing` through the engine API. |
| **Applier** | For each approved row: skip if its proposal ID is already a `num`; otherwise create (two splits or a split specification that sums exactly), or link to an existing unreconciled transaction for `match_existing`. Sets the document link where given, never overwriting an existing one. Every mutation inside `BeginEdit` / `CommitEdit`. |
| **Assertions** | After the batch: Imbalance account zero; each touched account's balance equals the statement closing balance where known. Non-zero exit on failure. |

It never creates accounts, never creates scheduled transactions, never sets the
reconciled flag, and never uses SQL against the book.

## 5.4 Launcher

A short shell wrapper that the user runs instead of `gnucash`:

1. Back up the book where the backend is a file; warn on server backends.
2. Run the pipeline; if proposals are pending, generate the review file and open
   `$EDITOR`.
3. Run the book process to apply, then assert. Notify on failure.
4. `exec gnucash` — always, regardless of the outcome of 1–3.

Unattended runs (homelab) use the same steps without step 2's editor and with
lock deferral instead of sequencing (section 7).

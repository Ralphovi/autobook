---
created: 14.10.2026 23:50
type: architecture
status: living
tags:
  - architecture
  - building-blocks
---
# 5. Building block view

> Living document. Describes the designed decomposition and the package layout
> that implements it (below). Diagram source:
> [`diagrams/c4-container.mermaid`](diagrams/c4-container.mermaid).

### Package layout

All under `src/autobook/`, one module per building block. Each stub module sets
`__all__` to the one name of its entry point.

| Path | Block |
|------|-------|
| `contracts.py` | The versioned JSON contracts (section 5.1). Standard library only. |
| `staging.py` | The staging store (section 5.1). Its own top-level block, because both processes use it. Standard library only. |
| `pipeline/` | `statement_source`, `admission`, `normaliser`, `correlator`, `bill_matcher`, `classifier`, `model_adapter`, `disposition`, `batch_gate`, `review_file`, `trial` (section 5.2). Never imports `gnucash`. |
| `book/` | `session`, `exporter`, `applier`, `readback`, `assertions`, `undo` (section 5.3). The only package that may import `gnucash`, per file, as each module needs it. |

The launcher (section 5.4) is a shell script, not a Python module. `import
autobook` does not import the subpackages.

## 5.1 Three processes and one store

| Block | Runs as | May link libgnucash | Purpose |
|-------|---------|---------------------|---------|
| **Pipeline** | Python in a virtualenv | **No — enforced by the gate** | Everything from statement to approved proposal |
| **Book process** | System Python (`python3-gnucash` in `dist-packages`) | Yes, and nothing else does | Every read from and write to a book, in two parts: the **exporter** (read-only, from build step 2) and the **applier** (writes, from build step 5) |
| **Launcher** | Shell wrapper around `gnucash` | No | Sequencing: backup, read-only export, pipeline, review, apply, assert, open GnuCash |
| **Staging store** | SQLite in `$XDG_DATA_HOME` (default) or a PostgreSQL URI | — | Audit trail, correction corpus, undo list; the seam between classification and writing |

The split between pipeline and book process is load-bearing (proposal 0001,
*Why the boundary matters*): it keeps the pipeline testable with no GnuCash
installed and no book present, sidesteps the `dist-packages` virtualenv problem,
and makes a future Windows port a component swap.

The ban on importing `gnucash` applies to the **pipeline**. It is lifted for the
whole book process, exporter and applier alike. The `nox -s applier` session and
the pytest `applier` marker keep that name (renaming code is out of scope) but
cover every book-process test.

### The JSON contracts

All communication between pipeline and book process is JSON on stdin/stdout or
in files under the staging directory. Each contract is versioned; widening one is
a documented change that updates this section in the same PR.

Wire shape, implemented in `autobook.contracts`:

- Every document is a JSON object with its `contract` name (`"corpus"`,
  `"coa"`) and an integer `version`, starting at `1`. A reader accepts only a
  name and version it knows, and rejects anything else with `ContractError`.
- Money is a plain integer of cents. A float or a boolean is rejected.
- An account is a **list of path components**, root account excluded, never a
  separator-joined string. GnuCash takes the account separator from a user
  preference outside the book (`.` in a headless session, often `:` on a
  desktop), so a joined string would mean different things on different
  machines. Nothing in the contracts joins or splits a path.
- A missing or unknown field is rejected, as is a value outside a closed set.
- The same checks run when a contract object is built in Python, so a writer
  cannot serialise a document a reader would refuse (for example a bare string
  where a path belongs, which would otherwise come out as one component per
  character).
- `corpus` is `{"contract", "version", "rows"}`. A row has `raw_memo`,
  `amount_cents` (the magnitude, an integer greater than zero), `sign`,
  `source_account`, `destination_account`, `post_date` (`YYYY-MM-DD`) and
  `provenance`. `sign` is `"out"` when the money leaves `source_account` and
  `"in"` when it enters it; the kNN index is keyed by `(source_account, sign)`.
  `provenance` is always `"observed"`: the contract refuses `corrected`.
- `coa` is `{"contract", "version", "accounts"}`. An account has `path`, `type`
  (one of GnuCash's account-type names, exact case: `NONE`, `BANK`, `CASH`,
  `CREDIT`, `ASSET`, `LIABILITY`, `STOCK`, `MUTUAL`, `CURRENCY`, `INCOME`,
  `EXPENSE`, `EQUITY`, `RECEIVABLE`, `PAYABLE`, `ROOT`, `TRADING`, `CHECKING`,
  `SAVINGS`, `MONEYMRKT`, `CREDITLINE`), `placeholder`, `commodity`
  (`{"namespace", "mnemonic"}`) and `fraction` (an integer greater than zero).

| Contract | Direction | Carries |
|----------|-----------|---------|
| `corpus` | book → pipeline | Two-split transactions: `(normalised-able raw memo, amount_cents, sign, source_account, destination_account, post_date)`, every one with provenance `observed`. Read-only session. `corrected` rows never come from the book; the pipeline adds them from staging. |
| `coa` | book → pipeline | The live account tree: paths (component lists), types, placeholder flags, commodities and their fractions. |
| `existing` | book → pipeline | Autobook IDs already present in `num` (idempotency); per source account the transactions in a date window, for the `match_existing` search; and the **scheduled-transaction (SX) definitions** — template accounts, amounts, recurrence — so the pipeline can tell when a row falls on an SX occurrence. Read-only session. |
| `apply-in` | pipeline → book | Approved rows: `proposal_id`, disposition, source and destination (or split specification), `amount_cents`, the source account's commodity, date, description, optional `doc_link`, optional `match_guid`. |
| `apply-out` | book → pipeline | Per row `{proposal_id, tx_guid, status}`, where `applied` is reported only after a read-back has found the transaction; per batch the assertion results. |

The `match_existing` search runs in the pipeline, over the `existing` export, so
that a row can be queued as awaiting a scheduled transaction or a pending
transfer and the review file can show the match. The applier re-checks the
matched GUID inside its write session before touching it. This settles the
earlier open question of whether `existing` is a separate call: the SX
definitions and the transfer search before classification both need it before
the pipeline runs.

## 5.2 Pipeline components

### Statement source

An interface with two first-class implementations: **paperless** (proposal 0002
§3) and **files**. Both yield `(original bytes, checksum, source_account, plugin)` to the
same admission path, so the plugins cannot tell where a statement came from. The
paperless source resolves statements through an explicit mapping of
correspondent and document type to source account; unmapped statements are
reported, never guessed.

### Admission and dedup

Runs the mapped ofxstatement plugin, applies the **balance check** where the
format has balances, and assigns row keys. Every key includes `source_account`.
Each plugin declares whether its `id` is bank-supplied. A bank-supplied FITID
is the key where present; otherwise — including IDs a plugin synthesises, such
as ofxstatement's hash of date, memo and amount — the key is
`(source_account, original_checksum, line_ordinal)` plus the period-overlap
rule. The overlap rule's line matching is **count-aware**: two identical lines
in the overlap need two identical staged lines.

Every statement gets a `statements` row, from paperless or from a file (the
checksum is the file's), so both paths can be compared row for row. For a
paperless statement, admission records the document version and fetches the
original with `?version=`. A statement that fails admission is rejected whole
and recorded with status `rejected` and its reason; other statements proceed.

**[OPEN]** until D0: whether statements arrive as PDFs or as the CSV/OFX exports
the plugins read today (proposal 0002, *Open questions*). PDF parsing is not a
settled part of this design.

### Normaliser

Strips SEPA boilerplate (`EREF+`, `MREF+`, `CRED+`, `SVWZ+`, `ABWA+`), dates, card
fragments and sequence numbers until the merchant token remains. **Profiles are
per source account**, loaded from the installed package and from a user
directory, so a new bank or country does not need a release. The normaliser
version is part of the version gate tuple.

### Correlator

The only component with a cross-account view. Pairs the two sides of transfers
between the user's own accounts and emits the transfer from one canonical side.
Without it every transfer is booked twice.

Transfers also span batches. Every transfer row first goes through a
`match_existing` search in its **source** account, before classification: the
second side of a transfer booked in an earlier batch resolves to the transaction
the first side created, which has splits in both accounts. A transfer booked
from one side records a `transfers_pending` entry (counterpart account, amount,
date window, the first side's proposal ID and transaction GUID). An unmatched
second side whose counterpart is pending is queued as "pending transfer", never
classified.

PayPal follows the configuration key `paypal_mode`:

- `account` (default): PayPal is its own GnuCash account and its statement is
  imported. Bank lines to PayPal are transfers, resolved here.
- `pass_through`: PayPal statements are never imported. The bank line is
  classified by the merchant parsed from its memo (`PAYPAL .VENDORX` →
  `VENDORX`).

### Bill matcher (proposal 0002)

Reads bill metadata from paperless and links bills to bank rows **batch-wide**:
exact amount in cents, date within an asymmetric window, and a **confirmed
correspondent association** between the bill's correspondent and the row's
merchant token (proposal 0002 §4.4). Candidate bills are first deduplicated by
`original_checksum`, because paperless accepts duplicate documents by default; a
link exists only when the remaining pairing is one-to-one. It changes no amount,
date or account. Its only downstream effect is to make document conditions
(correspondent, document type, tag) available to rules, and a `doc_link`
available to the applier.

A bill without a correspondent, or whose correspondent has no confirmed association, can only produce `doc_match = weak`: a hint line
in the review file, never input to a rule. Which paperless document types count
as bills and which as credit notes is configuration, and part of the version
tuple.

### Classifier

The cascade runs **rules → kNN → LLM** (k-nearest-neighbour, then a large
language model). Precedence is one table, which governs everywhere. It is
stated in full in proposal 0002 §5.1 (document conditions); proposal 0001's
*Rules* section points to it. In short:

| Tier | Source | Condition |
|------|--------|-----------|
| 1 | Creditor-ID rule (SEPA Gläubiger-ID) | Exact match |
| 2 | Document-keyed rule | Only with a confirmed correspondent association, `auto: true`, and passed shadow mode |
| 3 | Ambiguity flag (`AMAZON`, `PAYPAL` …) | Forces `?`: the row is never pre-marked |
| 4 | Memo-pattern rule | |
| 5 | kNN | Both gates pass |
| 6 | LLM tail | Optional; always `?` until shadow mode has measured its precision |

A rule's `priority` field orders rules **within** a tier only. Every rule has
an `auto` field: default `true`, except document-keyed rules, which default to
`false`; a rule with `auto: false` proposes but never pre-marks. The rule
builder reports conflicts between any two tiers on historical rows.

- **Rules.** A versioned, git-tracked file owned by the user, plus bundled
  packs. Rules may target a split specification; they are the only tier that
  may. Fixed split amounts are integer cents (`cents: 1250`), never a decimal
  value.
- **kNN.** Character n-gram TF-IDF (term frequency–inverse document frequency;
  `char_wb`, 3–5) over the user's own corpus, one index per
  `(source_account, sign)`, cosine distance, exponential recency decay
  (~18-month half-life), rebuilt every run in-process. A prediction is accepted
  only if the **nearest-neighbour distance** is under its cutoff **and** the
  **vote margin** clears its threshold. Corpus rows are tagged `observed` or
  `corrected`; nothing else can enter.
- **LLM tail.** Through the model adapter only. The label space is the live
  account list, minus placeholder accounts and Equity and Trading account types;
  output outside it is rejected. Temperature is pinned to 0, and the model ID is
  recorded in the version tuple. An LLM proposal is always `?` until shadow mode
  has measured per-method precision for `method=llm`; only then may a threshold
  pre-mark LLM rows. Optional.

A row nothing accepts goes to `queue`. kNN and the LLM return a single account,
never a split.

**Category indirection.** Bundled packs map patterns to semantic categories
(`groceries`, `insurance`), not accounts. A per-user category → account mapping
binds them, derived from history and confirmed by the user.

### Model adapter

The redaction boundary. Accepts a normalised merchant token, amount and sign;
cannot be handed a raw memo, an IBAN or document content by its type signature.
The account list is sent as **numeric indices**, mapped back to accounts
locally; account names never cross. OpenAI-compatible with a configurable
`base_url`; credentials from the Secret Service. Absent entirely in no-AI mode.

The default backend is **local** (Ollama, llama.cpp …). A remote backend is
opt-in, and then receives a token only when it matches a rule-pack entry or the
user's allowlist of business names; for any other token the LLM abstains and the
row is queued.

### Disposition

Assigns each row one of `create | create_split | match_existing | out_of_scope |
queue`. Out-of-scope rows (securities, split-currency) are recorded and visible
but excluded from the queue and from coverage and drift metrics.

A row in a source account whose amount and date (± the match window) fall on an
SX occurrence is **never `create`**: it is `match_existing` if GnuCash has
created the instance, otherwise `queue` with the reason "awaiting scheduled
transaction", which resolves on a later run. `match_existing` searches the
row's **source** account (an SX transaction may have many splits), among
transactions not already claimed by Autobook — no Autobook ID in `num` and no
GUID in staging's `applied_tx_guid`. Whether a candidate is reconciled does not
matter.

### Batch gate

Decides whether anything is written at all: coverage below a rolling baseline,
LLM-fallback spike, unusual share of rarely used accounts, parse errors above a
small count, a changed version tuple, paperless unreachable. Any of these writes
nothing and notifies; the launcher still opens GnuCash.

### Review file

Generates a `git rebase -i`-style text file at
`$XDG_RUNTIME_DIR/autobook/review.txt` (mode `0600`, removed in `finally`)
listing the batch's in-scope rows. Rows that passed the gates
are pre-marked `a` (accept); everything else is `?`. **Saving the file is the
user's approval of every row marked `a` in the saved file**, with the account,
amount and date shown. Nothing else reaches the book.

The file is parsed back **by ID, never by position**, strictly: an unknown ID,
status character, account or an amount change aborts the whole parse with a
line number. A row with a weak bill match carries a hint line, nothing more.
Corrections are recorded as `corrected` corpus rows. Until the
applier exists (build step 5), saving the file records the decisions to staging
and writes nothing.

### Trial tooling (scenario 1)

Never touches a book except through the exporter's read-only corpus export.
Contains the **backtest**, which is **rolling-origin**: for each month m, the
index holds the rows before m and the test set is month m. Results are reported
per method and per confidence band, with token-Bayes as a negative control, and
stratified by whether the memo was seen before in the index or is novel; gate
thresholds are set on the **novel** stratum. Leave-one-out remains only as an
upper bound and for the rule builder's quick "matches N historical rows"
verdict. Also the **rule builder** (cluster, propose, backtest immediately,
accept — GTK4 eventually, CLI first), the **assistant detector** (recurring
debits and loan-shaped payments handed to GnuCash's assistants), the **pack
validator**, and from proposal 0002 the **linkage backtest**.

### Staging store

This is the single staging schema; the proposals' schemas match it.

```
statements(original_checksum PK,          -- of the paperless original or the file
           paperless_doc_id, doc_version, -- NULL for file ingest
           source_account, plugin, plugin_version,
           period_start, period_end, opening_balance, closing_balance,
           balance_check,                 -- passed | not_possible
           status, reason,                -- admitted | rejected; why rejected
           admitted_ts)                   -- time of the admission decision

proposals(source_account, fitid_or_key,   -- PK (source_account, fitid_or_key)
          proposal_id,                    -- AB- + ULID; in num on created transactions only
          post_date, amount, currency,
          raw_memo, normalised_memo,
          proposed_account, confidence, method, rule_id,
          disposition, queue_reason, status,  -- status: pending|approved|rejected|applied
          applied_tx_guid, human_correction,
          statement_checksum, doc_id, doc_match, doc_candidates,
          classifier_version, normaliser_version, ts)

transfers_pending(counterpart_account, amount, window_start, window_end,
                  proposal_id, tx_guid)   -- first side of a cross-batch transfer
```

`fitid_or_key` is the bank-supplied FITID, or for statements without one the
`(original_checksum, line_ordinal)` pair. The **proposal ID** is something
else: `AB-` followed by a ULID (a 26-character sortable unique ID, short enough
for GnuCash's `num`), generated per staged row. Only `num` values matching
`^AB-[0-9A-HJKMNP-TV-Z]{26}$` count as Autobook IDs. `statement_checksum` is set
for file ingest as well as paperless ingest. A row is `applied` only after the
book process's read-back has confirmed it.

Amounts are integer cents. Document fields are IDs and counts, never content.

## 5.3 Book process components

The book process has two parts: the **exporter**, which only reads and exists
from build step 2, and the **applier**, which writes and exists from build step
5. They share the session manager.

| Component | Responsibility |
|-----------|----------------|
| **Session manager** | Opens with `SESSION_NORMAL_OPEN` for writes and `SESSION_READ_ONLY` for export and dry-run; never `SESSION_BREAK_LOCK`; one session per run. On the write path: after the last `CommitEdit`, `session.save()`, then the post-apply assertions, then `session.end()` in `finally`. On `ERR_BACKEND_LOCKED` (the lock error in `qofbackend.h`) it writes nothing and the launcher notifies. `SESSION_READ_ONLY` ignores locks, so an XML export with the GUI open reads the last *saved* state. |
| **Exporter** | Produces `corpus`, `coa` and `existing` (including SX definitions) through the engine API, in a `SESSION_READ_ONLY` session. |
| **Applier** | For each approved row. `create` / `create_split`: skip if its proposal ID is already a `num`; otherwise create (two splits, or a split specification that sums exactly) with the proposal ID in `num`. Before building `GncNumeric(cents, 100)` it takes the source account's commodity, verifies that both accounts share it and that its fraction is 100; no currency is hard-coded. `match_existing`: re-check the matched GUID; write **no `num`** and **no FITID / `online_id` stamp** to it. The only thing ever written to a matched transaction is a document link, and never over an existing one. Every mutation inside `BeginEdit` / `CommitEdit`. |
| **Read-back** | A row is reported `applied` (in `apply-out`, and in staging) only after a read-back confirms it. XML: reopen `SESSION_READ_ONLY` and find its ID. SQL: an engine query. With XML nothing persists until `save()`, so a batch is all-or-nothing; SQL is durable per `CommitEdit` and `save()` is harmless. |
| **Assertions** | After the batch, for each source account with a statement in the batch: (a) the change in its balance caused by the batch equals the sum of the rows applied; (b) where the statement has a closing balance, the account's balance on the closing date equals that closing balance minus the statement lines not yet applied (queued, `out_of_scope`, awaiting a scheduled transaction, pending transfer); (c) the Imbalance account is **unchanged** by the batch. Non-zero exit on failure. |
| **Undo** | Deletes only transactions whose GUID is in staging with disposition `create` **and** whose `num` equals that row's proposal ID, asserting both before each delete. For a matched row it removes only the document link the batch added. |

It never creates accounts, never creates scheduled transactions, never sets the
reconciled flag, and never uses SQL against the book.

## 5.4 Launcher

A short shell wrapper that the user runs instead of `gnucash`. It arrives with
the applier in build step 5; before that there is nothing to sequence.

1. Back up the book: a file copy where the backend is a file; `pg_dump` for a
   PostgreSQL book when it is on `PATH`, with the database credentials from the
   Secret Service, otherwise a warning; a warning for MySQL.
2. Run the book process's exporter (read-only).
3. Run the pipeline; if proposals are pending, generate the review file at
   `$XDG_RUNTIME_DIR/autobook/review.txt` (mode `0600`) and open `$EDITOR`.
4. Run the book process to apply, save, assert and read back. Remove the review
   file.
5. `exec gnucash` — always, regardless of the outcome of 1–4.

The launcher must always reach `exec gnucash`. There is no `set -e` abort path:
each step runs as `step || notify`, the steps run inside a function, and a
`trap` makes sure the `exec` happens and the review file is removed.

Unattended runs (homelab, no editor) are **[DEFERRED]** beyond v1: approval is a
save of the review file, which needs a human (section 7).

---
created: 14.10.2026 23:50
type: architecture
status: living
tags:
  - architecture
  - runtime
---
# 6. Runtime view

> Living document. The design is
> [proposal 0005](../proposals/draft/0005-beancount-ledger.md); section numbers
> written as §n refer to it. Diagram source for 6.1:
> [`diagrams/booking-run-sequence.mermaid`](diagrams/booking-run-sequence.mermaid).

Terms used throughout this chapter:

- The **driver** is a separate program, outside Autobook, that obtains bank
  statements, converts them to OFX files, calls Autobook's commands and talks to
  the user (section 5.4).
- A **statement** is one OFX file; a **line** is one entry of it. A staged line
  is also called a **row**.
- The **ledger** is the user's Beancount v3 plain-text ledger: a main file and
  the files it includes. The **owned file** is the one included file that
  Autobook writes to; it never edits any other.
- The **ledger package** is the only code that imports `beancount`. Its
  **reader** loads the ledger and its **writer** changes the owned file
  (section 5.3).
- **Staging** is Autobook's own store of statements, proposals and decisions
  (section 5.2).

## 6.1 An interactive booking run

Autobook does not drive a run. It offers commands, each of which does one thing
and exits with a code (section 5.5); none of them starts an editor or another
program. A run is those commands chained by the driver.

| Step | Who | What |
|------|-----|------|
| 1 | Driver | Obtains the statements and converts each to an OFX file. Hands the files to Autobook, optionally with a **producer string** per file (for example the converter plugin's name and version) |
| 2 | Autobook | `autobook propose FILE…`: the reader loads the ledger and supplies the chart of accounts, the corpus of historical transactions, the existing Autobook IDs and the match candidates. Each statement is admitted whole or not at all (6.2). The admitted lines are normalised, deduplicated, correlated (transfers, `match_existing`), linked to bills, classified and given a disposition — correlation and bill linking before classification (6.3, 6.4). The batch gate then decides whether the batch may go on, and the proposals are staged |
| 3 | Autobook | `autobook review-file`: writes the review file to standard output, with the rows that passed the gates pre-marked `a` and the rest `?` |
| 4 | Driver and user | The driver decides where the review file lives and opens it in an editor. The user corrects it and saves |
| 5 | Autobook | `autobook apply --from FILE`: parses the saved file strictly by ID and records the decisions to staging. Every row marked `a` in the saved file is approved, exactly as shown; nothing else is. The writer then books the approved rows into the owned file, reads the ledger back and runs the assertions (6.5) |
| 6 | Driver | Reads the exit code and the `--json` output, removes the review file, and notifies the user |

Autobook's part is steps 2, 3 and 5. Everything else — where statements come
from, when a run starts, which editor opens, how the user is told the result —
is the driver's, and a user can run the same commands by hand.

What ends a run early, and what it leaves behind:

- A statement rejected at admission gives exit code 7 and the reason per file.
  Nothing of that statement is staged.
- A refusal by the batch gate or the version gate gives exit code 3 and writes
  nothing (6.8). Proposals stay pending.
- A review file that does not parse gives exit code 5 with a line number.
  Nothing is recorded and nothing is booked.
- `autobook pending` exits 1 when there is nothing to review, so the driver can
  skip steps 3 to 5.

Until the writer exists (build step 5) the run ends after the review file:
`autobook decide --from FILE` records the decisions to staging and writes
nothing to the ledger, so shadow mode is the default state.

There is no lock and no ordering between Autobook and other programs. The
ledger is text files; an editor or Fava may have them open during a run. What
protects the ledger instead is in 6.5: nothing is written if any ledger file
changed since it was read, the owned file is replaced by one checked atomic
exchange that puts back a save that got in at the last moment, and
a failed read-back puts the previous content back. Between two Autobook runs
there is a lock: `propose`, `apply`, `undo` and `decide` hold Autobook's own writer lock from
before they parse the review file or read the ledger until staging is updated, and a run that cannot take it writes
nothing (exit 4).

## 6.2 Admitting a statement

Before admitting anything, `autobook propose` takes the writer lock and re-hashes the kept
pre-images; a changed or missing one stops it with exit code 4, because the ledger is then
missing a displaced save and would be incomplete history to match and classify against.
Admission is then the first thing `autobook propose` does with each OFX file.

1. Compute the file's checksum. A file already recorded in `statements` as
   **admitted** changes nothing: handing over the same file twice is harmless.
   A file recorded as **rejected** goes through every step again, so that a
   rejection for a reason outside the file can be cleared.
2. Parse the file with Autobook's own OFX parser (standard library only). It
   reads the account ID, the currency, the statement period, the ledger
   balance, and per line the ID, date, amount, name and memo. The memo is taken
   as it arrives; normalisation happens later, in Autobook.
3. Check the content. Every line has a date, an amount and a currency, and
   every amount is a whole number of cents. The account ID is one the
   configuration maps to a ledger account. The statement's currency is one that
   account's `open` directive declares.
4. Balance check where the statement states balances: lines sum exactly to
   closing minus opening, in cents.
5. Assign row keys, each including `source_account`. Where the configuration
   says the line IDs are bank-supplied, the key is the bank's ID. Otherwise the
   ID was synthesised by the converter and is not trusted as an identity: the
   line takes the key `(statement checksum, ordinal)`, and the period-overlap
   rule (proposal 0002 §3.4), matching lines count-aware, decides whether a
   later statement repeats it.
6. Record the statement with status `admitted`, together with its producer
   string if the driver gave one; stage its rows.

Any failure in 2–5 — including an overlap the rule cannot resolve — rejects
that statement only: it is recorded with status `rejected` and the reason, no
line of it is staged, and the command reports exit code 7 with the reason per
file.

Autobook does not second-guess a well-formed statement. Fetching the original
document, verifying it against its source, running the converter and removing
temporary copies are the driver's work and happen before step 1; Autobook sees
only the OFX file. It checks that file for consistency and its own work for
correctness.

## 6.3 Deciding one row

The cascade for one row — rules, then k-nearest-neighbour (kNN) search, then the
large language model (LLM) tail — after the structural checks:

```
out_of_scope?             → disposition out_of_scope, stop
transfer?                 → match_existing in the source account (side booked
                            in an earlier batch); else the canonical side of a
                            pair in this batch; else queue "pending transfer"
                            if the counterpart is pending; else book it from
                            this side and record it in transfers_pending; stop
creditor-ID rule fires?   → account or split spec, method=rule
document-keyed rule fires? → account or split spec, method=rule
ambiguity flag?           → the row stays `?` whatever proposes below
memo-pattern rule fires?  → account or split spec, method=rule
kNN: distance ok AND margin ok?
                          → account, method=knn
LLM enabled?              → constrained call, validated against the live
                            account list, method=llm, always `?`
otherwise                 → queue
```

Tiers follow the precedence table in section 5.2 (proposal 0002 §5.1).

Then: a target account that is not open in the ledger on the line's date, a
currency that the account's `open` directive does not allow, or confidence below
threshold → `queue`. Before any `create`, the row's **source** account is
searched within ±5 days for a posting of the same amount and currency in an entry that
is not already claimed for that source account: unique → `match_existing`;
ambiguous → `queue`. An entry is **claimed for a source account** when
another staged row of that account, still pending, approved or applied, created
it or matched it; a row's own `matched_entry` never excludes its own candidate,
and a rejected or skipped row releases its claim. An `autobook-id` (the metadata
key under which a created entry holds its proposal ID) does not by itself
exclude an entry: the second side of a transfer matches the entry the first
side created. A hand-written entry is identified by its **content hash**. The content hash covers the entry's date, flag, payee,
narration, tags, links and postings, not its metadata or position, and is how
Autobook identifies an entry it did not write (§8.2). Whether the user has
asserted a balance since is not a filter. Finally the row is pre-marked `a` only
if it passed every gate, came from a tier allowed to pre-mark (not an
ambiguity-flagged row, not a rule with `auto: false`, not the LLM before its
precision is measured), and is not queued.

A payment whose parts change every period — a loan instalment's interest and
principal — cannot be split from the statement line and is queued. If the user
writes that entry by hand, a later run resolves the line as `match_existing`
(§8.1).

## 6.4 Linking bills (proposal 0002)

Once per batch, after correlation and before classification:

1. Query paperless for bill and credit-note documents (document types from
   configuration) whose created date falls in the batch's date range widened by
   the window. Paperless's `created` is the first date found in the text from optical character recognition (OCR), so
   the window must allow for it.
2. Drop duplicate documents with the same `original_checksum`; paperless accepts
   duplicates by default.
3. For every row, collect candidate bills: exact amount and sign, date in window,
   a confirmed correspondent association, not already linked in staging.
4. Keep only one-to-one pairs. Everything else is unlinked.
5. A bill without a correspondent (or whose correspondent has no confirmed association) that would otherwise pair is recorded as
   `doc_match = weak`: a hint line in the review file, never input to a rule.
6. Record `doc_id`, `doc_match`, `doc_candidates` on the row.

Unlinked rows continue exactly as if documents did not exist.

A link changes no amount, date or account. When a linked row is applied as a
`create`, the entry carries the document's URL as `autobook-doc` metadata
(§10.2). On a `match_existing` row nothing is written to the ledger; the link
stays in staging only.

## 6.5 Applying a batch, and recovering from a crash

`autobook apply --from FILE` first takes the writer lock (step 0), recovers any
journal and checks the kept pre-images (see *Recovery*), and only then does what
`decide` does (6.1, step 5) and books the approved rows (§10.3). A run that
cannot take the lock, or refuses in recovery or the pre-image check, changes
nothing, staging included. A batch is booked
whole or not at all.

0. **Lock.** Take the writer lock, an advisory lock on a file beside the staging
   store. It is held until staging is updated at the end. If another Autobook
   run holds it: exit 4, nothing written.
1. **Read.** Load the ledger: its errors, the accounts, the existing Autobook
   IDs, and the SHA-256 of every loaded file. The owned file must be among
   them, and its root-name options (`name_assets` … `name_expenses`) must match
   the main file's, and every kept pre-image must still have its recorded hash
   (a changed one is a displaced save). Otherwise: exit code 4, nothing
   written.
2. **Filter.** Drop `create` rows whose proposal ID is already in the ledger.
   Only a value in `autobook-id` that matches the proposal-ID pattern counts.
   Drop `match_existing` rows that already have an `applied_entry` still
   present in the ledger. A matched row approved for the first time has only a
   `matched_entry` and goes on to step 3.
3. **Check each row.** Both accounts are open on its date; its currency is
   declared on the source account and allowed on the other; its postings are in
   whole cents and sum to exactly zero; no posting but the source posting is in
   the source account. For a matched row, the search is run
   again: exactly one candidate must remain, the row's `matched_entry`, in an account
   with no orphaned claim. A row the user rebound (proposal 0005 §8.2) must
   instead have its recorded entry pass the predicate, unclaimed by another row. A row that fails is queued, and the batch goes on without it.
   **A batch with no created rows** (only matched rows) writes nothing: steps
   4 and 5 are skipped, no journal or pre-image is made, and the ledger is
   loaded again and steps 6 and 7 run against that fresh load, immediately
   before staging is updated — the search must still find each row's
   `matched_entry`, and no ledger file and no kept pre-image may have changed
   since step 1. A failure marks nothing applied; there is nothing to restore.
4. **Render** the entries. Every posting carries an explicit amount, built from
   integer cents and printed with two decimals. The new content is the current
   owned file plus the entries.
5. **Compare, then replace.** Hash every file again, the kept pre-images
   included. If any differs from step
   1, stop: exit code 4, nothing written. Otherwise write the batch journal and
   make it durable (see *Recovery*), then write a temporary file in the same
   directory, `fsync` it, **exchange** it with the owned file in one atomic
   step (`renameat2` with `RENAME_EXCHANGE`), check that what was swapped out
   is exactly the content the batch was rendered from (otherwise exchange back,
   so the saved edit is in place again, and exit 4), and `fsync` the
   directory. The journal keeps the
   previous content until step 7 has passed and staging is updated.
6. **Read back.** Load the ledger again.
   - Every **created** row's proposal ID appears exactly once, with the
     approved date, accounts and amounts.
   - A **matched** row wrote nothing, so its ID is not looked for. Its recorded
     entry must still be present, and the search, run again, must still find
     exactly one candidate: that entry.
7. **Assert.**
   - The load reports no error that step 1 did not report.
   - No byte of the owned file before the appended entries changed, and no
     other file changed.
   - Every kept pre-image, this batch's included, still has its recorded hash.
     This is the last check before the rows are marked applied; a mismatch is
     a save that got into an old file and rolls the batch back.
   - The balance of every account the batch wrote postings to moved by exactly
     the sum of those postings, and no other account's balance moved. A matched
     row writes no posting and moves nothing.
   - Where the statement states a closing balance: the ledger's balance in the
     staged balance currency at the end of the staged closing-balance date (the
     OFX `LEDGERBAL` as-of date, not necessarily the period end) equals it, minus the statement's lines not yet applied
     (queued, out of scope, pending transfer). A matched line counts as applied
     only if its matched posting is dated on or before that date.
8. **On any failure in 6 or 7,** restore the previous content — only if the
   owned file still holds exactly what step 5 wrote — exit with code 6, and
   mark nothing applied.
   The restore is the checked exchange back; afterwards the pre-image path
   holds the rejected batch, and staging records it as such (`preimages.kind
   = rejected`, with that content's hash), so it is kept like any other
   displaced version but is not mistaken for a displaced save.

The writer reports `{proposal_id, entry, status}` per row and the assertion
results per batch (the `apply-out` contract, section 5.1). A row is `applied`
in staging only after step 7 has passed. Only then is `applied_entry` set: for a created row
the proposal ID, for a matched row the `matched_entry` found at proposal. Nothing is
written to a matched entry.

Two details of the checks:

- Autobook checks the zero sum itself because Beancount's own check is
  tolerant: it accepts a difference of half the last printed digit.
- A ledger that already has errors can still be booked into. Only a *new* error
  rolls a batch back.

**Recovery (§10.4).** The ledger and staging are two stores with no shared
transaction. A crash before the exchange in step 5 leaves the ledger untouched,
and the whole batch is re-run. A crash between "file replaced" and "marked
applied in staging" leaves the created entries in the owned file, each with its
proposal ID in `autobook-id`; a later run finds them by ID and drops them at
step 2, so nothing is created twice. Matched rows are found by their staged
entry, verified in the ledger.

Finding a batch's IDs in the ledger proves the entries are present, not that
the batch passed its checks. So the writer keeps a **batch journal** beside the
staging store. It holds everything steps 6 and 7 compare against: the batch and
its proposal IDs, the SHA-256 of every loaded file from step 1, the SHA-256 of
the owned file after the replace, the owned file's previous content, the path
of the temporary file (which holds the swapped-out content after the exchange),
the errors the first load reported, and the first load's balance of every
account. It is removed only after staging is updated. The staging
transaction that marks the rows also records the batch as committed
(`batches`); a journal found for a committed batch is only cleaned up, never
validated or rolled back again. `propose`, and a `decide` that would record a
decision, refuse while a journal exists.

**Durability.** A journal that can be lost while the exchange survives is no
journal. The order is: write the journal and `fsync` it and its directory;
write the rendered content to a scratch file (`.autobook-tmp-<ULID>`) and
`fsync` it; rename it to its final pre-image name, which the journal records,
and `fsync` the owned file's directory — so the final name only ever holds the
complete rendered content; exchange; `fsync` the owned file's directory again.
A scratch file left by a crash holds only content Autobook rendered and never
reached the ledger, so recovery removes it. The journal's removal is likewise followed by an `fsync` of its
directory, after staging has committed.

Every `propose`, `apply` and `undo` first looks for a journal, under the writer lock. `propose` refuses (exit 4) while one exists, so it never classifies against an unvalidated batch; `apply` and `undo` recover it. Every `apply` and `undo` first looks for a journal, under the writer lock:

- The owned file has the journal's *before* hash: either the exchange never
  happened, or the batch was exchanged back after a failed check. Before the
  journal is discarded, the file at the journal's pre-image path, if it
  exists, is checked: if it holds exactly the content the batch rendered (the
  journal's *after* hash), it is recorded in staging (`kind = rejected`). If it
  holds anything else, an editor saved into it: Autobook records nothing,
  keeps the journal and the file, and exits with code 4 for the user to
  resolve. It is never deleted. Then the batch is applied from the start.
- It has the *after* hash: the batch was written and never validated. First
  the swapped-out file at the journal's temporary path is checked. If it is
  not the owned file's previous content, a save got in just before the
  exchange: Autobook exchanges back, so the saved edit is at the owned path
  again, marks nothing applied and exits with code 4. Only if it is the
  previous content do steps 6 and 7 run, against the journal's baseline and not against the ledger as
  it stands: the other files' hashes, the errors and the balances are the
  journal's. If they pass, the rows are marked applied. If they fail — also
  because another ledger file changed in the meantime, so that the batch can
  no longer be validated — the previous content is restored (exit 6) and the
  batch can be applied again.
- It has neither: someone changed the file since. Autobook touches nothing,
  marks nothing applied and exits with code 4; `autobook status` shows the
  interrupted batch for the user to resolve.

A row is therefore never `applied` without having passed the read-back and the
assertions, also after a crash.

`autobook status` reports where the two stores disagree in ways a re-run does
not settle: Autobook entries that differ from what staging recorded (the user
corrected one), and proposal IDs that staging holds as applied but the ledger
no longer contains. Both are reports, never writes. A missing entry is not
silently created again.

## 6.6 A trial run (scenario 1)

Read-only towards the ledger, and may run at any time, also while the ledger is
open in an editor or in Fava (the reader then sees the files as last saved).
Export the corpus with `autobook export` (or use a cached export) and run the
**rolling-origin** backtest: for each month m, build the indices from the rows
before m and test on month m. Report precision and coverage per method and per
confidence band, stratified by memo seen before versus novel, with token-Bayes
as the negative control; gate thresholds are set on the novel stratum.
Leave-one-out is computed only as an upper bound. The command is

```
python -m autobook.pipeline.trial backtest --corpus <corpus.json> --out <report.json> \
    --max-distance <x> --min-margin <y> [--normaliser-dir <dir>]
```

This is the implemented entry point. The design lists the same backtest as
`autobook trial backtest` (section 5.5).

`--max-distance` and `--min-margin` have no default: thresholds are a human
decision on the report, never a default of the tool. `--normaliser-dir` is passed
to `normaliser.load`; omitted, the default user directory applies. A corpus file
that is not a valid `corpus` contract, an unreadable file, a refused normaliser
profile, thresholds or a row that the kNN index refuses, or a report that cannot
be written gives a one-line message on stderr, exit code 2 and no report; success
writes the JSON report and exits 0. The message names the kind of error and, at
most, the corpus field or the threshold it was raised at
(`corpus.rows[3].amount_cents`, `max_distance`), never the error's own text: that
quotes the refused value (an amount, a date) or a profile path. A refused
normaliser profile gets no location at all: its location is a path the user
chose. The rule builder, rule mining (proposal 0004), pack
validator and linkage backtest are the same machinery applied to a candidate
rule, the user's history, a pack, or bill links. A successful trial records, with
`autobook trial accept`, the version tuple that production will require.

## 6.7 Undoing a batch

Every entry a batch created carries its proposal ID in `autobook-id`.
`autobook undo BATCH` removes an entry only if its `autobook-id` is the proposal
ID of a staged row of that batch with disposition `create` or `create_split`
**and** the entry is in the owned file — both asserted before each removal
(§10.5). It removes exactly that entry's lines and regenerates nothing, so
entries added to the owned file afterwards stay as they are.

The command asks for confirmation unless `--yes` is given. An entry the user
edited after the batch is still removed; its differences are listed before the
confirmation.

For a `match_existing` row undo changes staging only: nothing was ever written
to the matched entry. Undo goes through the same journal, compare-then-replace
and restore-on-failure as 6.5, with its own read-back: the removed proposal IDs
are absent, no new load error, the owned file is the previous content minus
exactly the removed spans, no other file changed, and balances moved by exactly
minus the removed postings. The journal records the operation, so recovery of
an interrupted undo runs these checks, never apply's, and never marks a row
applied. On success it removes any paperless stamps the batch wrote and
returns the rows to `pending`.

Undo refuses (exit code 4) while a row outside the batch that is `pending`,
`approved` or `applied` has a `matched_entry` equal to the proposal ID of an
entry it would remove — the second side of a transfer matched to the entry this
batch created — and names those rows; they are undone or rejected first
(proposal 0005 §10.5). It never touches any other entry or any other
file.

## 6.8 Refusal

A refusal writes nothing — not to the ledger, and no row is marked applied —
and gives the specific reason on standard error and in the `--json` output.
There are two kinds:

| Exit code | Refused by | Example reasons |
|-----------|------------|-----------------|
| 3 | The batch gate or the version gate (section 5.2) | "coverage fell from 92% to 61%", "paperless unreachable", "rule file changed since last trial" |
| 4 | The writer's preconditions (6.5, steps 1 and 5) | the owned file is not included by the main file; its root-name options differ from the main file's; a ledger file changed during the run |

Proposals stay pending. Notifying the user is the driver's job; Autobook only
exits with the code and the reason.

There is no application to open afterwards and nothing to unblock: the ledger
is text files and stays usable throughout. The user can write entries by hand,
run a trial to re-validate (6.6), or fix the cause and rerun. The ledger is
never hostage to the classifier.

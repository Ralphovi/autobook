---
created: 14.10.2026 23:50
type: architecture
status: living
tags:
  - architecture
  - runtime
---
# 6. Runtime view

> Living document. Diagram source for 6.1:
> [`diagrams/booking-run-sequence.mermaid`](diagrams/booking-run-sequence.mermaid).

## 6.1 An interactive booking run

The user starts the launcher instead of GnuCash. The launcher backs up the book,
has the book process's exporter export the corpus, chart of accounts (CoA),
existing Autobook IDs, match candidates and scheduled-transaction (SX)
definitions in a read-only session, and runs the pipeline. The pipeline admits
new statements, normalises, dedups, correlates transfers, links bills, classifies
and assigns dispositions — correlation and bill linking before classification —
then lets the batch gate decide whether anything may be written.

If the gate refuses, the user is notified and GnuCash opens anyway; proposals
stay pending. Otherwise the review file opens in `$EDITOR`, with the gated rows
pre-marked `a` and the rest `?`. On save the pipeline parses it strictly by ID.
Every row marked `a` in the saved file is approved, exactly as shown; nothing
else is. The book process applies the approved rows in one write session,
saves, runs the assertions and confirms them by read-back, and GnuCash opens.

Until the applier exists (build step 5) the run ends at the review file: saving
it records the decisions to staging and writes nothing, so shadow mode is the
default state.

At no point are the book process and the GUI running at once, which is the
entire locking strategy.

## 6.2 Admitting a statement

1. The statement source lists candidates not yet in `statements`.
2. For a paperless statement: fetch metadata, document version and original
   checksum, download the original with `?version=` to `$XDG_RUNTIME_DIR` (mode
   `0600`), verify the checksum. For a file: compute its checksum.
3. Run the mapped plugin. If statements arrive as PDFs — the statement form is
   **[OPEN]** until D0 — a scanned PDF without a text layer is rejected.
4. Balance check where balances exist: lines sum exactly to closing minus
   opening, in cents.
5. Assign row keys, each including `source_account`; apply the period-overlap
   rule, matching lines count-aware.
6. Record the statement with status `admitted`; stage its rows. Remove the
   temporary file in `finally`.

Any failure in 2–5 rejects that statement only and records it with status
`rejected` and the reason.

## 6.3 Deciding one row

The cascade for one row — rules, then k-nearest-neighbour (kNN) search, then the
large language model (LLM) tail — after the structural checks:

```
out_of_scope?             → disposition out_of_scope, stop
on an SX occurrence?      → match_existing if the instance exists,
                            else queue "awaiting scheduled transaction", stop
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
LLM enabled?              → constrained call, validated against CoA,
                            method=llm, always `?`
otherwise                 → queue
```

Tiers follow the precedence table in section 5.2 (proposal 0002 §5.1).

Then: target account absent from the live CoA, a commodity mismatch with the
source account, or confidence below threshold → `queue`. Before any `create`, the
row's **source** account is searched within ±5 days for a transaction of the
same amount that Autobook has not already claimed: unique → `match_existing`;
ambiguous → `queue`. Finally the row is pre-marked `a` only if it passed every
gate, came from a tier allowed to pre-mark (not an ambiguity-flagged row, not a
rule with `auto: false`, not the LLM before its precision is measured), and is
not queued.

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

## 6.5 Applying a batch, and recovering from a crash

1. Open `SESSION_NORMAL_OPEN`. On `ERR_BACKEND_LOCKED`: write nothing, notify,
   and let GnuCash open. (Deferring and retrying in unattended runs is
   **[DEFERRED]** with the unattended profile.)
2. Read the Autobook IDs in `num` (values matching the proposal-ID pattern only);
   drop `create` rows whose proposal ID is present. Drop `match_existing` rows
   whose staged `applied_tx_guid` is verified in the book.
3. For each remaining row, inside `BeginEdit` / `CommitEdit`: create with the
   proposal ID in `num` and `GncNumeric(cents, 100)` amounts after the commodity
   check; or, for `match_existing`, write only the document link, if one is
   given and none exists.
4. After the last `CommitEdit`, `session.save()`.
5. Run the post-apply assertions.
6. `session.end()` in `finally`.
7. Read back: XML — reopen `SESSION_READ_ONLY` and find each ID; SQL — an engine
   query. Report `{proposal_id, tx_guid, status}` per row; only confirmed rows
   are `applied`.

Recovery depends on the backend. With XML nothing persists until `save()`: a
crash before it leaves the book untouched and the whole batch is re-run. With
SQL each `CommitEdit` is durable: a crash anywhere between "committed to book"
and "marked applied in staging" leaves created transactions in the book with
their ID in `num`, and the next run drops them at step 2. Matched rows are found
by their staged GUID, verified in the book. Staging is reconciled from
`apply-out` or a fresh `existing` export.

## 6.6 A trial run (scenario 1)

Read-only end to end, and may run with GnuCash open (an XML export then sees
the last saved state). Export the corpus (or use the cached export) and run the
**rolling-origin** backtest: for each month m, build the indices from the rows
before m and test on month m. Report precision and coverage per method and per
confidence band, stratified by memo seen before versus novel, with token-Bayes
as the negative control; gate thresholds are set on the novel stratum.
Leave-one-out is computed only as an upper bound. The rule builder, pack
validator and linkage backtest are the same machinery applied to a candidate
rule, a pack, or bill links. A successful trial records the version tuple that
production will require.

## 6.7 Undoing a batch

Every transaction a batch created carries its proposal ID in `num`. Undo is a
book-process command that deletes only transactions whose GUID is in staging
with disposition `create` **and** whose `num` equals that row's proposal ID —
both asserted before each delete. For a `match_existing` row it removes only
the document link the batch added; no FITID stamp or `num` was ever written
there. It then saves and reads back as in 6.5, removes any paperless stamps the
batch wrote, and returns the rows to `pending`. It never touches any other
transaction.

## 6.8 Refusal

A batch-level refusal writes nothing, notifies with the specific reason
("coverage fell from 92% to 61%", "paperless unreachable", "rule file changed
since last trial"), and opens GnuCash. The user can book by hand, run a trial to
re-validate, or fix the cause and rerun. Books are never hostage to the
classifier.

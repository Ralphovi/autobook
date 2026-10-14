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

The user starts the launcher instead of GnuCash. The launcher backs up the book
(file backends), has the book process export the corpus, chart of accounts and
existing IDs in a read-only session, and runs the pipeline. The pipeline admits
new statements, normalises, dedups, correlates transfers, links bills, classifies
and assigns dispositions, then lets the batch gate decide whether anything may
be written.

If the gate refuses, the user is notified and GnuCash opens anyway; proposals
stay pending. If rows need a decision, the review file opens in `$EDITOR`. On
save the pipeline parses it strictly by ID, the book process applies approved
rows in one write session and runs the assertions, and GnuCash opens.

At no point are the book process and the GUI running at once, which is the
entire locking strategy.

## 6.2 Admitting a statement

1. The statement source lists candidates not yet in `statements`.
2. For a paperless statement: fetch metadata and original checksum, download the
   original to `$XDG_RUNTIME_DIR` (mode `0600`), verify the checksum.
3. Run the mapped plugin. A scanned PDF without a text layer is rejected.
4. Balance check where balances exist: lines sum exactly to closing minus
   opening, in cents.
5. Assign row keys; apply the period-overlap rule.
6. Record the statement; stage its rows. Remove the temporary file in `finally`.

Any failure in 2–5 rejects that statement only and records why.

## 6.3 Deciding one row

```
out_of_scope?            → disposition out_of_scope, stop
correlated transfer?     → transfer from canonical side, stop
rule fires?              → account or split spec, method=rule
kNN: distance ok AND margin ok?
                         → account, method=knn
LLM enabled?             → constrained call, validated against CoA, method=llm
otherwise                → queue
```

Then: target account absent from the live CoA, amount or currency mismatching the
source, or confidence below threshold → `queue`. A matching unreconciled
transaction in the target account within ±5 days, unique → `match_existing`;
ambiguous → `queue`.

## 6.4 Linking bills (proposal 0002)

Once per batch, after correlation and before classification:

1. Query paperless for bill and credit-note documents whose created date falls in
   the batch's date range widened by the window.
2. For every row, collect candidate bills: exact amount and sign, date in window,
   compatible correspondent, not already linked in staging.
3. Keep only one-to-one pairs. Everything else is unlinked.
4. Record `doc_id`, `doc_match`, `doc_candidates` on the row.

Unlinked rows continue exactly as if documents did not exist.

## 6.5 Applying a batch, and recovering from a crash

1. Open `SESSION_NORMAL_OPEN`. If locked: interactive runs abort and notify;
   unattended runs exit 0 as deferred and escalate after repeated deferrals.
2. Read all `num` values; drop approved rows whose proposal ID is present.
3. For each remaining row, inside `BeginEdit` / `CommitEdit`: create with
   integer-cent `GncNumeric` amounts, or link for `match_existing`; set the
   document link if given and none exists.
4. Run assertions; report `{proposal_id, tx_guid, status}` per row.
5. `session.end()` in `finally`.

A crash anywhere between "committed to book" and "marked applied in staging"
leaves the transaction in the book with its ID in `num`. The next run drops it at
step 2 and staging is reconciled from `apply-out` or a fresh `existing` export.

## 6.6 A trial run (scenario 1)

Read-only end to end. Export the corpus (or use the cached export), build the
indices, run leave-one-out over every row, and report precision and coverage per
method and per confidence band, with token-Bayes as the negative control. The
rule builder and pack validator are the same machinery applied to a candidate
rule or pack. A successful trial records the version tuple that production will
require.

## 6.7 Undoing a batch

Every transaction a batch created carries its proposal ID in `num`. Undo is a
book-process command that deletes exactly those transactions (and, for
`match_existing`, removes only the link and FITID stamp it added), removes any
paperless stamps the batch wrote, and returns the rows to `pending`. It never
touches transactions without an Autobook ID.

## 6.8 Refusal

A batch-level refusal writes nothing, notifies with the specific reason
("coverage fell from 92% to 61%", "paperless unreachable", "rule file changed
since last trial"), and opens GnuCash. The user can book by hand, run a trial to
re-validate, or fix the cause and rerun. Books are never hostage to the
classifier.

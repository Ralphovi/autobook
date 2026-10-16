---
created: 14.10.2026 23:50
type: architecture
status: living
tags:
  - architecture
  - crosscutting
---
# 8. Cross-cutting concepts

> Living document. The binding form of most of these rules is
> [`AGENTS.md`](../../../AGENTS.md); this section explains how they fit together.

## 8.1 Money

Amounts are **integer cents** from the moment a plugin's value is parsed to the
moment the book process builds a `GncNumeric(cents, 100)`. Decimal strings from
statements and from paperless's monetary fields are parsed with `Decimal` and
converted once. No float exists on any monetary path, including tests and
fixtures. The hazard in the bindings is the `GncNumeric(float)` constructor
(they expose no `from_double`); it is never called with a float. Fixed amounts
in rules are integer cents too (`cents: 1250`, not `value: 12.50`). Every split
specification must sum exactly to the transaction total or the row fails; the
difference never goes to Imbalance.

Currency is read, never assumed, and never hard-coded. The book process takes
the source account's commodity and verifies that both accounts share it and
that its fraction is 100 before building `GncNumeric(cents, 100)`; a row that
fails the check is not written. A row whose split would be denominated in a
currency other than its account's is `out_of_scope`.

## 8.2 Idempotency and failure granularity

There are two stores (book and staging) and no distributed transaction between
them. Idempotency comes from the book side. Each staged row has a **proposal
ID** (`AB-` plus a ULID), distinct from its staging key. It is written to `num`
only on transactions Autobook creates, and every apply begins by dropping IDs
already present; only values matching `^AB-[0-9A-HJKMNP-TV-Z]{26}$` count.
A `match_existing` row writes no `num` and no FITID stamp: staging records the
matched GUID, and a re-run verifies that GUID in the book. A row counts as
applied only after `session.save()` and a read-back. Any batch can be re-run
after any failure, and any batch can be undone: undo deletes a transaction only
when its GUID is staged as `create` **and** its `num` equals that row's
proposal ID.

Failures are classified by granularity and never mixed:

| Tier | Examples | Effect |
|------|----------|--------|
| Statement | Parse error, failed balance check, overlap mismatch, no text layer | That statement is rejected; others proceed |
| Row | Low confidence, account missing from the chart of accounts (CoA), ambiguous `match_existing`, split sum mismatch, commodity check failed, awaiting a scheduled transaction, pending transfer | That row is queued; the batch proceeds |
| Batch | Coverage drop, spike in large-language-model (LLM) fallbacks, unusual target accounts, parse errors above a small count, version tuple changed, paperless unreachable, changed statement checksum | Nothing is written; notify; GnuCash still opens |

A failed post-apply assertion is the one batch-level failure that arrives after
`session.save()`: the batch is already in the book, so it is flagged, notified and
undone (section 6.7).

A per-row problem that halts a batch, or a batch-level problem that still writes,
is a defect.

## 8.3 Evidence, provenance and versions

**Every proposal is explainable.** It records method (`rule | knn | llm`), the
rule ID or the neighbour distances and vote shares, any linked document, and the
versions that produced it.

**The corpus has provenance.** Rows are `observed` (from the book export, which
yields nothing else) or `corrected` (review decisions, read from staging).
Index construction refuses (raises on) any row that is not `observed` or
`corrected`; there is no path by which a synthetic row can enter.

**Thresholds have evidence.** Distance cutoffs, vote margins, confidence bands
and the bill-matching window are set from rolling-origin backtest and
shadow-mode data across the corpus — gate thresholds on the stratum of novel
memos — never adjusted to fix one transaction. A threshold that pre-marks LLM
rows needs shadow-mode precision for `method=llm` first.

**The version gate.** A successful trial records the tuple: rule-file hash,
normaliser version, k-nearest-neighbour (kNN) index version, prompt version,
model ID and model configuration (temperature pinned to 0), ofxstatement plugin
versions, statement-source mapping, paperless version, correspondent-association
hash, the bill date window, and the configured bill and credit-note document
types. Production refuses to write if the current tuple differs from the last
validated one.

## 8.4 Normalisation is data, and lives in one place

Plugins convert formats and preserve the raw memo. All normalisation happens in
Autobook, driven by per-source-account profiles loadable from a user directory.
That is what lets normalisation — the thing tuned most — be changed and
re-backtested without touching any plugin, and lets a new bank's profile ship as
data.

## 8.5 Privacy and the redaction boundary

- The model adapter accepts a normalised merchant token, amount and sign. Raw
  memos, IBANs and document content cannot be passed to it. The account list
  crosses as **numeric indices**, mapped back locally; account names never
  leave the machine, because names like `Kirchensteuer` are Art. 9 data
  themselves.
- The default backend is **local**. A remote backend is opt-in, and then
  receives a token only if it matches a rule-pack entry or the user's allowlist
  of business names; otherwise the LLM abstains and the row is queued. Novel
  counterparties are disproportionately doctors and lawyers, which is why an
  unknown token never leaves.
- Documents are read as metadata; staging stores document IDs, amounts and dates,
  never content or correspondent names. Names are resolved for display when the
  review file is generated.
- Logs carry IDs, counts and versions, never memos or amounts tied to
  counterparties.
- The review file is written to `$XDG_RUNTIME_DIR/autobook/review.txt`, mode
  `0600`, and removed in `finally`; never `/tmp`. Downloaded statement originals
  follow the same rule.
- User rules and correspondent associations are personal data in a separate file
  from anything shippable. Packs carry pattern → category and ambiguity flags
  only; counterparty IBANs never enter one, creditor IDs may.
- Fixtures are synthetic or taken from published format documentation.

## 8.6 Backend neutrality

Everything that inspects a book — idempotency, Imbalance, balances, lock state,
match candidates — goes through the engine API. SQL against a book is never used,
because it does not exist for XML users and bypasses the engine's logic. Backups
are file copies where the backend is a file, `pg_dump` for PostgreSQL when it is
on `PATH`, and a warning otherwise; the real safety net is batch reversibility
by proposal ID.

## 8.7 Defer to the incumbent

When a job belongs to an existing tool, Autobook detects the need, hands off and
verifies the result:

| Job | Owner | Autobook's part |
|-----|-------|-----------------|
| Recurring fixed bookings | GnuCash Scheduled Transactions | Detect candidates; after the user creates them, show that rows now resolve as `match_existing`. The exporter exports the scheduled-transaction definitions, because GnuCash creates the instances at GUI start-up, after the apply: a row on an occurrence matches the instance or waits for it, and is never created |
| Loans | GnuCash Mortgage & Loan Repayment Assistant | Detect loan-shaped payments |
| Chart of accounts | GnuCash New Account Hierarchy Assistant | Point at it for empty books |
| Reconciliation | The user, in GnuCash | Never set the reconciled flag |
| Optical character recognition (OCR), correspondents, bill fields | paperless-ngx | Read the results; verify totals against bank amounts |

Assistants are referenced by name with a link to the versioned manual, never by
hardcoded menu path. Suggestions are thresholded and dismissible.

## 8.8 Configuration and secrets

TOML in `$XDG_CONFIG_HOME/autobook/`, mirroring GnuCash's own layout. Secrets in
the Secret Service. Every configuration value that can change a classification is
part of the version tuple.

The normaliser reads its user profiles and the `accounts.toml` that maps source
accounts to profiles from `$XDG_CONFIG_HOME/autobook/normaliser/` (or
`~/.config/autobook/normaliser/` when `XDG_CONFIG_HOME` is unset, empty or not
absolute); section 5.2 has the file formats and the override rule. They reach the
version tuple through the normaliser version, a digest of the effective profiles,
the mapping and the Unicode version.

## 8.9 Documentation currency

A change that adds or alters a CLI flag, configuration key, JSON contract field,
staging column or disposition updates this architecture description in the same
PR, from the first PR on. Decisions that settle arguments become ADRs; plans are
proposals.

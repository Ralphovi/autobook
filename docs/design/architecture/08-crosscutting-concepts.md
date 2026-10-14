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
fixtures; `GncNumeric.from_double` is never used. Every split specification must
sum exactly to the transaction total or the row fails; the difference never goes
to Imbalance.

Currency is read, never assumed. A row whose split would be denominated in a
currency other than its account's is `out_of_scope`.

## 8.2 Idempotency and failure granularity

There are two stores (book and staging) and no distributed transaction between
them. Idempotency comes from the book side: the proposal ID is written to the
transaction's `num`, and every apply begins by dropping IDs already present. Any
batch can be re-run after any failure, and any batch can be undone by deleting
exactly its IDs.

Failures are classified by granularity and never mixed:

| Tier | Examples | Effect |
|------|----------|--------|
| Statement | Parse error, failed balance check, overlap mismatch, no text layer | That statement is rejected; others proceed |
| Row | Low confidence, account missing from CoA, ambiguous `match_existing`, split sum mismatch | That row is queued; the batch proceeds |
| Batch | Coverage drop, LLM-fallback spike, unusual target accounts, parse errors above a small count, version tuple changed, paperless unreachable, failed assertions, changed statement checksum | Nothing is written; notify; GnuCash still opens |

A per-row problem that halts a batch, or a batch-level problem that still writes,
is a defect.

## 8.3 Evidence, provenance and versions

**Every proposal is explainable.** It records method (`rule | knn | llm`), the
rule ID or the neighbour distances and vote shares, any linked document, and the
versions that produced it.

**The corpus has provenance.** Rows are `observed` (from the book) or `corrected`
(from review decisions). Index construction filters on provenance; there is no
path by which a synthetic row can enter.

**Thresholds have evidence.** Distance cutoffs, vote margins, confidence bands
and the bill-matching window are set from backtest and shadow-mode data across
the corpus, never adjusted to fix one transaction.

**The version gate.** A successful trial records the tuple: rule-file hash,
normaliser version, kNN index version, prompt version, model ID and model
configuration, ofxstatement plugin versions, statement-source mapping, paperless
version, correspondent-association hash. Production refuses to write if the
current tuple differs from the last validated one.

## 8.4 Normalisation is data, and lives in one place

Plugins convert formats and preserve the raw memo. All normalisation happens in
Autobook, driven by per-source-account profiles loadable from a user directory.
That is what lets normalisation — the thing tuned most — be changed and
re-backtested without touching any plugin, and lets a new bank's profile ship as
data.

## 8.5 Privacy and the redaction boundary

- The model adapter accepts a normalised merchant token, amount and sign. Raw
  memos, IBANs and document content cannot be passed to it.
- Documents are read as metadata; staging stores document IDs, amounts and dates,
  never content or correspondent names. Names are resolved for display when the
  review file is generated.
- Logs carry IDs, counts and versions, never memos or amounts tied to
  counterparties.
- The review file is written under `$XDG_RUNTIME_DIR`, not `/tmp`.
- User rules and correspondent associations are personal data in a separate file
  from anything shippable. Packs carry pattern → category and ambiguity flags
  only; counterparty IBANs never enter one, creditor IDs may.
- Fixtures are synthetic or taken from published format documentation.

## 8.6 Backend neutrality

Everything that inspects a book — idempotency, Imbalance, balances, lock state,
match candidates — goes through the engine API. SQL against a book is never used,
because it does not exist for XML users and bypasses the engine's logic. Backups
are file copies where the backend is a file, and a warning otherwise; the real
safety net is batch reversibility by `num`.

## 8.7 Defer to the incumbent

When a job belongs to an existing tool, Autobook detects the need, hands off and
verifies the result:

| Job | Owner | Autobook's part |
|-----|-------|-----------------|
| Recurring fixed bookings | GnuCash Scheduled Transactions | Detect candidates; after the user creates them, show that rows now resolve as `match_existing` |
| Loans | GnuCash Mortgage & Loan Repayment Assistant | Detect loan-shaped payments |
| Chart of accounts | GnuCash New Account Hierarchy Assistant | Point at it for empty books |
| Reconciliation | The user, in GnuCash | Never set the reconciled flag |
| OCR, correspondents, bill fields | paperless-ngx | Read the results; verify totals against bank amounts |

Assistants are referenced by name with a link to the versioned manual, never by
hardcoded menu path. Suggestions are thresholded and dismissible.

## 8.8 Configuration and secrets

TOML in `$XDG_CONFIG_HOME/autobook/`, mirroring GnuCash's own layout. Secrets in
the Secret Service. Every configuration value that can change a classification is
part of the version tuple.

## 8.9 Documentation currency

A change that adds or alters a CLI flag, configuration key, JSON contract field,
staging column or disposition updates this architecture description in the same
PR. Decisions that settle arguments become ADRs; plans are proposals.

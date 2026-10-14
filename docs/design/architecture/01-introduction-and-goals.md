---
created: 14.10.2026 23:50
type: architecture
status: living
tags:
  - architecture
  - goals
  - requirements
---
# 1. Introduction and goals

> Living document. Describes the system **as designed** in
> [proposal 0001](../proposals/draft/0001-gnucash-auto-booking-pipeline.md) and
> [proposal 0002](../proposals/draft/0002-document-driven-booking-via-paperless.md);
> there is no implementation yet. From the first merged code onward this
> section follows the code, not the proposals. Open questions are marked
> **[OPEN]** inline.

## 1.1 What this is

GnuCash is a capable double-entry accounting system with a weak spot: getting
bank transactions into it. Its import assistant asks, transaction by transaction,
which account each line belongs to. Its Bayes matcher helps, but it only learns
during imports, never forgets an early mistake, and always returns a guess — even
for a merchant it has never seen. For a household with four or five accounts,
booking a month means a few hundred decisions in a modal dialog.

**Autobook** removes that dialog. It reads bank statements and bills from
paperless-ngx (or statement files from disk), proposes a destination account for
every bank line, and writes approved bookings into the book through GnuCash's own
engine. Most lines are decided by rules and by nearest-neighbour search over the
user's own booking history; a small residual is reviewed in a plain text file in
the user's editor. GnuCash remains the system of record and the place where
reconciliation happens.

The target is **~90–95% of transactions booked without per-transaction
interaction**. The residual is not a modelling failure: it is data a bank
statement does not contain. Linking bills (proposal 0002) recovers part of it.

## 1.2 The headline guarantee

**Autobook never writes a booking it cannot account for.** Every transaction it
creates either came from an explicit, human-committed rule, or from a
nearest-neighbour vote that passed both confidence gates, or from a human
decision in the review file — and every one carries an ID that makes it findable
and removable as part of its batch.

The corollary matters more than the guarantee: **when Autobook is unsure, it
says so and writes nothing for that row.** A silently wrong booking misreports
for years and may reach a tax filing; an unbooked row costs a minute of review.
The whole architecture is arranged so that uncertainty degrades into the review
queue, never into the ledger.

## 1.3 Quality goals

In priority order: when two pull against each other, the lower number wins. Each
goal is made measurable in section 10 and traced to a strategy in section 4.

1. **Ledger integrity.** No wrong, partial, duplicated or unattributable booking
   reaches the book. No write under a live GUI session. No account, scheduled
   transaction or reconciled flag created by code.

   The failure mode here is silent. A float rounding error, a transfer booked
   from both statements, a crash between "written" and "recorded as written" —
   none of these raise an error; they produce a ledger that looks fine and is
   wrong. That is why integrity is pursued structurally (exact money, idempotency
   by `num`, a single writer process, post-apply assertions) rather than by care.

2. **Privacy.** Financial data stays on the user's machine. What leaves for an
   optional model backend is a normalised merchant token, an amount and a sign —
   never a raw memo, a counterparty IBAN or document content.

   Bank memos and invoices carry Art. 9 special-category data: doctors, church
   tax, union dues, lawyers. A tool that leaks one of these to a cloud model, a
   log file or a shared rule pack has failed its users regardless of how well it
   books.

3. **Calibrated automation.** Maximise the share of rows booked unattended *at a
   fixed precision*, and abstain where the evidence is thin. Abstention is a
   feature: the kNN distance gate exists to say "never seen this".

   Coverage alone is the wrong target. A classifier that books 99% with 2% errors
   is worse than one that books 90% with 0.2%, because the errors are invisible
   and the abstentions are not.

4. **Auditability and reversibility.** Every proposal records which method,
   which rule or neighbours, which versions produced it. Every batch can be
   undone by ID. Every threshold traces to a backtest.

5. **Distributability.** Other GnuCash users — other banks, other locales, other
   backends — can run it without the author's setup. No-AI mode is first-class;
   paperless is optional; XML, SQLite, MySQL and PostgreSQL books all work.

## 1.4 Stakeholders and target users

- **Primary:** an individual or household already keeping books in GnuCash, with
  years of hand-booked history, on Linux. The author is the first such user.
- **Secondary:** GnuCash users in other locales who contribute normalisation
  profiles and rule packs (pattern → category data, never transactions).
- **Tertiary:** the GnuCash project itself — as recipient of bindings bug reports,
  friction notes and, eventually, small upstream patches (proposal 0001,
  *Parallel track*).

## 1.5 Scope boundaries

Autobook assigns destination accounts and writes the resulting bookings. Where
GnuCash or paperless already does a job, Autobook detects the need and defers.

- **In scope:** ingest of statements (from paperless or files), normalisation,
  dedup, transfer correlation, classification, bill linking, review, writing,
  post-apply verification, and the trial/backtest tooling that justifies every
  threshold.
- **Deferred to GnuCash:** reconciliation, chart-of-accounts creation, recurring
  bookings (Scheduled Transactions), loan amortisation.
- **Deferred to paperless-ngx:** OCR, correspondent and document-type recognition,
  extraction of bill fields.
- **Out of scope by decision:** statement acquisition from banks, mail retrieval,
  securities transactions, splits in a currency other than the account's,
  Windows (section 2), line-item splits from invoices (deferred, proposal 0002 §9).

These are catalogued with their reasons in section 11 (*Conscious exclusions*).

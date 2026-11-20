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
> [proposal 0005](../proposals/draft/0005-beancount-ledger.md), the whole system
> design.
> [Proposal 0002](../proposals/draft/0002-document-driven-booking-via-paperless.md)
> (bills from paperless) and
> [proposal 0004](../proposals/draft/0004-rules-first-mined-from-history.md)
> (rules first, mined from history) still apply, with the changes listed in
> proposal 0005's *Relation to the other proposals*. The normaliser, the kNN
> classifier and the backtest are implemented; nothing that reads or writes a
> ledger is yet. For merged code this section follows the code, not the
> proposals. Open questions are marked **[OPEN]** inline.

## 1.1 What this is

[Beancount](https://beancount.github.io/) is a double-entry accounting system
whose ledger is a set of plain-text files. Every transaction in it is written
out: a date, a description, and one posting per account touched. Getting bank
transactions into such a ledger means deciding, line by line, which account each
statement line belongs to. For a household with four or five accounts, booking a
month means a few hundred of those decisions.

**Autobook** makes most of them. It is handed bank statements as OFX files (OFX,
Open Financial Exchange, is a common statement interchange format), proposes a
destination account for every statement line, and writes approved bookings into
the ledger as transactions. Every proposal is listed in a plain text review
file. Rows decided by rules or by nearest-neighbour search over the user's own
booking history are pre-marked `a` (accept); the rest are marked `?` for the
user to decide. Saving the file is the approval.

Autobook is **not the pipeline driver**. It does not fetch statements, run
converter plugins, open an editor, or decide when to run. A separate program,
the **driver**, does that and calls Autobook's commands. The driver is its own
project in its own repository.

**The user's Beancount ledger is the system of record, and it belongs to the
user.** Autobook reads all of it and writes transactions only, into one file of
its own that the user's ledger includes — the **owned file**. It never changes
an entry it did not create. The user's own `balance` assertions remain the
independent check on everything Autobook does.

The target is **~90–95% of statement lines booked with one save of a pre-filled
review file**. The residual (rows left at `?`) is not a modelling failure: it is
data a bank statement does not contain. Linking bills (proposal 0002) recovers
part of it.

A secondary goal is that other people who keep a Beancount ledger can use it.

## 1.2 The headline guarantee

**Autobook never writes a booking it cannot account for.** Nothing reaches the
ledger that was not marked `a` in a review file the user saved, with the exact
account, amount and date shown there. A row is pre-marked `a` only when an
explicit, human-committed rule fired, a nearest-neighbour vote passed both
confidence gates, or — only after shadow mode has measured its precision — a model
proposal cleared a threshold set on that evidence; everything else waits for a human decision. Every transaction
Autobook creates carries a proposal ID, as `autobook-id` metadata on the entry,
that makes it findable and removable as part of its batch.

The corollary matters more than the guarantee: **when Autobook is unsure, it
says so and writes nothing for that row.** A silently wrong booking misreports
for years and may reach a tax filing; an unbooked row costs a minute of review.
The whole architecture is arranged so that uncertainty degrades into the review
queue, never into the ledger.

The same holds one level up: **the books must be correct at the end.** An import
with an error is rejected, not accepted. A statement is admitted whole or not at
all; a batch is booked whole or not at all; and a rejection is loud — a non-zero
exit code and the reason. The only case where a batch proceeds without a line is
a line that cannot be booked for a reason of its own (no confident account, an
account not open on its date, an ambiguous match). That line is **queued**:
shown for review, neither booked nor lost.

## 1.3 Quality goals

In priority order: when two pull against each other, the lower number wins. Each
goal is made measurable in section 10 and traced to a strategy in section 4.

1. **Ledger integrity.** No wrong, partial, duplicated or unattributable booking
   reaches the ledger. No entry that Autobook did not create is changed. No
   file but the owned file is written. No `open`, `close`, `balance`, `pad`,
   `price`, `commodity`, `plugin` or `include` directive is written by code.

   The failure mode here is silent. A float rounding error, a transfer booked
   from both statements, a crash between "written" and "recorded as written", a
   file replaced while the user was editing it — none of these raise an error;
   they produce a ledger that looks fine and is wrong. That is why integrity is
   pursued structurally (exact money, idempotency by `autobook-id`, a single
   package that imports `beancount`, a comparison of every ledger file before
   the write, a write confirmed by read-back, post-apply assertions, and the
   previous file restored on any failure) rather than by care.

2. **Privacy.** Financial data stays on the user's machine. The optional model
   backend is local by default. A remote backend is opt-in, and then receives
   only a merchant token that matches a rule-pack entry or the user's allowlist
   of business names (otherwise the model abstains and the row queues), the
   account list as numeric indices, an amount and a sign — never a raw memo, an
   account name, a counterparty IBAN or document content.

   Bank memos and invoices carry Art. 9 special-category data: doctors, church
   tax, union dues, lawyers. Account names such as `Kirchensteuer` are such data
   themselves. A tool that leaks one of these to a cloud model, a log file or a
   shared rule pack has failed its users regardless of how well it books.

3. **Calibrated automation.** Maximise the share of rows pre-marked `a` *at a
   fixed precision*, and abstain where the evidence is thin. Abstention is a
   feature: the kNN (k-nearest-neighbour) distance gate exists to say "never
   seen this".

   Coverage alone is the wrong target. A classifier that books 99% with 2% errors
   is worse than one that books 90% with 0.2%, because the errors are invisible
   and the abstentions are not.

4. **Auditability and reversibility.** Every proposal records which method,
   which rule or neighbours, which versions produced it. Every booking Autobook
   made is visible in the owned file, in an editor or in Fava. Every batch can
   be undone by ID. Every threshold traces to a backtest.

5. **Distributability.** Other Beancount users — other banks, other locales,
   other ledger layouts — can run it without the author's setup. No-AI mode is
   first-class; paperless is optional; a ledger with renamed root accounts (the
   `name_*` options) works like one with the English defaults. Because Autobook
   is not the driver, it is not tied to how one person gets statements.

## 1.4 Stakeholders and target users

- **Primary:** an individual or household already keeping a Beancount ledger,
  with booked history in it. The author is the first such user, and arrives
  with history from a GnuCash book that is converted once and then retired
  (proposal 0005 §14).
- **Secondary:** Beancount users in other locales who contribute normalisation
  profiles and rule packs (pattern → category data, never transactions).
- **Neighbour:** the driver project. It hands Autobook OFX files and depends on
  the command names, the exit codes, the `--json` output and the review file
  it passes on to the user (section 3.2). A change to any of those is a change to its interface.

## 1.5 Scope boundaries

Autobook assigns destination accounts and writes the resulting bookings. Where
the driver, the user or paperless already does a job, Autobook leaves it there.

- **In scope:** taking OFX statements and admitting them, normalisation, dedup,
  transfer correlation, classification, bill linking, review, writing,
  read-back and post-apply verification, and the trial/backtest tooling that
  justifies every threshold.
- **The driver's job:** getting a statement from the bank or from a document
  store, converting it to OFX with ofxstatement, deciding when to run, opening
  the review file in an editor, and notifying the user. Autobook never imports
  or runs ofxstatement.
- **The user's job:** the chart of accounts (`open` and `close` directives),
  balance assertions, prices, and every transaction that does not come from a
  statement line. Beancount has no recurring ("scheduled") transactions and
  Autobook does not add them: a recurring debit is an ordinary rule candidate,
  and a payment whose parts change every period, such as a loan instalment, is
  queued.
- **Deferred to paperless-ngx:** optical character recognition (OCR), correspondent and document-type recognition,
  extraction of bill fields.
- **Out of scope by decision:** statement acquisition from banks, mail retrieval,
  securities transactions, postings in a currency other than the account's
  (permanent, settled in proposal 0005 §1; revisiting needs an ADR), line-item splits from
  invoices (deferred, proposal 0002 §9; would need a new ADR, section 9).
  Statement lines of the excluded kinds still arrive; they get the disposition
  `out_of_scope` and are kept out of the coverage and drift metrics.
- **Deferred beyond v1:** booking without a person saving the review file
  **[DEFERRED]** — approval is a save of the review file, however the driver
  presents it.

These are catalogued with their reasons in section 11 (*Conscious exclusions*).

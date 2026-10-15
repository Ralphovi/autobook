# Threat model: Autobook

Reviewer-facing summary of what can go wrong, who or what causes it, and how bad each
outcome is. The design it describes is
[proposal 0001](../docs/design/proposals/draft/0001-gnucash-auto-booking-pipeline.md) as
amended by
[proposal 0002](../docs/design/proposals/draft/0002-document-driven-booking-via-paperless.md),
described in [the architecture](../docs/design/architecture/README.md); the design-level
model (assets, trust boundaries, mitigations) is
[chapter 14](../docs/design/architecture/14-threat-model.md); reporting and scope are in
[SECURITY.md](../SECURITY.md). Nothing is built yet: this file describes the design, and
each change that lands code updates it to describe the code. Where the two differ, this
file should describe what the code does today.

## What this project does

Autobook proposes the destination account for each line of a bank statement and, after
the user approves it in a review file, writes the bookings into their GnuCash book.

```
statement source ─> admission ─> normalise ─> dedup ─> correlate ─> link bills ─> classify
(paperless | files)  (checksum,              (FITID or   (transfers)  (paperless   rules → kNN
                     ofxstatement,           key +                    metadata)    → LLM (tail)
                     balance check)          overlap)                                  │
                                                                                       ▼
GnuCash book <── book process <── rows marked `a` <── review file ($EDITOR) <── staging
                 (exporter reads, applier writes)
```

- **Pipeline** (Python, no libgnucash): everything from statement to approved row. It
  stages proposals in SQLite (or PostgreSQL).
- **paperless-ngx client**: talks to the user's paperless-ngx over its REST API with a
  token from the Secret Service. It lists statements and bills, downloads statement
  originals, and, only if stamping is turned on, writes a tag and a custom field back.
- **Statement admission**: downloads a statement's original file to `$XDG_RUNTIME_DIR`
  (mode `0600`, removed in a `finally`), verifies its checksum against paperless, runs
  the mapped ofxstatement plugin on it, and applies the balance check and the
  period-overlap rule. A statement is admitted whole or rejected whole, with the reason
  recorded. Statement lines never come from OCR (optical character recognition) text, the archive version or metadata.
  The file path is the other, equally supported source and goes through the same
  admission.
- **Correlation pass**: pairs the two sides of transfers between the user's own accounts
  so each transfer is booked once.
- **Bill matcher**: links a bank row to a paperless bill only on an exact amount in
  cents, a date window and a compatible correspondent, and only when the pairing is
  one-to-one across the batch. A link changes no amount, date or account; it only makes
  document conditions available to rules and a document link available to the applier.
- **Classification cascade**: one precedence table (proposal 0002 §5.1): creditor-ID
  rules, then document-keyed rules (confirmed correspondent association, `auto: true`,
  shadow mode passed), then the ambiguity flag (forces review), then memo-pattern rules,
  then **kNN** (k-nearest-neighbours) over the user's own booking history with two abstention gates (neighbour
  distance and vote margin), then an optional **LLM** (large language model) for the tail, whose answer must be
  one non-placeholder account from the live chart of accounts that is not an Equity or
  Trading account.
- **Review file**: a plain-text file in `$EDITOR` at
  `$XDG_RUNTIME_DIR/autobook/review.txt` (mode `0600`), one row per proposal, parsed back
  by ID. Rows that passed the gates are pre-marked `a`, the rest `?`, and LLM rows are
  always `?` until shadow mode has measured them. Saving the file approves every row
  marked `a` in it.
- **Book process**: the only part that links libgnucash. The **exporter** reads the
  book in a read-only session (corpus, chart of accounts, existing transactions,
  scheduled-transaction definitions). The **applier** writes approved rows, puts the
  proposal ID in `num` on transactions it creates, saves, runs the post-apply assertions,
  and reads each row back.
- **Launcher**: backs up the book, runs the export, the pipeline, review and apply, then
  always starts GnuCash. The book process exits before the GUI opens.
- **Rule packs**: shared, locale-scoped data mapping memo patterns to semantic
  categories; loaded from bundled or third-party sources.
- **Model adapter**: OpenAI-compatible endpoint, optional, local by default. Only a
  redacted merchant token, the amount, the sign and the account list (the label space)
  cross it. A remote backend is
  opt-in and receives only tokens that match a rule-pack entry or the user's allowlist
  of business names, and the account list as numeric indices, never names.

## Who or what causes harm

Most of the harm here needs **no attacker**. A wrong booking misreports silently for
years and may reach a tax filing, so accidental causes are in scope alongside hostile
ones.

| Source | Can | Example |
|---|---|---|
| **Accident** (the main one) | a plugin bug, a bank changing its memo format, an overconfident model, a crash at the wrong moment | a transfer booked from both statements; a crash between "committed" and "marked applied" that books a row twice |
| **Counterparty text** | write any text into a memo or payee field: anyone who pays the user or bills them | a memo with a newline and a fake review row; a memo shaped like an instruction to the LLM |
| **Pack publisher** | ship rule-pack entries the user loads | a pattern that confidently books every `AMAZON` line to one account across all users |
| **Model backend** | return any text; see whatever crosses the adapter | an account name not in the user's tree; a cloud backend logging what it is sent |
| **Document author** | write bills and invoices that reach paperless-ngx, or its model-generated metadata (totals, dates, tags) | a misread total that links the wrong bill; a model-applied tag that steers a document-keyed rule |

Out of scope: **code already running as the user**. It can read the book, the staging
store and paperless directly. Autobook adds no exposure beyond what GnuCash and
paperless already store.

## Where untrusted input enters

Treat all of the following as attacker-controlled or plain wrong:

1. **Statement file contents**, from paperless originals or the file path. Memos, payee names, references and IBANs are arbitrary
   text written by a counterparty. They reach the normaliser, the staging store, the
   review file and (redacted) the model adapter.
2. **ofxstatement plugin output.** Trusted code, untrusted content. A misparse can change
   an amount, a date or a FITID.
3. **The FITID.** Supplied by the bank or synthesised by a plugin; a collision drops a real
   transaction, a change books it twice. A synthesised FITID is treated like no FITID:
   checksum + ordinal key and the overlap rule.
4. **Model output.** Untrusted for correctness every time, whatever the backend. It may
   name an account outside the tree, a placeholder account, or a split.
5. **Rule packs.** Third-party data until pinned or signed and validated against the
   user's own history.
6. **The review file as read back.** The user's edits are trusted intent, but the file
   also echoes memo text, so its structure (row boundaries, IDs, status characters) must
   come from the parser, not from what the text looks like.
7. **paperless-ngx metadata**: extracted totals, dates, correspondents and tags, some of
   them model-generated, and the document list itself (paperless accepts duplicate
   documents by default; bill candidates are deduplicated by original checksum).
8. **Downloaded statement originals**: untrusted until their checksum matches the one
   paperless reports for that document version.

Trusted:
- the user's approve, reject and correct decisions in the review file, once parsed by ID;
- the user's existing booking history in the book (it is their own labelling; it is
  still checked against the live chart of accounts);
- the live chart of accounts read from the book;
- the user's own rules file and config in `$XDG_CONFIG_HOME`;
- credentials from the Secret Service.

## What must hold

The full list with reasons is in [AGENTS.md](../AGENTS.md); these are the properties a
finding breaks.

- **Nothing is written to the book without the user's approval.** Approval is the saved
  review file: nothing reaches the book that was not marked `a` there. Packs, documents
  and models only propose.
- **What the user approved is exactly what is written**: same row, same account, same
  amount, same date as shown. The review parser matches by ID, never by position, and
  aborts the whole batch on anything it cannot parse.
- **The book is never written under a live session.** `SESSION_NORMAL_OPEN` for writes,
  `SESSION_READ_ONLY` otherwise, never `SESSION_BREAK_LOCK`; a locked book
  (`ERR_BACKEND_LOCKED`) means write nothing; `session.end()` in a `finally`.
- **A row is reported applied only when it is in the book.** `session.save()` after the
  last commit, then the post-apply assertions, then a read-back of each row before it
  is marked applied.
- **Money is exact.** Integer cents into `GncNumeric(cents, 100)`, after checking the
  source account's commodity is shared and has fraction 100; no float reaches the
  `GncNumeric` constructor on any monetary path. Splits sum exactly or the row fails;
  nothing is dumped into Imbalance, and the batch leaves the Imbalance account
  unchanged.
- **Every row is written at most once.** Created transactions carry the proposal ID
  (`AB-` + a ULID) in `num`; matched transactions get no `num` and no FITID stamp, and
  are tracked by GUID in staging. Re-runs drop rows already in the book. Undo deletes
  only a transaction whose GUID staging records as created **and** whose `num` is that
  row's proposal ID.
- **No transfer is booked twice** across the two statements it appears on, including
  across batches: the second side matches the transaction the first side created, or
  queues as "pending transfer".
- **Nothing is created on a scheduled-transaction occurrence.** Such a row matches the
  existing instance or queues as "awaiting scheduled transaction".
- **A statement is the reference.** Its lines and amounts come only from the original
  file, parsed by the plugin, never from OCR, the archive version or metadata.
  Admission is all or nothing per statement.
- **A document link changes nothing else**: no amount, date or account, no split, and
  never overwrites an existing link. The paperless stamp is never read back to decide
  anything, and is written only when stamping is turned on.
- **Autobook never sets the reconciled flag, creates accounts, or creates scheduled
  transactions.**
- **Only rules produce splits.** kNN and the LLM return one account from the live tree or
  nothing; failing either kNN gate falls through, it never lowers a threshold.
- **The pipeline never imports `gnucash`.** Only the book process does; the JSON
  contract is the only way across.
- **Nothing personal leaves the machine.** Only a normalised merchant token, the amount,
  the sign and the account list reach a model backend. A remote backend (opt-in; local is the default)
  gets only allowlisted or pack-matched tokens and account indices, never account names.
  Raw memos, counterparty IBANs, document content, correspondent names and credentials
  never reach a backend, a shared pack, a log, a crash report or a test fixture;
  staging holds document IDs, checksums, amounts and dates only.
- **Temporary files are private.** Downloaded originals and the review file live under
  `$XDG_RUNTIME_DIR`, mode `0600`, and are removed in a `finally`.
- **No-AI mode makes no network connection.**
- **A refusal never blocks opening GnuCash.** Proposals stay pending.

## Components that matter most

In order:
1. the applier write path (session mode, `BeginEdit`/`CommitEdit`, money conversion,
   save and read-back);
2. the review-file parser;
3. idempotency by `num`, `match_existing` (scheduled transactions, transfers), undo,
   and the post-apply assertions;
4. the redaction boundary in the model adapter (allowlist, account indices);
5. the classification gates (precedence, kNN distance and margin, the LLM label check);
6. the correlation pass (transfer pairing, double-booking);
7. statement admission (checksum, temporary files, balance check, overlap rule) and
   FITID dedup;
8. the bill matcher and document-link writing;
9. the paperless-ngx client (token handling, stamping);
10. rule-pack loading, pinning and validation;
11. the launcher sequence and lock handling;
12. logging and crash output (personal data).

Lower priority: the normaliser's output quality (a bad token falls through to review),
onboarding's category mapping (the user confirms each line).

Out of scope: GnuCash and libgnucash, ofxstatement and its plugins, paperless-ngx, and
the model backend itself (report a bug in them only if Autobook's use of it is what makes it harmful).

## Known gaps: do not report these on their own

- **Little is built yet.** A patch is reviewed against the design (proposal 0001 as
  amended by 0002, and the architecture) and AGENTS.md.
- **A model or kNN can propose the wrong account.** Expected; abstention and review exist
  because of it. In scope: a wrong proposal reaching the book without review, or a gate
  that lets a low-confidence proposal through as confident.
- **A user who approves a wrong booking gets it.** In scope: a review file that shows
  something other than what is written.
- **A configured remote backend sees allowlisted merchant tokens, account indices and
  amounts.** Accepted when the user chooses one; in scope if it sees more.
- **A wrong bill can be linked** when an equal-amount charge in a later statement owns
  it. A link changes no booking by itself; in scope if it changes an amount, date or
  account, or a document-keyed rule acts on it outside shadow mode.
- **Accounts without statement balances** have no admission-time integrity check.
- **Pack signing** is not designed yet; pinning is the stopgap.

## How to exercise it

`nox -s gate` runs format, lint, types, the pipeline tests, typos and the docs lint, with
no GnuCash installed. `nox -s applier` runs the book-process tests (exporter and applier;
the session keeps its old name) and needs the system `python3-gnucash`; run it only against a **restored copy of a book**, never a real one.
Test data is synthetic: no real statements, memos or IBANs in fixtures.

## How we rate severity

The project's promise is that the book only changes in the way the user approved, and
that their financial data stays on their machine.

- **Critical:**
  - a booking is written that the user did not approve, or differs from what they
    approved (account, amount, date, row);
  - the book is written under a live session or with `SESSION_BREAK_LOCK`, or left
    corrupted;
  - a raw memo, counterparty IBAN, document content or credential leaves the machine;
  - a remote backend receives a token that is not on the allowlist or in a rule pack,
    or an account name;
  - a statement is admitted from OCR or archive text, or its lines or amounts are taken
    from paperless metadata;
  - the reconciled flag is set, or an account or scheduled transaction is created, by
    Autobook.
- **High:**
  - a row is booked twice, or a transfer from both statements, or a row is created on
    a scheduled-transaction occurrence;
  - a row is reported applied that is not in the book (no save, no read-back);
  - undo deletes a transaction Autobook did not create;
  - a wrong document link is written, or an existing one overwritten;
  - a downloaded statement original or the review file is left readable by others or
    left behind after a run;
  - money passes through a float on its way to the book, or a split difference lands in
    Imbalance;
  - a model returns an account outside the live tree, or a split, and it is accepted;
  - a kNN proposal passes with either gate failed, or a threshold is lowered for one
    case;
  - personal data reaches a shared pack, a log, a crash report or a committed fixture;
  - no-AI mode makes a network connection;
  - the pipeline imports `gnucash`.
- **Medium:**
  - an unpinned or unvalidated pack is loaded;
  - an ambiguity-flagged merchant, or an LLM row before shadow mode has measured it, is
    pre-marked `a`;
  - Autobook writes to paperless when stamping is turned off;
  - a refusal blocks GnuCash from opening;
  - a synthetic row can enter the kNN index;
  - a credential is read from or written to the config file;
  - a FITID collision drops a real transaction without a warning.
- **Low:**
  - non-personal information in error messages;
  - issues reachable only through a misconfiguration the user made;
  - a poor normalised token that still falls through to review.

A clean reproducer matters more than a severity label. The best form is a failing test:
a statement line that ends up in the wrong row, a review file that applies something
other than what it shows, a crash point after which a re-run books twice, or an adapter
call whose payload carries more than the token, amount, sign and account indices.

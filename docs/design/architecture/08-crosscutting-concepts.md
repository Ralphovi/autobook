---
created: 14.10.2026 23:50
type: architecture
status: living
tags:
  - architecture
  - crosscutting
---
# 8. Cross-cutting concepts

> Living document. The design is
> [proposal 0005](../proposals/draft/0005-beancount-ledger.md); its §17 lists the
> rules for anyone writing code, and [`AGENTS.md`](../../../AGENTS.md) states them
> in full. This section
> explains how the rules fit together.

Terms used throughout: the **ledger** is the user's Beancount v3 plain-text
ledger, a main file and the files it includes. The **owned file** is the one
included file Autobook may write. The **ledger package** is the only code that
imports `beancount`; it has a **reader** (accounts, corpus, existing entries)
and a **writer** (append, read back, assert, undo). The **driver** is the
separate program that hands Autobook OFX statement files and calls its commands.

## 8.1 Money

Amounts are **integer cents** from the moment the OFX parser reads a value to
the moment the writer renders a posting. Decimal strings from statements and
from paperless's monetary fields are parsed with `Decimal` and converted once;
an amount that is not a whole number of cents rejects its statement at
admission. The writer builds a `Decimal` from the integer cents and prints it
with exactly two decimals. No float exists on any monetary path, including
tests and fixtures, and a float never reaches `Decimal`. Fixed amounts in rules
are integer cents too (`cents: 1250`, not `value: 12.50`, which a YAML parser
would read as a float).

Every posting carries an **explicit amount**. Autobook never leaves one for
Beancount to fill in, because an elided amount hides exactly the error the sum
check looks for. Every split specification must sum exactly to the line's
amount, and the postings of every entry must be in whole cents and sum to
exactly zero, or the row fails and is queued; there is no account that absorbs
a difference.

The exact-sum check is **Autobook's own**. Beancount's check is tolerant: it
infers a tolerance of half the last printed digit, so two-decimal postings that
are off by half a cent load without error (`10.00` against `-9.995` passes).
A path that skipped Autobook's check would let such an entry into the ledger.

Currency is read, never assumed, and never hard-coded. It comes **from the
statement** and is checked against both accounts' `open` directives: it must be
declared on the source account and allowed on the other account (an `open`
directive that names no currency allows any). A statement whose currency the
ledger account's `open` directive does not declare is rejected at admission; a
row that fails the check at apply is queued and not written. A row whose
posting would be denominated in a currency other than its account's is
`out_of_scope`.

## 8.2 Idempotency and failure granularity

There are two stores (ledger and staging) and no shared transaction between
them. Idempotency comes from the ledger side. Each staged row has a **proposal
ID** (`AB-` plus a ULID), generated once and distinct from its staging key. It
is written as `autobook-id` metadata only on entries Autobook creates, and
every apply begins by dropping rows whose ID the reader already finds in the
ledger; only values matching `^AB-[0-9A-HJKMNP-TV-Z]{26}$` count. A crash
between "file replaced" and "marked applied" leaves the two stores disagreeing,
and the ID in the ledger settles it.

A `match_existing` row writes nothing at all: the matched entry is in a file
Autobook does not own. A hand-written entry has no permanent identifier, so
staging records it in `applied_entry` by its **content hash** — Beancount's
`hash_entry` with `exclude_meta=True`, over date, flag, payee, narration, tags,
links and postings, stable when the entry moves in its file. A re-run drops a
matched row whose hash is in staging and still present in the ledger.

A row counts as `applied` only after the **read-back** (the ledger is loaded
again; every created row's proposal ID appears exactly once, with the approved
date, accounts and amounts, and every matched row's recorded entry is still
present) and every assertion have passed. That
holds after a crash too: the writer's batch journal, written before the
replace, lets the next run validate an interrupted batch against its original
baseline or restore the previous content (section 6.5). IDs found in the
ledger prove presence, not validation. Any batch can be re-run after any
failure. A proposal ID that staging holds as applied
and the ledger no longer contains is reported by `autobook status`, never
re-created silently; so is an Autobook entry that differs from what staging
recorded.

Any batch can be undone: undo removes an entry only when its `autobook-id` is
the proposal ID of a staged row with disposition `create` or `create_split` in
that batch **and** the entry is in the owned file; both are asserted first.
Undo of a matched row changes staging only (section 6.7).

**The books must be correct at the end; an import with an error is rejected,
not accepted.** A silently wrong booking is worse than a loud failure and worse
than no booking. Whatever Autobook can check, it checks, and a failure rejects
rather than degrades: a statement is admitted whole or not at all, a batch is
booked whole or not at all, and a rejection is loud — a non-zero exit code and
the reason. The only case where a batch proceeds without a line is a line that
cannot be booked for a reason of its own; that line is queued: shown for
review, neither booked nor lost, and counted as outstanding in the balance
check.

Failures are classified by granularity and never mixed:

| Tier | Examples | Effect |
|------|----------|--------|
| Statement | The file does not parse as OFX; a line lacks a date, an amount or a currency, or an amount is not a whole number of cents; the account ID is not in the configuration; the currency is not one the ledger account's `open` directive declares; the lines do not add up to the stated balances; an overlap the overlap rule cannot resolve | That statement is rejected at admission, the reason recorded, no line of it staged (exit 7); other statements proceed |
| Row | Low confidence, no rule and kNN distance over the cutoff, proposed account not open on the line's date, a currency the account does not allow, ambiguous or absent `match_existing`, split sum mismatch, a payment whose parts change every period (a loan instalment), pending transfer | That row is queued with its reason; the batch proceeds |
| Batch, before writing | Coverage drop, spike in large-language-model (LLM) fallbacks, unusual share of rarely used target accounts, version tuple changed (exit 3); owned file not included, root-name options differ from the main file's, a ledger file changed between read and replace (exit 4); review file does not parse (exit 5); paperless unreachable | Nothing is written; the reason is reported; the ledger is a text file and stays usable |
| Batch, after writing | The read-back does not find every created row's proposal ID exactly once as approved, or a matched row's entry is gone; the load reports a new error; a byte before the appended entries or another file changed; an account's balance did not move by exactly the sum of the postings written to it; the closing-balance check fails | The previous content of the owned file is restored, nothing is marked applied (exit 6) |

The second batch tier is what makes "whole or not at all" hold after the
replace: the writer keeps the previous content until the assertions pass and
restores it on any failure, provided the file still holds exactly what the
writer wrote (section 6.5). No failure leaves a partial batch. A ledger that
already has errors can still be booked into; only a *new* error rolls a batch
back.

A per-row problem that halts a batch, or a batch-level problem that still
leaves something written, is a defect.

## 8.3 Evidence, provenance and versions

**Every proposal is explainable.** It records method (`rule | knn | llm`), the
rule ID or the neighbour distances and vote shares, any linked document, and the
versions that produced it.

**The corpus has provenance.** Rows are `observed` (from the ledger, through the
reader's `corpus` contract, which yields nothing else) or `corrected` (review
decisions, read from staging). Index construction refuses (raises on) any row
that is not `observed` or `corrected`; there is no path by which a synthetic row
can enter.

**Thresholds have evidence.** Distance cutoffs, vote margins, confidence bands
and the bill-matching window are set from rolling-origin backtest and
shadow-mode data across the corpus — gate thresholds on the stratum of novel
memos — never adjusted to fix one transaction. A threshold that pre-marks LLM
rows needs shadow-mode precision for `method=llm` first.

**The version gate.** A successful trial records the tuple: rule-file hash,
normaliser version, k-nearest-neighbour (kNN) index version, steering-document
(prompt) version, model ID and model configuration (temperature pinned to 0),
the producer strings of the statements used, the Beancount version, and the
items proposal 0002 adds: paperless version, correspondent-association hash, the
bill date window, and the configured bill and credit-note document types.
Production refuses to write (exit 3) if the current tuple differs from the last
validated one.

A **producer string** is an optional text the driver hands over per OFX file,
for example the converter plugin's name and version. Autobook does not run the
converter and cannot know how a file was produced; a changed producer string
means a plugin was updated, which can change every memo without any Autobook
code changing.

## 8.4 Normalisation is data, and lives in one place

The converter plugins, which the driver runs, convert formats and must deliver
the raw memo unmodified. All normalisation happens in Autobook, driven by
per-source-account profiles loadable from a user directory. That is what lets
normalisation — the thing tuned most — be changed and re-backtested without
touching any plugin, and lets a new bank's profile ship as data.

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
- The review file holds counterparty and correspondent names. `autobook
  review-file` writes it to standard output and starts no editor; the driver
  decides where it lives. It must be private to the user and short-lived: under
  `$XDG_RUNTIME_DIR`, mode `0600`, removed in a `finally`; never `/tmp`.
  Statement originals and the OFX files converted from them are the driver's
  and follow the same rule there.
- User rules and correspondent associations are personal data in a separate file
  from anything shippable. Packs carry pattern → category and ambiguity flags
  only; counterparty IBANs never enter one, creditor IDs may.
- Fixtures are synthetic or taken from published format documentation.

## 8.6 One ledger format; assertions through the reader

There is one ledger format, Beancount v3 text, and one way to inspect it.
Everything that looks at the ledger — idempotency, the account list, balances,
match candidates, the read-back and every post-apply assertion — goes through
the reader, which loads the ledger with Beancount's own loader. Nothing outside
the ledger package parses ledger text, and only the ledger package imports
`beancount` (the linter enforces the import rule). The rest of Autobook sees the four typed
contracts (`corpus`, `coa`, `existing`, `apply-in`/`apply-out`; section 5.1).
There are no storage backends to tell apart and no SQL against a ledger. (The
staging store is a different thing: SQLite by default, a PostgreSQL URI as an
option.)

There is no backup step. The writer keeps the previous content of the owned
file for the duration of the run and restores it when the read-back or an
assertion fails. Keeping the ledger in git is recommended, never required. The
real safety net is batch reversibility by proposal ID.

Beancount has no lock, so against editors and Fava there is none to take or
respect. Between Autobook runs there is one: `apply` and `undo` hold Autobook's
own writer lock from the first read until staging is updated, because two runs
could otherwise both pass the compare and the second overwrite the first. The
other guards are
compare-before-write on every ledger file (each file's SHA-256 is taken at read
and checked again before the replace), a single atomic rename so that no reader
sees a half-written file, and the read-back with the previous content kept.
What that does not cover is in chapter 14.

## 8.7 The ledger belongs to the user

Autobook reads all of the ledger and writes only transactions, only into the
owned file. It never changes an entry it did not create.

| Job | Owner | Autobook's part |
|-----|-------|-----------------|
| Chart of accounts (`open`, `close`) | The user | Read through the `coa` contract. A proposed account that is not open on the line's date queues the row; the review-file parser rejects an account that is not open. Never creates or closes an account: accounts encode how someone thinks about their money and may map to tax categories |
| Balance assertions (`balance`, `pad`) | The user | Never written. They are the user's independent check on everything Autobook does |
| `price`, `commodity`, `plugin`, `include` | The user | Never written. `autobook init` prints the `include` line for the owned file; the user adds it |
| Transactions that do not come from a statement line, and every entry outside the owned file | The user | Found as `match_existing` candidates in the line's source account and identified by content hash. Nothing is written to a matched entry, not even a document link; the link is in staging only |
| Recurring fixed bookings | Nobody in particular: Beancount has no scheduled transactions and Autobook adds none | Ordinary rule candidates, mined like any other group; most become creditor-ID rules |
| Loans, and any payment whose parts change every period | The user, who writes the entry by hand | The line is queued; once the entry exists the line resolves as `match_existing` |
| Fetching statements, converting them to OFX, deciding when to run, opening the editor, notifying | The driver | Takes OFX files and an optional producer string; answers with an exit code, `--json` output and the review file |
| Optical character recognition (OCR), correspondents, bill fields | paperless-ngx | Read the results; verify totals against bank amounts |

One exception to "transactions only" is required by Beancount: an included file
does not inherit the main file's `name_assets` … `name_expenses` options.
`autobook init` copies those five options into the owned file's header, and
every run compares them with the main file's; a difference refuses the run
(exit 4).

The owned file is not private to Autobook. The user may correct an entry in it,
and Fava can edit or delete entries in any included file. So the writer never
regenerates the file: it appends, and on undo removes exact spans.

## 8.8 Configuration and secrets

TOML in `$XDG_CONFIG_HOME/autobook/`; data, including the default SQLite staging
store, in `$XDG_DATA_HOME/autobook/`. The configuration names the main ledger
file and the owned file, and per source: the OFX account ID, the ledger account,
whether the line IDs are bank-supplied or synthesised, the normalisation profile,
and `paypal_mode` where relevant. Autobook cannot learn any of these from the
file. Secrets are never in the configuration; they go in the Secret Service.
Every configuration value that can change a classification is part of the
version tuple.

The normaliser reads its user profiles and the `accounts.toml` that maps source
accounts to profiles from `$XDG_CONFIG_HOME/autobook/normaliser/` (or
`~/.config/autobook/normaliser/` when `XDG_CONFIG_HOME` is unset, empty or not
absolute); section 5.2 has the file formats and the override rule. They reach the
version tuple through the normaliser version, a digest of the effective profiles,
the mapping and the Unicode version.

## 8.9 Documentation currency

A change that adds or alters a CLI flag, configuration key, contract field,
staging column or disposition updates this architecture description in the same
PR, from the first PR on. Decisions that settle arguments become ADRs; plans are
proposals.

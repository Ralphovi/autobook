---
created: 20.11.2026 20:49
type: proposal
status: draft
author: Eduard Ralph
tracking-issue: 100
tags:
  - proposal
  - beancount
  - ledger
  - design
---

# Autobook: OFX statements into a Beancount ledger

> **Proposal 0005 — the whole system design.** It replaces
> [proposal 0001](0001-gnucash-auto-booking-pipeline.md) (the GnuCash design)
> and [proposal 0003](0003-windowed-interface-and-command-line.md) (windows and
> command line). This document is self-contained: nothing in it needs 0001 or
> 0003 to be read first. Both stay in `draft/` untouched until this proposal is
> accepted, and are withdrawn then.
>
> [Proposal 0002](0002-document-driven-booking-via-paperless.md) (bills from
> paperless) and [proposal 0004](0004-rules-first-mined-from-history.md)
> (rules first, mined from history) still apply, read against this document
> where they say "0001". What changes in them is listed under *Relation to the
> other proposals*.
>
> **Three decisions shape it:**
>
> 1. Autobook books into a **Beancount v3** plain-text ledger. The existing
>    GnuCash book is converted once and retired.
> 2. Autobook is **not the pipeline driver**. It is handed OFX statements and
>    books them into the right accounts. Fetching and converting statements is
>    done by a separate project.
> 3. **The books must be correct at the end.** An import with an error is
>    rejected, not accepted.
>
> It also **relicenses Autobook** as GPL-2.0-or-later, because Beancount is
> GPL-2.0-only (§13). That is
> [ADR-0005](../../adr/0005-relicense-gpl-2-or-later.md), which supersedes
> [ADR-0002](../../adr/0002-gpl-license-and-dco.md) when accepted.
>
> Accepted when milestones B0 and B1 (§16) have reported.

## In plain language

You hand Autobook a bank statement as an OFX file. For each line it works out
which account the money went to or came from. It writes its proposals into a
text file, with the ones it is sure about already marked as accepted. You look
through the file, fix what is wrong, and save it. Autobook then adds the
accepted lines to your ledger as transactions.

Your ledger is a Beancount file: plain text. Autobook adds its transactions to
one file of its own that your ledger includes. It checks the result by loading
the ledger again. If anything is wrong, it puts the file back as it was. You
can see every booking Autobook made in your editor or in Fava, and undo a
whole batch with one command.

Autobook does not fetch statements, run converter plugins, or decide when to
run. Another program does that and calls Autobook's commands.

## Goal

Book bank statement lines into a Beancount ledger without writing transactions
by hand.

Target: ~90–95% of lines proposed with enough confidence to be pre-marked `a`
(accept) in the review file; the rest decided by the user in that file.
**Approval is saving the review file**: nothing reaches the ledger that was not
marked `a` in the saved file.

The residual is not a modelling failure. It is genuinely ambiguous data — was
that Amazon order household or a gift? — which a statement line does not
contain the information to resolve.

Secondary goal: usable by other people who keep a Beancount ledger.

## Design

### 1. Scope

**In scope:** taking OFX statements, assigning a destination account to each
line, getting the user's approval, and writing the approved lines into the
ledger as transactions.

**Not Autobook's job — the driver's.** Getting a statement from the bank or
from a document store, converting it to OFX with ofxstatement, deciding when
to run, opening the review file in an editor, and notifying the user. The
driver is a separate project in its own repository. Autobook never imports or
runs ofxstatement.

**Not Autobook's job — the user's.** The chart of accounts (`open` and
`close`), balance assertions, prices, and every transaction that does not come
from a statement line. Beancount has no scheduled transactions and no
assistants; Autobook does not add them.

**Permanently out of scope**, as settled before and still requiring an ADR to
revisit:

- **Securities transactions.** There is no classification problem in "buy 10
  units of X": the work is structural (lots, cost basis, embedded fees, events
  with no cash flow), not categorical.
- **Postings in a currency other than the account's.** Foreign-currency
  spending that the bank already debited in the account's currency *is* in
  scope; it arrives as an ordinary line.

Both would need postings with a cost (`{…}`) or a price (`@`), which break the
plain two-posting, one-currency shape everything here is built on. Beancount
expresses them more easily than GnuCash did; that is not new evidence about
classification and does not reopen either exclusion.

Lines of these kinds still arrive in statements. They get the disposition
`out_of_scope`: recorded, shown as skipped, kept out of the review queue, and
**excluded from coverage and drift metrics**. Otherwise the drift detector
sees permanently low coverage and is tuned until it stops catching real drift.

**Unknowable splits** are a data limitation, not a scope choice: splitting a
supermarket charge needs receipt lines the statement lacks. Determinable
splits are in scope through rule templates (§6.1).

### 2. Principles

1. **The books must be correct at the end.** A silently wrong booking is worse
   than a loud failure and worse than no booking. Whatever Autobook can check,
   it checks, and a failure rejects rather than degrades:
   - a **statement** is admitted whole or not at all (§5);
   - a **batch** is booked whole or not at all (§10.3);
   - a rejection is loud: a non-zero exit code and the reason.
2. **The ledger belongs to the user.** Autobook reads all of it and writes
   only transactions, only into its own file (§10.1). It never changes an entry
   it did not create.
3. **Approval is the saved review file.** Nothing is booked that was not
   marked `a` there, with exactly the account, amount and date shown.
4. **Abstention is a feature.** A classifier that says "never seen this" is
   worth more here than one that is right slightly more often. Thresholds move
   on backtest evidence, never to fix one annoying line.
5. **Deterministic first.** Rules, then kNN, then an optional language model,
   so that as much as possible is explainable and identical on every run.
6. **Autobook does not second-guess a well-formed statement.** It cannot know
   how an OFX file was produced; converting it correctly is the job of
   ofxstatement and the driver. Autobook checks the file for consistency and
   its own work for correctness.

The only case where a batch proceeds without a line is a line that cannot be
booked for a reason of its own: no confident account, an account not open on
its date, an ambiguous match. That line is **queued**: shown for review,
neither booked nor lost, and counted as outstanding in the balance check.

### 3. Architecture

One program, one process. Python, GPL-2.0-or-later.

```
   driver (separate project)
     │  OFX files, optional producer string        ▲ exit code, --json,
     ▼                                             │ review file
┌─ AUTOBOOK ──────────────────────────────────────────────────────┐
│                                                                  │
│  input        parse OFX → admit (whole statement or nothing)     │
│                                                                  │
│  pipeline     normalise → dedup → correlate (transfers,          │
│               match_existing) → classify (rules → kNN → LLM)     │
│               → dispose → batch gate → stage → review file       │
│                                                                  │
│  staging      SQLite: statements, proposals, decisions           │
│                                                                  │
│  ledger       reader: accounts, corpus, existing entries         │
│  package      writer: append, read back, assert, undo            │
│               (the only code that imports beancount)             │
└───────────────────────────────┬──────────────────────────────────┘
                                │ reads every file; writes one
                                ▼
        main.beancount ── include ──▶ autobook.beancount (owned)
```

**The import rule.** Only the ledger package imports `beancount`, enforced by
the linter. Everything else reaches the ledger through four typed contracts
(§4.4), which serialise to JSON for fixtures and for `--json` output. This is
what keeps input, pipeline and staging testable against fixtures, with no
ledger on disk.

There is no second process. The GnuCash design needed one because the GnuCash
bindings could not be installed into a virtual environment; Beancount is an
ordinary dependency with wheels for Linux, macOS and Windows on Python
3.9–3.14.

### 4. Interface

#### 4.1 What the driver hands over

| In | Notes |
|---|---|
| One or more OFX files | Parsed by Autobook's own parser (standard library only). It reads the account ID, the currency, the statement period, the ledger balance, and per line the ID, date, amount, name and memo. The memo must arrive unmodified: normalisation is Autobook's. |
| Optionally, a producer string per file | For example the plugin name and version. Recorded with the statement and part of the version tuple (§9.3). |
| The saved review file | To `autobook decide` or `autobook apply`. |

#### 4.2 Commands

Every command accepts `--json` for machine-readable output. None of them
starts an editor or another program.

| Command | Does | Touches the ledger |
|---|---|---|
| `autobook init` | Create the owned file with its header; print the `include` line for the user to add | creates the owned file |
| `autobook propose FILE…` | Admit the statements, dedup, correlate, classify, dispose, run the batch gate, stage | read |
| `autobook pending` | Count and list pending proposals; exit 1 when there are none | none |
| `autobook review-file` | Write the review file to standard output | read (account list) |
| `autobook decide --from FILE` | Parse a saved review file and record its decisions to staging; `--check` parses only | read (account list) |
| `autobook apply --from FILE` | `decide`, then book the approved rows: write, read back, assert | **write** |
| `autobook undo BATCH` | Remove what a batch created; asks for confirmation unless `--yes` | **write** |
| `autobook status` | Last run, pending counts, the version tuple in force, entries that differ from staging | read |
| `autobook export` | Print the reader's contracts (`coa`, `corpus`, `existing`), for inspection and for the trial | read |
| `autobook trial backtest …` | Rolling-origin backtest (§9.1) | read |
| `autobook trial mine` | Mine rule candidates from history (proposal 0004) | read |
| `autobook trial accept` | Record this trial's version tuple for production | none |
| `autobook rules cluster` · `test RULE` · `accept RULE` | Cluster unresolved rows; score a candidate rule against history; add a scored rule to the rules file | read |

#### 4.3 Exit codes

| Code | Meaning | Written |
|---|---|---|
| 0 | Done | as the command says |
| 1 | Nothing to do | nothing |
| 2 | Usage or configuration error | nothing |
| 3 | The batch gate or the version gate refused (§9.2, §9.3) | nothing |
| 4 | The ledger is not writable as expected: the owned file is not included, its root-name options differ from the main file's, a ledger file changed during the run, or another Autobook run holds the writer lock | nothing |
| 5 | The review file did not parse; the line number is on standard error | nothing |
| 6 | The read-back or an assertion failed; the previous file was restored | nothing persists |
| 7 | A statement was rejected at admission; the reason is reported per file | nothing staged from that statement |

The numbering is fixed when the first command that returns 3–7 lands.

#### 4.4 Contracts between the ledger package and the rest

Account paths are lists of components.

| Contract | Content |
|---|---|
| `corpus` | One row per historical transaction with exactly two postings, one in a configured source account, both in the same currency, neither with a cost or price: raw memo, amount in integer cents, sign, source account, destination account, date, provenance. Unchanged from the implemented version. |
| `coa` | Per account: path; root category (`assets`, `liabilities`, `equity`, `income`, `expenses`, independent of renamed root names); `open` date; `close` date or null; the currencies its `open` directive allows (empty means any). |
| `existing` | Autobook IDs found in the ledger, with file and line and the entry as loaded. Match candidates per source account in a date window, each with its content hash (§8.2). The root-name options. Every loaded file with its SHA-256. The load's errors. |
| `apply-in` / `apply-out` | In: per row the proposal ID, disposition, accounts or split specification, amount in cents, currency, date, narration, optional document URL, optional match hash. Out: per row `{proposal_id, entry, status}`; per batch the assertion results. |

#### 4.5 Configuration

TOML under `$XDG_CONFIG_HOME/autobook/`; data under `$XDG_DATA_HOME/autobook/`.
It names the main ledger file and the owned file, and per source: the OFX
account ID, the ledger account, whether the line IDs are bank-supplied or
synthesised, the normalisation profile, and `paypal_mode` where relevant.
Autobook cannot learn any of these from the file. Credentials are never in the
configuration; they go in the Secret Service.

### 5. Statement input and admission

A statement is **admitted whole or not at all**. It is rejected, with the
reason recorded and no line staged, if:

- the file does not parse as OFX;
- a line lacks a date, an amount or a currency, or an amount is not a whole
  number of cents;
- the account ID is not in the configuration;
- the statement's currency is not one the ledger account's `open` directive
  declares;
- the lines do not add up to the statement's balances, where it states them;
- its period overlaps an admitted statement in a way the overlap rule cannot
  resolve (proposal 0002 §3.4).

Admission records a `statements` row with the file's checksum, so handing over
the same file twice changes nothing.

**Dedup.** A line is identified within its source account by the bank's ID
when the configuration says the IDs are bank-supplied. Otherwise the ID is
synthesised by the converter (a hash of date, memo and amount, so two
identical card payments on one day collide) and is not trusted as an identity:
the line takes the key `(statement checksum, ordinal)` and the overlap rule
decides whether a later statement repeats it.

### 6. Classification

The cascade is **rules → kNN → LLM**, in that order, for determinism and
auditability rather than cost. One precedence table governs everywhere; it is
stated in full in proposal 0002 §5.1:

1. creditor-ID rule (SEPA Gläubiger-ID);
2. document-keyed rule — only with a confirmed correspondent association,
   `auto: true`, and passed shadow mode;
3. ambiguity flag (`AMAZON`, `PAYPAL` …) — forces `?`;
4. memo-pattern rule;
5. kNN, both gates;
6. LLM, the tail.

A rule's `priority` orders rules within a tier only.

#### 6.1 Rules

A versioned file, owned by the user. Rules are data: id, match, target,
priority, `created-by` (`user`, `mined`, `llm`), `auto`, and the held-out
score at acceptance. They are built first and mostly **mined from the user's
own history**; a human accepts each one against a measurement on a held-out
period (proposal 0004).

- **Creditor ID**: exact, stable across memo reformatting, unique per company.
  Covers most recurring debits — insurance, utilities, telephone,
  subscriptions, rent by direct debit — with certainty. Creditor IDs are
  registered business identifiers and may be shared.
- **Memo pattern**: a regular expression on the normalised memo.
- Counterparty IBANs may belong to individuals: local only, never shared.
- **Ambiguity flags** force `?` for merchants whose lines cannot be told apart
  from the memo. Only a tier above the flag may decide such a line.

**Split templates.** A rule may target a split specification for fixed-ratio
cases:

```yaml
- id: versicherung-bundle
  match: {creditor_id: DE98ZZZ09999999999}
  splits:
    - {account: "Ausgaben:Versicherung:Haftpflicht", type: fixed, cents: 1250}
    - {account: "Ausgaben:Versicherung:Hausrat",     type: remainder}
```

Amounts are **integer cents**, never a decimal a YAML parser would read as a
float. A computed split must sum exactly to the line's amount; a mismatch
fails the row. **Splits are rules-tier only**: kNN and the LLM return a single
account.

#### 6.2 kNN

An index built from the user's own ledger at run time: in-process, CPU only,
no network, no model download.

- **Corpus:** the `corpus` contract — two-posting transactions with one
  posting in a source account. Every row is `observed` (from the ledger) or
  `corrected` (from review decisions); synthetic rows cannot enter.
- **Representation:** character n-gram TF-IDF (`char_wb`, 3–5) over the
  normalised memo. Bank memos are merchant tokens with noise, truncation and
  German compounds; character n-grams absorb that.
- **Partitioning:** a separate index per `(source account, sign)`. Amount
  stays out of the distance; it is a tie-breaker only.
- **Two gates**, both required: nearest-neighbour **distance** under a cutoff,
  and **vote margin** between the winner and the runner-up. A unanimous vote
  among distant neighbours is a sparse region, not confidence. Failing either
  falls through; it never lowers a threshold.
- **Recency weighting:** exponential decay, half-life about 18 months.
- Rebuilt on every run. No vector database.

A token-Bayes classifier over the same corpus runs in the backtest as a
negative control. If kNN does not clearly beat it on the lines the rules leave
over, that is a result.

**Cold start.** History comes from the ledger. For the author it comes from the
converted GnuCash book (§14). A new ledger starts with rules and packs only.

#### 6.3 LLM (the tail, optional)

Running with no language model at all is a first-class configuration.

- The label space is constrained: the account list is generated from the live
  ledger at run time, the answer is validated against it, and anything else is
  rejected. Rejected too: accounts not open on the line's date, accounts whose
  `open` directive does not allow the line's currency, and accounts under the
  Equity root.
- The steering document is versioned and never contains the account list.
  Temperature is 0. The model ID is in the version tuple.
- **An LLM proposal is always `?`** until shadow mode has measured precision
  for `method=llm`.
- It also drafts rule candidates, which are scored against history before a
  human sees them.

#### 6.4 Normalisation

Quality depends more on memo preprocessing than on k or the metric. Remove the
SEPA tags and drop the values of the reference, amount, IBAN and BIC tags;
keep the purpose text, the creditor ID and the ultimate debtor and creditor
names; strip embedded dates, card fragments and trailing sequence numbers.
What survives is the merchant token.

It **lives in Autobook**, never in a converter plugin: it is the thing tuned
most, and it must be changeable and re-backtestable in one place. Profiles are
per source account and load from a user directory as well as the package. The
normaliser version is part of the version tuple.

### 7. Correlation

With several accounts feeding in, every transfer between the user's own
accounts appears in two statements. Booking both sides double-books.

- Runs **before** classification. Every transfer line first goes through a
  `match_existing` search in its own source account.
- The first side of a transfer is booked and records a `transfers_pending`
  entry: counterpart account, amount, date window, its proposal ID.
- The second side resolves to the entry the first side created — it has a
  posting in both accounts — and is never booked again. An unmatched second
  side whose counterpart is pending is queued as "pending transfer", never
  classified.
- **PayPal** follows `paypal_mode`. `account` (default): PayPal is its own
  ledger account and its statement is imported; bank lines to PayPal are
  transfers, not expenses. `pass_through`: PayPal statements are never
  imported and the bank line is classified by the merchant in its memo.

### 8. Dispositions

Every staged line gets exactly one:

```
create | create_split | match_existing | out_of_scope | queue
```

#### 8.1 `queue`

Confidence under threshold; no rule and kNN distance over the cutoff; the
proposed account not open on the line's date; a currency the account does not
allow; an ambiguous or pending match. A queued row carries its reason and
appears in the review file as `?`.

A payment whose parts change every period — a loan instalment's interest and
principal — cannot be split from the statement line. It is queued. If the user
writes that entry by hand, the line resolves as `match_existing`.

#### 8.2 `match_existing`

The statement line is already in the ledger: the user wrote it by hand, or it
is the second side of a transfer.

- **Search** the line's **source** account for a posting with the same amount
  within ±5 days that is not already claimed for that source account. Whether
  the user has asserted a balance since is not a filter.
- **Unambiguous** → nothing is created. Staging records which entry matched.
  **Ambiguous or absent** → queue. Never guess.
- **Nothing is written to a matched entry.** It is in a file Autobook does not
  own.

A hand-written entry has no permanent identifier; its file and line move
whenever anything above it is edited. A matched entry is therefore identified
by a **content hash** over date, flag, payee, narration, tags, links and
postings, excluding metadata and position (Beancount's `hash_entry` with
`exclude_meta=True`; verified stable across processes and when the entry
moves). An entry Autobook created is identified by its `autobook-id` instead.

**Claims are per source account.** An entry is claimed for a source account
when a staged row of that account already refers to it: the row that created
it, or a row that matched it. This is what lets a transfer resolve. The first
side, booked from account A, creates an entry with a posting in A and one in
B. That entry is claimed for A and not for B, so the second side's search in B
finds it, matches it once, and claims it for B. An `autobook-id` alone does
not make an entry unavailable.

If the user later edits a matched hand-written entry, its hash changes and the
claim is lost. The staged row stays `applied`, so nothing is proposed twice; the entry
becomes a candidate again, and a second line that then finds more than one
candidate is queued. See *Risks*.

### 9. Trial and production

#### 9.1 Trial

Read-only, replayable at any time. **The method is backtesting.** Ground truth
is the user's own booked history. Calibration is **rolling-origin**: for each
month *m* the index holds only rows before *m* and the test set is month *m*.
Results are reported per method and per confidence band, in two strata — memo
seen before, and novel — and thresholds are set on the **novel** stratum,
because that is where confident errors happen.

The rule builder is the same machinery with one question: "this candidate
matches 47 historical transactions — 45 went to one account, 2 to another;
here are the 2." It turns accepting a rule from judgement into measurement and
makes a language model safe to use for drafting: it can only propose things
already scored against reality.

#### 9.2 Production

Two tiers of failure.

**Per row → queue it; the batch proceeds.** Do not hold 58 confident bookings
hostage to 2 ambiguous ones.

**Per batch → write nothing.** Checked before anything is written:

- coverage drop: the share decided by rules and kNN falls below its rolling
  baseline;
- a spike in LLM fallback, usually a changed memo format;
- an unusual share of proposals pointing at rarely used accounts.

The first two are drift detection: they catch the failure where everything
still works and precision quietly degrades.

A failed read-back or assertion after writing restores the previous file
(§10.3), so no failure leaves a partial batch.

#### 9.3 Version gate

Recorded per successful trial: rule-file hash, steering-document version,
model ID and configuration, kNN index version, normaliser version, the
producer strings of the statements used, the Beancount version, and the items
proposal 0002 adds. Production refuses (exit 3) when the current tuple differs
from the last validated one. A changed producer string means a converter
plugin was updated; that can change every memo without any Autobook code
changing.

A refusal writes nothing. The ledger is a text file and stays usable.

### 10. The ledger

#### 10.1 What Autobook may write

One file, the **owned file**, named in the configuration. `autobook init`
creates it and prints the `include` line; the user adds that line. Autobook
never edits any other file.

- It writes **transactions only**: never `open`, `close`, `balance`, `pad`,
  `price`, `commodity`, `plugin` or `include`. Accounts encode how someone
  thinks about their money and may map to tax categories. Balance assertions
  are the user's independent check on everything Autobook does.
- One exception, required by Beancount: an included file does not inherit the
  main file's `name_assets` … `name_expenses` options (verified: the parser
  rejects renamed roots in an include that does not repeat them). `autobook
  init` copies those five options into the owned file's header, and every run
  compares them with the main file's.
- The owned file is not private. The user may correct an entry in it, and Fava
  can edit or delete entries in any included file. So the writer never
  regenerates the file: it appends, and on undo removes exact spans.

#### 10.2 A created entry

```beancount
2026-07-14 * "REWE SAGT DANKE"
  autobook-id: "AB-01JZ8M3Q6T5W9X2C4V7B1N0PKD"
  Aktiva:Bank:Girokonto   -42.90 EUR
  Ausgaben:Lebensmittel    42.90 EUR
```

- The flag is `*`: the row was approved in the saved review file.
- **The proposal ID** is `AB-` and a ULID, generated once per staged line and
  stored in staging. Only a value matching `^AB-[0-9A-HJKMNP-TV-Z]{26}$` in
  `autobook-id` counts as Autobook's. It is written on entries Autobook
  creates and on nothing else.
- Every posting carries an explicit amount. Autobook never leaves one for
  Beancount to fill in.
- Money is `Decimal` built from integer cents and printed with exactly two
  decimals. A float never reaches `Decimal`.
- A linked bill (proposal 0002) adds `autobook-doc: "<URL>"`.

The exact bytes — key names, ordering, quoting, the header — are a contract
with other tools and with Autobook's own undo. They get a specification under
`docs/design/specs/` when the writer is built.

#### 10.3 Apply

`apply` first takes the writer lock (§10.6) and holds it until staging is
updated after step 7 or 8.

1. **Read.** Load the ledger: errors, accounts, existing Autobook IDs, and the
   SHA-256 of every file. The owned file must be among them, with matching
   root-name options. Otherwise exit 4.
2. **Filter.** Drop rows whose proposal ID is already in the ledger, and
   matched rows whose matched entry is recorded in staging and still present.
3. **Check each row.** Both accounts open on its date; its currency declared
   on the source account and allowed on the other; postings in whole cents
   summing to exactly zero. A row that fails is queued.
4. **Render** the entries; the new content is the current owned file plus the
   entries.
5. **Compare, then replace.** Re-hash every file. If any differs from step 1,
   stop: exit 4, nothing written. Otherwise write the batch journal (§10.4),
   then write a temporary file in the same directory, flush it to disk, and
   rename it over the owned file. The journal keeps the previous content
   until step 7 has passed and staging is updated.
6. **Read back.** Load the ledger again.
   - Every **created** row's proposal ID appears exactly once, with the
     approved date, accounts and amounts.
   - A **matched** row wrote nothing, so its ID is not looked for. Its
     recorded entry must still be present, with a posting of the row's amount
     in the row's source account.
7. **Assert.**
   - The load reports no error that step 1 did not report.
   - No byte of the owned file before the appended entries changed, and no
     other file changed.
   - The balance of every account the batch wrote postings to moved by exactly
     the sum of those postings, and no other account's balance moved. A
     matched row writes no posting and moves nothing.
   - Where the statement states a closing balance: the ledger's balance on the
     closing date equals it, minus the statement's lines not yet applied
     (queued, out of scope, pending transfer). A matched line counts as
     applied: its posting is already in the ledger.
8. **On any failure in 6 or 7,** restore the previous content — only if the
   file still holds exactly what step 5 wrote — exit 6, and mark nothing
   applied. A row is `applied` only after step 7 passes.

Autobook checks the sum itself because Beancount's check is tolerant: it
infers a tolerance of half the last printed digit, so two-decimal postings off
by half a cent load without error (verified: `10.00` against `-9.995` passes).

A ledger that already has errors can still be booked into; only a *new* error
rolls a batch back.

#### 10.4 Idempotency

Two stores, ledger and staging, with no shared transaction. A crash between
"file replaced" and "marked applied" leaves them disagreeing. Two things settle
it.

**The proposal ID** in the ledger: before each batch the reader finds created
rows by ID and drops them, so nothing is created twice.

**The batch journal.** Finding a batch's IDs in the ledger proves the entries are present, not that
the batch passed its checks. So the writer keeps a **batch journal** beside the
staging store. It is written and flushed to disk before the rename in step 5,
and holds: the batch and its proposal IDs, the SHA-256 of the owned file before
and after the replace, the previous content, the errors the first load
reported, and the source-account balances from the first load. It is removed
only after staging is updated.

Every `apply` and `undo` first looks for a journal, under the writer lock:

- The owned file has the journal's *before* hash: the replace never happened.
  The journal is discarded and the batch is applied from the start.
- It has the *after* hash: the batch was written and never validated. Steps 6
  and 7 run now, against the journal's baseline and not against the ledger as
  it stands. If they pass, the rows are marked applied. If they fail, the
  previous content is restored (exit 6).
- It has neither: someone changed the file since. Autobook touches nothing,
  marks nothing applied and exits with code 4; `autobook status` shows the
  interrupted batch for the user to resolve.

A row is therefore never `applied` without having passed the read-back and the
assertions, also after a crash.

Because the ID is in the ledger, an entry the user later corrected is still
recognisably Autobook's. `autobook status` lists Autobook entries that differ
from what staging recorded, and proposal IDs that staging holds as applied but
the ledger no longer contains. Both are reports, never writes: a missing entry
is not silently created again.

#### 10.5 Undo

Undo removes an entry only if its `autobook-id` is the proposal ID of a staged
row with disposition `create` or `create_split` in that batch **and** the
entry is in the owned file; both are asserted first. It removes exactly that
entry's lines, through the same compare-and-replace and read-back as apply. An
entry the user edited is still removed, with its differences listed before
confirmation. Undo of a matched row changes staging only.

#### 10.6 No ledger lock; one writer lock

Beancount has no lock, so nothing stops an editor or Fava from changing a
file. The guards are compare-before-write on every ledger
file (the same check Fava's editor makes before saving), a single atomic
rename so no reader sees a half-written file, and the read-back with the
previous content kept. Fava notices the change and reloads. An editor holding
unsaved changes to the owned file is not covered; see *Risks*.

Two Autobook runs are a different matter: both could pass the compare before
either renames, and the second would overwrite the first. So `apply` and
`undo` take Autobook's own **writer lock** (an advisory lock on a file
beside the staging store, never in the ledger's directory) before the first
read and hold it until staging is updated. A run that cannot take it writes
nothing and exits with code 4. The lock binds Autobook only; editors and
Fava do not know it.

### 11. Staging

SQLite under `$XDG_DATA_HOME` by default; a PostgreSQL URI as an option.

```
statements(
  checksum,                                    -- PK; of the OFX file
  source_account, producer,                    -- producer string from the driver, or NULL
  period_start, period_end,
  opening_balance, closing_balance,            -- integer cents, NULL if absent
  status, reason, admitted_ts                  -- admitted|rejected
)

proposals(
  source_account, line_key,                    -- PK; bank ID, or (checksum, ordinal)
  statement_checksum,
  proposal_id,                                 -- AB- + ULID
  post_date, amount, currency,                 -- amount in integer cents
  raw_memo, normalised_memo,
  disposition, queue_reason,
  proposed_account, confidence, method,        -- rule | knn | llm
  rule_id,
  status,                                      -- pending|approved|rejected|applied
  applied_entry,                               -- created: the row's proposal ID. matched: the entry's
                                               -- autobook-id if it has one, else its content hash
  batch, human_correction,
  classifier_version, normaliser_version, ts
)

transfers_pending(
  counterpart_account, amount,
  window_start, window_end,
  proposal_id
)
```

Proposal 0002 adds the document columns. Staging is the seam between
classification and writing, the audit trail, the source of `corrected` corpus
rows, and the list undo works from. It is the only component with a view
across accounts, which is why correlation lives there.

### 12. Review file

Plain text, in the idiom of `git rebase -i`:

```
# id      st  date        amount    account                    description
#   knn: Lebensmittel .81 | Haushalt .07
a1f3e9    a   2026-07-14   -42,90   Ausgaben:Lebensmittel      REWE SAGT DANKE
9de441    ?   2026-07-16   -18,50   Ausgaben:Freizeit          PAYPAL .VENDORX
```

Status: `a` accept, `?` needs a decision, `s` skip, `x` reject (recorded as a
negative example). Change an account by typing over it. Rows that passed the
gates are pre-marked `a`; everything else is `?`.

- **Saving is approving** every row marked `a`, with the account, amount and
  date shown.
- **Parse by ID, never by position.** Reordering or deleting rows must not
  misalign anything. An unknown ID is an error.
- **Strict parser.** An unknown status, an account that is not open in the
  ledger, or an amount that differs from staging aborts the whole file with a
  line number (exit 5) and applies nothing.
- The difference between what was proposed and what was saved is the training
  signal; both are recorded per row.

The file holds counterparty names. `review-file` writes it to standard output
and the driver decides where it lives; it should be private to the user and
short-lived.

Whether anything richer than this file is built is an open question.

### 13. Licence

Verified on Beancount 3.2.3: `pyproject.toml` declares `GPL-2.0-only`, the
README says "GNU GPLv2 only", and no source file grants "any later version".
beangulp and beanquery are the same. Fava is MIT.

Autobook is GPL-3.0-or-later by ADR-0002. The FSF's position is that
GPLv2-only and GPLv3 code cannot be combined into one program. **Autobook is
relicensed as GPL-2.0-or-later** and imports `beancount` in-process. This is
not legal advice.

- **Who must agree:** every contributor. Today that is the maintainer alone,
  and nothing has been released.
- **Why "or later":** distributed with Beancount the result is under GPLv2
  either way; "or later" keeps Autobook's own code usable under GPLv3 should
  Beancount ever relicense.
- **What it costs:** no Apache-2.0 library may be imported; the FSF reads
  Apache-2.0 as incompatible with GPLv2. Today the only runtime dependency is
  scikit-learn (BSD). The model adapter and the paperless client use an HTTP
  library under a compatible licence or the standard library. The gate gets a
  check on dependency licences.
- **ofxstatement** and the author's plugins are GPLv3. Autobook never imports
  them (§1), and a driver that runs both as separate commands combines
  nothing.
- **The record:** ADR-0005, which supersedes ADR-0002. `LICENSE`, `NOTICE`,
  `pyproject.toml`, `CONTRIBUTING.md` and the DCO's inbound licence change in
  the pull request that accepts it. Part of milestone B0.

### 14. Converting the GnuCash book

A one-off, attended conversion; afterwards the GnuCash book is a read-only
archive. It is a tool beside Autobook and the only remaining code that imports
`gnucash`.

**Two halves.** A full export through `python3-gnucash` in a read-only session
writes JSON; a writer with no GnuCash dependency turns that JSON into ledger
files. The export is wider than anything Autobook itself needs: all splits
with value and amount as exact rationals, commodities, the price database,
lots, transaction notes and document links, reconcile state, `online_id`, and
a count of scheduled transactions.

**Decisions, recorded in a file the user reviews.** The converter asks; it
does not guess.

| Decision | Options |
|---|---|
| Root names | Keep the book's own through the `name_*` options, or rename to Beancount's English defaults. |
| Account names | Beancount allows letters (umlauts included), digits and dashes, and each component must start with a capital or a digit. Spaces and punctuation must go. The converter proposes a rename table; it must be one-to-one. |
| Top-level accounts outside the five roots | Opening-balance and Imbalance accounts sit at the top level in GnuCash and must move under a root. |
| Transactions on the Imbalance account | Carry them to an explicit account, resolve them in GnuCash first, or hand them to Autobook as pending lines (see *Open questions*). |
| Securities | Hold at cost with lots, which needs a booking method and gain postings GnuCash never recorded; or hold without cost and convert at each transaction's total price, which reproduces GnuCash's values exactly. |
| Splits with a value but a zero amount | GnuCash allows a split worth an amount in the transaction currency with zero units of the account's own commodity. Beancount cannot express it; each pattern needs a target. |
| Reconcile state, `online_id`, memo | Drop, or keep as posting metadata. `online_id` should be kept: it is the bank's ID for lines already booked, and dedup can use it. |
| Placeholder and unused accounts | Open them, or leave them out. Open dates come from first use. |

**Verification** is mechanical, and a difference rejects the conversion:

- transaction and posting counts match, per year;
- every account's balance per commodity matches exactly at each year end and
  at the conversion date; these are written into the new ledger as `balance`
  directives;
- `bean-check` reports no error;
- the rename table is one-to-one and every exception is listed;
- each converted transaction carries its GnuCash GUID as metadata.

For scale, the author's book: about 1,400 transactions, nearly all from one
year; about 160 accounts, a third needing a rename, with no collisions under
the obvious rule. Roughly seven in eight transactions are plain two-posting,
single-currency and convert mechanically. The rest are securities and
Imbalance rows, where the decisions above apply.

Existing converters read SQLite books through piecash and do not handle lots.
They are a reference for the writer half, not a replacement.

### 15. Model backend, privacy and sharing

**Model backend.** OpenAI-compatible chat completions with a configurable base
URL. The default backend is **local**; a remote one is opt-in.

- **Redaction at the adapter boundary:** a backend receives the normalised
  merchant token, the amount and the sign — never the raw memo, never document
  content. The user can see exactly what leaves the machine.
- A **remote** backend receives a token only if it matches a rule-pack entry
  or the user's allowlist of business names; any other token makes the LLM
  abstain and the row queue. It receives the account list as numeric indices,
  never names. Novel counterparties are disproportionately doctors and
  lawyers, and an account name can itself be sensitive.

**Privacy.** Transactions are never collected or committed. Normalised memos
still carry names, IBANs, employer names and special-category data. Shared
artefacts carry patterns and categories only. User rules are personal data, in
a file separate from anything shippable.

**Sharing rules: category indirection.** A rule that targets one person's
account name is useless to anyone else. Three layers:

1. **Packs** map memo patterns to a semantic category (`groceries`,
   `insurance`). Read-only, versioned, locale-scoped, no account names. In
   their own repository; signed or pinned, because a pack influences what is
   written to a ledger.
2. The user's **category → account mapping**, derived from their own history:
   run the pack's patterns over the ledger and see where those transactions
   were booked. Thirty confirmations instead of thirty searches.
3. **User rules** target accounts directly and are never merged into a pack.

A pack is validated against the user's history before it is enabled, with the
rule builder's panel. Packs feed proposals; they never bypass review. They are
a cold-start aid, not a research programme.

### 16. Build order

Architecture chapter 9 governs the order and already follows this table. Step numbers of the earlier proposals are kept where a step
survives, because issues refer to them.

| Order | # | Milestone | Proves |
|---|---|---|---|
| 1 | **B0** | ADR-0005 accepted and the licence files changed (§13). Spikes, recorded as tests: a reader that emits `coa` and `corpus` from a synthetic ledger; content-hash stability; the root-name options check; what Fava and common editors do when the owned file is replaced under them. | The licence, and the facts the write path rests on. |
| 2 | **B1** | Conversion (§14). Human-run, attended. | The converted ledger equals the book. **Decision point: this proposal is accepted or reworked.** |
| 3 | 2 + R1 | Corpus, rule mining, kNN, rolling-origin backtest. No writes, no LLM. The corpus contract is unchanged, so this can run on a corpus from the GnuCash export and need not wait for B1. | **The premise**: mined rules decide the head at measured precision, and history is dense and consistent enough for kNN to abstain reliably on the rest. **Decision point.** |
| 4 | D0 + D2 | The paperless spikes of proposal 0002's D0 that concern bills, then the linkage backtest. | Whether linked bills resolve a meaningful share of the residual. **Decision point for 0002.** |
| 5 | 3 | OFX input, admission, staging, dedup. | Statements become staged lines with stable keys; a bad statement is rejected whole. |
| 6 | 6 + R2 | Review file with its strict parser; rules file, rule engine, candidate file for mined rules. | **The loop closes**: statements in, proposals shown, decisions recorded. Nothing is written yet, so shadow mode is the default state. |
| 7 | 4 | Correlation: transfers within and across batches, `match_existing`. | No transfer booked twice. |
| 8 | 5 | Ledger writer: `init`, apply, read-back, assertions, undo, the entry-format specification. | Writes are exact, whole or nothing, idempotent and reversible. |
| 9 | D3 | Bill linking; `autobook-doc` on created entries. | Links are right and change nothing else. |
| 10 | 7 + D4 | Shadow evidence, continuous from step 6. | Per-method, per-band precision that justifies every threshold. |
| 11 | 8 | LLM tail, LLM rule drafting, thresholds on evidence. | More rows pre-marked at measured precision. |
| 12 | 9 | Category indirection, packs, packaging. | Usable by others. |

Step 4 comes before step 5 for a reason that is not preference: a writer
without the correlation pass double-books every transfer.

Dropped from the earlier order: step 0's GnuCash spikes, D0's spikes on
statement files and on setting a document link, step 1 (Scheduled
Transactions), D1 (statements from paperless — the driver's now), and the
windows of step 9.

**Tests.** Everything runs in `nox -s gate` against synthetic ledgers in
temporary directories, on every supported Python version. The Docker test
environment keeps paperless; its GnuCash image stays only for the conversion's
export half and is removed with it. A real ledger, or a copy of one, is opened
only by a human, attended. Test fixtures never contain a real transaction.

### 17. Rules for anyone writing code

These replace the GnuCash-specific hard rules; `AGENTS.md` states them in
full. The classification, privacy and review-file rules there are unchanged.

- **Only the ledger package imports `beancount`.** Nothing imports
  `ofxstatement` or `gnucash`.
- **Write only to the owned file, and only transactions.** Never `open`,
  `close`, `balance`, `pad`, `price`, `commodity`, `plugin` or `include`.
- **Never change an entry Autobook did not create.** Nothing is written to a
  matched entry.
- **`autobook-id` only on entries Autobook creates.** Only a value matching the
  proposal-ID pattern counts as Autobook's.
- **Money is exact.** `Decimal` from integer cents, two decimals when printed.
  Never a float, in any code path, including tests and fixtures. Rules files
  use `cents:`.
- **The currency is read, never assumed.** From the statement, checked against
  both accounts' `open` directives.
- **Every posting has an explicit amount, and postings sum to exactly zero.**
  Autobook's own check; Beancount's is tolerant.
- **Compare before replacing.** Nothing is written if any ledger file changed
  since it was read. The replace is one atomic rename.
- **Read back, then report.** A row is `applied` only after the read-back and
  every assertion have passed.
- **A failed read-back or assertion restores the previous file.** No partial
  batch, ever.
- **Assertions go through the reader.** Nothing outside the ledger package
  parses ledger text.
- **A statement is admitted whole or not at all.**
- **A transfer is booked once.** Every transfer line goes through a
  source-account `match_existing` search before classification.
- **`match_existing` searches the source account** and never guesses between
  candidates. Claims are per source account, so the second side of a transfer
  can match the entry the first side created.
- **One Autobook writer at a time.** `apply` and `undo` hold the writer lock
  from the first read until staging is updated.
- **An interrupted batch is validated before it counts.** The batch journal
  is written before the replace. A later run that finds it runs the read-back
  and the assertions against the journal's baseline, or restores the previous
  content. IDs found in the ledger prove presence, not validation.
- **Idempotency on re-run.** Created rows are found by ID before each batch.
  A proposal ID that staging holds as applied and the ledger lacks is
  reported, never re-created silently.
- **Undo is narrow.** It removes an entry only if its ID belongs to a created
  row of that batch and the entry is in the owned file; both are asserted.
- **A refusal writes nothing.**

## Relation to the other proposals

**0001 and 0003 are replaced.** What is deliberately not carried over:

| From | Dropped | Why |
|---|---|---|
| 0001 | The book process, sessions, lock handling, per-backend persistence, the launcher that always reaches `exec gnucash` | They guarded GnuCash's engine. §10 replaces them. |
| 0001 | *Defer to GnuCash*; assistant detection and handoff; scheduled-transaction occurrences and the queue reason "awaiting scheduled transaction" | Beancount has no assistants and no scheduled transactions. Recurring debits are ordinary rule candidates; loans are queued (§8.1). |
| 0001 | Running ofxstatement inside the pipeline; plugin versions in the version tuple; the plugin declaring its IDs bank-supplied | Autobook is handed OFX (§1). The producer string and the configuration take their place. |
| 0001 | The Imbalance assertion | Beancount has no Imbalance account. "No new load error" and the exact-sum check replace it. |
| 0001 | Platform limits from the bindings; the upstream GnuCash track; the rejected alternatives about GnuCash (CSV import, piecash, Bayes seeding, in-app plugin, raw SQL, C++ applier) | Moot. |
| 0001 | Backups by file copy or `pg_dump` | The writer keeps the previous content for the run. Keeping the ledger in git is recommended, never required. |
| 0003 | GTK4 windows that look like GnuCash; `autobook run`, `gui`, `backup`, `assistants` | The windows were justified by GnuCash's users. The journey belongs to the driver. The remaining verbs, `--json` and the exit codes are §4. |

**0002 still applies, with these changes:**

| 0002 says | Now |
|---|---|
| §3.1 Discovery: Autobook finds and downloads statements from paperless | The driver's. Milestone D1 leaves Autobook. |
| §2: statement lines come from the original file parsed by its plugin, never from OCR text | Outside Autobook, which sees only the OFX (principle 6). |
| §3.2–3.4 Admission, balance check, dedup, overlap rule | Stay, applied to the OFX file (§5). |
| §6.1: a document link on `create` and on `match_existing` | `autobook-doc` on created entries. On a match nothing is written; the link is in staging only. |
| §6.2: the optional paperless stamp holds the transaction GUID | It holds the proposal ID. |
| §4.3: recurring fixed-amount charges go to Scheduled Transactions | Ordinary rule candidates. |

**0004 still applies, with one change:** its exclusion of schedulable
recurring debits from mining (§2, *Never mined*) is removed. They are mined
like any other group and mostly become creditor-ID rules.

## Alternatives considered

| Option | Why not |
|---|---|
| **Stay on GnuCash** | Most of that design's hard rules guard the engine, not the bookkeeping. The classification design does not depend on it. |
| **Support both ledgers** | Doubles the write path, the part where a mistake is silent, for a tool with one maintainer. The contracts keep it possible. |
| **Start the ledger from opening balances, no conversion** | Loses the booking history that rule mining and kNN learn from. |
| **Autobook as the driver** | Ties Autobook to how one person gets statements, and would put GPLv3 ofxstatement in one process with GPLv2-only Beancount. |
| **Keep GPL-3.0-or-later with a separate GPL-2.0-only reader program** | Keeps the licence and costs a second package released in step with Autobook, a subprocess on every read, and no direct use of Beancount's loader or content hash. |
| **Keep GPL-3.0-or-later, using only `bean-check` and `bean-query`** | Everything Autobook reads would come through beanquery's text output. |
| **Build on beangulp** | A framework for extracting entries from files, with duplicate detection but no staging, no correlation across accounts, and no review step with recorded decisions. A beangulp front end can be added later. |
| **smart_importer for classification** | Trains a linear classifier on the ledger and applies every prediction, with no threshold and no abstention. A useful extra baseline in the backtest. |
| **beancount-import** | The closest existing tool: it proposes the unknown posting, marks what it cannot predict, and a human confirms each transaction in a web UI. Per-transaction confirmation is what Autobook exists to remove, and it has no rule tier with measured precision. |
| **Insert entries into the user's own files** | Rewriting files Autobook does not own. "Never change what the user wrote" is cheapest to keep when it is structural. |
| **Let Beancount fill in the second posting** | An elided amount hides exactly the error §10.3 checks for. |
| **Sentence embeddings for kNN** | A model download, results that differ across versions, and help only for merchants that are lexically new but semantically familiar, which fall through to the LLM anyway. |
| **Pooled kNN indices or a shared transaction corpus** | The label space is per ledger, and transactions are special-category personal data. Sharing happens at the category level, through packs. |

## Graduation criteria

1. **B0.** ADR-0005 is accepted and the licence files are
   changed. A reader emits `coa` and `corpus` for a synthetic ledger, with
   `beancount` imported only inside the ledger package. The spikes are tests.
2. **B1.** On the author's book, the verification in §14 reports no
   difference, and every exception is in the decision file.
3. **Step 2.** The backtest reports per method and per band, on the novel
   stratum, with token-Bayes as the control (the premise test, and proposal
   0004's R1).
4. **Step 3, admission** — by test: each rejection reason in §5 rejects the
   whole statement and stages nothing; the same file twice changes nothing.
5. **Step 5, the writer** — by test, on synthetic ledgers:
   - a batch with one row that fails the reload leaves every file
     byte-identical;
   - a re-run after a crash at each point between rendering and "marked
     applied" creates nothing twice;
   - a crash after the replace of a batch that introduces a load error: the
     next run restores the previous content and marks nothing applied;
   - a crash after the replace, then a foreign edit to the owned file: the
     next run touches nothing and reports the interrupted batch;
   - a change to any ledger file between read and replace stops the write;
   - a batch holding one created row and one matched row applies: the matched
     row's ID is not required in the ledger and its amount is not counted as
     balance movement;
   - of two `apply` runs started together, one books and the other writes
     nothing;
   - the second side of a transfer matches the entry the first side created,
     once, and a third line with the same amount does not;
   - postings off by one cent, and off by half a cent, are both refused;
   - undo removes exactly the batch's created entries, including when
     unrelated entries were added to the owned file afterwards;
   - a ledger with existing errors can be booked into, and a new error rolls
     the batch back;
   - a mismatch in the root-name options refuses the run;
   - a proposal ID missing from the ledger is reported and not re-created.
6. **Reversal.** Any batch is reversed by `autobook undo`.

## Risks

What misreports silently if this is subtly wrong:

- **An OFX file that is wrong but consistent.** A conversion that drops a line
  and still states balances that add up, or states no balances, passes
  admission. The closing-balance check catches a missing line only where a
  balance is stated; elsewhere only the user's own `balance` assertions do.
- **A driver that changes memos.** Classification degrades quietly. The drift
  gates and the producer string are the only defence.
- **An edit lost under an open editor.** If the owned file is open with
  unsaved changes when Autobook replaces it, the editor decides what happens
  on save. One that does not warn would overwrite the batch. `status` and the
  next run report the missing IDs; nothing is re-created silently.
- **A matched entry edited afterwards.** The claim is lost (§8.2), and a later
  line with the same amount in the window could match it. Two payments would
  then be one entry and the account short by one. The closing-balance check
  catches it where a balance is stated.
- **Tolerance.** If the exact-sum check were skipped on some path, Beancount
  would accept a half-cent error.
- **Conversion decisions.** A wrong choice for securities or zero-amount
  splits produces a ledger that balances and is wrong. The comparison is exact
  for units; it does not prove a gain went to the right account. Those rows
  are listed for review, not sampled.
- **A plugin that rewrites entries.** A user's Beancount plugin can change
  transactions at load time, so an entry may not read back as written. The
  batch rolls back: loud, but it blocks booking until resolved.
- **Licence.** A later Apache-2.0 dependency would be a violation, not a
  ledger error. It needs the gate's check, not a habit.

## Backward compatibility

- **Staging.** No production staging data exists; the schema in §11 is the
  first released one.
- **Code.** The implemented modules — normaliser, kNN, backtest, `corpus`
  parsing — have no GnuCash dependency and stay. The `coa` contract and its
  tests, the synthetic-book builder under `tests/book/`, and the stubs under
  `autobook.book` change. The linter's ban on `gnucash` gains `ofxstatement`
  and a rule confining `beancount` to the ledger package.
- **Rules and the index.** Account names in rules follow the conversion's
  rename table. The kNN index is rebuilt on every run in any case.
- **Documents.** Proposals 0001–0004 are drafts, so none is frozen. ADR-0002
  is accepted and is superseded by ADR-0005. ADR-0001 and ADR-0003 mention
  GnuCash in examples only. `AGENTS.md`, the README and the architecture
  chapters already describe this design.
- **The interim tool** (`autobook-2025`) books into the GnuCash book. It
  finishes, or stops, before the export that B1 converts.

## Open questions

- **Bill matching.** Proposal 0002 has Autobook read bills from paperless as
  evidence for classification. This design leaves that in Autobook. If
  Autobook should not talk to paperless at all, the driver would hand over
  bill candidates in a file, and 0002 §4 needs its own amendment.
- **Rows on the Imbalance account at conversion.** They are bank lines that
  were imported and never classified. Carried over as transactions, Autobook
  can never fix them, since it does not change existing entries. The
  alternative is for the converter to leave them out of the ledger and hand
  them to staging as pending lines, to be booked through the review file. That
  needs its own check that the balances still agree afterwards.
- **`balance` directives from statements.** A statement's closing balance is
  the bank's figure. Writing it as a `balance` directive once every line is
  applied would make the check permanent, and would put a standing error into
  the ledger whenever the user and the bank disagree. Not in v1.
- **Corrections made in the ledger.** Whether an Autobook entry whose account
  the user changed counts as a `corrected` corpus row.
- **Payee.** Whether the payee field carries the normalised merchant token,
  with the raw memo as narration.
- **File layout.** One owned file, or one per year behind a glob `include`. A
  glob that matches nothing is a load error, so the first file must exist.
- **The driver contract.** Whether OFX files and a producer string are enough,
  or whether `propose` should also take the original statement's checksum, so
  that a statement converted twice is recognised.
- **A richer review surface.** None, a Fava extension, or a terminal UI.
  Decide at step 12, on what the review file has turned out to lack.
- **Expected transactions.** Third-party tools (beanahead, beanschedule) add
  expected future entries to a ledger. Whether `match_existing` should treat
  them specially is deferred until someone uses one with Autobook.
- **Synthetic corpus rows.** Deferred, as before: they would make a novel
  merchant look familiar and invalidate the backtest.
- **Where the conversion tool lives** after B1.

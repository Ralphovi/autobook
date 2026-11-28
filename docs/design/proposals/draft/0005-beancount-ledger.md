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
| `autobook forget PATH` | Remove the staging record of a pre-image the user has deleted; refuses while the file exists | writes staging (under the writer lock) |
| `autobook status` | Last run, pending counts, the version tuple in force, entries that differ from staging, kept pre-images whose content changed. | read |
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
| 4 | The ledger is not writable as expected: the owned file is not included, its root-name options differ from the main file's, a ledger file changed during the run, another Autobook run holds the writer lock — or a **conflict**: the owned file was saved, or its permissions changed, during the write | nothing, in a refusal. In a conflict, staging records nothing as applied, but the entries may still be in the ledger (a save that kept them, such as an edited narration, stays at the owned path): the user's saved version is at the owned path, every displaced version is kept as a file beside the journal, and `autobook status` names them; the driver reports a conflict for the user to resolve, not a clean refusal, and must not retry until `autobook status` shows it resolved |
| 5 | The review file did not parse; the line number is on standard error | nothing |
| 6 | The read-back or an assertion failed; no row of the batch was committed | nothing of Autobook's remains: the owned file holds its previous content again. A change to another included file that caused the failure is someone else's edit and is left as it is. If the batch was exchanged in, the previous file was restored and the rejected batch is kept as a pre-image beside the owned file and recorded in staging; a matched-only batch wrote nothing, so there is nothing to restore and no pre-image |
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
  resolve (proposal 0002 §3.4);
- for an account whose IDs the configuration declares **bank-supplied**: a
  line repeats a known bank ID with a different date, amount or currency, or
  a bank ID occurs twice in the statement (see *Dedup*). Synthesised IDs can
  collide legitimately (two identical payments) and go to the count-aware
  overlap rule instead.

Every decision is recorded in `statements` with the file's checksum. Handing
over a file that was already **admitted** changes nothing. A file that was
**rejected** is checked again from the start, so a statement rejected for a
reason outside the file (an account ID missing from the configuration, an
account not yet opened in the ledger) is admitted once that is fixed.

**Dedup.** A line is identified within its source account by the bank's ID
when the configuration says the IDs are bank-supplied. A bank ID that occurs
twice **within one statement** rejects the statement whole ("duplicate bank ID
in the statement"): the two lines would collide on one staging key. A later statement that
repeats a bank ID reuses its proposal only if the date, amount and currency
agree; a different memo is recorded but is not a conflict. If any of the three
differs, the bank changed a fact, and the whole statement is rejected
("conflicting line for a known bank ID") for the user to resolve; a
correction is never silently dropped. Otherwise the ID is
synthesised by the converter (a hash of date, memo and amount, so two
identical card payments on one day collide) and is not trusted as an identity:
the line takes the key `(statement checksum, ordinal)` and the overlap rule
decides whether a later statement repeats it. The overlap rule compares lines
count-aware on `(post_date, amount, currency, raw_memo)`: proposal 0002 §3.4's
tuple plus the **currency**, since an account may hold several and the same
number in another currency is a different line.

**Membership.** A line repeated by a later statement keeps its one proposal,
but belongs to both statements. `statement_lines` records every admitted
statement's lines, the reused ones included, so the closing-balance assertion
(§10.3 step 7) can find each statement's lines not yet applied from staging
alone.

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
- **Both sides staged before either is booked.** When both statements arrive
  before either side is in the ledger, neither search finds anything. So the
  correlator also pairs unbooked staged lines: two lines in two of the user's
  accounts, with opposite-signed amounts in the same currency, within the
  window, each pointing at the other's account (the amounts may differ by a
  fee). **Both sides are classified first**, so each has its proposed
  postings (a −105 line's +100 transfer and 5 fee split). Then the side whose
  proposed entry represents both movements goes on; the other is queued as
  "pending transfer" and resolves through `match_existing` once the first is
  applied. The configuration order (the **canonical side**, the account
  listed first) decides only when both sides represent both movements; when
  neither does, both are queued ("transfer amounts disagree"). An ambiguous
  pairing (two possible counterparts) queues both.
- The first side of a transfer records a `transfers_pending` entry **at
  proposal**, not only once booked, so the reservation exists before either
  side reaches a batch: counterpart account, amount, currency, date window, its proposal ID.
  A pending-transfer lookup requires the currency to be equal too; the same
  number in another currency is not the counterpart.
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
appears in the review file as `?`. Where it has no usable destination (none
proposed, or one not open on the line's date), its account column shows the
placeholder `(none)`; the parser accepts `(none)` on a row left at `?`, `s` or
`x`, and aborts only when a row marked `a` has `(none)` or an account that is
not open. A queued row saved unchanged therefore never blocks the rest of the
file.

A payment whose parts change every period — a loan instalment's interest and
principal — cannot be split from the statement line. It is queued. If the user
writes that entry by hand, the line resolves as `match_existing`.

#### 8.2 `match_existing`

The statement line is already in the ledger: the user wrote it by hand, or it
is the second side of a transfer.

- **Search** the line's **source** account for an entry whose **net movement
  in that account and currency** equals the line's amount — the sum of all
  its postings there, so an entry with −100 and +20 in the account (net −80)
  does not match a −100 line — within ±5 days, that is not already claimed
  for that source account. Whether
  the user has asserted a balance since is not a filter.
- **Unambiguous** → nothing is created. Staging records the candidate in
  `matched_entry`; `applied_entry` is set only once the batch has been
  validated.
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
when **another** staged row of that account that is still `pending`,
`approved` or `applied` refers to it — a row's own `matched_entry` never
excludes its own candidate, and a `rejected` or `skipped` row releases its claim: the row that created
it, through its proposal ID (the entry's `autobook-id`) once it is `applied`,
or a row that matched it, through `matched_entry` from proposal on, not
only through a validated `applied_entry`, so two pending rows cannot select
the same entry. The claim lookup covers both: `matched_entry` alone would
leave a created entry unclaimed in its own account, and a second payment of
the same amount there would match it. This is what lets a transfer resolve. The first
side, booked from account A, creates an entry with a posting in A and one in
B. That entry is claimed for A and not for B, so the second side's search in B
finds it, matches it once, and claims it for B. An `autobook-id` alone does
not make an entry unavailable.

If the user later edits a matched hand-written entry, its hash changes and the
staged row no longer finds its entry. The claim is **not** dropped: it becomes
an *orphaned claim*. Autobook cannot tell which entry the edited one is, so
while an orphaned claim exists, **matching is paused for that whole source
account**: every line that would go through `match_existing` there is queued
with the reason "a matched entry changed". `autobook status`
lists orphaned claims. Otherwise the edited entry would be a later line's only
candidate and two payments would become one entry.

**Rebinding an orphaned row.** The orphaned row returns to the review file as
`?`, with its account shown as `(orphaned match)`. Under it, one line per
entry that passes the row's match predicate (source account, amount,
currency, date window, not claimed for that account by another row); each line
shows the entry's date, amount, other account and narration, and its ID is the
row's ID, `.m` and the first 12 hex digits of the entry's content hash
(`9de441.m3fa9c2e1b7d0`), so it is parsed by ID, never by position:

```
9de441          ?   2026-07-16   -18,50 EUR   (orphaned match)       PAYPAL .VENDORX
9de441.m3fa9c2e1b7d0  -   2026-07-16   -18,50 EUR   Ausgaben:Freizeit   PayPal Vendor X
```

The user resolves the orphan in one of two ways; nothing else is accepted for
an orphaned row, and the strict parser aborts on anything else (exit 5):

- **`m` on exactly one candidate line** rebinds the row. `decide`, under the
  writer lock, runs the predicate again on the loaded ledger: the chosen entry
  must still pass it, and its hash prefix must name exactly one candidate.
  Otherwise the parse aborts (exit 5) and nothing is recorded. On success
  `matched_entry` becomes that entry's canonical identity, the same as for an
  ordinary match: its `autobook-id` if it has one, otherwise its content hash.
  The hash prefix only selects the line; storing the hash for an entry
  Autobook created would escape the claim and dependent-undo checks, which
  know that entry by its proposal ID. The old value is kept in
  `human_correction`, `match_source` becomes `rebound`, `applied_entry` is
  cleared in the same transaction, and the row is `approved`; `applied_entry`
  is set again only after the read-back, so step 2 never drops the row on the
  strength of the old entry. The candidate line stays in the review file
  regenerated from it. An `m` under a row that is not orphaned aborts the parse
  — except under a row already rebound (`match_source = rebound`, not yet
  applied) where the marked candidate's hash prefix is the recorded entry:
  that is the same rebind seen again, for example when `apply --from` runs on
  the file `decide` already recorded, and it counts as that row's approval.
  A different candidate under a rebound row aborts the parse.
- **`x` on the row** releases the claim and rejects the row: the line is not
  booked by Autobook, and the user books it by hand if it is real.

Leaving the row at `?` keeps the orphan, and matching in that account stays
paused. An edit that changed the entry's amount, currency or date beyond the
window leaves no candidate, so only `x` remains; Autobook never rebinds to an
entry that its own search would not match. For a rebound row, apply (§10.3
step 3) and the read-back require the recorded entry to pass the predicate and
be unclaimed by another row, rather than to be the only candidate, because
the user chose between candidates. Matching in the account resumes once no
orphaned claim is left in it.

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
from the last validated one — at `propose`, and again at `decide` and `apply`
before any decision is recorded (§10.3). A changed producer string means a converter
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

`apply` first takes the writer lock (§10.6), then recovers any journal and
checks the kept pre-images (§10.4, §10.6), and only then parses the review file
and records decisions. Before it records any decision it checks the
**version gate** (§9.3) again: the current version tuple must equal the last
validated one, and the classifier and normaliser versions every row in the
file was proposed under must be current; otherwise exit 3, nothing recorded —
a review generated before a rule or model change is re-proposed, not booked.
**The file must be the current review.** `review-file` writes a header line
`# autobook-review <ULID>` and records that review in staging (`reviews`)
with the version tuple and each row's revision; a re-proposal of a row
increments its `revision`. `decide` and `apply` refuse (exit 3, nothing
recorded) a file whose header is missing or names no recorded review, whose
review's tuple is no longer the validated one, or that lists a row whose
revision has changed since the review was written. An older review of a
re-proposed row can therefore never pass as an account edit.
**The batch is exactly the rows marked `a` in this file**, plus orphaned rows
rebound in it with `m` (§8.2): an `m` on a candidate is that row's approval
of the match, so `apply --from FILE` validates a rebind from the same file. A row that an
earlier `decide` left `approved` but that this file omits or no longer marks
`a` is not booked, and returns to `pending`; a stored approval is never a
substitute for the file being applied. It holds the lock until staging is
updated after step 7 or 8. A run that cannot take the lock, or refuses in recovery or the pre-image
check, changes nothing, staging included.
`decide` takes the same lock, and refuses while a batch journal exists
(§10.4).

1. **Read.** Load the ledger: errors, accounts, existing Autobook IDs, and the
   SHA-256 of every file. The hashes must describe the bytes Beancount
   parsed, so the load is taken from a **snapshot**: every ledger file is read
   once into memory, hashed, and written into a private directory (mode
   `0700`) that **mirrors each file's absolute path** (`/books/ledger/main.bean`
   becomes `<snapshot>/books/ledger/main.bean`), so every relative include,
   `../` included, resolves inside the copy exactly as it does live; an
   include that would resolve outside the mirrored files is refused (exit 4)
   before Beancount runs, and Beancount loads that copy, never
   the live files. The live files and the include set are then compared with
   the snapshot; if any differs, a save got in, and the snapshot is taken
   again (up to three times, then exit 4). A save that is undone during the
   load cannot slip through, because the parse never reads the live file.
   An **absolute** `include` would bypass the copy, since Beancount resolves it
   directly; v1 therefore refuses (exit 4) a ledger with an absolute include
   path anywhere in the include tree, and the user writes it relative. Every later load (the read-back, the fresh
   load of a matched-only batch, recovery) is taken the same way. The
   **include set** is part of the snapshot: the list of files the load
   resolved (globs expanded) is recorded, compared before and after each
   load, and compared again with every re-hash before the exchange, so a new
   file that starts matching an `include` glob counts as a change. The owned file must be among them, with matching
   root-name options, and every kept pre-image must still have its recorded
   hash: a changed pre-image is a save the owned file does not contain.
   Otherwise exit 4, until the user has resolved it.
2. **Filter.** Drop rows whose proposal ID is already in the ledger, and
   matched rows that already have an `applied_entry` still present. A matched
   row approved for the first time has only a `matched_entry`, and goes on.
   **A row staging already records as `applied` whose entry is missing from
   the ledger** (the user deleted it) is excluded and reported, never booked
   again: its staged status is read before the file's decisions are
   recorded, and a saved review file does not turn it back into a create.
   The one exception is a **matched** row rebound with `m` in this file
   (§8.2): its old entry is missing because the user edited it, and the
   rebind names the new one, so it goes on to step 3 and is validated there.
3. **Check each row.** Both accounts open on its date; its currency declared
   on the source account and allowed on the other; postings in whole cents
   summing to exactly zero. **No posting of a created row is to the source
   account except the source posting**: a destination equal to the source
   account, or a split posting other than `.0` in it, would net the account
   to zero and hide the bank movement. For a matched row, the **search is run again**
   against the ledger as loaded in step 1: exactly one candidate must remain,
   and it must be the row's `matched_entry`; the account must have no orphaned
   claim. For a row rebound by the user (§8.2), the recorded entry must pass
   the match predicate and be unclaimed by another row. **Every created row**
   is searched again in its source account, against the ledger as loaded in
   step 1, with the full match predicate: an entry the user booked by hand
   after the proposal is a candidate, and the row is queued ("needs a match
   decision") rather than duplicating it. **A created row
   whose destination is another of the user's own accounts** (a transfer,
   also one the user made so by editing the account) is searched again too,
   in its source account and in its destination account, against the ledger
   as loaded in step 1: if either search finds a candidate, the transfer may
   already be booked, and the row is queued ("needs a match decision"), never
   created. This duplicate screen **ignores claims**: an entry already
   claimed for the searched account (a transfer whose other side booked it)
   still counts as a candidate here, because it may be this very transfer; it
   only queues the row and never becomes the row's match. The same holds for **every split posting** to another of the
   user's own accounts (a transfer with a fee, for example): the row's split
   postings are **summed per account and currency** first (+60 and +40 to B
   are one +100 movement), that net movement is searched for in its account,
   and a candidate queues the whole row. **Ambiguity first:** before any
   side is chosen, every created row's eligible transfer counterparts are
   counted, in the batch and among staged rows, with the review's edits
   applied. A row with more than one — two equal debits from A to B and one
   credit from B to A — queues the whole group ("ambiguous transfer"); only
   one-to-one pairs go on to the choice below. **Batch-level:** every
   created row's **net movement in each other account of the user's** — its
   destination or its split postings, summed per account and currency, so
   +60 and +40 to B count as +100 — is compared with the source posting of
   every other created row in the batch. **Pairing does not depend on the
   amounts agreeing:** two rows in two of the user's accounts, same currency,
   within the window, each with a posting to the other's source account,
   **with opposite-signed statement amounts** (one leaves an account, the other
   arrives in the other: two independent payments A→B and B→A are both debits
   and are not paired), are treated as the two sides of one transfer whatever their amounts (−105 in A
   and +98 in B, each with its own bank's fee, are a pair). An exact pair is
   one where — the posting is in the other row's source account with the
   **same signed amount** as that row's source posting (A's entry posts
   +100 to B; B's statement line is +100 in B), the other row posts back to
   this row's source account, same currency, within the window; a fee in a
   split does not hide it — only one side stays and the other is queued as "pending
   transfer" — the balance-movement assertion would otherwise expect both
   writes and not see the duplicate. The side that stays is the one whose
   entry **represents both statement movements**: once written, the other
   side's match predicate (exact amount and currency in its own account)
   finds it. A split of A's −105 into +100 to B and a 5 fee does; B's plain
   +100 entry would put only −100 in A, which A's −105 line never matches.
   If both sides qualify, the configuration order decides (the canonical
   side); if neither does — as for −105 and +98 — both are queued ("transfer
   amounts disagree") and the user books the transfer by hand.
   **The same comparison runs against every staged row not in the batch**
   that is not yet applied (pending, approved or queued), in any of the
   user's accounts, so it does not depend on both sides being approved
   together. Pairing is the same **amount-independent** rule as within the
   batch (reciprocal accounts, opposite signs, same currency, within the
   window), using the staged row's proposed or approved postings. If a
   created row has such a staged counterpart and the row is not the side that
   represents both movements (B's plain +100 while A's −105 fee split is
   still pending), the row is queued as "pending transfer" until the
   counterpart is decided; if neither side represents both (−105 and +98),
   the row is queued as "transfer amounts disagree".
   A row that fails is queued.
   **A batch with no created rows** (only matched rows) writes nothing: steps
   4 and 5 are skipped, no journal or pre-image is made, and the ledger is
   loaded again and steps 6 and 7 run against that fresh load, immediately
   before staging is updated — the search must still find each row's
   `matched_entry`, and no ledger file and no kept pre-image may have changed
   since step 1. A failure marks nothing applied; there is nothing to restore.
4. **Render** the entries; the new content is the current owned file plus the
   entries.
5. **Compare, then replace.** Re-hash every file, the kept pre-images
   included. If any differs from step 1,
   stop: exit 4, nothing written. Otherwise write the batch journal and make
   it durable (§10.4), then write a temporary file in the same directory,
   `fsync` it, **re-hash every file and kept pre-image once more** — a save
   during that preparation would otherwise be published. If something
   changed, nothing is exchanged: the file at the pre-image path is checked
   to hold exactly the rendered content and recorded in staging (`kind =
   rejected`), the journal is removed and its directory `fsync`ed, and the
   run exits with code 4 — a later run is not blocked by a journal for a
   write that never happened. If nothing changed, **exchange** it with the owned file in one atomic step (§10.6),
   check that what was swapped out is exactly the content the batch was
   rendered from (otherwise exchange back and exit 4), and `fsync` the
   directory. The journal keeps the previous content
   until step 7 has passed and staging is updated.
6. **Read back.** Load the ledger again.
   - Every **created** row's proposal ID appears exactly once, with the
     approved date, accounts, and amounts with their currencies (each posting's
     amount and currency compared together), and with exactly one posting in its
     source account: the source posting, carrying the statement amount.
   - A **matched** row wrote nothing, so its ID is not looked for. Its
     search, run again on the reloaded ledger, must still find exactly one
     candidate, and it must be the row's `matched_entry` (for a rebound row:
     the recorded entry still passes the predicate, unclaimed by another row).
7. **Assert.**
   - The load reports no error that step 1 did not report.
   - The owned file's SHA-256 is exactly the rendered content's, and no other
     file changed. Checking only the bytes before the appended entries would
     miss an edit inside them (a changed narration keeps IDs, amounts and
     balances). The two cases are handled differently:
     - **The owned file differs** from the rendered content: a save got in
       after the exchange. It is not exchanged away. Autobook keeps that
       version at the owned path and the previous content as the pre-image,
       marks nothing applied and exits with code 4 for the user to resolve,
       as for any conflict (§10.6).
     - **Only another file changed**, and the owned file still holds exactly
       the rendered content: the batch cannot be validated, so it is rolled
       back by the checked exchange back of step 8 (exit 6). The other file's
       edit is untouched, since the restore changes only the owned file.
   - The balance of every account the batch wrote postings to moved by exactly
     the sum of those postings, and no other account's balance moved. A
     matched row writes no posting and moves nothing.
   - Where the statement states a closing balance: the ledger's balance in
     `balance_currency` at the end of `closing_balance_date` (as staged; the
     OFX file is not needed at apply) equals it, minus the lines not yet applied
     (queued, out of scope, pending transfer, skipped). The check is made
     against the state after this batch: the batch's own rows, just verified
     by the read-back, count as applied here although they are marked only
     after step 7 passes, and are left out of the candidate check below.
     Only lines in
     `balance_currency` dated on or before `closing_balance_date` are
     **subtracted**: a later line, or one in another currency, is not part of
     that balance. The **candidate check** below is wider: it also covers
     unapplied lines dated after the closing date (a July 1 line may already
     be booked on June 30), because a candidate dated on or before the
     closing date is in the ledger's balance either way. A line not yet applied
     can still be in the ledger already, for example a skipped line whose
     hand-written entry exists. So before subtracting, the writer runs each
     such line's match predicate (claims ignored), counting only candidates
     dated on or before `closing_balance_date`, since a later posting cannot
     be in the balance on that date: a line with no such candidate is
     subtracted; a line with one makes the statement's
     representation ambiguous, and the closing-balance assertion is
     **deferred** for that statement — reported in `apply-out` and by
     `autobook status`, never failed and never satisfied by marking the line
     applied. Every other assertion still runs. A matched line counts as
     applied only when its matched posting is dated on or before
     `closing_balance_date`; a line matched to a posting dated later (the
     match window reaches five days past the line) is counted with the lines
     not yet applied, since its posting is not in the balance on that date.
     The opposite crossing counts too: a line dated after the closing date
     whose matched posting is dated on or before it has that posting in the
     balance, so the posting's amount is added to the expected balance. A
     line dated after the closing date that is not yet applied but has a
     candidate dated on or before it defers the assertion, as above.
     **Counterpart postings.** A transfer Autobook created from another
     account's line (A's June 30 debit) puts a posting in this account dated
     on A's date, while this account's bank may credit it later (B's July 1).
     A posting in this account dated on or before the closing date, created
     from another account's line and not yet matched by any staged line of
     this account, is added to the expected balance **only when admitted
     statements of this account cover every date the bank could have booked
     it on** — from the posting's date minus the match window through the
     closing date — and none has a line for it: then the bank provably
     had not booked it by then. Where that span is not covered (this
     account's first statement starts June 1 and the posting is June 2, so
     the bank may have booked it on May 31 and the opening balance already
     include it), the assertion is deferred and reported. If this account's own staged line for it is dated on
     or before the closing date, it would have matched; if it exists but is
     still unapplied, the candidate rule above defers. Both arrival orders of
     the two statements give the same result.
     **An intraday cutoff.** Where `closing_balance_time` is set and is not
     the end of the day, the bank's balance may exclude some of that day's
     movements, and a date-only ledger cannot say which. If the account has
     any posting on `closing_balance_date` — in the ledger or among the lines
     not yet applied — the assertion is deferred with the reason "intraday
     cutoff" and reported; otherwise it runs as above.
     A closing balance is cumulative, so "the lines" are **every staged line
     of that source account** up to the closing date, from this statement and
     from every earlier admitted one: a January line still pending is in
     February's closing balance but not in the ledger. They are read from
     `statement_lines`, so a line an overlapping statement staged is counted
     once.
   - Every kept pre-image, this batch's included, still has its recorded hash.
     Checked **last**, after every other assertion and immediately before
     the staging commit, so a displaced save during the other checks is
     caught. This is the last check before the rows are marked applied; a mismatch is
     a save that got into an old file and rolls the batch back.
   - In the same final step, the **live ledger files and the include set** are
     re-hashed against the read-back snapshot: a save while the assertions
     ran is handled as in the hash check above (the owned file changed: a
     conflict, exit 4; only another file changed: rolled back, exit 6). A save
     that lands after this final check and before the staging commit is an
     ordinary later edit, no different from one made a minute after `apply`
     returns; `autobook status` reports any applied entry that no longer
     matches staging. No re-check can close that last instant without a
     ledger lock, which Beancount does not have.
8. **On any failure in 6 or 7,** restore the previous content — only if the
   file still holds exactly what step 5 wrote — exit 6, and mark nothing
   applied. A row is `applied` only after step 7 passes.
   The restore is the checked exchange back, followed by an `fsync` of the
   owned file's directory before the pre-image is recorded or the journal
   removed, so a power loss cannot bring the rejected entries back without a
   journal to recover them. Afterwards the pre-image path
   holds the rejected batch, and staging records it as such (`preimages.kind
   = rejected`, with that content's hash), so it is kept like any other
   displaced version but is not mistaken for a displaced save.

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
staging store. It holds everything steps 6 and 7 compare against: the
operation (`apply` or `undo`, §10.5), the batch and its proposal IDs, the SHA-256 of every loaded file from step 1, the SHA-256 of
the owned file after the replace, the owned file's previous content, the path
of the temporary file (which holds the swapped-out content after the exchange),
the errors the first load reported, the first load's balance of every
account, and the owned file's mode, owner and group as last checked before
the exchange. It is removed only after staging is updated.

**Durability.** A journal that can be lost while the exchange survives is no
journal, and a half-written journal blocks every command without telling
recovery anything. The order is: write the journal to a scratch name
(`.journal-tmp-<ULID>`) and `fsync` it, rename it to its final name and
`fsync` its directory, so the final name only ever holds a complete journal
(a scratch journal left by a crash is removed: no exchange follows before the
rename);
write the rendered content to a scratch file (`.autobook-tmp-<ULID>`) and
`fsync` it; rename it to its final pre-image name, which the journal records,
and `fsync` the owned file's directory — so the final name only ever holds the
complete rendered content; then mark the journal **published** (rewritten
under a scratch name and renamed, like the journal itself), so recovery knows
the pre-image must exist from here on; exchange; `fsync` the owned file's directory again.
An exchange back is made durable the same way — the directory is `fsync`ed
before the pre-image is recorded or the journal removed.

**File modes.** The exchange puts the scratch file's inode at the owned path,
so its metadata becomes the ledger's. The scratch file is created with
`O_CREAT | O_EXCL | O_NOFOLLOW` and mode `0600`, then `fchmod`ed to the owned
file's current mode, so the process umask never decides who can read the
ledger. It is also given the owned file's group with `fchown` (the user must
be a member of it; otherwise the writer refuses, exit 4), since a setgid
directory or the user's primary group could otherwise hand a `0640` ledger to
the wrong group. Before the exchange the writer checks, with `fstat` on both
open files, that the scratch file has the owned file's mode, owner and group;
the owned file must belong to the running user. An owned file with a POSIX ACL or other
extended attributes is refused (exit 4) rather than silently stripped of them.
The scratch file is checked too, before its mode is widened: a default ACL on
the ledger's directory is inherited by new files, and `fchmod` would then make
its named-user and named-group entries effective while `fstat` still shows the
expected mode. If the scratch file carries any ACL or extended attribute, the
writer removes it and refuses (exit 4); it never exchanges such a file in.
The journal, which holds the previous content, and the staging store are
created `0600` in a directory of mode `0700`. A pre-image keeps the mode of
the inode it is, the owned file's old one. `autobook init` creates the owned
file `0600`.
A scratch file left by a crash holds only content Autobook rendered and never
reached the ledger, so recovery removes it. The journal's removal is likewise followed by an `fsync` of its
directory, after staging has committed.

Every `propose`, `apply` and `undo` first looks for a journal, under the
writer lock — `propose` too, so that it never classifies against a batch that
was written but not yet validated. `propose` does not recover a journal
itself: it refuses with exit code 4 until `apply` or `undo` has. So does a
`decide` that would record a decision, before it parses the review file: the
journal's batch is re-checked against `approved_account`, `approved_splits` and `matched_entry` in
staging, and a decision recorded in between would change what that batch is
checked against. `apply` and `undo` recover as follows:

- **Staging already records the batch as committed.** The staging transaction
  that marks the rows `applied` (or, for an undo, `pending`) also records the
  journal's **operation ID** as committed (`operations.committed_ts`). Each
  apply or undo attempt has its own ID, written in its journal, so an earlier
  undo of the same batch is never mistaken for this one. A crash
  after that commit and before the journal is removed leaves a journal for a
  finished operation. Recovery checks staging first: if the operation is
  committed, it only finishes the cleanup — records the pre-image if that was
  not yet done, removes the journal and `fsync`s its directory — and never
  validates or rolls back again. The cases below apply only to a batch staging
  does not record as committed.

- The owned file has the journal's *before* hash: either the exchange never
  happened, or the batch was exchanged back after a failed check. The owned
  file's directory is `fsync`ed first, since an exchange back may not yet be
  durable if the crash came right after it. Before the
  journal is discarded, the file at the journal's pre-image path is checked.
  If it is missing and the journal is not yet marked *published*, the crash
  came while the scratch file was being prepared and there is nothing to
  keep. If it is missing although the journal is *published*, a version
  Autobook was keeping is gone: the journal is kept and the run exits with
  code 4, as for any missing pre-image. If it exists, it is checked: if it holds exactly the content the batch rendered (the
  journal's *after* hash) **and** still has the mode, owner, group and ACL
  state the writer gave it, it is recorded in staging (`kind = rejected`). If
  it holds anything else, or its metadata changed, an editor saved into it or
  the user changed its permissions: Autobook records nothing,
  keeps the journal and the file, and exits with code 4 for the user to
  resolve. It is never deleted. Then the batch is applied from the start.
- It has the *after* hash: the batch was written and never validated. First
  the swapped-out file at the journal's temporary path is checked. If it is
  **missing**, recovery can neither hash it nor exchange back: Autobook keeps
  the journal, marks nothing applied and exits with code 4, naming the missing
  path, as for any missing pre-image (§10.6). If it is
  not the owned file's previous content, or its mode, owner, group or ACL
  differs from what the journal recorded at the last check (the journal holds
  that metadata), a save or a permission change got in just before the
  exchange: Autobook exchanges back, so the saved edit is at the owned path
  again, marks nothing applied and exits with code 4. Only if it is the
  previous content do steps 6 and 7 run — for an undo, its own checks
  (§10.5) —, against the journal's baseline and not against the ledger as
  it stands: the other files' hashes, the errors and the balances are the
  journal's. If they pass, the owned file's directory is `fsync`ed first —
  the exchange may not yet be durable if the crash came right after it — and
  only then are the rows marked applied (or, for an undo, returned to
  `pending`). If they fail — also
  because another ledger file changed in the meantime, so that the batch can
  no longer be validated — the previous content is restored (exit 6) and the
  batch can be applied again.
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
entry's lines, under the writer lock, through the same journal, compare-and-replace and restore-on-failure as apply. An
entry the user edited is still removed, with its differences listed before
confirmation. Undo of a matched row changes staging only. On success the
batch's rows return to `pending` and their `applied_entry` is cleared, and
each row's `revision` is incremented in the same transaction (also when
recovery completes an undo), so the saved review file the batch was applied
from no longer passes the review check and cannot book the rows again. A
matched row also releases its claim: its `matched_entry` moves to
`released_entry`, kept for the audit, and is cleared, so the row is searched
again on the next `propose` and no longer blocks undo of the batch that
created the entry.

**Undo has its own read-back.** The journal records the operation (`apply` or
`undo`), and for an undo the entries it removes. After the exchange, and in
recovery when the owned file has the journal's *after* hash, an undo is
validated by its own checks, never apply's:

- none of the removed proposal IDs appears in the ledger any more;
- the load reports no error the first load did not report;
- the owned file is the previous content with exactly the removed spans taken
  out, and no other file changed;
- the balance of every account the removed entries posted to moved by exactly
  minus those postings, and no other account's balance moved;
- every kept pre-image still has its recorded hash;
- last, immediately before staging is updated, the live ledger files and the
  include set are re-hashed against the read-back snapshot, as for apply
  (§10.3 step 7), in a live undo and in a recovered one alike.

If they pass, the rows return to `pending`; otherwise the previous content is
restored (exit 6) and the rows stay `applied`. Recovery of an undo never marks
a row applied.

**A dependent match blocks undo.** The second side of a transfer may match the
entry a first side created in an earlier batch (§8.2). Removing that entry
would leave the matching row recorded as `applied` with no entry behind it. So
undo refuses (exit 4) while any row outside the batch that is `pending`,
`approved` or `applied` has a `matched_entry` equal to the proposal ID of an
entry the undo would remove, and names those rows. The user undoes or rejects
them first; undoing a matched row changes staging only, so this order always
works.

#### 10.6 No ledger lock; one writer lock

Beancount has no lock, so nothing stops an editor or Fava from changing a
file. The guards are compare-before-write on every ledger
file (the same check Fava's editor makes before saving), a single checked
atomic exchange (below) so no reader sees a half-written file, and the read-back with the
previous content kept. Fava notices the change and reloads. An editor holding
unsaved changes to the owned file is not covered; see *Risks*.

Two Autobook runs are a different matter: both could pass the compare before
either exchanges, and the second would overwrite the first. So `propose`,
`apply`, `undo` and `decide` take Autobook's own **writer lock** — `propose`
because its match search and staging of claims must not interleave with
another run's — (an advisory lock on a
file in the store's state directory, §11, never in the ledger's directory) before they
parse the review file, record any decision or read the ledger, and hold it until staging is updated. A run that cannot take it writes
nothing and exits with code 4. The lock binds Autobook only; editors and
Fava do not know it.

**The swap.** A re-hash followed by a plain rename leaves a window: a save by
an editor or Fava between the last hash and the rename would be overwritten by
content rendered from the older snapshot, and the read-back could not tell.
So the owned file is not renamed over; it is **exchanged** with the temporary
file in one atomic step (`renameat2` with `RENAME_EXCHANGE`, Linux). After the
exchange the temporary path holds exactly what was at the owned path an
instant before. Autobook hashes it, and `fstat`s it: its mode, owner and
group, and the absence of an ACL or extended attribute, must still be what
the scratch file was given. If the user changed the owned file's permissions
after the last check, the exchange would publish the older ones, so a
metadata mismatch is handled like a content mismatch. If it is not the content the batch was
rendered from, or its metadata differs, a save or a permission change got in: Autobook exchanges back, so the saved edit is at
the owned path again, writes nothing and exits with code 4. Nothing is lost in
either order.

An editor may still hold the old file open and write to it after the exchange;
that write lands in the swapped-out file. So the swapped-out file is **never
deleted** and never renamed after the exchange. The temporary file gets its
final name before the exchange, once its content is complete (see
*Durability*): `.autobook-preimage-<batch>-<ULID>` beside the owned file, unique
to that apply or undo, and named in the journal. After the exchange that file is
the pre-image, at the path the journal already records, so a crash at any
point leaves recovery a path that exists. Before the journal is removed, the
pre-image's path, batch and the hash it had when swapped out are recorded in
staging (`preimages`); recovery repeats that step if it was interrupted. It never
leaves the owned file's file system: a move across file systems would be a
copy, which detaches an editor's open file and makes its later saves
invisible. `autobook status` re-hashes every kept pre-image and reports one whose
content changed since, because that is a save the owned file does not contain.
Every `propose`, `apply` and `undo` re-hashes the kept pre-images before it
reads the ledger — `propose` too, because a ledger missing a displaced save is
incomplete history to classify against — again in step 5's compare and again as step 7's last check, and refuses (exit 4) while one has changed, so no batch is booked
against an owned file that is missing a displaced save. Autobook never deletes
a pre-image and has no command that does. The user deletes them by hand, once
no program still has the old file open; `autobook status` lists them with their
size and age. A recorded pre-image that is missing blocks writing like a changed
one, because a deleted file and a lost file look the same. After deleting one,
the user runs `autobook forget PATH`: it takes the writer lock, refuses while
the file still exists, and removes only the staging record.

**A displaced version is never deleted.** Exchanging back is itself checked:
what the second exchange swaps out must be exactly the content the batch
rendered, with the mode, owner, group and ACL state the first exchange left
(a permission change in between is not silently undone). If it is not, the
file was saved or its permissions changed in between, and Autobook stops
resolving: it keeps every version it holds as a file beside the journal, writes
nothing further, marks nothing applied, and exits with code 4, naming the
files. `autobook status` shows the conflict until the user resolves it. The
same holds for recovery. This ends the chain of "what if it was saved again"
cases: Autobook may refuse, but it never discards a saved version.

Editing the owned file while `apply` or `undo` runs is therefore not supported
but is safe: the worst outcome is a refusal and a conflict to resolve by hand.

**Autobook's own files never match an include.** Scratch files
(`.autobook-tmp-…`) and pre-images (`.autobook-preimage-…`) sit beside the
owned file, and Beancount's glob expansion can match dotfiles, so an
`include "owned/*"` would pick them up: the include set would change under
Autobook's own write, and a kept pre-image would be loaded as a second copy of
the ledger. The preflight tests every include pattern against those two name
patterns in the owned file's directory and refuses (exit 4) a ledger where
either could match; `autobook init` says so when it prints the `include`
line.

**The owned path must be a regular file, not a symbolic link.** The reader
would follow a link and hash its target, while the exchange swaps the link
itself, so the file compared would not be the file exchanged. `init` and the
preflight of every write refuse (exit 4) an owned path that is a symlink or
not a regular file (checked with `lstat`), and it is checked again with the
re-hash immediately before the exchange; the exchange is made relative to a
directory descriptor opened on the owned file's real directory.

The writer requires a file system that supports the exchange. Where it is not
available, `apply` refuses with exit code 4 instead of falling back to a plain
rename.

### 11. Staging

SQLite under `$XDG_DATA_HOME` by default; a PostgreSQL URI as an option. The
writer lock and the batch journal live in a local directory **keyed by the
staging store's identity**, not by the configuration: a UUID that `init`
writes into the store, together with the **absolute path of the one state
directory** for that store (`init` creates it under its own
`$XDG_STATE_HOME/autobook/<store-UUID>/`, mode `0700`). Every client reads
that path from the store, never from its own environment, so a scheduled run
and an interactive run with different state homes take the same lock and see
the same journal; a client that cannot use the directory, or does not own it,
is refused (exit 2). They are files, not rows, so they bind only the clients
of one machine. A PostgreSQL store is therefore supported for **one machine only**:
Autobook records the host that created the store and refuses (exit 2) a run
from another host. Sharing one ledger and one store between machines would
need a lock and a journal every client sees; it is not designed here (see
*Open questions*).

```
statements(
  checksum,                                    -- PK; of the OFX file
  source_account, producer,                    -- producer string from the driver, or NULL
  period_start, period_end,
  opening_balance, closing_balance,            -- integer cents, NULL if absent
  balance_currency,                            -- the stated balances' currency
  closing_balance_date,                        -- the closing balance's as-of date (OFX
                                               -- LEDGERBAL DTASOF), which may differ from period_end
  closing_balance_time,                        -- its time of day if DTASOF carries one, else NULL
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
  approved_account,                            -- create only: the destination as saved by `decide`
                                               -- (possibly edited); what apply books and recovery re-checks
  proposed_splits,                             -- create_split only: every posting, account and cents
  approved_splits,                             -- create_split only: the postings as saved by `decide`
                                               -- (accounts possibly edited); what apply books
  rule_id,
  matched_entry,                               -- match_existing: the candidate found at proposal, its
                                               -- autobook-id if it has one, else its content hash
  match_source,                                -- search | rebound (the user chose it, §8.2)
  revision,                                    -- incremented on every re-proposal of the row
  released_entry,                              -- the matched_entry an undo released; audit only, claims nothing
  status,                                      -- pending|approved|skipped|rejected|applied
                                               -- skipped: `s` in the review file; releases the
                                               -- row's claim, and the row returns as `?` next time
  applied_entry,                               -- set only after read-back and assertions pass:
                                               -- created: the row's proposal ID; matched: = matched_entry
  batch, human_correction,
  classifier_version, normaliser_version, ts
)

transfers_pending(
  counterpart_account, amount, currency,
  window_start, window_end,
  proposal_id
)

statement_lines(
  statement_checksum, ordinal,                 -- PK; every line of every admitted statement
  source_account, line_key                     -- the proposal it is, also when an earlier
                                               -- statement staged it (overlap)
)

reviews(
  review_id,                                   -- PK; ULID in the review file's header
  version_tuple, row_revisions, ts             -- the tuple and each listed row's revision when written
)

operations(
  operation_id,                                -- PK; a ULID per apply or undo attempt, also in its journal
  batch, operation,                            -- apply | undo; a batch applied, undone and applied
                                               -- again has three operations
  committed_ts                                 -- set in the same transaction that marks the rows;
                                               -- a journal whose operation is committed is only cleaned up
)

preimages(
  path,                                        -- PK; unique per apply or undo
  batch, operation,                            -- apply | undo
  kind,                                        -- before (the previous content) | rejected (a
                                               -- batch that failed and was exchanged back)
  sha256, kept_ts                              -- hash of the content now at the path
)
```

Proposal 0002 adds the document columns. Staging is the seam between
classification and writing, the audit trail, the source of `corrected` corpus
rows, and the list undo works from. It is the only component with a view
across accounts, which is why correlation lives there.

### 12. Review file

Plain text, in the idiom of `git rebase -i`:

```
# id      st  date        amount        account                    description
#   knn: Lebensmittel .81 | Haushalt .07
a1f3e9    a   2026-07-14   -42,90 EUR   Ausgaben:Lebensmittel      REWE SAGT DANKE
9de441    ?   2026-07-16   -18,50 EUR   Ausgaben:Freizeit          PAYPAL .VENDORX
c27b10    a   2026-07-18   -89,00 EUR   (split)                    HUK-COBURG
c27b10.0  >                   -89,00 EUR   Aktiva:Bank:Girokonto
c27b10.1  >                    12,50 EUR   Ausgaben:Versicherung:Haftpflicht
c27b10.2  >                    76,50 EUR   Ausgaben:Versicherung:Hausrat
```

A `create_split` row shows every posting on its own line, the source posting
first (`.0`), each carrying the row's ID and a posting number, so the lines are
parsed by ID like every other line. Amounts are shown with the sign they get in the ledger: the source
posting is the row's amount, and the destination postings balance it. The
postings are stored in staging (`proposed_splits`); `decide` stores them as
saved in `approved_splits`, which apply books and recovery re-checks, while
`proposed_splits` stays as the audit of what was proposed. So what is shown is what is
booked. A destination posting's **account** may be changed by typing over it; the
source posting's account comes from the configuration and may not. No
posting's **amount** may be changed — the amounts come from the rule, and a split with other
amounts is rejected (`x`) and written by hand. The strict parser compares every
posting line's ID, amount and currency with staging on every split, and, on a
row marked `a`, checks each account against the live chart of accounts: open
on the row's date, currency allowed. A split left at `?`, `s` or `x` whose
destination was closed since does not block the file.
A posting line with no parent row, or a parent row missing a posting, aborts
the parse.

Status: `a` accept, `?` needs a decision, `s` skip, `x` reject (recorded as a
negative example), and `m` on a candidate line under an orphaned row, which
rebinds it (§8.2). Change an account by typing over it. Rows that passed the
gates are pre-marked `a`; everything else is `?`.

- **Saving is approving** every row marked `a`, with the account, amount,
  currency and date shown. `decide` stores the saved destination in
  `approved_account` (a split's postings in `approved_splits`); apply books
  that, never `proposed_account`. Every row shows its currency: an account may hold
  several, and a bare number would hide which one is being approved.
- **Parse by ID, never by position.** Reordering or deleting rows must not
  misalign anything. An unknown ID is an error, and so is an ID that occurs
  twice — a copied row or posting line — since staging holds one decision per
  row; the parse aborts (exit 5) before any decision is recorded.
- **Strict parser.** An unknown status, an account that is not open in the
  ledger on a row marked `a` (a `?`, `s` or `x` row may keep `(none)`, §8.1), or a date, amount or currency that differs from staging aborts the whole file with a
  line number (exit 5) and applies nothing. The date is a statement fact, like
  the amount: it is shown, never edited. So does a destination account, or
  a split's destination posting, equal to the row's source account. A
  classifier (a rule, kNN or the LLM) that proposes the source account as the
  destination has its row queued, never pre-marked.
- **An orphaned match** is resolved here, by `m` on one candidate line or `x`
  on the row (§8.2).
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

- **every transaction is compared by GUID.** Each exported transaction is
  found in the ledger by its GUID exactly once, and no converted transaction
  lacks one. Its date, description (as narration) and retained metadata must
  match, and its postings must match one to one: account (through the rename
  table), exact value and exact amount, and retained posting metadata. Postings
  are paired by split GUID, kept as posting metadata, not by position or value,
  so two equal-valued postings swapped between accounts are caught. Aggregate
  checks alone are not enough: a converter defect that changes a date or a
  narration, or swaps equal postings, keeps every count and total. Any
  difference the decision file causes (a renamed account, a dropped field, a
  re-homed Imbalance posting) is listed per GUID in the decision file; an
  unlisted difference rejects the conversion;
- transaction and posting counts match, per year;
- every account's balance per commodity matches exactly at each year end and
  at the conversion date; these are written into the new ledger as `balance`
  directives dated the **following day**, because Beancount checks a
  `balance` directive at the start of its date, before that day's postings;
- `bean-check` reports no error;
- the rename table is one-to-one and every exception is listed;
- each converted transaction carries its GnuCash GUID as metadata, and each
  posting its split GUID.

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
  since it was read. The replace is one atomic **exchange**, and what it
  swapped out is checked: a save that got in between the last hash and the
  exchange is put back, never overwritten.
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
  candidates. The search is run at proposal, again at apply and again in the
  read-back; exactly one candidate must remain each time. An orphaned claim
  pauses matching for its whole source account until the user rebinds the row
  to an entry the predicate still matches, or rejects it. Claims are per source account, so the second side of a transfer
  can match the entry the first side created.
- **One Autobook writer at a time.** `propose`, `apply`, `undo` and `decide` hold the writer lock
  from before they parse the review file or read the ledger until staging is
  updated.
- **An interrupted batch is validated before it counts.** The batch journal
  is written and made durable (file and directory `fsync`) before the
  replace, and holds the complete baseline: every file's hash, the first
  load's errors and every account's balance. A later run that finds it runs the read-back
  and the assertions against the journal's baseline, or restores the previous
  content. IDs found in the ledger prove presence, not validation.
- **Idempotency on re-run.** Created rows are found by ID before each batch.
  A proposal ID that staging holds as applied and the ledger lacks is
  reported, never re-created silently.
- **Undo is narrow.** It removes an entry only if its ID belongs to a created
  row of that batch and the entry is in the owned file; both are asserted.
- **A created row never posts back to its source account.** Its destination,
  and every split posting but the source posting, is another account.
- **The exchange keeps the ledger's mode.** The scratch file is created `0600`
  and given the owned file's mode before the exchange, checked with `fstat`;
  the journal and staging are `0600` in a `0700` directory.
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
| 0001 | Backups by file copy or `pg_dump` | The writer keeps every previous version of the owned file as a pre-image, which only the user deletes (§10.6). Keeping the ledger in git is recommended, never required. |
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
   difference, and every exception is in the decision file. By test, on a
   synthetic export: a changed date, a changed narration, and two
   equal-valued postings swapped between accounts each reject the conversion
   although every count and total still matches.
3. **Step 2.** The backtest reports per method and per band, on the novel
   stratum, with token-Bayes as the control (the premise test, and proposal
   0004's R1).
4. **Step 3, admission** — by test: each rejection reason in §5 rejects the
   whole statement and stages nothing; an admitted file handed over again
   changes nothing; a file rejected for an unconfigured account is admitted
   after the configuration is fixed.
5. **Step 5, the writer** — by test, on synthetic ledgers:
   - a batch with one row that fails the reload leaves every ledger file
     byte-identical, and keeps the rejected batch only as a recorded
     pre-image;
   - a re-run after a crash at each point between rendering and "marked
     applied" creates nothing twice;
   - a crash after the replace of a batch that introduces a load error: the
     next run restores the previous content and marks nothing applied;
   - a crash after the replace, then a foreign edit to the owned file: the
     next run touches nothing and reports the interrupted batch;
   - a crash after the replace, then an edit to another ledger file: the next
     run restores the previous content and marks nothing applied;
   - a matched entry moved outside the date window between proposal and apply:
     the row is queued, not marked applied;
   - a matched hand-written entry is edited: every later line that would
     match in that account is queued until the orphan is resolved;
   - an orphaned row rebound with `m` to a candidate is matched to that entry
     and matching in the account resumes; `m` on an entry that no longer
     passes the predicate aborts the parse and records nothing;
   - a row whose destination, or a split posting other than the source
     posting, is the source account is refused by the parser and queued at
     apply;
   - with a umask of `022` and an owned file of mode `0600`, the owned file
     is still `0600` after a batch; an owned file with an ACL is refused;
   - a second candidate appears between proposal and apply: the row is queued;
   - a change to any ledger file between read and replace stops the write;
   - a save to the owned file between the last re-hash and the exchange is
     put back at the owned path, and nothing is written — also when Autobook
     crashes right after the exchange and the next run recovers;
   - a batch holding one created row and one matched row applies: the matched
     row's ID is not required in the ledger and its amount is not counted as
     balance movement;
   - of two `apply` runs started together, one books and the other writes
     nothing;
   - the second side of a transfer matches the entry the first side created,
     once, and a third line with the same amount does not;
   - a line does not match a posting with the same number in another
     currency, neither in the search nor in the read-back;
   - postings off by one cent, and off by half a cent, are both refused;
   - undo removes exactly the batch's created entries, including when
     unrelated entries were added to the owned file afterwards;
   - a crash after an undo's exchange: the next run validates it with the
     undo checks and returns the rows to `pending`, without restoring the
     removed entries;
   - undo of a batch whose created transfer entry another batch matched is
     refused until that matched row is undone;
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
- **A matched entry edited afterwards.** Its claim becomes an orphaned claim
  (§8.2), which blocks later lines of the same amount and currency in the
  window until the user resolves it. If that rule were skipped, two payments
  could become one entry and the account be short by one; the closing-balance
  check would catch it only where a balance is stated.
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
- **More than one machine.** A PostgreSQL staging store shared by several
  hosts would need a writer lock and a batch journal every client sees (for
  example an advisory lock and a journal table in the database, with the
  ledger on a shared file system). v1 refuses a run from another host.

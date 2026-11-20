---
created: 14.10.2026 23:50
type: architecture
status: living
tags:
  - architecture
  - building-blocks
---
# 5. Building block view

> Living document. Describes the designed decomposition and the package layout
> that implements it (below). The design is
> [proposal 0005](../proposals/draft/0005-beancount-ledger.md): Autobook is handed
> OFX statement files and books them into a Beancount v3 plain-text ledger.
> Diagram source: [`diagrams/c4-container.mermaid`](diagrams/c4-container.mermaid).

### Package layout

All under `src/autobook/`, one module per building block. Each stub module sets
`__all__` to the one name of its entry point; a block that has been built
(`normaliser`, `classifier`, `trial`, `contracts`) exports its real API instead.

| Path | Block |
|------|-------|
| `contracts.py` | The versioned contracts (section 5.1). Standard library only. |
| `staging.py` | The staging store (section 5.1). Its own top-level block, because both the pipeline and the ledger package use it. Standard library only. |
| `pipeline/` | `statement_source`, `admission`, `normaliser`, `correlator`, `bill_matcher`, `classifier`, `model_adapter`, `disposition`, `batch_gate`, `review_file`, `trial` (section 5.2). Never imports `beancount`. `pipeline/profiles/` is package data, not a block: the normaliser's shipped profiles. |
| `book/` | The **ledger package** (section 5.3): reader, writer, read-back, assertions, undo. The only package that may import `beancount`. The directory name is historical: it dates from the earlier design, which booked into a GnuCash book. |

The modules under `book/` are still the stubs of that earlier design today
(`session`, `exporter`, `applier`, `readback`, `assertions`, `undo`). They are
replaced by the components of section 5.3 when the ledger package is built
(proposal 0005, *Backward compatibility*).

There is no launcher script: sequencing a run is the driver's job, and the
driver is a separate project (section 5.4). The `autobook` command (section 5.5)
has no module yet; the only command that exists today is
`python -m autobook.pipeline.trial backtest`. `import autobook` does not import
the subpackages.

## 5.1 One process and one store

Autobook is one program and runs as one process. It has four parts and is
called by a program outside it.

| Block | Where | May import `beancount` | Purpose |
|-------|-------|------------------------|---------|
| **Input** | `pipeline/statement_source`, `pipeline/admission` | No | Parse the OFX files it is handed; admit each statement whole or not at all |
| **Pipeline** | the rest of `pipeline/` | **No — enforced by the linter** | Everything from admitted statement to approved proposal: normalise, dedup, correlate, classify, dispose, batch gate, stage, review file |
| **Staging store** | `staging.py`; SQLite in `$XDG_DATA_HOME` (default) or a PostgreSQL URI | No | Audit trail, correction corpus, undo list; the seam between classification and writing |
| **Ledger package** | `book/` | Yes, and nothing else does | Every read from and write to the ledger, in two parts: the **reader** (accounts, corpus, existing entries) and the **writer** (append, read back, assert, undo) |
| **Driver** (outside Autobook) | a separate project | — | Gets statements, converts them to OFX, decides when to run, calls Autobook's commands, opens the review file in an editor, notifies the user (section 5.4) |

Terms used throughout this chapter:

- A **statement** is one OFX file; a **line** is one transaction in it.
- The **ledger** is the user's Beancount ledger: a main file and the files it
  includes.
- The **owned file** is the one ledger file Autobook writes to. It is named in
  the configuration, created by `autobook init`, and included from the user's
  main file by a line the user adds.
- The **proposal ID** is `AB-` followed by a ULID, generated once per staged
  line. An entry Autobook creates carries it as `autobook-id` metadata.

**The import rule.** Only the ledger package imports `beancount`, per file, as
each module needs it; the linter enforces this. Nothing in Autobook imports
`ofxstatement` or `gnucash`. Everything else reaches the ledger through the
typed contracts below. This is what keeps input, pipeline and staging testable
against fixtures, with no ledger on disk (proposal 0005 §3).

There is no second process. The earlier design needed one because the GnuCash
bindings could not be installed into a virtual environment. Beancount is an
ordinary dependency with wheels, so the ledger package is tested like the rest:
in `nox -s gate`, against synthetic ledgers in temporary directories, on every
supported Python version, with no Docker image. The Docker test environment
keeps paperless. Its GnuCash image, with the `nox -s applier` session and the
pytest `applier` marker, stays only for the export half of the one-off
conversion from GnuCash and is removed with it (proposal 0005 §16, *Tests*).

### The JSON contracts

The ledger package and the rest of Autobook exchange typed contract objects, in
process. Each contract serialises to JSON, for test fixtures, for `--json`
output and for `autobook export`. Each contract is versioned; widening one is a
documented change that updates this section in the same PR.

Wire shape, implemented in `autobook.contracts` for `corpus` and `coa`:

- Every document is a JSON object with its `contract` name (`"corpus"`,
  `"coa"`) and an integer `version`, starting at `1`. A reader accepts only a
  name and version it knows, and rejects anything else with `ContractError`.
- Money is a plain integer of cents. A float or a boolean is rejected.
- An account is a **list of path components**, never a separator-joined string
  (`["Ausgaben", "Lebensmittel"]`, not `"Ausgaben:Lebensmittel"`). Nothing in
  the contracts joins or splits a path. Ledger text and the review file write
  the components joined by `:`; a contract never does.
- A missing or unknown field is rejected, as is a value outside a closed set.
- The same checks run when a contract object is built in Python, so a writer
  cannot serialise a document a reader would refuse (for example a bare string
  where a path belongs, which would otherwise come out as one component per
  character).
- `corpus` is `{"contract", "version", "rows"}`. A row has `raw_memo`,
  `amount_cents` (the magnitude, an integer greater than zero), `sign`,
  `source_account`, `destination_account`, `post_date` (`YYYY-MM-DD`) and
  `provenance`. `sign` is `"out"` when the money leaves `source_account` and
  `"in"` when it enters it; the kNN index is keyed by `(source_account, sign)`.
  `provenance` is always `"observed"`: the contract refuses `corrected`. This
  design does not change the `corpus` contract.
- `coa` is `{"contract", "version", "accounts"}`. **The implemented version 1
  still has the fields of the earlier GnuCash design**: `path`, `type` (one of
  GnuCash's account-type names, such as `BANK` or `EXPENSE`), `placeholder`,
  `commodity` (`{"namespace", "mnemonic"}`) and `fraction` (an integer greater
  than zero). None of these but `path` exists in a Beancount ledger. Under this
  design `coa` gets a new version with the fields in the table below; the code
  and its tests change when the reader is built.

| Contract | Direction | Carries | State |
|----------|-----------|---------|-------|
| `corpus` | ledger package → pipeline | One row per historical transaction with exactly two postings, one of them in a configured source account, both in the same currency, neither with a cost or a price: `(raw memo, amount_cents, sign, source_account, destination_account, post_date)`, every one with provenance `observed`. `corrected` rows never come from the ledger; the pipeline adds them from staging. | Implemented, version 1, unchanged |
| `coa` | ledger package → pipeline | The live account list. Per account: the path (a component list); the root category (`assets`, `liabilities`, `equity`, `income`, `expenses`, whatever the ledger's root names are); the date of its `open` directive; the date of its `close` directive, or null; the currencies its `open` directive allows (empty means any). | Designed. The implemented version 1 has the GnuCash-shaped fields above |
| `existing` | ledger package → pipeline | Autobook IDs found in the ledger, each with its file and line and the entry as loaded (idempotency). Per source account, the match candidates in a date window, each with its **content hash**, for the `match_existing` search. The ledger's root-name options. Every loaded file with its SHA-256. The errors the load reported. | Designed, not implemented |
| `apply-in` | pipeline → ledger package | Approved rows: `proposal_id`, disposition, source and destination accounts (or split specification), `amount_cents`, currency, date, narration, optional document URL, optional match hash. | Designed, not implemented |
| `apply-out` | ledger package → pipeline | Per row `{proposal_id, entry, status}`, where `applied` is reported only after the read-back and every assertion have passed; per batch the assertion results. | Designed, not implemented |

A **content hash** identifies an entry the user wrote by hand, which has no
permanent identifier: its file and line move whenever anything above it is
edited. The hash covers date, flag, payee, narration, tags, links and postings,
and excludes metadata and position (Beancount's `hash_entry` with
`exclude_meta=True`; proposal 0005 §8.2).

The `match_existing` search runs in the pipeline, over the `existing` contract,
so that a row can be queued as a pending transfer and the review file can show
the match. Nothing is ever written to a matched entry, so apply has no write to
guard there: its filter step drops matched rows whose hash is in staging and
still present in the ledger (section 5.3). `existing` is needed before the
pipeline runs, because the transfer search comes before classification.

## 5.2 Pipeline components

### Statement source

Autobook's input is **OFX files handed over by the driver**: `autobook propose
FILE…` takes one or more. Autobook never fetches a statement, never runs a
converter and never imports or runs ofxstatement; discovering and downloading
statements from paperless or a bank, and converting them to OFX, is the driver's
job (section 5.4).

- **The parser is Autobook's own**, standard library only. From each file it
  reads the account ID, the currency, the statement period and the ledger
  balance, and per line the ID, date, amount, name and memo.
- **The memo must arrive unmodified.** Normalisation is Autobook's (the
  normaliser, below), never the converter's.
- The driver may pass a **producer string** per file, for example the converter
  plugin's name and version. It is recorded with the statement and is part of
  the version tuple (section 8.3): a changed producer string means a converter
  was updated, which can change every memo without any Autobook code changing.
- The **configuration** binds a file to the ledger. Per source it names the OFX
  account ID, the ledger account (the *source account*), whether the line IDs
  are bank-supplied or synthesised, the normalisation profile, and `paypal_mode`
  where relevant (proposal 0005 §4.5). Autobook cannot learn any of these from
  the file. Today the implemented normaliser reads its account-to-profile
  mapping from its own `accounts.toml` (below).

Autobook does not second-guess a well-formed statement. It cannot know how an
OFX file was produced; it checks the file for consistency and its own work for
correctness.

**[OPEN]** whether OFX files and a producer string are enough, or whether
`propose` should also take the checksum of the original statement, so that a
statement converted twice is recognised (proposal 0005, *Open questions*).

### Admission and dedup

**Admission** is the decision to accept a statement. A statement is **admitted
whole or not at all** (proposal 0005 §5). It is rejected, with the reason
recorded and no line staged, if:

- the file does not parse as OFX;
- a line lacks a date, an amount or a currency, or an amount is not a whole
  number of cents;
- the account ID is not in the configuration;
- the statement's currency is not one the ledger account's `open` directive
  declares;
- the lines do not add up to the statement's balances, where it states them
  (the **balance check**);
- its period overlaps an admitted statement in a way the overlap rule cannot
  resolve (proposal 0002 §3.4).

Every statement gets a `statements` row, keyed by the checksum of the OFX file,
so handing over the same file twice changes nothing. A statement that fails
admission is recorded with status `rejected` and its reason; `propose` exits
with code 7 and reports the reason per file. Other statements in the same call
are admitted on their own merits.

Where a statement states no balances, the balance check is not possible, and
coverage reports show which accounts are protected by it and which are not
(proposal 0002 §3.3). **[OPEN]**: the staging schema of proposal 0005 §11 has no
column for this; the balances themselves are `NULL` when absent.

**Dedup** assigns each line its key. Every key includes `source_account`. The
configuration says, per source, whether the line IDs are bank-supplied. A
bank-supplied ID is the key where present. Otherwise the ID was synthesised by
the converter (ofxstatement hashes date, memo and amount, so two identical card
payments on one day collide) and is not trusted as an identity: the key is
`(source_account, statement checksum, line ordinal)`, and the period-overlap
rule decides whether a later statement repeats the line. The overlap rule's line
matching is **count-aware**: two identical lines in the overlap need two
identical staged lines.

### Normaliser

Strips the noise from a raw memo (SEPA tags and references, dates, card fragments,
sequence numbers) until the merchant token remains. It is the only place that
normalises a memo (section 8.4). **Profiles are per source account**, loaded from
the installed package and from a user directory, so a new bank or country does not
need a release. The normaliser version is part of the version gate tuple.

Implemented in `autobook.pipeline.normaliser`:

- `load(user_dir=None)` reads the package profiles and the user directory once and
  returns a `Normaliser`; `None` means the default user directory (below). Every bad
  input raises `NormaliserError` (a `ValueError`) naming the file or directory and
  what is wrong; nothing falls back silently. Error messages never carry a memo.
- `Normaliser.normalise(raw_memo, source_account)` returns a `NormalisedMemo` with
  `raw_memo` (unchanged), `token`, `profile` (the profile used for the account) and
  `version`. `source_account` is a tuple of path components, as in the contracts.
  Neither the memo nor the token appears in the `repr`, so a logged result carries
  no memo (section 8.5).
- `Normaliser.version` is the normaliser version (below); `NORMALISER_VERSION` is
  the code's part of it.

**Profiles.** A profile is a named, ordered list of rules. Each rule is a Python
regular expression whose matches are removed (replaced by a space). The name is the
file name without `.toml`. Users write these files by hand, so the layout is a
compatibility promise:

```toml
# <name>.toml
extends = "default"     # optional

[[rules]]
pattern = '\bKARTE \d+'

[[rules]]
pattern = '\bREF \d+'
```

- The top-level keys are `rules`, an array of tables, and the optional `extends`, a
  profile name. A file with no `[[rules]]` is a profile with no rules of its own.
  Each rule has exactly one key, `pattern`, a string. Any other key, a value of the
  wrong type or a pattern that does not compile is an error, so a typo never
  becomes a rule that silently does nothing.
- Patterns match regardless of case (`re.IGNORECASE`). TOML literal strings
  (`'…'`) keep backslashes as written.
- A profile's effective rules are its own rules in file order, followed by the
  effective rules of the profile it `extends`. `extends` is resolved after the
  user's overrides (below), so a user `default.toml` also changes every profile that
  extends `default`, `sepa` included. Chains are allowed; an unknown name or a cycle
  is an error.

To normalise a memo: upper-case it, apply the effective rules in order, collapse
runs of whitespace to one space and strip both ends. The token may be empty when
the memo is all noise. The raw memo is never changed or discarded: it is returned in
`NormalisedMemo.raw_memo` and stays the stored form in the corpus.

Two profiles ship in the package, in `src/autobook/pipeline/profiles/`:

- `default` strips noise in general form, in this order: the `SAGT DANKE`
  boilerplate; card fragments (`KARTE <digits>`); reference fragments
  (`REF <digits>`, `NR. <digits>`, `NR.<digits>`); ISO dates with an optional time
  (`2025-03-05T10:11:12`); clock times (`10:11`, `10:11:12`); day-month dates
  (`DD.MM.`, `DD.MM.YYYY`); month-year (`01.2025`); standalone digit runs; and
  whitespace-delimited fragments made only of punctuation. The date and time rules
  run before the digit-run rule. Digits inside a word, as in a creditor ID, and
  multi-word merchant names survive.
- `sepa` extends `default` with the structured-purpose tags of the German MT940
  field 86 and the CAMT export. The full tag set is `EREF+` `KREF+` `MREF+` `CRED+`
  `DEBT+` `COAM+` `OAMT+` `SVWZ+` `ABWA+` `ABWE+` `IBAN+` `BIC+` `BREF+` `RREF+`
  `PURP+`. Every tag of the set ends the value of the tag before it, and a tag is
  found with no word boundary in front, because some exports glue the fields
  (`EREF+NOTPROVIDEDSVWZ+…`). Each tag is handled one of two ways:

| Tags | Handling | Why |
|------|----------|-----|
| `SVWZ+`, `CRED+`, `ABWA+`, `ABWE+` | The tag is removed and the value kept; the `default` rules then clean it | They tell merchants apart: the purpose text, the creditor ID (a registered business identifier, allowed in shareable data by section 8.5), the ultimate debtor and the ultimate creditor (the real payee when a provider pays on a merchant's behalf) |
| `EREF+`, `KREF+`, `MREF+`, `DEBT+`, `COAM+`, `OAMT+`, `IBAN+`, `BIC+`, `BREF+`, `RREF+`, `PURP+` | The tag and its value are removed, up to the next tag of the set or the end | References and amounts change from one payment to the next. An IBAN must never reach the model adapter (section 8.5) and may belong to a person, and so may the originator ID after `DEBT+`. A BIC names a bank, not a merchant |

Known limit, on purpose: a value kept from `ABWA+`/`ABWE+`, and the `SVWZ+` text,
can be a person's name, and an IBAN the sender typed into the `SVWZ+` text is not
removed (a rule for any IBAN-shaped text would also remove creditor IDs, which have
the same shape). The guard is the adapter boundary (section 8.5): a remote backend
receives a token only if it matches a pack entry or the user's allowlist.

**User directory.** `$XDG_CONFIG_HOME/autobook/normaliser/`, or
`~/.config/autobook/normaliser/` when `XDG_CONFIG_HOME` is unset, empty or not an
absolute path (section 8.8). A directory that does not exist means package profiles
only and no mapping. `load` reads the top level only:

- An entry whose name ends in exactly `.toml` (lower case) and does not start with
  `.` is a profile file, or the mapping file `accounts.toml`. It must be a regular
  file or a symlink to one. Every other entry is ignored and does not enter the
  version: subdirectories, dotfiles, editor backups (`sepa.toml~`, `sepa.toml.bak`),
  other suffixes (`SEPA.TOML`), notes. A user directory that cannot be listed, a
  user directory path that is a dangling symlink, and one that is a file are errors.
- A `<name>.toml` replaces the package profile of the same name entirely; there is
  no merge. A new name adds a profile. Names are case-sensitive: `Default.toml` adds
  a profile `Default`. To change only the accounts mapped to `sepa`, override `sepa`.
- A user profile must be used: one that replaces no package profile, is named by no
  `accounts.toml` entry and is extended by no profile is an error. This catches
  `defualt.toml`, which would otherwise sit unused while the package `default` keeps
  applying.
- `accounts` is reserved for the mapping file. It maps source accounts to profiles,
  each account a list of path components, never a separator-joined string
  (section 5.1):

```toml
# accounts.toml
[[accounts]]
path = ["Aktiva", "Girokonto"]
profile = "sepa"
```

The only top-level key is `accounts`, an array of tables; each entry has exactly
`path` (a non-empty array of non-empty strings) and `profile`. A profile that does
not exist, or an account mapped twice, is an error. An account with no mapping uses
`default`; the package maps no account.

**Version.** `Normaliser.version` is `"<NORMALISER_VERSION>-<12 hex digits>"`.
`NORMALISER_VERSION` is the code's algorithm version, bumped when the code (not a
profile) changes what a token looks like. The hex digits start a SHA-256 digest
over the effective rules of every profile, the account mapping and the interpreter's
Unicode database version: `str.upper()` and the regex classes `\d`, `\b`, `\s`
follow the Unicode database, and CI runs Python 3.11 to 3.14, which ship different
versions. The digest is taken over a canonical form, sorted by profile name and
account path, holding no file path, other file name or timestamp. So the same files
give the same version from any directory, and one changed rule, mapping line or
Unicode version gives a new one.

The version is global on purpose: a change for one account changes it for every
account. That costs nothing extra, because the kNN index is rebuilt whole every run
(proposal 0005 §6.2); the cost is a backtest re-run, which is what the version gate
forces. This string, not `NORMALISER_VERSION` alone, is the normaliser version that
is recorded with every vector, in the version tuple (section 8.3) and in the
`normaliser_version` staging column; the integer alone would miss a user's profile
edit (section 8.8).

### Correlator

The only pipeline component with a cross-account view, which staging gives it.
Pairs the two sides of transfers between the user's own accounts and emits the
transfer from one canonical side. Without it every transfer is booked twice.

Transfers also span batches. Every transfer row first goes through a
`match_existing` search in its **source** account, before classification: the
second side of a transfer booked in an earlier batch resolves to the entry the
first side created, which has a posting in both accounts. A transfer booked
from one side records a `transfers_pending` entry (counterpart account, amount,
date window, the first side's proposal ID). An unmatched second side whose
counterpart is pending is queued as "pending transfer", never classified.

PayPal follows the configuration key `paypal_mode`:

- `account` (default): PayPal is its own ledger account and its statement is
  imported. Bank lines to PayPal are transfers, resolved here.
- `pass_through`: PayPal statements are never imported. The bank line is
  classified by the merchant parsed from its memo (`PAYPAL .VENDORX` →
  `VENDORX`).

### Bill matcher (proposal 0002)

Reads bill metadata from paperless and links bills to bank rows **batch-wide**:
exact amount in cents, date within an asymmetric window, and a **confirmed
correspondent association** between the bill's correspondent and the row's
merchant token (proposal 0002 §4.4). Candidate bills are first deduplicated by
`original_checksum`, because paperless accepts duplicate documents by default; a
link exists only when the remaining pairing is one-to-one. It changes no amount,
date or account. Its only downstream effects are to make document conditions
(correspondent, document type, tag) available to rules, and a document URL
available to the writer: a created entry with a linked bill carries it as
`autobook-doc` metadata. On a `match_existing` row nothing is written to the
ledger, and the link is recorded in staging only.

A bill without a correspondent, or whose correspondent has no confirmed association, can only produce `doc_match = weak`: a hint line
in the review file, never input to a rule. Which paperless document types count
as bills and which as credit notes is configuration, and part of the version
tuple.

This is the one place where Autobook still talks to paperless. Statements no
longer come from there (they are the driver's), but bills do. Whether the driver
should hand over bill candidates in a file instead is **[OPEN]** (proposal 0005,
*Open questions*). The paperless client uses the standard library or an HTTP
library whose licence is compatible with GPLv2
([ADR-0005](../adr/0005-relicense-gpl-2-or-later.md), status Proposed).

### Classifier

The cascade runs **rules → kNN → LLM** (k-nearest-neighbour, then a large
language model). Precedence is one table, which governs everywhere. It is
stated in full in proposal 0002 §5.1 (document conditions); proposal 0005 §6
points to it. In short:

| Tier | Source | Condition |
|------|--------|-----------|
| 1 | Creditor-ID rule (SEPA Gläubiger-ID) | Exact match |
| 2 | Document-keyed rule | Only with a confirmed correspondent association, `auto: true`, and passed shadow mode |
| 3 | Ambiguity flag (`AMAZON`, `PAYPAL` …) | Forces `?`: the row is never pre-marked |
| 4 | Memo-pattern rule | |
| 5 | kNN | Both gates pass |
| 6 | LLM tail | Optional; always `?` until shadow mode has measured its precision |

A rule's `priority` field orders rules **within** a tier only. Every rule has
an `auto` field: default `true`, except document-keyed rules, which default to
`false`; a rule with `auto: false` proposes but never pre-marks. The rule
builder reports conflicts between any two tiers on historical rows.

- **Rules.** A versioned, git-tracked file owned by the user, plus bundled
  packs. Rules may target a split specification; they are the only tier that
  may. Fixed split amounts are integer cents (`cents: 1250`), never a decimal
  value. Most user rules are **mined from history** and accepted by the user
  (proposal 0004): creditor-ID and memo-pattern candidates, scored on a held-out
  period, with `created-by: mined` and `mined_cutoff`. Mining never produces a
  split specification.
- **kNN.** Character n-gram TF-IDF (term frequency–inverse document frequency;
  `char_wb`, 3–5) over the user's own corpus, one index per
  `(source_account, sign)`, cosine distance, exponential recency decay
  (~18-month half-life), rebuilt every run in-process. A prediction is accepted
  only if the **nearest-neighbour distance** is within its cutoff **and** the
  **vote margin** clears its threshold. Corpus rows are tagged `observed` or
  `corrected`; nothing else can enter.

  In `autobook.pipeline.classifier`: `index_rows(corpus, normaliser)` turns a
  corpus into `IndexRow`s (one per corpus row, token and `normaliser_version`
  from `Normaliser.normalise`, `provenance` copied from the corpus row);
  `KnnIndex.build(rows, *, max_distance, min_margin, half_life_days=HALF_LIFE_DAYS)`
  fits one `TfidfVectorizer` per `(source_account, sign)`;
  `KnnIndex.query(token, source_account, sign, *, as_of, normaliser_version,
  exclude=None)` returns a `KnnResult` (`account`, `candidate`,
  `nearest_distance`, `margin`, `share`, `failed_gates`, and `accepted`). A query
  never sees another partition, and is compared with every row of its own.
  - *Distance.* Measured over every n-gram of the query, including those no row
    of the partition contains. Each distinct n-gram, counted `c` times in the
    query, weighs `(1 + ln c) * idf`, with scikit-learn's smooth idf on the
    partition's counts: `ln((1 + n) / (1 + df)) + 1` for `n` rows of which `df`
    contain the n-gram. The idf of one that no row contains is therefore
    `ln(1 + n) + 1`, the idf a term no row contains would get. The query is
    L2-normalised over all of its n-grams, and its distance to a row is one minus
    its dot product with the row's fitted (L2-normalised) vector. Text that
    history never contained matches no row but still counts in the query's
    length, so it moves the query away from history.
    `TfidfVectorizer.transform` alone would drop it: a known merchant followed by
    new words would score as an exact match. A query whose n-grams are all unseen
    is at distance `1` from every row. Distance is clamped to `[0, 1]`, and a
    distance under `1e-9` (rounding noise on identical vectors) is read as `0`.
    Without `exclude`, a query whose n-grams are all known gets the plain cosine
    distance, and an exact token match is at distance `0`, so it passes even
    `max_distance = 0`. With `exclude`, neither is guaranteed (see *`exclude`*).
  - *Vote.* Every row at or below the 15th smallest distance votes (every row,
    in a partition of fewer than 15). Rows tied with the 15th all vote, so a
    group of identical memos votes as a whole and recency decides among them:
    the result depends on the set of rows, not on the order they were given in.
    A voter's weight is `(1 - distance) * 0.5 ** (age_days / half_life_days)`,
    with `age_days = max(0, (as_of - post_date).days)` and
    `HALF_LIFE_DAYS = 548` (18 months). An account's *share* is its weight over
    the total weight; the candidate is the account with the largest share (on an
    exact tie, the smaller path tuple); *margin* is
    `share(candidate) - share(runner-up)`, with a runner-up of `0` when only one
    account voted and a margin of `0` when the total weight is `0`.
  - *Gates.* Distance passes iff `nearest_distance <= max_distance`; margin passes
    iff `margin >= min_margin`. Both are evaluated and every failure is listed in
    `failed_gates`; `account` is set only when the set is empty. A partition with
    no rows, or an empty token, gives `nearest_distance = None` and
    `{"distance"}`. Thresholds are required, have no default, and are validated
    (`0 <= max_distance < 1`, `0 < min_margin <= 1`), so a tie is never accepted.
    The distance gate is `<=`, not a strict "under the cutoff": distances take
    continuous values apart from exactly `0` and `1`, and `max_distance < 1`, so
    the two differ only at `max_distance = 0`, where `<=` means "exact matches
    only" and `<` would mean "nothing ever passes".
  - *`exclude`.* A leave-one-out that does not rebuild the index, for the
    backtest: the query is measured as if one row equal to `exclude` were not in
    history. That row is taken out before the voters are chosen, and out of the
    query's idf (`n` and the `df` of each of its n-grams are one lower, so an
    n-gram only that row contains weighs as unseen). The other rows are not
    refitted: their vectors keep the idf fitted with the row in, so a
    leave-one-out distance is exact on the query's side only. As a result, a
    remaining row with the query's own token is usually a little above distance
    `0`, not at it: one row fewer changes an n-gram's idf by an amount that
    depends on its `df`, so when the query's n-grams have different `df`, its
    weights are no longer proportional to that row's. With `BEISPIELMARKT` twice
    and `BEISPIEL GMBH` in one partition, `BEISPIELMARKT` with one of its rows
    excluded is at `0.000877` from the other, above the `1e-9` snap, so a
    leave-one-out of a repeated merchant can fail `max_distance = 0`. An
    `exclude` that the query's partition does not hold (no such row, or a row of
    another `(source_account, sign)`) raises `KnnError` before any result is
    returned: a leave-one-out that left nothing out would score the row against
    itself.
  - *Provenance and version.* `IndexRow` refuses any provenance but `observed` or
    `corrected` when built, and `build` checks every row again; both raise
    `KnnError`, and no partial index exists. `index_rows` copies each corpus
    row's provenance rather than setting one, so the check sees the real value.
    `build` takes only `IndexRow` itself, not a subclass, and the checks require
    exact `str` and `tuple` field types, so neither a subclass nor a field with
    its own `__eq__` can pass the check; `query` checks an `exclude` row the same
    way. One index holds one `normaliser_version` (`build` raises on a mix;
    `query` raises on a version other than the index's). The index is rebuilt
    every run and never persisted, so it has no version of its own yet; that
    arrives with the version tuple.
- **LLM tail.** Through the model adapter only. The label space is the live
  account list, generated from the ledger at run time (the `coa` contract) and
  never written into the steering document. The answer is validated against it:
  output outside it is rejected, and so are accounts not open on the line's
  date, accounts whose `open` directive does not allow the line's currency, and
  accounts under the Equity root. Temperature is pinned to 0, and the model ID
  is recorded in the version tuple. An LLM proposal is always `?` until shadow
  mode has measured per-method precision for `method=llm`; only then may a
  threshold pre-mark LLM rows. Optional: running with no language model at all
  is a first-class configuration.

A row nothing accepts goes to `queue`. kNN and the LLM return a single account,
never a split.

**Category indirection.** Bundled packs map patterns to semantic categories
(`groceries`, `insurance`), not accounts. A per-user category → account mapping
binds them, derived from history and confirmed by the user.

### Model adapter

The redaction boundary. Accepts a normalised merchant token, amount and sign;
cannot be handed a raw memo, an IBAN or document content by its type signature.
The account list is sent as **numeric indices**, mapped back to accounts
locally; account names never cross. OpenAI-compatible with a configurable
`base_url`; credentials from the Secret Service. Absent entirely in no-AI mode.
Like the paperless client, it uses the standard library or an HTTP library whose
licence is compatible with GPLv2 (ADR-0005, status Proposed).

The default backend is **local** (Ollama, llama.cpp …). A remote backend is
opt-in, and then receives a token only when it matches a rule-pack entry or the
user's allowlist of business names; for any other token the LLM abstains and the
row is queued.

### Disposition

Assigns each row exactly one of `create | create_split | match_existing |
out_of_scope | queue`. Out-of-scope rows (securities transactions, postings in a
currency other than the account's) are recorded and visible but excluded from
the queue and from coverage and drift metrics.

**`queue`** means the row is shown for review as `?`, neither booked nor lost,
and counted as outstanding in the balance check. A queued row carries its
reason: confidence under threshold; no rule and a kNN distance over the cutoff;
the proposed account not open on the line's date; a currency the account does
not allow; an ambiguous match; a pending transfer. A payment whose parts change
every period (a loan instalment's interest and principal) cannot be split from
the statement line and is queued. If the user writes that entry by hand, the
line resolves as `match_existing`.

**`match_existing`** means the line is already in the ledger: the user wrote it
by hand, or it is the second side of a transfer. The search looks in the row's
**source** account for a posting with the same amount within ±5 days, among
entries not already claimed by Autobook. An entry is *claimed* when it carries
an `autobook-id` or its content hash (section 5.1) is in staging's
`applied_entry`. Whether the user has asserted a balance since does not matter.
One candidate: nothing is created, and staging records the matched entry's
content hash. No candidate or more than one: the row is queued. The search
never guesses.

Nothing is written to a matched entry; it is in a file Autobook does not own.
If the user later edits a matched entry, its hash changes and the claim is
lost. The staged row stays `applied`, so nothing is proposed twice; the entry
becomes a candidate again, and a later line that then finds more than one
candidate is queued (proposal 0005 §8.2 and *Risks*).

### Batch gate

Decides whether anything is written at all: coverage below a rolling baseline,
LLM-fallback spike, unusual share of rarely used accounts, a changed version
tuple, paperless unreachable. Any of these writes nothing; the command exits
with code 3 and the reason, and notifying the user is the driver's job. The
ledger is a text file and stays usable. Proposals stay pending.

A file that does not parse is no longer a batch-gate matter: the statement is
rejected whole at admission (exit code 7).

### Review file

Generates a `git rebase -i`-style text file listing the batch's in-scope rows.
`autobook review-file` writes it to standard output; the driver decides where
it lives and opens the editor. The file holds counterparty names, so it should
be private to the user and short-lived. Each row has a status: `a` accept, `?`
needs a decision, `s` skip, `x` reject (recorded as a negative example). Rows
that passed the gates are pre-marked `a`; everything else is `?`. **Saving the
file is the user's approval of every row marked `a` in the saved file**, with
the account, amount and date shown. Nothing else reaches the ledger.

The file is parsed back **by ID, never by position**, strictly: an unknown ID,
an unknown status character, an account that is not open in the ledger or an
amount that differs from staging aborts the whole parse with a line number
(exit code 5) and applies nothing. A row with a weak bill match carries a hint
line, nothing more. What was proposed and what was saved are both recorded per
row; corrections are recorded as `corrected` corpus rows. `autobook decide`
records the decisions to staging and writes nothing to the ledger; until the
writer exists (build step 5) that is all saving the file can do.

### Trial tooling (scenario 1)

Never writes to a ledger; it reads one only through the reader's contracts
(`autobook export`). Until the conversion from GnuCash is done, the backtest
can run on a `corpus` document from the GnuCash export, because the `corpus`
contract is unchanged (proposal 0005 §16).
Contains the **backtest**, which is **rolling-origin**: for each calendar month m
after the first, the index holds the rows dated before the first day of m and the
test set is month m. Nothing dated in m or later enters m's index or token-Bayes
counts (a row's own date does not bound the past; the month boundary does), so a
row's future never votes for it. Results are reported per method and per
confidence band, with token-Bayes as a negative control, and stratified by whether
the memo was seen before in the index or is novel; gate thresholds are set on the
**novel** stratum. Leave-one-out remains only as an upper bound and for the rule
builder's quick "matches N historical rows" verdict. Also the **rule miner**
(candidates from history, scored on a held-out period, accepted in a text file;
proposal 0004; `autobook trial mine`), the **rule builder** (cluster, propose,
backtest immediately, accept; `autobook rules cluster`, `test` and `accept`),
the **pack validator**, and from proposal 0002 the **linkage backtest**.
Recurring debits get no special treatment: they are mined like any other group
and mostly become creditor-ID rules.

Built so far: the backtest and its command line (`python -m
autobook.pipeline.trial backtest`, section 6.6). Its method:

- **Methods.** `knn` is the gated kNN of the classifier (confidence is the vote
  share of the winner); `token_bayes`, the negative control, is multinomial naive
  Bayes over the words of the token per `(source_account, sign)`, Laplace
  smoothing over the partition's vocabulary, class priors from counts, no
  recency, and abstains only on an empty partition (confidence is the winner's
  normalised posterior). A word the partition's history does not hold is
  skipped, so a token with no known word (or a blank one) goes by the priors.
- **Strata.** A test row is `seen` if the index holds a row of the same
  `(source_account, sign)` with the same token, `novel` otherwise; every result
  is also given for `all`. Each carries `rows`, `accepted`, `correct`,
  `precision` (correct / accepted) and `coverage` (accepted / rows).
- **Bands.** Confidence bands `[0,0.5)`, `[0.5,0.7)`, `[0.7,0.9)`, `[0.9,1]`
  (`trial.BANDS`) split the accepted rows by confidence, with the same fields.
  A band's `rows` is every tested row of the method, the denominator of its
  coverage, so the bands' `accepted` add up to the method's.
- **Sweep.** For the kNN novel stratum, the gates re-applied over a grid of
  `max_distance` and `min_margin` (`trial.SWEEP_DISTANCES`, `SWEEP_MARGINS`) to
  the stored results; no re-query, and it never feeds back into the run. A row
  that passes a cell's gates counts as correct when the vote's candidate is the
  truth.
- **Upper bound.** `upper_bound.knn_leave_one_out`: one index over all rows,
  every row queried with `exclude=row`. Never under `methods`, never in the sweep.
- **Report** (JSON): `report`, `report_version`, `normaliser_version`,
  `thresholds`, `bands`, `months` (`first`, `last`, `tested`, `by_month`; every
  calendar month after the first is tested and listed, one with no rows with zero
  counts), `methods`, `upper_bound`, `novel_sweep`. **Privacy:** counts, rates,
  versions, thresholds and months only; no memo, token, merchant, account, amount
  or day, and no per-account breakdown (ch.8 section 8.5).
- **Not yet:** per-cluster results (they come with the rule builder).

### Staging store

This is the single staging schema: proposal 0005 §11, plus the document columns
of proposal 0002 §7.

```
statements(checksum PK,                   -- of the OFX file
           source_account, producer,      -- producer string from the driver, or NULL
           period_start, period_end,
           opening_balance, closing_balance,  -- integer cents, NULL if absent
           status, reason,                -- admitted | rejected; why rejected
           admitted_ts)                   -- time of the admission decision

proposals(source_account, line_key,       -- PK (source_account, line_key)
          statement_checksum,
          proposal_id,                    -- AB- + ULID; autobook-id on created entries only
          post_date, amount, currency,
          raw_memo, normalised_memo,
          disposition, queue_reason,
          proposed_account, confidence, method, rule_id,  -- method: rule | knn | llm
          status,                         -- pending|approved|rejected|applied
          applied_entry,                  -- proposal ID if created, content hash if matched
          batch, human_correction,
          doc_id, doc_match, doc_candidates,  -- proposal 0002: linked bill, linked|weak|ambiguous|none, count
          classifier_version, normaliser_version, ts)

transfers_pending(counterpart_account, amount, window_start, window_end,
                  proposal_id)            -- first side of a cross-batch transfer
```

`line_key` is the bank-supplied line ID, or for sources whose IDs are
synthesised the `(statement checksum, line ordinal)` pair. The **proposal ID**
is something else: `AB-` followed by a ULID (a 26-character sortable unique
ID), generated once per staged row. Only an `autobook-id` value matching
`^AB-[0-9A-HJKMNP-TV-Z]{26}$` counts as Autobook's; it is written on entries
Autobook creates and on nothing else. `applied_entry` holds the proposal ID for
a created row and the content hash for a matched row. `batch` names the batch
a row was applied in; it is what `autobook undo BATCH` works from. A row is
`applied` only after the ledger package's read-back and every assertion have
passed.

Amounts are integer cents. Document fields are IDs and counts, never content.

Staging is SQLite under `$XDG_DATA_HOME` by default, with a PostgreSQL URI as
an option. No production staging data exists; this schema is the first released
one.

## 5.3 Ledger package components

The ledger package has two parts: the **reader**, which only reads, and the
**writer**, which writes and exists from build step 5. The reader starts with
milestone B0, as a spike that emits `coa` and `corpus` from a synthetic ledger
(chapter 9). Nothing outside the ledger package parses ledger text.

| Component | Responsibility |
|-----------|----------------|
| **Reader** | Loads the whole ledger through Beancount's loader and produces `corpus`, `coa` and `existing`: accounts with their `open` and `close` dates and currencies, existing Autobook IDs, match candidates with content hashes, the root-name options, the SHA-256 of every loaded file, and the load's errors. Every assertion goes through it. |
| **Writer** | `autobook init` creates the owned file with its header and prints the `include` line for the user to add. **Apply**, for a batch of approved rows: (1) *read* — load the ledger; the owned file must be among the loaded files, with root-name options matching the main file's, otherwise exit code 4; (2) *filter* — drop rows whose proposal ID is already in the ledger, and matched rows whose hash is in staging and still present; (3) *check each row* — both accounts open on its date, its currency declared on the source account and allowed on the other, postings in whole cents summing to exactly zero; a row that fails is queued; (4) *render* the entries; the new content is the current owned file plus the entries; (5) *compare, then replace* — re-hash every ledger file; if any differs from step 1, stop with exit code 4 and write nothing; otherwise write a temporary file in the same directory, flush it to disk and rename it over the owned file, keeping the previous content. Then read-back and assertions, below. `match_existing`: nothing is created and nothing is written. |
| **Read-back** | Loads the ledger again after the replace. Every proposal ID of the batch must appear exactly once, with the approved date, accounts and amounts. A row is reported `applied` (in `apply-out`, and in staging) only after the read-back and every assertion have passed. |
| **Assertions** | After the read-back: (a) the load reports no error that the first load did not report; (b) no byte of the owned file before the appended entries changed, and no other ledger file changed; (c) for each source account with a statement in the batch, its balance moved by exactly the sum of the rows applied; (d) where the statement states a closing balance, the account's balance on the closing date equals that closing balance minus the statement lines not yet applied (queued, `out_of_scope`, pending transfer). **On any failure of the read-back or an assertion**, the writer restores the previous content of the owned file (only if the file still holds exactly what the replace wrote), exits with code 6 and marks nothing applied. |
| **Undo** | Removes an entry only if its `autobook-id` is the proposal ID of a staged row with disposition `create` or `create_split` in that batch **and** the entry is in the owned file, asserting both before each removal. It removes exactly that entry's lines, through the same compare-then-replace and read-back as apply. An entry the user edited is still removed, with its differences listed before confirmation. Undo of a matched row changes staging only. |

**A created entry** looks like this (proposal 0005 §10.2):

```beancount
2026-07-14 * "REWE SAGT DANKE"
  autobook-id: "AB-01JZ8M3Q6T5W9X2C4V7B1N0PKD"
  Aktiva:Bank:Girokonto   -42.90 EUR
  Ausgaben:Lebensmittel    42.90 EUR
```

The flag is `*`, because the row was approved in the saved review file. Every
posting carries an explicit amount; the writer never leaves one for Beancount to
fill in. Money is `Decimal` built from integer cents and printed with exactly
two decimals; a float never reaches `Decimal`. The currency is read from the
statement and checked against both accounts' `open` directives; none is
hard-coded. A linked bill adds `autobook-doc: "<URL>"`. The exact bytes (key
names, ordering, quoting, the header of the owned file) are a contract with
other tools and with undo; they get a specification under `docs/design/specs/`
when the writer is built.

**Why the writer checks the sum itself.** Beancount's own balance check is
tolerant: it infers a tolerance of half the last printed digit, so two-decimal
postings that are off by half a cent load without error.

**A ledger that already has errors can still be booked into.** Only a *new*
load error rolls a batch back.

**The owned file's header.** An included file does not inherit the main file's
`name_assets` … `name_expenses` options. `autobook init` copies those five
options into the owned file's header, and every run compares them with the main
file's. This is the one thing other than transactions that Autobook writes.

**The owned file is not private.** The user may correct an entry in it, and
Fava (a web interface for Beancount ledgers) can edit or delete entries in any
included file. So the writer never regenerates the file: it appends, and on
undo it removes exact spans.

**Idempotency.** Ledger and staging are two stores with no shared transaction.
A crash between "file replaced" and "marked applied" leaves them disagreeing.
The proposal ID in the ledger settles it: before each batch the reader finds
created rows by ID and the filter step drops them, so `apply` can be re-run
after any failure. `autobook status` lists Autobook entries that differ from
what staging recorded, and proposal IDs that staging holds as applied but the
ledger no longer contains. Both are reports, never writes: a missing entry is
not silently created again.

**No lock.** Beancount has no lock. The guards are the compare before the
replace on every ledger file, the single atomic rename, so that no reader sees a
half-written file, and the read-back with the previous content kept. An editor
holding unsaved changes to the owned file is not covered (proposal 0005,
*Risks*).

The ledger package writes transactions only, and only into the owned file. It
never writes `open`, `close`, `balance`, `pad`, `price`, `commodity`, `plugin`
or `include`, so it never creates accounts and never asserts a balance: balance
assertions are the user's independent check on everything Autobook does. It
never changes an entry Autobook did not create, and never edits any other file.

## 5.4 The driver (outside Autobook)

Autobook has no launcher and is not the driver of a run. The **driver** is a
separate project in its own repository. It is described here only so that the
hand-over is clear; none of it is Autobook code.

The driver does what Autobook does not (proposal 0005 §1):

1. gets a statement from the bank or from a document store;
2. converts it to OFX with ofxstatement;
3. decides when to run;
4. calls Autobook's commands (section 5.5) and reads their exit codes and
   `--json` output;
5. puts the review file somewhere private, opens it in an editor, and hands the
   saved file back;
6. notifies the user, for example when a gate refuses or a statement is
   rejected.

What the driver hands over (proposal 0005 §4.1):

| In | Notes |
|----|-------|
| One or more OFX files | To `autobook propose`. Parsed by Autobook's own parser. The memo must arrive unmodified. |
| Optionally, a producer string per file | For example the plugin name and version. Recorded with the statement and part of the version tuple. |
| The saved review file | To `autobook decide` or `autobook apply`. |

What it gets back: an exit code, `--json` output on standard output, and the
review file from `autobook review-file`.

No Autobook command starts an editor or another program. A driver that runs
ofxstatement and Autobook as separate commands combines nothing, which matters
for the licence: ofxstatement is GPLv3 and Beancount is GPL-2.0-only
([ADR-0005](../adr/0005-relicense-gpl-2-or-later.md), status Proposed).

Unattended runs (homelab, no editor) are **[DEFERRED]** beyond v1: approval is a
save of the review file, which needs a human (section 7).

## 5.5 Command line

The command line is Autobook's whole interface; there are no windows. Every
command accepts `--json` for machine-readable output. None of them starts an
editor or another program (proposal 0005 §4.2).

| Command | Does | Touches the ledger |
|---------|------|--------------------|
| `autobook init` | Create the owned file with its header; print the `include` line for the user to add | creates the owned file |
| `autobook propose FILE…` | Admit the statements, dedup, correlate, classify, dispose, run the batch gate, stage | read |
| `autobook pending` | Count and list pending proposals; exit 1 when there are none | none |
| `autobook review-file` | Write the review file to standard output | read (account list) |
| `autobook decide --from FILE` | Parse a saved review file and record its decisions to staging; `--check` parses only | read (account list) |
| `autobook apply --from FILE` | `decide`, then book the approved rows: write, read back, assert | **write** |
| `autobook undo BATCH` | Remove what a batch created; asks for confirmation unless `--yes` | **write** |
| `autobook status` | Last run, pending counts, the version tuple in force, entries that differ from staging | read |
| `autobook export` | Print the reader's contracts (`coa`, `corpus`, `existing`), for inspection and for the trial | read |
| `autobook trial backtest …` | Rolling-origin backtest | read |
| `autobook trial mine` | Mine rule candidates from history (proposal 0004) | read |
| `autobook trial accept` | Record this trial's version tuple for production | none |
| `autobook rules cluster` · `test RULE` · `accept RULE` | Cluster unresolved rows; score a candidate rule against history; add a scored rule to the rules file | read |

Exit codes (proposal 0005 §4.3):

| Code | Meaning | Written |
|------|---------|---------|
| 0 | Done | as the command says |
| 1 | Nothing to do | nothing |
| 2 | Usage or configuration error | nothing |
| 3 | The batch gate or the version gate refused | nothing |
| 4 | The ledger is not writable as expected: the owned file is not included, its root-name options differ from the main file's, or a ledger file changed during the run | nothing |
| 5 | The review file did not parse; the line number is on standard error | nothing |
| 6 | The read-back or an assertion failed; the previous file was restored | nothing persists |
| 7 | A statement was rejected at admission; the reason is reported per file | nothing staged from that statement |

The numbering is fixed when the first command that returns 3–7 lands.

Of these commands, only the backtest exists today, as `python -m
autobook.pipeline.trial backtest` (section 6.6).

**Saving the review file stays the only approval.** `decide` and `apply` take
the saved file; there is no other path from a command to staging decisions or
to the ledger. Whether anything richer than the review file is built (a Fava
extension, a terminal UI) is **[OPEN]** and decided at the last build step (packs and packaging), on
what the review file has turned out to lack (proposal 0005, *Open questions*).

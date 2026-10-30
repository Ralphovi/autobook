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
> that implements it (below). Diagram source:
> [`diagrams/c4-container.mermaid`](diagrams/c4-container.mermaid).

### Package layout

All under `src/autobook/`, one module per building block. Each stub module sets
`__all__` to the one name of its entry point; a block that has been built
(`normaliser`) exports its real API instead.

| Path | Block |
|------|-------|
| `contracts.py` | The versioned JSON contracts (section 5.1). Standard library only. |
| `staging.py` | The staging store (section 5.1). Its own top-level block, because both processes use it. Standard library only. |
| `pipeline/` | `statement_source`, `admission`, `normaliser`, `correlator`, `bill_matcher`, `classifier`, `model_adapter`, `disposition`, `batch_gate`, `review_file`, `trial` (section 5.2). Never imports `gnucash`. `pipeline/profiles/` is package data, not a block: the normaliser's shipped profiles. |
| `book/` | `session`, `exporter`, `applier`, `readback`, `assertions`, `undo` (section 5.3). The only package that may import `gnucash`, per file, as each module needs it. |

The launcher (section 5.4) is a shell script, not a Python module. The client
(section 5.5, proposal 0003) has no package yet; it lands with build step 9. `import
autobook` does not import the subpackages.

## 5.1 Three processes and one store

| Block | Runs as | May link libgnucash | Purpose |
|-------|---------|---------------------|---------|
| **Pipeline** | Python in a virtualenv | **No — enforced by the gate** | Everything from statement to approved proposal |
| **Book process** | System Python (`python3-gnucash` in `dist-packages`) | Yes, and nothing else does | Every read from and write to a book, in two parts: the **exporter** (read-only, from build step 2) and the **applier** (writes, from build step 5) |
| **Launcher** | Shell wrapper around `gnucash` | No | Sequencing: backup, read-only export, pipeline, review, apply, assert, open GnuCash |
| **Client** (proposal 0003, draft) | GTK4 windows; Python with PyGObject | No, and it does not import the pipeline either | Runs `autobook` subcommands with `--json` and renders them; edits the review file; never a second approval path (section 5.5) |
| **Staging store** | SQLite in `$XDG_DATA_HOME` (default) or a PostgreSQL URI | — | Audit trail, correction corpus, undo list; the seam between classification and writing |

The split between pipeline and book process is load-bearing (proposal 0001,
*Why the boundary matters*): it keeps the pipeline testable with no GnuCash
installed and no book present, sidesteps the `dist-packages` virtualenv problem,
and makes a future Windows port a component swap.

The ban on importing `gnucash` applies to the **pipeline**. It is lifted for the
whole book process, exporter and applier alike. The `nox -s applier` session and
the pytest `applier` marker keep that name (renaming code is out of scope) but
cover every book-process test.

### The JSON contracts

All communication between pipeline and book process is JSON on stdin/stdout or
in files under the staging directory. Each contract is versioned; widening one is
a documented change that updates this section in the same PR.

Wire shape, implemented in `autobook.contracts`:

- Every document is a JSON object with its `contract` name (`"corpus"`,
  `"coa"`) and an integer `version`, starting at `1`. A reader accepts only a
  name and version it knows, and rejects anything else with `ContractError`.
- Money is a plain integer of cents. A float or a boolean is rejected.
- An account is a **list of path components**, root account excluded, never a
  separator-joined string. GnuCash takes the account separator from a user
  preference outside the book (`.` in a headless session, often `:` on a
  desktop), so a joined string would mean different things on different
  machines. Nothing in the contracts joins or splits a path.
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
  `provenance` is always `"observed"`: the contract refuses `corrected`.
- `coa` is `{"contract", "version", "accounts"}`. An account has `path`, `type`
  (one of GnuCash's account-type names, exact case: `NONE`, `BANK`, `CASH`,
  `CREDIT`, `ASSET`, `LIABILITY`, `STOCK`, `MUTUAL`, `CURRENCY`, `INCOME`,
  `EXPENSE`, `EQUITY`, `RECEIVABLE`, `PAYABLE`, `ROOT`, `TRADING`, `CHECKING`,
  `SAVINGS`, `MONEYMRKT`, `CREDITLINE`), `placeholder`, `commodity`
  (`{"namespace", "mnemonic"}`) and `fraction` (an integer greater than zero).

| Contract | Direction | Carries |
|----------|-----------|---------|
| `corpus` | book → pipeline | Two-split transactions: `(normalised-able raw memo, amount_cents, sign, source_account, destination_account, post_date)`, every one with provenance `observed`. Read-only session. `corrected` rows never come from the book; the pipeline adds them from staging. |
| `coa` | book → pipeline | The live account tree: paths (component lists), types, placeholder flags, commodities and their fractions. |
| `existing` | book → pipeline | Autobook IDs already present in `num` (idempotency); per source account the transactions in a date window, for the `match_existing` search; and the **scheduled-transaction (SX) definitions** — template accounts, amounts, recurrence — so the pipeline can tell when a row falls on an SX occurrence. Read-only session. |
| `apply-in` | pipeline → book | Approved rows: `proposal_id`, disposition, source and destination (or split specification), `amount_cents`, the source account's commodity, date, description, optional `doc_link`, optional `match_guid`. |
| `apply-out` | book → pipeline | Per row `{proposal_id, tx_guid, status}`, where `applied` is reported only after a read-back has found the transaction; per batch the assertion results. |

The `match_existing` search runs in the pipeline, over the `existing` export, so
that a row can be queued as awaiting a scheduled transaction or a pending
transfer and the review file can show the match. The applier re-checks the
matched GUID inside its write session before touching it. This settles the
earlier open question of whether `existing` is a separate call: the SX
definitions and the transfer search before classification both need it before
the pipeline runs.

## 5.2 Pipeline components

### Statement source

An interface with two first-class implementations: **paperless** (proposal 0002
§3) and **files**. Both yield `(original bytes, checksum, source_account, plugin)` to the
same admission path, so the plugins cannot tell where a statement came from. The
paperless source resolves statements through an explicit mapping of
correspondent and document type to source account; unmapped statements are
reported, never guessed.

### Admission and dedup

Runs the mapped ofxstatement plugin, applies the **balance check** where the
format has balances, and assigns row keys. Every key includes `source_account`.
Each plugin declares whether its `id` is bank-supplied. A bank-supplied FITID
is the key where present; otherwise — including IDs a plugin synthesises, such
as ofxstatement's hash of date, memo and amount — the key is
`(source_account, original_checksum, line_ordinal)` plus the period-overlap
rule. The overlap rule's line matching is **count-aware**: two identical lines
in the overlap need two identical staged lines.

Every statement gets a `statements` row, from paperless or from a file (the
checksum is the file's), so both paths can be compared row for row. For a
paperless statement, admission records the document version and fetches the
original with `?version=`. A statement that fails admission is rejected whole
and recorded with status `rejected` and its reason; other statements proceed.

**[OPEN]** until D0: whether statements arrive as PDFs or as the CSV/OFX exports
the plugins read today (proposal 0002, *Open questions*). PDF parsing is not a
settled part of this design.

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
(proposal 0001); the cost is a backtest re-run, which is what the version gate
forces. This string, not `NORMALISER_VERSION` alone, is the normaliser version that
is recorded with every vector, in the version tuple (section 8.3) and in the
`normaliser_version` staging column; the integer alone would miss a user's profile
edit (section 8.8).

### Correlator

The only component with a cross-account view. Pairs the two sides of transfers
between the user's own accounts and emits the transfer from one canonical side.
Without it every transfer is booked twice.

Transfers also span batches. Every transfer row first goes through a
`match_existing` search in its **source** account, before classification: the
second side of a transfer booked in an earlier batch resolves to the transaction
the first side created, which has splits in both accounts. A transfer booked
from one side records a `transfers_pending` entry (counterpart account, amount,
date window, the first side's proposal ID and transaction GUID). An unmatched
second side whose counterpart is pending is queued as "pending transfer", never
classified.

PayPal follows the configuration key `paypal_mode`:

- `account` (default): PayPal is its own GnuCash account and its statement is
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
date or account. Its only downstream effect is to make document conditions
(correspondent, document type, tag) available to rules, and a `doc_link`
available to the applier.

A bill without a correspondent, or whose correspondent has no confirmed association, can only produce `doc_match = weak`: a hint line
in the review file, never input to a rule. Which paperless document types count
as bills and which as credit notes is configuration, and part of the version
tuple.

### Classifier

The cascade runs **rules → kNN → LLM** (k-nearest-neighbour, then a large
language model). Precedence is one table, which governs everywhere. It is
stated in full in proposal 0002 §5.1 (document conditions); proposal 0001's
*Rules* section points to it. In short:

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
  account list, minus placeholder accounts and Equity and Trading account types;
  output outside it is rejected. Temperature is pinned to 0, and the model ID is
  recorded in the version tuple. An LLM proposal is always `?` until shadow mode
  has measured per-method precision for `method=llm`; only then may a threshold
  pre-mark LLM rows. Optional.

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

The default backend is **local** (Ollama, llama.cpp …). A remote backend is
opt-in, and then receives a token only when it matches a rule-pack entry or the
user's allowlist of business names; for any other token the LLM abstains and the
row is queued.

### Disposition

Assigns each row one of `create | create_split | match_existing | out_of_scope |
queue`. Out-of-scope rows (securities, split-currency) are recorded and visible
but excluded from the queue and from coverage and drift metrics.

A row in a source account whose amount and date (± the match window) fall on an
SX occurrence is **never `create`**: it is `match_existing` if GnuCash has
created the instance, otherwise `queue` with the reason "awaiting scheduled
transaction", which resolves on a later run. `match_existing` searches the
row's **source** account (an SX transaction may have many splits), among
transactions not already claimed by Autobook — no Autobook ID in `num` and no
GUID in staging's `applied_tx_guid`. Whether a candidate is reconciled does not
matter.

### Batch gate

Decides whether anything is written at all: coverage below a rolling baseline,
LLM-fallback spike, unusual share of rarely used accounts, parse errors above a
small count, a changed version tuple, paperless unreachable. Any of these writes
nothing and notifies; the launcher still opens GnuCash.

### Review file

Generates a `git rebase -i`-style text file at
`$XDG_RUNTIME_DIR/autobook/review.txt` (mode `0600`, removed in `finally`)
listing the batch's in-scope rows. Rows that passed the gates
are pre-marked `a` (accept); everything else is `?`. **Saving the file is the
user's approval of every row marked `a` in the saved file**, with the account,
amount and date shown. Nothing else reaches the book.

The file is parsed back **by ID, never by position**, strictly: an unknown ID,
status character, account or an amount change aborts the whole parse with a
line number. A row with a weak bill match carries a hint line, nothing more.
Corrections are recorded as `corrected` corpus rows. Until the
applier exists (build step 5), saving the file records the decisions to staging
and writes nothing.

### Trial tooling (scenario 1)

Never touches a book except through the exporter's read-only corpus export.
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
proposal 0004), the **rule builder** (cluster, propose, backtest immediately,
accept — GTK4 eventually, CLI first), the
**assistant detector** (recurring debits and loan-shaped payments handed to
GnuCash's assistants), the **pack validator**, and from proposal 0002 the
**linkage backtest**.

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

This is the single staging schema; the proposals' schemas match it.

```
statements(original_checksum PK,          -- of the paperless original or the file
           paperless_doc_id, doc_version, -- NULL for file ingest
           source_account, plugin, plugin_version,
           period_start, period_end, opening_balance, closing_balance,
           balance_check,                 -- passed | not_possible
           status, reason,                -- admitted | rejected; why rejected
           admitted_ts)                   -- time of the admission decision

proposals(source_account, fitid_or_key,   -- PK (source_account, fitid_or_key)
          proposal_id,                    -- AB- + ULID; in num on created transactions only
          post_date, amount, currency,
          raw_memo, normalised_memo,
          proposed_account, confidence, method, rule_id,
          disposition, queue_reason, status,  -- status: pending|approved|rejected|applied
          applied_tx_guid, human_correction,
          statement_checksum, doc_id, doc_match, doc_candidates,
          classifier_version, normaliser_version, ts)

transfers_pending(counterpart_account, amount, window_start, window_end,
                  proposal_id, tx_guid)   -- first side of a cross-batch transfer
```

`fitid_or_key` is the bank-supplied FITID, or for statements without one the
`(original_checksum, line_ordinal)` pair. The **proposal ID** is something
else: `AB-` followed by a ULID (a 26-character sortable unique ID, short enough
for GnuCash's `num`), generated per staged row. Only `num` values matching
`^AB-[0-9A-HJKMNP-TV-Z]{26}$` count as Autobook IDs. `statement_checksum` is set
for file ingest as well as paperless ingest. A row is `applied` only after the
book process's read-back has confirmed it.

Amounts are integer cents. Document fields are IDs and counts, never content.

## 5.3 Book process components

The book process has two parts: the **exporter**, which only reads and exists
from build step 2, and the **applier**, which writes and exists from build step
5. They share the session manager.

| Component | Responsibility |
|-----------|----------------|
| **Session manager** | Opens with `SESSION_NORMAL_OPEN` for writes and `SESSION_READ_ONLY` for export and dry-run; never `SESSION_BREAK_LOCK`; one session per run. On the write path: after the last `CommitEdit`, `session.save()`, then the post-apply assertions, then `session.end()` in `finally`. On `ERR_BACKEND_LOCKED` (the lock error in `qofbackend.h`) it writes nothing and the launcher notifies. `SESSION_READ_ONLY` ignores locks, so an XML export with the GUI open reads the last *saved* state. |
| **Exporter** | Produces `corpus`, `coa` and `existing` (including SX definitions) through the engine API, in a `SESSION_READ_ONLY` session. |
| **Applier** | For each approved row. `create` / `create_split`: skip if its proposal ID is already a `num`; otherwise create (two splits, or a split specification that sums exactly) with the proposal ID in `num`. Before building `GncNumeric(cents, 100)` it takes the source account's commodity, verifies that both accounts share it and that its fraction is 100; no currency is hard-coded. `match_existing`: re-check the matched GUID; write **no `num`** and **no FITID / `online_id` stamp** to it. The only thing ever written to a matched transaction is a document link, and never over an existing one. Every mutation inside `BeginEdit` / `CommitEdit`. |
| **Read-back** | A row is reported `applied` (in `apply-out`, and in staging) only after a read-back confirms it. XML: reopen `SESSION_READ_ONLY` and find its ID. SQL: an engine query. With XML nothing persists until `save()`, so a batch is all-or-nothing; SQL is durable per `CommitEdit` and `save()` is harmless. |
| **Assertions** | After the batch, for each source account with a statement in the batch: (a) the change in its balance caused by the batch equals the sum of the rows applied; (b) where the statement has a closing balance, the account's balance on the closing date equals that closing balance minus the statement lines not yet applied (queued, `out_of_scope`, awaiting a scheduled transaction, pending transfer); (c) the Imbalance account is **unchanged** by the batch. Non-zero exit on failure. |
| **Undo** | Deletes only transactions whose GUID is in staging with disposition `create` **and** whose `num` equals that row's proposal ID, asserting both before each delete. For a matched row it removes only the document link the batch added. |

It never creates accounts, never creates scheduled transactions, never sets the
reconciled flag, and never uses SQL against the book.

## 5.4 Launcher

A short shell wrapper that the user runs instead of `gnucash`. It arrives with
the applier in build step 5; before that there is nothing to sequence.

1. Back up the book: a file copy where the backend is a file; `pg_dump` for a
   PostgreSQL book when it is on `PATH`, with the database credentials from the
   Secret Service, otherwise a warning; a warning for MySQL.
2. Run the book process's exporter (read-only).
3. Run the pipeline; if proposals are pending, generate the review file at
   `$XDG_RUNTIME_DIR/autobook/review.txt` (mode `0600`) and open `$EDITOR`.
4. Run the book process to apply, save, assert and read back. Remove the review
   file.
5. `exec gnucash` — always, regardless of the outcome of 1–4.

The launcher must always reach `exec gnucash`. There is no `set -e` abort path:
each step runs as `step || notify`, the steps run inside a function, and a
`trap` makes sure the `exec` happens and the review file is removed.

Unattended runs (homelab, no editor) are **[DEFERRED]** beyond v1: approval is a
save of the review file, which needs a human (section 7).

## 5.5 Command line and windows (proposal 0003)

> Designed in [proposal 0003](../proposals/draft/0003-windowed-interface-and-command-line.md),
> still `draft`. Where this section and the proposal disagree, the proposal
> governs.

**The command line is the primary interface.** Every step of the journey is an
`autobook` subcommand: `run` (the launcher's sequence), `gui`, `backup`,
`export`, `propose`, `pending`, `review-file`, `decide --from`, `apply --from`,
`undo`, `status`, `trial backtest` / `trial accept`, `rules cluster` / `test` /
`accept`, `assistants` (proposal 0003 §2.1). With `--json`, stdout is one
versioned contract document and messages go to stderr; no command prompts
without a TTY; exit codes are 0 done, 1 nothing to do, 2 usage or input error,
3 gate refused, 4 book locked, 5 review file did not parse, 6 assertion or
read-back failed (§2.3).

**The windows are a client of the command line.** GTK4 windows — Start, Review,
Booking, the refusal dialog and Trial (Backtest, Rule Builder, Assistants) —
run the subcommands as subprocesses and render their `--json` output. The
client imports only `autobook.contracts`; it never imports `gnucash` or the
pipeline.

**The review file is the Review window's state.** The window loads
`autobook review-file`, edits its lines, renders the list from parsing that
text, and hands it to `autobook decide --from` (*Save Decisions*) or
`autobook apply --from` (*Approve and Book*). Saving the review file stays the
approval in both surfaces; there is no other path from a window to staging or a
book. *Open in Editor…* blocks the window while `$EDITOR` has the file and
re-parses on return.

`autobook gui` is the launcher with the Review window as its review step and
keeps the launcher's invariant: it always reaches `exec gnucash`.

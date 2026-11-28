# Agent instructions — Autobook

This repository is the source of truth for Autobook code, design docs, and CI.
Treat repo policy as part of the work: make changes in an isolated worktree,
sign off commits, link PRs to issues, and run the gate that matches the surface
you changed.

**This project writes to people's accounting books.** A silently wrong booking
is worse than a loud failure, and worse than no booking at all — it misreports
for years and may reach a tax filing. Every rule below that looks pedantic is
there because the failure it prevents is invisible.

**The design is [proposal 0005](docs/design/proposals/draft/0005-beancount-ledger.md):**
Autobook is handed OFX statements and books them into a Beancount v3 plain-text
ledger. It replaces the earlier GnuCash design. The proposal is a draft, and
parts of the tree still date from the GnuCash design: the stubs under
`src/autobook/book/`, the tests under `tests/book/`, the test environment's
`book` image, the `applier` nox session, and the linter's ban on `gnucash`. Do
not extend those. New ledger code follows the rules below.

## Worktree discipline

- Do implementation work in a dedicated Git worktree, not in the user's active
  checkout, unless the user explicitly asks otherwise.
- Name worktrees by task or branch, for example `../autobook-knn-backtest` or
  `../autobook-fix-fitid-dedup`.
- Before editing, inspect `git status -sb` in both the active checkout and the
  worktree you plan to use. Do not overwrite unrelated user changes.
- Keep each worktree scoped to one PR-sized change. If a task splits, create a
  second worktree/branch rather than mixing unrelated files.
- When a dependent PR has landed, fetch `origin main`, rebase the worktree
  branch onto it, resolve conflicts locally, rerun the gate, and push with
  `--force-with-lease`.

## Publishing defaults

- Open draft PRs unless the user explicitly asks for ready-for-review.
- Every non-Dependabot PR must reference a real issue in the title or body. Use
  `Closes #N`, `Fixes #N`, or `Refs #N`; prefer closing keywords when the PR
  fully resolves the issue.
- Every commit must carry a DCO sign-off trailer. Use `git commit -s` for new
  commits. If a commit is missing the trailer, fix it before pushing with
  `git commit --amend -s --no-edit`.
- Verify sign-off before final push with `git log -1 --format=full`.
- After a rebase or amend on a published branch, push with
  `git push --force-with-lease`.

## Required PR gates and local actions

- **DCO (`dco`)** — every commit must include a `Signed-off-by:` trailer. This
  applies to docs-only changes too.
- **Issue linkage (`require-issue`)** — every non-Dependabot PR must reference a
  real issue, not only another PR.
- **Gate (`ci` / required job: `gate`)** — run `nox -s gate` locally. This is the
  single-sourced gate: formatting, lint, types, tests, spelling, and the docs
  lint. It is the same command CI runs and the same command the PDCA (Plan-Do-Check-Act) harness
  delegates to; never re-declare gates elsewhere.
- **Ledger tests are part of `gate`.** Reader and writer tests run against
  synthetic ledgers the tests build in temporary directories, on every
  supported Python version. They need no Docker image.
- **Live-paperless tests (`nox -s live`)** run inside the throwaway **test
  environment** (`testenv/`, Docker): paperless-ngx 3.3.0 on an internal
  network with no outbound access. They are not part of `gate`; CI runs them in
  the `testenv` workflow.
- **GnuCash-era tests (`nox -s applier`)** run in the same environment, against
  its GnuCash 5.14 image. They remain only for the one-off conversion of a
  GnuCash book (proposal 0005 §14) and are removed with it. Nothing new belongs
  there except the conversion's export half.
- **Unattended runs only touch synthetic ledgers (MUST).** CI and the PDCA
  driver run ledger, conversion and paperless tests only against ledgers and
  books the tests build and the documents `testenv/seed/` creates. A real
  ledger or a real GnuCash book, or a copy of one, is opened only by a human,
  attended — and never mounted into the test environment. A test fixture never
  contains a real transaction.

If a tool the gate needs is not installed, the session warns and skips. Never
report a skipped step as having run.

### Where the tests run, and how each place gets the dependencies

The tests run in four places, and each installs Autobook's dependencies its own way. A
change that adds, removes or bumps a dependency in `pyproject.toml` must work in all four;
a plan or brief that adds one says how it reaches each (#53).

| Where | Runs | Gets `[project].dependencies` from |
|---|---|---|
| `nox -s gate` (CI job `gate`) | lint, types, the pipeline and ledger tests | `pip install -e .` in nox's venv |
| CI `test-matrix` (Python 3.11–3.14) | the pipeline and ledger tests | `pip install -e .` in nox's venv, per interpreter |
| the test environment (`testenv/`, CI workflow `testenv`) | paperless and GnuCash-era tests | the `book` image's venv, built from the tree's `pyproject.toml` (`testenv/book/Dockerfile`) |
| the PDCA instance (Ralphovi/autobook-pdca) | the bundle's tests, on the host | the instance `.venv`, synced from the worktree's `pyproject.toml` before each check |

pytest imports **every** test module before it filters by marker. So a test module that
imports a new dependency breaks the test environment's run even when it holds no test that
runs there — the image must have the dependency too. Only `[project].dependencies` reach the image,
never the `dev` extra: test modules must not import a dev-only tool. `beancount` is an
ordinary dependency and reaches all four. `python3-gnucash` is a system package, is needed
only by the conversion's export half, and stays out of `pyproject.toml`.

## The ledger-package boundary is load-bearing

Autobook is one process. Inside it, the **ledger package** is the only code
that imports `beancount`. It has two parts: the **reader**, which loads the
ledger and never writes (chart of accounts, history, existing entries, file
hashes, load errors), and the **writer**, which appends approved rows to the
owned file, reads back, asserts, and undoes. Everything else — statement input,
the pipeline, staging — reaches the ledger through the contracts.

The split is not a style preference. It is what keeps input, pipeline and
staging testable against fixtures with no ledger on disk, and it keeps every
rule about writing in one place.

- **Only the ledger package imports `beancount`.** Not in a function body, not
  behind a `try`, not lazily. If you find yourself wanting to elsewhere, the
  design is wrong — move the work behind a contract.
- **Nothing imports `ofxstatement`.** Autobook is handed OFX files; it does not
  run the converter. This is also a licence rule (see *Dependencies and
  licence*).
- **Nothing imports `gnucash`**, except the export half of the one-off
  conversion tool.
- **Nothing outside the ledger package parses ledger text.** Assertions,
  idempotency checks and balance checks go through the reader.
- The contracts (`corpus`, `coa`, `existing`, `apply-in`, `apply-out`) are typed
  and serialise to JSON. Widen them deliberately and document it; don't smuggle
  behaviour across by convention.
- **Autobook is not the driver.** It starts no editor and no other program, and
  it does not fetch statements. A driver, which is a separate project, calls
  its commands and reads its exit codes and `--json` output.

## Hard rules for anything touching a ledger (MUST)

**The books must be correct at the end. An import with an error is rejected,
not accepted.** Every rule here has a silent-corruption failure mode. Violating
one does not produce an error — it produces a wrong ledger.

- **Write only to the owned file, and only transactions.** The owned file is
  the one file named in the configuration that the user's ledger includes.
  Never write `open`, `close`, `balance`, `pad`, `price`, `commodity`, `plugin`
  or `include`, and never edit any other file. The one exception is the owned
  file's header, where `autobook init` copies the main file's five root-name
  options, because an included file does not inherit them.
- **Never create accounts.** That is: never write `open` or `close`. A chart of
  accounts encodes how someone thinks about their money and may map to tax
  categories an accountant specified. An account under the wrong root does not
  error, it misreports forever.
- **Never write `balance` or `pad`.** Balance assertions are the user's
  independent check on everything this tool does. Writing one to make a number
  look right defeats the tool's only external audit.
- **Never change an entry Autobook did not create.** Nothing is written to a
  matched entry — no metadata, no link, no tag.
- **Never regenerate the owned file.** The user and Fava may edit entries in
  it. Append; on undo remove exact spans.
- **Only an admitted statement is skipped on its checksum.** A rejected one is
  checked again when handed over again.
- **A statement is admitted whole or not at all.** A statement that fails any
  admission check (parse, a line without date, amount or currency, an unknown
  account ID, a currency the ledger account does not declare, lines that do not
  add up to the stated balances, an overlap the rule cannot resolve, a repeated bank ID whose date, amount or
  currency differs from the staged line, a bank ID twice in one statement) is
  rejected whole, its reason recorded, and no line of it is staged.
- **A batch is booked whole or not at all.** A failed read-back or assertion
  restores the previous content of the owned file and marks nothing applied.
  There is no partial batch.
- **Compare before replacing.** Nothing is written if any ledger file changed
  since it was read, and the resolved include set (globs expanded) is part of
  what is compared; the compare is repeated after the journal and temporary
  file are durable, immediately before the exchange. Load from a snapshot: read each
  file once, hash those bytes, copy them to a private directory and let
  Beancount parse the copy, then compare the live files and include set with
  the snapshot and retake it if anything moved, so the hashes are of the bytes
  Beancount parsed. The replace is one atomic **exchange** (`renameat2` with
  `RENAME_EXCHANGE`) with a file written and flushed in the same directory,
  never a plain rename. The swapped-out file is never deleted and never renamed:
  the temporary file is given its final, operation-unique pre-image name
  beside the owned file before the exchange, it and its directory are fsynced
  before the exchange, the journal names it, and its
  path, batch and hash are recorded in staging (`preimages`) before the
  journal is removed, and `autobook status` reports one whose
  content changed since (an editor that still held the old file open). Autobook
  has no command that deletes a pre-image; the user deletes them by hand and
  then runs `autobook forget PATH`, which removes only the staging record and
  refuses while the file still exists.
  Also: after the exchange, hash and `fstat` what was swapped out, and if
  it is not the content the batch was rendered from, or its mode, owner,
  group or ACL changed since the last check, exchange back and write
  nothing. Exchanging back is checked the same way; if the file was saved
  again in between, keep every version as a file, stop and report the
  conflict. **Never delete a version Autobook displaced.** A plain rename would silently overwrite a save that got in after
  the last hash. No fallback to a plain rename where the exchange is
  unavailable: refuse. Beancount has no lock; against editors and
  Fava this is the guard.
- **One Autobook writer at a time.** `propose`, `apply`, `undo` and `decide` take
  Autobook's own writer lock (an advisory lock on a file beside the staging
  store, never in the ledger's directory) before they parse the review file or
  record any decision, and before the first read of the ledger, and hold it until staging is
  updated. Without it, two runs can both pass the compare and the second
  overwrites the first. A run that cannot take the lock writes nothing.
- **Read back, then report.** After the replace, load the ledger again. A row
  is reported applied — in `apply-out` and as `applied` in staging — only after
  the read-back and every assertion have passed. For a created row the
  read-back finds its proposal ID exactly once with the approved date, accounts,
  and each posting's amount and currency. A matched row wrote nothing, so its ID is not looked for: its
  search, run again, must find exactly one candidate and it must be the recorded
  entry — except for a row the user rebound, whose recorded entry must pass the
  full predicate, unclaimed, but need not be the only candidate. The search runs at proposal, again at apply, and again in the
  read-back.
- **The assertions.** The load reports no error it did not report before the
  write. No other file changed, and the owned file's hash is exactly the
  rendered content's,
  so an edit inside the appended entries is caught; such a save is kept as a
  conflict (exit 4), never exchanged away. If only another file changed and
  the owned file still holds the rendered content, the batch is rolled back
  (exit 6). The balance of every account the batch wrote postings to
  moved by exactly the sum of those postings, and no other balance moved; a
  matched row writes none and moves nothing. Where the statement states a closing balance, the ledger's balance
  on that date equals it minus the account's staged lines up to that date not
  yet applied, from every admitted statement (a closing balance is cumulative). A line
  not yet applied that has any match candidate may already be in the ledger:
  then (counting only candidates dated by the closing date) the closing-balance assertion is deferred and reported, never failed
  and never satisfied by marking the line applied. Where the bank's balance
  carries a time before the end of the day and the account has any movement
  on that date, the assertion is likewise deferred ("intraday cutoff"): a
  date-only ledger cannot say which of that day's movements the bank counted.
- **Money is exact.** Amounts are `Decimal` built from **integer cents** and
  printed with exactly two decimals. Never floats, in any code path, including
  tests and fixtures; the hazard is `Decimal(float)`, which accepts a float
  without complaint. Money in a rules file is `cents: 1250`, never
  `value: 12.50`.
- **The currency is read, never assumed.** Take it from the statement, check
  that the source account's `open` directive declares it and that the other
  account's allows it. No hard-coded `EUR`.
- **Every posting has an explicit amount, and postings sum to exactly zero.**
  Never leave an amount for Beancount to fill in. Check the sum yourself:
  Beancount infers a tolerance of half the last printed digit, so two-decimal
  postings that are off by half a cent load without error. A computed split
  specification that does not sum to the line's amount fails the row loudly.
- **Accounts must be open on the row's date.** A row whose account is not open
  then, or is closed, is queued. It is never written to produce a load error.
- **The proposal ID.** `AB-` followed by a ULID, generated once per staged line
  and stored in staging. It is not the staging key. Only a value matching
  `^AB-[0-9A-HJKMNP-TV-Z]{26}$` in `autobook-id` metadata counts as Autobook's;
  anything else belongs to the user.
- **`autobook-id` only on entries Autobook creates.** A created entry carries
  its proposal ID in `autobook-id`. On a `match_existing` row Autobook writes
  nothing to the ledger. Staging records the candidate found at proposal in
  `matched_entry` (its `autobook-id` if it has one, otherwise its content hash)
  and copies it to `applied_entry` only after the batch is validated.
  `applied_entry` means validated, never merely proposed.
- **`match_existing` searches the row's source account**, not the target
  account, for an entry whose net movement in that account (the sum of its
  postings there) equals the row's amount **and currency** (an account
  may hold several currencies; the number alone is not a match), and its candidates are entries not already claimed **for that
  source account**: an entry is claimed for an account when a staged row of
  that account created it (its proposal ID, once applied) or matched it
  (`matched_entry`); the claim lookup covers both. An `autobook-id` alone does not exclude
  an entry, or the second side of a transfer could never match the entry the
  first side created. An ambiguous or
  absent match is queued; never guess between candidates. Do not filter on
  whether the user has asserted a balance since.
- **A pending match claims too.** An entry is claimed by another row's
  `matched_entry` from proposal on, while that row is `pending`, `approved` or
  `applied` (a row never excludes its own candidate; a rejected or skipped row
  releases its claim), not only by a validated `applied_entry`,
  so two pending rows can never select the same entry.
- **A live journal blocks `propose` and `decide`.** `propose`, and a `decide`
  that would record a decision, refuse while a batch journal exists, so
  nothing is matched, classified or decided against a batch that was written
  but not validated; `apply` or `undo` recover it first.
- **A committed batch is never rolled back.** The staging transaction that
  marks the rows records the operation (an ID per apply or undo attempt, also
  in its journal) as committed; a journal left after that
  commit is only cleaned up, never validated or restored again.
- **A changed pre-image blocks writing.** `propose`, `apply` and `undo` re-hash every
  kept pre-image first, again in the compare before the exchange and again as
  the last assertion before rows are marked applied (matched-only batches
  too), and refuse while one differs from its recorded hash or is missing
  without having been forgotten:
  that is a displaced save the owned file does not contain.
- **A batch with only matched rows writes nothing.** No render, no exchange,
  no journal, no pre-image; it is validated against the unchanged load.
- **A claim outlives an edit.** If a matched hand-written entry's hash is no
  longer in the ledger, its claim becomes an orphaned claim, and matching is
  paused for that whole source account: every line that would match there is
  queued until the user resolves the orphan. Autobook cannot tell which entry
  the edited one is, so blocking only the old amount and date is not enough. Dropping the claim would
  let two payments become one entry. The user resolves it in the review file:
  `m` on exactly one listed candidate (an entry that passes the full match
  predicate, identified by its content-hash prefix) rebinds the row after
  `decide` re-runs the predicate under the lock; `x` on the row releases the
  claim and rejects it. Never rebind to an entry the search would not match.
  A rebind stores the entry's canonical identity, as an ordinary match does
  (`autobook-id` if present, else content hash); the hash prefix only selects. A
  rebound row (`match_source = rebound`) must pass the predicate, unclaimed,
  at apply and in the read-back, rather than be the only candidate.
- **A created row never posts back to its source account.** Its destination,
  and every split posting except the source posting, is another account; the
  parser rejects such an edit (exit 5), a classifier proposing it is queued,
  apply step 3 queues the row, and the read-back requires exactly one posting
  in the source account. Otherwise `-x + x = 0` hides the bank movement from
  every balance check.
- **A matched hand-written entry is identified by its content hash**, excluding
  metadata and file position. Never by file and line: both move whenever anything above the
  entry is edited.
- **A transfer is booked once.** Every transfer row goes through a
  source-account `match_existing` search *before* classification. When both
  sides are staged before either is booked, the correlator pairs them and only
  the canonical side (first in the configuration) is classified; the other is
  queued as "pending transfer". `transfers_pending` is recorded at proposal,
  and apply queues the second of two created rows that are one transfer's two
  sides — compared by net movement per account and currency, so a split with
  a fee leg, or two legs to the same account, is caught. The owned path must be
  a regular file, never a symlink (checked with `lstat` at preflight and again
  before the exchange). No include glob may match `.autobook-tmp-*` or
  `.autobook-preimage-*` beside the owned file, and no include path may be
  absolute (the snapshot copy could not redirect it); the preflight refuses
  both. The exchange back checks mode, owner, group and ACL state as well as
  content.
  The side kept is the one whose entry the other side's exact-amount match
  would find (the fee-bearing split, not the plain 100); configuration order
  decides only when both qualify, and neither qualifying queues both. The
  comparison also runs against staged rows outside the batch, so a plain side
  waits ("pending transfer") while the fee-bearing side is still undecided. Apply also searches again, in both accounts against the live ledger,
  for every created row whose destination, or any split posting, is one of
  the user's own accounts (split postings summed per account and currency), and queues it
  if a search finds a candidate. This screen ignores claims: an
  entry already claimed in that account still queues the row, though it never
  becomes the row's match. The second
  side of a transfer whose first side was booked in an earlier batch resolves
  to the entry the first side created. An unmatched second side whose
  counterpart is in `transfers_pending`, with the same amount and currency, is queued as "pending transfer", never
  classified.
- **An interrupted batch is validated before it counts.** Before the replace,
  write the batch journal beside the staging store. It holds the complete
  baseline the assertions need: proposal IDs, the hash of every loaded file,
  the owned file's hash after the replace and its previous content, the path
  holding the swapped-out content after the exchange, the first load's errors,
  and every account's balance. Before it ever discards a journal, a run
  records the file at the journal's pre-image path in staging, after checking
  it holds the content it must: the owned file's previous content when the
  exchange was kept, or the batch's rendered content when the exchange never
  happened or was undone. Anything else is a displaced save: keep the journal
  and refuse. The final pre-image name is given only to a complete, fsynced
  file (write a scratch file, then rename), so a crash never leaves a partial
  file under that name.
- **Preflight before decisions.** `apply` takes the lock, recovers any
  journal and checks the kept pre-images before it parses the review file or
  records any decision, so a refusal leaves staging unchanged. A run that
  finds a journal first checks staging: a committed operation is only cleaned
  up. Otherwise it classifies the owned file by the journal's hashes. With the
  *before* hash the exchange never happened or was undone, and the pre-image
  path holds the rendered batch: record it (content and metadata checked),
  never install it. Only with the *after* hash does it check the swapped-out
  file: if it is missing, or not the previous content, or its metadata
  differs, a save or a permission change got in just before the exchange, so
  exchange back (or, if missing, keep the journal) and mark nothing applied.
  Only then does it validate that batch against the journal's baseline, never against the
  ledger as it now stands, or restores the previous content — also when
  another ledger file changed in the meantime. If the owned file matches
  neither recorded hash it touches nothing and reports.
- **The exchange keeps the ledger private.** The exchange puts the scratch
  file's inode at the owned path, so create it with `O_CREAT | O_EXCL |
  O_NOFOLLOW`, mode `0600`, then `fchmod` it to the owned file's mode, and
  `fchown` it to the owned file's group (refuse if the user is not a member),
  check the scratch file for an inherited ACL or extended attribute before
  widening its mode (a default ACL on the directory; refuse if present),
  and check mode, owner and group with `fstat` before the exchange; the umask must never
  decide who reads the ledger. Refuse (exit 4) an owned file not owned by the
  running user or carrying an ACL or extended attributes. The journal (it holds
  the previous content) and staging are `0600` in a `0700` directory.
- **Writes are durable in order.** Write the journal under a scratch name,
  `fsync` it, rename it to its final name and `fsync` its directory, all
  before the exchange, so a live journal is always complete; `fsync` the temporary file before the exchange and the
  owned file's directory after it; `fsync` the owned file's directory after an exchange back too, before the
  pre-image is recorded or the journal removed; `fsync` after removing the journal. Recovery `fsync`s the owned file's
  directory before it commits a validated exchange to staging. An
  exchange that survives a power loss while its journal does not is an
  unvalidated batch. Finding IDs in the ledger proves presence, not validation.
- **Idempotency on re-run.** Before each batch, find created rows by their
  `autobook-id` and matched rows by the hash in staging, verified in the
  ledger; drop both. This is what makes `apply` safely re-runnable after any
  failure.
- **A missing entry is reported, never re-created silently.** A proposal ID
  that staging holds as applied and the ledger no longer contains was removed
  by someone. Report it. Apply reads a row's staged status before recording
  the file's decisions, so such a row is excluded also when a saved review
  file marks it `a` again. Every created row is searched again in its source
  account at apply, so an entry booked by hand after the proposal queues the
  row instead of being duplicated.
- **Undo is narrow.** Undo removes an entry only if its `autobook-id` is the
  proposal ID of a staged row with disposition `create` or `create_split` in
  that batch **and** the entry is in the owned file — assert both before
  removing. It goes through the same compare, replace and read-back as apply.
  Undo of a matched row changes staging only. Undo has its own read-back (the
  removed IDs are absent, the owned file is the previous content minus exactly
  the removed spans, balances moved by minus the removed postings); the journal
  records the operation so recovery never validates an undo with apply's checks.
  Undo refuses while a row outside the batch still has a `matched_entry` equal
  to a proposal ID it would remove (a transfer's second side); that row is
  undone or rejected first. Undoing a matched row releases its claim
  (`matched_entry` moves to the audit-only `released_entry`).
- **A refusal writes nothing.** The batch gate, the version gate and an
  unwritable ledger leave every ledger file byte-identical. Proposals stay
  pending. Exit with the documented code and the reason; the driver notifies.
  The version gate is checked at `propose` and again at `decide` and `apply`
  before any decision is recorded, so a review generated before a rule or
  model change is never booked. The review file's header names a review
  recorded in staging with the version tuple and every row's revision; a file
  whose review is unknown or stale, or that lists a re-proposed row, is
  refused (exit 3).
- **Autobook does not second-guess a well-formed statement.** It cannot know
  how an OFX file was produced. It checks the file for consistency and its own
  work for correctness, and it never "repairs" a statement.

## Classification rules (MUST)

- **One precedence table governs everywhere.** It is stated in full in proposal
  0002 §5.1 (document conditions); every other document points to it:
  1. creditor-ID (SEPA Gläubiger-ID) rule;
  2. document-keyed rule — only with a **confirmed correspondent association**,
     `auto: true`, and passed shadow mode;
  3. ambiguity flag (`AMAZON`, `PAYPAL` …) — forces `?`;
  4. memo-pattern rule;
  5. kNN (k-nearest-neighbours, both gates);
  6. LLM (large language model, the tail).

  A rule's `priority` orders rules **within** a tier only, never across tiers.
  The rule builder reports conflicts between any two tiers on historical rows.
  `auto` is a field on every rule: default `true`, except document-keyed rules,
  which default to `false`.
- **An ambiguity flag forces `?`.** A flagged merchant is never pre-marked by a
  memo pattern, kNN or the LLM; only a creditor-ID rule or a qualifying
  document-keyed rule, both above the flag, may decide it.
- **Splits are rules-tier only.** kNN and the LLM may only ever return a *single*
  destination account. The corpus stays two-posting-only, and a model guessing at
  split ratios inside a ledger is precisely the confident wrongness the
  abstention design exists to prevent.
- **Abstention is a feature, not a failure.** Both gates — nearest-neighbour
  distance and vote margin — must pass before a kNN prediction is accepted.
  Failing either falls through; it does not lower a threshold. A unanimous vote
  among distant neighbours is a sparse region of the space, not confidence.
- **Never widen a threshold to fix a specific miss.** Thresholds move on
  backtest evidence across the corpus, not on one annoying transaction.
- **The LLM's label space is constrained.** Pass the account list, validate
  output against it, reject anything not in the live tree. Never put the account
  list in the steering document — generate it from the live chart of accounts
  (CoA) at runtime or it drifts silently out of sync with the ledger. The check
  also rejects accounts not open on the row's date, accounts whose `open`
  directive does not allow the row's currency, and accounts under the Equity
  root.
  Temperature is pinned to 0, and the model ID is part of the version tuple.
- **LLM rows are never pre-marked.** An LLM-tier proposal is always `?` until
  shadow mode has measured per-method precision for `method=llm`; only then may
  a threshold pre-mark LLM rows.
- **Provenance tagging is structural.** Every corpus row is `observed` or
  `corrected`: the ledger reader yields only `observed` rows, and `corrected` rows
  come from staging. Synthetic rows must not be able to enter the index.
- **Normalisation lives in the pipeline**, never in an ofxstatement plugin or
  the driver. They convert formats and hand over the raw memo unmodified. Normalisation is the thing
  that gets tuned most; it must be changeable and re-backtestable in one place.
- **The normaliser version is part of the gate tuple.** Changing it changes what
  every vector means.

## Privacy rules (MUST)

- **Redaction happens at the model-adapter boundary** — normalised merchant
  token, amount, sign; not the raw memo, and never document content. Built in at
  the boundary so no backend can see the unredacted string. Show the user
  exactly what leaves the machine.
- **The default model backend is local** (Ollama, llama.cpp …). A remote backend
  is opt-in, and then receives only:
  - a merchant token that matches a rule-pack entry or the user's allowlist of
    business names — any other token makes the LLM abstain and the row queue;
  - the account list as **numeric indices**, mapped back locally — never the
    account names (a name like `Kirchensteuer` is itself Art. 9 data);
  - the amount and sign.

  Novel counterparties are disproportionately doctors and lawyers; that is why
  an unknown token never goes remote.
- **Credentials go in the Secret Service via libsecret**, never in the config
  file, never in the repository.
- **Never collect or commit transactions.** Normalised memos routinely still
  carry counterparty names, IBANs, creditor IDs, employer names, and Art. 9
  special-category data (medical providers, church tax, union dues, party
  donations, lawyers, debt collection). Shared artifacts carry *patterns and
  categories only*. Merchant tokens (`REWE`, `Shell`) are business names; that is
  the line.
- **Counterparty IBANs are local-only** and never enter a shared pack. Creditor
  IDs are registered business identifiers and may.
- **User rules are personal data.** They live in a separate file from anything
  shippable; export is an explicit reviewed action.

## Documents (MUST)

Proposal 0002 reads bills from paperless-ngx. A document is evidence, never the
reference. Statements are not read from paperless by Autobook: the driver
hands over OFX files.

- **Statement lines and amounts come from the OFX file only** — never from OCR
  (optical character recognition) text, a document's archive version, or any
  metadata field.
- **A link changes nothing else.** A document link changes no amount, date or
  account, and creates no posting.
- **A link is written on created entries only**, as `autobook-doc` metadata.
  On a matched entry nothing is written; the link is recorded in staging.
- **The paperless stamp is never read back** to decide anything. "Already
  linked" is known from staging. The stamp, where enabled, holds the proposal
  ID.
- **Document content and correspondent names never reach staging, logs or a
  model backend.** Only IDs, checksums, amounts and dates.
- **Temporary files are private and short-lived.** Anything Autobook downloads
  lives under `$XDG_RUNTIME_DIR/autobook/`, mode `0600`, removed in a
  `finally`. `autobook review-file` writes to standard output; where the review
  file lives is the driver's decision, and it holds counterparty names.

## Review interface rules (MUST)

- **Approval is the saved review file.** The pipeline writes the review file
  with rows that passed the gates pre-marked `a` and every other row `?`.
  Saving the file is the user's approval of every row marked `a` in it. Nothing
  reaches the ledger that was not marked `a` in the review file being applied
  (an approval an earlier `decide` stored is not enough: `apply --from FILE`
  books exactly the rows marked `a` in FILE), with
  exactly the account, amount, currency and date shown there. Every row shows
  its currency, and a split row shows every posting it will book, with the sign
  it gets in the ledger, each on a line carrying the row's ID and a posting
  number, the source posting included. Destination accounts may be
  changed and are checked against the live chart of accounts; amounts and the
  source account may not.
- **Parse by ID, never by position.** Reordering, deleting, or sorting the review
  file must not misalign rows. An unknown ID is an error, not a guess; so is
  an ID that appears twice.
- **Strict parser, fail loudly.** Unknown status char, unparseable account, or
  date, amount or currency mismatch aborts the whole batch with a line number and applies nothing.
  Validate accounts against the live CoA at parse time so a typo stops the run
  instead of reaching the writer.

## Workflows

- Pin every action to a full commit hash with its release as a comment
  (`uses: actions/checkout@<40-char sha> # v7.0.1`), never to a tag or branch. Pick a
  release at least 7 days old; Dependabot keeps pins current.
- Give every `actions/checkout` `persist-credentials: false`, and each job only the
  `permissions:` it needs.
- A job that branch protection requires is listed in `.github/required-checks.txt`. When
  you rename, add or drop one, change the file in the same PR and tell the maintainer to
  re-apply the settings after the merge; it needs admin rights.
- Scorecard reports unpinned actions and broad token permissions in the Security tab.

## Design documents — pick the right class, change it the right way

`docs/design/README.md` is the map. The design is proposal 0005, with
proposals 0002 and 0004 applying as it lists, described in
`docs/design/architecture/`. Proposals 0001 and 0003 describe the earlier
GnuCash design and are replaced by 0005.

- **ADR** (`docs/design/adr/`) — a settled decision plus its rationale.
- **Proposal** (`docs/design/proposals/`) — an implementation plan or milestone
  scope; `draft/` → `accepted/`.
- **Architecture** (`docs/design/architecture/`) — living description of the
  current system; update it whenever the system changes.

**Changing a ratified doc = supersede, never rewrite.** Once an ADR is Accepted
or a proposal accepted, its file is frozen. Write a *new* doc carrying
`supersedes: <old>`, leave the old file untouched, and record the supersession in
the index/README.

**Docs currency** is a merge requirement, not a follow-up: a change that adds or
alters a CLI flag, a config key, a JSON contract field, a staging-table column,
a disposition, an exit code, or the format of a written entry updates the
living architecture doc in the same PR.

## Review rubric & protocol

Authors self-review against this before requesting review; reviewers judge
against it. The repo's written conventions are the arbiter, not reviewer taste.
When a defect class recurs, it graduates to a gate and drops out of review scope.

### Recurring defect classes (MUST check when the diff touches the surface)

- *Money*: any float in a monetary path; a float reaching `Decimal`; a
  rules-file amount written as `value: 12.50` instead of integer `cents:`;
  rounding that does not preserve the exact-sum property; a posting written
  without an explicit amount; the sum left to Beancount's tolerant check; a
  currency assumed rather than read from the statement and checked against the
  accounts' `open` directives.
- *Ledger writes*: a row written that was not marked `a` in the saved review
  file; a write to any file but the owned file; any directive but a
  transaction; a write to an entry Autobook did not create; the owned file
  regenerated instead of appended to; a replace without the compare, or one
  that is a plain rename instead of a checked exchange; a row reported applied without a
  read-back and the assertions; a failed read-back or assertion that leaves
  the batch in the ledger; a refusal that changes a ledger file.
- *Admission*: a statement partly admitted; a line staged from a rejected
  statement; a rejection without a recorded reason; a statement "repaired"
  instead of rejected; the same file admitted twice; a rejected file refused on its checksum
  without being checked again.
- *Idempotency*: a path that can create an entry twice after a crash between
  "file replaced" and "marked applied"; an interrupted batch marked applied
  because its IDs are in the ledger, without the journal's read-back and
  assertions, or validated against the restarted load instead of the journal's
  baseline; a rename not ordered after a durable journal; an `autobook-id` written to a matched
  entry; a value that does not match the proposal-ID pattern treated as
  Autobook's; a missing entry silently re-created; an `apply` or `undo` that
  runs without the writer lock; an undo that removes
  without checking both the staged `create` row and the owned file.
- *Double-booking*: a transfer booked from both statements, or a second side
  classified instead of matched or queued as "pending transfer"; a PayPal row
  classified as an expense rather than matched to its funding transaction (in
  `account` mode); a `match_existing` search on the target account, or one
  that picks between several candidates; a match on the amount without the
  currency, or one not re-checked against the date window at apply; a claim that is not per source account
  (the second side of a transfer unable to match, or one posting matched
  twice); a matched entry identified by file
  and line.
- *Boundary*: `beancount` imported outside the ledger package; `ofxstatement`
  or `gnucash` imported anywhere but the conversion's export half; ledger text
  parsed outside the ledger package; Autobook starting an editor, the
  converter or any other program.
- *Documents*: a statement line or amount taken from anything but the OFX
  file; a document link that changes an amount, date or account or creates a
  posting; a link written to a matched entry; a decision read from the
  paperless stamp; document content or a correspondent name in staging, a log
  or a model request; a downloaded file outside `$XDG_RUNTIME_DIR`, readable by
  others, or left behind after a failure; a document-keyed rule acting without
  a confirmed correspondent association.
- *Out-of-scope rows*: silently queued instead of dispositioned `out_of_scope`,
  or counted in coverage and drift metrics — either one degrades the drift
  detector until it stops catching real drift.
- *Abstention erosion*: a change that makes a novel merchant look familiar; a
  threshold widened without backtest evidence; a synthetic row reaching the
  index; an LLM row pre-marked before shadow mode has measured `method=llm`; an
  ambiguity-flagged row pre-marked by a tier below the flag; a rule `priority`
  that reorders tiers.
- *Failure granularity*: a per-row problem that halts the batch; a
  statement-level problem that stages some lines; a batch-level problem
  (coverage drop, LLM-fallback spike) that still writes.
- *Privacy*: a raw memo crossing the adapter boundary; a remote backend
  receiving a token outside the rule packs and allowlist, or an account name; a
  counterparty IBAN in shareable data; a credential in config; a transaction in
  a test fixture drawn from a real statement or a real ledger.
- *Licence*: a new dependency under Apache-2.0, GPL-3.0 or another licence not
  compatible with GPLv2.

### Reviewer protocol

- **DCO**: the `dco` status check is the sole authority. Do not report
  `Signed-off-by` findings from your own commit inspection — the SHAs a review
  context exposes are often GitHub's synthesized merge-preview commits, and this
  finding class is reliably a false positive.
- **Deferrals are settled**: a finding answered with "Deferred — tracked in #N"
  (or an in-code `# deferred: #N` marker) is resolved for review purposes. Raise
  the tracking issue instead if the deferral itself seems wrong.
- **Out of scope**: a real finding outside the PR's stated scope gets a
  decline-with-issue-reference, not an in-PR fix.
- **Definition of done**: the gate green plus **one** deep, multi-pass review
  whose findings are each fixed or rejected with a recorded reason. Do not
  iterate review rounds chasing silence.

## Dependencies and licence

- Beancount is **GPL-2.0-only**. ADR-0005 relicenses Autobook as
  GPL-2.0-or-later so that it can import it; the ADR is Proposed, and `LICENSE`
  changes when it is accepted. Write new code as if it already were.
- **A library Autobook imports must be compatible with GPLv2**: MIT, BSD, ISC,
  LGPL, GPL-2.0-or-later. **Apache-2.0 is not, and neither is GPLv3.** That
  rules out `requests`, vendor SDKs under Apache-2.0, and `ofxstatement`.
- Tools that are run and not imported (nox, ruff, mypy, pytest) are unaffected.
- Check the licence before proposing a dependency, and say what it is in the
  pull request.


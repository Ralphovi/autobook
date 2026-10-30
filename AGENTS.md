# Agent instructions — Autobook

This repository is the source of truth for Autobook code, design docs, and CI.
Treat repo policy as part of the work: make changes in an isolated worktree,
sign off commits, link PRs to issues, and run the gate that matches the surface
you changed.

**This project writes to people's accounting books.** A silently wrong booking
is worse than a loud failure, and worse than no booking at all — it misreports
for years and may reach a tax filing. Every rule below that looks pedantic is
there because the failure it prevents is invisible.

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
- **Book-process tests (`nox -s applier`) and live-paperless tests (`nox -s live`)**
  — run inside the throwaway **test environment** (`testenv/`, Docker): GnuCash
  5.14 bindings, PostgreSQL and paperless-ngx 3.3.0 on an internal network with
  no outbound access. They are not part of `gate`; CI runs them in the
  `testenv` workflow. The session and the pytest marker keep the name `applier`,
  but they cover every book-process test, the exporter's included.
- **Unattended book-process runs only touch synthetic books (MUST).** CI and the
  PDCA driver may run book-process and paperless tests **only** in the test
  environment, against books the tests build and the documents `testenv/seed/`
  creates. A real book, or a restored copy of one, is opened only by a human,
  attended — and never mounted into the test environment.

If a tool the gate needs is not installed, the session warns and skips. Never
report a skipped step as having run.

### Where the tests run, and how each place gets the dependencies

The tests run in four places, and each installs Autobook's dependencies its own way. A
change that adds, removes or bumps a dependency in `pyproject.toml` must work in all four;
a plan or brief that adds one says how it reaches each (#53).

| Where | Runs | Gets `[project].dependencies` from |
|---|---|---|
| `nox -s gate` (CI job `gate`) | lint, types, the pipeline tests | `pip install -e .` in nox's venv |
| CI `test-matrix` (Python 3.11–3.14) | the pipeline tests | `pip install -e .` in nox's venv, per interpreter |
| the test environment (`testenv/`, CI workflow `testenv`) | book-process and paperless tests | the `book` image's venv, built from the tree's `pyproject.toml` (`testenv/book/Dockerfile`) |
| the PDCA instance (Ralphovi/autobook-pdca) | the bundle's tests, on the host | the instance `.venv`, synced from the worktree's `pyproject.toml` before each check |

pytest imports **every** test module before it filters by marker. So a test module that
imports a new dependency breaks the test environment's run even when it holds no book-process
test — the image must have the dependency too. Only `[project].dependencies` reach the image,
never the `dev` extra: test modules must not import a dev-only tool. `python3-gnucash` is a
system package and stays out of `pyproject.toml` (the boundary below).

## The pipeline/book-process boundary is load-bearing

The **book process** is the only process that links libgnucash. It has two
parts: the **exporter**, which only reads (`SESSION_READ_ONLY`; corpus, chart of
accounts, existing transactions and scheduled-transaction definitions) and
exists from build step 2, and the **applier**, which writes and exists from
build step 5. Everything else is the **pipeline**.

The split is not a style preference. It is what makes the pipeline testable
with no GnuCash installed, sidesteps the `dist-packages` venv problem, and keeps
a future Windows port a component swap rather than a redesign.

- **Nothing under the pipeline may import `gnucash`.** Not in a function body,
  not behind a `try`, not lazily. If you find yourself wanting to, the design is
  wrong — move the work across the JSON boundary. The ban is lifted only for the
  book process: for the exporter's modules from step 2, for the applier's from
  step 5, each through an explicit per-file exception.
- The contract between them is JSON. Widen it deliberately and document it;
  don't smuggle behaviour across by convention.

## Hard rules for anything touching a book (MUST)

Every one of these has a silent-corruption failure mode. Violating one does not
produce an error — it produces a wrong ledger.

- **Session mode.** `SESSION_NORMAL_OPEN` for writes, `SESSION_READ_ONLY` for
  dry-run and inspection. **Never `SESSION_BREAK_LOCK`** — that is how a book
  gets corrupted by writing under a live GUI session. Use `SessionOpenMode`, not
  the deprecated `ignore_lock` / `is_new` / `force_new` booleans; pre-5.x
  examples will show the old form. A locked book is reported as
  `ERR_BACKEND_LOCKED` (the real enum in `qofbackend.h`; there is no
  `QOF_BACKEND_LOCKED`): GnuCash is open, so write nothing. `SESSION_READ_ONLY`
  ignores the lock — an export of an XML book while the GUI is open reads the
  last *saved* state, not what is on screen.
- **Save, then read back.** After the last `CommitEdit` of a batch, call
  `session.save()`, then run the post-apply assertions, then `session.end()` in
  the `finally`. On an XML book nothing persists until `save()` (all or nothing
  per batch); on an SQL book each `CommitEdit` is already durable and `save()` is
  a harmless no-op. `session.end()` does not save. A row is reported applied —
  in `apply-out` and as `applied` in staging — only after a read-back confirms
  it: for XML, reopen `SESSION_READ_ONLY` and find its ID; for SQL, an engine
  query.
- **Always release the session.** `session.end()` in a `finally`, unconditional.
  A crashed book process that skips it leaves a stale lock.
- **One session per run**, not per transaction. Session open loads the book.
- **Money is exact.** Amounts are `GncNumeric` rationals built from **integer
  cents**. Never floats, in any code path, including tests and fixtures. The
  bindings hazard is the `GncNumeric(float)` constructor, which accepts a float
  without complaint; the Python bindings expose no `from_double`, so do not go
  looking for a safe one. Money in a rules file is `cents: 1250`, never
  `value: 12.50`.
- **The currency is read, never assumed.** Take the source account's commodity,
  check that both accounts of the transaction share it and that its fraction is
  100, and only then build `GncNumeric(cents, 100)`. No hard-coded `EUR`.
- **Every mutation is bracketed** by `BeginEdit` / `CommitEdit`.
- **Never set the reconciled flag from code.** Reconciliation is the independent
  human check on everything this tool does. Removing that check to make a number
  look right defeats the tool's only external audit.
- **Never create accounts.** A chart of accounts encodes how someone thinks
  about their money and may map to tax categories an accountant specified. An
  auto-created account carries type, parent, placeholder flag, and commodity — an
  expense account typed as an asset does not error, it misreports forever, and
  removing an account with transactions is unpleasant. Point at GnuCash's New
  Account Hierarchy assistant instead.
- **Never create scheduled transactions programmatically.** A wrong frequency or
  formula generates phantom transactions indefinitely; for loans it duplicates
  the amortisation schedule and creates a second source of truth. Guide, verify,
  don't create.
- **Never `create` on a scheduled-transaction occurrence.** GnuCash creates
  scheduled-transaction (SX) instances in its Since-Last-Run step when the GUI
  starts — *after* the launcher has applied. So the exporter exports SX
  definitions with `existing`, and a statement row in a source account whose
  amount and date (within the match window) fall on an SX occurrence is never
  `create`: it is `match_existing` if the instance exists, otherwise `queue`
  with the reason "awaiting scheduled transaction".
- **`match_existing` searches the row's source account**, not the target
  account (an SX transaction may have many splits), and its candidates are
  transactions not already claimed by Autobook. Do not filter on "unreconciled":
  a user who reconciles promptly would never match.
- **A transfer is booked once.** Every transfer row goes through a source-account
  `match_existing` search *before* classification. The second side of a transfer
  whose first side was booked in an earlier batch resolves to the transaction
  the first side created. An unmatched second side whose counterpart is in
  `transfers_pending` is queued as "pending transfer", never classified.
- **Splits must sum exactly.** A computed split specification that does not sum
  to the transaction total fails the row loudly. **Never dump the difference into
  Imbalance.**
- **Assertions go through the engine API, never SQL.** SQL assertions do not
  exist for XML-backend users. This applies to the idempotency check, the
  Imbalance assertion, balance checks, and lock inspection alike. Slower on large
  books; works everywhere.
- **The proposal ID.** `AB-` followed by a ULID, generated once per staged row and
  stored in staging. It is not the staging key (`(source_account,
  fitid_or_key)`). Only a value matching `^AB-[0-9A-HJKMNP-TV-Z]{26}$` counts as
  an Autobook ID; anything else in `num` belongs to the user.
- **`num` only on transactions Autobook creates.** A created transaction carries
  its proposal ID in `num`. On a `match_existing` row Autobook **never writes
  `num` and writes no FITID or `online_id` stamp**; staging records
  `applied_tx_guid`, and the only thing that may be written to a matched
  transaction is a document link, never overwriting one already there.
- **Idempotency on re-run.** Before each batch, find created rows by their `num`
  and matched rows by the GUID in staging, verified in the book; drop both. This
  is what makes the applier safely re-runnable after any failure.
- **Undo is narrow.** Undo deletes a transaction only if its GUID is in staging
  with disposition `create` **and** its `num` equals that row's proposal ID —
  assert both before deleting. Undo of a matched row removes only the document
  link Autobook added.
- **A refusal must never block opening GnuCash.** Notify loudly, then open the
  app anyway. Proposals stay pending. Books are not hostage to a classifier that
  lost confidence in itself. The launcher has no abort path before
  `exec gnucash`: no `set -e` exit, each step `|| notify`.

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
  destination account. The corpus stays two-split-only, and a model guessing at
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
  (CoA) at runtime or it drifts silently out of sync with the book. The check
  also rejects placeholder accounts and Equity and Trading account types.
  Temperature is pinned to 0, and the model ID is part of the version tuple.
- **LLM rows are never pre-marked.** An LLM-tier proposal is always `?` until
  shadow mode has measured per-method precision for `method=llm`; only then may
  a threshold pre-mark LLM rows.
- **Provenance tagging is structural.** Every corpus row is `observed` or
  `corrected`: the book export yields only `observed` rows, and `corrected` rows
  come from staging. Synthetic rows must not be able to enter the index.
- **Normalisation lives in the pipeline**, never in an ofxstatement plugin.
  Plugins convert formats and preserve the raw memo. Normalisation is the thing
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

Proposal 0002 reads statements and bills from paperless-ngx. A document is
evidence, never the reference.

- **Statement lines and amounts never come from extraction.** They come from the
  original file, parsed by the plugin — never from OCR (optical character recognition) text, the archive
  version, or any metadata field.
- **Admission is all or nothing per statement.** A statement that fails any
  admission step (checksum, parse, balance check, overlap rule) is rejected whole
  and its reason recorded; no line of it is staged.
- **A link changes nothing else.** A document link changes no amount, date or
  account, and creates no split.
- **Never overwrite an existing document link.** A human put it there.
- **The paperless stamp is never read back** to decide anything. "Already
  linked" is known from staging.
- **Document content and correspondent names never reach staging, logs or a
  model backend.** Only IDs, checksums, amounts and dates.
- **Temporary files are private and short-lived.** Downloaded originals and the
  review file live under `$XDG_RUNTIME_DIR` (the review file at
  `$XDG_RUNTIME_DIR/autobook/review.txt`), mode `0600`, removed in a `finally`.

## Review interface rules (MUST)

- **Approval is the saved review file.** The pipeline writes the review file
  with rows that passed the gates pre-marked `a` and every other row `?`.
  Saving the file is the user's approval of every row marked `a` in it. Nothing
  reaches the book that was not marked `a` in the saved review file, with
  exactly the account, amount and date shown there. Unattended runs with no
  editor are deferred beyond v1.
- **Parse by ID, never by position.** Reordering, deleting, or sorting the review
  file must not misalign rows. An unknown ID is an error, not a guess.
- **Strict parser, fail loudly.** Unknown status char, unparseable account, or
  amount mismatch aborts the whole batch with a line number and applies nothing.
  Validate accounts against the live CoA at parse time so a typo stops the run
  instead of creating an Imbalance row.

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

`docs/design/README.md` is the map. The design is proposal 0001 as amended by
proposal 0002, described in `docs/design/architecture/`.

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
or a disposition updates the living architecture doc in the same PR.

## Review rubric & protocol

Authors self-review against this before requesting review; reviewers judge
against it. The repo's written conventions are the arbiter, not reviewer taste.
When a defect class recurs, it graduates to a gate and drops out of review scope.

### Recurring defect classes (MUST check when the diff touches the surface)

- *Money*: any float in a monetary path; a float reaching the `GncNumeric(float)`
  constructor; a rules-file amount written as `value: 12.50` instead of integer
  `cents:`; rounding that does not preserve the exact-sum property; a currency
  assumed rather than read from the source account's commodity, or a commodity
  whose fraction is not checked to be 100.
- *Book writes*: a row written that was not marked `a` in the saved review file;
  a mutation outside `BeginEdit`/`CommitEdit`; a batch ended without
  `session.save()`; a row reported applied without a read-back; a session not
  ended in `finally`; a write path that could run while the GUI holds the lock
  (`ERR_BACKEND_LOCKED`); a launcher path that can exit before `exec gnucash`.
- *Idempotency*: a path that can create a transaction twice after a crash between
  "committed to book" and "marked applied"; `num` or a FITID/`online_id` stamp
  written to a matched transaction; a `num` that does not match the proposal-ID
  pattern treated as Autobook's; an undo that deletes without checking both the
  staging GUID with disposition `create` and the `num`.
- *Double-booking*: a transfer booked from both statements, or a second side
  classified instead of matched or queued as "pending transfer"; a PayPal row
  classified as an expense rather than matched to its funding transaction (in
  `account` mode); a `create` on a scheduled-transaction occurrence; a
  `match_existing` search on the target account, or filtered to unreconciled
  transactions.
- *Documents*: a statement line, amount or balance taken from OCR text, the
  archive version or metadata; a statement partly admitted; a document link that
  changes an amount, date or account, creates a split, or overwrites an existing
  link; a decision read from the paperless stamp; document content or a
  correspondent name in staging, a log or a model request; a downloaded original
  or review file outside `$XDG_RUNTIME_DIR`, readable by others, or left behind
  after a failure; a document-keyed rule acting without a confirmed
  correspondent association.
- *Out-of-scope rows*: silently queued instead of dispositioned `out_of_scope`,
  or counted in coverage and drift metrics — either one degrades the drift
  detector until it stops catching real drift.
- *Abstention erosion*: a change that makes a novel merchant look familiar; a
  threshold widened without backtest evidence; a synthetic row reaching the
  index; an LLM row pre-marked before shadow mode has measured `method=llm`; an
  ambiguity-flagged row pre-marked by a tier below the flag; a rule `priority`
  that reorders tiers.
- *Failure granularity*: a per-row problem that halts the batch, or a batch-level
  problem (coverage drop, LLM-fallback spike, parse errors) that still writes; a
  failed post-apply assertion that is not flagged and undoable.
- *Backend assumptions*: SQL used where an XML book must work; a file-copy backup
  assumed where the backend is a server; a `CommitEdit` assumed durable on an
  XML book.
- *Privacy*: a raw memo crossing the adapter boundary; a remote backend
  receiving a token outside the rule packs and allowlist, or an account name; a
  counterparty IBAN in shareable data; a credential in config; a transaction in
  a test fixture drawn from a real statement.

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

## Working with GnuCash upstream

- Enhancement requests go to Bugzilla (Severity=Enhancement,
  Version=git-future); new features target the `future` branch. A report with a
  well-written patch is far more likely to land — there is boilerplate rejection
  text for unpatched proposals.
- Since Sept 2025 Bugzilla requires login even to *view* bugs and automatic
  account creation is disabled. Mailing list archives remain indexed
  (`site:lists.gnucash.org`).
- Expect silence rather than rejection. Small, concrete, patch-attached.

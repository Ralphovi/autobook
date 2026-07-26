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
  lint. It is the same command CI runs and the same command the PDCA harness
  delegates to; never re-declare gates elsewhere.
- **Applier tests (`nox -s applier`)** — separate because it is the only session
  permitted to see the system `python3-gnucash`. It is not part of `gate` and
  does not run in CI (no GnuCash there); run it locally when you touch the
  applier, against a **restored copy of a book, never a real one**.

If a tool the gate needs is not installed, the session warns and skips. Never
report a skipped step as having run.

## The pipeline/applier boundary is load-bearing

The two-process split is not a style preference. It is what makes the pipeline
testable with no GnuCash installed, sidesteps the `dist-packages` venv problem,
and keeps a future Windows port a component swap rather than a redesign.

- **Nothing under the pipeline may import `gnucash`.** Not in a function body,
  not behind a `try`, not lazily. If you find yourself wanting to, the design is
  wrong — move the work across the JSON boundary.
- The contract between them is JSON. Widen it deliberately and document it;
  don't smuggle behaviour across by convention.

## Hard rules for anything touching a book (MUST)

Every one of these has a silent-corruption failure mode. Violating one does not
produce an error — it produces a wrong ledger.

- **Session mode.** `SESSION_NORMAL_OPEN` for writes, `SESSION_READ_ONLY` for
  dry-run and inspection. **Never `SESSION_BREAK_LOCK`** — that is how a book
  gets corrupted by writing under a live GUI session. Use `SessionOpenMode`, not
  the deprecated `ignore_lock` / `is_new` / `force_new` booleans; pre-5.x
  examples will show the old form.
- **Always release the session.** `session.end()` in a `finally`, unconditional.
  A crashed applier that skips it leaves a stale lock.
- **One session per run**, not per transaction. Session open loads the book.
- **Money is exact.** Amounts are `GncNumeric` rationals built from **integer
  cents**. Never floats. `GncNumeric.from_double` exists; do not use it for
  money, in any code path, including tests and fixtures.
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
- **Splits must sum exactly.** A computed split specification that does not sum
  to the transaction total fails the row loudly. **Never dump the difference into
  Imbalance.**
- **Assertions go through the engine API, never SQL.** SQL assertions do not
  exist for XML-backend users. This applies to the idempotency check, the
  Imbalance assertion, balance checks, and lock inspection alike. Slower on large
  books; works everywhere.
- **Idempotency is the `num` field.** The proposal ID goes in the transaction's
  `num`. Query existing IDs before each batch and drop those already present.
  This is what makes the applier safely re-runnable after any failure, and what
  makes a batch reversible.
- **A refusal must never block opening GnuCash.** Notify loudly, then open the
  app anyway. Proposals stay pending. Books are not hostage to a classifier that
  lost confidence in itself.

## Classification rules (MUST)

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
  list in the steering document — generate it from the live CoA at runtime or it
  drifts silently out of sync with the book.
- **Provenance tagging is structural.** Every corpus row is `observed` or
  `corrected`. Synthetic rows must not be able to enter the index.
- **Normalisation lives in the pipeline**, never in an ofxstatement plugin.
  Plugins convert formats and preserve the raw memo. Normalisation is the thing
  that gets tuned most; it must be changeable and re-backtestable in one place.
- **The normaliser version is part of the gate tuple.** Changing it changes what
  every vector means.

## Privacy rules (MUST)

- **Redaction happens at the model-adapter boundary** — normalised merchant
  token, amount, sign; not the raw memo. Built in at the boundary so no backend
  can see the unredacted string. Show the user exactly what leaves the machine.
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

## Review interface rules (MUST)

- **Parse by ID, never by position.** Reordering, deleting, or sorting the review
  file must not misalign rows. An unknown ID is an error, not a guess.
- **Strict parser, fail loudly.** Unknown status char, unparseable account, or
  amount mismatch aborts the whole batch with a line number and applies nothing.
  Validate accounts against the live CoA at parse time so a typo stops the run
  instead of creating an Imbalance row.

## Design documents — pick the right class, change it the right way

`docs/design/README.md` is the map.

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

- *Money*: any float in a monetary path; any `from_double`; rounding that does
  not preserve the exact-sum property; a currency assumed rather than read.
- *Book writes*: a mutation outside `BeginEdit`/`CommitEdit`; a session not ended
  in `finally`; a write path that could run while the GUI holds the lock.
- *Idempotency*: a path that can create a transaction twice after a crash between
  "committed to book" and "marked applied"; a batch that is not reversible by
  `num`.
- *Double-booking*: a transfer booked from both statements; a PayPal row
  classified as an expense rather than matched to its funding transaction; an
  applier that only ever creates and so re-books what a scheduled transaction
  already entered.
- *Out-of-scope rows*: silently queued instead of dispositioned `out_of_scope`,
  or counted in coverage and drift metrics — either one degrades the drift
  detector until it stops catching real drift.
- *Abstention erosion*: a change that makes a novel merchant look familiar; a
  threshold widened without backtest evidence; a synthetic row reaching the
  index.
- *Failure granularity*: a per-row problem that halts the batch, or a batch-level
  problem (coverage drop, LLM-fallback spike, parse errors, failed post-apply
  assertions) that still writes.
- *Backend assumptions*: SQL used where an XML book must work; a file-copy backup
  assumed where the backend is a server.
- *Privacy*: a raw memo crossing the adapter boundary; a counterparty IBAN in
  shareable data; a credential in config; a transaction in a test fixture drawn
  from a real statement.

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

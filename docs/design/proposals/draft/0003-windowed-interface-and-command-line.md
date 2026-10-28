---
created: 25.10.2026 02:30
type: proposal
status: draft
author: Eduard Ralph
tracking-issue: 73
tags:
  - proposal
  - review
  - launcher
  - gui
  - cli
  - design
---

# Proposal: Windowed interface, user journey and command line

> **What this settles.** How a person moves through Autobook, from starting it
> to handing the book back to GnuCash, and the two surfaces that journey runs
> on: a **command line** that is the primary interface, and a set of **GTK4
> windows** that are a client of that command line. It names the commands (§2),
> their output and exit-code contract (§2.3), the journey (§3), the windows (§4),
> how a window drives the commands (§5) and the visual rules the windows follow
> (§6).
>
> **What this does not change.** Nothing about what reaches a book. The review
> file stays the approval: **every row marked `a` in the saved review file is
> approved, exactly as shown, and nothing else is** (proposal 0001, *Review
> interface*). The window does not get its own approval path; it writes the same
> file and calls the same command. The parser stays strict and by ID. The book
> process still never runs while GnuCash holds the book. No change to the
> classification cascade, its gates, the staging schema, the dispositions, the
> write path or what leaves the machine.
>
> **Relation to proposals 0001 and 0002.** Both are still `draft`. This proposal
> amends 0001 in the rows of *Changes to proposal 0001* below and otherwise adds
> to it. It does not touch 0002. It reopens one point 0001 decided in passing —
> that a custom review UI is not worth building — and says why under
> *Alternatives considered*.

## In plain language

Today the plan has one place where a person decides anything: a text file that
opens in their editor, one line per bank transaction, with a letter in front.
For someone who lives in vim that is the fastest interface there is, and it
stays exactly as it is.

But Autobook is meant to be usable by people other than its author, and most
GnuCash users do not edit a `git rebase -i` file for their bookkeeping. So this
proposal adds windows that look and behave like GnuCash — the green register,
the same words, the same keys — for the same three moments: starting a run,
deciding the rows Autobook was unsure about, and watching the batch get booked.

The windows are not a second program. Every button runs a command you could
type yourself, and the window shows you which one. The Review window edits the
same review file the editor would; pressing *Approve and Book* is the same as
saving that file and running `autobook apply`. Anything a window can do, a
script can do, and anything a script does, a window can show.

## Motivation

Three needs, in order of weight:

1. **Distribution (build step 9).** Section 9 of the architecture names step 9
   "distributable to other users". A tool whose only interactive surface is a
   text file in `$EDITOR` is distributable to people who already work that way.
   The residual — the rows marked `?` — is decided by a human every run; that
   human should not need editor fluency to do it well.
2. **Evidence at the point of decision.** The review file shows a hint line per
   row (kNN votes, a weak bill). 0001 already names the trigger for a richer
   interface: "repeatedly wanting full memo / merchant history / running balance
   before deciding". A window can show the raw and normalised memo, the vote
   shares, the linked bill and *why a row is not pre-marked* without making the
   file longer.
3. **One journey, scriptable.** The launcher today is a shell script around
   unnamed subcommands (`autobook export`, `propose`, `pending`, `review-file`,
   `apply --from`). Naming the full verb set and its contract once, with machine
   output and exit codes, is what makes both the windows and unattended use
   later possible without a second implementation.

Nothing here changes what gets written to a book.

## Design

### 1. Principles

1. **Command line first.** Every step of the journey is an `autobook`
   subcommand. A window adds no capability the command line lacks.
2. **The window is a client.** It runs the subcommands as subprocesses and reads
   their `--json` output. It imports neither `gnucash` nor the pipeline's
   modules (§5).
3. **Saving is approving, in both surfaces.** The window's state *is* a review
   file. *Approve and Book* writes it and calls `autobook apply --from` on it.
4. **Never with GnuCash.** The book process and GnuCash never hold the book at
   the same time. Every window that can lead to a write ends in *Open GnuCash*,
   which is the launcher's `exec gnucash`.
5. **GnuCash's words and looks.** Book, Account, Transaction, Split, Register,
   Scheduled Transaction; colon account paths; the register's colours; the
   book's locale for numbers and dates (§6).
6. **Say it, don't colour it.** A status is a letter *and* a word; a negative
   amount carries a minus sign *and* the negative colour.

### 2. The command line

#### 2.1 Verbs

| Command | Does | Book access | Window equivalent | In 0001 |
|---|---|---|---|---|
| `autobook run` | The whole journey: the launcher (architecture 5.4), ending in `exec gnucash` | via the steps below | — | launcher |
| `autobook gui` | The same journey with windows instead of `$EDITOR` | via the steps below | the Start window | new |
| `autobook backup` | Back up the book (file copy, or `pg_dump` for PostgreSQL) | read | Start › Back Up Book | launcher step 1 |
| `autobook export [--corpus]` | The exporter: corpus, CoA, existing, SX definitions | read-only session | Start › Export Book | yes |
| `autobook propose` | Admit statements, correlate, link bills, classify, dispose, batch gate | none | Start › Propose Bookings | yes |
| `autobook pending` | Count and list pending proposals; exit 1 when there are none | none | Start › *Review N Rows* | yes |
| `autobook review-file` | Write the review file to stdout | none | Review › Open in Editor… | yes |
| `autobook decide --from FILE` | Parse a saved review file and record its decisions to staging; write nothing to the book | none | Review › Save Decisions | new (0001: "saving records the decisions to staging" before step 5) |
| `autobook apply --from FILE` | `decide`, then the book process: apply, save, assertions, read-back | one write session | Review › Approve and Book | yes |
| `autobook undo BATCH` | Undo a batch (architecture 6.7) | one write session | Booking › Undo This Batch… | new name |
| `autobook status` | The last run, pending counts, the version tuple in force | none | Start window | new |
| `autobook trial backtest …` | The rolling-origin backtest (architecture 6.6) | none | Trial › Backtest | yes (`python -m autobook.pipeline.trial backtest`) |
| `autobook trial accept` | Record this trial's version tuple for production | none | leaving Trial | new name |
| `autobook rules cluster` | Cluster queued and low-confidence rows | none | Trial › Rule Builder | new name |
| `autobook rules test RULE` | Backtest one candidate rule; print the verdict | none | Rule Builder › verdict | new name |
| `autobook rules accept RULE` | Add a scored rule to the rules file | none | Rule Builder › Accept Rule | new name |
| `autobook assistants` | List rows better handled by a GnuCash assistant | none | Trial › Assistants | new name |

"New name" means the capability is in 0001 or the architecture and only the
verb is new. `autobook trial backtest` keeps the arguments, the no-defaults rule
for `--max-distance` and `--min-margin`, and the error contract of section 6.6;
the `python -m` form stays as an alias.

#### 2.2 What each command prints

- **stdout carries data, stderr carries messages.** With `--json`, stdout is a
  single JSON document — a versioned contract like those of section 5.1 — and
  nothing else. Without it, stdout is fixed-column text in the review file's
  style.
- **No prompts without a TTY.** A command that would ask (`undo`'s
  confirmation) refuses with exit 2 when stdin is not a terminal unless `--yes`
  is given. `apply` never asks: its approval is the file it is given, so a
  script cannot approve anything by accident.
- **Messages follow section 6.6's rule.** An error names the kind of error and
  at most the field, row ID or line number; it never quotes a refused value — no
  amount, memo, counterparty or path the user chose.

#### 2.3 Exit codes

| Code | Meaning | Written to the book |
|---|---|---|
| 0 | Done | as the command says |
| 1 | Nothing to do (`pending` with no rows) | nothing |
| 2 | Usage or input error (section 6.6's exit 2, generalised) | nothing |
| 3 | The batch gate refused (architecture 6.8) | nothing |
| 4 | The book is locked: `ERR_BACKEND_LOCKED` | nothing |
| 5 | The review file did not parse; the line number is on stderr | nothing |
| 6 | An assertion or the read-back failed | see architecture 6.5 for what persists per backend |

Codes 3–6 are what the launcher's `|| notify` branches distinguish, and what the
windows map to dialogs.

### 3. The journey

A booking run, scenario 2, in six stages. The lanes are what a person does,
which window shows it, which command runs, and who holds the book.

| Stage | Person | Window | Command | Book access |
|---|---|---|---|---|
| 1 Start | Opens Autobook instead of GnuCash | Start | `run` / `gui` | none |
| 2 Prepare | Waits seconds; sees which statements were admitted and why one was rejected | Start (checklist) | `backup`, `export` | read-only, after the backup |
| 3 Propose | Sees how many rows are pre-marked and whether the gate passed | Start (summary) or the refusal dialog | `propose`, `pending` | none |
| 4 Review | Decides only the residual: accept, retype the account, skip, reject | Review, or `$EDITOR` | `review-file`, `decide` | none |
| 5 Book | Presses *Approve and Book* once; watches write, assertions, read-back | Booking | `apply --from` | one write session; GnuCash not running |
| 6 Hand over | Carries on in GnuCash, or undoes the batch | Booking | `exec gnucash`, `undo` | GnuCash |

Three exits leave the happy path, each writing nothing:

- **Refused** at stage 3 (exit 3): the dialog names the reason, offers *Run
  Trial…* and *Open GnuCash*; proposals stay pending.
- **Does not parse** at stage 4 (exit 5): the window marks the row, the editor
  gets a line number; nothing is applied until it parses.
- **Locked** at stage 5 (exit 4): decisions are kept, so the next run starts at
  Review.

The trial journey, scenario 1, is read-only end to end and may run with GnuCash
open: export the corpus → backtest (the person sets the thresholds) → cluster the
residual → score a candidate rule → accept it, or hand the cluster to a GnuCash
assistant → record the version tuple (`trial accept`). It is entered from the
Start window (*Run Trial…*) or the refusal dialog. Leaving it with a changed rule
set makes the next booking run require this trial: the version gate of
architecture 8.3.

### 4. The windows

GTK4, GNOME header bars. Every header bar has a **Show Command** button that
prints the exact command line the window ran or will run. Window titles and
buttons are Title Case; an ellipsis means a dialog follows.

#### 4.1 Start

The book (name, backend), then **This Run** as a checklist — *Back Up Book*,
*Export Book (read-only)*, *Admit Statements — n of m*, *Propose Bookings*,
*Batch Gate* — each with its command beside it and a state that is a word and an
icon, not a colour alone. Beside it, **Statements** lists each statement with
*Admitted* or *Rejected* and the reason in plain words ("Lines sum to −312,40 €;
closing minus opening is −312,41 €. Re-export the statement and run again.").
A summary bar shows the rows proposed, split into pre-marked `a`, `?` and out of
scope. Actions: *Run Trial…*, *Open GnuCash*, and the suggested action *Review
N Rows*.

#### 4.2 Review

The heart of the windows and the only one that edits anything. It is a
register-styled list of the batch's in-scope rows with the columns of the review
file — Status, Date, Amount, Transfer, Description — plus a short **Basis**
(Rule, kNN with its confidence, LLM, Transfer, Scheduled, Doc rule, None).

- **Status** is a chip with the letter and its word: `a` Accept, `?` Decide,
  `s` Skip, `x` Reject. Out-of-scope rows are listed, greyed, with no status;
  they are not in the review file.
- A **sidebar** filters by view (All, Needs Decision, Marked Accept, Skipped or
  Rejected, Out of Scope) and by source account, with counts.
- An **evidence panel** for the selected row: proposal ID and disposition; raw
  memo, date, amount, source account; the status buttons; the Transfer account
  picker (accounts from the live CoA only, full colon path); **Why this isn't
  pre-marked** in a sentence (ambiguity flag, LLM not yet measured,
  document-keyed rule with `auto: false`, kNN abstained, queue reason); the kNN
  votes as shares; the bill in paperless and its match quality; and **the same
  row as a line of `review.txt`**.
- An **approve bar**: "*n* rows marked Accept will be booked exactly as shown",
  what happens to the rest, and *Save Decisions* and the suggested action
  *Approve and Book n Rows*.
- *Open in Editor…* opens the same file in `$EDITOR` (§5.3).

Keyboard, after the register: `a`, `?`, `s`, `x` set the status of the selected
row; Enter moves to the next row; Tab moves to the Transfer account and accepts
completion; Esc cancels an edit. These are listed in the sidebar and in the
row's tooltip.

#### 4.3 Booking

Shown while and after `apply` runs. A banner states the outcome ("7 rows booked
and confirmed by read-back", or the failure). **Steps**: parse review strictly by
ID, open write session, skip rows already in the book, create transactions with
the proposal ID in Num, save book, read back *n of n*. **Assertions** (section
5.3): each source account's change equals the rows applied; closing balance
minus unapplied lines; Imbalance unchanged — each *Passed* or *Failed* in words.
**Applied rows** in register style with Num, Date, Amount, Transfer, Result
(created, matched existing, bill linked). Actions: *Undo This Batch…*
(destructive, confirms with the consequence: "Delete the 6 transactions this
batch created and remove 1 document link?") and the suggested action *Open
GnuCash*.

#### 4.4 Refusal

An alert dialog over the Start window. Title: "Nothing was booked". Body: the
gate's specific reason (architecture 6.8, e.g. "Coverage fell from 92% to 61%")
and that proposals stay pending. A list of every gate check, *Passed* or
*Failed*. The command and its exit code. Actions: *Copy Details*, *Run Trial…*,
and the suggested action *Open GnuCash* — a refusal never keeps the book
hostage.

#### 4.5 Trial

A read-only banner ("Nothing here changes your book; GnuCash may stay open")
and the thresholds in force. Three tabs:

- **Backtest** — the report of section 6.6 rendered: per method, per band, seen
  versus novel, the novel-stratum sweep. Threshold fields start empty: the tool
  never proposes a default.
- **Rule Builder** — 0001's core panel. Clusters of the residual on the left
  (an ambiguity-flagged cluster is shown and marked "cannot become a rule"). The
  proposed rule: pattern, Transfer account, scope, `auto`, and who drafted it
  (kNN cluster or LLM). The **verdict**, immediately: "Matches 47 historical
  transactions — 45 booked to Expenses:Lebensmittel, 2 to Expenses:Haushalt",
  the disagreeing rows listed with *Show in Register*, conflicts with existing
  rules, and that accepting changes the version tuple. *Reject*, *Edit Pattern*
  (the verdict re-runs), *Accept Rule*.
- **Assistants** — rows better handled by GnuCash (recurring fixed debits,
  loan-shaped payments, a thin CoA), each with the pre-computed values to copy
  into the assistant. Autobook never creates the scheduled transaction or the
  account itself.

### 5. How a window drives the command line

#### 5.1 Process shape

The windows run in a fourth process kind, **client**, beside pipeline, book
process and launcher. It:

- runs `autobook <verb> --json` as subprocesses and renders their output;
- imports only `autobook.contracts` (standard library) to read that output;
- never imports `gnucash`, and never imports the pipeline's modules, so the
  window cannot do anything the commands do not, and the gate's ban on
  importing `gnucash` needs no new exception.

`autobook gui` is the launcher with the window as its review step: it runs the
same sequence as section 5.4 and must reach `exec gnucash` on every path, just
like the shell launcher.

#### 5.2 The review file is the window's state

- The Review window loads by running `autobook review-file` and holds **that
  text** as its state. Each edit rewrites the affected line (status character,
  account); the row list is rendered from a parse of the current text, not from
  a separate model, so what the window shows as `a` is what the file says.
- *Save Decisions* writes the text to the review file and runs `autobook decide
  --from`. *Approve and Book* writes it and runs `autobook apply --from`. There is
  no other path from the window to staging or the book.
- The file lives where 0001 puts it: `$XDG_RUNTIME_DIR/autobook/review.txt`,
  mode `0600`, removed when the run ends however it ends.
- Exit 5 from either command is mapped to its line, and the window selects that
  row and shows the message. Nothing was recorded or written.

#### 5.3 Open in Editor…

The window writes the file, spawns `$EDITOR` on it and waits. On return it
re-reads the file and re-parses it with `autobook decide --from FILE --check
--json` (parse only, record nothing). If the file no longer parses, the window
shows the line and offers to reopen the editor. The window does not accept
edits while the editor is open, so the two never race.

### 6. Visual rules

The windows follow GnuCash's own GTK theme and register colours
(`gnucash/gnucash.css`, `gnucash-fallback.css`): register header, alternating
primary and secondary rows, the split colour, the cursor colour for the row
being edited, black register text. Where they depart from GnuCash they do so to
be clearer, not to look different:

- Status chips reuse the import matcher's three colours — *no intervention
  needed*, *probably required*, *required* — for Accept, Decide and Reject, and an
  outlined chip for Skip; each always with its letter and word.
- Negative amounts carry a minus sign and the negative colour; amounts are
  right-aligned with tabular figures.
- Numbers, currency and dates follow the book's locale (`1.234,56 €`,
  `23.10.2026` in a German book); the decimal separator is never hard-coded.
- Keyboard focus is always visible: a 2 px ring on every focusable element,
  register cells included.
- Text meets 4.5:1 contrast on its ground; GnuCash's register negative on the
  primary row (4.47:1) is the one documented exception, kept as GnuCash has it.
- Data grids are square; dialogs and cards have small radii; elevation only for
  popovers and completion lists.
- No emoji, no exclamation marks. Confirmations state the consequence; errors
  name the fix.

### 7. Where it lands in the build order

The commands arrive with the steps that need them: `export` and `trial
backtest` with step 2, `propose`, `pending`, `review-file` and `decide` with step
6, `backup`, `apply`, `undo` and `run` with step 5, `rules …` and `assistants`
with step 9. `--json` and the exit codes of §2.3 apply to each command from the
step it lands in.

The windows land in **step 9**, Trial first (0001: "build this before anything
else in the UI"), then Review, Start, Booking and the refusal dialog. This keeps
section 9's reasoning: the rule builder is backtest machinery with a window
around it, and a Review window before the text review file has been used on
real statements would be a GUI over guesses.

### What this touches

- **Classification cascade and gates:** no.
- **Staging schema and dispositions:** no new columns. `pending --json` and the
  evidence panel read fields staging already has (`method`, `confidence`,
  `rule_id`, `queue_reason`, `doc_id`, `doc_match`, `doc_candidates`) plus the
  kNN vote shares the review file's hint line already prints. The `pending`
  document is a new versioned contract, pipeline → client.
- **Write path, idempotency, locking:** no. The window reaches the book only
  through `apply` and `undo`; the launcher's sequencing is unchanged.
- **What leaves the machine:** nothing. The window shows what the review file
  already contains and keeps none of it after the run (§ Risks).

### Changes to proposal 0001

| 0001 says | This proposal |
|---|---|
| *Review interface*: "Why this over a custom UI … it would be built worse"; escalate to a TUI only if the file lacks information | The text file stays the reference interface and the parse contract. A GTK4 Review window is added as a second client of the same file, for distribution, at step 9. The TUI is not needed. |
| *Launcher*: a shell script with `autobook export`, `propose`, `pending`, `review-file`, `apply --from` | The same sequence, available as `autobook run`; `autobook gui` runs it with the Review window in place of `$EDITOR`. Verbs, `--json` and exit codes as §2. |
| *Scenario 1*: GTK4 rule builder | Unchanged in substance; placed in the Trial window with Backtest and Assistants tabs (§4.5). |

## Alternatives considered

| Option | Why not |
|---|---|
| **Keep `$EDITOR` only** | Right for the author and for anyone with editor fluency, and it stays. It fails step 9's goal: most GnuCash users would have to learn a `git rebase -i` idiom to book. |
| **Textual TUI** (0001's escalation path) | Solves the information-density trigger but not distribution: it is still a terminal program. It would also be a third rendering of the same rows to keep in parity. |
| **Window with its own approval model** (check boxes, an in-memory "approved" set) | Two approval paths, two parsers, and the one guarantee that matters — only what was saved as `a` is booked — would rest on keeping them in sync. Rejected: the window edits the file. |
| **Window importing the pipeline in-process** | Faster to build, but capabilities would leak into the window that the command line lacks, and the GTK dependency would sit in the pipeline's import graph. Rejected in favour of subprocess + `--json`. |
| **Local web UI** | A server, a port and a browser for a desktop tool that already sits next to a GTK application; the GnuCash look is GTK. |
| **In-app GnuCash plugin** | Already rejected in 0001 (*Rejected alternatives*); nothing here changes that. |

## Graduation criteria

- **Parity, by test.** For every row and every status, setting it in the window
  produces byte-for-byte the review file line the text path would produce. A
  test enumerates the window's actions and fails if one has no command.
- **One approval path, by test.** The client package has no import of
  `gnucash` or `autobook.pipeline` (checked in the gate like the existing ban),
  and the only commands the client runs that reach a book are `apply` and
  `undo`.
- **Exit codes, by test.** Each of 0–6 is produced by a fixture and mapped to its
  window state.
- **The launcher invariant, by test.** `autobook gui` reaches `exec gnucash` on
  every exit code, as the shell launcher does.
- **Usability, measured once.** Someone who has not used a `git rebase -i` file
  books a synthetic batch from the Start window to *Open GnuCash* without help.
  Note what they got stuck on; fix those before calling step 9 done.
- **Accessibility.** Keyboard-only completion of the journey; every status and
  amount readable with colour removed.

## Risks

- **The window shows something other than what it books.** The silent failure
  this proposal must not introduce. Mitigation: the window's state is the review
  file text, the list is rendered from parsing it, and *Approve and Book* hands
  that file to the same strict parser (§5.2).
- **Editor and window both edit the file.** Prevented by blocking the window
  while `$EDITOR` is open and re-parsing on return (§5.3).
- **Counterparty names outlive the run.** The window must not cache row content:
  no saved window state with memos, no recent-files entry for `review.txt`, no
  clipboard writes except on *Copy Details*, which carries the gate's reasons and
  no transaction data.
- **Colour carrying meaning.** Prevented by §1.6 and §6, and tested under
  graduation.
- **Drift between the verbs here and the launcher.** The launcher becomes a thin
  sequence of the same verbs; a test runs both against the same fixtures.

## Backward compatibility

None to preserve: nothing is implemented. The review file format is unchanged.
`python -m autobook.pipeline.trial backtest` stays as an alias of `autobook trial
backtest`. The version gate tuple is unaffected: the window is not part of it.

## Open questions

- **PyGObject packaging.** GTK4 bindings come as a system package
  (`python3-gi`) on most distributions, like `python3-gnucash`; installing them
  into a virtualenv needs build dependencies. Whether the client runs on system
  Python or in the venv with a `gui` extra is **[OPEN]**, and the four places the
  tests run (AGENTS.md) must each say how they get it.
- **`autobook run` versus the shell launcher.** Whether `run` replaces the shell
  script or the script stays and calls the verbs. Either way the invariant is
  the same: always reach `exec gnucash`.
- **The batch identifier for `undo`.** Staging has no batch column; a batch is
  currently implied by the run. Naming it may need a staging change, which would
  then be in scope for the proposal that adds it.
- **Exit-code numbering** is a first cut; it is fixed when the first command
  that returns 3–6 lands.
- **macOS.** GTK4 on macOS is possible but unverified, like the GnuCash bindings
  there.

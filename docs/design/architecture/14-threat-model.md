---
created: 14.10.2026 23:50
type: architecture
status: living
tags:
  - architecture
  - security
  - threat-model
---
# 14. Threat model

> Living document, **v0**. Hardens as surfaces are built. The reporting process
> and scope are in [`SECURITY.md`](../../../SECURITY.md); this chapter is the model
> behind it. The design it models is
> [proposal 0005](../proposals/draft/0005-beancount-ledger.md).

Autobook's threat model is unusual for a small tool: most of the harm it can do
needs **no attacker**. A converter bug, a bank changing its memo format, a
careless rule pack, an overconfident model or an editor with unsaved changes can
each produce a wrong ledger without anyone intending it. Those are treated as
threats here, alongside the conventional ones.

Terms: the **ledger** is the user's Beancount plain-text ledger, a main file and
the files it includes. The **owned file** is the one included file Autobook may
write. The **driver** is the separate program that gets statements, converts
them to OFX and calls Autobook's commands. A **statement** is one OFX file the
driver hands over.

## 14.1 Assets

| Asset | Why it matters |
|-------|----------------|
| The ledger's integrity: the main file and every file it includes | A wrong booking misreports silently for years and may reach a tax filing. Autobook reads all of these files and must change none of them |
| The owned file | The only file Autobook writes. It holds every entry Autobook created, and the user or Fava may edit it too |
| Bank statements and memos | Counterparty names, IBANs, employers, Art. 9 special-category data. They reach Autobook as OFX files |
| Bills and invoices in paperless | Same, in more detail: line items, addresses, medical and legal providers |
| Staging store and review files | Derived from both of the above |
| User rules and correspondent associations | Encode who the user pays — personal data |
| The chart of accounts | Account names such as `Kirchensteuer` are Art. 9 data themselves |
| Credentials | paperless token, model API key |
| Shared rule packs | Influence what is written to every user's ledger |

## 14.2 Trust boundaries

- **The user's machine** — Autobook (one process), the ledger files, staging,
  configuration. Trusted.
- **The driver and the converter plugins** — a separate project that runs
  ofxstatement and hands over OFX files and an optional producer string. Trusted
  code that Autobook does not control and cannot inspect: Autobook checks a
  statement for consistency, not for how it was produced.
- **Statement content** — untrusted: a memo is arbitrary text written by a
  counterparty.
- **The ledger's other writers** — the user's editor, Fava, and any Beancount
  plugin the ledger loads. Trusted, but concurrent: there is no lock, and a
  plugin may change entries at load time.
- **paperless-ngx** — the user's own service, but its metadata may be
  model-generated. Trusted for availability and storage, **not** for the
  correctness of extracted fields.
- **The model backend** — local by default; a remote one is opt-in. Untrusted
  for confidentiality (remote) and for output correctness (any).
- **Rule packs** — third-party data; untrusted until pinned or signed and
  validated against local history.
- **Dependencies** — imported libraries must be licence-compatible with GPLv2,
  because Beancount is GPL-2.0-only (Autobook is GPL-2.0-or-later once ADR-0005
  is accepted).

## 14.3 Threats and mitigations

| Threat | Class | Mitigation |
|--------|-------|------------|
| Writing while an editor or Fava holds unsaved changes to the owned file: on save, the editor may overwrite the batch | Integrity, accidental | Not prevented — Beancount has no lock. Fava notices the change and reloads; an editor that does not warn overwrites. Detected afterwards: `autobook status` and the next run report proposal IDs that staging holds as applied and the ledger lacks; nothing is re-created silently. Residual, see 14.4 |
| A ledger file changes between Autobook's read and its replace | Integrity, accidental | The SHA-256 of every loaded file is taken at read and compared again before the replace; any difference stops the run with nothing written (exit 4) |
| Two Autobook runs write at once: both pass the compare, and the second replace discards the first batch | Integrity, accidental | `propose`, `apply`, `undo` and `decide` hold Autobook's own writer lock from before the first read until staging is updated; a run that cannot take it writes nothing (exit 4) |
| An editor or Fava saves the owned file between Autobook's last re-hash and its replace | Integrity, accidental | The replace is an atomic exchange (`renameat2` with `RENAME_EXCHANGE`), not a rename: what was swapped out is hashed, and if it is not the content the batch was rendered from, Autobook exchanges back and writes nothing (exit 4). The journal records where the swapped-out content is, so a crash right after the exchange is caught the same way on recovery. Exchanging back is checked too; a second save in between stops the run with every version kept as a file and the conflict reported. A displaced version is never deleted. Where the exchange is unavailable, `apply` refuses |
| A partial write: a crash or a full disk while the owned file is being written | Integrity, accidental | The new content goes to a temporary file in the same directory, is flushed to disk and exchanged with the owned file in one checked atomic exchange (never a plain rename), so no reader sees a half-written file; the previous content is kept as a pre-image, never deleted, and restored on any failure |
| An editor still holding the old owned file writes to it after the exchange | Integrity, accidental | That write lands in the swapped-out file, which is never deleted: it is the batch's pre-image from the start (the exchange's temporary file is given its unique final name beforehand), its hash is recorded in staging, and `autobook status` reports a pre-image whose content changed since |
| A split row is approved with postings the user never saw | Integrity, accidental | Every posting of a `create_split` row is stored in staging and shown in the review file; the parser checks that all postings, the source posting included, sum to exactly zero |
| A written batch that does not load as intended | Integrity, accidental | Read-back: the ledger is loaded again and every created row's proposal ID must appear exactly once with the approved date, accounts and amounts, and every matched row's recorded entry must still be present; no new load error; no byte before the appended entries and no other file changed; balances moved by exactly the sum of the postings written. On failure the previous file is restored (exit 6) and nothing is marked applied |
| A row approved without the user seeing it | Integrity, accidental | Only rows marked `a` in the saved review file are written, as shown; large-language-model (LLM) rows are never pre-marked before their precision is measured |
| A crash after the replace leaves a batch in the ledger that never passed its checks, and a later run accepts it because its IDs are present | Integrity, accidental | The batch journal, written and made durable (`fsync` of file and directory) before the replace, holding the complete baseline (every file's hash, the first load's errors, every account's balance): the next run validates the interrupted batch against that baseline or restores the previous content, also when another file changed meanwhile; if the file matches neither recorded hash it touches nothing and reports |
| Duplicate or lost entries after a crash | Integrity, accidental | Proposal-ID idempotency through `autobook-id` for created rows, staged content hashes for matched rows; re-runnable batches (section 8.2) |
| A posting pair off by less than Beancount's tolerance (half a cent) | Integrity, accidental | Autobook's own exact-sum check on every row: whole cents, summing to exactly zero, every posting with an explicit amount |
| A line matches a posting with the same number in another currency, on an account that holds several | Integrity, accidental | `match_existing` requires amount and currency to be equal, in the candidate search and again in the read-back |
| A matched entry is moved outside the date window, or otherwise stops qualifying, between proposal and apply | Integrity, accidental | The search is run again at apply and in the read-back; exactly one candidate must remain and it must be the recorded entry, otherwise the row is queued — also when a second candidate appeared |
| A transfer booked twice across two batches | Integrity, accidental | Source-account `match_existing` before classification; `transfers_pending`; an unmatched second side queues |
| A matched entry is edited afterwards, and a later line with the same amount and currency would match it as its only candidate | Integrity, accidental | The claim is kept as an orphaned claim, and matching is paused for that whole source account until the user rebinds the orphaned row (`m` on one listed candidate that passes the match predicate) or rejects it; `autobook status` lists orphaned claims |
| A classifier (or an untrusted model backend) proposes the source account as the destination, so the row nets to zero and the bank movement is absent while every balance check passes | Integrity, accidental or hostile backend | A created row may not post to its source account except through the source posting: such a proposal is queued, the parser rejects such an edit (exit 5), apply queues the row, and the read-back requires exactly one posting in the source account |
| The exchange makes the private ledger world-readable: the scratch file's inode, created under a `022` umask, replaces the owned file | Confidentiality | The scratch file is created `0600` and given the owned file's mode before the exchange, checked with `fstat` with the owner; an owned file with an ACL or extended attributes is refused; journal and staging are `0600` in a `0700` directory |
| A converter defect changes a date or narration, or swaps equal-valued postings, while every count and total still matches | Integrity, accidental | The conversion compares every transaction and posting by GUID (split GUIDs kept as posting metadata); any difference not listed per GUID in the decision file rejects it (proposal 0005 §14) |
| The review file shows a bare number and the user approves the wrong currency on an account that holds several | Integrity, accidental | Every review row shows its currency; the strict parser rejects a currency that differs from staging |
| Undo deletes an entry the user wrote | Integrity, accidental | Undo removes an entry only when its `autobook-id` is the proposal ID of a row staged as `create` or `create_split` in that batch **and** the entry is in the owned file; both are asserted first. Nothing is ever written to a matched entry |
| Autobook changes something the user wrote | Integrity, accidental | Structural: it writes transactions only, into the owned file only, by appending; on undo it removes exact spans; the assertion "no byte before the appended entries changed, and no other file changed" checks it on every apply |
| An OFX file that is wrong but self-consistent: the conversion dropped a line and the balances still add up, or the file states no balances | Integrity, accidental | Balance check on admission and the closing-balance assertion after writing, both only where the statement states balances; elsewhere only the user's own `balance` assertions. Autobook does not second-guess a well-formed statement. Residual, see 14.4 |
| A malformed or inconsistent OFX file | Integrity, accidental | Admission is all or nothing per statement: a parse failure, a line without date, amount or currency, an amount not in whole cents, an unknown account ID, an undeclared currency, a failed balance check or an unresolvable overlap rejects the statement and stages no line of it (exit 7) |
| A driver or converter plugin that rewrites memos | Integrity, accidental | The memo must arrive unmodified; Autobook cannot verify that. Coverage-drop and LLM-fallback drift gates, and the producer string in the version tuple, are the only defence |
| A user's Beancount plugin rewrites entries at load, so an entry does not read back as written | Integrity and availability, accidental | The read-back fails and the batch rolls back: loud, nothing wrong persists, but booking is blocked until the user resolves it |
| Misread bill total links the wrong bill | Integrity, accidental | Exact-amount matching against the bank line; confirmed correspondent association; duplicate documents dropped by checksum; one-to-one only |
| A bill without a correspondent, or with an unconfirmed one, decides an account | Integrity, accidental | It can only be a weak match: a hint line in the review file, never input to a rule |
| AI-applied tag drives a document-keyed rule | Integrity, accidental | `auto: false` by default and shadow mode per rule; the document history's actor (`System` or none = machine; a user accepting a suggestion counts as human-accepted, still shadowed) |
| Malicious or careless pack entry | Integrity, supply chain | Pinning or signing; ambiguity flags; per-user validation against the user's history before enabling; packs only propose and never bypass review |
| Prompt injection via memo text into the LLM tail | Integrity | Only a normalised merchant token is sent; temperature 0; output constrained to the live account list minus accounts not open on the line's date, accounts whose `open` directive does not allow the line's currency, and accounts under the Equity root; LLM proposals are never pre-marked before measured |
| Raw memo, IBAN or document content sent to a model backend | Confidentiality | Redaction at the adapter by type; documents never reach the adapter; tested at the boundary |
| A novel counterparty (a doctor, a lawyer) or an account name sent to a remote backend | Confidentiality | Local backend by default; a remote one gets only tokens matching a rule-pack entry or the user's allowlist, otherwise the LLM abstains; accounts cross as numeric indices |
| Personal data in logs, crash reports or committed fixtures | Confidentiality | Logs carry IDs and counts; the review file is written to standard output and kept by the driver, which should hold it under `$XDG_RUNTIME_DIR`, mode `0600`, and remove it afterwards; synthetic fixtures only |
| Personal data in a contributed pack | Confidentiality | Contribution emits pattern + category only; counterparty IBANs excluded structurally; human review at both ends |
| Credential leakage | Confidentiality | Secret Service only; never in config or repo |
| Over-broad paperless access | Confidentiality | Dedicated paperless user meant to see bill documents only. **[OPEN]** until D0: unowned documents are visible to every paperless user, so this holds only if every other document has an owner |
| An Apache-2.0 or GPLv3 dependency slips in | Licence, not ledger | Autobook imports `beancount` (GPL-2.0-only) and therefore may import only GPLv2-compatible libraries; it never imports `ofxstatement` (GPLv3). A check on dependency licences in the gate, not a habit (ADR-0005) |
| A refusal blocks the user's bookkeeping | Availability | A refusal writes nothing; the ledger is a text file and stays usable in any editor and in Fava; proposals stay pending |
| Prompt injection through issue text into the repository's triage bot (mislabel, abusive comment, spend) | Integrity of the issue tracker | The model gets no tools and no token; its answer is validated against the label sets and the priority computed by code; the work is split in two jobs: `classify` holds `contents: read`, `issues: read` and `id-token: write`, calls the model and can write nothing to GitHub, and hands its plan on as an artifact; `apply` holds `contents: read` and `issues: write`, runs no model, treats the plan as untrusted data (only labels from the scheme, at most one of each kind, only `needs-triage` removed, an assignee from the owner table, the bot's own comment), re-reads the issue and skips it if a human set a priority, another run triaged it or its text changed since, sets labels and comment straight again if a write fails, and calls just the label, assignee and comment endpoints; a back-fill's `dispatch` job holds `actions: write` only to start one run per issue, and runs no model; no job holds both `issues: write` and `id-token: write`; the Claude API token is federated, short-lived and accepted only from `main`; a workspace spending limit caps cost (ADR-0003) |
| Financial data pasted into a public issue repeated by the triage bot, or sent on to its model | Confidentiality | An issue with a checksum-valid IBAN, a credential of a known shape or an account path under a standard top-level account is not sent to the model; reasons that repeat the issue (word runs, numbers, amounts, identifier-like tokens) are withheld, and all reasons are when the model flags financial data; the bot asks for a made-up example (ADR-0003) |

## 14.4 Residual and accepted risks

- **Local compromise.** An attacker with the user's session can read the
  ledger, paperless and staging directly. Out of scope; Autobook adds no new
  exposure beyond what the ledger files and paperless already store.
- **An edit lost under an open editor.** Compare-before-write sees only what is
  on disk. Unsaved changes in an editor are invisible to Autobook, and what
  happens on save is the editor's decision. Accepted; reported after the fact,
  never repaired silently. What Fava and common editors do is measured in
  milestone B0.
- **A wrong but self-consistent statement.** Autobook sees only the OFX file.
  Where it states no balances, nothing at admission or after writing can detect
  a missing line.
- **A matched entry edited afterwards.** Its claim is kept as an orphaned claim,
  which queues later lines until the user resolves it; this costs a manual step.
- **A remote model backend sees allowlisted business-name tokens, account
  indices, amounts and signs.** Accepted when the user opts in; shown to the
  user exactly; avoided by the default local backend or no-AI mode.
- **Accounts without statement balances** have no admission-time integrity check.
  Visible in coverage reports.
- **Issue text sent to the triage bot's model provider.** Title and description of
  each public issue go to Anthropic's API unless they hold a checksum-valid IBAN, a
  credential of a known shape or an account path under a standard top-level
  account; a memo, amount or payee a reporter pasted is the accepted residual
  exposure (ADR-0003, #57).

## 14.5 Gaps

- **[OPEN]** Pack signing: mechanism not chosen.
- Tag provenance through the paperless audit log: answered.
  `GET /api/documents/{id}/history/` gives the actor; it needs
  `PAPERLESS_AUDIT_LOG_ENABLED` (default true), which D0 confirms.
- **[OPEN]** Paperless permissions: whether every other document has an owner,
  checked in D0.
- **[OPEN]** Abuse-case tests for the review-file parser and the adapter boundary,
  to be written with the components.
- **[OPEN]** Path handling for the owned file. The design requires the owned
  file to be among the files the main ledger loads, and refuses the run
  otherwise (exit 4). It does not say what happens when the configured path is
  a symbolic link, or resolves outside the directory tree the ledger includes.
  No mitigation is specified yet.
- **[OPEN]** The dependency-licence check in the gate: required by ADR-0005,
  not built.
- **[OPEN]** Where the review file lives is the driver's decision. Autobook can
  state the requirement (private to the user, short-lived) but cannot enforce
  it.

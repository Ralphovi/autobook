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
> behind it.

Autobook's threat model is unusual for a small tool: most of the harm it can do
needs **no attacker**. A plugin bug, a bank changing its memo format, a careless
rule pack or an overconfident model can each produce a wrong ledger without
anyone intending it. Those are treated as threats here, alongside the
conventional ones.

## 14.1 Assets

| Asset | Why it matters |
|-------|----------------|
| The book's integrity | A wrong booking misreports silently for years and may reach a tax filing |
| Bank statements and memos | Counterparty names, IBANs, employers, Art. 9 special-category data |
| Bills and invoices in paperless | Same, in more detail: line items, addresses, medical and legal providers |
| Staging store and review files | Derived from both of the above |
| User rules and correspondent associations | Encode who the user pays — personal data |
| The chart of accounts | Account names such as `Kirchensteuer` are Art. 9 data themselves |
| Credentials | paperless token, model API key, PostgreSQL book credentials |
| Shared rule packs | Influence what is written to every user's book |

## 14.2 Trust boundaries

- **The user's machine** — pipeline, book process, staging, configuration.
  Trusted.
- **paperless-ngx** — the user's own service, but its metadata may be
  model-generated. Trusted for availability and storage, **not** for the
  correctness of extracted fields.
- **Statement files and plugins** — trusted code, untrusted content: a memo is
  arbitrary text written by a counterparty.
- **The model backend** — local by default; a remote one is opt-in. Untrusted
  for confidentiality (remote) and for output correctness (any).
- **Rule packs** — third-party data; untrusted until pinned or signed and
  validated against local history.

## 14.3 Threats and mitigations

| Threat | Class | Mitigation |
|--------|-------|------------|
| Writing under a live GUI session corrupts the book | Integrity, accidental | Never `SESSION_BREAK_LOCK`; launcher sequencing; on `ERR_BACKEND_LOCKED` write nothing and notify |
| A row approved without the user seeing it | Integrity, accidental | Only rows marked `a` in the saved review file are written, as shown; large-language-model (LLM) rows are never pre-marked before their precision is measured |
| Duplicate or lost transactions after a crash | Integrity, accidental | Proposal-ID idempotency in `num` for created rows, staged GUIDs for matched rows; re-runnable batches (section 8.2) |
| A batch reported applied but never persisted (XML book ended without saving) | Integrity, accidental | `session.save()` after the last edit; a row is `applied` only after a read-back finds it |
| A bank row double-booked against a scheduled transaction GnuCash creates later | Integrity, accidental | Scheduled-transaction (SX) definitions exported; a row on an SX occurrence is never created — it matches or waits |
| A transfer booked twice across two batches | Integrity, accidental | Source-account `match_existing` before classification; `transfers_pending`; an unmatched second side queues |
| Undo deletes a transaction the user entered | Integrity, accidental | Undo deletes only when the GUID is staged as `create` **and** `num` equals the proposal ID; nothing is ever written to a matched transaction but a document link |
| Plugin misparses a statement | Integrity, accidental | Balance check on admission; statements read from originals only |
| Misread bill total links the wrong bill | Integrity, accidental | Exact-amount matching against the bank line; confirmed correspondent association; duplicate documents dropped by checksum; one-to-one only |
| A bill without a correspondent, or with an unconfirmed one, decides an account | Integrity, accidental | It can only be a weak match: a hint line in the review file, never input to a rule |
| AI-applied tag drives a document-keyed rule | Integrity, accidental | `auto: false` by default and shadow mode per rule; the document history's actor (`System` or none = machine; a user accepting a suggestion counts as human-accepted, still shadowed) |
| Malicious or careless pack entry | Integrity, supply chain | Pinning or signing; ambiguity flags; per-user validation before enabling; packs only propose |
| Prompt injection via memo text into the LLM tail | Integrity | Only a normalised merchant token is sent; temperature 0; output constrained to the live account list minus placeholder, Equity and Trading accounts; LLM proposals are never pre-marked before measured |
| Raw memo, IBAN or document content sent to a model backend | Confidentiality | Redaction at the adapter by type; documents never reach the adapter; tested at the boundary |
| A novel counterparty (a doctor, a lawyer) or an account name sent to a remote backend | Confidentiality | Local backend by default; a remote one gets only tokens matching a rule-pack entry or the user's allowlist, otherwise the LLM abstains; accounts cross as numeric indices |
| Personal data in logs, crash reports or committed fixtures | Confidentiality | Logs carry IDs and counts; review file and downloaded originals under `$XDG_RUNTIME_DIR`, mode `0600`, removed in `finally`; synthetic fixtures only |
| Personal data in a contributed pack | Confidentiality | Contribution emits pattern + category only; counterparty IBANs excluded structurally; human review at both ends |
| Credential leakage | Confidentiality | Secret Service only; never in config or repo |
| Over-broad paperless access | Confidentiality | Dedicated paperless user meant to see statement and bill documents only. **[OPEN]** until D0: unowned documents are visible to every paperless user, so this holds only if every other document has an owner |
| Book format upgraded by a newer libgnucash | Availability of the user's own book | Refuse to write any book that would need an upgrade (relevant the day bindings are bundled) |
| A refusal blocks the user's bookkeeping | Availability | GnuCash always opens; proposals stay pending |

## 14.4 Residual and accepted risks

- **Local compromise.** An attacker with the user's session can read the book,
  paperless and staging directly. Out of scope; Autobook adds no new exposure
  beyond what GnuCash and paperless already store.
- **A remote model backend sees allowlisted business-name tokens, account
  indices, amounts and signs.** Accepted when the user opts in; shown to the
  user exactly; avoided by the default local backend or no-AI mode.
- **Accounts without statement balances** have no admission-time integrity check.
  Visible in coverage reports.

## 14.5 Gaps

- **[OPEN]** Pack signing: mechanism not chosen.
- Tag provenance through the paperless audit log: answered.
  `GET /api/documents/{id}/history/` gives the actor; it needs
  `PAPERLESS_AUDIT_LOG_ENABLED` (default true), which D0 confirms.
- **[OPEN]** Paperless permissions: whether every other document has an owner,
  checked in D0.
- **[OPEN]** Abuse-case tests for the review-file parser and the adapter boundary,
  to be written with the components.

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
| Credentials | paperless token, model API key |
| Shared rule packs | Influence what is written to every user's book |

## 14.2 Trust boundaries

- **The user's machine** — pipeline, book process, staging, configuration.
  Trusted.
- **paperless-ngx** — the user's own service, but its metadata may be
  model-generated. Trusted for availability and storage, **not** for the
  correctness of extracted fields.
- **Statement files and plugins** — trusted code, untrusted content: a memo is
  arbitrary text written by a counterparty.
- **The model backend** — untrusted for both confidentiality (cloud) and output
  correctness (any).
- **Rule packs** — third-party data; untrusted until pinned or signed and
  validated against local history.

## 14.3 Threats and mitigations

| Threat | Class | Mitigation |
|--------|-------|------------|
| Writing under a live GUI session corrupts the book | Integrity, accidental | Never `SESSION_BREAK_LOCK`; launcher sequencing; lock deferral when unattended |
| Duplicate or lost transactions after a crash | Integrity, accidental | `num` idempotency; re-runnable batches (section 8.2) |
| Plugin misparses a statement | Integrity, accidental | Balance check on admission; statements read from originals only |
| Misread bill total links the wrong bill | Integrity, accidental | Exact-amount matching against the bank line; one-to-one only |
| AI-applied tag drives a document-keyed rule | Integrity, accidental | Shadow mode per rule; tag provenance if paperless exposes it |
| Malicious or careless pack entry | Integrity, supply chain | Pinning or signing; ambiguity flags; per-user validation before enabling; packs only propose |
| Prompt injection via memo text into the LLM tail | Integrity | Only a normalised merchant token is sent; output constrained to the live account list; LLM proposals go through the same gates and review |
| Raw memo, IBAN or document content sent to a model backend | Confidentiality | Redaction at the adapter by type; documents never reach the adapter; tested at the boundary |
| Personal data in logs, crash reports or committed fixtures | Confidentiality | Logs carry IDs and counts; review file under `$XDG_RUNTIME_DIR`; synthetic fixtures only |
| Personal data in a contributed pack | Confidentiality | Contribution emits pattern + category only; counterparty IBANs excluded structurally; human review at both ends |
| Credential leakage | Confidentiality | Secret Service only; never in config or repo |
| Over-broad paperless access | Confidentiality | Dedicated paperless user, view permission on statement and bill types only |
| Book format upgraded by a newer libgnucash | Availability of the user's own book | Refuse to write any book that would need an upgrade (relevant the day bindings are bundled) |
| A refusal blocks the user's bookkeeping | Availability | GnuCash always opens; proposals stay pending |

## 14.4 Residual and accepted risks

- **Local compromise.** An attacker with the user's session can read the book,
  paperless and staging directly. Out of scope; Autobook adds no new exposure
  beyond what GnuCash and paperless already store.
- **A cloud model backend sees merchant tokens and amounts.** Accepted when the
  user configures one; shown to the user exactly; avoidable with a local backend
  or no-AI mode.
- **Accounts without statement balances** have no admission-time integrity check.
  Visible in coverage reports.

## 14.5 Gaps

- **[OPEN]** Pack signing: mechanism not chosen.
- **[OPEN]** Tag provenance through the paperless audit log: availability unknown
  (proposal 0002, D0).
- **[OPEN]** Abuse-case tests for the review-file parser and the adapter boundary,
  to be written with the components.

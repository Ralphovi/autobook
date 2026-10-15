---
created: 26.07.2026 19:00
type: index
tags:
  - index
  - adr
---
# Architecture decision records

Numbered, immutable records of *why* a decision was made. An accepted ADR is
never edited — it is superseded by a later record that references it, and the
supersession is noted in this table. **This index is the authority on what
currently stands**, because the documents themselves cannot say that they have
been overtaken.

See [ADR-0001](0001-record-architecture-decisions.md) for the process and
[`../templates/adr.md`](../templates/adr.md) to start one.

| # | Title | Status | Notes |
|---|-------|--------|-------|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted | |
| [0002](0002-gpl-license-and-dco.md) | GPL-3.0-or-later, and the DCO | Accepted | Whole repo GPL; the PDCA harness stays Apache-2.0 |

## Decisions not yet recorded here

The system design in [proposal 0001](../proposals/draft/0001-gnucash-auto-booking-pipeline.md)
contains several settled choices that would each make a reasonable ADR — the
two-process boundary, the defer-to-GnuCash principle, kNN over the Bayes matcher,
and the permanent scope exclusions. They are deliberately left in the proposal
for now rather than pre-emptively split out. Extract one into an ADR when it is
first cited to settle an argument; that is the moment its rationale needs to
stand on its own, and doing it earlier is filing for its own sake.

### ADR candidates

Decisions that are foundational enough to need an ADR when first contested, or
that would change something an accepted ADR or a MUST rule already says:

| Candidate | Source | Why it needs an ADR |
|-----------|--------|---------------------|
| No model runs on documents; OCR and extraction belong to paperless-ngx | Proposal 0002 §1 | Foundational constraint of the document design; reversing it moves document content inside Autobook's process |
| A statement is never taken from extraction (OCR, archive version or metadata); only the original file, parsed by its plugin | Proposal 0002 §2 | Foundational constraint; the ledger's reference data must not pass through OCR |
| Bill matching is on exact amount only | Proposal 0002 §4.2 | Foundational constraint; it is what makes model-filled totals safe |
| Line-item splits from invoices | Proposal 0002 §9, [architecture section 9](../architecture/09-build-order-and-roadmap.md) | Would amend the "splits are rules-tier only" MUST in AGENTS.md and proposal 0001; a proposal alone cannot do that |
| Revisiting splits in a currency other than the account's | Proposal 0001 (*Out of scope*) | Settled as permanent in proposal 0001 (ADR-0001's context cites it as an example); revisiting needs an ADR that records the change |
| Revisiting securities transactions | Proposal 0001 (*Out of scope*) | Settled as permanent in proposal 0001 (ADR-0001's context cites it as an example); revisiting needs an ADR that records the change |

The renaming of the applier to the **book process** (exporter and applier) does
not contradict ADR-0001: the two-process split it mentions is unchanged.

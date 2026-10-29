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

## How an ADR is made

The rules are in ADR-0001 (lifecycle and supersession) and ADR-0004 (proposals and
specifications). In order:

1. **Open an issue** that states the question. Every pull request needs one, and the
   discussion before there is a draft belongs there.
2. **Take the next number.** One more than the highest number in the index and in any open
   pull request that adds an ADR. Numbers are never reused, not even for an ADR that was
   dropped.
3. **Write it from the template.** Copy [`../templates/adr.md`](../templates/adr.md) to
   `NNNN-short-title.md`, keep `status: Proposed` with nothing after it on that line, and
   write Context, Decision and Consequences. Mark anything still undecided **[OPEN]**.
4. **Add it to the index** below, with status `Proposed`, in the same pull request.
5. **Open the pull request** with `Refs #N` for the issue. Discussion happens there; a
   Proposed ADR may be edited freely, before and after it merges.
6. **Accept it.** When the maintainer agrees and no **[OPEN]** items are left, change
   `status:` to `Accepted` and the index row to match, then merge. This edit is the act of
   acceptance; only a maintainer makes it, never an agent. From here the file is frozen
   (`docs-immutability`).
7. **Change it later only by superseding it** (ADR-0001): a new ADR with
   `supersedes: NNNN`, and the old index row changed to `Superseded by NNNN`, in one pull
   request. The old file stays untouched.

`docs-check` keeps this index honest: every ADR is listed once, its status here matches its
frontmatter, and both sides of every supersession agree. Run
`python3 -I .github/docs-check/adr_index.py` before pushing.

## Index

| # | Title | Status | Notes |
|---|-------|--------|-------|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted | |
| [0002](0002-gpl-license-and-dco.md) | GPL-3.0-or-later, and the DCO | Accepted | Whole repo GPL; the PDCA harness stays Apache-2.0 |
| [0003](0003-issue-priority-and-automated-triage.md) | Issue priority and automated triage: severity × reach set P0–P3; a GitHub Action applies it with one Claude API call per issue | Proposed | Booking-integrity and security/privacy overrides; Workload Identity Federation; a real IBAN is never sent to the model |
| [0004](0004-proposal-and-spec-process.md) | Proposal and specification process, lifecycle, and immutability | Proposed | Supersession is recorded in each class index; frozen files are never edited |

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

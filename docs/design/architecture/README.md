---
created: 26.07.2026 19:00
type: index
tags:
  - index
  - architecture
---
# Architecture overview

The living description of the system — trimmed [arc42](https://arc42.org/) plus
[C4](https://c4model.com/) diagrams, numbered `NN-section-name.md`, structured
like Wyrd's. Edited continuously; once code exists it must never lag the code.

**These sections describe the system as designed** in
[proposal 0005](../proposals/draft/0005-beancount-ledger.md): Autobook is handed
OFX statement files by an outside driver and books them into a Beancount
plain-text ledger. Proposal 0005 is the whole system design. It replaces
proposals 0001 (the GnuCash design) and 0003 (windows and command line), which
stay in `draft/` until 0005 is accepted and are withdrawn then.
[Proposal 0002](../proposals/draft/0002-document-driven-booking-via-paperless.md)
(bills from paperless) and
[proposal 0004](../proposals/draft/0004-rules-first-mined-from-history.md)
(rules first, mined from history) still apply, with the changes listed in
proposal 0005's section *Relation to the other proposals*; where they say
"0001", read 0005.

Part of the design is implemented: the normaliser, the kNN classifier and the
backtest. For those, the sections follow the code. For everything else the
proposals remain the authority on *why*; where a section and a proposal
disagree, the proposal governs until code exists, and the code governs after.
One exception to "the proposal governs": the **execution order** of the build is
decided in section 9 alone; the proposals' build-order sections describe what
each step contains.

An earlier version of this index argued the directory should stay empty until
the first code landed. That was revised: the proposals together had become too
large to serve as the only map of the system, and a sectioned description is
what a contributor reads first.

"Update the architecture doc" is a merge requirement on any PR that changes
structure, not a follow-up. It applies from the first PR, with no starting step
(the same rule as in [`AGENTS.md`](../../../AGENTS.md)).

## Sections

| # | Section | Covers |
|---|---------|--------|
| 1 | [Introduction and goals](01-introduction-and-goals.md) | What Autobook is, the headline guarantee, quality goals in priority order, scope |
| 2 | [Constraints](02-constraints.md) | Technical, organisational, conventions |
| 3 | [Context and scope](03-context-and-scope.md) | External partners and what crosses each interface |
| 4 | [Solution strategy](04-solution-strategy.md) | Quality goals traced to strategies; the shape in one paragraph |
| 5 | [Building block view](05-building-block-view.md) | Input, pipeline, staging, the ledger package; the contracts between them; the command line |
| 6 | [Runtime view](06-runtime-view.md) | A booking run, statement admission, deciding a row, bill linking, apply and crash recovery, undo, refusal |
| 7 | [Deployment view](07-deployment-view.md) | Profiles, what gets installed, the reference deployment, platforms |
| 8 | [Cross-cutting concepts](08-crosscutting-concepts.md) | Money, idempotency, provenance and the version gate, privacy, configuration |
| 9 | [Build order and roadmap](09-build-order-and-roadmap.md) | The single governing execution order, merging the milestones of proposals 0005, 0002 and 0004, with status |
| 10–13 | [Quality, risks, glossary, testing](10-quality-risks-glossary.md) | Measurable scenarios, risks, conscious exclusions, glossary, test tiers |
| 14 | [Threat model](14-threat-model.md) | Assets, trust boundaries, threats including the accidental ones |

Diagrams are Mermaid source in [`diagrams/`](diagrams/), never binary exports.

Start a new section from [`../templates/architecture.md`](../templates/architecture.md).

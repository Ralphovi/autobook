---
created: 26.07.2026 19:00
type: index
tags:
  - index
---
# Autobook — design documentation

The design documentation is organised into three classes, each with its own
purpose and change process. The distinction matters because some of these
documents are *settled* — they record decisions that should not be relitigated
every time someone new reads the code — while others describe a system that is
expected to keep changing.

## The three document classes

| Class | Location | Nature | Change process |
|-------|----------|--------|----------------|
| 1. Decision records (ADRs) | [`adr/`](adr/README.md) | Immutable history | Append-only; superseded, never edited |
| 2. Proposals | [`proposals/`](proposals/README.md) | The change process | `draft/` → `accepted/`; accepted records are immutable |
| 3. Architecture overview | [`architecture/`](architecture/README.md) | Descriptive, living | Edited continuously; always describes the current system |

Autobook has **no specification class**. Wyrd, whose documentation structure this
borrows, needs one because its on-disk format must outlive the software that
wrote it. Autobook writes through GnuCash's engine API and owns no persistent
format that another implementation must conform to — the staging table is
internal and disposable, and the book format belongs to GnuCash. If a shareable
rule-pack format ever needs a compatibility contract, that is the point to add
the class back, not before.

### 1. Decision records (`adr/`)

Short, numbered, immutable records of *why* a decision was made, in
[Nygard](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)
style. They exist so the same debate — "why not piecash?", "why kNN rather than
GnuCash's Bayes matcher?" — is not reopened in every new issue. An ADR is never
edited after acceptance; it is superseded by a later ADR that references it.

Start one from [`templates/adr.md`](templates/adr.md) and add a row to the
[ADR index](adr/README.md).

### 2. Proposals (`proposals/`)

How design change flows. A proposal carries motivation, design, alternatives, and
graduation criteria, and moves from `draft/` to `accepted/`. Modelled on
Kubernetes KEPs and Rust RFCs, kept deliberately lightweight.

The whole system design is [proposal 0001](proposals/draft/0001-gnucash-auto-booking-pipeline.md),
amended by [proposal 0002](proposals/draft/0002-document-driven-booking-via-paperless.md)
(statements and bills from paperless-ngx). For the rows in 0002's *Changes to
proposal 0001* table, 0002 governs.
[Proposal 0003](proposals/draft/0003-windowed-interface-and-command-line.md)
adds the command line's verbs and contract and GTK4 windows as their client. The order in which the build steps are
carried out is decided in
[architecture section 9](architecture/09-build-order-and-roadmap.md), not in
the proposals.

Start one from [`templates/proposal.md`](templates/proposal.md).

### 3. Architecture overview (`architecture/`)

The living description of the system as it currently is — trimmed
[arc42](https://arc42.org/). It is edited continuously and must never lag the
code. "Update the architecture doc" is a legitimate merge requirement on a PR
that changes structure, not a follow-up.

Until the first code lands it describes the system as designed in proposals 0001
and 0002, and says so in every section; from then on it follows the code. See
the [architecture index](architecture/README.md) for why this changed.

Start a section from [`templates/architecture.md`](templates/architecture.md).

## Conventions

- **Immutability.** Once an ADR is Accepted or a proposal accepted, its file is
  frozen. To change it, write a *new* document carrying `supersedes: <old>`,
  leave the old file untouched, and record the supersession in the index. Do not
  add a "superseded by" banner to the frozen file.
- **Front matter.** Every ADR and proposal carries the YAML front matter its
  template defines. `nox -s docs` checks this, that ADR numbers are unique and
  indexed, and that relative links resolve.
- **No Obsidian wikilinks.** `[[like this]]` renders as literal text on GitHub;
  the docs lint rejects it. Use ordinary Markdown links.
- **Reference decisions by number** in prose — "see ADR-0002" — rather than
  restating their reasoning.

## Reading order

1. [`architecture/01-introduction-and-goals.md`](architecture/01-introduction-and-goals.md)
   — what this is, the guarantee, the quality goals.
2. [`architecture/05-building-block-view.md`](architecture/05-building-block-view.md)
   — the processes, components and contracts.
3. [Proposal 0001](proposals/draft/0001-gnucash-auto-booking-pipeline.md) and
   [proposal 0002](proposals/draft/0002-document-driven-booking-via-paperless.md)
   — the full reasoning, alternatives, and what each build step contains. The
   execution order is
   [architecture section 9](architecture/09-build-order-and-roadmap.md).
4. [ADR-0002](adr/0002-gpl-license-and-dco.md) — licensing and contribution
   provenance.
5. [`AGENTS.md`](../../AGENTS.md) — the rules that bind anyone, human or agent,
   writing code here.

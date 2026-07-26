---
created: 26.07.2026 19:00
type: adr
status: Accepted
tags:
  - adr
  - process
---
# 0001. Record architecture decisions

## Context

Autobook is a small project with an unusually high cost of forgetting *why*.
Several of its central choices look arbitrary or even wrong from the code alone,
and each has a reasoned justification that took real effort to arrive at:

- classification runs rules → kNN → LLM in that order, for determinism, **not**
  token cost;
- kNN is preferred over GnuCash's own Bayes matcher for **abstention**, not
  accuracy;
- the pipeline and applier are separate processes, which looks like
  over-engineering until the `dist-packages` problem is explained;
- securities and cross-currency splits are permanently out of scope, which reads
  as an unfinished feature rather than a decision;
- `piecash`, CSV import, and an in-app GnuCash plugin were each considered and
  rejected.

Without a record, every one of these is re-proposed by the next contributor — or
by the next model — and the argument is had again from a worse starting position,
because the evidence that settled it has been lost.

Decisions of this kind also age differently from code. The reasoning behind
"exclude securities" stays valid long after the module layout that implemented it
has been rewritten.

## Decision

We will record architecture decisions in this directory as numbered
[Nygard-style](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)
records: `NNNN-short-title.md`, with Context, Decision, and Consequences.

An ADR records a decision *and its rationale*, including what was rejected and
why. A record that states only the outcome has failed at its one job.

**ADRs are append-only.** Once a record is Accepted its file is frozen. To change
a decision, write a new ADR that references and supersedes it, leave the old file
untouched, and record the supersession in the index. Reversing a decision is
normal; quietly editing the history that justified it is not.

Use an ADR when the decision is foundational — it constrains what can be built
later. Use a [proposal](../proposals/README.md) when it is an implementation plan
for something already agreed. When in doubt, a proposal can cite an ADR it
depends on; an ADR should not depend on a proposal.

## Consequences

- The cost is a short document per decision, written when the decision is fresh
  and the reasoning is still recoverable. Written later, it is reconstruction.
- The benefit is that "why not just use piecash?" has an answer with a date on
  it, and that answer is available to a contributor or an agent reading the
  repository cold.
- Accepting immutability means the index — not the documents — carries the
  current state. A reader must consult [the index](README.md) to know whether a
  record still stands.
- `nox -s docs` enforces the mechanical part: front matter, unique numbers,
  presence in the index, and resolvable links. It cannot enforce that the
  rationale is actually recorded; review does that.

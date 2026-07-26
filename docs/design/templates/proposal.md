---
created: <DD.MM.YYYY HH:MM>
type: proposal
status: draft   # draft | accepted | implemented | withdrawn
author:
tracking-issue:
tags:
  - proposal
---
# Proposal: <title>

> Proposals are how design change flows. Move this file from `draft/` to
> `accepted/` when accepted; an accepted proposal is frozen — supersede it rather
> than rewriting it. If the change is a foundational decision rather than an
> implementation plan, it may warrant an ADR instead. Early in the project this is
> deliberately lightweight; the discipline matters more than the ceremony.

## Motivation

What problem does this solve? Why now? What is the user-visible need? If this
changes what gets written to a book, say so in the first paragraph.

## Design

The proposed change. Be concrete about which component it lands in — pipeline or
applier — and about anything crossing the JSON boundary between them.

State explicitly whether it touches any of:

- the classification cascade or its confidence gates,
- the staging schema or a disposition,
- the write path, idempotency, or locking,
- what leaves the machine.

Each of those carries a higher bar. The hard rules in `AGENTS.md` are not
negotiable within a proposal.

## Alternatives considered

What else was weighed, and why this over those? Check the *Rejected alternatives*
table in proposal 0001 first — if this reopens one, say what new evidence
justifies that.

## Graduation criteria

How do we know it is done and correct? For anything classification-shaped the
answer is a **backtest against the corpus**, reported per method and per
confidence band — not an impression that it seems better. State the measurement
before building it.

For anything that writes: which post-apply assertion proves it, and how is it
reversed if it turns out wrong?

## Risks

What silently misreports if this is subtly wrong? A change whose failure mode is
a loud error is far cheaper than one whose failure mode is a plausible wrong
account, and the difference belongs here.

## Backward compatibility

Effect on existing staging data, existing rule files, an already-built index, and
the version gate tuple. Changing the normaliser or the rule format invalidates
what is already staged; say so.

## Open questions

Mark unresolved points explicitly.

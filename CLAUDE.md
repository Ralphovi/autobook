# Autobook — Claude Code context

The repository conventions live in [AGENTS.md](AGENTS.md). Read it before making
changes; it is vendor-neutral and is the single source for worktree discipline,
PR gates, the hard rules for book writes, and the review rubric.

Quick orientation:

- **The design** is `docs/design/proposals/draft/0001-gnucash-auto-booking-pipeline.md`.
  There is no implementation yet.
- **The gate** is `nox -s gate`. Run it before proposing a PR.
- **Two hard rules** worth internalising before you touch anything:
  nothing in the pipeline may import `gnucash`, and money is never a float.

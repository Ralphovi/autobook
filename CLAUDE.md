# Autobook — Claude Code context

The repository conventions live in [AGENTS.md](AGENTS.md). Read it before making
changes; it is vendor-neutral and is the single source for worktree discipline,
PR gates, the hard rules for book writes, and the review rubric.

Quick orientation:

- **The design** is proposal 0001
  (`docs/design/proposals/draft/0001-gnucash-auto-booking-pipeline.md`) as
  amended by proposal 0002
  (`docs/design/proposals/draft/0002-document-driven-booking-via-paperless.md`),
  described in `docs/design/architecture/`. There is no implementation yet.
- **The gate** is `nox -s gate`. Run it before proposing a PR.
- **Two hard rules** worth internalising before you touch anything:
  nothing in the pipeline may import `gnucash` (only the book process may), and
  money is never a float.

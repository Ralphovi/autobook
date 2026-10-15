# Autobook — documentation

This repository is the source of truth for Autobook's documentation. It is
authored in Markdown and read in Git, GitHub, or any editor. There is no
published site.

## Where things live

| Path | What it is |
|------|------------|
| [`design/`](design/README.md) | **Start here.** Decision records, proposals, and the living architecture description, in three classes with different change processes. |
| [`design/proposals/draft/0001-gnucash-auto-booking-pipeline.md`](design/proposals/draft/0001-gnucash-auto-booking-pipeline.md) | The design, as amended by proposal 0002. Read this before anything else. |
| [`design/proposals/draft/0002-document-driven-booking-via-paperless.md`](design/proposals/draft/0002-document-driven-booking-via-paperless.md) | Statements and bills from paperless-ngx; amends 0001. For the rows in its *Changes to proposal 0001* table, 0002 governs. |
| [`design/architecture/`](design/architecture/README.md) | The living description of the design: proposal 0001 as amended by 0002. |
| [`tools/`](tools/lint_docs.py) | `lint_docs.py`, run by `nox -s docs` as part of the gate. Not documentation. |

Repository conventions — worktree discipline, PR gates, the hard rules for
anything that writes to a book, and the review rubric — are in
[`AGENTS.md`](../AGENTS.md), not here.

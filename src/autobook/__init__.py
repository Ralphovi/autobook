"""Autobook — automatic destination-account assignment for GnuCash bank imports.

There is no implementation yet. The design is proposal 0001
(`docs/design/proposals/draft/0001-gnucash-auto-booking-pipeline.md`) as amended
by proposal 0002 (`docs/design/proposals/draft/0002-document-driven-booking-via-paperless.md`),
described in `docs/design/architecture/`. Build order step 2 (corpus export, kNN,
backtest harness) is the first code to exist after the spikes, because it is
what tells us whether the premise holds.

**Nothing in the pipeline may import `gnucash`.** The pipeline runs with no
GnuCash installed and no book present; only the book process (the read-only
exporter from step 2, the applier from step 5) links libgnucash, across the
JSON boundary. `ruff`'s banned-api rule enforces this; book-process modules
carry an explicit per-file exception. See AGENTS.md.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.0.0"

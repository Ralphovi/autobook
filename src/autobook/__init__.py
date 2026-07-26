"""Autobook — automatic destination-account assignment for GnuCash bank imports.

There is no implementation yet. The design is
`docs/design/proposals/draft/0001-gnucash-auto-booking-pipeline.md`; build order
step 2 (corpus export, kNN, backtest harness) is the first thing to exist,
because it is what tells us whether the premise holds.

**Nothing in this package may import `gnucash`.** The pipeline runs with no
GnuCash installed and no book present; only the applier links libgnucash, across
the JSON boundary. `ruff`'s banned-api rule enforces this. See AGENTS.md.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.0.0"

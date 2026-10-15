"""Staging store — building block of ch.5 section 5.1.

Design: `docs/design/architecture/05-building-block-view.md`.

Its own top-level block, not part of the pipeline: the pipeline writes decisions
to it, and the book process's read-back records `applied` and undo reads the
GUID list. **Standard library only, and never `gnucash`.**

Stub: the entry point exists so later build steps have a symbol to change.
"""

from __future__ import annotations

__all__ = ["open_store"]


def open_store() -> None:
    """Entry point of the staging store block."""
    raise NotImplementedError

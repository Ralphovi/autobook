"""Undo — building block of ch.5 section 5.3.

Design: `docs/design/architecture/05-building-block-view.md`.

Stub: the entry point exists so later build steps have a symbol to change; it
has no behaviour yet.

Book-process module. It does not import `gnucash` yet; the first per-file ruff
exception arrives with the exporter.
"""

from __future__ import annotations

__all__ = ["undo_batch"]


def undo_batch() -> None:
    """Entry point of the undo block."""
    raise NotImplementedError

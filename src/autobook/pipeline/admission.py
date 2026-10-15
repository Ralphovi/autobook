"""Admission and dedup — building block of ch.5 section 5.2.

Design: `docs/design/architecture/05-building-block-view.md`.

Stub: the entry point exists so later build steps have a symbol to change; it
has no behaviour yet.

Pipeline module: must never import `gnucash`.
"""

from __future__ import annotations

__all__ = ["admit_statement"]


def admit_statement() -> None:
    """Entry point of the admission and dedup block."""
    raise NotImplementedError

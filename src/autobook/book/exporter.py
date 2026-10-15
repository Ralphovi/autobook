"""Exporter — building block of ch.5 section 5.3.

Design: `docs/design/architecture/05-building-block-view.md`.

Stub: the entry point exists so later build steps have a symbol to change; it
has no behaviour yet.

Book-process module. It does not import `gnucash` yet; the first per-file ruff
exception arrives with the exporter.
"""

from __future__ import annotations

__all__ = ["export_book"]


def export_book() -> None:
    """Entry point of the exporter block."""
    raise NotImplementedError

"""Smoke tests: the package imports, and the pipeline/applier boundary holds.

The boundary test is not ceremony. "The pipeline does not depend on libgnucash"
is the claim the whole two-process architecture rests on, and it is the kind of
claim that quietly stops being true the first time someone adds a convenient
import. `ruff`'s banned-api rule catches it in the linter; this catches it at
runtime, including for a transitive import the linter cannot see.
"""

from __future__ import annotations

import sys

import autobook


def test_package_imports() -> None:
    assert autobook.__version__


def test_pipeline_does_not_import_gnucash() -> None:
    """Importing autobook must not pull in the GnuCash bindings.

    Passes trivially where GnuCash is not installed — which is the point: this
    suite must give the same verdict on a developer's machine that has it and in
    CI, which does not.
    """
    assert "gnucash" not in sys.modules, (
        "importing autobook pulled in the gnucash bindings — the pipeline must "
        "run with no GnuCash installed. See the boundary rules in AGENTS.md."
    )

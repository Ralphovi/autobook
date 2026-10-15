"""The package skeleton: one importable stub per building block of ch.5.

Modules are discovered with `pkgutil`, not named, so a missing module shows up
as a count below the minimum. Everything is loaded inside the test body. A block
that has been built is listed in `IMPLEMENTED` and leaves the stub checks; every
other check still covers it.
"""

from __future__ import annotations

import importlib
import importlib.util
import pkgutil
import sys
from typing import Any

import pytest

MINIMUM_MODULES = {"autobook.pipeline": 11, "autobook.book": 6}

# Building blocks that export their real API instead of one stub entry point.
IMPLEMENTED = {
    "autobook.pipeline.classifier",
    "autobook.pipeline.normaliser",
    "autobook.pipeline.trial",
}


def _modules(package: str) -> list[str]:
    path = importlib.import_module(package).__path__
    return sorted(f"{package}.{info.name}" for info in pkgutil.iter_modules(path))


def _all_building_blocks() -> list[str]:
    blocks = ["autobook.staging"]
    for package in MINIMUM_MODULES:
        blocks.extend(_modules(package))
    return blocks


@pytest.mark.parametrize("package", sorted(MINIMUM_MODULES))
def test_package_has_one_module_per_building_block(package: str) -> None:
    assert len(_modules(package)) >= MINIMUM_MODULES[package]


def test_staging_is_a_top_level_block_not_part_of_the_pipeline() -> None:
    # Ask the import system, not `_all_building_blocks()`, which names staging itself.
    assert importlib.util.find_spec("autobook.staging") is not None
    assert importlib.util.find_spec("autobook.pipeline.staging") is None


def test_every_block_has_one_entry_point_that_is_not_implemented() -> None:
    blocks = _all_building_blocks()
    assert set(blocks) >= IMPLEMENTED, "IMPLEMENTED names a module that is not a block"
    for name in blocks:
        if name in IMPLEMENTED:
            continue
        module: Any = importlib.import_module(name)
        assert len(module.__all__) == 1, name
        entry_point = getattr(module, module.__all__[0])
        assert callable(entry_point), name
        with pytest.raises(NotImplementedError):
            entry_point()


def test_building_blocks_and_contracts_do_not_import_gnucash() -> None:
    for name in _all_building_blocks():
        importlib.import_module(name)
    importlib.import_module("autobook.contracts")
    assert "gnucash" not in sys.modules, (
        "a building block or the contracts pulled in the gnucash bindings — only "
        "the book process may import them, and no module does yet. See AGENTS.md."
    )

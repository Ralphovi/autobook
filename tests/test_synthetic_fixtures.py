"""The synthetic fixtures: a seeded corpus builder and a `coa.json` document.

The builder and `autobook.contracts` are loaded inside each test, never at module
scope.
"""

from __future__ import annotations

import importlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

SYNTHETIC = Path(__file__).parent / "fixtures" / "synthetic"
SEEDS = (0, 1, 42)


def _builder() -> Any:
    return importlib.import_module("tests.fixtures.synthetic.corpus_builder")


def _contracts() -> Any:
    return importlib.import_module("autobook.contracts")


def test_same_seed_gives_an_equal_corpus_and_another_seed_a_different_one() -> None:
    build = _builder().build_corpus
    assert build(7) == build(7)
    assert build(7) != build(8)


def test_corpus_has_near_duplicate_memos_for_the_same_merchant() -> None:
    builder = _builder()
    for seed in SEEDS:
        memos: dict[str, set[str]] = defaultdict(set)
        for row in builder.build_corpus(seed).rows:
            for merchant in builder.MERCHANTS:
                if row.raw_memo.startswith(merchant.token):
                    memos[merchant.token].add(row.raw_memo)
        assert set(memos) == {merchant.token for merchant in builder.MERCHANTS}
        assert all(len(variants) >= 3 for variants in memos.values()), seed


def test_corpus_has_exactly_one_novel_merchant_row_on_the_latest_date() -> None:
    builder = _builder()
    for seed in SEEDS:
        rows = builder.build_corpus(seed).rows
        novel = [row for row in rows if builder.NOVEL_MERCHANT in row.raw_memo]
        latest = max(row.post_date for row in rows)
        assert len(novel) == 1, seed
        assert novel[0].post_date == latest, seed
        assert [row.post_date for row in rows].count(latest) == 1, seed
        # the final month also holds ordinary rows, so the backtest has an index
        assert any(
            row.post_date.month == latest.month and row.post_date != latest for row in rows
        ), seed


def test_corpus_rows_are_integer_cents_observed_and_free_of_iban_shapes() -> None:
    for seed in SEEDS:
        for row in _builder().build_corpus(seed).rows:
            assert type(row.amount_cents) is int
            assert row.amount_cents > 0
            assert row.provenance == "observed"
            assert not any(
                token[:2].isalpha() and token[2:4].isdigit() and len(token) >= 15
                for token in row.raw_memo.split()
            )


def test_corpus_round_trips_through_the_contract() -> None:
    contracts = _contracts()
    corpus = _builder().build_corpus(3)
    document = contracts.serialise_corpus(corpus)
    assert contracts.parse_corpus(document) == corpus
    assert contracts.corpus_from_json(json.dumps(document)) == corpus
    assert contracts.serialise_corpus(contracts.parse_corpus(document)) == document


def test_coa_json_is_a_valid_coa_document_for_the_synthetic_book_tree() -> None:
    contracts = _contracts()
    document = json.loads((SYNTHETIC / "coa.json").read_text(encoding="utf-8"))
    coa = contracts.parse_coa(document)
    assert contracts.serialise_coa(coa) == document
    assert [(a.path, a.type) for a in coa.accounts] == [
        (("Aktiva",), "ASSET"),
        (("Aktiva", "Girokonto"), "BANK"),
        (("Aktiva", "Revolut"), "BANK"),
        (("Ausgaben",), "EXPENSE"),
        (("Ausgaben", "Lebensmittel"), "EXPENSE"),
        (("Ausgaben", "Miete"), "EXPENSE"),
        (("Einnahmen",), "INCOME"),
        (("Einnahmen", "Gehalt"), "INCOME"),
    ]
    assert all(
        not a.placeholder
        and (a.commodity.namespace, a.commodity.mnemonic) == ("CURRENCY", "EUR")
        and a.fraction == 100
        for a in coa.accounts
    )

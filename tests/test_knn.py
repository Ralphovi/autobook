"""The kNN tier of the classifier: two gates, one account, structural provenance (ch.5 5.2).

Every memo, merchant and account here is invented (`tests/fixtures/synthetic`). The
thresholds are test inputs, not a recommendation: real ones come from the backtest.

Only modules that exist without this change are imported at module scope. Every name
the change adds is reached through the module object inside a test body, so with the
change reverted each test runs and fails instead of the file failing to import.
"""

from __future__ import annotations

import dataclasses
import datetime
import random
import typing
import unittest.mock
from pathlib import Path
from typing import Any

import pytest

from autobook.pipeline import classifier, normaliser
from tests.fixtures.synthetic import corpus_builder

GIROKONTO = corpus_builder.GIROKONTO
REVOLUT = corpus_builder.REVOLUT
LEBENSMITTEL = corpus_builder.LEBENSMITTEL
MIETE = corpus_builder.MIETE

MAX_DISTANCE = 0.5
MIN_MARGIN = 0.5
AS_OF = datetime.date(2025, 12, 28)
VERSION = "test-1"


def _load(directory: Path) -> Any:
    return normaliser.load(directory)


def _history(directory: Path) -> tuple[Any, list[Any], datetime.date, Any]:
    """The normaliser, the index rows dated before the novel row, and its date."""
    norm = _load(directory)
    corpus = corpus_builder.build_corpus(0)
    novel = next(
        row for row in corpus.rows if row.raw_memo.startswith(corpus_builder.NOVEL_MERCHANT)
    )
    rows = [
        row for row in classifier.index_rows(corpus, norm) if row.post_date < novel.post_date
    ]
    return norm, rows, novel.post_date, novel


def _fixture_index(directory: Path) -> tuple[Any, Any, datetime.date, Any]:
    norm, rows, as_of, novel = _history(directory)
    index = classifier.KnnIndex.build(rows, max_distance=MAX_DISTANCE, min_margin=MIN_MARGIN)
    return norm, index, as_of, novel


def _row(
    token: str,
    destination: tuple[str, ...],
    *,
    days_before: int = 0,
    source: tuple[str, ...] = GIROKONTO,
    sign: str = "out",
    provenance: str = "observed",
    version: str = VERSION,
) -> Any:
    return classifier.IndexRow(
        token=token,
        source_account=source,
        sign=sign,  # type: ignore[arg-type]
        destination_account=destination,
        post_date=AS_OF - datetime.timedelta(days=days_before),
        provenance=provenance,  # type: ignore[arg-type]
        normaliser_version=version,
    )


def _build(rows: list[Any], **overrides: Any) -> Any:
    options: dict[str, Any] = {"max_distance": MAX_DISTANCE, "min_margin": MIN_MARGIN}
    options.update(overrides)
    return classifier.KnnIndex.build(rows, **options)


def _query(index: Any, token: str, **overrides: Any) -> Any:
    options: dict[str, Any] = {"as_of": AS_OF, "normaliser_version": VERSION}
    options.update(overrides)
    return index.query(
        token, options.pop("source", GIROKONTO), options.pop("sign", "out"), **options
    )


# --- (a), (b): the fixture history -------------------------------------------------


def test_known_merchant_with_card_noise_is_accepted(tmp_path: Path) -> None:
    norm, index, as_of, _ = _fixture_index(tmp_path)
    memo = norm.normalise("BEISPIELMARKT KARTE 40711 17.12. SAGT DANKE 5521", GIROKONTO)

    result = index.query(
        memo.token, GIROKONTO, "out", as_of=as_of, normaliser_version=norm.version
    )

    assert result.accepted
    assert result.failed_gates == frozenset()
    assert result.account == LEBENSMITTEL
    assert result.candidate == LEBENSMITTEL
    assert result.nearest_distance == pytest.approx(0, abs=1e-6)
    assert result.margin == pytest.approx(1)


def test_novel_merchant_abstains_on_distance(tmp_path: Path) -> None:
    norm, index, as_of, novel = _fixture_index(tmp_path)
    memo = norm.normalise(novel.raw_memo, GIROKONTO)

    result = index.query(
        memo.token, GIROKONTO, "out", as_of=as_of, normaliser_version=norm.version
    )

    assert not result.accepted
    assert result.account is None
    assert "distance" in result.failed_gates
    assert result.nearest_distance is not None
    assert result.nearest_distance > MAX_DISTANCE


def test_index_rows_are_observed_and_carry_the_normaliser_version(tmp_path: Path) -> None:
    norm, rows, _, _ = _history(tmp_path)

    assert rows
    assert {row.provenance for row in rows} == {"observed"}
    assert {row.normaliser_version for row in rows} == {norm.version}


# --- (c): a split vote -------------------------------------------------------------


def test_split_vote_abstains_on_margin_only() -> None:
    rows = [_row("NEUBAU DROGERIE", LEBENSMITTEL, days_before=day) for day in (5, 40, 90)]
    rows += [_row("NEUBAU DROGERIE", MIETE, days_before=day) for day in (5, 40, 90)]
    index = _build(rows)

    result = _query(index, "NEUBAU DROGERIE")

    assert result.failed_gates == frozenset({"margin"})
    assert result.account is None
    assert result.margin == pytest.approx(0)
    assert result.share == pytest.approx(0.5)
    assert result.nearest_distance == pytest.approx(0, abs=1e-6)


def test_exact_tie_names_the_smaller_path_as_candidate() -> None:
    rows = [_row("NEUBAU DROGERIE", MIETE), _row("NEUBAU DROGERIE", LEBENSMITTEL)]

    result = _query(_build(rows), "NEUBAU DROGERIE")

    assert result.candidate == LEBENSMITTEL
    assert result.account is None


# --- (d): provenance is refused at two points --------------------------------------


def test_synthetic_provenance_is_refused_by_the_row_constructor() -> None:
    with pytest.raises(classifier.KnnError):
        _row("BEISPIELMARKT", LEBENSMITTEL, provenance="synthetic")


def test_synthetic_provenance_is_refused_by_build() -> None:
    good = _row("BEISPIELMARKT", LEBENSMITTEL)
    smuggled = _row("MUSTERBAECKEREI", LEBENSMITTEL)
    object.__setattr__(smuggled, "provenance", "synthetic")

    with pytest.raises(classifier.KnnError):
        _build([good, smuggled])


def test_a_subclass_cannot_switch_off_the_build_check() -> None:
    # Skips the constructor check and offers a do-nothing validator in case `build`
    # looks one up on the row.
    class Lenient(classifier.IndexRow):
        def __post_init__(self) -> None:
            pass

        def _validate(self) -> None:
            pass

    fields = dataclasses.asdict(_row("MUSTERBAECKEREI", LEBENSMITTEL))
    smuggled = Lenient(**{**fields, "provenance": "synthetic"})
    assert dataclasses.asdict(smuggled)["provenance"] == "synthetic"

    with pytest.raises(classifier.KnnError):
        _build([_row("BEISPIELMARKT", LEBENSMITTEL), smuggled])


class _Chameleon(str):
    """A string that compares equal to everything: reads "synthetic", passes `in`."""

    def __eq__(self, other: object) -> bool:
        return True

    def __ne__(self, other: object) -> bool:
        return False

    __hash__ = str.__hash__


@pytest.mark.parametrize(
    "provenance",
    [_Chameleon("synthetic"), unittest.mock.ANY],
    ids=["str-subclass", "mock-ANY"],
)
def test_a_provenance_with_its_own_equality_is_refused(provenance: Any) -> None:
    with pytest.raises(classifier.KnnError):
        _row("MUSTERBAECKEREI", LEBENSMITTEL, provenance=provenance)

    smuggled = _row("MUSTERBAECKEREI", LEBENSMITTEL)
    object.__setattr__(smuggled, "provenance", provenance)
    with pytest.raises(classifier.KnnError):
        _build([_row("BEISPIELMARKT", LEBENSMITTEL), smuggled])


def test_other_fields_with_their_own_equality_are_refused() -> None:
    with pytest.raises(classifier.KnnError):
        _row("BEISPIELMARKT", LEBENSMITTEL, sign=_Chameleon("sideways"))
    with pytest.raises(classifier.KnnError):
        _row("BEISPIELMARKT", (_Chameleon("Aufwand"),))
    with pytest.raises(classifier.KnnError):
        _row("BEISPIELMARKT", LEBENSMITTEL, version=_Chameleon("v2"))

    index = _build([_row("BEISPIELMARKT", LEBENSMITTEL)])
    # Compares equal to the index's version, but is not it.
    with pytest.raises(classifier.KnnError):
        _query(index, "BEISPIELMARKT", normaliser_version=_Chameleon("other"))


def test_corrected_rows_are_accepted() -> None:
    index = _build([_row("BEISPIELMARKT", LEBENSMITTEL, provenance="corrected")])

    assert _query(index, "BEISPIELMARKT").account == LEBENSMITTEL


# --- (e): an empty partition -------------------------------------------------------


def test_partition_with_no_rows_abstains_on_distance(tmp_path: Path) -> None:
    norm, index, as_of, _ = _fixture_index(tmp_path)

    result = index.query(
        "TESTHOF GEMUESE",
        REVOLUT,
        "in",
        as_of=as_of,
        normaliser_version=norm.version,
    )

    assert result.failed_gates == frozenset({"distance"})
    assert result.nearest_distance is None
    assert result.account is None
    assert result.candidate is None


def test_a_query_never_sees_another_partition() -> None:
    index = _build([_row("BEISPIELMARKT", LEBENSMITTEL, source=GIROKONTO)])

    other_source = _query(index, "BEISPIELMARKT", source=REVOLUT)
    other_sign = _query(index, "BEISPIELMARKT", sign="in")

    for result in (other_source, other_sign):
        assert result.failed_gates == frozenset({"distance"})
        assert result.nearest_distance is None


def test_empty_token_abstains_on_distance() -> None:
    index = _build([_row("BEISPIELMARKT", LEBENSMITTEL)])

    result = _query(index, "")

    assert result.failed_gates == frozenset({"distance"})
    assert result.nearest_distance is None


def test_index_of_empty_tokens_builds_and_abstains() -> None:
    index = _build([_row("", LEBENSMITTEL)])

    result = _query(index, "BEISPIELMARKT")

    assert result.failed_gates == frozenset({"distance"})


# --- (f): one normaliser version ---------------------------------------------------


def test_build_refuses_two_normaliser_versions() -> None:
    rows = [
        _row("BEISPIELMARKT", LEBENSMITTEL, version="v1"),
        _row("BEISPIELMARKT", LEBENSMITTEL, version="v2"),
    ]

    with pytest.raises(classifier.KnnError):
        _build(rows)


def test_query_refuses_another_normaliser_version() -> None:
    index = _build([_row("BEISPIELMARKT", LEBENSMITTEL)])

    with pytest.raises(classifier.KnnError):
        _query(index, "BEISPIELMARKT", normaliser_version="other")


# --- (g): thresholds ---------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_distance": 1.0},
        {"max_distance": -0.1},
        {"min_margin": 0.0},
        {"min_margin": 1.5},
    ],
)
def test_build_refuses_a_threshold_out_of_range(overrides: dict[str, float]) -> None:
    with pytest.raises(classifier.KnnError):
        _build([_row("BEISPIELMARKT", LEBENSMITTEL)], **overrides)


def test_thresholds_have_no_default() -> None:
    with pytest.raises(TypeError):
        classifier.KnnIndex.build([_row("BEISPIELMARKT", LEBENSMITTEL)])  # type: ignore[call-arg]


@pytest.mark.parametrize("half_life", [0.0, -1.0, float("inf"), float("nan")])
def test_build_refuses_a_half_life_that_is_not_positive_and_finite(half_life: float) -> None:
    with pytest.raises(classifier.KnnError):
        _build([_row("BEISPIELMARKT", LEBENSMITTEL)], half_life_days=half_life)


def test_boundary_thresholds_are_accepted() -> None:
    index = _build([_row("BEISPIELMARKT", LEBENSMITTEL)], max_distance=0.0, min_margin=1.0)

    result = _query(index, "BEISPIELMARKT")

    assert result.accepted
    assert result.account == LEBENSMITTEL


def test_every_exact_token_match_is_at_distance_zero(tmp_path: Path) -> None:
    # scikit-learn can return a few ulps above 0 for identical vectors (seen in this
    # fixture: `MUSTER HAUSVERWALTUNG` against itself). An exact match must still pass
    # the strictest distance gate the validation allows.
    norm, rows, as_of, _ = _history(tmp_path)
    index = classifier.KnnIndex.build(rows, max_distance=0.0, min_margin=MIN_MARGIN)

    keys = {(row.token, row.source_account, row.sign) for row in rows}
    assert len(keys) > 1
    for token, source, sign in sorted(keys):
        result = index.query(token, source, sign, as_of=as_of, normaliser_version=norm.version)

        assert result.nearest_distance is not None, token
        assert "distance" not in result.failed_gates, token


# --- (h): recency ------------------------------------------------------------------


def test_recent_habit_outvotes_an_older_majority() -> None:
    rows = [_row("MUSTER VERMIETER", LEBENSMITTEL, days_before=1500) for _ in range(3)]
    rows += [_row("MUSTER VERMIETER", MIETE, days_before=10) for _ in range(2)]

    result = _query(_build(rows), "MUSTER VERMIETER")

    assert result.candidate == MIETE
    assert result.share is not None
    assert result.share > 0.5


def test_a_very_long_half_life_restores_the_count() -> None:
    rows = [_row("MUSTER VERMIETER", LEBENSMITTEL, days_before=1500) for _ in range(3)]
    rows += [_row("MUSTER VERMIETER", MIETE, days_before=10) for _ in range(2)]

    result = _query(_build(rows, half_life_days=1e9), "MUSTER VERMIETER")

    assert result.candidate == LEBENSMITTEL


# --- (i): exclude ------------------------------------------------------------------


def test_exclude_leaves_out_exactly_one_equal_row() -> None:
    repeated = _row("MUSTER VERMIETER", LEBENSMITTEL)
    other = _row("MUSTER VERMIETER", MIETE)
    index = _build([repeated, repeated, other])

    result = _query(index, "MUSTER VERMIETER", exclude=repeated)

    assert result.margin == pytest.approx(0)
    assert result.failed_gates == frozenset({"margin"})


def test_exclude_of_the_only_row_leaves_nothing_near() -> None:
    only = _row("MUSTER VERMIETER", LEBENSMITTEL)
    index = _build([only])

    result = _query(index, "MUSTER VERMIETER", exclude=only)

    assert result.nearest_distance is None
    assert result.failed_gates == frozenset({"distance"})


def test_exclude_comes_out_before_the_voters_are_chosen() -> None:
    # 15 exact matches fill the vote. With one of them left out, 15 voters means the
    # other 14 plus the nearest row booked elsewhere, so the margin drops below 1.
    rows = [_row("BEISPIELMARKT", LEBENSMITTEL) for _ in range(15)]
    rows.append(_row("BEISPIELMARKT FILIALE", MIETE))
    index = _build(rows)

    whole = _query(index, "BEISPIELMARKT")
    left_out = _query(index, "BEISPIELMARKT", exclude=rows[0])

    assert whole.margin == pytest.approx(1)
    assert left_out.margin == pytest.approx(0.9430, abs=1e-3)


def test_exclude_that_matches_no_row_is_an_error() -> None:
    # A leave-one-out that silently left nothing out would score the row against itself.
    repeated = _row("MUSTER VERMIETER", LEBENSMITTEL)
    index = _build([repeated, repeated, _row("MUSTER VERMIETER", MIETE)])
    absent = _row("PERSOENLICHER EMPFAENGER", MIETE)

    with pytest.raises(classifier.KnnError, match="exclude") as caught:
        _query(index, "MUSTER VERMIETER", exclude=absent)

    assert "PERSOENLICHER" not in str(caught.value)
    assert "VERMIETER" not in str(caught.value)


def test_exclude_from_another_partition_is_an_error() -> None:
    outgoing = _row("MUSTER VERMIETER", LEBENSMITTEL)
    incoming = _row("MUSTER VERMIETER", LEBENSMITTEL, sign="in")
    index = _build([outgoing, incoming])

    with pytest.raises(classifier.KnnError, match="exclude"):
        _query(index, "MUSTER VERMIETER", exclude=incoming)


def test_exclude_is_checked_before_any_result_is_returned() -> None:
    index = _build([_row("MUSTER VERMIETER", LEBENSMITTEL)])
    absent = _row("BEISPIELMARKT", MIETE)

    # An empty token and an empty partition each have a result of their own.
    with pytest.raises(classifier.KnnError, match="exclude"):
        _query(index, "", exclude=absent)
    with pytest.raises(classifier.KnnError, match="exclude"):
        _query(index, "MUSTER VERMIETER", source=REVOLUT, exclude=absent)


@pytest.mark.parametrize(
    ("field", "value"),
    [("provenance", unittest.mock.ANY), ("source_account", ["Aktiva", "Girokonto"])],
    ids=["mock-ANY", "list-path"],
)
def test_an_exclude_with_a_tampered_field_is_refused(field: str, value: Any) -> None:
    # `mock.ANY` compares equal to every row's provenance; a list cannot be hashed.
    index = _build([_row("MUSTER VERMIETER", LEBENSMITTEL), _row("MUSTER VERMIETER", MIETE)])
    tampered = _row("MUSTER VERMIETER", LEBENSMITTEL)
    object.__setattr__(tampered, field, value)

    with pytest.raises(classifier.KnnError):
        _query(index, "MUSTER VERMIETER", exclude=tampered)


# --- (j): recency reaches every row tied for a place in the vote -------------------


def _tied_rows() -> list[Any]:
    """20 old rows for one account and 5 recent ones for another, one token, oldest first.

    Oldest first is the order `build_corpus` and a book export produce.
    """
    old = [_row("MUSTER VERMIETER", LEBENSMITTEL, days_before=1500 + 30 * i) for i in range(20)]
    recent = [_row("MUSTER VERMIETER", MIETE, days_before=10 + 30 * i) for i in range(5)]
    return sorted([*old, *recent], key=lambda row: row.post_date)


def test_every_row_tied_with_the_kth_distance_votes() -> None:
    # All 25 rows tie at distance 0. Cut to 15 in input order, the vote would hold only
    # the oldest rows and accept the stale account with margin 1.
    result = _query(_build(_tied_rows()), "MUSTER VERMIETER")

    assert result.candidate == MIETE
    assert result.margin == pytest.approx(0.3630, abs=1e-3)
    assert result.failed_gates == frozenset({"margin"})


@pytest.mark.parametrize("order", ["newest-first", "shuffled"])
def test_the_vote_does_not_depend_on_the_order_of_the_rows(order: str) -> None:
    rows = _tied_rows()
    if order == "newest-first":
        reordered = rows[::-1]
    else:
        reordered = list(rows)
        random.Random(24).shuffle(reordered)  # noqa: S311  # test data, not a security context
    assert reordered != rows

    expected = _query(_build(rows), "MUSTER VERMIETER")
    result = _query(_build(reordered), "MUSTER VERMIETER")

    assert result.candidate == expected.candidate
    assert result.failed_gates == expected.failed_gates
    assert result.margin == pytest.approx(expected.margin)
    assert result.share == pytest.approx(expected.share)


# --- (k): text history never contained counts toward the distance ------------------


def test_ngrams_no_row_contains_move_the_query_away_from_history() -> None:
    index = _build([_row("BEISPIELMARKT", LEBENSMITTEL)], max_distance=0.3, min_margin=0.5)

    known = _query(index, "BEISPIELMARKT")
    one_new_word = _query(index, "BEISPIELMARKT QXZV")
    two_new_words = _query(index, "BEISPIELMARKT QXZV WJKQ")

    assert known.accepted
    assert known.nearest_distance == pytest.approx(0)
    assert one_new_word.accepted
    assert one_new_word.nearest_distance == pytest.approx(0.2368, abs=1e-3)
    assert two_new_words.nearest_distance == pytest.approx(0.3589, abs=1e-3)
    assert two_new_words.account is None
    assert two_new_words.failed_gates == frozenset({"distance"})


def test_a_query_history_never_contained_is_at_distance_one() -> None:
    index = _build([_row("BEISPIELMARKT", LEBENSMITTEL)], max_distance=0.3, min_margin=0.5)

    result = _query(index, "QXZV WJKQ")

    assert result.nearest_distance == 1.0
    assert result.account is None
    assert "distance" in result.failed_gates


# --- (l): index_rows carries provenance through ------------------------------------


def test_index_rows_copies_provenance_from_the_corpus(tmp_path: Path) -> None:
    norm = _load(tmp_path)
    corpus = corpus_builder.build_corpus(0)
    object.__setattr__(corpus.rows[0], "provenance", "synthetic")

    with pytest.raises(classifier.KnnError, match="provenance"):
        classifier.index_rows(corpus, norm)


# --- (m): exclude takes its row out of the query's idf too -------------------------


def test_exclude_takes_its_row_out_of_the_query_idf() -> None:
    kept = _row("BEISPIELMARKT", LEBENSMITTEL)
    excluded = _row("QXZV WJKQ", MIETE)
    index = _build([kept, excluded], max_distance=0.3, min_margin=0.5)
    alone = _build([kept], max_distance=0.3, min_margin=0.5)

    with_it = _query(index, "BEISPIELMARKT QXZV")
    without_it = _query(index, "BEISPIELMARKT QXZV", exclude=excluded)

    # With the excluded row in history, QXZV is a word history contains.
    assert with_it.nearest_distance == pytest.approx(0.1056, abs=1e-3)
    # Without it, QXZV is as new as in an index that never held the row: (k)'s value.
    assert without_it.nearest_distance == pytest.approx(0.2368, abs=1e-3)
    assert without_it.nearest_distance == pytest.approx(
        _query(alone, "BEISPIELMARKT QXZV").nearest_distance
    )
    assert without_it.account == LEBENSMITTEL
    assert without_it.failed_gates == frozenset()


def test_exclude_lowers_the_df_of_ngrams_it_shares_with_other_rows() -> None:
    # The n-grams of BEISPIEL are in all three rows, the rest of BEISPIELMARKT's in the
    # two BEISPIELMARKT rows. Leaving one of those out lowers the counts to two and one;
    # it does not make its n-grams unseen (that rule gives 0.00781 and margin 0.4107).
    excluded = _row("BEISPIELMARKT", LEBENSMITTEL)
    index = _build(
        [excluded, _row("BEISPIELMARKT", LEBENSMITTEL), _row("BEISPIEL GMBH", MIETE)]
    )

    whole = _query(index, "BEISPIELMARKT")
    left_out = _query(index, "BEISPIELMARKT", exclude=excluded)

    assert whole.nearest_distance == 0.0
    # The other BEISPIELMARKT row keeps the idf fitted with the excluded row in, so the
    # query's weights are no longer proportional to its own: it is a little above 0.
    assert left_out.nearest_distance == pytest.approx(0.000877, rel=1e-2)
    # Both rows vote, so the margin carries the distance to BEISPIEL GMBH, 0.6602.
    assert left_out.margin == pytest.approx(0.4924, abs=1e-3)
    assert left_out.candidate == LEBENSMITTEL


# --- malformed input ---------------------------------------------------------------


def test_malformed_rows_are_refused() -> None:
    with pytest.raises(classifier.KnnError):
        _row("BEISPIELMARKT", ())
    with pytest.raises(classifier.KnnError):
        _row("BEISPIELMARKT", LEBENSMITTEL, sign="sideways")
    with pytest.raises(classifier.KnnError):
        _row("BEISPIELMARKT", LEBENSMITTEL, version="")
    with pytest.raises(classifier.KnnError):
        _build(["not a row"])


def test_a_refused_row_message_does_not_carry_the_token() -> None:
    with pytest.raises(classifier.KnnError) as caught:
        _row("PERSOENLICHER EMPFAENGER", LEBENSMITTEL, provenance="synthetic")

    assert "PERSOENLICHER" not in str(caught.value)


def test_the_result_holds_one_account_path_and_no_split_type_exists() -> None:
    # Splits are rules-tier only: the result has one `account` field holding one path,
    # and the module exports nothing else that could carry a split.
    hints = typing.get_type_hints(classifier.KnnResult)
    assert [field.name for field in dataclasses.fields(classifier.KnnResult)] == [
        "account",
        "candidate",
        "nearest_distance",
        "margin",
        "share",
        "failed_gates",
    ]
    assert hints["account"] == tuple[str, ...] | None
    assert set(classifier.__all__) == {
        "HALF_LIFE_DAYS",
        "IndexRow",
        "KnnError",
        "KnnIndex",
        "KnnResult",
        "classify",
        "index_rows",
    }

    result = _query(_build([_row("BEISPIELMARKT", LEBENSMITTEL)]), "BEISPIELMARKT")

    assert result.account == LEBENSMITTEL
    assert all(isinstance(part, str) for part in result.account)


def test_the_cascade_entry_point_is_still_the_stub() -> None:
    with pytest.raises(NotImplementedError):
        classifier.classify()

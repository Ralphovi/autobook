"""The rolling-origin backtest (ch.5 5.2 *Trial tooling*, ch.6 6.6).

Every memo, merchant and account here is invented (`tests/fixtures/synthetic`). The
thresholds are test inputs, not a recommendation: real ones come from a human reading
the report.

Only modules that exist without this change are imported at module scope. Every name
the change adds is reached through the module object inside a test body, so with the
change reverted each test runs and fails instead of the file failing to import.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

import pytest

from autobook import contracts
from autobook.pipeline import normaliser, trial
from tests.fixtures.synthetic import corpus_builder

GIROKONTO = corpus_builder.GIROKONTO
REVOLUT = corpus_builder.REVOLUT
LEBENSMITTEL = corpus_builder.LEBENSMITTEL
MIETE = corpus_builder.MIETE
GEHALT = corpus_builder.GEHALT

MAX_DISTANCE = 0.5
MIN_MARGIN = 0.5

METHODS = ("knn", "token_bayes")
BAND_LABELS = ["[0,0.5)", "[0.5,0.7)", "[0.7,0.9)", "[0.9,1]"]


def _norm(tmp_path: Path) -> Any:
    empty = tmp_path / "normaliser"
    empty.mkdir(exist_ok=True)
    return normaliser.load(empty)


def _row(
    memo: str,
    destination: tuple[str, ...],
    *date: int,
    source: tuple[str, ...] = GIROKONTO,
    sign: contracts.Sign = "out",
) -> Any:
    return contracts.CorpusRow(
        raw_memo=memo,
        amount_cents=1000,
        sign=sign,
        source_account=source,
        destination_account=destination,
        post_date=datetime.date(*date),
    )


def _corpus(*rows: Any) -> Any:
    return contracts.CorpusContract(rows=tuple(rows))


def _january() -> list[Any]:
    return [_row("ALPHA", LEBENSMITTEL, 2025, 1, d) for d in (3, 10, 17)] + [
        _row("BRAVO", MIETE, 2025, 1, d) for d in (4, 11, 18)
    ]


def _planted() -> Any:
    return _corpus(
        *_january(),
        _row("ALPHA 123", LEBENSMITTEL, 2025, 2, 5),
        _row("BRAVO REF 9", LEBENSMITTEL, 2025, 2, 12),
        _row("ZULU KIOSK", LEBENSMITTEL, 2025, 2, 19),
    )


def _run(
    corpus: Any,
    tmp_path: Path,
    *,
    max_distance: float = MAX_DISTANCE,
    min_margin: float = MIN_MARGIN,
) -> dict[str, Any]:
    return trial.backtest(
        corpus, _norm(tmp_path), max_distance=max_distance, min_margin=min_margin
    )


def _stratum(report: dict[str, Any], method: str, stratum: str) -> dict[str, Any]:
    result: dict[str, Any] = report["methods"][method]["strata"][stratum]
    return result


def _counts(entry: dict[str, Any]) -> tuple[int, int, int]:
    return (entry["rows"], entry["accepted"], entry["correct"])


def _band_accepted(report: dict[str, Any], method: str) -> dict[str, tuple[int, int]]:
    """``(accepted, correct)`` of every band that holds an accepted row."""
    bands = report["methods"][method]["bands"]
    return {
        label: (band["accepted"], band["correct"])
        for label, band in bands.items()
        if band["accepted"]
    }


def _cli(source: Path, out: Path, normaliser_dir: Path) -> int:
    return trial.main(
        [
            "backtest",
            "--corpus",
            str(source),
            "--out",
            str(out),
            "--max-distance",
            "0.5",
            "--min-margin",
            "0.5",
            "--normaliser-dir",
            str(normaliser_dir),
        ]
    )


def test_planted_corpus_numbers(tmp_path: Path) -> None:
    report = _run(_planted(), tmp_path)

    assert report["months"]["tested"] == 1
    assert (report["months"]["first"], report["months"]["last"]) == ("2025-01", "2025-02")
    seen = _stratum(report, "knn", "seen")
    assert _counts(seen) == (2, 2, 1)
    assert seen["precision"] == 0.5
    assert seen["coverage"] == 1.0
    novel = _stratum(report, "knn", "novel")
    assert _counts(novel) == (1, 0, 0)
    assert novel["precision"] is None
    assert novel["coverage"] == 0.0
    assert _stratum(report, "token_bayes", "all")["rows"] == 3


def test_a_future_row_never_votes_for_a_past_one(tmp_path: Path) -> None:
    before = _run(_planted(), tmp_path)
    march = [_row("ALPHA", MIETE, 2025, 3, d) for d in (3, 6, 9, 12, 15)]
    after = _run(_corpus(*_planted().rows, *march), tmp_path)

    february_before = before["months"]["by_month"]["2025-02"]
    february_after = after["months"]["by_month"]["2025-02"]
    for method in METHODS:
        assert february_after[method] == february_before[method]
    assert after["months"]["tested"] == 2


def test_novel_stratum_of_the_synthetic_corpus_is_the_planted_merchant(tmp_path: Path) -> None:
    for seed in (0, 1, 2):
        report = _run(corpus_builder.build_corpus(seed), tmp_path)
        novel = _stratum(report, "knn", "novel")
        assert novel["rows"] == 1, seed
        assert novel["accepted"] == 0, seed


def test_the_month_boundary_bounds_the_past_not_the_row_date(tmp_path: Path) -> None:
    corpus = _corpus(
        *[_row("ALPHA", LEBENSMITTEL, 2025, 1, d) for d in (3, 10, 17)],
        _row("CHARLIE", MIETE, 2025, 2, 1),
        _row("CHARLIE", MIETE, 2025, 2, 20),
    )
    report = _run(corpus, tmp_path)

    novel = _stratum(report, "knn", "novel")
    assert (novel["rows"], novel["accepted"]) == (2, 0)
    assert _stratum(report, "knn", "seen")["rows"] == 0
    bayes = _stratum(report, "token_bayes", "all")
    assert (bayes["accepted"], bayes["correct"]) == (2, 0)


def test_a_calendar_month_without_rows_is_listed_with_zero_counts(tmp_path: Path) -> None:
    corpus = _corpus(
        *[_row("ALPHA", LEBENSMITTEL, 2025, 1, d) for d in (3, 10, 17)],
        _row("ALPHA", LEBENSMITTEL, 2025, 3, 5),
    )
    months = _run(corpus, tmp_path)["months"]

    # Every calendar month from the first to the last is tested, February too, though
    # it holds no row.
    assert (months["first"], months["last"], months["tested"]) == ("2025-01", "2025-03", 2)
    zero = {"rows": 0, "accepted": 0, "correct": 0}
    assert months["by_month"]["2025-02"] == {"knn": zero, "token_bayes": zero}
    # The empty month does not cut the history: March is still classified on January.
    one = {"rows": 1, "accepted": 1, "correct": 1}
    assert months["by_month"]["2025-03"] == {"knn": one, "token_bayes": one}

    # Two empty months across a year end, listed in calendar order.
    corpus = _corpus(
        _row("ALPHA", LEBENSMITTEL, 2024, 11, 5),
        _row("ALPHA", LEBENSMITTEL, 2025, 2, 5),
    )
    months = _run(corpus, tmp_path)["months"]
    assert list(months["by_month"]) == ["2024-12", "2025-01", "2025-02"]
    assert months["tested"] == 3


def test_cli_writes_a_report_without_identifying_data(tmp_path: Path) -> None:
    source = tmp_path / "corpus.json"
    corpus = corpus_builder.build_corpus(0)
    source.write_text(contracts.corpus_to_json(corpus), encoding="utf-8")
    empty = tmp_path / "empty"
    empty.mkdir()
    out = tmp_path / "report.json"

    assert _cli(source, out, empty) == 0

    text = out.read_text(encoding="utf-8")
    report = json.loads(text)
    assert report["report"] == "backtest"
    assert report["report_version"] == trial.REPORT_VERSION
    lowered = text.lower()
    names = {m.token for m in corpus_builder.MERCHANTS} | {corpus_builder.NOVEL_MERCHANT}
    for merchant in names:
        assert merchant.lower() not in lowered
    for path in (GIROKONTO, REVOLUT, LEBENSMITTEL, MIETE, GEHALT):
        for part in path:
            assert part.lower() not in lowered
    # Only month labels carry a date: no day, no ISO date.
    assert "2025-01-" not in text


def test_cli_refuses_a_file_that_is_not_a_corpus(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    out = tmp_path / "report.json"
    for content in ('{"contract": "coa", "version": 1, "accounts": []}', "not json"):
        source = tmp_path / "bad.json"
        source.write_text(content, encoding="utf-8")
        assert _cli(source, out, empty) != 0
        assert not out.exists()
    assert _cli(tmp_path / "missing.json", out, empty) != 0
    assert not out.exists()


def test_cli_refusals_name_the_field_never_the_value(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    out = tmp_path / "report.json"
    valid = json.loads(contracts.corpus_to_json(_planted()))
    # Each bad row quotes something identifying in the contract's own error text.
    cases = {
        "amount_cents": -4711,
        "post_date": "2025-02-30",
        "sign": "ZULU KIOSK",
    }
    for field, value in cases.items():
        document = json.loads(json.dumps(valid))
        document["rows"][1][field] = value
        source = tmp_path / f"{field}.json"
        source.write_text(json.dumps(document), encoding="utf-8")

        assert _cli(source, out, empty) == 2
        assert not out.exists()
        err = capsys.readouterr().err
        assert err.count("\n") == 1, err
        assert f"corpus.rows[1].{field}" in err
        assert str(value).lower() not in err.lower()
        assert "4711" not in err

    # A field name read from the file is not a field path of the contract: dropped.
    document = json.loads(json.dumps(valid))
    document["rows"][0]["ZULU KIOSK"] = 1
    source = tmp_path / "unknown.json"
    source.write_text(json.dumps(document), encoding="utf-8")
    assert _cli(source, out, empty) == 2
    err = capsys.readouterr().err
    assert "ContractError at corpus.rows[0]" in err
    assert "zulu" not in err.lower()

    # A normaliser error quotes the profile path and pattern: neither is passed on.
    profiles = tmp_path / "ALPHA-profiles"
    profiles.mkdir()
    (profiles / "default.toml").write_text('[[rules]]\npattern = "ALPHA("\n', encoding="utf-8")
    source = tmp_path / "corpus.json"
    source.write_text(contracts.corpus_to_json(_planted()), encoding="utf-8")
    assert _cli(source, out, profiles) == 2
    assert not out.exists()
    err = capsys.readouterr().err
    assert "NormaliserError" in err
    assert "alpha" not in err.lower()


def test_a_relative_profile_path_never_reaches_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A relative user directory with no slash reads like a field name. Here it is a
    # file, so the normaliser refuses it, and its error starts with that path.
    monkeypatch.chdir(tmp_path)
    Path("PRIVATE_PROFILE").write_text("", encoding="utf-8")
    source = tmp_path / "corpus.json"
    source.write_text(contracts.corpus_to_json(_planted()), encoding="utf-8")
    out = tmp_path / "report.json"

    assert _cli(source, out, Path("PRIVATE_PROFILE")) == 2
    assert not out.exists()
    err = capsys.readouterr().err
    assert err == "error: the normaliser profiles were refused (NormaliserError)\n"

    # A refused threshold is still named: that name comes from the code, not the data.
    empty = tmp_path / "empty"
    empty.mkdir()
    argv = ["backtest", "--corpus", str(source), "--out", str(out)]
    argv += ["--max-distance", "1.5", "--min-margin", "0.5", "--normaliser-dir", str(empty)]
    assert trial.main(argv) == 2
    assert not out.exists()
    err = capsys.readouterr().err
    assert err == (
        "error: the kNN index refused the thresholds or a row (KnnError at max_distance)\n"
    )


def test_a_history_of_blank_tokens_still_gives_a_report(tmp_path: Path) -> None:
    # "12345" normalises to a blank token: the partition has a row but no word.
    corpus = _corpus(
        _row("12345", MIETE, 2025, 1, 6),
        _row("ALPHA", MIETE, 2025, 2, 6),
    )
    report = _run(corpus, tmp_path)

    # Token-Bayes has no word evidence, so the prior decides: MIETE, the only class.
    assert _counts(_stratum(report, "token_bayes", "all")) == (1, 1, 1)
    assert _band_accepted(report, "token_bayes") == {"[0.9,1]": (1, 1)}
    # A blank history has no n-gram to be near: kNN abstains.
    assert _counts(_stratum(report, "knn", "novel")) == (1, 0, 0)

    source = tmp_path / "corpus.json"
    source.write_text(contracts.corpus_to_json(corpus), encoding="utf-8")
    out = tmp_path / "report.json"
    assert _cli(source, out, tmp_path / "normaliser") == 0
    assert json.loads(out.read_text(encoding="utf-8")) == report


def test_token_bayes_priors_decide_a_token_with_no_known_word(tmp_path: Path) -> None:
    corpus = _corpus(
        *[_row("ALPHA", MIETE, 2025, 1, d) for d in (3, 10, 17)],
        _row("BRAVO", LEBENSMITTEL, 2025, 1, 24),
        _row("CHARLIE", MIETE, 2025, 2, 6),
    )
    report = _run(corpus, tmp_path)

    # Priors 3/4 against 1/4: MIETE with confidence 0.75. Without the priors it would
    # be a tie, going to the smaller path (LEBENSMITTEL) at 0.5.
    assert _band_accepted(report, "token_bayes") == {"[0.7,0.9)": (1, 1)}


def test_token_bayes_smooths_over_the_partition_vocabulary(tmp_path: Path) -> None:
    corpus = _corpus(
        _row("ALPHA", LEBENSMITTEL, 2025, 1, 3),
        _row("BRAVO CHARLIE DELTA ECHO FOXTROT", MIETE, 2025, 1, 10),
        _row("ALPHA", LEBENSMITTEL, 2025, 2, 6),
    )
    report = _run(corpus, tmp_path)

    # Vocabulary 6, equal priors: LEBENSMITTEL (1 + 1) / (1 + 6), MIETE 1 / (5 + 6),
    # posterior 22 / 29 = 0.76. Without the vocabulary in the denominator: 2 against
    # 1 / 5, posterior 0.91, the band above.
    assert _band_accepted(report, "token_bayes") == {"[0.7,0.9)": (1, 1)}


def test_seen_is_decided_within_the_source_account_and_sign(tmp_path: Path) -> None:
    corpus = _corpus(
        *[_row("ALPHA", LEBENSMITTEL, 2025, 1, d) for d in (3, 10, 17)],
        _row("ALPHA", LEBENSMITTEL, 2025, 2, 5),
        _row("ALPHA", LEBENSMITTEL, 2025, 2, 6, source=REVOLUT),
        _row("ALPHA", GEHALT, 2025, 2, 7, sign="in"),
    )
    report = _run(corpus, tmp_path)

    assert _counts(_stratum(report, "knn", "seen")) == (1, 1, 1)
    # The same token in another partition is novel there: nothing to vote with.
    assert _counts(_stratum(report, "knn", "novel")) == (2, 0, 0)
    # Token-Bayes abstains only on an empty partition.
    assert _counts(_stratum(report, "token_bayes", "seen")) == (1, 1, 1)
    assert _counts(_stratum(report, "token_bayes", "novel")) == (2, 0, 0)


def test_leave_one_out_is_reported_only_as_an_upper_bound(tmp_path: Path) -> None:
    report = _run(_planted(), tmp_path)

    assert set(report["methods"]) == set(METHODS)
    strata = report["upper_bound"]["knn_leave_one_out"]["strata"]
    # Every row is scored, the first month included. "Seen" means another row of the
    # partition has the token: ALPHA and BRAVO four times each, ZULU KIOSK once.
    assert strata["all"]["rows"] == 9
    assert strata["seen"]["rows"] == 8
    assert _counts(strata["novel"]) == (1, 0, 0)
    assert all("leave" not in key for key in report["methods"])
    assert all("leave" not in key for key in report["novel_sweep"][0])


def test_band_records_carry_every_count(tmp_path: Path) -> None:
    report = _run(corpus_builder.build_corpus(0), tmp_path)

    assert report["bands"] == BAND_LABELS
    for method in METHODS:
        bands = report["methods"][method]["bands"]
        assert list(bands) == BAND_LABELS
        everything = _stratum(report, method, "all")
        assert everything["accepted"] > 0
        assert sum(band["accepted"] for band in bands.values()) == everything["accepted"]
        assert sum(band["correct"] for band in bands.values()) == everything["correct"]
        for band in bands.values():
            # `rows` is every tested row: the denominator of the band's coverage.
            assert band["rows"] == everything["rows"]
            assert band["coverage"] == band["accepted"] / band["rows"]
            if band["accepted"]:
                assert band["precision"] == band["correct"] / band["accepted"]
            else:
                assert band["precision"] is None


def test_sweep_re_applies_both_gates_to_the_novel_stratum(tmp_path: Path) -> None:
    corpus = _corpus(
        *[_row("ALPHA MARKT", LEBENSMITTEL, 2025, 1, d) for d in (3, 10, 17)],
        *[_row("BRAVO HAUS", MIETE, 2025, 1, d) for d in (4, 11, 18)],
        # Seen: never in the sweep.
        _row("ALPHA MARKT", LEBENSMITTEL, 2025, 2, 3),
        # Novel near-matches, with their distance and margin to the January rows:
        # nearest ALPHA MARKT (0.48, margin 1), candidate right;
        _row("ALPHA MARKET", LEBENSMITTEL, 2025, 2, 5),
        # nearest BRAVO HAUS (0.37, margin 1), candidate MIETE, wrong;
        _row("BRAVO HAUSE", LEBENSMITTEL, 2025, 2, 12),
        # between both (0.47, margin 0.11), candidate LEBENSMITTEL, wrong.
        _row("MARKT HAUS", MIETE, 2025, 2, 19),
    )
    # The run's own gates accept no novel row, so every sweep acceptance below comes
    # from re-applying the gates, and its `correct` from the vote's candidate.
    report = _run(corpus, tmp_path, max_distance=0.2, min_margin=0.5)
    assert _counts(_stratum(report, "knn", "novel")) == (3, 0, 0)

    sweep = report["novel_sweep"]
    assert len(sweep) == len(trial.SWEEP_DISTANCES) * len(trial.SWEEP_MARGINS)
    assert {entry["rows"] for entry in sweep} == {3}
    cells = {(e["max_distance"], e["min_margin"]): e for e in sweep}
    expected = {
        (0.3, 0.1): (0, 0),
        (0.4, 0.5): (1, 0),
        (0.5, 0.5): (2, 1),
        (0.5, 0.2): (2, 1),
        (0.5, 0.1): (3, 1),
        # A unanimous vote has a margin of exactly 1: the margin gate is inclusive.
        (0.5, 1.0): (2, 1),
    }
    for cell, (accepted, correct) in expected.items():
        entry = cells[cell]
        assert (entry["accepted"], entry["correct"]) == (accepted, correct), cell
    assert cells[(0.5, 0.5)]["precision"] == 0.5
    assert cells[(0.5, 0.5)]["coverage"] == 2 / 3


def test_sweep_gates_are_inclusive_at_both_edges() -> None:
    # Real distances seldom land on a grid value, so the edges are pinned on stored
    # outcomes fed to the sweep itself: one at exactly (0.5, 1.0), one just outside.
    def outcome(distance: float, margin: float) -> Any:
        return trial._Outcome(
            seen=False,
            accepted=False,
            correct=False,
            confidence=None,
            nearest_distance=distance,
            margin=margin,
            candidate_correct=True,
        )

    on_edge = outcome(0.5, 1.0)
    outside = outcome(0.5000001, 0.9999999)
    cells = {(e["max_distance"], e["min_margin"]): e for e in trial._sweep([on_edge, outside])}

    assert _counts(cells[(0.5, 1.0)]) == (2, 1, 1)
    assert _counts(cells[(0.6, 0.9)]) == (2, 2, 2)
    assert _counts(cells[(0.4, 0.1)]) == (2, 0, 0)
    # A seen outcome never enters the sweep.
    seen = trial._Outcome(True, False, False, None, 0.0, 1.0, candidate_correct=True)
    assert {e["rows"] for e in trial._sweep([seen])} == {0}


def test_a_confidence_on_a_band_edge_falls_in_the_band_above(tmp_path: Path) -> None:
    corpus = _corpus(
        _row("ALPHA", MIETE, 2025, 1, 3),
        _row("ALPHA", LEBENSMITTEL, 2025, 1, 10),
        _row("ALPHA", LEBENSMITTEL, 2025, 2, 6),
    )
    report = _run(corpus, tmp_path)

    # Equal priors, equal word counts: an exact tie, posterior 0.5, won by the smaller
    # path (LEBENSMITTEL). Bands are [lower, upper), so 0.5 is in [0.5,0.7).
    assert _band_accepted(report, "token_bayes") == {"[0.5,0.7)": (1, 1)}
    # The kNN vote is near a tie (recency alone splits it, margin under 0.01): refused.
    assert _counts(_stratum(report, "knn", "all")) == (1, 0, 0)


def test_recency_is_measured_from_the_test_row_after_its_history(tmp_path: Path) -> None:
    corpus = _corpus(
        # Two old rows to MIETE, about three years before the test row.
        _row("ALPHA", MIETE, 2022, 1, 3),
        _row("ALPHA", MIETE, 2022, 1, 10),
        # One recent row to LEBENSMITTEL, six weeks before it.
        _row("ALPHA", LEBENSMITTEL, 2024, 12, 2),
        _row("ALPHA", LEBENSMITTEL, 2025, 1, 15),
    )
    report = _run(corpus, tmp_path, min_margin=0.2)

    # Weights at distance 0: 2 * 0.5 ** (~1100 / 548) = 0.50 against 0.5 ** (44 / 548)
    # = 0.95, so LEBENSMITTEL wins with share 0.66 and margin 0.31. Ages measured from
    # a date at or before the history would give every row the same weight, and the
    # two old rows would win 2 to 1.
    january = report["months"]["by_month"]["2025-01"]["knn"]
    assert january == {"rows": 1, "accepted": 1, "correct": 1}
    # The December row, with only the two MIETE rows behind it, is accepted and wrong.
    december = report["months"]["by_month"]["2024-12"]["knn"]
    assert december == {"rows": 1, "accepted": 1, "correct": 0}
    assert _band_accepted(report, "knn") == {"[0.5,0.7)": (1, 1), "[0.9,1]": (1, 0)}


def test_leave_one_out_measures_age_from_the_row_itself(tmp_path: Path) -> None:
    # In the rolling origin all history is older than the test row, so moving `as_of`
    # later scales every weight alike and changes no vote. Leave-one-out also has
    # future rows: measured from the row's own date they are age 0, like a same-day row.
    corpus = _corpus(
        _row("ALPHA", LEBENSMITTEL, 2025, 1, 10),
        _row("ALPHA", LEBENSMITTEL, 2025, 1, 10),
        _row("ALPHA", MIETE, 2027, 10, 7),
    )
    report = _run(corpus, tmp_path)

    strata = report["upper_bound"]["knn_leave_one_out"]["strata"]
    # Each January row: the other January row and the 2027 row weigh the same, a tie,
    # refused. The 2027 row: both January rows vote LEBENSMITTEL, accepted and wrong.
    # From a later `as_of`, the 2027 row would outweigh the January one (share 0.78)
    # and both January rows would be accepted as MIETE.
    assert _counts(strata["all"]) == (3, 1, 0)


def test_thresholds_are_refused_even_when_no_month_is_tested(tmp_path: Path) -> None:
    one_month = _corpus(*_january())
    with pytest.raises(ValueError, match="max_distance"):
        trial.backtest(one_month, _norm(tmp_path), max_distance=1.5, min_margin=0.5)

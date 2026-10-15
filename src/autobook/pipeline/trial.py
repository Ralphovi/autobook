"""Trial tooling (scenario 1) — building block of ch.5 section 5.2.

Design: `docs/design/architecture/05-building-block-view.md`.

This module holds the **rolling-origin backtest** and its command line:
``python -m autobook.pipeline.trial backtest --corpus <corpus.json> --out <report.json>
--max-distance <x> --min-margin <y> [--normaliser-dir <dir>]``.

For every calendar month m after the first, the rows dated before the first day of m
are the history, and month m is the test set. Nothing dated in m or later enters m's
index or its token-Bayes counts, so no row's own future votes for it. Results are per
method (the gated kNN of the classifier, and token-Bayes as the negative control), per
confidence band and per stratum (a memo seen before in the history, or novel). Gate
thresholds are chosen on the novel stratum: the report carries a sweep of it. A
leave-one-out number is reported under ``upper_bound`` only, and is never used for
thresholds.

The report holds counts, rates, versions, thresholds and months only: no memo, token,
merchant, account, amount or day (ch.8 section 8.5). It is evidence; thresholds are
set by a human, never by this module.

``run_trial`` is still the stub for the rest of the trial tooling (rule builder,
assistant detector, pack validator, linkage backtest).

Pipeline module: must never import `gnucash`.
"""

from __future__ import annotations

import argparse
import bisect
import datetime
import json
import math
import re
import sys
from collections import Counter
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from autobook.contracts import CORPUS_NAME, ContractError, CorpusContract, corpus_from_json
from autobook.pipeline.classifier import (
    HALF_LIFE_DAYS,
    IndexRow,
    KnnError,
    KnnIndex,
    index_rows,
)
from autobook.pipeline.normaliser import Normaliser, NormaliserError
from autobook.pipeline.normaliser import load as load_normaliser

__all__ = [
    "BANDS",
    "REPORT_VERSION",
    "SWEEP_DISTANCES",
    "SWEEP_MARGINS",
    "backtest",
    "main",
    "run_trial",
]

REPORT_VERSION: Final = 1

# Band edges over confidence: [0, 0.5), [0.5, 0.7), [0.7, 0.9), [0.9, 1].
BANDS: Final[tuple[float, ...]] = (0.5, 0.7, 0.9)

# The novel-stratum sweep grid. Distances must satisfy 0 <= d < 1 and margins
# 0 < m <= 1 (the gate ranges of `KnnIndex.build`); both cover (0, 1).
SWEEP_DISTANCES: Final[tuple[float, ...]] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
SWEEP_MARGINS: Final[tuple[float, ...]] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)

_STRATA: Final = ("seen", "novel", "all")
_EXIT_USAGE: Final = 2

_Account = tuple[str, ...]
_Month = tuple[int, int]
_Partition = tuple[_Account, str]


@dataclass(frozen=True)
class _Outcome:
    """What one method did with one test row. Never leaves this module."""

    seen: bool
    accepted: bool
    correct: bool
    confidence: float | None
    # kNN only, for the threshold sweep, which re-applies the gates to these.
    nearest_distance: float | None = None
    margin: float | None = None
    candidate_correct: bool = False


class _TokenBayes:
    """Multinomial naive Bayes over the words of a token, per ``(source_account, sign)``.

    Laplace smoothing (add one) over the partition's vocabulary, class priors from row
    counts, no recency, log space. A word the partition's history never holds carries no
    evidence and is skipped, so a token made only of such words (or a blank one) is
    decided by the priors. It abstains only when the partition has no rows. Ties go to
    the smaller path tuple.
    """

    def __init__(self, rows: Iterable[IndexRow]) -> None:
        self._class_rows: dict[_Partition, Counter[_Account]] = {}
        self._words: dict[_Partition, dict[_Account, Counter[str]]] = {}
        self._vocabulary: dict[_Partition, set[str]] = {}
        for row in rows:
            key = (row.source_account, row.sign)
            self._class_rows.setdefault(key, Counter())[row.destination_account] += 1
            words = row.token.split()
            by_class = self._words.setdefault(key, {})
            by_class.setdefault(row.destination_account, Counter()).update(words)
            self._vocabulary.setdefault(key, set()).update(words)

    def classify(self, token: str, key: _Partition) -> tuple[_Account, float] | None:
        """The winning account and its normalised posterior, or ``None`` to abstain."""
        class_rows = self._class_rows.get(key)
        if not class_rows:
            return None
        total_rows = sum(class_rows.values())
        known = self._vocabulary[key]
        vocabulary = len(known)
        # Only words the history holds: then `vocabulary >= 1` wherever a denominator
        # is used, even when every history token of the partition is blank.
        words = [word for word in token.split() if word in known]
        scores: dict[_Account, float] = {}
        for account, rows in class_rows.items():
            counts = self._words[key][account]
            denominator = sum(counts.values()) + vocabulary
            score = math.log(rows / total_rows)
            for word in words:
                score += math.log((counts[word] + 1) / denominator)
            scores[account] = score
        # Highest score first; on an exact tie the smaller path tuple.
        winner, best = min(scores.items(), key=lambda item: (-item[1], item[0]))
        log_total = best + math.log(sum(math.exp(score - best) for score in scores.values()))
        return winner, math.exp(best - log_total)


def _month_of(date: datetime.date) -> _Month:
    return (date.year, date.month)


def _label(month: _Month) -> str:
    return f"{month[0]:04d}-{month[1]:02d}"


def _calendar(first: _Month, last: _Month) -> list[_Month]:
    """Every calendar month from ``first`` to ``last``, both included, in order."""
    start = first[0] * 12 + first[1] - 1
    end = last[0] * 12 + last[1] - 1
    return [(count // 12, count % 12 + 1) for count in range(start, end + 1)]


def _band_labels() -> list[str]:
    edges = (0.0, *BANDS, 1.0)
    last = len(edges) - 2
    return [
        f"[{edges[i]:g},{edges[i + 1]:g}{']' if i == last else ')'}" for i in range(last + 1)
    ]


def _rates(rows: int, accepted: int, correct: int) -> dict[str, Any]:
    return {
        "rows": rows,
        "accepted": accepted,
        "correct": correct,
        "precision": correct / accepted if accepted else None,
        "coverage": accepted / rows if rows else None,
    }


def _strata(outcomes: Sequence[_Outcome]) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for stratum in _STRATA:
        chosen = [o for o in outcomes if stratum == "all" or o.seen == (stratum == "seen")]
        report[stratum] = _rates(
            len(chosen),
            sum(o.accepted for o in chosen),
            sum(o.correct for o in chosen),
        )
    return report


def _bands(outcomes: Sequence[_Outcome]) -> dict[str, Any]:
    """The accepted rows split by the band their confidence falls in.

    Each band carries the same fields as a stratum. ``rows`` is every row the method
    was tested on, the denominator of ``coverage``, so the bands' ``accepted`` and
    ``coverage`` add up to those of the ``all`` stratum.
    """
    labels = _band_labels()
    accepted = [0] * len(labels)
    correct = [0] * len(labels)
    for outcome in outcomes:
        if not outcome.accepted or outcome.confidence is None:
            continue
        band = bisect.bisect_right(BANDS, outcome.confidence)
        accepted[band] += 1
        correct[band] += outcome.correct
    return {
        label: _rates(len(outcomes), accepted[i], correct[i]) for i, label in enumerate(labels)
    }


def _sweep(outcomes: Sequence[_Outcome]) -> list[dict[str, Any]]:
    """The kNN novel stratum under each grid pair: the gates of #24 re-applied, no re-query."""
    novel = [o for o in outcomes if not o.seen]
    sweep: list[dict[str, Any]] = []
    for distance in SWEEP_DISTANCES:
        for margin in SWEEP_MARGINS:
            passed = [
                o
                for o in novel
                if o.nearest_distance is not None
                and o.margin is not None
                and o.nearest_distance <= distance
                and o.margin >= margin
            ]
            entry: dict[str, Any] = {"max_distance": distance, "min_margin": margin}
            entry.update(
                _rates(len(novel), len(passed), sum(o.candidate_correct for o in passed))
            )
            sweep.append(entry)
    return sweep


def _knn_outcome(
    index: KnnIndex,
    row: IndexRow,
    normaliser: Normaliser,
    seen: bool,
    *,
    exclude: IndexRow | None = None,
) -> _Outcome:
    result = index.query(
        row.token,
        row.source_account,
        row.sign,
        as_of=row.post_date,
        normaliser_version=normaliser.version,
        exclude=exclude,
    )
    truth = row.destination_account
    return _Outcome(
        seen=seen,
        accepted=result.accepted,
        correct=result.accepted and result.account == truth,
        confidence=result.share,
        nearest_distance=result.nearest_distance,
        margin=result.margin,
        candidate_correct=result.candidate == truth,
    )


def _bayes_outcome(bayes: _TokenBayes, row: IndexRow, seen: bool) -> _Outcome:
    verdict = bayes.classify(row.token, (row.source_account, row.sign))
    if verdict is None:
        return _Outcome(seen=seen, accepted=False, correct=False, confidence=None)
    account, posterior = verdict
    return _Outcome(
        seen=seen,
        accepted=True,
        correct=account == row.destination_account,
        confidence=posterior,
    )


def _method_report(outcomes: Sequence[_Outcome]) -> dict[str, Any]:
    return {"strata": _strata(outcomes), "bands": _bands(outcomes)}


def _counts(outcomes: Sequence[_Outcome]) -> dict[str, int]:
    return {
        "rows": len(outcomes),
        "accepted": sum(o.accepted for o in outcomes),
        "correct": sum(o.correct for o in outcomes),
    }


def backtest(
    corpus: CorpusContract,
    normaliser: Normaliser,
    *,
    max_distance: float,
    min_margin: float,
) -> dict[str, Any]:
    """Run the rolling-origin backtest and return the report (the object the CLI writes).

    Raises :class:`KnnError` for thresholds the kNN index refuses, even when the corpus
    is too short to test a month.
    """
    # Validates the thresholds up front; an empty index is fine.
    KnnIndex.build([], max_distance=max_distance, min_margin=min_margin)
    rows = index_rows(corpus, normaliser)

    by_month: dict[_Month, list[IndexRow]] = {}
    for row in rows:
        by_month.setdefault(_month_of(row.post_date), []).append(row)
    # Every calendar month of the range, one without rows too: it is tested, with zero
    # counts, so the per-month list has no hole.
    months = _calendar(min(by_month), max(by_month)) if by_month else []

    knn_all: list[_Outcome] = []
    bayes_all: list[_Outcome] = []
    monthly: dict[str, Any] = {}
    for month in months[1:]:
        start = datetime.date(month[0], month[1], 1)
        history = [row for row in rows if row.post_date < start]
        index = KnnIndex.build(history, max_distance=max_distance, min_margin=min_margin)
        bayes = _TokenBayes(history)
        known = {(r.source_account, r.sign, r.token) for r in history}
        knn_month: list[_Outcome] = []
        bayes_month: list[_Outcome] = []
        for row in by_month.get(month, []):
            seen = (row.source_account, row.sign, row.token) in known
            knn_month.append(_knn_outcome(index, row, normaliser, seen))
            bayes_month.append(_bayes_outcome(bayes, row, seen))
        monthly[_label(month)] = {
            "knn": _counts(knn_month),
            "token_bayes": _counts(bayes_month),
        }
        knn_all.extend(knn_month)
        bayes_all.extend(bayes_month)

    return {
        "report": "backtest",
        "report_version": REPORT_VERSION,
        "normaliser_version": normaliser.version,
        "thresholds": {
            "max_distance": max_distance,
            "min_margin": min_margin,
            "half_life_days": HALF_LIFE_DAYS,
        },
        "bands": _band_labels(),
        "months": {
            "first": _label(months[0]) if months else None,
            "last": _label(months[-1]) if months else None,
            "tested": len(monthly),
            "by_month": monthly,
        },
        "methods": {
            "knn": _method_report(knn_all),
            "token_bayes": _method_report(bayes_all),
        },
        "upper_bound": {
            "knn_leave_one_out": {
                "strata": _strata(
                    _leave_one_out(rows, normaliser, max_distance, min_margin),
                )
            },
        },
        "novel_sweep": _sweep(knn_all),
    }


def _leave_one_out(
    rows: Sequence[IndexRow],
    normaliser: Normaliser,
    max_distance: float,
    min_margin: float,
) -> list[_Outcome]:
    """Every row against all the others, the future included: an upper bound only."""
    index = KnnIndex.build(rows, max_distance=max_distance, min_margin=min_margin)
    tokens = Counter((r.source_account, r.sign, r.token) for r in rows)
    return [
        _knn_outcome(
            index,
            row,
            normaliser,
            tokens[(row.source_account, row.sign, row.token)] > 1,
            exclude=row,
        )
        for row in rows
    ]


def run_trial() -> None:
    """Entry point of the rest of the trial tooling (scenario 1) block."""
    raise NotImplementedError


# --- command line -----------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m autobook.pipeline.trial", description="Trial tooling (scenario 1)."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser(
        "backtest",
        help="rolling-origin backtest of a corpus export; writes a counts-only JSON report",
    )
    run.add_argument("--corpus", required=True, type=Path, help="a `corpus` contract file")
    run.add_argument("--out", required=True, type=Path, help="where to write the report")
    run.add_argument("--max-distance", required=True, type=float, help="distance gate")
    run.add_argument("--min-margin", required=True, type=float, help="margin gate")
    run.add_argument(
        "--normaliser-dir",
        type=Path,
        default=None,
        help="user normaliser directory (default: the user config directory)",
    )
    return parser


def _fail(message: str) -> int:
    sys.stderr.write(f"error: {message}\n")
    return _EXIT_USAGE


# A field path such as `corpus.rows[3].post_date`: names and indices only.
_FIELD: Final = re.compile(r"(?P<root>[A-Za-z_]+)(?:\[\d+\])*(?:\.[A-Za-z_]+(?:\[\d+\])*)*")

# Where a kNN error the command line can cause is located: the threshold it refused.
_THRESHOLDS: Final = frozenset({"max_distance", "min_margin"})


def _refused(what: str, exc: ValueError, roots: Collection[str]) -> int:
    """Say what was refused and where, never with the error's own text.

    Contract and index errors quote the value they refuse (an amount, a date, a field
    name read from the file), and normaliser errors quote file paths and patterns, so
    the message is never passed on. Only its leading field path is, and only when it is
    made of names and indices and starts at one of ``roots``, the names the caller
    knows this kind of error is located at (ch.8 section 8.5: logs carry IDs, counts
    and versions). A path the user chose can read like a name (``PRIVATE_PROFILE``), so
    the shape alone is not enough.
    """
    location = str(exc).split(": ", 1)[0]
    field = _FIELD.fullmatch(location)
    if field is not None and field["root"] in roots:
        return _fail(f"{what} ({type(exc).__name__} at {location})")
    return _fail(f"{what} ({type(exc).__name__})")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line; 0 on success, 2 on a refused input (no report is written)."""
    args = _parser().parse_args(argv)
    try:
        corpus = corpus_from_json(args.corpus.read_text(encoding="utf-8"))
        normaliser = load_normaliser(args.normaliser_dir)
        report = backtest(
            corpus,
            normaliser,
            max_distance=args.max_distance,
            min_margin=args.min_margin,
        )
    except ContractError as exc:
        return _refused("the corpus file is not a valid `corpus` contract", exc, {CORPUS_NAME})
    except NormaliserError as exc:
        # Located at a profile file or directory, a path the user chose: never named.
        return _refused("the normaliser profiles were refused", exc, ())
    except KnnError as exc:
        return _refused("the kNN index refused the thresholds or a row", exc, _THRESHOLDS)
    except (OSError, UnicodeDecodeError) as exc:
        return _fail(f"cannot read the corpus: {type(exc).__name__}")
    try:
        text = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False)
        args.out.write_text(text + "\n", encoding="utf-8")
    except OSError as exc:
        return _fail(f"cannot write the report: {type(exc).__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

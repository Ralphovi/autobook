"""Classifier — building block of ch.5 section 5.2.

Design: `docs/design/architecture/05-building-block-view.md`.

This module holds the kNN tier (tier 5 of the cascade): a character n-gram TF-IDF
nearest-neighbour index per ``(source_account, sign)`` over the user's own history.
:meth:`KnnIndex.query` proposes one destination account only when both gates pass:
the nearest neighbour is close enough, and the recency-weighted vote has a clear
winner. Otherwise it abstains and says which gate failed. Thresholds have no default:
they come from backtest evidence, never from code (AGENTS.md).

Only ``observed`` and ``corrected`` rows can enter an index, all normalised under one
normaliser version. Refusal is an error (:class:`KnnError`), never a silent skip.

``classify`` is still the stub: the cascade itself arrives with a later build step.

Pipeline module: must never import `gnucash`.
"""

from __future__ import annotations

import datetime
import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Final, Literal, NoReturn

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from autobook.contracts import CorpusContract, Sign
from autobook.pipeline.normaliser import Normaliser

__all__ = [
    "HALF_LIFE_DAYS",
    "IndexRow",
    "KnnError",
    "KnnIndex",
    "KnnResult",
    "classify",
    "index_rows",
]

# ch.5: "~18-month half-life". 18 months of 365/12 days, rounded: 547.5 -> 548.
HALF_LIFE_DAYS: Final[float] = 548.0

# Neighbours that vote: every row at or below the k-th smallest distance, so more
# than k when rows tie with the k-th. A partition smaller than this votes whole.
_K: Final = 15

# A cosine distance below this is rounding noise on identical vectors, read as 0.
# Float error on a dot product of unit vectors is ~1e-16 per term; real distances
# between different tokens are many orders of magnitude larger.
_IDENTICAL: Final = 1e-9

_SIGNS: Final[tuple[str, ...]] = ("out", "in")
_PROVENANCE: Final[tuple[str, ...]] = ("observed", "corrected")

Gate = Literal["distance", "margin"]
_Account = tuple[str, ...]


class KnnError(ValueError):
    """A row, a threshold or a query was not accepted by the kNN index.

    Messages name the field, never the memo token or the account path: both are
    personal data (ch.8 section 8.5).
    """


def _fail(where: str, message: str) -> NoReturn:
    raise KnnError(f"{where}: {message}")


# Field checks compare exact types, never `isinstance`: a `str` or `tuple` subclass
# (or an object such as `unittest.mock.ANY`) can define its own `__eq__` and pass a
# membership or equality test, e.g. a provenance that reads "synthetic" yet compares
# equal to "observed".


def _text(value: object, where: str, *, non_empty: bool) -> None:
    # Typed `object` so the runtime check is not dead code to the type checker.
    if type(value) is not str:
        _fail(where, f"expected a string, got {type(value).__name__}")
    if non_empty and not value:
        _fail(where, "must not be empty")


def _choice(value: object, where: str, allowed: tuple[str, ...], message: str) -> None:
    if type(value) is not str:
        _fail(where, f"{message}, got {type(value).__name__}")
    if value not in allowed:
        _fail(where, f"{message}, got {value!r}")


def _path(value: object, where: str) -> None:
    if (
        type(value) is not tuple
        or not value
        or not all(type(part) is str and part for part in value)
    ):
        _fail(where, "an account is a non-empty tuple of non-empty path components")


@dataclass(frozen=True)
class IndexRow:
    """One history row as the index sees it: a normalised memo and where it was booked."""

    token: str
    source_account: tuple[str, ...]
    sign: Sign
    destination_account: tuple[str, ...]
    post_date: datetime.date
    provenance: Literal["observed", "corrected"]
    normaliser_version: str

    def __post_init__(self) -> None:
        _check_row(self)


def _check_row(row: IndexRow) -> None:
    # A module function, not a method: `KnnIndex.build` runs it again on every row
    # (a row built around the constructor, e.g. `object.__setattr__` on a frozen
    # instance, must still be refused), and a subclass must not be able to
    # override the check.
    _text(row.token, "token", non_empty=False)
    _path(row.source_account, "source_account")
    _path(row.destination_account, "destination_account")
    _choice(row.sign, "sign", _SIGNS, f"expected one of {list(_SIGNS)}")
    # datetime is a subclass of date; its subtraction from a date raises TypeError.
    if type(row.post_date) is not datetime.date:
        _fail("post_date", f"expected a date, got {type(row.post_date).__name__}")
    _choice(
        row.provenance,
        "provenance",
        _PROVENANCE,
        f"only {list(_PROVENANCE)} rows can enter the index",
    )
    _text(row.normaliser_version, "normaliser_version", non_empty=True)


@dataclass(frozen=True)
class KnnResult:
    """What one query found, whether or not it was accepted.

    ``account`` is set only when both gates passed. ``candidate`` is the vote winner
    either way, so a review can show it. Both gate numbers are reported when they exist.
    """

    account: tuple[str, ...] | None
    candidate: tuple[str, ...] | None
    nearest_distance: float | None
    margin: float | None
    share: float | None
    failed_gates: frozenset[Gate]

    @property
    def accepted(self) -> bool:
        return not self.failed_gates


def index_rows(corpus: CorpusContract, normaliser: Normaliser) -> tuple[IndexRow, ...]:
    """One row per corpus row, normalised by ``normaliser``.

    ``provenance`` is copied from the corpus row, never set here, so the
    :class:`IndexRow` check sees the value the row really carries.
    """
    rows: list[IndexRow] = []
    for row in corpus.rows:
        memo = normaliser.normalise(row.raw_memo, row.source_account)
        rows.append(
            IndexRow(
                token=memo.token,
                source_account=row.source_account,
                sign=row.sign,
                destination_account=row.destination_account,
                post_date=row.post_date,
                provenance=row.provenance,
                normaliser_version=memo.version,
            )
        )
    return tuple(rows)


class _Partition:
    """The rows of one ``(source_account, sign)`` and the vectors fitted on them."""

    def __init__(self, rows: list[IndexRow]) -> None:
        self.rows: Final = tuple(rows)
        # The first position of each distinct row, for `exclude`. Equal rows are
        # interchangeable, so which of them is left out does not matter.
        self._position: Final[dict[IndexRow, int]] = {}
        for position, row in enumerate(self.rows):
            self._position.setdefault(row, position)
        tokens = [row.token for row in rows]
        self._matrix: Any = None
        self._analyse: Any = None
        self._vocabulary: dict[str, int] = {}
        self._document_frequency: Any = None
        # char_wb pads every word with spaces, so any non-blank token has an n-gram.
        # All-blank tokens leave an empty vocabulary, which scikit-learn refuses.
        if any(token.strip() for token in tokens):
            vectoriser = TfidfVectorizer(
                analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True
            )
            # One L2-normalised TF-IDF vector per row.
            self._matrix = vectoriser.fit_transform(tokens)
            # The rows' own n-grams and lowercasing, for the query and for `exclude`.
            self._analyse = vectoriser.build_analyzer()
            self._vocabulary = vectoriser.vocabulary_
            # How many rows contain each vocabulary n-gram.
            self._document_frequency = np.asarray((self._matrix > 0).sum(axis=0)).ravel()

    def holds(self, row: IndexRow) -> bool:
        """Whether a row equal to ``row`` is in this partition."""
        return row in self._position

    def voters(self, token: str, exclude: IndexRow | None) -> list[tuple[float, IndexRow]]:
        """The rows that vote on ``token``, closest first, each with its distance.

        ``exclude``, a row this partition holds, is taken out first. Then every row at
        or below the k-th smallest distance votes, so input order never decides which
        of the rows tied with the k-th get in.
        """
        if self._matrix is None or not token.strip():
            return []
        positions = np.arange(len(self.rows))
        if exclude is not None:
            positions = np.delete(positions, self._position[exclude])
        if positions.size == 0:
            return []
        distances = self._distances(token, exclude)
        remaining = distances[positions]
        last = min(_K, remaining.size) - 1  # the k-th smallest, counted from 0
        cutoff = np.partition(remaining, last)[last]
        chosen = positions[remaining <= cutoff]
        # Closest first; rows at the same distance stay in position order.
        chosen = chosen[np.argsort(distances[chosen], kind="stable")]
        return [(float(distances[position]), self.rows[int(position)]) for position in chosen]

    def _distances(self, token: str, exclude: IndexRow | None) -> Any:
        """The distance from ``token`` to every row, measured over all of its n-grams.

        A query n-gram counted ``c`` times weighs ``(1 + ln c) * idf``, with
        scikit-learn's smooth idf on this partition's counts,
        ``idf = ln((1 + n) / (1 + df)) + 1`` for ``n`` rows of which ``df`` contain the
        n-gram. One that no row contains (``df = 0``) gets the weight of a term no row
        contains: it matches no row, but it counts in the query's L2 norm, so it moves
        the query away from history. (``TfidfVectorizer.transform`` would drop it.) The
        distance to a row is ``1 - (query . row)``, with the row's fitted vector.

        With ``exclude``, ``n`` and the ``df`` of each of its n-grams are one lower, as
        if it were not in history. The other rows' vectors keep the idf they were
        fitted with.
        """
        n = len(self.rows)
        dropped: set[str] = set()
        if exclude is not None:
            n -= 1
            dropped = set(self._analyse(exclude.token))
        query = np.zeros(len(self._vocabulary))
        squared = 0.0
        for gram, count in Counter(self._analyse(token)).items():
            column = self._vocabulary.get(gram)
            df = 0 if column is None else int(self._document_frequency[column])
            if gram in dropped:
                df -= 1
            weight = (1.0 + math.log(count)) * (math.log((1 + n) / (1 + df)) + 1.0)
            squared += weight * weight
            if column is not None:
                query[column] = weight
        # A non-blank token has at least one n-gram, and every weight is at least 1.
        return _clamp(1.0 - (self._matrix @ query) / math.sqrt(squared))


def _clamp(distances: Any) -> Any:
    """Cosine distances as the gates see them: in [0, 1], and exactly 0 for identical vectors.

    ``1 - dot(a, b)`` is computed in floating point, so identical vectors can come back
    a few ulps either side of 0 (seen: ``1.8e-15``). Without the snap an exact token
    match could fail ``max_distance=0``.
    """
    return np.where(distances < _IDENTICAL, 0.0, np.minimum(distances, 1.0))


def _threshold(value: object, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        _fail(where, f"expected a number, got {type(value).__name__}")
    return float(value)


class KnnIndex:
    """Nearest-neighbour index with abstention gates. Built only by :meth:`build`."""

    def __init__(
        self,
        partitions: dict[tuple[_Account, str], _Partition],
        normaliser_version: str | None,
        max_distance: float,
        min_margin: float,
        half_life_days: float,
    ) -> None:
        self._partitions: Final = partitions
        self._normaliser_version: Final = normaliser_version
        self._max_distance: Final = max_distance
        self._min_margin: Final = min_margin
        self._half_life_days: Final = half_life_days

    @classmethod
    def build(
        cls,
        rows: Iterable[IndexRow],
        *,
        max_distance: float,
        min_margin: float,
        half_life_days: float = HALF_LIFE_DAYS,
    ) -> KnnIndex:
        """Fit one sub-index per ``(source_account, sign)``.

        Raises :class:`KnnError`, and returns nothing, for a row that is not
        ``observed`` or ``corrected`` (checked again here, not only in the
        constructor), for rows of more than one normaliser version, and for a
        threshold outside ``0 <= max_distance < 1``, ``0 < min_margin <= 1`` or a
        half-life that is not a positive finite number.
        """
        distance = _threshold(max_distance, "max_distance")
        margin = _threshold(min_margin, "min_margin")
        half_life = _threshold(half_life_days, "half_life_days")
        if not 0 <= distance < 1:
            _fail("max_distance", "must satisfy 0 <= max_distance < 1")
        # min_margin > 0 means a tie can never be accepted.
        if not 0 < margin <= 1:
            _fail("min_margin", "must satisfy 0 < min_margin <= 1")
        if not (math.isfinite(half_life) and half_life > 0):
            _fail("half_life_days", "must be a positive, finite number of days")

        grouped: dict[tuple[_Account, str], list[IndexRow]] = {}
        versions: set[str] = set()
        for row in rows:
            # Exactly IndexRow: a subclass could change how its fields read.
            if type(row) is not IndexRow:
                _fail("rows", f"expected IndexRow objects, got {type(row).__name__}")
            _check_row(row)  # the constructor check can be bypassed
            versions.add(row.normaliser_version)
            grouped.setdefault((row.source_account, row.sign), []).append(row)
        if len(versions) > 1:
            _fail(
                "normaliser_version",
                f"one index holds one normaliser version, got {len(versions)}",
            )
        partitions = {key: _Partition(members) for key, members in grouped.items()}
        version = next(iter(versions), None)
        return cls(partitions, version, distance, margin, half_life)

    def query(
        self,
        token: str,
        source_account: tuple[str, ...],
        sign: Sign,
        *,
        as_of: datetime.date,
        normaliser_version: str,
        exclude: IndexRow | None = None,
    ) -> KnnResult:
        """Vote among the rows nearest to ``token`` in its ``(source_account, sign)`` partition.

        The distance is measured over every n-gram of ``token``: one that no row of the
        partition contains moves the query away from history, never toward it. Every
        row at or below the 15th smallest distance votes, so the result depends on the
        set of rows, not on the order they were passed to :meth:`build`.

        ``exclude`` is a leave-one-out that does not rebuild the index: the query is
        measured as if one row equal to it were not in history. That row is taken out
        before the voters are chosen, and out of the query's idf (``n`` and the
        document frequency of its n-grams drop by one). The other rows are not refitted:
        their vectors keep the idf fitted with it in. So a remaining row with the
        query's own token is usually a little above distance 0, and ``max_distance=0``
        can fail where the same query without ``exclude`` passes. Raises
        :class:`KnnError` if the query's partition holds no row equal to ``exclude``.
        """
        _text(token, "token", non_empty=False)
        _path(source_account, "source_account")
        _choice(sign, "sign", _SIGNS, f"expected one of {list(_SIGNS)}")
        _text(normaliser_version, "normaliser_version", non_empty=True)
        if type(as_of) is not datetime.date:
            _fail("as_of", f"expected a date, got {type(as_of).__name__}")
        if exclude is not None:
            # Exactly IndexRow, with exact field types: a subclass's or a field's own
            # `__eq__` would otherwise decide which row counts as equal to it.
            if type(exclude) is not IndexRow:
                _fail("exclude", f"expected an IndexRow, got {type(exclude).__name__}")
            _check_row(exclude)
        if self._normaliser_version is not None and normaliser_version != (
            self._normaliser_version
        ):
            _fail(
                "normaliser_version",
                "the query was normalised under a different version than the index",
            )

        partition = self._partitions.get((source_account, sign))
        # Before any result: a leave-one-out that silently left nothing out would score
        # the row against itself.
        if exclude is not None and (partition is None or not partition.holds(exclude)):
            _fail("exclude", "the query's (source_account, sign) partition holds no equal row")
        voters = [] if partition is None else partition.voters(token, exclude)
        if not voters:
            return KnnResult(None, None, None, None, None, frozenset({"distance"}))
        return self._vote(voters, as_of)

    def _vote(
        self, neighbours: list[tuple[float, IndexRow]], as_of: datetime.date
    ) -> KnnResult:
        weights: dict[_Account, float] = {}
        for distance, row in neighbours:
            age_days = max(0, (as_of - row.post_date).days)
            weight = (1.0 - distance) * 0.5 ** (age_days / self._half_life_days)
            weights[row.destination_account] = (
                weights.get(row.destination_account, 0.0) + weight
            )
        # Largest weight first; on an exact tie the smaller path tuple, so results
        # are deterministic.
        ranked = sorted(weights.items(), key=lambda item: (-item[1], item[0]))
        total = sum(weights.values())
        candidate, top = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
        share = top / total if total > 0 else 0.0
        margin = (top - runner_up) / total if total > 0 else 0.0

        nearest = neighbours[0][0]
        failed: set[Gate] = set()
        if not nearest <= self._max_distance:
            failed.add("distance")
        if not margin >= self._min_margin:
            failed.add("margin")
        return KnnResult(
            account=None if failed else candidate,
            candidate=candidate,
            nearest_distance=nearest,
            margin=margin,
            share=share,
            failed_gates=frozenset(failed),
        )


def classify() -> None:
    """Entry point of the classifier block."""
    raise NotImplementedError

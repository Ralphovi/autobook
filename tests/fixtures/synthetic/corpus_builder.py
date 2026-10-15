"""Seeded builder for a synthetic ``corpus`` contract object.

Every merchant, memo and amount is invented (see README.md). Amounts are integer
cents. The account tree is the one `tests/book/synthetic_book.py` builds, written
here as component tuples because that module imports `gnucash` and cannot be
loaded on the host.
"""

from __future__ import annotations

import datetime
import random
from typing import NamedTuple

from autobook.contracts import CorpusContract, CorpusRow, Sign

GIROKONTO = ("Aktiva", "Girokonto")
REVOLUT = ("Aktiva", "Revolut")
LEBENSMITTEL = ("Ausgaben", "Lebensmittel")
MIETE = ("Ausgaben", "Miete")
GEHALT = ("Einnahmen", "Gehalt")


class Merchant(NamedTuple):
    token: str
    source: tuple[str, ...]
    destination: tuple[str, ...]
    sign: Sign
    cents: tuple[int, int]  # inclusive range
    per_month: tuple[int, int]  # inclusive range


MERCHANTS: tuple[Merchant, ...] = (
    Merchant("BEISPIELMARKT", GIROKONTO, LEBENSMITTEL, "out", (1500, 9500), (2, 4)),
    Merchant("MUSTERBAECKEREI", GIROKONTO, LEBENSMITTEL, "out", (300, 1800), (2, 4)),
    Merchant("TESTHOF GEMUESE", REVOLUT, LEBENSMITTEL, "out", (800, 4200), (1, 2)),
    Merchant("MUSTER HAUSVERWALTUNG", GIROKONTO, MIETE, "out", (75000, 75000), (1, 1)),
    Merchant("BEISPIEL ARBEITGEBER GMBH", GIROKONTO, GEHALT, "in", (240000, 260000), (1, 1)),
)

# Occurs exactly once, on the latest date, so a rolling-origin backtest sees it
# only in the final month.
NOVEL_MERCHANT = "NEUHEIM KIOSK"

FIRST_MONTH = datetime.date(2025, 1, 1)
MONTHS = 12
# Regular rows fall on days 1-27; the novel row takes day 28 of the last month, a
# date no other row has.
LAST_REGULAR_DAY = 27
NOVEL_DAY = 28

# The kind of noise the normaliser strips: reference and card fragments, sequence
# numbers, dates. {n} is a number, {d} a day, {m} a month.
NOISE = (
    "SAGT DANKE {n}",
    "KARTE {n} {d:02d}.{m:02d}.",
    "REF {n}",
    "NR. {n}",
    "{d:02d}.{m:02d}. {n}",
    "",
)


def _month(index: int) -> tuple[int, int]:
    zero_based = FIRST_MONTH.month - 1 + index
    return FIRST_MONTH.year + zero_based // 12, zero_based % 12 + 1


def build_corpus(seed: int) -> CorpusContract:
    """Return a synthetic corpus; the same ``seed`` always gives an equal one."""
    rng = random.Random(seed)  # noqa: S311  # synthetic data, not a security context
    rows: list[CorpusRow] = []
    for index in range(MONTHS):
        year, month = _month(index)
        for merchant in MERCHANTS:
            for _ in range(rng.randint(*merchant.per_month)):
                day = rng.randint(1, LAST_REGULAR_DAY)
                noise = rng.choice(NOISE).format(n=rng.randint(100, 99999), d=day, m=month)
                rows.append(
                    CorpusRow(
                        raw_memo=f"{merchant.token} {noise}".strip(),
                        amount_cents=rng.randint(*merchant.cents),
                        sign=merchant.sign,
                        source_account=merchant.source,
                        destination_account=merchant.destination,
                        post_date=datetime.date(year, month, day),
                    )
                )
    year, month = _month(MONTHS - 1)
    rows.append(
        CorpusRow(
            raw_memo=f"{NOVEL_MERCHANT} {rng.randint(100, 99999)}",
            amount_cents=rng.randint(200, 2500),
            sign="out",
            source_account=GIROKONTO,
            destination_account=LEBENSMITTEL,
            post_date=datetime.date(year, month, NOVEL_DAY),
        )
    )
    rows.sort(key=lambda row: (row.post_date, row.raw_memo, row.amount_cents))
    return CorpusContract(rows=tuple(rows))

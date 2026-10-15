"""Build a small synthetic GnuCash book through the bindings (book-process tests only).

Every name and amount is invented. Amounts are integer cents, never floats.
"""

from __future__ import annotations

from typing import Any

import gnucash
from gnucash import Account, GncNumeric, Session, Split, Transaction

# (path, account type) — created in this order, parents first.
ACCOUNTS: list[tuple[str, int]] = [
    ("Aktiva", gnucash.ACCT_TYPE_ASSET),
    ("Aktiva:Girokonto", gnucash.ACCT_TYPE_BANK),
    ("Aktiva:Revolut", gnucash.ACCT_TYPE_BANK),
    ("Ausgaben", gnucash.ACCT_TYPE_EXPENSE),
    ("Ausgaben:Lebensmittel", gnucash.ACCT_TYPE_EXPENSE),
    ("Ausgaben:Miete", gnucash.ACCT_TYPE_EXPENSE),
    ("Einnahmen", gnucash.ACCT_TYPE_INCOME),
    ("Einnahmen:Gehalt", gnucash.ACCT_TYPE_INCOME),
]

# (day, month, year, description, from account, to account, cents)
TRANSACTIONS: list[tuple[int, int, int, str, str, str, int]] = [
    (
        2,
        1,
        2026,
        "BEISPIELMARKT SAGT DANKE 4711",
        "Aktiva:Girokonto",
        "Ausgaben:Lebensmittel",
        4290,
    ),
    (
        3,
        1,
        2026,
        "MUSTER HAUSVERWALTUNG MIETE JANUAR",
        "Aktiva:Girokonto",
        "Ausgaben:Miete",
        75000,
    ),
    (
        28,
        1,
        2026,
        "BEISPIEL ARBEITGEBER GMBH GEHALT",
        "Einnahmen:Gehalt",
        "Aktiva:Girokonto",
        250000,
    ),
    (5, 2, 2026, "UEBERTRAG REVOLUT", "Aktiva:Girokonto", "Aktiva:Revolut", 10000),
]

# Expected balances in cents after TRANSACTIONS (assets positive, spending positive).
BALANCES: dict[str, int] = {
    "Aktiva:Girokonto": 250000 - 4290 - 75000 - 10000,
    "Aktiva:Revolut": 10000,
    "Ausgaben:Lebensmittel": 4290,
    "Ausgaben:Miete": 75000,
}


def populate(book: Any) -> None:
    """Create ACCOUNTS and TRANSACTIONS in an open, empty book."""
    eur = book.get_table().lookup("CURRENCY", "EUR")
    root = book.get_root_account()
    accounts: dict[str, Any] = {}
    for path, kind in ACCOUNTS:
        parent_path, _, name = path.rpartition(":")
        account = Account(book)
        account.BeginEdit()
        account.SetName(name)
        account.SetType(kind)
        account.SetCommodity(eur)
        account.CommitEdit()
        (accounts[parent_path] if parent_path else root).append_child(account)
        accounts[path] = account
    for row in TRANSACTIONS:
        add_transaction(book, *row)


def add_transaction(
    book: Any,
    day: int,
    month: int,
    year: int,
    description: str,
    source: str,
    target: str,
    cents: int,
) -> None:
    """Book ``cents`` from ``source`` to ``target`` as one two-split transaction."""
    eur = book.get_table().lookup("CURRENCY", "EUR")
    tx = Transaction(book)
    tx.BeginEdit()
    tx.SetCurrency(eur)
    tx.SetDate(day, month, year)
    tx.SetDescription(description)
    for path, value in ((target, cents), (source, -cents)):
        split = Split(book)
        split.SetParent(tx)
        split.SetAccount(lookup(book, path))
        split.SetValue(GncNumeric(value, 100))
        split.SetAmount(GncNumeric(value, 100))
    tx.CommitEdit()


def build(uri: str) -> None:
    """Create a new book at ``uri``, populate it, and save it."""
    session = Session(uri, gnucash.SessionOpenMode.SESSION_NEW_STORE)
    try:
        populate(session.book)
        session.save()
    finally:
        session.end()


def lookup(book: Any, path: str) -> Any:
    """Find an account by its components, never by a separator-joined full name.

    GnuCash takes the account separator from a user preference outside the book; a
    headless session uses "." while a desktop is often set to ":". Walking the
    components works whatever the preference is.
    """
    account = book.get_root_account()
    for name in path.split(":"):
        children = {child.GetName(): child for child in account.get_children()}
        if name not in children:
            return None
        account = children[name]
    return account


def balance_cents(book: Any, path: str) -> int:
    account = lookup(book, path)
    if account is None:
        raise LookupError(path)
    value = account.GetBalance()
    return int(value.num() * 100 // value.denom())

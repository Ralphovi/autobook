"""Book-process smoke tests for the test environment (testenv/, #47).

They also record, as executable checks, what spike #3 asks of the GnuCash version the
environment pins (5.14): SessionOpenMode exists, a PostgreSQL URI with a non-default port
works, a second writer gets ERR_BACKEND_LOCKED, and nothing persists without save().
Synthetic books only.
"""

from __future__ import annotations

import os
import socket
import subprocess
import uuid
from pathlib import Path
from typing import Any

import pytest

gnucash = pytest.importorskip("gnucash")

from tests.book import synthetic_book

pytestmark = pytest.mark.applier

SessionOpenMode = gnucash.SessionOpenMode


def _open(uri: str, mode: Any) -> Any:
    return gnucash.Session(uri, mode)


def test_session_open_modes_exist() -> None:
    names = {m for m in dir(SessionOpenMode) if m.startswith("SESSION_")}
    assert {"SESSION_NORMAL_OPEN", "SESSION_READ_ONLY", "SESSION_NEW_STORE"} <= names


def test_float_constructor_is_the_money_hazard() -> None:
    # The bindings convert a double silently; integer cents are the only safe input.
    assert not hasattr(gnucash.GncNumeric, "from_double")
    half = gnucash.GncNumeric(0.5)
    assert half.num() * 2 == half.denom()


def test_xml_book_round_trip(tmp_path: Path) -> None:
    uri = f"xml://{tmp_path / 'book.gnucash'}"
    synthetic_book.build(uri)
    session = _open(uri, SessionOpenMode.SESSION_READ_ONLY)
    try:
        for path, cents in synthetic_book.BALANCES.items():
            assert synthetic_book.balance_cents(session.book, path) == cents
    finally:
        session.end()


def test_xml_write_without_save_persists_nothing(tmp_path: Path) -> None:
    # B1: on the XML backend session.end() does not write the file, so a committed
    # transaction that was never saved is gone after the session ends.
    uri = f"xml://{tmp_path / 'book.gnucash'}"
    synthetic_book.build(uri)
    writer = _open(uri, SessionOpenMode.SESSION_NORMAL_OPEN)
    try:
        synthetic_book.add_transaction(
            writer.book,
            6,
            2,
            2026,
            "BEISPIELMARKT",
            "Aktiva:Girokonto",
            "Ausgaben:Lebensmittel",
            1735,
        )
        assert synthetic_book.balance_cents(writer.book, "Ausgaben:Lebensmittel") == 4290 + 1735
    finally:
        writer.end()  # no save()
    reader = _open(uri, SessionOpenMode.SESSION_READ_ONLY)
    try:
        assert synthetic_book.balance_cents(reader.book, "Ausgaben:Lebensmittel") == 4290
    finally:
        reader.end()


def test_xml_write_with_save_persists(tmp_path: Path) -> None:
    uri = f"xml://{tmp_path / 'book.gnucash'}"
    synthetic_book.build(uri)
    writer = _open(uri, SessionOpenMode.SESSION_NORMAL_OPEN)
    try:
        synthetic_book.add_transaction(
            writer.book,
            6,
            2,
            2026,
            "BEISPIELMARKT",
            "Aktiva:Girokonto",
            "Ausgaben:Lebensmittel",
            1735,
        )
        writer.save()
    finally:
        writer.end()
    reader = _open(uri, SessionOpenMode.SESSION_READ_ONLY)
    try:
        assert synthetic_book.balance_cents(reader.book, "Ausgaben:Lebensmittel") == 4290 + 1735
    finally:
        reader.end()


@pytest.mark.skipif("AUTOBOOK_TEST_PG" not in os.environ, reason="needs the testenv PostgreSQL")
def test_postgres_uri_with_non_default_port() -> None:
    server = os.environ["AUTOBOOK_TEST_PG"]
    assert server.endswith(":5433")
    name = f"t_{uuid.uuid4().hex[:12]}"
    # GnuCash's SQL backend does not create the database; it must exist first.
    subprocess.run(["psql", f"{server}/postgres", "-qc", f"CREATE DATABASE {name}"], check=True)
    uri = f"{server}/{name}"
    synthetic_book.build(uri)
    session = _open(uri, SessionOpenMode.SESSION_READ_ONLY)
    try:
        assert synthetic_book.balance_cents(session.book, "Aktiva:Revolut") == 10000
    finally:
        session.end()


def test_second_writer_gets_err_backend_locked(tmp_path: Path) -> None:
    uri = f"xml://{tmp_path / 'book.gnucash'}"
    synthetic_book.build(uri)
    first = _open(uri, SessionOpenMode.SESSION_NORMAL_OPEN)
    try:
        with pytest.raises(gnucash.GnuCashBackendException) as caught:
            _open(uri, SessionOpenMode.SESSION_NORMAL_OPEN)
        assert gnucash.ERR_BACKEND_LOCKED in caught.value.errors
        # SESSION_READ_ONLY ignores the lock and reads the last saved state.
        reader = _open(uri, SessionOpenMode.SESSION_READ_ONLY)
        try:
            assert synthetic_book.balance_cents(reader.book, "Ausgaben:Miete") == 75000
        finally:
            reader.end()
    finally:
        first.end()


def test_environment_has_no_outbound_network() -> None:
    # The stack runs on an internal network: synthetic data cannot leave it, and a test
    # cannot quietly depend on the internet.
    try:
        socket.create_connection(("1.1.1.1", 443), timeout=3).close()
    except OSError:
        return  # unreachable, refused or timed out: what an internal network does
    pytest.fail("an outbound connection succeeded from the test environment")

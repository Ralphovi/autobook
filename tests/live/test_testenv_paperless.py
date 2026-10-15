"""paperless-ngx smoke tests for the test environment (testenv/, #47).

They record, as executable checks against the version the environment pins (3.3.0, the
reference deployment's), the paperless behaviour proposal 0002 relies on: the original
file and its checksum, duplicates, custom-field queries, document history, and what a
restricted user can and cannot see. Synthetic documents only.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import pytest

pytestmark = [
    pytest.mark.live_paperless,
    pytest.mark.skipif(
        "AUTOBOOK_PAPERLESS_TOKENS" not in os.environ, reason="needs the testenv paperless-ngx"
    ),
]

ACCEPT = "application/json; version=10"


@pytest.fixture(scope="module")
def seed() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(Path(os.environ["AUTOBOOK_PAPERLESS_TOKENS"]).read_text())
    return data


def _get(path: str, token: str, *, raw: bool = False) -> Any:
    request = urllib.request.Request(
        os.environ["AUTOBOOK_PAPERLESS_URL"] + path,
        headers={"Accept": ACCEPT, "Authorization": f"Token {token}"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
    return body if raw else json.loads(body)


def _status(method: str, path: str, token: str, payload: dict[str, Any]) -> int:
    request = urllib.request.Request(
        os.environ["AUTOBOOK_PAPERLESS_URL"] + path,
        data=json.dumps(payload).encode(),
        method=method,
        headers={
            "Accept": ACCEPT,
            "Authorization": f"Token {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return int(response.status)
    except urllib.error.HTTPError as error:
        return int(error.code)


def _visible_ids(token: str) -> set[int]:
    return {row["id"] for row in _get("/api/documents/?page_size=100", token)["results"]}


def test_restricted_user_sees_statements_and_bills_only(seed: dict[str, Any]) -> None:
    docs = seed["documents"]
    visible = _visible_ids(seed["autobook"])
    for key in ("statement_jan", "statement_feb", "bill_market", "bill_energy", "credit_note"):
        assert docs[key] in visible, key
    assert docs["private"] not in visible


def test_unowned_documents_are_visible_to_every_user(seed: dict[str, Any]) -> None:
    # The permissions caveat: limiting a user to some document types only works if every
    # other document has an owner.
    assert seed["documents"]["unowned"] in _visible_ids(seed["autobook"])


def test_restricted_user_cannot_change_documents(seed: dict[str, Any]) -> None:
    doc = seed["documents"]["bill_market"]
    status = _status("PATCH", f"/api/documents/{doc}/", seed["autobook"], {"title": "x"})
    assert status in (403, 404)


def test_original_download_matches_original_checksum(seed: dict[str, Any]) -> None:
    doc = seed["documents"]["statement_jan"]
    meta = _get(f"/api/documents/{doc}/metadata/", seed["autobook"])
    original = _get(f"/api/documents/{doc}/download/?original=true", seed["autobook"], raw=True)
    assert original.startswith(b"%PDF")
    # paperless-ngx 3.x stores SHA-256, so the checksum is a real integrity check.
    assert hashlib.sha256(original).hexdigest() == meta["original_checksum"]


def test_duplicates_are_accepted_by_default(seed: dict[str, Any]) -> None:
    docs = seed["documents"]
    assert docs["bill_energy"] != docs["bill_energy_dup"]
    checksums = {
        _get(f"/api/documents/{docs[k]}/metadata/", seed["admin"])["original_checksum"]
        for k in ("bill_energy", "bill_energy_dup")
    }
    assert len(checksums) == 1


def test_custom_field_query_on_a_monetary_amount(seed: dict[str, Any]) -> None:
    query = urllib.parse.quote(json.dumps(["Betrag", "exact", "EUR59.00"]))
    found = {
        row["id"]
        for row in _get(f"/api/documents/?custom_field_query={query}", seed["autobook"])[
            "results"
        ]
    }
    docs = seed["documents"]
    assert {docs["bill_energy"], docs["bill_energy_dup"], docs["bill_no_corr"]} <= found
    assert docs["bill_market"] not in found


def test_document_history_names_the_human_actor(seed: dict[str, Any]) -> None:
    doc = seed["documents"]["bill_market"]
    history = _get(f"/api/documents/{doc}/history/", seed["admin"])
    actors = {(entry.get("actor") or {}).get("username") for entry in history}
    assert "admin" in actors

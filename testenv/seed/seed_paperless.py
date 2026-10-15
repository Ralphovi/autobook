"""Seed the test environment's paperless-ngx with a synthetic world.

Creates document types, correspondents and custom fields, a dedicated non-admin
`autobook` user, and uploads generated statements and bills — including the edge cases
the tests need (a duplicate bill, a bill with no correspondent, a private document the
`autobook` user must not see, an unowned document it can). Writes the API tokens and the
created IDs to $SEED_OUT/tokens.json for the tests.

Every name, amount and IBAN here is invented. Standard library only. Idempotent: if the
environment is already seeded, it only rewrites tokens.json.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from minipdf import render  # noqa: E402

URL = os.environ.get("PAPERLESS_URL", "http://paperless:8000").rstrip("/")
OUT = Path(os.environ.get("SEED_OUT", "/seed-out"))
ADMIN = (os.environ["PAPERLESS_ADMIN_USER"], os.environ["PAPERLESS_ADMIN_PASSWORD"])
AUTOBOOK = ("autobook", "autobook-synthetic")  # throwaway environment only


def call(method, path, token=None, data=None, form=None, files=None, expect=(200, 201, 204)):
    # Pin the REST API version, so a paperless upgrade cannot silently change the shapes.
    headers = {"Accept": "application/json; version=10"}
    body = None
    if token:
        headers["Authorization"] = f"Token {token}"
    if files is not None:
        boundary = uuid.uuid4().hex
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        parts = []
        for key, value in (form or {}).items():
            values = value if isinstance(value, list) else [value]
            for v in values:
                parts.append(
                    f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{v}\r\n'.encode()
                )
        for key, (name, blob) in files.items():
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"; filename="{name}"\r\n'
                f"Content-Type: application/pdf\r\n\r\n".encode() + blob + b"\r\n"
            )
        parts.append(f"--{boundary}--\r\n".encode())
        body = b"".join(parts)
    elif form is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = urllib.parse.urlencode(form).encode()
    elif data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode()
    req = urllib.request.Request(URL + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw, status = exc.read(), exc.code
    if status not in expect:
        raise SystemExit(f"seed: {method} {path} -> HTTP {status}: {raw[:400]!r}")
    return json.loads(raw) if raw and raw[:1] in (b"{", b"[", b'"') else raw


def token_for(user, password):
    return call("POST", "/api/token/", form={"username": user, "password": password})["token"]


def wait_for_api():
    for _ in range(120):
        try:
            # The API root serves HTML (406 for JSON); a real endpoint answers 401 untokened.
            call("GET", "/api/documents/", expect=(200, 401, 403))
            return
        except (urllib.error.URLError, OSError, SystemExit):
            time.sleep(2)
    raise SystemExit("seed: paperless API never came up")


def by_name(token, endpoint, name):
    q = urllib.parse.quote(name)
    res = call("GET", f"/api/{endpoint}/?name__iexact={q}", token)["results"]
    return res[0]["id"] if res else None


def ensure(token, endpoint, name, **extra):
    existing = by_name(token, endpoint, name)
    if existing:
        return existing
    return call("POST", f"/api/{endpoint}/", token, data={"name": name, **extra})["id"]


def upload(token, filename, lines, title, document_type, correspondent=None):
    form = {"title": title, "document_type": document_type}
    if correspondent:
        form["correspondent"] = correspondent
    task = call("POST", "/api/documents/post_document/", token, form=form,
                files={"document": (filename, render(lines))})
    task_id = task if isinstance(task, str) else task.get("task_id", task)
    for _ in range(150):
        rows = call("GET", f"/api/tasks/?task_id={task_id}", token)
        rows = rows["results"] if isinstance(rows, dict) else rows
        row = rows[0] if rows else {}
        status = str(row.get("status", "")).lower()
        # API v10 reports the document in result_data / related_document_ids and the
        # status in lower case; older versions used related_document and "SUCCESS".
        doc = (row.get("result_data") or {}).get("document_id") or \
            (row.get("related_document_ids") or [None])[0] or row.get("related_document")
        if status == "success" and doc:
            return int(doc)
        if status in ("failure", "failed"):
            raise SystemExit(f"seed: consuming {filename} failed: {row}")
        time.sleep(1)
    raise SystemExit(f"seed: {filename} was never consumed")


# --------------------------------------------------------------------- synthetic world
STATEMENT_JAN = [
    "Testbank AG - Kontoauszug 1/2026",
    "Konto: Girokonto  IBAN DE00 0000 0000 0000 0000 01",
    "Zeitraum 01.01.2026 - 31.01.2026",
    "Anfangssaldo 1.000,00 EUR",
    "02.01.2026  BEISPIELMARKT SAGT DANKE 4711          -42,90",
    "03.01.2026  MUSTER HAUSVERWALTUNG MIETE JANUAR     -750,00",
    "15.01.2026  MUSTER ENERGIE AG ABSCHLAG             -59,00",
    "28.01.2026  BEISPIEL ARBEITGEBER GMBH GEHALT     2.500,00",
    "Endsaldo 2.648,10 EUR",
]
STATEMENT_FEB = [
    "Testbank AG - Kontoauszug 2/2026",
    "Konto: Girokonto  IBAN DE00 0000 0000 0000 0000 01",
    "Zeitraum 01.02.2026 - 28.02.2026",
    "Anfangssaldo 2.648,10 EUR",
    "03.02.2026  MUSTER HAUSVERWALTUNG MIETE FEBRUAR    -750,00",
    "10.02.2026  BEISPIELMARKT SAGT DANKE 4712          -17,35",
    "16.02.2026  PRAXIS BEISPIEL                        -59,00",
    "Endsaldo 1.821,75 EUR",
]
BILL_MARKET = ["Beispielmarkt GmbH", "Rechnung Nr. 4711 vom 02.01.2026",
               "Lebensmittel", "Summe 42,90 EUR"]
BILL_ENERGY = ["Muster Energie AG", "Rechnung Abschlag Januar 2026, Datum 10.01.2026",
               "Strom Abschlag", "Betrag 59,00 EUR"]
BILL_NO_CORRESPONDENT = ["Rechnung", "Datum 14.02.2026", "Behandlung", "Betrag 59,00 EUR"]
CREDIT_NOTE = ["Beispielmarkt GmbH", "Gutschrift zu Rechnung 4711 vom 05.01.2026",
               "Betrag 4,90 EUR"]
PRIVATE = ["Privates Dokument", "Kein Bezug zu Buchungen"]
UNOWNED = ["Unbesitztes Dokument", "Sichtbar fuer alle Benutzer ohne Eigentuemer"]


# key, file name, text lines, document type, correspondent, (amount, invoice date)
PLAN = [
    ("statement_jan", "kontoauszug-2026-01.pdf", STATEMENT_JAN, "Kontoauszug", "Testbank AG", None),
    ("statement_feb", "kontoauszug-2026-02.pdf", STATEMENT_FEB, "Kontoauszug", "Testbank AG", None),
    ("bill_market", "rechnung-4711.pdf", BILL_MARKET, "Rechnung", "Beispielmarkt GmbH", ("EUR42.90", "2026-01-02")),
    ("bill_energy", "rechnung-energie.pdf", BILL_ENERGY, "Rechnung", "Muster Energie AG", ("EUR59.00", "2026-01-10")),
    ("bill_energy_dup", "rechnung-energie-kopie.pdf", BILL_ENERGY, "Rechnung", "Muster Energie AG", ("EUR59.00", "2026-01-10")),
    ("bill_no_corr", "rechnung-ohne-absender.pdf", BILL_NO_CORRESPONDENT, "Rechnung", None, ("EUR59.00", "2026-02-14")),
    ("credit_note", "gutschrift-4711.pdf", CREDIT_NOTE, "Gutschrift", "Beispielmarkt GmbH", ("EUR4.90", "2026-01-05")),
    ("private", "privat.pdf", PRIVATE, "Privat", None, None),
    ("unowned", "unbesitzt.pdf", UNOWNED, "Privat", None, None),
]


def main():
    wait_for_api()
    OUT.mkdir(parents=True, exist_ok=True)
    admin = token_for(*ADMIN)

    seeded = by_name(admin, "document_types", "Kontoauszug") is not None

    types = {n: ensure(admin, "document_types", n, matching_algorithm=0)
             for n in ("Kontoauszug", "Rechnung", "Gutschrift", "Privat")}
    corr = {n: ensure(admin, "correspondents", n, matching_algorithm=0)
            for n in ("Testbank AG", "Beispielmarkt GmbH", "Muster Energie AG")}
    fields = {"Betrag": ensure(admin, "custom_fields", "Betrag", data_type="monetary"),
              "Rechnungsdatum": ensure(admin, "custom_fields", "Rechnungsdatum", data_type="date")}

    users = call("GET", "/api/users/?username__iexact=autobook", admin)["results"]
    if users:
        autobook_id = users[0]["id"]
    else:
        autobook_id = call("POST", "/api/users/", admin, data={
            "username": AUTOBOOK[0], "password": AUTOBOOK[1], "is_superuser": False,
            "is_staff": False, "user_permissions": ["view_document", "view_correspondent",
                                                    "view_documenttype", "view_customfield",
                                                    "view_tag"],
        })["id"]
    admin_id = call("GET", "/api/users/?username__iexact=admin", admin)["results"][0]["id"]

    docs = {}
    if not seeded or not call("GET", "/api/documents/?page_size=1", admin)["count"]:
        for key, filename, lines, dtype, correspondent, money in PLAN:
            doc = upload(admin, filename, lines, filename.removesuffix(".pdf"), types[dtype],
                         corr.get(correspondent) if correspondent else None)
            docs[key] = doc
            patch = {}
            if money:
                patch["custom_fields"] = [{"field": fields["Betrag"], "value": money[0]},
                                          {"field": fields["Rechnungsdatum"], "value": money[1]}]
            if key == "unowned":
                patch["owner"] = None
            else:
                patch["owner"] = admin_id
                # Statements, bills and credit notes are visible to the autobook user;
                # the private document is not.
                viewers = [] if key == "private" else [autobook_id]
                patch["set_permissions"] = {"view": {"users": viewers, "groups": []},
                                            "change": {"users": [], "groups": []}}
            call("PATCH", f"/api/documents/{doc}/", admin, data=patch)
        # One recorded human change, so document history has an actor to read.
        call("PATCH", f"/api/documents/{docs['bill_market']}/", admin,
             data={"title": "rechnung-4711 (geprueft)"})
    else:
        key_for = {filename: key for key, filename, *_ in PLAN}
        for row in call("GET", "/api/documents/?page_size=100", admin)["results"]:
            if row.get("original_file_name") in key_for:
                docs[key_for[row["original_file_name"]]] = row["id"]

    out = {
        "admin": admin, "autobook": token_for(*AUTOBOOK),
        "admin_id": admin_id, "autobook_id": autobook_id,
        "document_types": types, "correspondents": corr, "custom_fields": fields,
        "documents": docs,
    }
    (OUT / "tokens.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    os.chmod(OUT / "tokens.json", 0o644)
    print(f"seed: paperless ready — {len(docs)} documents, tokens in {OUT / 'tokens.json'}")


if __name__ == "__main__":
    main()

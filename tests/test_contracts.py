"""The `corpus` and `coa` contracts: round trip, version check, integer money.

`autobook.contracts` is loaded inside each test (via `_contracts()`), never at
module scope, so a tree without it fails these tests instead of failing to
collect them.
"""

from __future__ import annotations

import copy
import datetime
import importlib
import json
from typing import Any

import pytest


def _contracts() -> Any:
    return importlib.import_module("autobook.contracts")


def corpus_document() -> dict[str, Any]:
    return {
        "contract": "corpus",
        "version": 1,
        "rows": [
            {
                "raw_memo": "BEISPIELMARKT SAGT DANKE 4711",
                "amount_cents": 4290,
                "sign": "out",
                "source_account": ["Aktiva", "Girokonto"],
                "destination_account": ["Ausgaben", "Lebensmittel"],
                "post_date": "2026-01-02",
                "provenance": "observed",
            },
            {
                "raw_memo": "BEISPIEL ARBEITGEBER GMBH GEHALT",
                "amount_cents": 250000,
                "sign": "in",
                "source_account": ["Aktiva", "Girokonto"],
                "destination_account": ["Einnahmen", "Gehalt"],
                "post_date": "2026-01-28",
                "provenance": "observed",
            },
        ],
    }


def coa_document() -> dict[str, Any]:
    return {
        "contract": "coa",
        "version": 1,
        "accounts": [
            {
                "path": ["Aktiva", "Girokonto"],
                "type": "BANK",
                "placeholder": False,
                "commodity": {"namespace": "CURRENCY", "mnemonic": "EUR"},
                "fraction": 100,
            },
            {
                "path": ["Ausgaben"],
                "type": "EXPENSE",
                "placeholder": True,
                "commodity": {"namespace": "CURRENCY", "mnemonic": "EUR"},
                "fraction": 100,
            },
        ],
    }


def _parse(name: str, document: object) -> Any:
    return getattr(_contracts(), f"parse_{name}")(document)


def _serialise(name: str, contract: object) -> Any:
    return getattr(_contracts(), f"serialise_{name}")(contract)


DOCUMENTS = {"corpus": corpus_document, "coa": coa_document}
BODY_KEY = {"corpus": "rows", "coa": "accounts"}


def _with(name: str, mutate: Any) -> dict[str, Any]:
    document = DOCUMENTS[name]()
    mutate(document)
    return document


def _row(document: dict[str, Any], key: str, value: object) -> None:
    document["rows"][0][key] = value


def _account(document: dict[str, Any], key: str, value: object) -> None:
    document["accounts"][0][key] = value


# --- (a) round trip ----------------------------------------------------------------


@pytest.mark.parametrize("name", ["corpus", "coa"])
def test_canonical_document_serialises_back_to_itself(name: str) -> None:
    document = DOCUMENTS[name]()
    assert _serialise(name, _parse(name, copy.deepcopy(document))) == document


def test_corpus_object_round_trips_through_dict_and_json_text() -> None:
    contracts = _contracts()
    contract = contracts.CorpusContract(
        rows=(
            contracts.CorpusRow(
                raw_memo="MUSTERBAECKEREI REF 17",
                amount_cents=420,
                sign="out",
                source_account=("Aktiva", "Revolut"),
                destination_account=("Ausgaben", "Lebensmittel"),
                post_date=datetime.date(2026, 3, 9),
            ),
        )
    )
    assert contracts.parse_corpus(contracts.serialise_corpus(contract)) == contract
    assert contracts.corpus_from_json(contracts.corpus_to_json(contract)) == contract


def test_coa_object_round_trips_through_dict_and_json_text() -> None:
    contracts = _contracts()
    contract = contracts.CoaContract(
        accounts=(
            contracts.CoaAccount(
                path=("Einnahmen", "Gehalt"),
                type="INCOME",
                placeholder=False,
                commodity=contracts.Commodity(namespace="CURRENCY", mnemonic="EUR"),
                fraction=100,
            ),
        )
    )
    assert contracts.parse_coa(contracts.serialise_coa(contract)) == contract
    assert contracts.coa_from_json(contracts.coa_to_json(contract)) == contract


@pytest.mark.parametrize("name", ["corpus", "coa"])
def test_canonical_json_text_parses_and_reserialises(name: str) -> None:
    contracts = _contracts()
    text = json.dumps(DOCUMENTS[name]())
    contract = getattr(contracts, f"{name}_from_json")(text)
    assert json.loads(getattr(contracts, f"{name}_to_json")(contract)) == DOCUMENTS[name]()


def test_account_path_is_kept_as_components_not_split_on_a_separator() -> None:
    document = corpus_document()
    document["rows"][0]["source_account"] = ["Aktiva:Girokonto"]
    parsed = _parse("corpus", document)
    assert parsed.rows[0].source_account == ("Aktiva:Girokonto",)
    assert _serialise("corpus", parsed) == document


# --- (b) unknown contract name or version ------------------------------------------


@pytest.mark.parametrize("name", ["corpus", "coa"])
@pytest.mark.parametrize("version", [0, 2, -1, 1.0, True, "1", None])
def test_unknown_version_is_rejected(name: str, version: object) -> None:
    document = DOCUMENTS[name]()
    document["version"] = version
    with pytest.raises(_contracts().ContractError):
        _parse(name, document)


@pytest.mark.parametrize("name", ["corpus", "coa"])
def test_missing_version_is_rejected(name: str) -> None:
    document = DOCUMENTS[name]()
    del document["version"]
    with pytest.raises(_contracts().ContractError):
        _parse(name, document)


@pytest.mark.parametrize("name", ["corpus", "coa"])
def test_other_contract_name_is_rejected(name: str) -> None:
    other = "coa" if name == "corpus" else "corpus"
    document = DOCUMENTS[name]()
    document["contract"] = other
    with pytest.raises(_contracts().ContractError):
        _parse(name, document)


def test_contract_error_is_a_value_error() -> None:
    assert issubclass(_contracts().ContractError, ValueError)


@pytest.mark.parametrize("name", ["corpus", "coa"])
def test_malformed_json_text_is_a_contract_error(name: str) -> None:
    contracts = _contracts()
    with pytest.raises(contracts.ContractError):
        getattr(contracts, f"{name}_from_json")("{not json")


# --- (c) integer-only money --------------------------------------------------------


@pytest.mark.parametrize("amount", [12.5, 1250.0, True, "1250", None, 0, -1250])
def test_corpus_rejects_a_non_integer_or_non_positive_amount(amount: object) -> None:
    document = _with("corpus", lambda d: _row(d, "amount_cents", amount))
    with pytest.raises(_contracts().ContractError):
        _parse("corpus", document)


@pytest.mark.parametrize("fraction", [100.0, 12.5, True, "100", None, 0, -100])
def test_coa_rejects_a_non_integer_or_non_positive_fraction(fraction: object) -> None:
    document = _with("coa", lambda d: _account(d, "fraction", fraction))
    with pytest.raises(_contracts().ContractError):
        _parse("coa", document)


# --- the rest of the parse rules ---------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["Aktiva:Girokonto", [], [""], ["Aktiva", ""], ["Aktiva", 3], None],
)
@pytest.mark.parametrize("field", ["source_account", "destination_account"])
def test_corpus_rejects_an_account_that_is_not_a_component_list(
    field: str, path: object
) -> None:
    document = _with("corpus", lambda d: _row(d, field, path))
    with pytest.raises(_contracts().ContractError):
        _parse("corpus", document)


@pytest.mark.parametrize("path", ["Aktiva:Girokonto", [], [""], None])
def test_coa_rejects_a_path_that_is_not_a_component_list(path: object) -> None:
    document = _with("coa", lambda d: _account(d, "path", path))
    with pytest.raises(_contracts().ContractError):
        _parse("coa", document)


@pytest.mark.parametrize("sign", ["debit", "OUT", "", 1, None])
def test_corpus_rejects_a_sign_outside_the_closed_set(sign: object) -> None:
    document = _with("corpus", lambda d: _row(d, "sign", sign))
    with pytest.raises(_contracts().ContractError):
        _parse("corpus", document)


@pytest.mark.parametrize("provenance", ["corrected", "", None])
def test_corpus_accepts_only_observed_provenance(provenance: object) -> None:
    document = _with("corpus", lambda d: _row(d, "provenance", provenance))
    with pytest.raises(_contracts().ContractError):
        _parse("corpus", document)


@pytest.mark.parametrize(
    "date", ["20260102", "2026-W01-5", "2026-13-01", "2026-02-30", 20260102]
)
def test_corpus_rejects_a_post_date_that_is_not_an_iso_calendar_date(date: object) -> None:
    document = _with("corpus", lambda d: _row(d, "post_date", date))
    with pytest.raises(_contracts().ContractError):
        _parse("corpus", document)


@pytest.mark.parametrize("name", ["corpus", "coa"])
def test_missing_and_unknown_fields_are_rejected(name: str) -> None:
    key = BODY_KEY[name]
    missing = DOCUMENTS[name]()
    del missing[key][0][next(iter(missing[key][0]))]
    unknown = DOCUMENTS[name]()
    unknown[key][0]["extra"] = 1
    top_level = DOCUMENTS[name]()
    top_level["extra"] = 1
    for document in (missing, unknown, top_level):
        with pytest.raises(_contracts().ContractError):
            _parse(name, document)


@pytest.mark.parametrize("name", ["corpus", "coa"])
@pytest.mark.parametrize("document", [None, [], "corpus", 1])
def test_a_non_object_document_is_rejected(name: str, document: object) -> None:
    with pytest.raises(_contracts().ContractError):
        _parse(name, document)


def test_coa_rejects_a_non_boolean_placeholder_and_a_malformed_commodity() -> None:
    bad_placeholder = _with("coa", lambda d: _account(d, "placeholder", 0))
    bad_commodity = _with("coa", lambda d: _account(d, "commodity", "EUR"))
    empty_mnemonic = _with("coa", lambda d: d["accounts"][0]["commodity"].update(mnemonic=""))
    for document in (bad_placeholder, bad_commodity, empty_mnemonic):
        with pytest.raises(_contracts().ContractError):
            _parse("coa", document)


# --- the coa account type is GnuCash's closed set -----------------------------------

GNUCASH_ACCOUNT_TYPES = (
    "NONE",
    "BANK",
    "CASH",
    "CREDIT",
    "ASSET",
    "LIABILITY",
    "STOCK",
    "MUTUAL",
    "CURRENCY",
    "INCOME",
    "EXPENSE",
    "EQUITY",
    "RECEIVABLE",
    "PAYABLE",
    "ROOT",
    "TRADING",
    "CHECKING",
    "SAVINGS",
    "MONEYMRKT",
    "CREDITLINE",
)


@pytest.mark.parametrize("account_type", GNUCASH_ACCOUNT_TYPES)
def test_coa_accepts_every_gnucash_account_type(account_type: str) -> None:
    document = _with("coa", lambda d: _account(d, "type", account_type))
    assert _parse("coa", document).accounts[0].type == account_type


# ["BANK"], {} and {"x": 1} are unhashable: they must still be a ContractError,
# not the TypeError a set lookup would raise.
BAD_ACCOUNT_TYPES = [
    "equity",
    "Equity",
    "EQUITYY",
    "",
    " BANK",
    1,
    None,
    ["BANK"],
    {},
    {"x": 1},
]


@pytest.mark.parametrize("account_type", BAD_ACCOUNT_TYPES)
def test_coa_rejects_an_account_type_outside_gnucash_set(account_type: object) -> None:
    document = _with("coa", lambda d: _account(d, "type", account_type))
    with pytest.raises(_contracts().ContractError):
        _parse("coa", document)


@pytest.mark.parametrize("account_type", BAD_ACCOUNT_TYPES)
def test_coa_json_text_rejects_an_account_type_outside_gnucash_set(
    account_type: object,
) -> None:
    contracts = _contracts()
    text = json.dumps(_with("coa", lambda d: _account(d, "type", account_type)))
    with pytest.raises(contracts.ContractError):
        contracts.coa_from_json(text)


@pytest.mark.parametrize("account_type", BAD_ACCOUNT_TYPES)
def test_coa_account_rejects_a_type_outside_gnucash_set_on_construction(
    account_type: object,
) -> None:
    with pytest.raises(_contracts().ContractError):
        _coa_account(type=account_type)


# --- contract objects check themselves, so serialise cannot write a bad document ---


def _corpus_row(**changes: object) -> Any:
    fields: dict[str, object] = {
        "raw_memo": "MUSTERBAECKEREI REF 17",
        "amount_cents": 420,
        "sign": "out",
        "source_account": ("Aktiva", "Revolut"),
        "destination_account": ("Ausgaben", "Lebensmittel"),
        "post_date": datetime.date(2026, 3, 9),
    }
    fields.update(changes)
    return _contracts().CorpusRow(**fields)


def _coa_account(**changes: object) -> Any:
    contracts = _contracts()
    fields: dict[str, object] = {
        "path": ("Einnahmen", "Gehalt"),
        "type": "INCOME",
        "placeholder": False,
        "commodity": contracts.Commodity(namespace="CURRENCY", mnemonic="EUR"),
        "fraction": 100,
    }
    fields.update(changes)
    return contracts.CoaAccount(**fields)


def test_the_object_builders_here_make_valid_objects() -> None:
    # guards the negative cases below: each one changes exactly one field
    contracts = _contracts()
    contracts.serialise_corpus(contracts.CorpusContract(rows=(_corpus_row(),)))
    contracts.serialise_coa(contracts.CoaContract(accounts=(_coa_account(),)))


@pytest.mark.parametrize("field", ["source_account", "destination_account"])
@pytest.mark.parametrize(
    "path", ["Aktiva", "Aktiva:Girokonto", ["Aktiva", "Girokonto"], (), ("Aktiva", "")]
)
def test_corpus_row_rejects_an_account_that_is_not_a_component_tuple(
    field: str, path: object
) -> None:
    # A str would otherwise be written as one component per character.
    with pytest.raises(_contracts().ContractError):
        _corpus_row(**{field: path})


@pytest.mark.parametrize("path", ["Aktiva", ["Aktiva"], (), ("",)])
def test_coa_account_rejects_a_path_that_is_not_a_component_tuple(path: object) -> None:
    with pytest.raises(_contracts().ContractError):
        _coa_account(path=path)


@pytest.mark.parametrize(
    "changes",
    [
        {"amount_cents": 12.5},
        {"amount_cents": True},
        {"amount_cents": 0},
        {"sign": "debit"},
        {"provenance": "corrected"},
        {"post_date": "2026-03-09"},
        {"post_date": datetime.datetime(2026, 3, 9, 12, 0)},
        {"raw_memo": None},
    ],
)
def test_corpus_row_rejects_a_bad_field_on_construction(changes: dict[str, object]) -> None:
    with pytest.raises(_contracts().ContractError):
        _corpus_row(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"fraction": 12.5},
        {"fraction": True},
        {"fraction": 0},
        {"type": "equity"},
        {"placeholder": 0},
        {"commodity": ("CURRENCY", "EUR")},
    ],
)
def test_coa_account_rejects_a_bad_field_on_construction(changes: dict[str, object]) -> None:
    with pytest.raises(_contracts().ContractError):
        _coa_account(**changes)


def test_commodity_rejects_an_empty_mnemonic_on_construction() -> None:
    contracts = _contracts()
    with pytest.raises(contracts.ContractError):
        contracts.Commodity(namespace="CURRENCY", mnemonic="")


@pytest.mark.parametrize(
    ("contract", "field", "make_items"),
    [
        ("CorpusContract", "rows", lambda: [_corpus_row()]),
        ("CorpusContract", "rows", lambda: ({"raw_memo": "x"},)),
        ("CoaContract", "accounts", lambda: [_coa_account()]),
        ("CoaContract", "accounts", lambda: (_corpus_row(),)),
    ],
)
def test_contracts_reject_items_that_are_not_a_tuple_of_contract_objects(
    contract: str, field: str, make_items: Any
) -> None:
    contracts = _contracts()
    items = make_items()
    with pytest.raises(contracts.ContractError):
        getattr(contracts, contract)(**{field: items})

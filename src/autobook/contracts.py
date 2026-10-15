"""The versioned JSON contracts between the pipeline and the book process.

Building block: the "JSON contracts" of ch.5 section 5.1
(`docs/design/architecture/05-building-block-view.md`). This step defines the
two book -> pipeline contracts the corpus export needs, ``corpus`` and ``coa``.
``existing``, ``apply-in`` and ``apply-out`` arrive with the steps that use them.

**Standard library only, and never ``gnucash``.** The pipeline venv and the book
process's system Python both import this module.

Wire shape. A document is a JSON object that carries its ``contract`` name and an
integer ``version``; a reader accepts only a name and version it knows::

    {"contract": "corpus", "version": 1, "rows": [...]}
    {"contract": "coa", "version": 1, "accounts": [...]}

Three rules hold for every contract. ``parse_*`` rejects a document that breaks
one with :class:`ContractError`, and so does building a contract object directly,
so ``serialise_*`` can only write a document that ``parse_*`` accepts:

* money is a plain ``int`` of cents. A ``float`` and a ``bool`` (a subclass of
  ``int`` in Python) are both refused;
* an account is a non-empty sequence of non-empty path components (a JSON array
  on the wire, a tuple in an object; a bare string is refused). GnuCash's account
  separator is a user preference outside the book, so nothing here joins or
  splits a path on a separator character;
* no field is missing, none is unknown, and closed-set values (``sign``,
  ``provenance``, the GnuCash account ``type``) are checked.
"""

from __future__ import annotations

import datetime
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final, Literal, NoReturn, TypeVar

__all__ = [
    "ACCOUNT_TYPES",
    "COA_NAME",
    "COA_VERSION",
    "CORPUS_NAME",
    "CORPUS_VERSION",
    "CoaAccount",
    "CoaContract",
    "Commodity",
    "ContractError",
    "CorpusContract",
    "CorpusRow",
    "Sign",
    "coa_from_json",
    "coa_to_json",
    "corpus_from_json",
    "corpus_to_json",
    "parse_coa",
    "parse_corpus",
    "serialise_coa",
    "serialise_corpus",
]

CORPUS_NAME: Final = "corpus"
CORPUS_VERSION: Final = 1
COA_NAME: Final = "coa"
COA_VERSION: Final = 1

# Direction of the money relative to ``source_account``: "out" leaves it (a
# payment), "in" enters it (a receipt). ``amount_cents`` is the magnitude, so the
# direction lives here and the kNN index can be keyed by (source_account, sign).
Sign = Literal["out", "in"]
_SIGNS: Final[tuple[str, ...]] = ("out", "in")

# The corpus comes from the book, so every row is observed; "corrected" rows are
# added by the pipeline from staging and never travel over this contract.
_PROVENANCE: Final = "observed"

_T = TypeVar("_T")

_ISO_DATE: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

# GnuCash's account-type names (``xaccAccountTypeEnumAsString``), exact case. The
# LLM label check filters on these, so a misspelt type must not pass as a new one.
ACCOUNT_TYPES: Final[frozenset[str]] = frozenset(
    {
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
    }
)


class ContractError(ValueError):
    """A contract document or contract object was not accepted."""


# Every contract object checks its own fields when it is built, so an object that
# exists is one ``serialise_*`` may write. ``parse_*`` only turns JSON shapes into
# Python ones (array -> tuple, string -> date) and leaves the value rules to these.


@dataclass(frozen=True)
class CorpusRow:
    """One two-split transaction exported from the book."""

    raw_memo: str
    amount_cents: int
    sign: Sign
    source_account: tuple[str, ...]
    destination_account: tuple[str, ...]
    post_date: datetime.date
    provenance: Literal["observed"] = "observed"

    def __post_init__(self) -> None:
        _text(self.raw_memo, "raw_memo")
        _cents(self.amount_cents, "amount_cents", minimum=1)
        if self.sign not in _SIGNS:
            _fail("sign", f"expected one of {list(_SIGNS)}, got {self.sign!r}")
        _path(self.source_account, "source_account")
        _path(self.destination_account, "destination_account")
        # datetime is a subclass of date and would serialise with a time part.
        if type(self.post_date) is not datetime.date:
            _fail("post_date", f"expected a date, got {type(self.post_date).__name__}")
        if self.provenance != _PROVENANCE:
            _fail(
                "provenance",
                f"the corpus contract accepts only {_PROVENANCE!r}, got {self.provenance!r}",
            )


@dataclass(frozen=True)
class CorpusContract:
    rows: tuple[CorpusRow, ...]

    def __post_init__(self) -> None:
        _items(self.rows, "rows", CorpusRow)


@dataclass(frozen=True)
class Commodity:
    namespace: str
    mnemonic: str

    def __post_init__(self) -> None:
        _text(self.namespace, "namespace", non_empty=True)
        _text(self.mnemonic, "mnemonic", non_empty=True)


@dataclass(frozen=True)
class CoaAccount:
    """One account of the live tree; ``path`` excludes the root account."""

    path: tuple[str, ...]
    type: str
    placeholder: bool
    commodity: Commodity
    fraction: int

    def __post_init__(self) -> None:
        _path(self.path, "path")
        # String check first: the set lookup hashes the value, and a JSON array or
        # object would raise TypeError there instead of ContractError.
        if _text(self.type, "type") not in ACCOUNT_TYPES:
            _fail("type", f"not a GnuCash account type: {self.type!r}")
        _flag(self.placeholder, "placeholder")
        if type(self.commodity) is not Commodity:
            _fail("commodity", f"expected a Commodity, got {type(self.commodity).__name__}")
        _cents(self.fraction, "fraction", minimum=1)


@dataclass(frozen=True)
class CoaContract:
    accounts: tuple[CoaAccount, ...]

    def __post_init__(self) -> None:
        _items(self.accounts, "accounts", CoaAccount)


# --- validation helpers ------------------------------------------------------------


def _fail(where: str, message: str) -> NoReturn:
    raise ContractError(f"{where}: {message}")


def _mapping(value: object, where: str, keys: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(where, f"expected a JSON object, got {type(value).__name__}")
    found = set(value)
    missing = [key for key in keys if key not in found]
    unknown = sorted(str(key) for key in found - set(keys))
    if missing:
        _fail(where, f"missing field(s): {', '.join(missing)}")
    if unknown:
        _fail(where, f"unknown field(s): {', '.join(unknown)}")
    return value


def _header(document: object, name: str, version: int, body: str) -> dict[str, Any]:
    mapping = _mapping(document, name, ("contract", "version", body))
    if mapping["contract"] != name:
        _fail(name, f"contract name is {mapping['contract']!r}, expected {name!r}")
    found = mapping["version"]
    # `type(...) is int` on purpose: True == 1 and 1.0 == 1, neither is a version.
    if type(found) is not int or found != version:
        _fail(name, f"unsupported version {found!r}; this code reads version {version}")
    return mapping


def _text(value: object, where: str, *, non_empty: bool = False) -> str:
    if not isinstance(value, str):
        _fail(where, f"expected a string, got {type(value).__name__}")
    if non_empty and not value:
        _fail(where, "must not be empty")
    return value


def _cents(value: object, where: str, *, minimum: int) -> int:
    # bool is a subclass of int, so isinstance() would let True through.
    if type(value) is not int:
        _fail(where, f"expected an integer, got {type(value).__name__}")
    if value < minimum:
        _fail(where, f"must be at least {minimum}, got {value}")
    return value


def _flag(value: object, where: str) -> bool:
    if type(value) is not bool:
        _fail(where, f"expected true or false, got {type(value).__name__}")
    return value


def _path(value: object, where: str) -> None:
    # A str is itself a sequence, so without the tuple check "Aktiva" would pass
    # as the six components "A", "k", "t", ... and be written that way.
    if not isinstance(value, tuple) or not value:
        _fail(where, "an account is a non-empty tuple of path components")
    for i, part in enumerate(value):
        _text(part, f"{where}[{i}]", non_empty=True)


def _items(value: object, where: str, kind: type) -> None:
    if not isinstance(value, tuple):
        _fail(where, f"expected a tuple, got {type(value).__name__}")
    for i, item in enumerate(value):
        if type(item) is not kind:
            _fail(f"{where}[{i}]", f"expected a {kind.__name__}, got {type(item).__name__}")


def _components(value: object, where: str) -> tuple[str, ...]:
    """A JSON array of path components as a tuple; the object checks the parts."""
    if not isinstance(value, list):
        _fail(where, "an account is a non-empty list of path components")
    return tuple(value)


def _build(where: str, factory: Callable[..., _T], **fields: object) -> _T:
    """Construct a contract object, naming the document location on failure."""
    try:
        return factory(**fields)
    except ContractError as exc:
        raise ContractError(f"{where}.{exc}") from None


def _date(value: object, where: str) -> datetime.date:
    text = _text(value, where)
    # fromisoformat() alone also takes "20260102" and "2026-W01-5" on 3.11+.
    if not _ISO_DATE.fullmatch(text):
        _fail(where, f"expected YYYY-MM-DD, got {text!r}")
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        _fail(where, f"not a calendar date: {text!r}")


def _list(value: object, where: str) -> list[Any]:
    if not isinstance(value, list):
        _fail(where, f"expected a JSON array, got {type(value).__name__}")
    return value


# --- corpus -----------------------------------------------------------------------

_ROW_KEYS: Final = (
    "raw_memo",
    "amount_cents",
    "sign",
    "source_account",
    "destination_account",
    "post_date",
    "provenance",
)


def parse_corpus(document: object) -> CorpusContract:
    """Validate a decoded ``corpus`` document and return it as an object."""
    body = _header(document, CORPUS_NAME, CORPUS_VERSION, "rows")
    rows: list[CorpusRow] = []
    for i, raw in enumerate(_list(body["rows"], "corpus.rows")):
        where = f"corpus.rows[{i}]"
        row = _mapping(raw, where, _ROW_KEYS)
        rows.append(
            _build(
                where,
                CorpusRow,
                raw_memo=row["raw_memo"],
                amount_cents=row["amount_cents"],
                sign=row["sign"],
                source_account=_components(row["source_account"], f"{where}.source_account"),
                destination_account=_components(
                    row["destination_account"], f"{where}.destination_account"
                ),
                post_date=_date(row["post_date"], f"{where}.post_date"),
                provenance=row["provenance"],
            )
        )
    return CorpusContract(rows=tuple(rows))


def serialise_corpus(corpus: CorpusContract) -> dict[str, Any]:
    """The canonical document for ``corpus``; ``parse_corpus`` reads it back."""
    return {
        "contract": CORPUS_NAME,
        "version": CORPUS_VERSION,
        "rows": [
            {
                "raw_memo": row.raw_memo,
                "amount_cents": row.amount_cents,
                "sign": row.sign,
                "source_account": list(row.source_account),
                "destination_account": list(row.destination_account),
                "post_date": row.post_date.isoformat(),
                "provenance": row.provenance,
            }
            for row in corpus.rows
        ],
    }


def corpus_to_json(corpus: CorpusContract) -> str:
    return json.dumps(serialise_corpus(corpus), ensure_ascii=False)


def corpus_from_json(text: str) -> CorpusContract:
    return parse_corpus(_decode(text, CORPUS_NAME))


# --- coa --------------------------------------------------------------------------

_ACCOUNT_KEYS: Final = ("path", "type", "placeholder", "commodity", "fraction")


def parse_coa(document: object) -> CoaContract:
    """Validate a decoded ``coa`` document and return it as an object."""
    body = _header(document, COA_NAME, COA_VERSION, "accounts")
    accounts: list[CoaAccount] = []
    for i, raw in enumerate(_list(body["accounts"], "coa.accounts")):
        where = f"coa.accounts[{i}]"
        account = _mapping(raw, where, _ACCOUNT_KEYS)
        commodity = _mapping(
            account["commodity"], f"{where}.commodity", ("namespace", "mnemonic")
        )
        accounts.append(
            _build(
                where,
                CoaAccount,
                path=_components(account["path"], f"{where}.path"),
                type=account["type"],
                placeholder=account["placeholder"],
                commodity=_build(
                    f"{where}.commodity",
                    Commodity,
                    namespace=commodity["namespace"],
                    mnemonic=commodity["mnemonic"],
                ),
                fraction=account["fraction"],
            )
        )
    return CoaContract(accounts=tuple(accounts))


def serialise_coa(coa: CoaContract) -> dict[str, Any]:
    """The canonical document for ``coa``; ``parse_coa`` reads it back."""
    return {
        "contract": COA_NAME,
        "version": COA_VERSION,
        "accounts": [
            {
                "path": list(account.path),
                "type": account.type,
                "placeholder": account.placeholder,
                "commodity": {
                    "namespace": account.commodity.namespace,
                    "mnemonic": account.commodity.mnemonic,
                },
                "fraction": account.fraction,
            }
            for account in coa.accounts
        ],
    }


def coa_to_json(coa: CoaContract) -> str:
    return json.dumps(serialise_coa(coa), ensure_ascii=False)


def coa_from_json(text: str) -> CoaContract:
    return parse_coa(_decode(text, COA_NAME))


def _decode(text: str, name: str) -> object:
    try:
        return json.loads(text)
    except ValueError as exc:
        raise ContractError(f"{name}: not valid JSON: {exc}") from exc

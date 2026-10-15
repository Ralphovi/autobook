"""Normaliser — building block of ch.5 section 5.2.

Design: `docs/design/architecture/05-building-block-view.md`.

Turns a raw bank memo into the merchant token the classifier works on, and is the
only place that does (ch.8 section 8.4). It is driven by data: named *profiles*,
ordered lists of regular expressions whose matches are removed, shipped in the
package (`profiles/`) and replaceable from the user directory, where
``accounts.toml`` picks a profile per source account.

``Normaliser.version`` changes whenever anything that can change a token changes:
the code (``NORMALISER_VERSION``), any effective profile rule, the account mapping
or the interpreter's Unicode database. That string, never ``NORMALISER_VERSION``
alone, is what gets recorded, so no vector, backtest or proposal can mix two
normalisations.

Pipeline module: must never import `gnucash`.
"""

from __future__ import annotations

import hashlib
import importlib.resources
import json
import os
import re
import stat
import tomllib
import unicodedata
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

__all__ = [
    "NORMALISER_VERSION",
    "NormalisedMemo",
    "Normaliser",
    "NormaliserError",
    "load",
]

# The code's algorithm version. Bump it when the code (not a profile) changes what a
# token looks like. It is one input to `Normaliser.version` and never recorded alone.
NORMALISER_VERSION: Final[int] = 1

_PACKAGE: Final = "autobook.pipeline"
_PACKAGE_PROFILES: Final = "profiles"
_SUFFIX: Final = ".toml"
_DEFAULT: Final = "default"
_ACCOUNTS: Final = "accounts"
_PROFILE_KEYS: Final = frozenset({"rules", "extends"})
_RULE_KEYS: Final = frozenset({"pattern"})
_ACCOUNTS_KEYS: Final = frozenset({_ACCOUNTS})
_ENTRY_KEYS: Final = frozenset({"path", "profile"})
_DIGEST_DIGITS: Final = 12

# Only `load` holds this, so only `load` can build a `Normaliser`.
_BUILT_BY_LOAD: Final = object()

_Rules = tuple[re.Pattern[str], ...]


class NormaliserError(ValueError):
    """A profile, the account mapping, the user directory or an input was not accepted."""


@dataclass(frozen=True)
class NormalisedMemo:
    """One memo after normalisation, with the profile and version that produced it.

    Neither the memo nor the token is in the ``repr``: the token is the memo with its
    noise removed, so a logged result would otherwise carry the memo (ch.8 section 8.5).
    """

    raw_memo: str = field(repr=False)
    token: str = field(repr=False)
    profile: str
    version: str


@dataclass(frozen=True)
class _Profile:
    source: str  # the file it came from, for error messages
    extends: str | None
    rules: _Rules


class Normaliser:
    """Normalises memos with one loaded set of profiles. Built only by :func:`load`."""

    def __init__(
        self,
        key: object,
        version: str,
        rules: Mapping[str, _Rules],
        accounts: Mapping[tuple[str, ...], str],
    ) -> None:
        if key is not _BUILT_BY_LOAD:
            raise TypeError("a Normaliser is built only by load()")
        self.version: Final[str] = version
        self._rules: Final = dict(rules)
        self._accounts: Final = dict(accounts)

    def normalise(self, raw_memo: str, source_account: tuple[str, ...]) -> NormalisedMemo:
        """Return the token for ``raw_memo`` under the profile mapped to the account."""
        _check_input(raw_memo, source_account)
        profile = self._accounts.get(source_account, _DEFAULT)
        text = raw_memo.upper()
        for rule in self._rules[profile]:
            text = rule.sub(" ", text)
        return NormalisedMemo(
            raw_memo=raw_memo,
            token=" ".join(text.split()),
            profile=profile,
            version=self.version,
        )


def load(user_dir: Path | None = None) -> Normaliser:
    """Read the package profiles and the user directory; return a ready normaliser.

    ``None`` means ``$XDG_CONFIG_HOME/autobook/normaliser/``, or
    ``~/.config/autobook/normaliser/`` when ``XDG_CONFIG_HOME`` is unset, empty or
    not absolute. A directory that does not exist means package profiles only.
    Raises :class:`NormaliserError` for every bad input; nothing falls back silently.
    """
    directory = _default_user_dir() if user_dir is None else Path(user_dir)
    package = _package_profiles()
    files = _user_files(directory)
    accounts_file = files.pop(_ACCOUNTS, None)
    user = {name: _parse_profile(str(path), _read(path)) for name, path in files.items()}
    profiles = {**package, **user}  # a user file replaces the package profile entirely
    rules = _resolve(profiles)
    accounts = {} if accounts_file is None else _parse_accounts(accounts_file, profiles)
    _check_used(files, package, profiles, accounts)
    return Normaliser(_BUILT_BY_LOAD, _version(rules, accounts), rules, accounts)


# --- reading ----------------------------------------------------------------------


def _default_user_dir() -> Path:
    # The XDG Base Directory spec: a relative value is invalid and is ignored.
    config = os.environ.get("XDG_CONFIG_HOME", "")
    base = Path(config) if config and os.path.isabs(config) else Path.home() / ".config"
    return base / "autobook" / "normaliser"


def _profile_name(file_name: str) -> str | None:
    """The profile (or mapping) name a directory entry stands for, or None to ignore it."""
    if file_name.startswith(".") or not file_name.endswith(_SUFFIX):
        return None
    return file_name[: -len(_SUFFIX)]


def _package_profiles() -> dict[str, _Profile]:
    directory = importlib.resources.files(_PACKAGE).joinpath(_PACKAGE_PROFILES)
    profiles: dict[str, _Profile] = {}
    try:
        for entry in directory.iterdir():
            name = _profile_name(entry.name)
            if name is None:
                continue
            if name == _ACCOUNTS or not entry.is_file():
                raise NormaliserError(f"{entry}: not a profile file")
            profiles[name] = _parse_profile(str(entry), entry.read_bytes())
    except OSError as exc:
        raise NormaliserError(f"{directory}: cannot read the package profiles") from exc
    if _DEFAULT not in profiles:
        raise NormaliserError(f"{directory}: the package ships no {_DEFAULT}{_SUFFIX}")
    return profiles


def _user_files(directory: Path) -> dict[str, Path]:
    """The ``*.toml`` files at the top of the user directory, by name."""
    try:
        # Not Path.glob: it swallows PermissionError, and an unreadable directory
        # would then look empty.
        with os.scandir(directory) as entries:
            names = sorted(entry.name for entry in entries)
    except FileNotFoundError:
        if os.path.lexists(directory):
            raise NormaliserError(
                f"{directory}: the user directory is a dangling symlink"
            ) from None
        return {}
    except NotADirectoryError:
        raise NormaliserError(f"{directory}: the user directory is not a directory") from None
    except OSError as exc:
        raise NormaliserError(
            f"{directory}: cannot list the user directory ({exc.strerror})"
        ) from exc
    files: dict[str, Path] = {}
    for file_name in names:
        name = _profile_name(file_name)
        if name is None:
            continue
        path = directory / file_name
        try:
            mode = path.stat().st_mode
        except OSError as exc:
            raise NormaliserError(f"{path}: not a regular file ({exc.strerror})") from exc
        if not stat.S_ISREG(mode):
            raise NormaliserError(f"{path}: not a regular file")
        files[name] = path
    return files


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise NormaliserError(f"{path}: cannot read ({exc.strerror})") from exc


def _toml(source: str, data: bytes) -> dict[str, Any]:
    try:
        return tomllib.loads(data.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise NormaliserError(f"{source}: not UTF-8 text") from exc
    except tomllib.TOMLDecodeError as exc:
        raise NormaliserError(f"{source}: not valid TOML: {exc}") from exc


def _check_keys(
    where: str,
    table: object,
    allowed: frozenset[str],
    kind: str,
) -> dict[str, Any]:
    if not isinstance(table, dict):
        raise NormaliserError(f"{where}: expected {kind}")
    unknown = sorted(str(key) for key in set(table) - allowed)
    if unknown:
        known = ", ".join(sorted(allowed))
        raise NormaliserError(f"{where}: unknown key(s) {', '.join(unknown)}; allowed: {known}")
    return table


def _tables(where: str, value: object, header: str) -> list[object]:
    if not isinstance(value, list):
        raise NormaliserError(f"{where}: `{header}` must be an array of tables ([[{header}]])")
    return value


# --- profiles ---------------------------------------------------------------------


def _parse_profile(source: str, data: bytes) -> _Profile:
    document = _check_keys(source, _toml(source, data), _PROFILE_KEYS, "a TOML document")
    extends = document.get("extends")
    if extends is not None and not isinstance(extends, str):
        raise NormaliserError(f"{source}: `extends` must be a string, the name of a profile")
    rules: list[re.Pattern[str]] = []
    for number, raw in enumerate(_tables(source, document.get("rules", []), "rules"), 1):
        where = f"{source}: rule {number}"
        rule = _check_keys(where, raw, _RULE_KEYS, "a table with one key, `pattern`")
        pattern = rule.get("pattern")
        if not isinstance(pattern, str):
            raise NormaliserError(f"{where}: `pattern` must be a string")
        try:
            rules.append(re.compile(pattern, re.IGNORECASE))
        except re.error as exc:
            # The pattern itself stays out of the message: it may name a person.
            raise NormaliserError(f"{where}: the pattern does not compile ({exc})") from exc
    return _Profile(source=source, extends=extends, rules=tuple(rules))


def _resolve(profiles: Mapping[str, _Profile]) -> dict[str, _Rules]:
    """Each profile's effective rules: its own, then those of the profile it extends."""
    effective: dict[str, _Rules] = {}
    for name in sorted(profiles):
        chain = [name]
        while (parent := profiles[chain[-1]].extends) is not None:
            source = profiles[chain[-1]].source
            if parent not in profiles:
                raise NormaliserError(f"{source}: `extends` names {parent!r}, not a profile")
            if parent in chain:
                # Name every file in the cycle: the one closing it may be a package file.
                members = chain[chain.index(parent) :]
                files = ", ".join(profiles[member].source for member in members)
                cycle = " -> ".join([*members, parent])
                raise NormaliserError(f"{files}: `extends` makes a cycle: {cycle}")
            chain.append(parent)
        effective[name] = tuple(rule for link in chain for rule in profiles[link].rules)
    return effective


# --- the account mapping ----------------------------------------------------------


def _parse_accounts(path: Path, profiles: Collection[str]) -> dict[tuple[str, ...], str]:
    source = str(path)
    document = _check_keys(source, _toml(source, _read(path)), _ACCOUNTS_KEYS, "a document")
    mapping: dict[tuple[str, ...], str] = {}
    entry_of: dict[tuple[str, ...], int] = {}
    for number, raw in enumerate(_tables(source, document.get(_ACCOUNTS, []), _ACCOUNTS), 1):
        # Entries are named by number: an account path is personal data.
        where = f"{source}: entry {number}"
        entry = _check_keys(where, raw, _ENTRY_KEYS, "a table with `path` and `profile`")
        missing = sorted(_ENTRY_KEYS - set(entry))
        if missing:
            raise NormaliserError(f"{where}: missing key(s) {', '.join(missing)}")
        components, profile = entry["path"], entry["profile"]
        if (
            not isinstance(components, list)
            or not components
            or not all(isinstance(part, str) and part for part in components)
        ):
            raise NormaliserError(
                f"{where}: `path` must be a non-empty array of non-empty strings, "
                "one per account path component"
            )
        if not isinstance(profile, str):
            raise NormaliserError(f"{where}: `profile` must be a string")
        if profile not in profiles:
            raise NormaliserError(f"{where}: `profile` names {profile!r}, not a profile")
        account = tuple(components)
        if account in entry_of:
            raise NormaliserError(
                f"{where}: maps the same account as entry {entry_of[account]}"
            )
        entry_of[account] = number
        mapping[account] = profile
    return mapping


def _check_used(
    user: Mapping[str, Path],
    package: Collection[str],
    profiles: Mapping[str, _Profile],
    accounts: Mapping[tuple[str, ...], str],
) -> None:
    """A user profile nothing uses is a typo (``defualt.toml``), not a profile."""
    used = {*package, *accounts.values()}
    used.update(profile.extends for profile in profiles.values() if profile.extends)
    unused = sorted(set(user) - used)
    if unused:
        raise NormaliserError(
            f"{user[unused[0]]}: the profile {unused[0]!r} is not used: it replaces no "
            f"package profile ({', '.join(sorted(package))}), no {_ACCOUNTS}{_SUFFIX} "
            "entry maps it and no profile extends it"
        )


# --- the version ------------------------------------------------------------------


def _version(rules: Mapping[str, _Rules], accounts: Mapping[tuple[str, ...], str]) -> str:
    """``<NORMALISER_VERSION>-<digest>`` over everything that can change a token.

    Canonical: sorted by profile name and account path, and free of file paths, file
    names and timestamps, so the same files give the same version from any directory.
    """
    canonical = json.dumps(
        {
            "normaliser": NORMALISER_VERSION,
            # str.upper() and the regex classes \d, \b, \s follow the Unicode database.
            # Read through the module, not imported by name, so a test can patch it.
            "unicode": unicodedata.unidata_version,
            "profiles": [
                [name, [rule.pattern for rule in rules[name]]] for name in sorted(rules)
            ],
            "accounts": [[list(account), accounts[account]] for account in sorted(accounts)],
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{NORMALISER_VERSION}-{digest[:_DIGEST_DIGITS]}"


# --- input checks -----------------------------------------------------------------


def _check_input(raw_memo: object, source_account: object) -> None:
    # Typed `object` so the runtime checks are not dead code to the type checker. The
    # messages never carry the memo or the account names.
    if not isinstance(raw_memo, str):
        raise NormaliserError(f"raw_memo: expected a string, got {type(raw_memo).__name__}")
    if (
        not isinstance(source_account, tuple)
        or not source_account
        or not all(isinstance(part, str) and part for part in source_account)
    ):
        raise NormaliserError(
            "source_account: an account is a non-empty tuple of non-empty path components"
        )

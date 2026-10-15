"""The normaliser: profiles, the account mapping and the version (ch.5 section 5.2).

Every memo, name, creditor ID and IBAN here is invented. Creditor IDs carry `ZZZ`,
and IBAN values start `DE00ZZZ`, which no real IBAN does.

Only modules that exist without this change are imported at module scope. Every name
the normaliser adds is reached through the module object inside a test, so with the
change reverted each test runs and fails instead of the file failing to import.

A user directory is always under `tmp_path`, passed to `load` or reached through
`XDG_CONFIG_HOME` / `HOME`; no test reads the real one.
"""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path
from typing import Any

import pytest

from autobook.pipeline import normaliser
from tests.fixtures.synthetic import corpus_builder

GIROKONTO = corpus_builder.GIROKONTO
REVOLUT = corpus_builder.REVOLUT

# A synthetic value for each SEPA tag whose value is kept.
KEPT_VALUES = {
    "CRED+": "DE98ZZZ09999999999",
    "SVWZ+": "MITGLIEDSBEITRAG",
    "ABWA+": "MUSTER VEREIN",
    "ABWE+": "BEISPIEL VERBAND",
}
# A synthetic value for each SEPA tag whose value is dropped. Letters and digits are
# glued together, so no `default` rule can remove one of these: only the SEPA rule can.
DROPPED_VALUES = {
    "EREF+": "ZZZENDTOEND0815",
    "KREF+": "ZZZKUNDENREF4711",
    "MREF+": "ZZZMANDAT0042",
    "DEBT+": "DE77ZZZ00000004711",
    "COAM+": "ZZZBETRAG0100",
    "OAMT+": "ZZZBETRAG0200",
    "IBAN+": "DE00ZZZ00000000000000",
    "BIC+": "TESTDEFFXXX",
    "BREF+": "ZZZBANKREF0001",
    "RREF+": "ZZZRETOURE0002",
    "PURP+": "ZZZZWECK",
}
# The full SEPA tag set, in the order of ch.5 section 5.2.
SEPA_TAGS = (
    "EREF+",
    "KREF+",
    "MREF+",
    "CRED+",
    "DEBT+",
    "COAM+",
    "OAMT+",
    "SVWZ+",
    "ABWA+",
    "ABWE+",
    "IBAN+",
    "BIC+",
    "BREF+",
    "RREF+",
    "PURP+",
)

# A replacement for the package `default` without the digit-run rule: under it the
# digits of `NOISY` stay in the token, so it is visible which `default` applied.
DEFAULT_WITHOUT_DIGITS = r"""
[[rules]]
pattern = '\bSAGT\s+DANKE\b'
"""
NOISY = "BEISPIELMARKT SAGT DANKE 4711"

# A user `sepa` override, for the version tests.
SEPA_OVERRIDE = r"""
extends = "default"

[[rules]]
pattern = '(?:EREF|SVWZ)\+'
"""


def _write(directory: Path, name: str, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def _map(directory: Path, profile: str, account: tuple[str, ...] = GIROKONTO) -> Path:
    """Write an `accounts.toml` mapping one account to ``profile``."""
    components = ", ".join(f'"{part}"' for part in account)
    entry = f'[[accounts]]\npath = [{components}]\nprofile = "{profile}"\n'
    return _write(directory, "accounts.toml", entry)


def _sepa(directory: Path) -> normaliser.Normaliser:
    """A normaliser whose user directory maps GIROKONTO, and only it, to `sepa`."""
    _map(directory, "sepa")
    return normaliser.load(directory)


def _token(directory: Path, memo: str, account: tuple[str, ...] = GIROKONTO) -> str:
    return normaliser.load(directory).normalise(memo, account).token


def _rejected(directory: Path) -> str:
    """Load ``directory`` expecting a NormaliserError, and return its message."""
    with pytest.raises(normaliser.NormaliserError) as caught:
        normaliser.load(directory)
    return str(caught.value)


def _all_tags(tags: tuple[str, ...], separator: str) -> str:
    values = {**KEPT_VALUES, **DROPPED_VALUES}
    return separator.join(f"{tag}{values[tag]}" for tag in tags)


# --- the public API ---------------------------------------------------------------


def test_the_module_exports_exactly_the_normaliser_api() -> None:
    assert sorted(normaliser.__all__) == [
        "NORMALISER_VERSION",
        "NormalisedMemo",
        "Normaliser",
        "NormaliserError",
        "load",
    ]
    assert not hasattr(normaliser, "normalise")  # the stub's entry point is gone
    assert normaliser.NORMALISER_VERSION == 1
    assert issubclass(normaliser.NormaliserError, ValueError)


def test_a_normaliser_is_built_only_by_load(tmp_path: Path) -> None:
    version = normaliser.load(tmp_path).version
    with pytest.raises(TypeError):
        normaliser.Normaliser(object(), version, {}, {})


# --- (a) the synthetic corpus -----------------------------------------------------


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_every_corpus_memo_normalises_to_its_merchant_name(seed: int, tmp_path: Path) -> None:
    norm = normaliser.load(tmp_path)  # an empty user directory: package profiles only
    names = [merchant.token for merchant in corpus_builder.MERCHANTS]
    rows = corpus_builder.build_corpus(seed).rows
    wrong: list[tuple[str, str, str]] = []
    for row in rows:
        starts = [name for name in names if row.raw_memo.startswith(name)]
        assert len(starts) <= 1, row.raw_memo
        if not starts:
            assert row.raw_memo.startswith(corpus_builder.NOVEL_MERCHANT), row.raw_memo
        expected = starts[0] if starts else corpus_builder.NOVEL_MERCHANT
        result = norm.normalise(row.raw_memo, row.source_account)
        assert result.profile == "default"
        if result.token != expected:
            wrong.append((row.raw_memo, result.token, expected))
    assert rows
    assert wrong == []


def test_a_memo_that_is_all_noise_gives_an_empty_token(tmp_path: Path) -> None:
    assert _token(tmp_path, "SAGT DANKE 4711 05.03.") == ""


# --- (b) SEPA memos on an account mapped to `sepa` ----------------------------------


@pytest.mark.parametrize(
    "memo",
    [
        pytest.param(_all_tags(SEPA_TAGS, " "), id="spaced"),
        pytest.param(_all_tags(SEPA_TAGS, ""), id="glued"),
        pytest.param(_all_tags(SEPA_TAGS[::-1], " "), id="reversed"),
        pytest.param(_all_tags(SEPA_TAGS, " ").lower(), id="lower-case"),
        pytest.param(_all_tags((*DROPPED_VALUES, *KEPT_VALUES), "\n"), id="one-tag-per-line"),
    ],
)
def test_no_sepa_tag_and_no_dropped_value_survives(memo: str, tmp_path: Path) -> None:
    result = _sepa(tmp_path).normalise(memo, GIROKONTO)
    assert result.profile == "sepa"
    for tag in SEPA_TAGS:
        assert tag not in result.token
    for value in DROPPED_VALUES.values():
        assert value not in result.token
    # The kept values are all that is left.
    rest = result.token
    for value in KEPT_VALUES.values():
        assert value in rest
        rest = rest.replace(value, "")
    assert rest.strip() == ""


@pytest.mark.parametrize(
    ("memo", "values"),
    [
        pytest.param(
            "EREF+ZZZ0815 CRED+{} SVWZ+MITGLIEDSBEITRAG 01.2025",
            ("DE98ZZZ09999999999", "DE12ZZZ01111111111"),
            id="CRED+",
        ),
        pytest.param(
            "SVWZ+ZAHLUNG 4711 ABWA+{}", ("MUSTERBAECKEREI", "TESTHOF GEMUESE"), id="ABWA+"
        ),
        pytest.param(
            "SVWZ+MIETE 03.2025 ABWE+{} EREF+NOTPROVIDED",
            ("MUSTER HAUSVERWALTUNG", "BEISPIEL WOHNBAU"),
            id="ABWE+",
        ),
    ],
)
def test_memos_that_differ_only_in_a_kept_value_get_different_tokens(
    memo: str, values: tuple[str, str], tmp_path: Path
) -> None:
    norm = _sepa(tmp_path)
    first, second = (norm.normalise(memo.format(value), GIROKONTO).token for value in values)
    assert first != second
    assert values[0] in first
    assert values[1] in second


@pytest.mark.parametrize(
    ("memo", "expected"),
    [
        # A dropped value ends at the next tag of the full set, glued or not.
        ("SVWZ+MIETE EREF+1 ABWE+MUSTER HAUSVERWALTUNG", "MIETE MUSTER HAUSVERWALTUNG"),
        ("EREF+NOTPROVIDEDSVWZ+BEISPIELMARKT", "BEISPIELMARKT"),
        ("EREF+ZZZ0815\nSVWZ+BEISPIELMARKT", "BEISPIELMARKT"),
        # The results checked at Plan.
        (
            "EREF+1 CRED+DE98ZZZ01111111111 SVWZ+MITGLIEDSBEITRAG 01.2025",
            "DE98ZZZ01111111111 MITGLIEDSBEITRAG",
        ),
        ("SVWZ+ZAHLUNG 1234 ABWA+MUSTERBAECKEREI", "ZAHLUNG MUSTERBAECKEREI"),
        ("SVWZ+BEISPIELMARKT IBAN+DE00ZZZ BIC+TESTDEFF", "BEISPIELMARKT"),
        ("SVWZ+BEISPIELMARKT//MUENCHEN/DE 2025-03-05T10:11:12", "BEISPIELMARKT//MUENCHEN/DE"),
    ],
)
def test_sepa_memos_give_the_expected_token(memo: str, expected: str, tmp_path: Path) -> None:
    assert _sepa(tmp_path).normalise(memo, GIROKONTO).token == expected


def test_card_payments_that_differ_only_in_the_timestamp_get_the_same_token(
    tmp_path: Path,
) -> None:
    norm = _sepa(tmp_path)
    tokens = {
        norm.normalise(f"SVWZ+BEISPIELMARKT//MUENCHEN/DE {stamp}", GIROKONTO).token
        for stamp in ("2025-03-05T10:11:12", "2025-04-17T18:02:59")
    }
    assert tokens == {"BEISPIELMARKT//MUENCHEN/DE"}


def test_an_unmapped_account_uses_the_default_profile(tmp_path: Path) -> None:
    memo = "EREF+NOTPROVIDEDSVWZ+BEISPIELMARKT"
    result = _sepa(tmp_path).normalise(memo, REVOLUT)
    assert (result.profile, result.token) == ("default", memo)


# --- (c) user profiles replace package profiles -----------------------------------


def test_a_user_profile_replaces_the_package_profile_of_the_same_name(tmp_path: Path) -> None:
    assert _token(tmp_path, NOISY) == "BEISPIELMARKT"
    user_default = _write(tmp_path, "default.toml", DEFAULT_WITHOUT_DIGITS)
    assert _token(tmp_path, NOISY) == "BEISPIELMARKT 4711"
    user_default.unlink()
    assert _token(tmp_path, NOISY) == "BEISPIELMARKT"


def test_a_user_default_also_changes_accounts_mapped_to_sepa(tmp_path: Path) -> None:
    memo = f"SVWZ+{NOISY} EREF+NOTPROVIDED"
    before = _sepa(tmp_path).normalise(memo, GIROKONTO)
    assert (before.profile, before.token) == ("sepa", "BEISPIELMARKT")
    # The package `sepa` extends `default`, resolved after the user's overrides.
    _write(tmp_path, "default.toml", DEFAULT_WITHOUT_DIGITS)
    after = normaliser.load(tmp_path).normalise(memo, GIROKONTO)
    assert (after.profile, after.token) == ("sepa", "BEISPIELMARKT 4711")


def test_a_user_profile_extended_by_another_profile_is_used(tmp_path: Path) -> None:
    _write(tmp_path, "basis.toml", "[[rules]]\npattern = '\\bFILIALE\\b'\n")
    _write(tmp_path, "default.toml", 'extends = "basis"\n')
    assert _token(tmp_path, "BEISPIELMARKT FILIALE 4711") == "BEISPIELMARKT 4711"


def test_profile_names_are_case_sensitive(tmp_path: Path) -> None:
    # `Default.toml` adds a profile `Default`; it does not replace `default`.
    _write(tmp_path, "Default.toml", DEFAULT_WITHOUT_DIGITS)
    _map(tmp_path, "Default")
    norm = normaliser.load(tmp_path)
    mapped = norm.normalise(NOISY, GIROKONTO)
    unmapped = norm.normalise(NOISY, REVOLUT)
    assert (mapped.profile, mapped.token) == ("Default", "BEISPIELMARKT 4711")
    assert (unmapped.profile, unmapped.token) == ("default", "BEISPIELMARKT")


def test_a_profile_may_be_a_symlink_to_a_regular_file(tmp_path: Path) -> None:
    target = _write(tmp_path / "elsewhere", "kept.toml", DEFAULT_WITHOUT_DIGITS)
    directory = tmp_path / "normaliser"
    directory.mkdir()
    (directory / "default.toml").symlink_to(target)
    assert _token(directory, NOISY) == "BEISPIELMARKT 4711"


# --- (d) the version --------------------------------------------------------------


def test_the_same_files_give_the_same_version_from_any_directory(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    for directory in (first, second):
        _write(directory, "sepa.toml", SEPA_OVERRIDE)
        _map(directory, "sepa")
    os.utime(second / "sepa.toml", (0, 0))  # a different modification time, too
    version = normaliser.load(first).version
    assert re.fullmatch(rf"{normaliser.NORMALISER_VERSION}-[0-9a-f]{{12}}", version)
    assert normaliser.load(first).version == version
    assert normaliser.load(second).version == version
    empty = tmp_path / "empty"
    assert normaliser.load(empty).version == normaliser.load(empty).version != version


def test_changing_one_rule_changes_the_version(tmp_path: Path) -> None:
    _map(tmp_path, "sepa")
    _write(tmp_path, "sepa.toml", SEPA_OVERRIDE)
    before = normaliser.load(tmp_path).version
    _write(tmp_path, "sepa.toml", SEPA_OVERRIDE.replace("EREF", "KREF"))
    assert normaliser.load(tmp_path).version != before


def test_changing_one_line_of_the_mapping_changes_the_version(tmp_path: Path) -> None:
    versions: set[str] = set()
    for profile, account in (("sepa", GIROKONTO), ("sepa", REVOLUT), ("default", GIROKONTO)):
        _map(tmp_path, profile, account)
        versions.add(normaliser.load(tmp_path).version)
    assert len(versions) == 3


def test_a_different_unicode_database_changes_the_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = normaliser.load(tmp_path).version
    monkeypatch.setattr(unicodedata, "unidata_version", "0.0.0")
    assert normaliser.load(tmp_path).version != before


def test_every_result_carries_the_version_and_the_unchanged_memo(tmp_path: Path) -> None:
    norm = _sepa(tmp_path)
    memos = [row.raw_memo for row in corpus_builder.build_corpus(0).rows]
    memos += ["  Beispielmarkt\tsagt danke 4711 ", "EREF+NOTPROVIDEDSVWZ+BEISPIELMARKT", ""]
    for memo in memos:
        for account in (GIROKONTO, REVOLUT):
            result = norm.normalise(memo, account)
            assert result.raw_memo == memo
            assert result.version == norm.version


# --- (e) patterns match regardless of case ----------------------------------------


def test_a_lower_case_user_pattern_matches(tmp_path: Path) -> None:
    lower_case = r"""
extends = "default"

[[rules]]
pattern = '\bfiliale\b'
"""
    _write(tmp_path, "filialen.toml", lower_case)
    _map(tmp_path, "filialen")
    result = normaliser.load(tmp_path).normalise("Beispielmarkt Filiale", GIROKONTO)
    assert (result.profile, result.token) == ("filialen", "BEISPIELMARKT")


# --- the user directory -----------------------------------------------------------


def test_a_missing_user_directory_means_package_profiles_only(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    assert normaliser.load(missing).version == normaliser.load(tmp_path).version
    assert _token(missing, NOISY) == "BEISPIELMARKT"


def test_entries_that_are_not_profiles_are_ignored_and_stay_out_of_the_version(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "normaliser"
    # Each would be rejected if it were read: none is valid TOML.
    names = ("sepa.toml~", "sepa.toml.bak", "sepa.tml", "SEPA.TOML", ".sepa.toml", "notes.txt")
    for name in (*names, "README"):
        _write(directory, name, "not TOML [[")
    _write(directory / "subdirectory", "default.toml", "not TOML [[")
    assert normaliser.load(directory).version == normaliser.load(tmp_path / "empty").version
    assert _token(directory, NOISY) == "BEISPIELMARKT"


def _fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point HOME into ``tmp_path`` and return the user directory it implies."""
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    return home / ".config" / "autobook" / "normaliser"


def test_load_reads_the_user_directory_under_xdg_config_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fallback(tmp_path, monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    _write(tmp_path / "xdg" / "autobook" / "normaliser", "default.toml", DEFAULT_WITHOUT_DIGITS)
    result = normaliser.load().normalise(NOISY, GIROKONTO)
    assert (result.profile, result.token) == ("default", "BEISPIELMARKT 4711")


@pytest.mark.parametrize("value", [None, "", "relative-config"])
def test_load_falls_back_to_dot_config_unless_xdg_config_home_is_absolute(
    value: str | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(_fallback(tmp_path, monkeypatch), "default.toml", DEFAULT_WITHOUT_DIGITS)
    # The relative value names a directory that exists from the working directory,
    # with a profile that is rejected if read: the value must be ignored.
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "relative-config" / "autobook" / "normaliser", "default.toml", "[[")
    if value is None:
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    else:
        monkeypatch.setenv("XDG_CONFIG_HOME", value)
    result = normaliser.load().normalise(NOISY, GIROKONTO)
    assert (result.profile, result.token) == ("default", "BEISPIELMARKT 4711")


@pytest.mark.parametrize("name", ["defualt.toml", "Default.toml"])
def test_a_user_profile_that_nothing_uses_is_rejected(name: str, tmp_path: Path) -> None:
    path = _write(tmp_path, name, DEFAULT_WITHOUT_DIGITS)
    assert str(path) in _rejected(tmp_path)


def test_an_unreadable_user_directory_is_rejected(tmp_path: Path) -> None:
    directory = tmp_path / "normaliser"
    _write(directory, "default.toml", DEFAULT_WITHOUT_DIGITS)
    directory.chmod(0o300)  # write and search, but it cannot be listed
    try:
        message = _rejected(directory)
    finally:
        directory.chmod(0o700)
    assert str(directory) in message


def test_a_user_directory_that_is_a_dangling_symlink_is_rejected(tmp_path: Path) -> None:
    link = tmp_path / "normaliser"
    link.symlink_to(tmp_path / "gone", target_is_directory=True)
    assert str(link) in _rejected(link)


def test_a_user_directory_that_is_a_file_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, "normaliser", "")
    assert str(path) in _rejected(path)


@pytest.mark.parametrize("kind", ["directory", "dangling symlink"])
def test_a_toml_entry_that_is_not_a_regular_file_is_rejected(kind: str, tmp_path: Path) -> None:
    entry = tmp_path / "sepa.toml"
    if kind == "directory":
        entry.mkdir()
    else:
        entry.symlink_to(tmp_path / "gone.toml")
    assert str(entry) in _rejected(tmp_path)


# --- bad profile and mapping files ------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("[[rules]\npattern = 'X'\n", id="not TOML"),
        pytest.param('extend = "default"\n', id="unknown top-level key"),
        pytest.param("[[rules]]\npatern = 'X'\n", id="unknown rule key"),
        pytest.param("[[rules]]\n", id="rule without a pattern"),
        pytest.param("[[rules]]\npattern = 1\n", id="pattern not a string"),
        pytest.param("[[rules]]\npattern = '(X'\n", id="pattern does not compile"),
        pytest.param("rules = 'X'\n", id="rules not an array"),
        pytest.param("rules = ['X']\n", id="rule not a table"),
        pytest.param("extends = 1\n", id="extends not a string"),
        pytest.param('extends = "nirgends"\n', id="extends names no profile"),
        pytest.param('extends = "sepa"\n', id="extends itself"),
    ],
)
def test_a_bad_profile_is_rejected_naming_the_file(text: str, tmp_path: Path) -> None:
    path = _write(tmp_path, "sepa.toml", text)
    assert str(path) in _rejected(tmp_path)


def test_an_extends_cycle_is_rejected_naming_the_files_in_it(tmp_path: Path) -> None:
    # The package `sepa` extends `default`, so a user `default` extending `sepa` closes
    # a cycle.
    path = _write(tmp_path, "default.toml", 'extends = "sepa"\n')
    message = _rejected(tmp_path)
    assert str(path) in message
    assert "default -> sepa -> default" in message


def test_a_profile_that_is_not_utf8_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "sepa.toml"
    path.write_bytes(b"[[rules]]\npattern = '\xff'\n")
    assert str(path) in _rejected(tmp_path)


def test_an_unreadable_profile_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, "sepa.toml", SEPA_OVERRIDE)
    path.chmod(0o000)
    try:
        message = _rejected(tmp_path)
    finally:
        path.chmod(0o600)
    assert str(path) in message


GIRO = 'path = ["Aktiva", "Girokonto"]\n'


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("[[accounts]\n", id="not TOML"),
        pytest.param(f'[[account]]\n{GIRO}profile = "sepa"\n', id="unknown top-level key"),
        pytest.param("accounts = 'X'\n", id="accounts not an array"),
        pytest.param("accounts = ['X']\n", id="entry not a table"),
        pytest.param(
            f'[[accounts]]\n{GIRO}profile = "sepa"\nprofil = "sepa"\n', id="unknown entry key"
        ),
        pytest.param(f"[[accounts]]\n{GIRO}", id="entry without a profile"),
        pytest.param('[[accounts]]\nprofile = "sepa"\n', id="entry without a path"),
        pytest.param(
            '[[accounts]]\npath = "Aktiva:Girokonto"\nprofile = "sepa"\n', id="path as a string"
        ),
        pytest.param('[[accounts]]\npath = []\nprofile = "sepa"\n', id="empty path"),
        pytest.param(
            '[[accounts]]\npath = ["Aktiva", ""]\nprofile = "sepa"\n', id="empty component"
        ),
        pytest.param(
            '[[accounts]]\npath = ["Aktiva", 1]\nprofile = "sepa"\n',
            id="component not a string",
        ),
        pytest.param(f"[[accounts]]\n{GIRO}profile = 1\n", id="profile not a string"),
        pytest.param(
            f'[[accounts]]\n{GIRO}profile = "nirgends"\n', id="profile does not exist"
        ),
        pytest.param(
            f'[[accounts]]\n{GIRO}profile = "sepa"\n\n'
            f'[[accounts]]\n{GIRO}profile = "default"\n',
            id="account mapped twice",
        ),
    ],
)
def test_a_bad_mapping_is_rejected_naming_the_file(text: str, tmp_path: Path) -> None:
    path = _write(tmp_path, "accounts.toml", text)
    assert str(path) in _rejected(tmp_path)


# --- normalise() inputs and what a result shows -----------------------------------


@pytest.mark.parametrize(
    "account",
    [
        pytest.param(["Aktiva", "Girokonto"], id="list"),
        pytest.param("Aktiva:Girokonto", id="joined string"),
        pytest.param((), id="empty"),
        pytest.param(("Aktiva", ""), id="empty component"),
        pytest.param(("Aktiva", 1), id="component not a string"),
        pytest.param(None, id="none"),
    ],
)
def test_a_malformed_source_account_is_rejected_without_the_memo(
    account: Any, tmp_path: Path
) -> None:
    norm = normaliser.load(tmp_path)
    with pytest.raises(normaliser.NormaliserError) as caught:
        norm.normalise("GEHEIMER EMPFAENGER 4711", account)
    assert "GEHEIMER" not in str(caught.value)


def test_a_memo_that_is_not_a_string_is_rejected(tmp_path: Path) -> None:
    memo: Any = b"BEISPIELMARKT"
    with pytest.raises(normaliser.NormaliserError):
        normaliser.load(tmp_path).normalise(memo, GIROKONTO)


def test_a_result_repr_carries_neither_the_memo_nor_the_token(tmp_path: Path) -> None:
    norm = normaliser.load(tmp_path)
    # With no noise the token is the memo itself.
    for memo in ("MUSTER HAUSVERWALTUNG", "Muster Hausverwaltung NR. 4711"):
        result = norm.normalise(memo, GIROKONTO)
        assert (result.profile, result.token) == ("default", "MUSTER HAUSVERWALTUNG")
        shown = repr(result)
        assert memo not in shown
        assert "MUSTER" not in shown.upper()
        assert result.version in shown

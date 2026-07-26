"""Single-sourced gate definitions for Autobook.

`nox -s gate` is THE gate. CI runs it, `nox` runs it locally, and the PDCA
harness (Ralphovi/autobook-pdca) delegates to it through `engine/nox.sh` rather
than re-declaring any of it. If a check is not here, it is not a gate.

Two properties are deliberate:

1. **The default sessions never see GnuCash.** Every session below runs in a
   clean virtualenv. Only `applier` is created with `venv_params` granting access
   to system site-packages, because `python3-gnucash` lives in `dist-packages`
   and cannot be pip-installed. That split is what keeps "the pipeline does not
   depend on libgnucash" true rather than aspirational — see AGENTS.md.

2. **Missing external tools warn and skip; they never silently pass.** A skipped
   step prints why. Never report a skipped step as having run.
"""

from __future__ import annotations

import shutil
import sys

import nox

nox.options.sessions = ["gate"]
nox.options.reuse_existing_virtualenvs = True

# The supported interpreter range, and the CI test matrix.
PYTHONS = ["3.11", "3.12", "3.13", "3.14"]

# The interpreter running nox, e.g. "3.14". The tool sessions below use `None`
# (meaning "whatever nox itself runs on") rather than a pinned version, and the
# gate tests on THIS interpreter.
#
# Pinning a version here would be worse than it looks: on a machine that happens
# not to have it, every affected session is SKIPPED and nox still exits 0 — the
# gate goes green having checked nothing. A gate that cannot fail is worse than
# no gate. CI pins the version it wants with actions/setup-python, and fans the
# test suite across the full matrix in a separate job.
CURRENT_PYTHON = f"{sys.version_info.major}.{sys.version_info.minor}"

LINT_DEPS = ["ruff==0.14.2"]
TYPE_DEPS = ["mypy==1.18.2", "pytest>=8"]
TEST_DEPS = ["pytest>=8", "pytest-cov>=5"]

SOURCES = ("src", "tests", "noxfile.py")


@nox.session(python=None)
def fmt(session: nox.Session) -> None:
    """Check formatting. Pass `-- --fix` to rewrite instead of reporting."""
    session.install(*LINT_DEPS)
    if "--fix" in session.posargs:
        session.run("ruff", "format", *SOURCES)
        session.run("ruff", "check", "--fix", *SOURCES)
    else:
        session.run("ruff", "format", "--check", "--diff", *SOURCES)


@nox.session(python=None)
def lint(session: nox.Session) -> None:
    """Lint with ruff, warnings denied."""
    session.install(*LINT_DEPS)
    session.run("ruff", "check", *SOURCES)


@nox.session(python=None)
def types(session: nox.Session) -> None:
    """Type-check with mypy in strict mode."""
    session.install(*TYPE_DEPS)
    session.install("-e", ".")
    session.run("mypy")


@nox.session(python=PYTHONS)
def test(session: nox.Session) -> None:
    """Run the test suite. Excludes applier tests — they need system GnuCash."""
    session.install(*TEST_DEPS)
    session.install("-e", ".")
    session.run("pytest", "-m", "not applier", *session.posargs)


@nox.session(python=None, venv_backend="none")
def typos(session: nox.Session) -> None:
    """Spell-check prose, identifiers, and comments."""
    if shutil.which("typos") is None:
        session.warn(
            "SKIPPED: `typos` is not installed. Install it "
            "(cargo install typos-cli --locked, or your distro's package) "
            "for parity with CI, which always runs it."
        )
        return
    session.run("typos", external=True)


@nox.session(python=None, venv_backend="none")
def docs(session: nox.Session) -> None:
    """Lint the design documentation: front-matter, structure, internal links."""
    session.run("python3", "docs/tools/lint_docs.py", external=True)


@nox.session(
    python=None,
    venv_params=["--system-site-packages"],
)
def applier(session: nox.Session) -> None:
    """Applier tests. The ONLY session permitted to see python3-gnucash.

    Not part of `gate` and not run in CI, which has no GnuCash installed. Run it
    locally against a RESTORED COPY of a book, never a real one.
    """
    session.install(*TEST_DEPS)
    session.install("-e", ".")
    session.run(
        "python",
        "-c",
        "import gnucash; print('gnucash bindings:', gnucash.__file__)",
    )
    session.run("pytest", "-m", "applier", *session.posargs)


@nox.session(python=None, venv_backend="none")
def gate(session: nox.Session) -> None:
    """THE gate. Everything CI requires, in one command.

    Two deliberate exclusions:

    - `applier` — CI has no GnuCash, and a gate that cannot run in CI is not a
      gate.
    - the other interpreters — the gate tests on the one running nox, so it stays
      fast enough to run before every push. CI fans `test` across the full
      PYTHONS matrix in a separate job; that matrix is a required check too, it
      is just not part of this command.
    """
    # `test` is parametrized over PYTHONS, so its sessions are named `test-3.11`,
    # `test-3.12`, … — notify() needs the exact name, not "test". Running on an
    # interpreter outside PYTHONS is a real state (a new release lands before we
    # support it); say so rather than notifying a session that does not exist,
    # which nox reports as an obscure KeyError.
    if CURRENT_PYTHON not in PYTHONS:
        session.error(
            f"nox is running on Python {CURRENT_PYTHON}, which is outside the "
            f"supported range {PYTHONS[0]} to {PYTHONS[-1]}. Run nox on a supported "
            f"interpreter, or add {CURRENT_PYTHON} to PYTHONS in noxfile.py and "
            "to requires-python in pyproject.toml once it is genuinely supported."
        )
    for name in ("fmt", "lint", "types", f"test-{CURRENT_PYTHON}", "typos", "docs"):
        session.notify(name)

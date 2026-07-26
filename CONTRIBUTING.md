# Contributing to Autobook

Thank you for your interest in contributing to Autobook.

Before contributing, please read [AGENTS.md](AGENTS.md) — it holds the repository
conventions, including the hard rules that govern any code touching a GnuCash
book — and the [Security Policy](SECURITY.md).

## Development workflow

1. Fork the repository.
2. Create a feature branch for your changes.
3. Make your changes and test them locally.
4. Push the branch to your fork.
5. Open a pull request against the `main` branch.

## Pull request requirements

### Reference an issue

Every pull request must reference a real issue in this repository.

Examples:

* Closes #123
* Refs #123

Pull requests that do not reference an issue will fail the required checks.

### DCO sign-off

Every commit must contain a Developer Certificate of Origin (DCO) sign-off. The
DCO is reproduced in [`DCO`](DCO); by signing off you certify it.

The easiest way is to create commits using:

```bash
git commit -s -m "your commit message"
```

This automatically adds the required `Signed-off-by` line.

Contributions are licensed inbound under GPL-3.0-or-later, identical to the
outbound license. See [ADR-0002](docs/design/adr/0002-gpl-license-and-dco.md) for
why this project uses a DCO rather than a CLA.

## Running checks

Before opening a pull request, run:

```bash
nox -s gate
```

This is the same gate that runs in CI: formatting, lint, types, tests, spelling,
and the docs lint. External tools it needs are warn-and-skip when not installed
locally, so install them for full parity:

```bash
pipx install nox
```

If you touched the applier, also run:

```bash
nox -s applier
```

This is the only session permitted to see the system `python3-gnucash`, and it
is not part of `gate` (CI has no GnuCash installed). **Run it against a restored
copy of a book, never against a real one.**

## A note on test data

Never commit transaction data drawn from a real bank statement, even normalised.
Normalised memos routinely still carry counterparty names, IBANs, creditor IDs,
and employer names. Fixtures are synthetic or drawn from published format
documentation. See the privacy rules in [AGENTS.md](AGENTS.md).

## Reporting bugs

Please use the issue templates provided by the repository.

When reporting a misclassification or a booking problem, **redact before
pasting**: replace counterparty names, IBANs, and amounts with placeholders. A
description of the shape of the problem is more useful to us than a real
transaction, and safer for you.

## Security issues

Do not report security vulnerabilities through public issues.

See [SECURITY.md](SECURITY.md) for responsible disclosure instructions.

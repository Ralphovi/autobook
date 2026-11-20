# Autobook

Books bank statements into a Beancount ledger.

Autobook is handed bank statements as OFX files. For each line it works out
which account the money went to or came from, and writes its proposals into a
plain text review file. Lines it is confident about arrive pre-marked for
acceptance, the rest are left for a decision, and saving the file is the
approval. Autobook then adds the approved lines to a
[Beancount](https://beancount.github.io/) ledger as transactions. The target is
that ~90–95% of lines arrive pre-marked.

The residual is not a modelling failure. It is ambiguous *given the statement
alone* — was that Amazon order household or a gift? When the matching bill is
in [paperless-ngx](https://docs.paperless-ngx.com/), it can resolve part of
that; the rest stays with the user.

> **Status: design, with the first building blocks implemented.** The memo
> normaliser, the kNN index and the rolling-origin backtest exist. Nothing
> writes to a ledger yet. The design is
> [proposal 0005](docs/design/proposals/draft/0005-beancount-ledger.md), with
> [proposal 0002](docs/design/proposals/draft/0002-document-driven-booking-via-paperless.md)
> (bills from paperless-ngx) and
> [proposal 0004](docs/design/proposals/draft/0004-rules-first-mined-from-history.md)
> (rules mined from history), described in
> [`docs/design/architecture/`](docs/design/architecture/README.md). All three
> are drafts.
>
> Autobook was first designed for GnuCash. Proposal 0005 replaces that design;
> parts of the test scaffolding still date from it.

## How it works

```
   driver (a separate project)
     │  OFX files                                  ▲ exit code, --json,
     ▼                                             │ review file
┌─ AUTOBOOK ──────────────────────────────────────────────────────┐
│  input      parse OFX → admit (whole statement or nothing)       │
│  pipeline   normalise → dedup → correlate → link bills           │
│             → classify → stage → review file                     │
│  ledger     reader: accounts, history, existing entries          │
│  package    writer: append, read back, assert, undo              │
└───────────────────────────────┬──────────────────────────────────┘
                                │ reads every file; writes one
                                ▼
        main.beancount ── include ──▶ autobook.beancount
```

**Autobook is not the pipeline driver.** Getting a statement from the bank,
converting it to OFX, and deciding when to run are done by another program that
calls Autobook's commands. Autobook never runs or imports ofxstatement.

**The books must be correct at the end.** An import with an error is rejected,
not accepted: a statement is admitted whole or not at all, and a batch is
booked whole or not at all. After writing, Autobook loads the ledger again,
checks it, and puts the file back as it was if anything is wrong.

**The ledger belongs to the user.** Autobook writes transactions only, into one
file of its own that the user's ledger includes. It never changes an entry it
did not create, and never writes `open`, `balance` or any other directive.
Every entry it creates carries its ID, so a batch can be undone with one
command.

Classification is a cascade — **rules → kNN (k-nearest-neighbours) → LLM (large
language model)** — in that order, for determinism and auditability rather than
token cost. Rules come first and are mostly mined from the user's own history.
The kNN index is built from the user's own ledger at run time: in-process, CPU
only, no network, no model download. Its distinguishing property is not
accuracy but **abstention**: a nearest-neighbour distance gate that says "never
seen this" instead of returning a confident guess.

Running with **no LLM at all** is a first-class configuration, not a degraded
fallback. When an LLM is used, the default is a local one.

Bills in paperless-ngx are matched to bank lines on exact amount and linked as
evidence. Autobook runs no model on documents.

## Scope

Autobook assigns destination accounts for bank statement lines and books the
approved ones. The chart of accounts, balance assertions, prices and every
transaction that does not come from a statement line stay with the user.

Permanently out of scope: securities transactions, and postings in a currency
other than the account's. Both need postings with a cost or a price, which
break the plain two-posting, one-currency shape the pipeline is built on.
Foreign-currency spending that the bank already debited in the account's
currency **is** in scope.

## Related projects

Statements are converted to OFX by separate
[ofxstatement](https://github.com/kedder/ofxstatement) plugins, run by the
driver, not by this repository:

- [ofxstatement-consorsbank](https://github.com/Ralphovi/ofxstatement-consorsbank)
- [ofxstatement-revolut](https://github.com/Ralphovi/ofxstatement-revolut)
- [ofxstatement-scalable](https://github.com/Ralphovi/ofxstatement-scalable)

Memo normalisation deliberately lives in Autobook rather than in the plugins, so
it can be changed and re-backtested in one place.

Development process runs out-of-tree in
[autobook-pdca](https://github.com/Ralphovi/autobook-pdca).

## Development

```bash
pipx install nox
nox -s gate     # the full gate: fmt, lint, types, tests, spelling, docs
```

`nox -s gate` is the local equivalent of the required CI gate — run it before
opening a pull request. Individual sessions:

```bash
nox -s fmt lint types test typos docs
nox -s live       # paperless-ngx tests, in the Docker test environment (testenv/)
nox -s applier    # GnuCash-era tests, same environment; see below
```

Under proposal 0005 the ledger tests run in the gate, against synthetic ledgers
in temporary directories. The `applier` session and the test environment's
GnuCash image date from the earlier design. They remain for the one-off
conversion of a GnuCash book and are removed with it.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the pull-request requirements (a
linked issue and a DCO sign-off on every commit) and [AGENTS.md](AGENTS.md) for
the repository conventions, including the hard rules that govern anything
touching a ledger.

## Documentation

| Path | What it is |
|------|------------|
| [`docs/design/`](docs/design/README.md) | **Start here.** Decision records, proposals, and the living architecture description. |
| [`docs/design/proposals/draft/0005-beancount-ledger.md`](docs/design/proposals/draft/0005-beancount-ledger.md) | The design. |
| [`docs/design/proposals/draft/0002-document-driven-booking-via-paperless.md`](docs/design/proposals/draft/0002-document-driven-booking-via-paperless.md) | Bills from paperless-ngx. |
| [`docs/design/proposals/draft/0004-rules-first-mined-from-history.md`](docs/design/proposals/draft/0004-rules-first-mined-from-history.md) | Rules first, mined from history. |
| [`docs/design/architecture/`](docs/design/architecture/README.md) | The living description of the design. |

## License

GPL-3.0-or-later today; see
[ADR-0002](docs/design/adr/0002-gpl-license-and-dco.md).

[ADR-0005](docs/design/adr/0005-relicense-gpl-2-or-later.md) (proposed) changes
this to GPL-2.0-or-later, because Beancount is GPL-2.0-only. The `LICENSE` file
changes when that ADR is accepted.

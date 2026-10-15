# Autobook

Automatic destination-account assignment for GnuCash bank imports.

Autobook classifies imported bank transactions so that booking takes one save
of a pre-filled review file instead of per-transaction work in GnuCash's import
UI. Rows Autobook is confident about arrive pre-marked for acceptance, the rest
are left for a decision, and saving the file is the approval. The target is
that ~90–95% of transactions arrive pre-marked; the residual is decided in that
plain text file rather than in GnuCash's matcher.

The residual is not a modelling failure. It is ambiguous *given the statement
alone* — was that Amazon order household or a gift? When the matching bill is
in [paperless-ngx](https://docs.paperless-ngx.com/), it can resolve part of
that; the rest stays with the user.

> **Status: design.** No implementation yet. The design is
> [proposal 0001](docs/design/proposals/draft/0001-gnucash-auto-booking-pipeline.md)
> as amended by
> [proposal 0002](docs/design/proposals/draft/0002-document-driven-booking-via-paperless.md),
> described in [`docs/design/architecture/`](docs/design/architecture/README.md).
> This repository currently holds governance, documentation structure, and the
> gate harness.

## How it works

Two processes with a JSON contract between them:

```
┌─ PIPELINE ────────────────────────────────────────────────┐
│  no libgnucash · no book lock · runs anywhere             │
│                                                           │
│  statement source (paperless-ngx or files)                │
│    → ofxstatement → admission (checksum, balance check)   │
│    → normalise → dedup → correlate → link bills           │
│    → classify → stage → review file                       │
└──────────────────────▲───────────────┬────────────────────┘
  JSON: corpus,        │               │  JSON: rows marked `a`
  accounts, existing   │               │  in the saved review file
                       │               ▼
┌─ BOOK PROCESS ───────┴────────────────────────────────────┐
│  the only process that links libgnucash                   │
│                                                           │
│  exporter: read-only session → corpus, accounts, existing │
│  applier:  approved rows → transactions, save, read back  │
│            out: {proposal_id, tx_guid, status}            │
└───────────────────────────────────────────────────────────┘
```

The boundary is what makes the pipeline testable with no GnuCash installed and
no book present, and it sidesteps the Linux venv problem entirely
(`python3-gnucash` lives in `dist-packages`).

Statements can come from paperless-ngx (the original file, parsed by the same
ofxstatement plugin) or from files on disk; both are first-class. Bills in
paperless are matched to bank lines on exact amount and linked as evidence.
Autobook runs no model on documents, and a statement's lines never come from
OCR (optical character recognition) text.

Classification is a cascade — **rules → kNN (k-nearest-neighbours) → LLM (large language model)** — in that order, for
determinism and auditability rather than token cost. The kNN index is built from
the user's own book at runtime: in-process, CPU only, no network, no model
download. Its distinguishing property is not accuracy but **abstention**: a
nearest-neighbour distance gate that says "never seen this" instead of returning
a confident guess.

Running with **no LLM at all** is a first-class configuration, not a degraded
fallback. When an LLM is used, the default is a local one.

## Scope

Autobook assigns destination accounts for irregular transactions. Everything
structural stays in GnuCash. Where GnuCash ships an assistant that does the job
better, Autobook detects the need and hands off rather than reimplementing —
this already covers reconciliation, chart-of-accounts creation, recurring
bookings, and loan amortisation.

Permanently out of scope: securities transactions, and splits denominated in a
currency other than the account's. Both break the equality of a split's *value*
and its *amount*, and with it the two-split representation the pipeline is built
on. Foreign-currency spending that the bank already debited in the book currency
**is** in scope.

## Related projects

Statement ingest is handled by separate [ofxstatement](https://github.com/kedder/ofxstatement)
plugins, not by this repository:

- [ofxstatement-consorsbank](https://github.com/Ralphovi/ofxstatement-consorsbank)
- [ofxstatement-revolut](https://github.com/Ralphovi/ofxstatement-revolut)
- [ofxstatement-scalable](https://github.com/Ralphovi/ofxstatement-scalable)

Memo normalisation deliberately lives in Autobook rather than in the plugins, so
it can be changed and re-backtested without touching four packages.

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
nox -s applier    # book-process tests, in the Docker test environment (testenv/)
nox -s live       # paperless-ngx tests, same environment
```

The `applier` session (named before the book process had an exporter; it runs
all book-process tests) is the only one that sees `python3-gnucash`, inside the
test environment's `book` container; every other session runs in a clean
virtualenv, which is how the pipeline's
independence from libgnucash stays true rather than aspirational.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the pull-request requirements (a
linked issue and a DCO sign-off on every commit) and [AGENTS.md](AGENTS.md) for
the repository conventions, including the hard rules that govern anything
touching a book.

## Documentation

| Path | What it is |
|------|------------|
| [`docs/design/`](docs/design/README.md) | **Start here.** Decision records, proposals, and the living architecture description. |
| [`docs/design/proposals/draft/0001-gnucash-auto-booking-pipeline.md`](docs/design/proposals/draft/0001-gnucash-auto-booking-pipeline.md) | The design, as amended by proposal 0002. |
| [`docs/design/proposals/draft/0002-document-driven-booking-via-paperless.md`](docs/design/proposals/draft/0002-document-driven-booking-via-paperless.md) | Statements and bills from paperless-ngx; amends 0001. |
| [`docs/design/architecture/`](docs/design/architecture/README.md) | The living description of the design. |

## License

GPL-3.0-or-later. The book process links libgnucash (GPL-2.0-or-later); Autobook
exercises the "or later" option. See
[ADR-0002](docs/design/adr/0002-gpl-license-and-dco.md).

# Autobook

Automatic destination-account assignment for GnuCash bank imports.

Autobook classifies imported bank transactions so that booking requires no
per-transaction interaction with GnuCash's import UI. The target is that
~90–95% of transactions book unattended; the residual is reviewed in a plain
text file rather than in GnuCash's matcher.

The residual is not a modelling failure. It is genuinely ambiguous data — was
that Amazon order household or a gift? — which a bank statement does not contain
the information to resolve.

> **Status: design.** No implementation yet. The design is
> [proposal 0001](docs/design/proposals/draft/0001-gnucash-auto-booking-pipeline.md);
> read that first. This repository currently holds governance, documentation
> structure, and the gate harness.

## How it works

Two processes with a JSON contract between them:

```
┌─ PIPELINE ──────────────────────────────────────────────┐
│  no libgnucash · no book lock · runs anywhere            │
│                                                          │
│  ofxstatement → normalise → dedup (FITID) → classify     │
│    → correlate → stage → review                          │
└──────────────────────┬───────────────────────────────────┘
                       │  JSON: bookings in
                       ▼
┌─ APPLIER ───────────────────────────────────────────────┐
│  links libgnucash · needs the book lock                  │
│                                                          │
│  approved rows → transactions                            │
│  out: {proposal_id, tx_guid, status}                     │
└──────────────────────────────────────────────────────────┘
```

The boundary is what makes the pipeline testable with no GnuCash installed and
no book present, and it sidesteps the Linux venv problem entirely
(`python3-gnucash` lives in `dist-packages`).

Classification is a cascade — **rules → kNN → LLM** — in that order, for
determinism and auditability rather than token cost. The kNN index is built from
the user's own book at runtime: in-process, CPU only, no network, no model
download. Its distinguishing property is not accuracy but **abstention**: a
nearest-neighbour distance gate that says "never seen this" instead of returning
a confident guess.

Running with **no LLM at all** is a first-class configuration, not a degraded
fallback.

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
nox -s applier    # applier tests; needs system python3-gnucash
```

The `applier` session is the only one that may see `python3-gnucash`; every
other session runs in a clean virtualenv, which is how the pipeline's
independence from libgnucash stays true rather than aspirational.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the pull-request requirements (a
linked issue and a DCO sign-off on every commit) and [AGENTS.md](AGENTS.md) for
the repository conventions, including the hard rules that govern anything
touching a book.

## Documentation

| Path | What it is |
|------|------------|
| [`docs/design/`](docs/design/README.md) | **Start here.** Decision records, proposals, and the living architecture description. |
| [`docs/design/proposals/draft/0001-gnucash-auto-booking-pipeline.md`](docs/design/proposals/draft/0001-gnucash-auto-booking-pipeline.md) | The full design. |

## License

GPL-3.0-or-later. The applier links libgnucash (GPL-2.0-or-later); Autobook
exercises the "or later" option. See
[ADR-0002](docs/design/adr/0002-gpl-license-and-dco.md).

# Synthetic fixtures

Everything under this directory is **invented**. Every merchant name, memo,
account name and amount is made up for the tests.

The rule, from AGENTS.md ("Never collect or commit transactions"):

- no real statement, memo, IBAN, document or correspondent name;
- nothing derived from one, not even after normalising it;
- amounts are integer cents, never floats.

This is the one path `.gitignore` un-ignores for data-shaped files. If a fixture
here looks like it came from a real statement, it does not belong here.

## Contents

| File | What it is |
|------|------------|
| `corpus_builder.py` | `build_corpus(seed)` returns a `corpus` contract object. The same seed gives an equal corpus; a different seed gives a different one. It holds near-duplicate memos and exactly one novel merchant, on the latest date. |
| `coa.json` | A valid `coa` contract document for the same account tree that `tests/book/synthetic_book.py` builds (`ACCOUNTS`): 8 accounts, paths as component lists. |

`coa.json` and `synthetic_book.ACCOUNTS` must stay in step. Comparing the two needs
the GnuCash bindings, so it is done in the book-process tests, not here.

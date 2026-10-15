# testenv — the throwaway test environment

Book-process tests need the GnuCash bindings, and paperless tests need a running
paperless-ngx. Neither belongs on a developer's machine or near a real book, so they
run here: a Docker Compose stack with pinned versions, synthetic data only, on an
internal network with no host ports and no outbound access.

| Service | What | Pinned |
|---|---|---|
| `book` | Ubuntu 26.04 with the GnuCash bindings, pytest and `psql`; tests run here, with the source mounted read-only at `/src` | GnuCash 5.14 (`1:5.14-1build1`), Python 3.14 |
| `bookdb` | PostgreSQL for GnuCash's SQL backend, on port **5433** (a non-default port, like a NAS) | PostgreSQL 17 |
| `paperless` + `redis` + `paperlessdb` | paperless-ngx with its own PostgreSQL, OCR off (the seeded PDFs have a text layer) | paperless-ngx 3.3.0 (the reference deployment's version) |
| `seed` | one-shot: creates paperless's document types, custom fields, correspondents, a restricted `autobook` user and a synthetic set of documents; writes the API tokens for the tests | — |

All images are pinned by digest, so a local run, CI (`.github/workflows/testenv.yml`) and
the PDCA driver test against the same bits.

## Use

```bash
testenv/run up           # build, start, seed (about a minute from cold)
testenv/run test         # pytest -m "applier or live_paperless" in the book container
testenv/run test -k pg   # any pytest arguments; the marker filter stays unless you pass -m
testenv/run shell        # a shell in the book container
testenv/run down         # delete everything, volumes included
```

`nox -s applier` and `nox -s live` call the same commands. `AUTOBOOK_TESTENV_PROJECT`
names the compose project, so several copies can run side by side (the PDCA lanes do);
`AUTOBOOK_SRC` picks the source tree mounted at `/src` (the driver passes its worktree).

## Rules

- **Synthetic only.** Book tests build their own books (`tests/book/synthetic_book.py`)
  — a temporary XML file, or a fresh PostgreSQL database per test. The seed's documents
  are generated text. No real statement, memo, IBAN, document, correspondent name or book
  ever goes into this stack, and nothing here is copied out of a real one.
- **Never mount a real book**, nor a restored copy of one. Those stay with a human,
  attended (AGENTS.md).
- **Disposable.** Databases and paperless's data live in tmpfs; `down` removes the rest.

## What the environment showed about these versions

Checked by the tests in `tests/book/` and `tests/live/`, so a version bump that changes
any of it turns them red.

**GnuCash 5.14**
- `SessionOpenMode` exists; the bindings expose no `GncNumeric.from_double`, and
  `GncNumeric(0.5)` silently converts a float — integer cents are the only safe input.
- On the XML backend, a committed transaction that was never `save()`d is gone after
  `session.end()`; with `save()` it persists.
- A PostgreSQL URI with a port works (`postgres://user:pass@host:5433/db`), but the
  database must **already exist** — `SESSION_NEW_STORE` does not create it.
- A second `SESSION_NORMAL_OPEN` fails with `ERR_BACKEND_LOCKED`; `SESSION_READ_ONLY`
  ignores the lock and reads the last saved state.
- The **account separator is a user preference outside the book** (a headless session
  uses `.`; many desktops use `:`). Never build or parse account paths with a hard-coded
  separator — walk the components.
- On Ubuntu the bindings need the full `gnucash` package: the engine libraries
  (`libgnc-engine`, `libgnc-app-utils`) are not in `python3-gnucash`.

**paperless-ngx 3.3.0**
- The REST API needs a JSON `Accept` header with a version; the environment pins
  `application/json; version=10`. The API root serves HTML (406 for JSON).
- In API v10 a task's status is lower case (`success`) and the new document is in
  `result_data.document_id` / `related_document_ids`.
- `original_checksum` is **SHA-256** of the original file: a real integrity check.
- Duplicates are accepted by default (two documents, one checksum).
- `custom_field_query=["Betrag","exact","EUR59.00"]` finds monetary amounts.
- Document history names the human actor of a change.
- A non-admin user sees only documents it is granted — **plus every document with no
  owner**. Limiting a user to statements and bills needs every other document owned.

Not yet covered here: scheduled-transaction definitions (the bindings expose no usable
API to create them; #35 brings them), document versions, and the document-link binding.

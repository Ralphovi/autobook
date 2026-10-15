---
created: 14.10.2026 23:50
type: architecture
status: living
tags:
  - architecture
  - constraints
---
# 2. Constraints

> Living document.

## 2.1 Technical constraints

| Constraint | Source | Consequence |
|------------|--------|-------------|
| Writes go through libgnucash via the `python3-gnucash` bindings | Proposal 0001 (*Rejected alternatives*: piecash, raw SQL, CSV import) | The engine's business logic and backend abstraction apply to every write; the bindings are thinly documented and learned at the REPL |
| `python3-gnucash` installs into the system `dist-packages`, not a virtualenv | Distribution packaging | The code that imports `gnucash` runs as a separate process, the book process, under the system interpreter; everything else runs in a clean venv (section 5) |
| GnuCash holds a single-writer lock for its whole GUI session and cannot reload | GnuCash | The writer runs only when the GUI is closed; the launcher sequences rather than schedules (section 6.1) |
| `SESSION_READ_ONLY` ignores the lock | GnuCash | A read-only export with the GUI open sees the last *saved* state of an XML book (section 7.1) |
| With the XML backend nothing persists until `session.save()`; SQL backends persist each `CommitEdit` | GnuCash (`qofsession.h`: ending a session "will not save the data to a file") | The applier always calls `save()` and reports a row applied only after a read-back (section 6.5) |
| GnuCash creates scheduled-transaction (SX) instances in its Since-Last-Run step at GUI start-up — after the launcher's apply | GnuCash | A statement row on an SX occurrence is never created; it matches the instance or waits for it (section 6.3) |
| Books may be XML, SQLite, MySQL or PostgreSQL | GnuCash backends | Every check goes through the engine API; SQL is never used against a book (section 8.6) |
| No usable Python bindings on Windows | GnuCash Windows build (MinGW Python ABI) | Linux first; macOS unverified **[OPEN]**; Windows deferred as a known restriction (proposal 0001, *Platform support*) |
| License GPL-3.0-or-later | ADR-0002 (libgnucash is GPL-2.0-or-later) | Apache-2.0 dependencies remain usable; GPL-2.0-only ones do not |
| Paperless-ngx accessed only through its REST API, 3.x | Proposal 0002 | No dependency on its database or media layout; API changes are a version-gate event |
| Statements arrive through ofxstatement plugins | Existing plugins (Consorsbank, Revolut, Scalable) | Format conversion stays in the plugins; normalisation stays in Autobook (section 8.4) |
| Model backend is optional and OpenAI-compatible | Proposal 0001 | No vendor SDK in the core; no model and a local model (the default) are equal configurations; a remote backend is opt-in and restricted (section 8.5) |

## 2.2 Organizational constraints

- **One maintainer, volunteer project.** Favours small components, boring
  dependencies, and a build order that is useful early (the text-file review is
  usable before any GUI exists).
- **Open source, contributor-friendly where it is safe.** Rule packs and
  normalisation profiles are the intended contribution surface; they are data,
  versioned separately, and validated against each user's own history before use.
- **Provenance via DCO**, not a CLA (ADR-0002). Every commit is signed off;
  every PR references an issue.
- **The development process runs out of tree** in `autobook-pdca` (a
  plan-do-check-act harness), which drives
  `nox -s gate` by subprocess and never imports Autobook.

## 2.3 Conventions

- The gate is `nox -s gate`, single-sourced; CI and the PDCA harness both call it.
- Only `nox -s applier` may see the system `python3-gnucash`, and only ever
  against a restored copy of a book. The session and the pytest marker keep the
  name `applier`, but they cover every test of the book process — the exporter
  as well as the applier.
- Diagrams as code in [`diagrams/`](diagrams/), Mermaid source, never binary
  exports.
- Decisions become ADRs when first cited to settle an argument; implementation
  plans are proposals; this directory describes what exists.
- The hard rules for anything touching a book are in
  [`AGENTS.md`](../../../AGENTS.md) and are not restated here.

---
created: 14.10.2026 23:50
type: architecture
status: living
tags:
  - architecture
  - constraints
---
# 2. Constraints

> Living document. The design is
> [proposal 0005](../proposals/draft/0005-beancount-ledger.md); "§" numbers
> below refer to it unless another document is named.

## 2.1 Technical constraints

Most of these come from Beancount, the plain-text accounting system whose ledger
Autobook books into. "Verified" means the behaviour was checked against
Beancount 3.2.3 and is recorded in proposal 0005.

| Constraint | Source | Consequence |
|------------|--------|-------------|
| The ledger is read and written with the Beancount v3 library (its loader, printer and entry hash) | §3, §10 | Beancount is an ordinary dependency with wheels for Linux, macOS and Windows: one process, no system interpreter. Only the **ledger package** (a reader and a writer) imports `beancount`; the linter enforces it (section 5) |
| Beancount v3 is GPL-2.0-only; so are beangulp and beanquery | Beancount 3.2.3 (`pyproject.toml`, README; no file grants "any later version"), §13 | Autobook is GPL-2.0-or-later once [ADR-0005](../adr/0005-relicense-gpl-2-or-later.md) is accepted; until then the `LICENSE` file still says GPL-3.0-or-later (ADR-0002). No Apache-2.0 and no GPLv3 library may be imported. ofxstatement and its plugins are GPLv3, so Autobook never imports them. The paperless client and the model adapter use an HTTP library under a compatible licence, or the standard library. The gate gets a check on dependency licences |
| A plain-text ledger has no lock | Beancount | Fava or an editor may change a ledger file at any moment. Autobook serialises its own runs with a writer lock of its own. The guards are a comparison of every ledger file's SHA-256 before the write, one checked atomic exchange (never a plain rename), and a read-back; the previous content is kept for good as a pre-image (section 6.5). An editor holding unsaved changes to the owned file is not covered (section 11) |
| A ledger entry has no permanent identifier; its file and line move whenever anything above it is edited | Beancount | An entry Autobook creates carries its proposal ID as `autobook-id` metadata. An existing entry that a statement line matched is identified by a **content hash** over date, flag, payee, narration, tags, links and postings, excluding metadata and position; nothing is written to it (section 8.2) |
| An included file does not inherit the main file's `name_assets` … `name_expenses` root options | Beancount (verified: the parser rejects renamed roots in an include that does not repeat them) | `autobook init` copies the five options into the header of the **owned file** — the one file Autobook writes, which the user's ledger includes. Every run compares them with the main file's; a difference refuses the run (exit 4) |
| Beancount's balance check is tolerant: it infers a tolerance of half the last printed digit | Beancount (verified: `10.00` against `-9.995` loads without error) | Autobook checks the sum itself, in integer cents, and requires exactly zero. Every posting carries an explicit amount; none is left for Beancount to fill in (section 8.1) |
| An account must be opened before it is used, and its `open` directive may constrain its currencies | Beancount | Autobook never writes `open`. A statement whose currency the source account's `open` directive does not declare is rejected at admission. A row whose accounts are not both open on its date, or whose currency the other account does not allow, is queued (sections 6.2, 6.5) |
| Beancount has no scheduled transactions and no assistants | Beancount | Autobook adds neither. Recurring debits are ordinary rule candidates; a payment whose parts change every period is queued (§8.1) |
| A user's Beancount plugin can change transactions at load time | Beancount | An entry may not read back as written. The batch then rolls back: loud, and it blocks booking until resolved (section 11) |
| The ledger loads with whatever errors the user's files already have | Beancount | A ledger that already has errors can still be booked into; only a *new* error rolls a batch back (section 6.5) |
| Input is OFX, handed over by a driver; Autobook neither fetches nor converts statements | §1, §4.1 | Autobook parses OFX with its own parser (standard library only). It cannot know how a file was produced: it checks the file for consistency and its own work for correctness. The memo must arrive unmodified; normalisation stays in Autobook (section 8.4). An optional producer string per file is recorded and is part of the version tuple (section 8.3) |
| An OFX file does not say which ledger account it belongs to, nor whether its line IDs are the bank's or synthesised by the converter | OFX; §4.5, §5 | Both are configuration, per source. Synthesised IDs are not trusted as an identity (section 6.2) |
| Paperless-ngx accessed only through its REST API, 3.x, and for bills only | Proposal 0002, as changed by proposal 0005 | No dependency on its database or media layout; API changes are a version-gate event. Finding and downloading statements is the driver's |
| Model backend is optional and OpenAI-compatible | §6.3, §15 | No vendor SDK in the core; no model and a local model (the default) are equal configurations; a remote backend is opt-in and restricted (section 8.5) |
| The author's history is in a GnuCash book | §14 | A one-off, attended conversion tool beside Autobook turns it into a ledger; afterwards the book is a read-only archive. That tool is the only code that imports `gnucash` |

## 2.2 Organizational constraints

- **One maintainer, volunteer project.** Favours small components, boring
  dependencies, and a build order that is useful early (the text-file review is
  usable before any richer review surface exists).
- **Open source, contributor-friendly where it is safe.** Rule packs and
  normalisation profiles are the intended contribution surface; they are data,
  versioned separately, and validated against each user's own history before use.
- **Provenance via DCO**, not a CLA (ADR-0002; unchanged by ADR-0005 except for
  the licence it names). Every commit is signed off; every PR references an
  issue.
- **The development process runs out of tree** in `autobook-pdca` (a
  plan-do-check-act harness), which drives
  `nox -s gate` by subprocess and never imports Autobook.
- **The driver is a separate project** in its own repository. Autobook's
  commands, exit codes and `--json` output are its interface (section 3.2).

## 2.3 Conventions

- The gate is `nox -s gate`, single-sourced; CI and the PDCA harness both call it.
- **Where the tests run** (§16, *Tests*). Everything runs in `nox -s gate`,
  against synthetic ledgers that the tests build in temporary directories, on
  every supported Python version. No Docker image is needed to test the ledger
  package, the write path included.
- The Docker test environment (`testenv/`) keeps paperless-ngx, for the tests
  that talk to a live paperless. Its GnuCash image stays only for the export
  half of the one-off conversion (§14) and is removed with it.
- A real ledger, or a copy of one, is opened only by a human, attended. Test
  fixtures never contain a real transaction.
- Diagrams as code in [`diagrams/`](diagrams/), Mermaid source, never binary
  exports.
- Decisions become ADRs when first cited to settle an argument; implementation
  plans are proposals; this directory describes what exists.
- The hard rules for anything touching the ledger are proposal 0005 §17 and are
  not restated here. They replace the GnuCash-specific hard rules in
  [`AGENTS.md`](../../../AGENTS.md) when the writer is built; the
  classification, privacy and review-file rules there are unchanged.

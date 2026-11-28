---
created: 14.10.2026 23:50
type: architecture
status: living
tags:
  - architecture
  - context
  - scope
---
# 3. Context and scope

> Living document. The design is
> [proposal 0005](../proposals/draft/0005-beancount-ledger.md).

## 3.1 System context (C4 level 1)

See [`diagrams/c4-context.mermaid`](diagrams/c4-context.mermaid) for the diagram. In prose:

- The **driver** is a separate program, in its own repository. It gets
  statements from the bank or from a document store, converts them to OFX with
  ofxstatement, and decides when to run. It hands Autobook **OFX files**, each
  optionally with a **producer string** (for example the converter plugin's name
  and version), and calls Autobook's commands. It gets back an exit code,
  `--json` output and the review file, opens that file in an editor, and
  notifies the user. Autobook starts no editor and no other program.
- The **user** settles the rows marked `?` in the pre-filled review file and
  approves the file by saving it. The user also owns the ledger: the chart of
  accounts, the balance assertions, and the `include` line that makes the owned
  file part of the ledger.
- Autobook reads the whole **Beancount ledger** — the main file and every file
  it includes — and writes one of those files, the **owned file**, and only
  transactions.
- **Fava** (Beancount's web interface) and **text editors** read and may edit
  the same files, the owned file included, at any time. There is no lock.
- Autobook reads **bill metadata** from **paperless-ngx** to link bills to
  statement lines (proposal 0002). It does not read statements from paperless;
  that is the driver's.
- Optionally it asks a **model backend** about rows nothing else can decide. The
  backend is local by default; a remote one is opt-in and receives only an
  allowlisted merchant token, account indices, an amount and a sign.
- Credentials come from the **Secret Service**; shared **rule packs** come from
  a separate repository and carry no personal data.
- **GnuCash** is not a neighbour of the running system. The author's GnuCash
  book is the source of a one-off conversion into a ledger, done by a tool
  beside Autobook; afterwards the book is a read-only archive.

## 3.2 External interfaces

| Partner | Direction | What crosses | Notes |
|---------|-----------|--------------|-------|
| Driver | Calls Autobook's commands | In: one or more OFX files; optionally a producer string per file; the saved review file (to `autobook decide` or `autobook apply`). Out: the exit code, `--json` output on request, the review file on standard output | A separate project. Autobook reads from each OFX file the account ID, the currency, the statement period, the ledger balance, and per line the ID, date, amount, name and memo. The memo must arrive unmodified. Commands and exit codes are in section 5.5. Whether `propose` should also take the original statement's checksum is **[OPEN]** (proposal 0005, *Open questions*) |
| User | Edits and saves the review file; edits the ledger | Decisions: `a`, `?`, `s`, `x` per row and typed-over accounts; the confirmation of an `undo` | Saving the review file approves every row marked `a`; it is parsed strictly by ID. The file holds counterparty names: the driver decides where it lives, and it should be private to the user and short-lived |
| Beancount ledger: the main file and its includes | Read | Accounts with their `open` and `close` dates and allowed currencies; the booked history (the corpus); existing entries as match candidates; the root-name options; every loaded file's SHA-256; the load's errors | Never written. Read through the ledger package's reader, the only code besides the writer that imports `beancount` (section 5) |
| Owned file | Read and write | Created transactions, each with its proposal ID as `autobook-id` metadata and, for a linked bill, `autobook-doc`; a header repeating the main file's five root-name options | `autobook init` creates it and prints the `include` line; the user adds that line. Written by append, and on undo by removing exact spans, through compare-then-atomic-replace; never regenerated (section 6.5) |
| Fava, text editors | None with Autobook; they read and edit the same ledger files | Nothing | The owned file is not private: the user may correct an entry in it, and Fava can edit or delete entries in any included file. Autobook does not write if any ledger file changed since it was read. Fava notices a replaced file and reloads. An editor holding unsaved changes to the owned file is not covered (section 11) |
| paperless-ngx | Autobook reads; optionally writes a tag and a proposal-ID field | Bill metadata (correspondent, type, date, monetary total, tags); document history (who changed the tags) | Bills only. REST only, token from Secret Service; read-only by default (proposal 0002 §6.2). Which documents the dedicated user can see is **[OPEN]** until proposal 0002's D0 spike (section 7.3) |
| Model backend | Request/response | Normalised merchant token, amount, sign, live account list as numeric indices | Optional; local by default. A remote backend is opt-in and gets only tokens that match a rule-pack entry or the user's allowlist; account names never leave the machine (section 8.5). Output validated against the ledger's live account list |
| Secret Service | Read | paperless token, model API key, credentials of a PostgreSQL staging store where one is configured | Never in config files or the repository |
| Rule packs | Read | Pattern → semantic category, ambiguity flags | Separate repository; pinned or signed; validated against local history before enabling |
| GnuCash book | Read once, by the conversion tool, not by Autobook | The whole book, exported to JSON and turned into ledger files | One-off and attended (proposal 0005 §14). The conversion tool is the only code that imports `gnucash` |

## 3.3 What is explicitly out of context

- **Banks.** Autobook never talks to a bank. Statements are acquired by the user
  or by the driver.
- **Statement stores and converters.** Where a statement is kept, and the
  ofxstatement plugin that converts it to OFX, are the driver's. Autobook never
  imports or runs ofxstatement and sees only the OFX file.
- **Editors and notifications.** Opening the review file and telling the user
  that something needs attention are the driver's.
- **Mail.** Bills reach paperless through paperless's own mail consumption or
  the user's forwarding. Autobook holds no mail credentials.
- **Brokers.** Securities lines arrive in statements but are dispositioned
  `out_of_scope` (proposal 0005 §1).
- **Tax software, accountants.** Autobook's output is the ledger; anything
  downstream reads the ledger.
- **Other users' data.** No telemetry, no pooled corpus. Contribution is reviewed
  rules only.

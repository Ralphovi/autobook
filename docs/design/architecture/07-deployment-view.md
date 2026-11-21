---
created: 14.10.2026 23:50
type: architecture
status: living
tags:
  - architecture
  - deployment
---
# 7. Deployment view

> Living document. The design is
> [proposal 0005](../proposals/draft/0005-beancount-ledger.md); section numbers
> written as §n refer to it. Packaging details are **[OPEN]** until the first
> release.

Terms used in this chapter: the **ledger** is the user's Beancount v3
plain-text ledger, a main file and the files it includes. The **owned file** is
the one included file Autobook writes to. The **driver** is a separate program,
outside Autobook, that obtains bank statements, converts them to OFX files,
calls Autobook's commands and talks to the user (section 5.4). **Staging** is
Autobook's own store of statements, proposals and decisions (section 5.2).

## 7.1 Deployment profiles

There is one deployment. Autobook is an ordinary Python package, installed on
the machine that holds the ledger files and run there as one process per
command. It needs no particular interpreter beyond a supported Python version,
no other accounting program on the machine, and no server.

What differs is who calls it and whether anything is written:

| Use | Who runs the commands | Writes to the ledger | Notes |
|-----|-----------------------|----------------------|-------|
| **Driven** (default) | The driver | Yes, with `autobook apply` | The driver chains the commands of section 6.1 and opens the review file in an editor. Saving the review file is the approval |
| **By hand** | The user, in a shell | Yes, with `autobook apply` | The same commands, typed. Nothing in Autobook depends on a driver being present |
| **Trial only** | Either | Never | Read-only export, backtest, rule building (section 6.6). Works on any machine that has a copy of the ledger, or only a corpus export. May run while the ledger is open in an editor or in Fava; the reader sees the files as last saved |
| **Unattended** **[DEFERRED]** | A driver on a timer, with no user present | No | Deferred beyond v1. Approval is a save of the review file, and a headless run has no one to save one; nothing may reach the ledger without it. When to run is the driver's decision, not Autobook's |

No sequencing with other programs is needed, because nothing holds a lock on a
Beancount ledger. An editor or Fava may be open during a run. The writer's
guards — compare every ledger file before writing, replace the owned file by
one checked atomic exchange (Linux `renameat2`), read back, restore on failure — are described in section
6.5.

The ledger and the staging store belong together: staging records what was
proposed, approved and applied to this ledger. Proposal 0005 does not describe
booking into one ledger from more than one machine. A PostgreSQL staging store
is the only piece that could be shared, and nothing is designed around that.

## 7.2 What gets installed

| Piece | Source | Notes |
|-------|--------|-------|
| `autobook` Python package | PyPI / source | Installs into a virtual environment with `pip`, or via `pipx`. Python 3.11 to 3.14. One package and one process: the pipeline, staging and the ledger package (section 5.3) are installed together |
| Beancount v3 | PyPI | An ordinary dependency of the package, with wheels; installed automatically. Only the ledger package imports it. No pairing with a system package and no system interpreter is required |
| Other runtime dependencies | PyPI | Today only scikit-learn. Every imported library must have a licence compatible with GPLv2, because Beancount is GPL-2.0-only and Autobook is GPL-2.0-or-later once ADR-0005 is accepted ([ADR-0005](../adr/0005-relicense-gpl-2-or-later.md)) |
| The ledger | The user's own files | A main file and the files it includes, named in the configuration. `autobook init` creates the owned file and prints the `include` line; the user adds that line to the main file. Keeping the ledger in git is recommended, never required |
| Normalisation profiles, rule packs | Package, user directory, pack repository | Data, not code |
| Staging store | SQLite file in `$XDG_DATA_HOME/autobook/`, or a PostgreSQL URI | PostgreSQL is optional, never required |
| Configuration | TOML in `$XDG_CONFIG_HOME/autobook/` | Names the main ledger file and the owned file, and per source the OFX account ID, the ledger account, whether line IDs are bank-supplied, the normalisation profile, and `paypal_mode` where relevant (§4.5). No secrets |
| Secrets | Secret Service via libsecret | paperless token, model API key (remote backend only), the password of a PostgreSQL staging store if one is used |

What is **not** part of an Autobook installation:

- **ofxstatement and its plugins.** Converting a bank's statement to OFX is the
  driver's work. Autobook never imports or runs ofxstatement; the driver may
  have it installed on the same machine, in its own environment.
- **The driver** itself. It is a separate project in its own repository.
- **GnuCash or its Python bindings.** The only code that still imports
  `gnucash` is the one-off conversion tool that turns an existing GnuCash book
  into a ledger (§14). It is run once, attended, on a machine that has
  `python3-gnucash`, and is not needed afterwards.

## 7.3 Optional neighbours

- **paperless-ngx 3.x**, reachable over HTTP(S) on the local network. Autobook
  reads bills from it as evidence for classification (section 6.4). It uses a
  dedicated paperless user, meant to see bill documents only; change permission
  only if stamping is enabled. **[OPEN]** until D0 (proposal 0002):
  paperless shows unowned documents to every user, so the restriction holds only
  if every other document has an owner. D0 checks this as a setup step. Tag
  provenance needs `PAPERLESS_AUDIT_LOG_ENABLED` (default true). If the driver
  takes statements from paperless as well, that is the driver's access, with
  its own credentials.
- **A model backend**: none, a local server (Ollama, llama.cpp, vLLM) — the
  default — or, opt-in, a remote endpoint. A local backend keeps every byte on
  the user's network. A remote one receives only allowlisted merchant tokens,
  account indices, amounts and signs (section 8.5).
- **Fava**, the web interface for Beancount ledgers. Optional and independent:
  Autobook neither needs nor talks to it. Because Autobook's entries are
  ordinary transactions in an included file, Fava shows them like any others,
  and notices when the owned file is replaced and reloads.

## 7.4 Reference deployment

The author's setup, which the first milestones are validated against:

- A Beancount ledger on Linux, converted once from the author's GnuCash book
  (milestone B1, §14); the GnuCash book is a read-only archive afterwards.
  Until B1 has reported, history for the read-only milestones may come from a
  corpus export of that book: the `corpus` contract is the same.
- Autobook and the driver on the desktop that holds the ledger files; staging
  in the default SQLite file.
- paperless-ngx on a homelab host, holding both bills (arriving by mail
  forwarding) and bank statements (however they are acquired — outside
  Autobook). Whether its own AI features are enabled, and against which model,
  is paperless configuration **[OPEN]**.
- Statements from Consorsbank, Revolut, Scalable and PayPal, with PayPal as its
  own account (`paypal_mode = "account"`). In which form each arrives, and how
  it becomes an OFX file, is the driver's concern; Autobook receives OFX.
- A local model backend for the large-language-model (LLM) tail, or none.

Testing never rests on the reference deployment (section 13). Everything runs
in `nox -s gate` against synthetic ledgers in temporary directories, on every
supported Python version. The Docker test environment (`testenv/`) keeps
paperless-ngx for the bill tests. Its GnuCash image is needed only for the
export half of the one-off conversion and is removed with it. A real ledger, or
a copy of one, is opened only by a human, attended.

## 7.5 Platforms

Linux first: it is where the gate and the reference deployment run.

macOS and Windows are not ruled out by a dependency: Beancount publishes wheels
for both. The **writer** is Linux-only for now, because it replaces the owned
file by an atomic exchange (`renameat2` with `RENAME_EXCHANGE`) and refuses
rather than fall back to a plain rename (section 6.5). macOS has an equivalent
(`renamex_np` with `RENAME_SWAP`); Windows has none that is known to fit. The
reader, the trial and the backtest have no such requirement. What else would
have to be checked includes the secret store (the Secret Service is a Linux
desktop service) and the configuration and data paths (the XDG directories).
No support beyond Linux is claimed.

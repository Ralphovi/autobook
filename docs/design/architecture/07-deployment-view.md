---
created: 14.10.2026 23:50
type: architecture
status: living
tags:
  - architecture
  - deployment
---
# 7. Deployment view

> Living document. Packaging details are **[OPEN]** until the first release.

## 7.1 Deployment profiles

| Profile | Where it runs | How the writer avoids the GUI | Notes |
|---------|---------------|-------------------------------|-------|
| **Desktop launcher** (default) | The machine where GnuCash is used | Sequencing: the launcher runs before `exec gnucash` | Interactive review in `$EDITOR` |
| **Unattended** | A homelab host or the same desktop on a timer | `SESSION_NORMAL_OPEN`; `QOF_BACKEND_LOCKED` → deferred exit 0; escalate after repeated deferrals | Only sensible with a server-backend book reachable from that host; no editor, so only rows that need no review are applied **[OPEN]** whether this is worth supporting in v1 |
| **Trial only** | Any machine | Never writes | Read-only export, backtest, rule building; runs with GnuCash open |

Whether booking ever happens from more than one machine is an open question in
proposal 0001; the answer decides whether the unattended profile is needed.

## 7.2 What gets installed

| Piece | Source | Notes |
|-------|--------|-------|
| `autobook` Python package | PyPI / source | Pipeline and launcher entry points; installs into a venv or via `pipx` |
| Book process | Same package, separate entry point | Must run under the **system** interpreter that has `python3-gnucash`; the launcher invokes it explicitly with that interpreter **[OPEN]** exact mechanism |
| `python3-gnucash` | Distribution package | Version must match the installed GnuCash |
| ofxstatement + plugins | PyPI | One plugin per bank, installed into the pipeline's venv |
| Normalisation profiles, rule packs | Package, user directory, pack repository | Data, not code |
| Staging store | SQLite file in `$XDG_DATA_HOME/autobook/`, or a PostgreSQL URI | PostgreSQL is optional, never required |
| Configuration | TOML in `$XDG_CONFIG_HOME/autobook/` | No secrets |
| Secrets | Secret Service via libsecret | paperless token, model API key |

## 7.3 Optional neighbours

- **paperless-ngx 3.x**, reachable over HTTP(S) on the local network. Autobook
  uses a dedicated paperless user with view permission on statement and bill
  document types only; change permission only if stamping is enabled.
- **A model backend**: none, a local server (Ollama, llama.cpp, vLLM) or a cloud
  endpoint. A local backend keeps every byte on the user's network.

## 7.4 Reference deployment

The author's setup, which the first milestones are validated against:

- GnuCash with a **PostgreSQL** book backend on Linux; the launcher on the
  desktop where GnuCash runs.
- paperless-ngx on a homelab host, holding both bills (arriving by mail
  forwarding) and bank statements (however they are acquired — outside
  Autobook). Whether its own AI features are enabled, and against which model,
  is paperless configuration **[OPEN]**.
- Statements from Consorsbank, Revolut, Scalable and PayPal.
- A local model backend for the LLM tail, or none.

The XML and SQLite backends are covered in testing by restored copies and
synthetic books, never by the reference deployment alone (section 13).

## 7.5 Platforms

Linux first. macOS depends on whether Homebrew's GnuCash enables the Python
bindings **[OPEN]**. Windows is deferred: the bindings are not shipped there and
cannot be loaded by a python.org interpreter. The JSON boundary keeps a Windows
book process a component swap if that changes, and the version-skew hazard of
bundling libgnucash (proposal 0001, *Platform support*) applies the day it is
attempted.

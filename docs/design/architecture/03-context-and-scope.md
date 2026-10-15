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

> Living document.

## 3.1 System context (C4 level 1)

See [`diagrams/c4-context.mermaid`](diagrams/c4-context.mermaid) for the diagram. In prose:

- The **user** runs the launcher before opening GnuCash, settles the rows marked
  `?` in a pre-filled review file in their own editor, and approves the file by
  saving it.
- Autobook reads **statements** from paperless-ngx or from files (both
  first-class), parses them with the per-bank **ofxstatement plugins**, and reads
  **bill metadata** from paperless to link bills to bank lines.
- It reads and writes the **GnuCash book** through libgnucash, then hands over to
  the **GnuCash desktop**, which is never prevented from opening.
- Optionally it asks a **model backend** about rows nothing else can decide. The
  backend is local by default; a remote one is opt-in and receives only an
  allowlisted merchant token, account indices, an amount and a sign.
- Credentials come from the **Secret Service**; failures go to a **notifier**;
  shared **rule packs** come from a separate repository and carry no personal data.

## 3.2 External interfaces

| Partner | Direction | What crosses | Notes |
|---------|-----------|--------------|-------|
| paperless-ngx | Autobook reads; optionally writes a tag and a GUID field | Statement originals, document versions and checksums; bill metadata (correspondent, type, date, monetary total, tags); document history (who changed the tags) | REST only, token from Secret Service; read-only by default (proposal 0002 §6.2). Which documents the dedicated user can see is **[OPEN]** until D0 (section 7.3) |
| Statement files | Read | OFX/CSV, or PDF where a plugin parses one | First-class, not a fallback. Which form each bank's statements take is **[OPEN]** until D0 |
| ofxstatement plugins | In-process call | Raw statement lines with raw memo | Plugins convert format and preserve the memo; they never normalise |
| GnuCash book | Book process: the exporter reads (`SESSION_READ_ONLY`), the applier writes | Corpus export, chart of accounts (CoA), existing Autobook IDs, match candidates, scheduled-transaction definitions; created transactions and document links | Only the book process links libgnucash (section 5) |
| GnuCash desktop | Launcher `exec`s it last | Nothing — sequencing only | A refusal never prevents it from opening |
| Model backend | Request/response | Normalised merchant token, amount, sign, live account list as numeric indices | Optional; local by default. A remote backend is opt-in and gets only tokens that match a rule-pack entry or the user's allowlist; account names never leave the machine (section 8.5). Output validated against the live account tree |
| Secret Service | Read | paperless token, model API key, PostgreSQL book credentials | Never in config files or the repository |
| `$EDITOR` | Launcher spawns | The review file, at `$XDG_RUNTIME_DIR/autobook/review.txt`, mode `0600` | Saving it approves every row marked `a`; parsed strictly by ID on return |
| Notifier | Write | Failure and refusal messages, no transaction data | Configurable command |
| Rule packs | Read | Pattern → semantic category, ambiguity flags | Separate repository; pinned or signed; validated against local history before enabling |

## 3.3 What is explicitly out of context

- **Banks.** Autobook never talks to a bank. Statements are acquired by the user
  or by other tooling and land in paperless or on disk.
- **Mail.** Bills reach paperless through paperless's own mail consumption or
  the user's forwarding. Autobook holds no mail credentials.
- **Brokers.** Securities lines arrive in statements but are dispositioned
  `out_of_scope` (proposal 0001).
- **Tax software, accountants.** Autobook's output is the book; anything
  downstream reads the book.
- **Other users' data.** No telemetry, no pooled corpus. Contribution is reviewed
  rules only.

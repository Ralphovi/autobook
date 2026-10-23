---
created: 23.10.2026 00:40
type: adr
status: Proposed
tags:
  - adr
  - governance
  - triage
---
# 0003. Issue priority and automated triage: severity and reach set P0–P3, and a GitHub Action applies it with one Claude API call per issue

## Context

Autobook's issues carry a type label (`bug`, `enhancement`, `documentation`, `spike`) and sometimes a planning label (`build-order`, `no-code`, `human-run`), but nothing records how urgent an issue is. Ordering the backlog means rereading issues one by one, and the PDCA instance (Ralphovi/autobook-pdca) works whatever the open milestone holds, so whoever sets the milestone effectively starts the work.

Triage needs its rules written down, so that two people, or the same person on different days, put the same issue at the same priority, and so that a bot can apply them with the maintainer making the final call. The structure is the one Stemma, Wyrd and nl-shell already use: severity and reach give a priority from a fixed table, and a short list of overrides moves some issues up. The severity meanings, area labels and overrides below are Autobook's own.

Four things shape them.

- **A silently wrong booking is the worst outcome.** AGENTS.md and SECURITY.md say so plainly: a wrong ledger misreports for years and may reach a tax filing, so it is worse than a loud failure and worse than no booking at all. Most of the harm needs no attacker (threat model §14). Many of the failures that produce it need a crash at one exact step, an unusual book or a particular pair of statements, so a plain impact-times-likelihood table would rank them low.
- **Financial data is the other asset.** Bank memos carry counterparty names, IBANs, employers and Art. 9 special-category data (medical providers, church tax, union dues, lawyers). A leak of any of it, or of a credential, is a vulnerability under SECURITY.md even when only a crafted input can cause it.
- **The repository is public.** Anyone can open an issue, so whatever reads issues reads text written by strangers, and whatever an issue triggers, a stranger can trigger. Reporters are asked to redact (SECURITY.md), but a bug report can still carry a pasted statement line, an IBAN or an amount.
- **Most issues arrive typed.** Blank issues are disabled, and the bug and enhancement templates set their label; bugs in GnuCash or in statement parsing are sent elsewhere by the template's contact links.

## Decision

We will qualify every issue with three labels, derive a priority from two of them with a fixed table, and apply a short list of overrides (sections 1–3). Section 4 says what an automated triager may and may not do, and section 5 how ours runs.

### 1. Labels describing the issue

**Severity: how bad it is when it happens**

| Label | Meaning |
|---|---|
| `sev:critical` | A booking is written that the user did not approve in the saved review file, or with a different account, amount or date than shown; a transaction is booked twice (a transfer from both statements, a scheduled-transaction occurrence created, a re-run after a crash) or lost; a row is reported applied without a read-back; a book is corrupted, written under a live GnuCash session, or its lock broken; the reconciled flag is set from code; a float reaches a monetary amount, or a currency is assumed rather than read; a raw memo, IBAN, account name, document content or credential leaves the machine or reaches a log, pack or fixture; an unattended run touches a real book |
| `sev:major` | A safety check is off or can be bypassed without a wrong booking yet: the review-file parser, the batch gate, an abstention gate, the adapter's redaction, the admission balance check; a statement is partly admitted, or data is dropped or queued without being reported; a crash or failed run that leaves a stale lock or an unrecoverable batch; a core flow is broken with no workaround |
| `sev:minor` | Wrong behaviour with a workaround, a visible degradation, or misleading output or metrics |
| `sev:trivial` | Cosmetic, wording, docs, or a test-only gap |

**Reach: how likely someone hits it**

| Label | Meaning |
|---|---|
| `reach:common` | Normal use with an ordinary book, statement and configuration triggers it |
| `reach:edge` | Needs an unusual book (backend, currency, structure), statement, model backend, configuration or timing, such as a crash at one exact step |
| `reach:adversarial` | Only triggers when someone sets it up on purpose: a crafted memo, statement or document, a hostile rule pack, a malicious paperless instance or model backend |

**Area: where the issue lives** (for routing and assignment)

Following the building blocks (architecture §5): `area:admission`, `area:normaliser`, `area:correlator`, `area:classifier` (rules, kNN, the LLM tail), `area:model-adapter`, `area:documents` (paperless-ngx and the bill matcher, proposal 0002), `area:review` (disposition, batch gate, review file), `area:staging`, `area:contracts`, `area:book` (the book process: session, exporter, applier, read-back, assertions, undo), `area:launcher`, `area:trial`, `area:testenv`, plus `area:docs` and `area:ci`. An issue gets one or two. The existing labels `build-order`, `no-code`, `spike` and `human-run` stay as they are.

### 2. Priority from severity and reach

| | common | edge | adversarial |
|---|---|---|---|
| **critical** | P0 | P1 | P1 |
| **major** | P1 | P2 | P2 |
| **minor** | P2 | P3 | P3 |
| **trivial** | P3 | P3 | P3 |

- **P0:** drop other work, fix now, block the release.
- **P1:** goes on the current milestone.
- **P2:** next milestone, or whenever it fits.
- **P3:** backlog.

The labels are `priority:P0` to `priority:P3`, the same names as in Stemma and Wyrd, so a priority means the same in each. P1 and P2 line up roughly with Codex's review badges.

### 3. Overrides

- **Booking-integrity bugs get at least P1, even when `reach:edge`.** Anything that can write a wrong, duplicated, unapproved or unverified booking, lose a transaction, skip the read-back, corrupt a book or set the reconciled flag. A crash at one exact step is an edge case by nature, and the idempotency rules exist precisely for it.
- **Security and privacy bugs get at least P1, even when `reach:adversarial`.** Financial data leaving the machine, a credential exposed, a way around the redaction boundary: SECURITY.md counts each as a vulnerability whether or not an attacker is needed.
- **Deferred review findings** keep the review's priority, unless the triager can show the pull request changed the impact.
- **When unsure, leave the priority off.** If the triager cannot place severity or reach, they set `needs-triage` and say what is missing. Never guess a lower priority.

### 4. Automated triage

A bot that triages does this on each new issue:

1. Set type (`bug`, `enhancement`, `documentation` or `spike`) unless one is already set, plus severity, reach, area and priority. The templates set `bug` or `enhancement`, so most issues arrive typed; the bot keeps that label, and says in its comment when the issue reads as a different type.
2. Post one comment with a line of reasoning per label, so the maintainer can check the call quickly and correct it by changing a label.
3. Assign from a fixed owner table by area, unless someone is already assigned.
4. Leave the milestone empty; setting it stays the maintainer's decision.

Issue text is untrusted input. The bot's job MUST hold only `contents: read`, `issues: write` and `id-token: write`; it gets no write access to code and no secret beyond its own short-lived tokens. GitHub has no narrower permission than `issues: write`, and that one allows more than the bot uses: it can also edit an issue's title and body, close, reopen or lock it, set its milestone, and edit or delete comments. The bot's code calls only the label, assignee and comment endpoints, with arguments it builds itself, so the model's answer cannot reach the rest. The wider capability is reachable only by compromising the job's code or its dependencies, which are hash-pinned (section 5); such a compromise could rewrite, close or re-milestone issues, which shows in each issue's history and can be undone, but it cannot touch code, releases or secrets. What the model returns MUST be validated against the label sets before anything is written, and the priority MUST be computed by code from sections 2 and 3, not taken from the model.

The bot MUST NOT quote the issue in its comment: no statement line, memo, IBAN, amount, date, payee or account name, path or key, only descriptions in general terms. When an issue appears to contain real financial data, the comment SHOULD ask the reporter to replace it with a made-up example and edit the original out, and say that editing alone does not remove it from the issue's history; this is also all the repository may hold (AGENTS.md: synthetic fixtures only). When it appears to contain a credential, the comment SHOULD ask for it to be rotated. When it appears to report an undisclosed vulnerability, the bot still sets the labels, but its comment MUST NOT restate the details; it points to SECURITY.md so the maintainer can move the report to a private advisory.

The bot skips pull requests, closed issues, issues opened by bots, and issues that already carry a priority.

### 5. How the bot runs

We will run triage as a GitHub Action, `.github/workflows/triage-priority.yml`, with a Python script, `.github/triage/triage_priority.py`. It runs when an issue is opened, reopened or edited and has no `priority:*` label, and on demand to back-fill open issues.

- **A real IBAN is never sent to the model.** Before any call, the script looks for an IBAN that passes the ISO 13616 mod-97 check. If it finds one, the issue is most likely carrying a real account: the script makes no model call, sets `needs-triage` and asks for a made-up example (an IBAN with a wrong check number is fine). The issue is triaged again once the reporter edits it, because an issue at `needs-triage` is re-read on edit.
- **One request per issue.** Claude Sonnet 5.5 at low effort, with no tools, structured JSON output, and the issue title and description capped at fixed lengths; the comment says when it cut the text. The static rules are sent as a cached system prompt. An issue is classified once; an edit triggers a new call only while it carries `needs-triage`, at most twice (the script's `--retry` flag, which the workflow passes only for an edit). A back-fill or a reopen never classifies an issue again, and a back-fill batch counts only issues it will classify. A retry that places the priority removes `needs-triage`. Only the workflow's own comments (`github-actions[bot]`) count as an earlier classification, since anyone can type the comment marker.
- **The model classifies; the script decides.** The model returns type, severity, reach, area, the override flags, the `financial_data`, `secret_in_issue` and `vulnerability_report` flags, and one reason per label. Each reason field in the output schema says what it should explain, because a bare string field is sometimes filled with a single word. The script validates the answer, computes the priority, and applies labels, assignee and comment with the workflow's own `GITHUB_TOKEN`; `id-token: write` lets the job fetch its identity token and nothing more.
- **Reasons that echo the issue are withheld whole.** A reason is not posted when it repeats from the issue a run of five words, a number of three or more digits (an IBAN group, a date, an ID), an amount with two decimals (`12,50` and `12.50` count as the same), or a single token that looks like an identifier (eight characters or more, containing a digit, one of `. / _ : = @ +`, or two hyphens, such as a compact IBAN, a key, a path or an account name like `Ausgaben:Arzt`; a word with one hyphen does not count). A reason under three words is shown as "(no reason given)", and mentions and markup are neutralised.
- **A decline or a malformed answer sets `needs-triage`** and a short comment; nothing is guessed. A safety-classifier decline, which a security-heavy report can trip, is first retried server-side on Anthropic's recommended fallback model.
- **No stored API key.** The job authenticates by Workload Identity Federation: it fetches GitHub's OIDC identity token (audience `https://api.anthropic.com`) and the Anthropic SDK exchanges it for a Claude API token that acts as a dedicated service account. The repository uses GitHub's immutable subject format, so the federation rule's subject prefix names the owner and repository by their numeric IDs, `repo:Ralphovi@284903369/autobook@1313037413:ref:refs/heads/main`, and a renamed or re-created account cannot match it. The rule's only extra claims are `repository_owner: Ralphovi` and `ref: refs/heads/main`; it does not pin `event_name` or `workflow`, because issue events and manual runs share it. That covers issue events and manual runs from main, and no pull request, fork or other branch. The rule grants `workspace:developer` for 600 seconds; GitHub's token can be exchanged once, so a run must finish within about eight minutes. The rule, organisation, service-account and workspace IDs are repository variables, not secrets, and the workflow does nothing until they are set. A manual run with `check` ticked makes one 16-token request to test the sign-in.
- **Cost is capped outside the bot as well as inside it.** Anyone can open an issue on a public repository, so the service account acts in a workspace with its own spending limit; that limit is the backstop against a flood of issues. Each comment states its token use.
- **Dependencies are pinned and hash-checked.** The SDK and everything it pulls in are compiled with hashes and installed with `--require-hashes`, each version at least two weeks old when chosen. The triage tooling is not part of the package, so its dependencies stay out of `pyproject.toml` and reach none of the four places the tests run.
- **The label set lives in `.github/triage/labels.json`**, with descriptions under GitHub's 100-character limit, and the workflow creates missing labels.

We reject running a model on a subscription in the Action: its credential is a whole personal account, exposed to every issue author's prompt injection. We reject a stored `ANTHROPIC_API_KEY` secret: it lasts until someone revokes it, while a federated token expires within minutes and works only from this repository's main branch. We reject an agent that reads the code to triage: one judgement per issue does not need it, and reading code is what would make the cost grow.

### 6. The threat model run through it

As a check of the scheme rather than real triage, here are threats from the threat model (§14.3) classified as if each had been reported as a bug:

| Issue | Severity / reach | Priority |
|---|---|---|
| A transfer is booked from both statements in two batches | critical / edge, plus the booking-integrity override | P1 |
| A crash between "committed to book" and "marked applied" creates the transaction again on re-run | critical / edge, plus the booking-integrity override | P1 |
| An XML book batch is reported applied but was never saved | critical / common | P0 |
| Writing proceeds while the GnuCash GUI holds the lock | critical / edge, plus the booking-integrity override | P1 |
| A crafted memo makes the remote backend receive a non-allowlisted token | critical / adversarial, plus the security-or-privacy override | P1 |
| The review-file parser accepts an unknown status character and skips the row | major / edge | P2 |
| A coverage report double-counts out-of-scope rows | minor / common | P2 |

## Consequences

Every issue carries a priority that says why it has it, and the backlog can be sorted by label instead of by rereading issues. Manual and automated triage use the same rules, and a priority means the same in Autobook, Stemma, Wyrd and nl-shell.

The booking-integrity and security-or-privacy overrides move more issues up than any other rule. That is deliberate: a rare double booking and an attacker-only leak compete with common crashes for the current milestone, because SECURITY.md already ranks them that way. Leaving the milestone to the maintainer keeps the PDCA loop from starting work on the bot's judgement alone, at the cost of one manual step per issue.

Every issue's title and description, unless it holds a checksum-valid IBAN, is sent to Anthropic's API. The text is already public, but a pasted statement line can still be the reporter's or a third party's financial data, and the bot adds a processor that sees it. The IBAN check keeps the clearest case from being sent at all; memos, amounts and payee names without an IBAN still are, and the bot then asks for them to be replaced. Whether that is enough, or whether the bot should hold back on more patterns before the call, is **[OPEN]**.

The rules exist twice, in this ADR and in `.github/triage/prompt.md`, and the table and overrides a third time in the script. A change to this ADR has to update both files; the script's tests pin the table, so a drift shows up as a failing test. The model is a constant in the script, so moving to a cheaper or stronger one is a one-line change.

The same bot on Stemma used about 2,800 to 3,100 input and 140 to 290 output tokens per issue. Autobook's prompt is similar in size, so back-filling its open issues should cost well under a dollar; that is an estimate until the first run reports its use. A comment can lack a reason for a label or two, when the model's reason is too short or the check withholds one; the labels are unaffected.

The triage script lives under `.github/triage/` and is not covered by `nox -s gate`, which checks `src`, `tests` and `noxfile.py`; only `typos` reads it. Its own unit tests run in the workflow on pull requests that touch it.

Follow-on work: create the federation rule and repository variables, run the connection check, back-fill the open issues with a dry run first, and review the first comments before relying on the bot.

Left open:

- **[OPEN]** Whether the bot should hold back from the model on more than a checksum-valid IBAN (a creditor ID, a statement-line shape), at the cost of more issues waiting for a human.
- **[OPEN]** Whether P3 issues ever close automatically, or stay open until the maintainer closes them.

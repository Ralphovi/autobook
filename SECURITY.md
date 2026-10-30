# Security policy

Autobook is pre-release software — currently a design with no implementation —
and carries no correctness or security promise at this stage. We still want to
hear about vulnerabilities early, including in the design itself.

## What "security" means for this project

Autobook writes to accounting books, reads statements and bills from
paperless-ngx when configured to, and, optionally, sends data to a model
backend. The threat model is therefore unusual for a small tool, and two classes
matter more than the usual web-application concerns:

**Integrity of the book.** The worst outcome is not a crash — it is a silently
wrong ledger. Anything that could cause Autobook to write a booking the user did
not approve, to write under a live GnuCash session, to corrupt a book, to double-
book a transfer, to set a reconciled flag, or to create accounts, is a security
issue here even though no attacker is involved. Approval is the saved review
file: a booking the user did not mark `a` there, or one that differs from the
account, amount or date shown there, is a booking the user did not approve. The hard rules in
[AGENTS.md](AGENTS.md) exist to make this class structurally difficult; a way
around them is worth reporting.

**Confidentiality of financial data.** Bank memos routinely carry counterparty
names, IBANs, creditor IDs, employer names, and Art. 9 special-category data —
medical providers, church tax, union dues, party donations, lawyers, debt
collection. Bills and invoices in paperless-ngx carry the same, in more detail.
Autobook redacts at the model-adapter boundary and sends only a normalised
merchant token, amount, and sign; document content never reaches the adapter.
The default model backend is local. A remote backend is opt-in, and then
receives only a merchant token that matches a rule-pack entry or the user's
allowlist of business names (any other token makes the model abstain and the
row queue for review), the account list as numeric indices mapped back locally
(never the account names, which can themselves be special-category data, such
as `Kirchensteuer`), and the amount and sign. **Any path by which an unredacted
memo, document content, a counterparty IBAN, an account name, a non-allowlisted
token, or a credential could leave the machine — or by which memo or document
content could reach a shareable rule pack, a log file, a crash report, or a test
fixture — is a vulnerability.** So is a shipped pack that could cause confident mis-booking
across the whole user base.

Running with no model backend at all is a supported configuration, and the
no-network path is part of what we want kept sound.

## Reporting a vulnerability

Please report suspected vulnerabilities **privately**, not via a public issue or
pull request.

Use GitHub's [private vulnerability reporting](https://github.com/Ralphovi/autobook/security/advisories/new)
for this repository, or email **policy@ralphovi.net**, with:

- a description of the issue and its impact,
- the steps or proof-of-concept needed to reproduce it, and
- the affected version or commit.

**Please redact before you send.** Do not include real transactions, real IBANs,
or real statement files in a report. A synthetic reproduction is more useful to
us and safer for you; if the bug genuinely depends on real data, say so and we
will work out how to reproduce it without you sending it.

We will acknowledge your report and keep you informed as we investigate. Please
give us a reasonable opportunity to address the issue before any public
disclosure.

**Safe harbor.** We will not pursue or support legal action against researchers
acting in good faith under this policy — accessing only their own data, avoiding
privacy violations, service disruption, and data destruction, and giving us
reasonable time to remediate before public disclosure.

## Scope

**In scope:** the pipeline and the book process (exporter and applier), the
redaction boundary, credential handling, rule-pack loading and validation, the
review-file parser, the launcher wrapper, the paperless-ngx client, statement
admission (checksum verification, temporary files), bill matching, and stamping
documents in paperless.

**Out of scope:** vulnerabilities in GnuCash itself (report those to the
[GnuCash project](https://bugs.gnucash.org/)), in ofxstatement or its plugins, in
paperless-ngx itself, or in a model backend you have configured. We are glad to
help route a report to the right place.

Until there is a release, behavioural changes are expected and are not in
themselves security issues.

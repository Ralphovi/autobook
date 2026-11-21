---
created: 20.11.2026 21:30
type: adr
status: Proposed
supersedes: 0002
tags:
  - adr
  - governance
  - licensing
---
# 0005. Relicense as GPL-2.0-or-later; the DCO stays

## Context

ADR-0002 licensed Autobook under GPL-3.0-or-later. Its reason was the dependency: the
applier linked libgnucash, which is GPL-2.0-or-later, and choosing version 3 kept
Apache-2.0 dependencies available.

Proposal 0005 replaces GnuCash with a Beancount v3 ledger. Autobook then links nothing of
GnuCash's, and imports `beancount` instead. Beancount's licence is different in the one
way that matters here. Checked on Beancount 3.2.3:

- `pyproject.toml` declares `license = { text = "GPL-2.0-only" }`;
- the README says the code is distributed under "GNU GPLv2 only";
- no source file grants "any later version".

beangulp and beanquery carry the same licence. Fava is MIT.

The Free Software Foundation's position is that code under GPLv2 only and code under
GPLv3 cannot be combined into one program, and that modules which import each other and
share data structures are one program. A GPL-3.0-or-later Autobook that imports
`beancount` could therefore not be distributed.

Three ways out were weighed in proposal 0005:

1. keep GPL-3.0-or-later and put the code that imports `beancount` into a separate
   GPL-2.0-only program, reached by subprocess;
2. keep GPL-3.0-or-later and use only Beancount's command-line tools;
3. relicense Autobook so that it can import `beancount`.

Two facts make the third possible and cheap today. Every contribution so far is the
maintainer's own, apart from automated version bumps, so no other copyright holder has to
agree. And nothing has been released, so no recipient holds a copy under the old licence
that matters in practice.

This is the project's reading of the licences, not legal advice.

## Decision

### 1. License Autobook under GPL-2.0-or-later, whole repository

We will distribute the whole repository as **GPL-2.0-or-later** and import `beancount`
in-process. Distributed together with Beancount, the combined work is conveyed under
GPLv2.

**"Or later", not "only".** The combination is under GPLv2 either way. "Or later" keeps
Autobook's own code usable under GPLv3 if Beancount ever relicenses, or by anyone who
uses parts of Autobook without Beancount.

**We will not split the tree by directory**, for the reasons ADR-0002 gave: two licence
texts, per-file headers, and a boundary argued about in review. That only the ledger
package imports `beancount` remains an architectural rule with a linter behind it; it is
a testability property, not a licensing one.

**We reject the separate reader program and the command-line-only route.** Both keep the
old licence at the cost of a permanent subprocess boundary, and the first adds a second
package to release in step with Autobook. The licence should follow the design here, not
shape it.

### 2. Dependencies must be compatible with GPLv2

A library that Autobook imports MUST be under a licence compatible with GPLv2. MIT, BSD,
ISC, LGPL and GPL-2.0-or-later are. **Apache-2.0 is not**, on the FSF's reading, and
neither is GPL-3.0-only or GPL-3.0-or-later.

- The gate SHOULD check the licences of the runtime dependencies, so that this is not left
  to memory.
- Autobook MUST NOT import `ofxstatement` or its plugins; they are GPLv3. Proposal 0005
  already makes Autobook a program that is handed OFX files. A driver that runs
  ofxstatement and Autobook as separate commands combines nothing.
- Tools that are run and not imported — nox, ruff, mypy, the test runner — are separate
  programs and are unaffected, whatever their licence.

### 3. The PDCA harness stays Apache-2.0

Unchanged from ADR-0002. The harness never imports Autobook and drives its gate by
subprocess from a separate checkout.

### 4. The DCO stays; inbound equals outbound

Unchanged from ADR-0002 except for the licence it names. Contributions are certified by a
per-commit Developer Certificate of Origin sign-off, and are licensed inbound under
GPL-2.0-or-later. There is no CLA. A later relicensing would need every contributor's
agreement, as this one would have, had there been other contributors.

### 5. What changes with this ADR

In the pull request that accepts it: `LICENSE` (the GPL version 2 text), `NOTICE`,
`pyproject.toml` (`license = "GPL-2.0-or-later"` and the classifier), `CONTRIBUTING.md`,
the licence section of `README.md`, and the licence row in architecture chapter 2.

## Consequences

- Autobook can import Beancount's loader, printer and comparison functions directly. One
  process, one repository.
- Apache-2.0 libraries are no longer available. This costs nothing today: the only
  runtime dependency is scikit-learn (BSD-3-Clause). It constrains later choices: the
  paperless client and the model adapter must use an HTTP library under a compatible
  licence, or the standard library. `requests` and the vendor SDKs that are Apache-2.0
  are out.
- This reverses the consideration ADR-0002 called deciding. The trade is deliberate:
  ADR-0002 protected dependencies the project might want; this ADR admits the one
  dependency the design needs.
- Autobook and the ofxstatement plugins can never be merged into one program. That is
  the design in any case.
- Publishing to PyPI requires the wheel metadata to declare `GPL-2.0-or-later`; the SPDX
  expression in `pyproject.toml` remains the single source for it.
- The decision is cheap now and expensive later. Once anyone else has contributed, or a
  release is in circulation, changing the licence again needs their agreement.
- If Beancount ever becomes GPL-2.0-or-later or more permissive, returning to
  GPL-3.0-or-later is possible by a further ADR, because of "or later".

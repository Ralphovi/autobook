---
created: 26.07.2026 19:00
type: adr
status: Accepted
tags:
  - adr
  - governance
  - licensing
---
# 0002. GPL-3.0-or-later, and the DCO

## Context

Autobook's applier links **libgnucash** through the `python3-gnucash` bindings.
GnuCash's `LICENSE` states that the software is *"licensed under the GNU General
Public License, Version 2, or (at your option) Version 3"*; almost all source
files are GPLv2 **or-later**, and `bindings/python/gnucash_core.py` carries the
standard "version 2 of the License, or (at your option) any later version"
header. Linking it makes Autobook's distribution a GPL matter. This is not a
preference to be optimised — it is a consequence of the dependency, and the
design records it as such.

Two things remain genuinely open, and this ADR settles them.

**Which GPL version.** "Or later" means the v3 option is available. The choice
matters more than it appears: **Apache-2.0 is compatible with GPLv3 but not with
GPLv2**, because the FSF reads Apache's patent-termination and indemnity clauses
as additional restrictions GPLv2 does not permit. Picking GPL-2.0-only would
quietly foreclose every Apache-2.0 dependency — a large share of the Python
ecosystem, including tooling this project already uses.

**Whether to split the tree.** Only the applier links libgnucash. The pipeline —
normalisation, the kNN index, staging, correlation, the rule packs — imports no
GnuCash code at all, by an architectural rule strong enough to be enforced by the
linter. A per-directory split (permissive pipeline, GPL applier) is therefore
*arguable*.

A related question is the development harness. Autobook's PDCA process runs
out-of-tree in a separate repository rendered from an Apache-2.0 template; it
drives Autobook's gates by subprocess in a sibling checkout and never imports
Autobook.

## Decision

### 1. License Autobook under GPL-3.0-or-later, whole repository

Exercise libgnucash's "or later" option and distribute the whole repository as
**GPL-3.0-or-later**. Ship `LICENSE`, `NOTICE`, and `SECURITY.md` from the first
commit.

**We will not split the tree by directory.** The split would be defensible, but
it buys reuse that nobody has asked for and charges a permanent tax: two license
texts, per-file headers, a boundary that must be argued about in review whenever
a helper moves, and a real risk of an Apache-labelled file drifting into the
applier's import graph unnoticed. The pipeline's independence from libgnucash is
worth protecting *architecturally* — and it is, by the import ban and its
gate — but that is a testability property, not a licensing one. Should a
genuine outside consumer for the pipeline appear, this decision can be revisited
by superseding ADR; extracting a permissively-licensed library later is ordinary
work, whereas un-shipping a wrong license is not.

Choosing v3-or-later, not v2, is what keeps Apache-2.0 dependencies available.
That is the deciding consideration and it should not be reopened without one.

### 2. Keep the PDCA harness Apache-2.0

`Ralphovi/autobook-pdca` stays **Apache-2.0**, as its template renders it. It has
no GPL trigger: it never imports Autobook, links nothing of GnuCash's, and
invokes the gate as a subprocess in a separate checkout — no derivative work
arises. Making it GPL would be a preference, and a costly one: the rendered
instance vendors Apache-2.0 harness sources, so every `copier update` would carry
a license reconciliation, and each fix worth sending upstream would need
relicensing first.

Two licenses across the two repositories is not an inconsistency to be tidied
away. It is the process/product boundary showing up in the license field: the
harness is generic machinery that would work unchanged against a project in
another language, and Autobook is the thing that links libgnucash.

### 3. Track provenance with the DCO, not a CLA

Contributions are certified with a per-commit
[Developer Certificate of Origin](https://developercertificate.org/) sign-off
(`git commit -s`), reproduced in the repository's `DCO` file. Inbound license
equals outbound license: GPL-3.0-or-later.

A **CLA** would give the maintainer cleaner legal footing and, in most forms, the
right to relicense unilaterally. Both are refused deliberately. The friction — a
contributor clearing an agreement through an employer's legal team before a
one-line fix can merge — falls hardest on exactly the drive-by contributors this
project wants, in an ecosystem where such contributors are the norm. And the
relicensing right is not one this project should hold: under the DCO every
contributor keeps copyright under GPL-3.0-or-later, so Autobook *cannot* later be
relicensed out from under the people who wrote it.

## Consequences

- Apache-2.0, MIT, and BSD dependencies remain available; a GPL-2.0-only
  dependency does not. This has not yet constrained any choice and is unlikely
  to: the relevant Python ecosystem is overwhelmingly permissive.
- Anyone distributing a modified Autobook must ship source under the same terms.
  For a personal-finance tool whose users are individuals running it locally,
  this costs little and preserves the guarantee that the tool stays inspectable
  by the people trusting it with their books.
- Rule packs, contributed as pattern-plus-category data rather than code, are
  covered by the repository license where they live. If packs move to their own
  repository — as proposal 0001 anticipates — that repository picks its own
  license, and a permissive one is likely more appropriate for pure data. That
  decision is deferred, not made here.
- Publishing to PyPI requires the wheel metadata to declare
  `GPL-3.0-or-later`; the SPDX expression in `pyproject.toml` is the single
  source for it.
- The two repositories carry different licenses. Anyone moving code between them
  must treat it as a relicensing question, not a copy-paste.

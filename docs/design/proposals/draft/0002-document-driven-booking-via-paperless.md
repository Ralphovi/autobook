---
created: 14.10.2026 23:45
type: proposal
status: draft
author: Eduard Ralph
tracking-issue:
tags:
  - proposal
  - paperless
  - documents
  - ingest
  - design
---

# Proposal: Document-driven booking — statements and bills from paperless-ngx

> **What this settles.** Autobook's inputs move into paperless-ngx. Bank
> statements are read from paperless as their **original files** and parsed by
> the existing ofxstatement plugins; bills and invoices are read from paperless as
> **structured metadata** and linked to bank transactions as evidence. It settles
> which representation of a document Autobook may trust for what (§2), how a
> statement is admitted into staging (§3), how a bill is matched to a transaction
> (§4), what a matched bill is allowed to change about a booking (§5), and what
> Autobook writes back, where (§6).
>
> **What this settles by exclusion.** Autobook runs **no model on documents**.
> OCR, correspondent recognition and field extraction belong to paperless, under
> the user's own paperless configuration. Autobook's model adapter never receives
> document content, so the redaction boundary in proposal 0001 holds unchanged.
> Nothing here lets a document — or a model's reading of one — decide an account
> directly: documents feed **rules**, and rules stay human-committed.
>
> **What this does not settle.** Statement acquisition (getting statements from a
> bank into paperless) is out of scope, as is mail retrieval (getting bills into
> paperless). Paperless is where acquisition ends. **Line-item splits** from
> invoices are deferred to a later proposal (§9). Securities stay out of scope for
> the reasons proposal 0001 gives; documents do not change them.
>
> **Relation to proposal 0001.** 0001 is still `draft`. This proposal *amends* it
> rather than superseding it — see *Changes to proposal 0001* below for exactly
> what moves. 0001's acceptance criterion (build order step 2 has reported) is
> unaffected; this proposal adds its own read-only premise test (§8, D2) that
> runs on the same corpus.

## In plain language

Today the plan is: export a statement, convert it, classify each line, review
what is left. The "what is left" — five to ten percent — was declared permanent,
because the statement does not say whether an Amazon order was groceries or a
birthday present.

But the invoice does. Bills already land in paperless, and paperless already
reads them: it knows who sent each one, when, and — with a total field — how
much. Put the statements there too, and Autobook has one place to look for
everything. It reads a statement exactly as before, just from paperless instead
of a folder. Then, for each bank line, it asks paperless whether there is a bill
for exactly that amount, from a plausible sender, around that date. If there is
exactly one, the booking gets a link to the bill in GnuCash, and the bill's tags
become something a rule can match on.

What it will not do is let paperless's AI book anything on its own. A total
paperless read wrongly simply fails to match the bank amount and nothing
happens. A tag paperless's AI applied is treated with suspicion until shadow-mode
evidence says otherwise.

## Changes to proposal 0001

| 0001 says | This proposal |
|---|---|
| The residual is "genuinely ambiguous data … a bank statement does not contain the information to resolve" | The residual is ambiguous *given the statement alone*. A matched document can resolve part of it. 0001's 90–95% target is unchanged; this adds a second measurement on top (§8). |
| Ingest: `ofxstatement → normalise → dedup (FITID)` from files | Ingest source becomes a **statement source** adapter: paperless (new) or the file path (kept, first-class). Plugins are unchanged in role. |
| Dedup by FITID | FITID where the format carries one; otherwise a synthetic key plus a period-overlap rule (§3.4). |
| Rule types: creditor ID, memo pattern | Adds **document-keyed** conditions: paperless correspondent, document type, tag (§5). |
| Applier output `{proposal_id, tx_guid, status}` | Applier input gains an optional `doc_link`; GnuCash's document link is set on create and on `match_existing` (§6.1). |
| Build order 3: "Ingest, staging, FITID dedup" | Split: file ingest as before, then D1 (paperless statement source). D2–D4 slot after 0001 step 7 (§8). |

If 0001 is reworked before acceptance, these rows should be folded into it and
this section reduced to a pointer.

## Motivation

Two needs, one move.

**Shrink the residual with information that exists.** 0001's review queue is
dominated by rows where the account depends on *what was bought*: marketplace
orders, PayPal merchants that sell anything, the same supermarket for household
and for a party. The statement cannot say; the invoice usually can. The user
already archives invoices in paperless, so the information is sitting one API
call away and currently unused.

**One inbox, not two.** If bills live in paperless and statements live in a
folder, Autobook has two ingest mechanisms with two notions of "already
processed" and two places a file can go missing. Putting statements in paperless
too gives a single, already-backed-up archive with checksums, correspondents and
a REST API, and makes the folder path a fallback for users who do not run
paperless.

**Why now, before any code.** 0001's staging schema, rule format and JSON
contract are not yet built. Adding a document dimension after the fact would
change all three; adding it now costs a few columns.

## Design

### 1. Defer to paperless

0001's design principle is *defer to GnuCash*: where GnuCash ships the feature,
detect the need and hand off. This proposal extends it to the other side of the
pipeline. Paperless-ngx (3.x) does OCR, maintains correspondents, classifies
document types and tags with its own classifier, and optionally fills fields
with a local LLM. Autobook reimplements none of that.

Consequences:

- Autobook has **no PDF text extraction for bills**, no OCR, no layout parsing,
  no invoice model.
- The quality of bill metadata is a paperless configuration matter. Autobook
  documents what fields it reads and what it assumes about them (§4.1), and
  measures (§8) rather than trusts.
- Autobook talks to paperless **only through its REST API**, with a token held
  in the Secret Service (0001's credential rule). It never reads paperless's
  database or media directory: the API is the stable contract, the storage
  layout is not.

Paperless-ngx is GPL-3.0 and is accessed over HTTP. No licensing question
arises (ADR-0002 is unaffected).

### 2. Which representation is trusted for what

Paperless holds up to three representations of one document: the **original**
file as consumed, an **archive** version (PDF/A, OCR text layer added), and
extracted **content** text. Plus **metadata**: correspondent, document type,
tags, dates, custom fields.

| Use | Reads | Never reads |
|---|---|---|
| Statement lines and balances | Original file, parsed by the plugin | Archive version, OCR content, any metadata field |
| Statement → source account | Metadata (correspondent + document type), mapped by config | — |
| Bill matching | Metadata: correspondent, document type, created date, monetary total | Content text |
| Rule conditions | Metadata: correspondent, document type, tags | Content text |
| GnuCash document link | Document ID → URL | — |

The rule behind the table: **a statement is the reference, so nothing about it
may come from extraction.** An amount that passed through OCR has no place in a
ledger, because nothing downstream would catch the error. A bill is *evidence*,
and every use of bill evidence is cross-checked against the statement (§4.2), so
extraction errors there fail closed.

### 3. Statement source

#### 3.1 Discovery

A configured mapping identifies statements and binds them to source accounts:

```toml
[[paperless.statements]]
correspondent  = "Consorsbank"        # paperless correspondent name, resolved to ID at start
document_type  = "Kontoauszug"
source_account = "Aktiva:Girokonto:Consorsbank"
plugin         = "consorsbank"        # ofxstatement plugin name
```

Mapping is explicit, never guessed. A document of a statement type whose
correspondent has no mapping is reported, not ingested.

#### 3.2 Admission

For each candidate statement not yet in staging:

1. Fetch its metadata and the **original-file checksum** from paperless.
2. Download the original file to a private temporary location
   (`$XDG_RUNTIME_DIR`, mode `0600`, removed in a `finally`). Verify its checksum
   against paperless's before parsing.
3. Run the mapped plugin on it, exactly as the file path would.
4. Apply the **balance check** (§3.3).
5. Stage the lines, recording the statement in the `statements` table (§7).

Steps 1–4 failing for one statement rejects that statement and records why. It
does not stop other statements: a statement is the unit of failure here, the way
a row is in 0001's per-row tier.

**Text layer only.** If the original is a PDF, the plugin parses its embedded
text layer. A scanned statement without one is **rejected**, never OCR'd. Whether
the plugins parse PDF at all depends on which form the statements arrive in — see
*Open questions*.

#### 3.3 Balance check

Where the format carries opening and closing balances (PDF statements generally
do), admission requires

```
sum(line amounts) == closing − opening      # integer cents, exact
```

A mismatch rejects the statement: a line was dropped, duplicated or misread by
the plugin. This is a stronger guarantee than CSV exports usually allow, and it
is the cheapest possible test of a plugin change. The same closing balance then
feeds 0001's post-apply balance assertion.

Where the format carries no balances, admission records that the check was not
possible. Coverage reports show it, so a user can see which accounts are
protected and which are not.

#### 3.4 Dedup without FITIDs

FITID dedup stays where the format provides one. Where it does not (typical for
PDF statements), the row key becomes

```
(source_account, original_checksum, line_ordinal)
```

which is stable for a given file and safe as long as each statement is consumed
once. That assumption breaks in exactly one way: **two documents covering
overlapping periods** for the same account — a monthly PDF and an ad-hoc export,
or a re-downloaded statement saved as a separate document. So:

- Each admitted statement records its period `[start, end]`.
- A new statement overlapping an admitted one is admitted only if every line in
  the overlap matches an already-staged line exactly on
  `(post_date, amount, raw_memo)`; matching lines dedup to the existing rows,
  the rest stage normally.
- Any unmatched line inside the overlap rejects the statement. It is either a
  correction by the bank or a parse difference, and both need a human.

Paperless refuses byte-identical duplicates on consumption, which handles the
trivial case before Autobook sees it. The overlap rule handles the rest.

#### 3.5 Changed documents

Paperless 3.x keeps file versions of a document. A statement whose original
checksum changes after admission is a **batch-level failure**: staged rows refer
to a file that no longer exists in that form. Autobook reports it and books
nothing until a human resolves it.

### 4. Bill matching

#### 4.1 What Autobook reads from a bill

| Field | Source in paperless | Required |
|---|---|---|
| Total | A configured **monetary custom field** | Yes |
| Date | The document's created date | Yes |
| Correspondent | Correspondent | No, but strongly weights matching |
| Document type | Document type | Yes — selects bills vs. credit notes |
| Tags | Tags | No — rule conditions only (§5) |

Which document types count as bills, and which as credit notes (refunds,
*Gutschriften*), is configuration.

The monetary field is parsed with `Decimal` into **integer cents**, honouring
paperless's currency-code prefix (`EUR42.90`). A value with a currency other than
the transaction's never matches — consistent with 0001's FX boundary. A value
that does not parse is skipped and counted, not guessed.

**No assumption that metadata is human-verified.** With paperless's "Apply AI
Suggestions" workflow, or paperless-gpt filling custom fields, every one of these
values may be an unreviewed model output. Matching is designed so that this does
not matter for the total (§4.2), and does matter for tags (§5.2).

#### 4.2 The match

A bank row and a bill **match** when all hold:

- **Amount is exactly equal**, in integer cents, with sign: a bill matches a
  debit, a credit note matches a credit.
- **Date is in window**: `doc_date − before ≤ post_date ≤ doc_date + after`,
  asymmetric because payment follows invoicing — SEPA debits and invoices with
  payment terms land days to weeks later, card charges at or before the invoice
  date. Defaults are set from D2's measurements, not chosen here.
- **Correspondent is compatible**: the bill's correspondent is associated with
  the row's normalised merchant token in the user's linked history (§4.4), or
  the bill has no correspondent. An associated-elsewhere correspondent is a
  mismatch.

Exact amount equality is the load-bearing condition. It is what makes extraction
errors harmless: a misread total does not produce a wrong match, it produces no
match. Fuzzy amount matching is rejected (*Alternatives*).

#### 4.3 Ambiguity

Matching is computed **for the whole batch at once**, not row by row, so that
order cannot decide which row claims which bill:

- A row with exactly one candidate bill, where that bill has exactly one
  candidate row, is linked.
- Everything else is unlinked: two equal invoices in the window, two equal bank
  rows, a bill already linked by an earlier batch.

Unlinked is not a failure. The row proceeds through 0001's cascade exactly as if
documents did not exist. **A missing or ambiguous document must never block or
degrade a booking**; it can only fail to improve one.

Recurring fixed-amount charges (subscriptions) are the expected ambiguous case.
They are also the case 0001 hands to Scheduled Transactions, so the overlap is
small.

#### 4.4 Correspondent association

The association "paperless correspondent ↔ normalised merchant token" is
**derived from history**, the same way 0001 derives pack category mappings:
link historical bills to historical transactions using amount and date alone,
count which merchant tokens co-occur with which correspondents, and present the
result for confirmation:

```
Amazon EU S.à r.l.   ↔ AMAZON         212 links, 99% agreement   ✓
Stadtwerke Augsburg  ↔ SWA            36 links, 100%             ✓
Dr. Mustermann       ↔ (none)         4 links, tokens disagree    needs mapping
```

Confirmed associations are stored in the **user rules file** — they are personal
data (correspondent names include doctors, lawyers, individuals) and never enter
a pack.

### 5. What a matched bill may change

#### 5.1 Document-keyed rule conditions

A matched bill contributes conditions that **rules** may test:

```yaml
- id: amazon-geschenk
  match:
    merchant: AMAZON
    paperless_tag: Geschenk
  account: "Ausgaben:Geschenke"

- id: apotheke
  match:
    paperless_correspondent: "Stadt-Apotheke"
  account: "Ausgaben:Gesundheit"
```

That is the entire classification effect. kNN does not see documents: adding
document features would change what every vector means and give the corpus a
dimension most historical rows lack. The LLM tail does not see documents either:
that would move document content across the redaction boundary.

Rules are where this belongs because rules are the tier that is human-committed,
explainable and backtestable. A document-keyed rule is backtested exactly like
any other — against historical transactions that have a linked bill — before it
is accepted.

Rule candidates come from the same machinery as 0001's rule builder: for each
tag or document type, look at where its linked transactions were actually booked,
and propose a rule where agreement is high.

#### 5.2 Tag provenance

The total is protected by the exact-amount check. **Tags are not**: nothing
cross-checks a tag. If paperless's AI tags an invoice *Geschenk* and a rule keys
on that tag, a model has decided an account by proxy.

Two layers of defence:

- **Shadow mode first.** Document-keyed rules ship with an `auto: false` default:
  they propose, they do not book unattended, until shadow-mode precision for that
  rule clears the threshold that governs any rule. The proposal's `method`
  records `rule` plus the rule ID, so precision is measurable per rule.
- **Human-set tags, if paperless can tell us.** Paperless keeps an audit log.
  If its API exposes the actor of the last change to a document's tags, a rule
  can require that the matching tag was applied by a human. Whether that is
  available is an open question; until it is, shadow-mode evidence is the only
  defence, and the review file shows the tag next to the proposal.

#### 5.3 What a match never does

- Never changes the amount, date or source account of a booking. Those come from
  the statement.
- Never creates splits. Line items are §9.
- Never overrides a rule that did not use document conditions, or a confident
  kNN prediction. A document-keyed rule competes by rule precedence like any
  other rule.
- Never moves a row out of `out_of_scope`.

### 6. Write-back

#### 6.1 GnuCash document link

GnuCash can attach a document link to a transaction. For every applied row with a
linked bill — on `create` and on `match_existing` — the applier sets it to the
paperless document URL. No file is copied into the book's directory: the archive
is paperless, and a URL survives the book moving between machines where a file
path does not.

This crosses the JSON boundary: the applier's input row gains an optional
`doc_link` string. The applier validates it as a URL and does nothing else with
it. The pipeline still never imports `gnucash`.

The link is set inside the same `BeginEdit` / `CommitEdit` as the rest of the
transaction, and an existing link on a `match_existing` target is **not
overwritten** — a human put it there.

#### 6.2 Paperless stamp (optional)

After the applier reports success, the pipeline may stamp the bill in paperless:
a tag (`gebucht`) and a string custom field holding the transaction GUID. This is
a **convenience for the user browsing paperless**, nothing more:

- It is off by default and requires a token with change permission. Read-only is
  the default posture.
- Autobook never reads the stamp back to decide anything. "Already linked" is
  known from staging; the stamp can be removed, edited or lost without effect.
- Undoing a batch by `num` (0001) removes the stamps it wrote.

### 7. Staging changes

```
statements(
  paperless_doc_id, original_checksum PK,
  source_account, plugin, plugin_version,
  period_start, period_end,
  opening_balance, closing_balance,        -- integer cents, NULL if absent
  balance_check,                           -- passed | not_possible
  admitted_ts
)

proposals(
  ... 0001 columns ...,
  statement_checksum,                      -- FK statements; NULL for file-path ingest
  doc_id,                                  -- linked paperless bill, NULL if none
  doc_match,                               -- linked | ambiguous | none
  doc_candidates                           -- count, for measurement
)
```

Staging stores **IDs, checksums, amounts and dates — never document content**,
correspondent names included: names are resolved from paperless when the review
file is generated, so the staging database holds no special-category text it
did not already hold under 0001.

The review file gains one annotation line per linked row:

```
# id      st  date        amount    account                    description
#   rule amazon-geschenk | doc 4711 Amazon EU 2026-07-12 [Geschenk]
a1f3e9    ?   2026-07-14   -42,90   Ausgaben:Geschenke         AMAZON .MKTPLCE
```

### 8. Milestones

Each milestone carries **proves**, **retires**, **needs**, **done when**, and
whether it is a stopping point. They interleave with 0001's build order; none
precedes 0001 step 2.

#### D0 — Spikes *(with 0001 step 0)*

- **Proves:** the external surfaces behave as this document assumes.
- **Retires:** designing against an API that does not exist.
- **Needs:** a paperless 3.x instance with a copy of real documents; a restored
  book copy.
- **Done when:** each is answered in writing — original download and checksum via
  the API; custom field query by document type and date range; whether the audit
  log exposes the actor of a tag change; the Python bindings' call for setting a
  transaction's document link; the form the statements arrive in (PDF or export).
- **Stopping point:** no.

#### D1 — Statements from paperless *(after 0001 step 3)*

- **Proves:** paperless as a statement source loses nothing against the file path.
- **Retires:** a second ingest path that quietly diverges from the first.
- **Needs:** 0001 step 3 (ingest, staging, dedup); D0.
- **Done when:** for at least twelve months of statements per account, ingesting
  from paperless and from the same files on disk stages **identical rows**; the
  balance check passes on every statement that carries balances; the overlap rule
  is exercised by a synthetic overlapping statement and rejects a planted
  mismatch.
- **Stopping point:** yes — useful on its own as "one inbox".

#### D2 — Linkage backtest *(read-only, after 0001 step 2)*

- **Proves:** the premise — that documents resolve a meaningful share of the
  residual.
- **Retires:** building matching, write-back and document rules for an effect
  that turns out small.
- **Needs:** 0001's corpus export; read access to paperless. No writes anywhere.
- **Done when:** a report exists with, for the corpus period: link rate (rows with
  exactly one candidate), ambiguity rate, the measured date-lag distribution
  (which sets §4.2's window), the derived correspondent associations with
  agreement, and — the number that matters — **the share of rows that 0001's
  cascade would abstain on that gain a linked bill**, split by whether a
  document-keyed rule could resolve them.
- **Stopping point:** yes, and a **decision point**. If that last share is small,
  this proposal stops at D1 and is revised.

#### D3 — Linking and document links *(after 0001 step 5)*

- **Proves:** links are written correctly and reversibly.
- **Retires:** a link path that differs between `create` and `match_existing`.
- **Needs:** 0001's applier; D2 report.
- **Done when:** on a restored book copy, every linked row carries the paperless
  URL; an existing link on a matched transaction is untouched; undo-by-`num`
  removes created transactions and their paperless stamps; the batch-level
  matching is shown order-independent by shuffling input.
- **Stopping point:** yes.

#### D4 — Document-keyed rules in shadow mode *(alongside 0001 step 7)*

- **Proves:** document conditions improve precision-at-coverage, not just
  coverage.
- **Retires:** tag provenance (§5.2) as an unmeasured risk.
- **Needs:** D3; 0001 shadow mode.
- **Done when:** a month of shadow mode reports per-rule precision for
  document-keyed rules separately from other rules, and the review queue size
  with and without them.
- **Stopping point:** yes — the proposal graduates here.

### 9. Deferred: line-item splits

Invoices with line items (a marketplace order of three things for three
accounts) are the remaining "unknowable split". Paperless gives a document a
total, not lines, so this needs extraction Autobook has excluded (§1). It also
needs 0001's constraint *models never decide split ratios* to be stated
precisely: extraction may come from a model; assignment of lines to accounts is
per-line cascade; the sum must match the bank amount exactly or the row queues.

That is a separate proposal, after D4, if D2 shows the volume justifies it.

## Alternatives considered

**Autobook extracts invoices itself, with a local model.** Rejected. Paperless
already does it, the user already runs it, and a second extraction stack is a
second model, a second set of prompts and a second privacy surface. It would
also put document content inside Autobook's process, where today there is none.

**Reading statement amounts from paperless's OCR content or custom fields.**
Rejected. The statement is the reference; nothing would catch an error (§2).

**A watched directory instead of the paperless API.** Kept for statements as the
existing file path, because users without paperless must remain first-class.
Rejected for bills: a directory of PDFs gives no correspondent, no document type
and no total without Autobook doing extraction, which is the first alternative
again.

**Fetching bills from mail directly.** Out of scope. Mail credentials, OAuth and
MIME parsing would enter a GPL codebase whose security policy is about ledgers.
Paperless already consumes mail.

**Fuzzy amount matching** (tolerance for rounding, partial refunds). Rejected.
Exact equality is the property that makes model-filled totals safe. Partial
payments and split shipments remain unlinked, which is correct: unlinked costs
nothing.

**Documents as kNN features.** Rejected (§5.1): it changes the meaning of every
vector, most historical rows lack the feature, and it blurs abstention.

**Sending documents to the LLM tail.** Rejected. It moves special-category
content across the redaction boundary, which 0001 and SECURITY.md exist to
prevent.

**Paperless as the source of truth for "booked".** Rejected (§6.2). A tag in
another system that any user or workflow can remove cannot carry idempotency.

## Graduation criteria

1. D1: identical staged rows from paperless and file ingest over twelve months
   per account; balance check green on every statement that carries balances.
2. D2: the linkage report exists and its residual-resolution share is stated,
   with the decision taken on it recorded in this proposal.
3. D3: document links verified on a restored book; post-apply assertions
   unchanged and green; undo-by-`num` reverses links and stamps; matching shown
   order-independent.
4. D4: per-rule shadow-mode precision for document-keyed rules, reported per
   confidence band, meeting the same bar as any rule before `auto: true` is
   allowed.
5. No path exists by which document content reaches staging, logs or a model
   backend — verified by test, not review.

## Risks

What silently misreports if this is subtly wrong:

- **A wrong bill linked.** Batch-level matching (§4.3) is order-independent
  *within* a batch but cannot see the future: if bill 1 belongs to a charge that
  arrives in next month's statement, an equal-amount charge this month from the
  same correspondent can claim it as the only candidate. The mitigation is that a
  link alone changes no amount and no account; only a document-keyed rule turns
  it into a booking decision, and those are in shadow mode first. Worst case: a
  wrong document link, visible in GnuCash and correctable by hand.
- **An AI tag deciding an account** (§5.2). The real risk of this proposal.
  Shadow-mode precision per rule is the defence; audit-log provenance is the
  stronger one if available.
- **A plugin regression on PDF statements.** Caught by the balance check where
  balances exist; *not* caught where they do not. Accounts without balances
  should be visible as such in every coverage report.
- **Paperless unavailable.** Statement ingest does nothing (loud, harmless).
  Bill matching unavailable mid-run would make rows that depend on document
  rules queue — which 0001's coverage-drop detector reads as drift and refuses
  the batch. That is the right outcome, but the notification must say "paperless
  unreachable", not "classifier drift". Treat unreachable paperless as an explicit
  batch deferral.
- **Privacy by aggregation.** Staging plus paperless IDs plus review files
  together describe a person's medical, legal and religious spending. None of it
  leaves the machine; but the review file now contains correspondent names, and
  it lives in `/tmp` in 0001's launcher. Move it under `$XDG_RUNTIME_DIR`.

## Backward compatibility

- **File-path ingest is unchanged and remains supported.** Users without
  paperless lose nothing; every document feature is absent rather than degraded.
- **Staging schema** gains a table and four columns; nothing is built yet, so
  there is no migration.
- **Rule format** gains document-keyed conditions. A rule without them means what
  it meant.
- **JSON contract** gains an optional `doc_link`. An applier ignoring it would
  still write correct bookings.
- **Version gate tuple** gains the statement-source configuration (mapping,
  paperless version) and the correspondent association file hash. A change in
  either sends production back to scenario 1, as any classifier change does.

## Open questions

- **[OPEN] Statement form.** Will statements be stored in paperless as PDFs, or as
  the CSV/OFX exports the plugins read today? PDFs give balances (§3.3) but need
  PDF parsing in each plugin and lose FITIDs; exports keep FITIDs but usually
  lack balances. Mixing per bank is allowed by the design; the plugins' work
  differs.
- **[OPEN] Tag provenance.** Does the paperless audit log expose, through the API,
  who last changed a document's tags? Determines whether §5.2 has a structural
  defence or only a statistical one.
- **[OPEN] Date window.** Defaults come from D2's lag distribution. Per document
  type or global?
- **[OPEN] Paperless permissions.** A dedicated paperless user for Autobook, with
  view permission on statement and bill types only, seems right. Confirm it is
  expressible in paperless's permission model without exposing other documents.
- **[OPEN] Stamping default.** Off by default (§6.2). Revisit after D3 if users
  routinely want it.
- **[OPEN] Line-item splits** (§9) — after D4, if D2 justifies it.

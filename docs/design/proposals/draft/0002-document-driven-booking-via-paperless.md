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
> OCR (optical character recognition), correspondent recognition and field extraction belong to paperless, under
> the user's own paperless configuration. Autobook's model adapter never receives
> document content, so the redaction boundary in proposal 0001 holds unchanged.
> Nothing here lets a document — or a model's reading of one — decide an account
> directly: documents feed **rules**, and rules stay human-committed.
>
> **What this does not settle.** Statement acquisition (getting statements from a
> bank into paperless) is out of scope, as is mail retrieval (getting bills into
> paperless). Paperless is where acquisition ends. **Line-item splits** from
> invoices are deferred (§9; this needs a new ADR, not only a proposal). Securities stay out of scope for
> the reasons proposal 0001 gives; documents do not change them.
>
> **Relation to proposal 0001.** 0001 is still `draft`. This proposal *amends* it
> rather than superseding it — see *Changes to proposal 0001* below for exactly
> what moves. For the rows in that table, this proposal governs; elsewhere 0001
> does. 0001's acceptance criterion (build order step 2 has reported) is
> unaffected. This proposal is accepted separately, when **D2's report** exists:
> its own read-only premise test (§8, D2), run on the same corpus.

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
| Rule types: creditor ID, memo pattern | Adds **document-keyed** conditions: paperless correspondent, document type, tag (§5). The full rule precedence table, including ambiguity flags, is §5.1 and governs everywhere. |
| Applier output `{proposal_id, tx_guid, status}` | Applier input gains an optional `doc_link`; GnuCash's document link is set on create and on `match_existing` (§6.1). On a matched transaction it is the only thing Autobook writes, and never over an existing link. |
| Build order 3: "Ingest, staging, FITID dedup" | Split: file ingest as before, then D1 (paperless statement source). The D-milestones interleave with 0001's steps as set in [architecture chapter 9](../../architecture/09-build-order-and-roadmap.md): D0 with step 0, D2 after step 2, D1 after step 6, D3 after step 5, D4 with step 7 (§8). |
| Staging: `proposals` only | Adds a `statements` table (§7). File-path ingest records a `statements` row too, with the file's checksum, so both paths stage identical rows. |
| Version gate tuple (rule-file hash, prompt version, model ID, …) | Adds the statement-source configuration, the correspondent association file hash, the bill date window, and which document types count as bills and credit notes (*Backward compatibility*). |
| Launcher writes the review file to `/tmp/booking.txt` | `$XDG_RUNTIME_DIR/autobook/review.txt`, mode 0600, removed in a `finally`: the review file now carries correspondent names. Already folded into 0001's launcher sketch. |

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
a REST API. The folder path stays first-class, for users who do not run
paperless.

**Why now, before any code.** 0001's staging schema, rule format and JSON
contract are not yet built. Adding a document dimension after the fact would
change all three; adding it now costs a few columns.

## Design

**What this touches** (the template's higher-bar list):

- **The classification cascade or its confidence gates — yes.** Rules gain
  document-keyed conditions and a precedence tier of their own (§5.1). The
  k-nearest-neighbour (kNN) tier, the large language model (LLM) tail and their
  gates are unchanged; neither sees documents.
- **The staging schema or a disposition — yes.** A `statements` table and four
  `proposals` columns (§7). No new disposition.
- **The write path, idempotency, or locking — yes.** The applier sets a
  document link on `create` and `match_existing` (§6.1), inside the existing
  `BeginEdit` / `CommitEdit`; undo removes links Autobook added. Idempotency and
  locking are unchanged.
- **What leaves the machine — no new path.** Autobook reads from paperless and,
  only if stamping is on, writes a tag and a GUID to it (§6.2); paperless is the
  user's own service. No document content reaches a model backend.

Component: everything here is pipeline except the document link, which crosses
the JSON boundary as an optional `doc_link` field (§6.1).

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

1. Fetch its metadata, its current **document version** and the
   **original-file checksum** from paperless.
2. Download that version of the original file (`?version=`) to a private
   temporary location (`$XDG_RUNTIME_DIR`, mode `0600`, removed in a `finally`).
   Verify its checksum against paperless's before parsing.
3. Run the mapped plugin on it, exactly as the file path would.
4. Apply the **balance check** (§3.3).
5. Stage the lines, recording the statement in the `statements` table (§7) with
   status `admitted`.

Steps 1–4 failing for one statement rejects that statement: it is recorded in
`statements` with status `rejected` and the reason. It does not stop other
statements: a statement is the unit of failure here, the way
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
feeds 0001's post-apply balance assertion (balance at the closing date ==
closing balance − lines of the statement not yet applied).

Where the format carries no balances, admission records that the check was not
possible. Coverage reports show it, so a user can see which accounts are
protected and which are not.

#### 3.4 Dedup without FITIDs

FITID (financial institution transaction ID) dedup stays where the format
provides one — and only where it is the bank's. Each ofxstatement plugin
declares whether its `id` field is bank-supplied. Synthesised IDs (ofxstatement
hashes date + memo + amount, so two identical payments on one day collide) are
treated as no FITID. Where there is none (typical for PDF statements), the row
key becomes

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
- Matching is **count-aware**: if the overlap holds three identical lines, three
  staged lines must match them. Two equal coffees on one day are two lines, not
  one.
- Any unmatched line inside the overlap rejects the statement. It is either a
  correction by the bank or a parse difference, and both need a human.

Paperless-ngx accepts byte-identical duplicate documents by default. A second
document whose original checksum is already in `statements` with status
`admitted` is skipped. The overlap rule handles the rest.

#### 3.5 Changed documents

Paperless 3.x keeps file versions of a document; admission records the version
it read. A statement whose original checksum changes after admission is a **batch-level failure**: staged rows refer
to a file that no longer exists in that form. Autobook reports it and books
nothing until a human resolves it.

### 4. Bill matching

#### 4.1 What Autobook reads from a bill

| Field | Source in paperless | Required |
|---|---|---|
| Total | A configured **monetary custom field** | Yes |
| Date | The document's `created` date — the first date paperless found in the OCR text, not necessarily the invoice date | Yes |
| Correspondent | Correspondent | No, but constrains matching; without one, a bill gives only a weak match (§4.2) |
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
  date. Defaults are set from D2's measurements, not chosen here. D2 measures
  the lag against paperless's `created` date, which is the first date found in
  the OCR text — an order date or a delivery date as often as an invoice date —
  so the window must allow for that.
- **Correspondent is compatible**: the bill's correspondent is associated with
  the row's normalised merchant token in a **confirmed** correspondent
  association (§4.4). An associated-elsewhere correspondent is a mismatch.

A bill **without a correspondent** can only produce `doc_match = weak`: a hint
line in the review file, never input to a rule. A bill link feeds a rule only
when the bill's correspondent has a confirmed association, so a bill whose
correspondent has no confirmed association yet is treated the same way — weak,
a hint only. (The amount and date conditions still apply to a weak match.)

Exact amount equality is the load-bearing condition. It is what makes extraction
errors harmless: a misread total does not produce a wrong match, it produces no
match. Fuzzy amount matching is rejected (*Alternatives*).

#### 4.3 Ambiguity

Matching is computed **for the whole batch at once**, not row by row, so that
order cannot decide which row claims which bill. Paperless-ngx accepts duplicate
documents by default, so bill candidates are first deduplicated by
`original_checksum` — otherwise one invoice consumed twice would look like two
candidates and leave the row unlinked.

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
a pack. A confirmed association is a precondition for any bill link to feed a
rule (§4.2, §5.1).

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

**Rule precedence.** This one table governs everywhere — 0001's *Rules* section
and the architecture point here. The first tier that applies decides:

| Tier | Source | Effect |
|---|---|---|
| 1 | **Creditor-ID rule** (SEPA Gläubiger-ID) | Proposes its account. |
| 2 | **Document-keyed rule** — only with a confirmed correspondent association (§4.4), `auto: true`, and shadow mode passed (§5.2) | Proposes its account. |
| 3 | **Ambiguity flag** (`AMAZON`, `PAYPAL` …) | Forces `?`; nothing is pre-marked. |
| 4 | **Memo-pattern rule** | Proposes its account. |
| 5 | **kNN**, both gates passed | Proposes its account. |
| 6 | **LLM** (tail) | Proposes its account, always as `?` until shadow mode has measured `method=llm` (0001, *LLM*). |

- A rule's `priority` field orders rules **within** a tier only.
- `auto` is a field on every rule: default `true`, except document-keyed rules,
  which default to `false`. `auto: true` means the rule's proposals may be
  pre-marked `a` in the review file.
- The rule builder reports conflicts between any two tiers on historical rows,
  not only between rules of the same tier.
- A document-keyed rule that does not yet meet all three tier-2 conditions takes
  no part in precedence: the row is classified as if the rule did not exist, and
  the rule's proposal is recorded in staging and shown beside the row in the
  review file, so shadow mode can measure it.

#### 5.2 Tag provenance

The total is protected by the exact-amount check. **Tags are not**: nothing
cross-checks a tag. If paperless's AI tags an invoice *Geschenk* and a rule keys
on that tag, a model has decided an account by proxy.

Two layers of defence:

- **Shadow mode first.** Document-keyed rules ship with an `auto: false` default:
  they propose, they are never pre-marked `a`, until shadow-mode precision for
  that rule clears the threshold that governs any rule. The proposal records
  `method = rule` and the `rule_id`, so precision is measurable per rule.
- **Human-set tags.** Paperless keeps an audit log, and
  `GET /api/documents/{id}/history/` gives the actor of each change. No actor,
  or `System`, means a machine set the tag — AI-suggestion workflows are recorded
  as `System`. A user accepting a suggestion is recorded as that user, so
  actor = user means "human-accepted", not "human-chosen": a rule may require it,
  and such rules are still shadowed. This needs `PAPERLESS_AUDIT_LOG_ENABLED`
  (default true) on the paperless instance. The review file shows the tag next
  to the proposal.

#### 5.3 What a match never does

- Never changes the amount, date or source account of a booking. Those come from
  the statement.
- Never creates splits. Line items are §9.
- Never overrides a creditor-ID rule. A document-keyed rule outranks the ambiguity
  flag, memo-pattern rules and kNN only once it qualifies for tier 2 of the
  precedence table (§5.1); until then it overrides nothing, and the flag still
  forces `?`.
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
overwritten** — a human put it there. On a matched transaction the link is the
only thing Autobook writes (no `num`, no FITID stamp — 0001, *Idempotency*), and
undoing that row removes only the link Autobook added.

#### 6.2 Paperless stamp (optional)

After the applier reports success, the pipeline may stamp the bill in paperless:
a tag (`gebucht`) and a string custom field holding the transaction GUID. This is
a **convenience for the user browsing paperless**, nothing more:

- It is off by default and requires a token with change permission. Read-only is
  the default posture.
- Autobook never reads the stamp back to decide anything. "Already linked" is
  known from staging; the stamp can be removed, edited or lost without effect.
- Undoing a batch (0001, *Idempotency*) removes the stamps it wrote.

### 7. Staging changes

```
statements(
  original_checksum PK,                    -- of the file, for paperless and file-path ingest alike
  paperless_doc_id, doc_version,           -- NULL for file-path ingest
  source_account, plugin, plugin_version,
  period_start, period_end,
  opening_balance, closing_balance,        -- integer cents, NULL if absent
  balance_check,                           -- passed | not_possible
  status, reason,                          -- admitted | rejected; why, when rejected
  admitted_ts
)

proposals(
  ... 0001 columns ...,                    -- PK (source_account, fitid_or_key)
  statement_checksum,                      -- FK statements; set for every ingest path
  doc_id,                                  -- linked paperless bill, NULL if none
  doc_match,                               -- linked | weak | ambiguous | none
  doc_candidates                           -- count, for measurement
)
```

File-path ingest records a `statements` row too, with the checksum of the file,
so D1's "identical rows" test can hold. For rows without a bank FITID,
`fitid_or_key` is `(original_checksum, line_ordinal)`, making the staging key
`(source_account, checksum, ordinal)` (§3.4).

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

A weak match (§4.2) gets the same kind of line, marked `weak`, and is a hint
only.

### 8. Milestones

Each milestone carries **proves**, **retires**, **needs**, **done when**, and
whether it is a stopping point. They interleave with 0001's build order; none
precedes step 2 except the D0 spikes. The execution order of all steps is set in
[architecture chapter 9](../../architecture/09-build-order-and-roadmap.md):
0 + D0 → 1 → 2 → **D2** → 3 → 6 → **D1** → 4 → 5 → **D3** → 7 + **D4** → 8 → 9.

#### D0 — Spikes *(with 0001 step 0)*

- **Proves:** the external surfaces behave as this document assumes.
- **Retires:** designing against an API that does not exist.
- **Needs:** a paperless 3.x instance with a copy of real documents; a restored
  book copy.
- **Done when:** each is answered in writing — original download (by version)
  and checksum via the API; custom field query by document type and date range;
  that the instance has `PAPERLESS_AUDIT_LOG_ENABLED` and the history endpoint
  returns the actors §5.2 expects; whether every document other than statements
  and bills has an owner (unowned documents are visible to every user, which
  defeats a restricted Autobook user); the Python bindings' call for setting a
  transaction's document link; the form the statements arrive in (PDF or export).
- **Stopping point:** no.

#### D1 — Statements from paperless *(after 0001 step 6)*

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
  against paperless's `created` date (which sets §4.2's window), the derived correspondent associations with
  agreement, and — the number that matters — **the share of rows that 0001's
  cascade would abstain on that gain a linked bill**, split by whether a
  document-keyed rule could resolve them.
- **Stopping point:** yes, and a **decision point**. If that last share is small,
  this proposal stops at D1 and is revised. D2's report is also this proposal's
  acceptance trigger.

#### D3 — Linking and document links *(after 0001 step 5)*

- **Proves:** links are written correctly and reversibly.
- **Retires:** a link path that differs between `create` and `match_existing`.
- **Needs:** 0001's applier; D2 report.
- **Done when:** on a restored book copy, every linked row carries the paperless
  URL; an existing link on a matched transaction is untouched; undo removes
  created transactions and their paperless stamps, and on matched transactions
  removes only the link Autobook added; the batch-level
  matching is shown order-independent by shuffling input.
- **Stopping point:** yes.

#### D4 — Document-keyed rules in shadow mode *(alongside 0001 step 7)*

- **Proves:** document conditions improve precision-at-coverage, not just
  coverage.
- **Retires:** tag provenance (§5.2) as an unmeasured risk.
- **Needs:** D3; 0001 shadow mode.
- **Done when:** shadow mode — continuous, closing when there is enough
  evidence — reports per-rule precision for document-keyed rules separately from
  other rules, and the review queue size with and without them.
- **Stopping point:** yes — the proposal graduates here.

### 9. Deferred: line-item splits

Invoices with line items (a marketplace order of three things for three
accounts) are the remaining "unknowable split". Paperless gives a document a
total, not lines, so this needs extraction Autobook has excluded (§1). It also
needs 0001's constraint *models never decide split ratios* to be stated
precisely: extraction may come from a model; assignment of lines to accounts is
per-line cascade; the sum must match the bank amount exactly or the row queues.

That is a separate proposal, after D4, if D2 shows the volume justifies it. It
cannot be a proposal alone: "splits are rules-tier only" is a MUST, and changing
it needs a new ADR first.

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
   unchanged and green; undo reverses links and stamps; matching shown
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
  Shadow-mode precision per rule is the defence; audit-log provenance adds a
  structural one, but "human-accepted" is weaker than "human-chosen".
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
  leaves the machine; but the review file now contains correspondent names. It
  lived in `/tmp` in 0001's launcher; it now lives under `$XDG_RUNTIME_DIR`,
  mode 0600, removed in a `finally` (see *Changes to proposal 0001*).

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
  paperless version), the correspondent association file hash, the bill date
  window (§4.2), and the configuration of which document types count as bills
  and which as credit notes (§4.1). A change in any of them sends production
  back to scenario 1, as any classifier change does.

## Open questions

- **[OPEN] Statement form.** Will statements be stored in paperless as PDFs, or as
  the CSV/OFX exports the plugins read today? PDFs give balances (§3.3) but need
  PDF parsing in each plugin and lose FITIDs; exports keep FITIDs but usually
  lack balances. Mixing per bank is allowed by the design; the plugins' work
  differs.
- **Tag provenance — answered.** `GET /api/documents/{id}/history/` gives the
  actor of each change (§5.2), given `PAPERLESS_AUDIT_LOG_ENABLED`; D0 confirms
  it on the real instance.
- **[OPEN] Date window.** Defaults come from D2's lag distribution. Per document
  type or global?
- **[OPEN] Paperless permissions.** A dedicated paperless user for Autobook, with
  view permission on statement and bill types only, seems right. It only works
  if every other document has an owner: unowned documents are visible to all
  users. D0 checks this; open until it does.
- **[OPEN] Stamping default.** Off by default (§6.2). Revisit after D3 if users
  routinely want it.
- **[OPEN] Line-item splits** (§9) — after D4, if D2 justifies it.

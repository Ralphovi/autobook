---
created: 23.10.2026 21:00
type: proposal
status: draft
author: Eduard Ralph
tracking-issue:
tags:
  - proposal
  - classification
  - rules
  - design
---

# Proposal: Rules first — mined from history

> **What this settles.** The rules tier is built **first**, not at build step 8,
> and most rules are **mined from the user's own booking history** rather than
> written by hand. Mining produces candidates; a human accepts them; acceptance is
> a measurement on a held-out period, never an in-sample agreement rate. kNN is
> then judged on what the rules leave over — the residual — which is its real job.
>
> **What this does not change.** The precedence table (proposal 0002 §5.1) is
> unchanged: mined rules are ordinary creditor-ID (tier 1) and memo-pattern
> (tier 4) rules. Rules stay human-committed, kNN and the LLM still return a single
> account, and split templates stay hand-written.
>
> **Relation to proposals 0001 and 0002.** Both are still `draft`. This proposal
> *amends* 0001 the way 0002 does — see *Changes to proposal 0001* below. For the
> rows in that table, this proposal governs; elsewhere 0001 and 0002 do. Its
> milestones (R1, R2) ride on existing build steps, so the execution order in
> [architecture chapter 9](../../architecture/09-build-order-and-roadmap.md)
> keeps its sequence; only the content of steps 2, 6 and 8 changes. It is
> accepted when R1's report exists.

## In plain language

The plan so far: let a nearest-neighbour search over your history do almost all
the classification, and add a rules file late, once a GUI exists to build rules
in. That gets the order backwards. Rules are the simplest part of the cascade:
a rule that fires is explainable and does the same thing every time.

Most of them are also already in your history. Every insurance debit from the
same creditor ID has gone to the same account for years; every REWE purchase to
groceries. Finding those needs no AI — group the history, keep the groups that
always went to the same place, and offer them as rules. You accept them in a
text file, much like the review file. kNN and the LLM then only have to handle
what is left.

## Changes to proposal 0001

| 0001 says | This proposal |
|---|---|
| Rules: "hand-owned. Model may *propose*; the human commits." | Human-committed, mostly **mined**: the human's job is acceptance, not authorship. Three candidate sources (§2). |
| Rule fields: `created-by` (`llm`/`user`), backtest score at acceptance time | `created-by` gains `mined`. The score is the **held-out** score (§3), and the rule records the mining cutoff it was scored against. |
| Scenario 1 rule builder: "1. Cluster unmatched / low-confidence rows. 2. LLM proposes pattern + target." | 1. Mined candidates first, ranked by held-out coverage. 2. Remaining clusters; the LLM drafts a pattern only where a cluster has no shared token (§2). Steps 3–4 unchanged. |
| Build order 2: corpus export + kNN + backtest harness | Adds **R1**: rule mining inside the rolling-origin backtest, reported as method `rule`, and kNN reported on the residual (§5). |
| Build order 6: text-file review | Adds **R2**: the rules file, the rule engine for tiers 1, 3 and 4, and a candidate file for accepting mined rules (§5). |
| Build order 8: rules file, LLM tail, thresholds on evidence | LLM tail, **LLM rule drafting**, thresholds on evidence. The rules file has moved to step 6. |

If 0001 is reworked before acceptance, these rows should be folded into it and
this section reduced to a pointer.

## Motivation

**The simplest tier ships last.** In 0001's build order, everything from the
first backtest to a month of shadow evidence runs on kNN alone. The tier that
needs no confidence gate — a deterministic rule — arrives at step 8, through the
heaviest machinery: LLM drafting, a GTK4 builder, conflict detection.

**The premise test asks a harder question than it needs to.** Step 2 asks
whether kNN can carry the whole classification. If a few dozen mined rules cover
the head of the volume at near-perfect held-out precision, kNN only has to carry
the tail — a smaller claim, easier to judge, and the one that actually matters.

**Writing rules by hand is the step people give up on.** 0001 already makes this
argument for the category mapping during onboarding: derive it from history,
let the user confirm. The same argument applies to rules.

## Design

**What this touches** (the template's higher-bar list):

- **The classification cascade or its confidence gates — yes,** in what feeds
  tiers 1 and 4, not in the tiers themselves. Gates and precedence are unchanged.
- **The staging schema or a disposition — no.** Proposals already record
  `method = rule` and `rule_id`.
- **The write path, idempotency, or locking — no.**
- **What leaves the machine — no new path.** Mining is local. LLM drafting
  (source 3) sends normalised merchant tokens of a cluster, which is what the LLM
  tail already sends under 0001's redaction boundary.

Component: pipeline only — the trial tooling (mining, scoring) and the
classifier (loading the rules file). Nothing crosses the JSON boundary.

### 1. Rules first

The rules file and the engine for tiers 1, 3 (ambiguity flags) and 4 exist from
build step 6. A mined rule is indistinguishable at runtime from a hand-written
one: it is a line in the user's rules file with an `id`, a `match`, an
`account`, `priority` and `auto`. Only its provenance fields differ.

### 2. Rule sources

Three sources, in order of trust. All three produce **candidates**; none writes
to the rules file directly.

1. **Mined, creditor ID** (`created-by: mined`, tier 1). Group the corpus by
   `(source_account, sign, creditor_id)`. A group becomes a candidate when it has
   at least 6 rows, at least 98 % recency-weighted agreement on one destination
   account (the kNN half-life, ~18 months), and its most recent row agrees. A
   plain group-by; no model.
2. **Mined, merchant pattern** (`created-by: mined`, tier 4). For rows without a
   creditor ID: take kNN neighbourhoods that pass **both** gates and are
   unanimous, and emit their shared normalised merchant token as an anchored
   pattern (`^TOKEN\b`), with the same occurrence and agreement thresholds. kNN
   is used here to cluster history, not to classify.
3. **LLM-drafted** (`created-by: llm`, tier 4). Only for clusters whose tokens
   vary too much to share one — the model drafts a pattern that covers them.
   Same acceptance path, no privileged status.

Document-keyed rules (proposal 0002 §5.1) already come from the same procedure —
"look where linked transactions were actually booked, propose where agreement is
high" — and follow 0002's shadow-mode rules, not this proposal's `auto` default.

**Never mined:**

- **Tokens carrying an ambiguity flag** (`AMAZON`, `PAYPAL`). Tier 3 forces `?`
  regardless, so a mined rule for them would never pre-mark; mining them would
  only add noise to the candidate list.
- **Recurring fixed-amount debits the assistant detector marks as schedulable.**
  Those are offered as a Scheduled Transactions handoff instead. Once the SX
  exists, its occurrences resolve as `match_existing` before any rule is
  consulted (architecture section 6.3), so a rule would be dead weight — and
  offering a rule first makes the row look solved and hides the better fix.
- **Transfers** between the user's own accounts and rows dispositioned
  `out_of_scope`. The structural checks own both.
- **Split templates.** The corpus is two-split-only, so mining can produce only
  single-account rules; split templates remain hand-written.
- **Rows that are not `observed` or `corrected`.** Provenance tagging already
  guarantees no other row exists in the corpus.

### 3. Acceptance is measured on a held-out period

Mining a rule from a group and then scoring it on the same group is circular:
its agreement is guaranteed in-sample. Mining follows the backtest's rule — a
row's future never votes for it:

- **Per candidate:** mine on rows dated before a cutoff (default: twelve months
  before the newest row), score on rows on or after it. The candidate shows its
  held-out coverage, held-out precision, and every disagreeing row.
- **A candidate with no held-out rows is unproven**, not perfect. It is shown,
  and if accepted it gets `auto: false` until review decisions have measured it.
- **LLM drafts** see only rows before the cutoff, for the same reason.
- **For the method as a whole:** the rolling-origin backtest re-mines at every
  origin month *m* from rows before *m* and applies the result to *m*, reported
  as method `rule` beside `knn` and `token_bayes` (§5, R1).

### 4. Acceptance, `auto`, and staleness

**Candidate file.** `trial mine` writes candidates to a file in the review-file
idiom: one line per candidate, with its id, match, target, held-out coverage and
precision. `a` accepts, `x` rejects (the rejection is recorded, so the candidate
is not offered again unless its numbers change). The parser follows the review
file's rules: by id, never by position; strict; an unknown id, status character
or account aborts the whole file with a line number. Accepted candidates are
appended to the **user** rules file. The GTK4 rule builder (step 9) is a faster
way to do the same thing, not a prerequisite.

**`auto` default.** A mined rule is `auto: true` when its held-out precision
meets the bar any rule must meet and it has at least the minimum number of
held-out rows; otherwise `auto: false`. An LLM-drafted rule is `auto: false` until
review decisions have measured it — the same treatment the LLM tail gets.

**New fields.** `created-by: mined`, `mined_cutoff` (the date the held-out
period started), and the held-out score at acceptance time.

**Rules go stale.** A mined rule encodes past practice. After the user
restructures the chart of accounts it keeps firing with full determinism. Every
review decision on a row with `method = rule` is recorded against its `rule_id`;
a rule whose rows are being corrected is flagged in the candidate file for
re-mining, and its `auto` drops to `false` until it is re-accepted. A rule whose
target account no longer exists already fails the row (architecture section 6.3).

**Privacy.** Mined rules are personal data and land in the user rules file only.
A mined memo token can be a private person's name (rent paid to a landlord), so
nothing mined is ever exported to a pack except through 0001's explicit reviewed
export. The backtest report stays counts-only (architecture section 8.5); the
candidate file holds tokens and accounts and is local, like the rules file.

### 5. Milestones

Each rides on an existing build step, so architecture chapter 9's sequence is
unchanged.

#### R1 — Rule mining in the backtest *(with 0001 step 2)*

- **Proves:** what share of volume deterministic rules cover, at what held-out
  precision, and what is left for kNN.
- **Retires:** a premise test that asks kNN to carry the head of the volume it
  never needed to.
- **Needs:** the corpus export and the rolling-origin backtest.
- **Done when:** the backtest report carries method `rule` (mined per origin)
  with the same strata and bands as `knn`, plus kNN and `token_bayes` reported on
  the **residual** — the rows `rule` did not decide. Counts only.
- **Stopping point:** yes, and part of step 2's **decision point**. If rules
  cover most volume, kNN's priority drops. If rules cover the head and kNN cannot
  carry the residual, the design changes, as before.

#### R2 — Rules file, rule engine, candidate file *(with 0001 step 6)*

- **Proves:** real statements are classified by accepted rules first, and the
  review file shows `method = rule` with its `rule_id`.
- **Retires:** a review file that only ever shows kNN proposals.
- **Needs:** R1; the review file.
- **Done when:** the classifier loads the user rules file (tiers 1, 3, 4);
  `trial mine` writes the candidate file; its strict parser appends accepted
  candidates to the rules file; per-rule correction counts are recorded.
- **Stopping point:** yes.

## Alternatives considered

- **Keep rules at step 8, built in the GUI.** The original order. It reaches the
  same rules much later, through more machinery, and leaves the premise test
  asking the wrong question.
- **Hand-written rules only.** Deterministic, but slow, and the step people give
  up on. Mining finds the same rules from history in seconds.
- **No rules tier; kNN for everything.** Gives up the tier that needs no
  confidence gate, and makes every recurring debit depend on a distance cutoff.
- **Mine without a held-out period.** Circular: in-sample agreement is guaranteed,
  so the score would say nothing.
- **Let mined rules write the rules file directly.** Breaks "rules are
  human-committed", which is where determinism comes from.

None of these reopens a row of 0001's *Rejected alternatives*.

## Graduation criteria

1. R1: the backtest report carries method `rule` and the residual results, and
   the decision taken on them is recorded in this proposal.
2. R2: on synthetic fixtures, the candidate file round-trips — accepted
   candidates become rules that fire, rejected ones are not offered again, a
   malformed file aborts with a line number and changes nothing.
3. Held-out scoring shown non-circular by test: a candidate mined from rows that
   are all inside the held-out period is rejected as unproven, not scored.
4. A mined rule's corrections lower its `auto` without anyone editing the file.

## Risks

What silently misreports if this is subtly wrong:

- **A mined rule encodes a past mistake.** If the history booked something wrong
  consistently, mining makes it deterministic. Mitigation: the human accepts
  every rule and sees every disagreeing row; agreement thresholds are high; review
  corrections lower `auto`.
- **A mined rule outlives a CoA restructure.** It fires with full determinism
  into an account that still exists but is no longer used for that purpose. This
  is the real risk of the proposal. The correction-rate flag is the defence; it
  depends on the user correcting rows in review rather than in GnuCash afterwards.
- **A pattern too broad.** `^TOKEN\b` mined from a short token can match a
  different merchant later. The held-out score catches what history contains,
  not what the future brings; per-rule correction counts catch the rest.
- **Leakage in the held-out score.** If the cutoff is applied to statement dates
  in one place and booking dates in another, the score is partly in-sample. Use
  the backtest's month boundary rule everywhere.

## Backward compatibility

- **Nothing is built yet** beyond the backtest, so there is no migration.
- **Rule format** gains `created-by: mined`, `mined_cutoff` and the held-out
  score. A rule without them means what it meant.
- **Backtest report** gains method `rule` and the residual results; existing
  fields are unchanged. `report_version` increments.
- **Version gate tuple** is unchanged: accepted rules are in the rules file,
  whose hash is already in it. Mining parameters change which candidates are
  offered, not what any accepted rule does.

## Open questions

- Mining thresholds (6 rows, 98 % agreement, a twelve-month held-out period, the
  minimum held-out rows for `auto: true`) are starting values, to be set from
  R1's report like every other threshold.
- Whether mined rules are re-mined on a schedule, or only when the correction
  flag fires.
- Whether kNN neighbourhoods are the right clusters for source 2, or whether
  grouping on the normalised token alone is enough. R1 can report both.

#!/usr/bin/env python3
"""Automated issue priority triage (ADR-0003 sections 4 and 5).

Two commands, run by two jobs of .github/workflows/triage-priority.yml, because GitHub
scopes the token's permissions per job (ADR-0003 sections 4 and 5):

    classify   reads issues, asks Claude once per issue, writes the plan as JSON.
               Runs with a read-only token; the only other credential is the Claude API
               identity token. It never writes to GitHub. An issue holding a
               checksum-valid IBAN, a credential of a known shape or a GnuCash account
               path is not sent to the model at all (ADR-0003 section 5).
    apply      reads that plan, checks every label against the fixed sets in
               labels.json, and applies labels, an assignee and one comment. Runs with
               issues: write and never imports the Anthropic SDK or calls a model.

For each issue that has no `priority:*` label, the model returns a JSON verdict (type,
severity, reach, area, flags, the review priority of a deferred finding). The priority
is computed HERE from ADR-0003's table and overrides, never by the model. The model
has no tools. The script never sets a milestone, and withholds any reason that repeats
the issue's own text, so a statement line, IBAN, amount, memo or key pasted into a report
is not copied into the comment. A report that looks like an undisclosed vulnerability is
labelled but not restated (ADR-0003 section 4).

    triage_priority.py classify --issue 42 --out plan.json
    triage_priority.py classify --all --limit 20 --dry-run
    triage_priority.py apply --plan plan.json
Tests: python -I -m unittest discover -s .github/triage
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent

MODEL = "claude-sonnet-5-5"
# Classification: low effort is enough and keeps thinking short. max_tokens covers that
# thinking plus a ~300-token verdict; hitting it is handled as "could not classify".
EFFORT = "low"
MAX_TOKENS = 4096
# Input cap, the main cost lever. The cut is stated in the comment, never silent.
MAX_TITLE = 300
MAX_BODY = 6000
MAX_REASON = 200
MAX_COMMENT = 6000
MARKER = "<!-- autobook-triage -->"
# Text the project template ships in prompt.md and labels.json until they are filled in.
TEMPLATE_MARKERS = ("PROJECT SUMMARY", "EXAMPLE, replace")
# Only the workflow's own comments count as triage comments; anyone can type the marker.
# The REST API names the bot "github-actions[bot]", GraphQL names it "github-actions".
BOT_LOGIN = "github-actions[bot]"
GRAPHQL_BOT_LOGIN = "github-actions"
# An issue left at needs-triage is triaged again only when it is edited, at most this often.
MAX_RETRIES = 2
# A back-fill scans at most this many open issues, in pages of BACKFILL_PAGE.
MAX_SCAN = 500
BACKFILL_PAGE = 50
# A back-fill leaves an issue alone that changed this recently: an issue event's own run
# (opened, reopened, edited) may still be classifying it, and both would comment. The
# window is longer than both jobs' timeouts together (15 + 10 minutes).
BACKFILL_QUIET = timedelta(minutes=30)
# Only these authors can name a deferred review's priority in an issue; a stranger
# writing "Review priority: P0" gets the table like any other issue.
TRUSTED_AUTHORS = ("OWNER", "MEMBER", "COLLABORATOR")
# Audience of the GitHub OIDC token the Claude API accepts (ADR-0003 section 5).
OIDC_AUDIENCE = "https://api.anthropic.com"

# `spike` is Autobook's label for a time-boxed investigation; it plays the part other
# repositories give `research`.
TYPES = ("bug", "enhancement", "documentation", "spike")
SEVERITIES = ("critical", "major", "minor", "trivial")
REACHES = ("common", "edge", "adversarial")
FLAGS = ("booking_integrity", "security_or_privacy")
REVIEW_PRIORITIES = ("none", "P0", "P1", "P2", "P3")
# ADR-0003 section 4 sets a priority on every issue: for an enhancement, documentation or
# spike, severity is how much it matters if it is not done.
PRIORITISED_TYPES = TYPES

# ADR-0003 section 2: severity x reach -> priority (0 = P0).
TABLE = {
    "critical": {"common": 0, "edge": 1, "adversarial": 1},
    "major": {"common": 1, "edge": 2, "adversarial": 2},
    "minor": {"common": 2, "edge": 3, "adversarial": 3},
    "trivial": {"common": 3, "edge": 3, "adversarial": 3},
}
# ADR-0003 section 3: each override is a floor (the priority is at least this). A flag
# comes from the model; a label is one the issue already has.
FLOORS = {
    "booking_integrity": (1, "booking-integrity bug"),
    "security_or_privacy": (1, "security or privacy bug"),
}
# Autobook has no label that sets a floor (ADR-0003 section 3).
LABEL_FLOORS: dict[str, tuple[int, str]] = {}


def load_config(path: Path = HERE / "labels.json") -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def area_names(config: dict) -> list[str]:
    return [name.removeprefix("area:") for name in config["area"]]


def allowed_labels(config: dict) -> set[str]:
    """Every label the bot may add: the types plus the configured groups."""
    names = set(TYPES)
    for group in ("severity", "reach", "area", "priority", "other"):
        names |= set(config[group])
    return names


def verdict_schema(areas: list[str]) -> dict:
    """JSON schema for the model's verdict (structured output)."""
    # Without a description per field, low effort fills each reason with a single word.
    about = {
        "type": "why it is a bug, an enhancement, documentation or a spike",
        "severity": "what goes wrong for the user's book or data and why that is this severity",
        "reach": "who runs into it and why that is this reach",
        "area": "which part of Autobook it is in",
        "overrides": "which overrides apply and why, or that none apply",
    }
    reasons = {k: {"type": "string",
                   "description": f"One plain sentence of 8 to 30 words: {v}. Never quote the issue."}
               for k, v in about.items()}
    return {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": list(TYPES)},
            "severity": {"type": "string", "enum": list(SEVERITIES)},
            "reach": {"type": "string", "enum": list(REACHES)},
            # Structured output accepts minItems 0 or 1 only, not maxItems; validate()
            # keeps the first two.
            "areas": {"type": "array", "items": {"type": "string", "enum": areas},
                      "minItems": 1, "description": "One area, or two when it clearly spans both."},
            "flags": {
                "type": "object",
                "properties": {f: {"type": "boolean"} for f in FLAGS},
                "required": list(FLAGS),
                "additionalProperties": False,
            },
            "review_priority": {"type": "string", "enum": list(REVIEW_PRIORITIES)},
            "unsure": {"type": "boolean"},
            "missing": {"type": "string"},
            "financial_data": {"type": "boolean"},
            "secret_in_issue": {"type": "boolean"},
            "vulnerability_report": {"type": "boolean"},
            "reasons": {
                "type": "object",
                "properties": reasons,
                "required": list(reasons),
                "additionalProperties": False,
            },
        },
        "required": ["type", "severity", "reach", "areas", "flags", "review_priority", "unsure",
                     "missing", "financial_data", "secret_in_issue", "vulnerability_report",
                     "reasons"],
        "additionalProperties": False,
    }


class InvalidVerdict(ValueError):
    pass


def validate(verdict: dict, areas: list[str]) -> dict:
    """Check the verdict against the fixed label sets. Structured output should already
    guarantee this; it is checked again because nothing the model returns is trusted."""
    try:
        if verdict["type"] not in TYPES:
            raise InvalidVerdict(f"type {verdict['type']!r}")
        if verdict["severity"] not in SEVERITIES:
            raise InvalidVerdict(f"severity {verdict['severity']!r}")
        if verdict["reach"] not in REACHES:
            raise InvalidVerdict(f"reach {verdict['reach']!r}")
        if verdict["review_priority"] not in REVIEW_PRIORITIES:
            raise InvalidVerdict(f"review_priority {verdict['review_priority']!r}")
        chosen = [a for a in verdict["areas"] if a in areas]
        if len(chosen) != len(verdict["areas"]):
            raise InvalidVerdict(f"areas {verdict['areas']!r}")
        if not chosen:
            raise InvalidVerdict("no area")
        flags = {f: verdict["flags"][f] is True for f in FLAGS}
        # A vulnerability report is a security issue, so it gets the security floor even
        # when the model left that flag off (ADR-0003 section 5).
        if verdict["vulnerability_report"] is True:
            flags["security_or_privacy"] = True
        reasons = {k: str(verdict["reasons"][k]) for k in ("type", "severity", "reach", "area", "overrides")}
        return {
            "type": verdict["type"],
            "severity": verdict["severity"],
            "reach": verdict["reach"],
            "areas": list(dict.fromkeys(chosen))[:2],
            "flags": flags,
            "review_priority": verdict["review_priority"],
            "unsure": verdict["unsure"] is True,
            "missing": str(verdict["missing"]),
            "financial_data": verdict["financial_data"] is True,
            "secret_in_issue": verdict["secret_in_issue"] is True,
            "vulnerability_report": verdict["vulnerability_report"] is True,
            "reasons": reasons,
        }
    except (KeyError, TypeError) as e:
        raise InvalidVerdict(f"missing or malformed field: {e}") from e


def compute_priority(severity: str, reach: str, flags: dict[str, bool], review_priority: str,
                     existing_labels: set[str]) -> tuple[int, int, list[str]]:
    """ADR-0003 sections 2 and 3. Returns (priority, table_priority, notes).

    Order where the rules disagree: the table, then a deferred review finding keeps the
    review's priority, then the floors, so a floor can still raise a review's priority."""
    base = TABLE[severity][reach]
    prio, notes = base, []
    if review_priority != "none":
        kept = int(review_priority[1])
        if kept != prio:
            notes.append(f"kept the deferred review's P{kept}")
        prio = kept
    floors = [FLOORS[k] for k, on in flags.items() if on and k in FLOORS]
    floors += [LABEL_FLOORS[name] for name in sorted(existing_labels) if name in LABEL_FLOORS]
    for floor, label in sorted(set(floors)):
        if floor < prio:
            prio = floor
            notes.append(f"{label} (at least P{floor})")
    return prio, base, notes


# The line a maintainer writes when filing a deferred review finding, for example
# "Review priority: P1. Per ADR-0003 section 3 the issue keeps that priority".
_REVIEW_LINE = re.compile(r"^[ \t>*_]*review priority[*_]*:[*_ \t]*P([0-3])\b",
                          re.IGNORECASE | re.MULTILINE)


def stated_review_priority(issue: "Issue") -> str | None:
    """The review priority the issue states in a "Review priority: P1" line (P0 to P3), or None.
    Only a maintainer's statement counts (TRUSTED_AUTHORS): anyone can open an issue, and
    a stranger must not be able to set P0 by writing the line (ADR-0003 section 3)."""
    if issue.author_association not in TRUSTED_AUTHORS:
        return None
    found = {f"P{m}" for m in _REVIEW_LINE.findall(issue.body or "")}
    # Two different lines are a contradiction; leave it to the model and the table.
    return found.pop() if len(found) == 1 else None


def review_priority_for(issue: "Issue", verdict: dict) -> tuple[str, str | None]:
    """The review priority to keep, and a note on where it came from. The issue's own
    line wins over the model's reading; the model's is used only for a maintainer's issue,
    for the same reason the line is."""
    stated = stated_review_priority(issue)
    if stated:
        return stated, "the issue states it"
    if issue.author_association not in TRUSTED_AUTHORS:
        return "none", None
    return verdict["review_priority"], None


# --- never echo the issue back ------------------------------------------------------------

_WORD = re.compile(r"[\w'-]+", re.UNICODE)
SHINGLE = 5


def _words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


def _shingles(words: list[str], n: int = SHINGLE) -> set[tuple[str, ...]]:
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


IDENT_MIN = 8
_IDENT_MARK = re.compile(r"[\d./_:=@+]")
_EDGE = ".,;:!?()[]{}<>\"'`*"


def _identifiers(text: str) -> set[str]:
    """Single tokens that look like keys, hostnames, paths or IDs: IDENT_MIN characters or
    more with a digit, one of . / _ : = @ +, or two hyphens (a bucket or host name, or an
    account name like Ausgaben:Arzt). A word with one hyphen ("read-only") does not count."""
    tokens = (t.strip(_EDGE).lower() for t in text.split())
    return {t for t in tokens
            if len(t) >= IDENT_MIN and (_IDENT_MARK.search(t) or t.count("-") >= 2)}


_AMOUNT = re.compile(r"\d+[.,]\d{2}(?!\d)")


def _amounts(text: str) -> set[str]:
    """Money-like numbers with two decimals ("12,50", "9.99"), with the decimal mark
    normalised, so a short amount is caught even though it has no three-digit run."""
    return {a.replace(",", ".") for a in _AMOUNT.findall(text)}


def echoes(reason: str, issue_text: str) -> bool:
    """True when the reason repeats the issue: a run of SHINGLE words, a number of three
    or more digits (years, dates, IBAN groups, identifiers), an amount with two decimals,
    or one identifier-like token such as a key or IBAN, that also appears in the issue."""
    if _shingles(_words(reason)) & _shingles(_words(issue_text)):
        return True
    issue_numbers = set(re.findall(r"\d{3,}", issue_text))
    if any(n in issue_numbers for n in re.findall(r"\d{3,}", reason)):
        return True
    if _amounts(reason) & _amounts(issue_text):
        return True
    return bool(_identifiers(reason) & _identifiers(issue_text))


def scrub(reason: str, issue_text: str) -> str:
    """Make a model-written reason safe to post: no echo of the issue, no mentions, no
    Markdown or HTML that could change the comment, one line, bounded length."""
    if echoes(reason, issue_text):
        return "(reason withheld: it repeated text from the issue)"
    text = " ".join(reason.split())
    text = re.sub(r"[<>`|*_\[\]#]", "", text)
    text = text.replace("@", "@​")
    if len(text) > MAX_REASON:
        text = text[:MAX_REASON - 1].rstrip() + "…"
    # A word or two ("major", "bug") is a label name, not a reason.
    return text if len(text.split()) >= 3 else "(no reason given)"


# --- the plan: what to write to the issue -------------------------------------------------

@dataclass
class Issue:
    number: int
    title: str
    body: str
    labels: set[str]
    assignees: list[str]
    state: str = "open"
    is_pr: bool = False
    author_is_bot: bool = False
    triage_count: int = 0  # the workflow's own triage comments on the issue
    author_association: str = "NONE"  # OWNER, MEMBER, COLLABORATOR, CONTRIBUTOR, NONE ...
    updated_at: str = ""  # ISO 8601, as GitHub reports it


def text_hash(issue: Issue) -> str:
    """Fingerprint of the text the model reads, so the apply job can tell an edit made
    while the model ran."""
    return hashlib.sha256(f"{issue.title}\0{issue.body or ''}".encode("utf-8")).hexdigest()


def recently_updated(issue: Issue, now: datetime | None = None) -> bool:
    """True when the issue changed within BACKFILL_QUIET, or its time cannot be read."""
    try:
        updated = datetime.fromisoformat(issue.updated_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    return (now or datetime.now(timezone.utc)) - updated < BACKFILL_QUIET


@dataclass
class Plan:
    number: int = 0
    add_labels: list[str] = field(default_factory=list)
    remove_labels: list[str] = field(default_factory=list)
    assignee: str | None = None
    comment: str = ""
    # What the classify job saw: whether this run may retry the issue (an edit), and how
    # many triage comments the issue had. The apply job checks both against a fresh read.
    retry: bool = False
    triage_count: int = 0
    # The text that was classified (text_hash); the apply job drops the plan when the
    # issue's text changed since, and the run for that edit classifies the new text.
    text_hash: str = ""
    # A back-fill plan also records when the issue last changed, and is dropped when it
    # changed at all since: an issue event's run may be triaging it at the same time.
    backfill: bool = False
    updated_at: str = ""


def skip_reason(issue: Issue, retry: bool = False) -> str | None:
    """Why ``issue`` is not triaged, or None. ``retry`` is True only for an edit to the
    issue: the one event that may bring the information a needs-triage issue lacked."""
    if issue.is_pr:
        return "is a pull request"
    if issue.state != "open":
        return "is closed"
    if issue.author_is_bot:
        return "was opened by a bot"
    if any(label.startswith("priority:") for label in issue.labels):
        return "already has a priority"
    # One automated pass per issue. A back-fill or a reopen never triages an issue again,
    # so it cannot re-spend tokens or post the same comment twice; only an edit retries
    # one left at needs-triage, and at most MAX_RETRIES times.
    if issue.triage_count:
        if not retry or "needs-triage" not in issue.labels:
            return "was already triaged"
        if issue.triage_count > MAX_RETRIES:
            return "was retried too often"
    return None


def issue_input(issue: Issue) -> tuple[str, bool]:
    """The user message: the issue as delimited data, capped. Returns (text, truncated)."""
    title = issue.title[:MAX_TITLE]
    body = issue.body or ""
    truncated = len(body) > MAX_BODY
    body = body[:MAX_BODY]
    note = f"\n[The description was cut at {MAX_BODY} characters.]" if truncated else ""
    return f"<issue>\n<title>{title}</title>\n<body>\n{body}\n</body>\n</issue>{note}", truncated


def _row(label: str, why: str) -> str:
    return f"| `{label}` | {why} |"


def build_plan(issue: Issue, verdict: dict, config: dict, *, model: str, usage: str,
               truncated: bool) -> Plan:
    issue_text = f"{issue.title}\n{issue.body or ''}"
    withhold = (verdict["vulnerability_report"] or verdict["financial_data"]
                or verdict["secret_in_issue"])
    if withhold:
        # Labels yes, explanation no: a public comment must not restate the details. The
        # echo check misses a short payee, memo phrase or one-word password, so these are
        # held back whole (ADR-0003 section 5).
        reasons = {k: "Not restated here; see the note below." for k in verdict["reasons"]}
    else:
        reasons = {k: scrub(v, issue_text) for k, v in verdict["reasons"].items()}
    plan, rows = Plan(number=issue.number, text_hash=text_hash(issue),
                      updated_at=issue.updated_at), []

    have_type = [t for t in TYPES if t in issue.labels]
    kind = have_type[0] if have_type else verdict["type"]
    if have_type:
        # The label wins, but a disagreement is worth a line: templates set the type.
        why = "Kept the type the issue already had."
        if verdict["type"] != have_type[0]:
            why += f" It reads more like {verdict['type']}: {reasons['type']}"
        rows.append(_row(have_type[0], why))
    else:
        plan.add_labels.append(verdict["type"])
        rows.append(_row(verdict["type"], reasons["type"]))

    # Areas and the owner are set only with a placed priority. An unsure verdict waits at
    # needs-triage, and a retry after an edit may place the issue in other areas; areas set
    # on the first pass would stay next to the new ones, with the first pass's owner.
    placed = kind in PRIORITISED_TYPES and not verdict["unsure"]
    have_areas = sorted(l for l in issue.labels if l.startswith("area:"))
    if placed and have_areas:
        # Like the type: an area someone already set wins, so there are never more than two.
        rows.append(_row(", ".join(have_areas).replace(", ", "`, `"),
                         "Kept the area the issue already had."))
    elif placed:
        plan.add_labels += [f"area:{a}" for a in verdict["areas"]]
        rows.append(_row(", ".join(f"area:{a}" for a in verdict["areas"]).replace(", ", "`, `"),
                         reasons["area"]))

    if kind not in PRIORITISED_TYPES:
        rows.append(_row("no priority", f"ADR-0003 does not define a priority for {kind} "
                                        "issues; a maintainer sets it if needed."))
    elif verdict["unsure"]:
        plan.add_labels.append("needs-triage")
        missing = ("not restated" if withhold
                   else scrub(verdict["missing"], issue_text))
        rows.append(_row("needs-triage", f"Severity or reach could not be placed. Missing: {missing}"))
    else:
        review, source = review_priority_for(issue, verdict)
        prio, base, notes = compute_priority(verdict["severity"], verdict["reach"],
                                             verdict["flags"], review, issue.labels)
        if source:
            notes = [f"{n} ({source})" if n.startswith("kept the deferred review") else n
                     for n in notes]
        if "needs-triage" in issue.labels:
            plan.remove_labels.append("needs-triage")
        plan.add_labels += [f"sev:{verdict['severity']}", f"reach:{verdict['reach']}",
                            f"priority:P{prio}"]
        rows.append(_row(f"sev:{verdict['severity']}", reasons["severity"]))
        rows.append(_row(f"reach:{verdict['reach']}", reasons["reach"]))
        why = f"{verdict['severity']} × {verdict['reach']} is P{base} in the ADR-0003 table."
        if notes:
            why += " Then: " + "; ".join(notes) + f". {reasons['overrides']}"
        rows.append(_row(f"priority:P{prio}", why))

    if placed and not issue.assignees:
        owners = config.get("owners", {})
        area = have_areas[0] if have_areas else f"area:{verdict['areas'][0]}"
        plan.assignee = owners.get(area) or owners.get("*")

    lines = [
        MARKER,
        "**Automated triage** under ADR-0003. A maintainer makes the final call: change any "
        "label to correct it. The milestone is left to the maintainer.",
        "",
        "| Label | Why |",
        "|---|---|",
        *rows,
    ]
    if verdict["vulnerability_report"]:
        lines += ["", "This issue may describe a security or privacy vulnerability. Please "
                      "report vulnerabilities privately as SECURITY.md describes; a maintainer "
                      "may move this report to a private advisory."]
    if verdict["financial_data"]:
        lines += ["", "This issue seems to contain real financial data: statement lines, an "
                      "IBAN, a memo, amounts or a payee. Please replace it with a made-up example "
                      "that shows the same problem, and edit the original out; editing alone does "
                      "not remove it from the issue's history. The repository only holds "
                      "synthetic data."]
    if verdict["secret_in_issue"]:
        lines += ["", "This issue seems to contain a credential or other secret. Please rotate "
                      "it and edit it out of the issue; editing alone does not remove it from "
                      "the issue's history."]
    if truncated:
        lines += ["", TRUNCATED_NOTE]
    lines += ["", f"<sub>{model} · {usage}</sub>"]
    plan.comment = "\n".join(lines) + "\n"
    return plan


TRUNCATED_NOTE = f"Only the first {MAX_BODY:,} characters of the description were read."


def unclassified_plan(issue: Issue, why: str, *, model: str, usage: str,
                      truncated: bool = False) -> Plan:
    """When the model declined or ran out of room: flag for a human, guess nothing. A cut
    description is stated, since it may be why the model could not classify it."""
    lines = [
        MARKER,
        f"**Automated triage** could not classify this issue ({why}). A maintainer will "
        "triage it by hand under ADR-0003.",
    ]
    if truncated:
        lines += ["", TRUNCATED_NOTE]
    lines += ["", f"<sub>{model} · {usage}</sub>"]
    return Plan(number=issue.number, add_labels=["needs-triage"], comment="\n".join(lines) + "\n",
                text_hash=text_hash(issue), updated_at=issue.updated_at)


# --- a real IBAN is never sent to the model -----------------------------------------------

_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}\b", re.IGNORECASE | re.ASCII)


def _iban_valid(candidate: str) -> bool:
    """ISO 13616 mod-97 check. A made-up IBAN with a wrong check number fails it."""
    s = candidate.replace(" ", "")
    digits = "".join(str(int(c, 36)) for c in s[4:] + s[:4])
    return int(digits) % 97 == 1


def contains_real_iban(text: str) -> bool:
    """True when the text holds a checksum-valid IBAN: most likely a real account. Such
    an issue is not sent to the model at all (ADR-0003 section 5). The pattern is greedy,
    so an uppercase word after the IBAN can join the match; every IBAN length within the
    match is checked (15 to 34 characters). Case is ignored, for ASCII only: a pasted IBAN
    can be lowercase, and a Unicode letter that folds to A-Z (the Kelvin sign) must not
    reach the base-36 conversion."""
    for match in _IBAN.findall(text):
        s = match.replace(" ", "").upper()
        if any(_iban_valid(s[:n]) for n in range(15, min(len(s), 34) + 1)):
            return True
    return False


# Credentials by their published shapes. Each is specific enough that ordinary prose and
# code rarely match; a match costs a maintainer's manual triage, a miss leaks a secret.
_SECRETS = re.compile("|".join([
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",                     # PEM private key
    r"\bsk-ant-[A-Za-z0-9_-]{20,}",                            # Anthropic
    r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}",                      # OpenAI and similar
    r"\bgh[pousr]_[A-Za-z0-9]{36,}",                           # GitHub tokens
    r"\bgithub_pat_[A-Za-z0-9_]{40,}",                         # GitHub fine-grained token
    r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",                          # AWS access key ID
    r"\bAIza[0-9A-Za-z_-]{35}",                                # Google API key
    r"\bxox[abposr]-[A-Za-z0-9-]{10,}",                        # Slack
    r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}",  # JWT
    # A value assigned to a secret-named key: at least 8 characters with a letter and a
    # digit, so `token: <your token>`, `password = os.environ[...]` and prose do not count.
    r"\b(?i:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|auth)"
    r"[\"']?\s*[:=]\s*[\"']?(?=[^\s\"']*\d)(?=[^\s\"']*[A-Za-z])[A-Za-z0-9_\-+/=!#%^&*~]{8,}",
]), re.ASCII)

# A GnuCash account path under a standard top-level account, German or English
# ("Ausgaben:Arzt", "Expenses:Medical:Dentist"). An account name can be Art. 9 data on its
# own (AGENTS.md: "a name like Kirchensteuer"). Imbalance-EUR and Orphan-EUR have no path.
_ACCOUNT_PATH = re.compile(
    r"\b(?:Ausgaben|Einnahmen|Aufwand|Aufwendungen|Erträge|Ertraege|Aktiva|Passiva|"
    r"Verbindlichkeiten|Eigenkapital|Vermögen|Expenses|Expense|Income|Assets|Liabilities|"
    r"Equity):[^\s:,;()\[\]`'\"]{2,}")


def hold_back_reason(text: str) -> str | None:
    """Why the text must not reach the model, or None (#57, ADR-0003 section 5). The
    whole issue is checked, not just the part that would be sent. Payee names, memo
    phrases and amounts without one of these still go to the model; the model flags them
    and the comment asks for a made-up example."""
    if contains_real_iban(text):
        return "iban"
    if _SECRETS.search(text):
        return "secret"
    if _ACCOUNT_PATH.search(text):
        return "account"
    return None


_HELD_BACK = {
    "iban": ("it seems to contain a real IBAN",
             "Please replace the statement data with a made-up example that shows the same "
             "problem (an IBAN with a wrong check number is fine), and edit the original "
             "out; editing alone does not remove it from the issue's history."),
    "secret": ("it seems to contain a credential: a key, a token or a password",
               "Please rotate it, and edit it out of the issue; editing alone does not "
               "remove it from the issue's history. A placeholder such as `<token>` is fine."),
    "account": ("it names an account from a GnuCash chart of accounts, which can be "
                "personal data on its own",
                "If it is from a real book, please replace it with a made-up one, and edit "
                "the original out; editing alone does not remove it from the issue's "
                "history. If it is already made up, a maintainer will triage the issue by "
                "hand."),
}


def held_back_plan(issue: Issue, reason: str = "iban") -> Plan:
    """An issue the bot may not send to the model: say why in general terms (never the
    match itself), ask for it to be replaced, classify nothing."""
    found, ask = _HELD_BACK[reason]
    return Plan(number=issue.number, add_labels=["needs-triage"], comment="\n".join([
        MARKER,
        f"**Automated triage** did not read this issue: {found}, so it was not sent to "
        f"the model. {ask} The issue is triaged again after the edit.",
    ]) + "\n", text_hash=text_hash(issue), updated_at=issue.updated_at)


# --- the plan handed from the classify job to the apply job -------------------------------

class InvalidPlan(ValueError):
    pass


def check_plan(entry: dict, config: dict) -> Plan:
    """The apply job's own check of one plan entry. The plan comes from another job, so it
    is data: every label must be one the bot may add, with at most one of each kind, and
    the comment must be the bot's own."""
    try:
        number = entry["number"]
        labels = entry["add_labels"]
        assignee = entry["assignee"]
        remove = entry["remove_labels"]
        comment = entry["comment"]
        retry = entry["retry"]
        triage_count = entry["triage_count"]
        digest = entry["text_hash"]
        backfill = entry["backfill"]
        updated_at = entry["updated_at"]
    except (KeyError, TypeError) as e:
        raise InvalidPlan(f"missing field: {e}") from e
    if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
        raise InvalidPlan(f"issue number {number!r}")
    if not isinstance(labels, list) or not all(isinstance(l, str) for l in labels):
        raise InvalidPlan("labels are not a list of strings")
    unknown = set(labels) - allowed_labels(config)
    if unknown:
        raise InvalidPlan(f"labels outside the scheme: {sorted(unknown)}")
    for prefix in ("sev:", "reach:", "priority:"):
        if sum(l.startswith(prefix) for l in labels) > 1:
            raise InvalidPlan(f"more than one {prefix} label")
    if sum(l in TYPES for l in labels) > 1:
        raise InvalidPlan("more than one type label")
    if sum(l.startswith("area:") for l in labels) > 2:
        raise InvalidPlan("more than two area labels")
    if not isinstance(remove, list) or not set(remove) <= {"needs-triage"}:
        raise InvalidPlan(f"may only remove needs-triage, not {remove!r}")
    if assignee is not None and assignee not in set(config.get("owners", {}).values()):
        raise InvalidPlan(f"assignee {assignee!r} is not in the owner table")
    if not isinstance(comment, str) or not comment.startswith(MARKER) or len(comment) > MAX_COMMENT:
        raise InvalidPlan("comment is not the bot's own")
    if not isinstance(retry, bool):
        raise InvalidPlan(f"retry {retry!r}")
    if not isinstance(triage_count, int) or isinstance(triage_count, bool) or triage_count < 0:
        raise InvalidPlan(f"triage count {triage_count!r}")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise InvalidPlan(f"text hash {digest!r}")
    if not isinstance(backfill, bool):
        raise InvalidPlan(f"backfill {backfill!r}")
    if not isinstance(updated_at, str) or len(updated_at) > 40:
        raise InvalidPlan(f"updated_at {updated_at!r}")
    return Plan(number=number, add_labels=list(labels), remove_labels=list(remove),
                assignee=assignee, comment=comment, retry=retry, triage_count=triage_count,
                text_hash=digest, backfill=backfill, updated_at=updated_at)


def write_plans(path: Path, plans: list[Plan]) -> None:
    path.write_text(json.dumps([asdict(p) for p in plans], indent=2) + "\n", encoding="utf-8")


def read_plans(path: Path, config: dict) -> list[Plan]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise InvalidPlan("the plan file is not a list")
    return [check_plan(entry, config) for entry in data]


# --- Claude -------------------------------------------------------------------------------

@dataclass
class Result:
    verdict: dict | None
    failure: str | None
    model: str
    usage: str


def github_identity_token() -> str:
    """A fresh GitHub OIDC token for the Claude API. GitHub's token expires after about
    five minutes and can be exchanged once, so the SDK asks for a new one at every
    exchange instead of reading one file fetched at the start of the job (#61)."""
    url = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"]
    sep = "&" if urllib.parse.urlsplit(url).query else "?"
    request = urllib.request.Request(
        f"{url}{sep}audience={urllib.parse.quote(OIDC_AUDIENCE, safe='')}",
        headers={"Authorization": f"Bearer {os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN']}"})
    with urllib.request.urlopen(request, timeout=30) as response:
        value = json.load(response).get("value")
    if not isinstance(value, str) or not value:
        raise RuntimeError("GitHub returned no identity token")
    return value


def claude_client(**options):
    """The Claude API client. In a workflow job with `id-token: write` it signs in by
    Workload Identity Federation with a token provider that fetches GitHub's identity token
    anew for each exchange; elsewhere the SDK reads its usual environment."""
    import anthropic

    if not os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL"):
        return anthropic.Anthropic(**options)
    from anthropic.lib.credentials import WorkloadIdentityCredentials

    credentials = WorkloadIdentityCredentials(
        identity_token_provider=github_identity_token,
        federation_rule_id=os.environ["ANTHROPIC_FEDERATION_RULE_ID"],
        organization_id=os.environ["ANTHROPIC_ORGANIZATION_ID"],
        service_account_id=os.environ.get("ANTHROPIC_SERVICE_ACCOUNT_ID") or None,
        # An empty variable would be sent as an empty ID; leave it out instead.
        workspace_id=os.environ.get("ANTHROPIC_WORKSPACE_ID") or None,
    )
    return anthropic.Anthropic(credentials=credentials, **options)


def usage_line(u) -> str:
    """Tokens billed for the request. After a server-side fallback the top-level usage
    covers only the attempt that answered; every attempt, the declined one included, is
    in `usage.iterations`, so those are summed when present (#62)."""
    parts = getattr(u, "iterations", None) or [u]
    def total(name: str) -> int:
        return sum(getattr(p, name, 0) or 0 for p in parts)
    cached, created = total("cache_read_input_tokens"), total("cache_creation_input_tokens")
    line = (f"{total('input_tokens') + cached + created:,} tokens in ({cached:,} cached), "
            f"{total('output_tokens'):,} out")
    if len(parts) > 1:
        line += f" over {len(parts)} attempts"
    return line


def classify_issue(client, prompt: str, issue: Issue, areas: list[str]) -> tuple[Result, bool]:
    # The caller holds such an issue back; refuse here too, so no path sends one.
    if (why := hold_back_reason(f"{issue.title}\n{issue.body or ''}")):
        raise ValueError(f"#{issue.number} must not reach the model ({why})")
    text, truncated = issue_input(issue)
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        # Server-side fallback: a cyber-category decline (security reports can trigger
        # one) is retried on Anthropic's recommended model instead of failing.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": EFFORT,
                       "format": {"type": "json_schema", "schema": verdict_schema(areas)}},
        # The rules are identical on every call; caching pays off during a back-fill run.
        system=[{"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": text}],
    )
    usage = usage_line(response.usage)
    model = response.model
    if response.stop_reason == "refusal":
        return Result(None, "the model declined to classify it", model, usage), truncated
    if response.stop_reason == "max_tokens":
        return Result(None, "the model ran out of output room", model, usage), truncated
    raw = next((b.text for b in response.content if b.type == "text"), "")
    try:
        verdict = validate(json.loads(raw), areas)
    except (json.JSONDecodeError, InvalidVerdict) as e:
        print(f"#{issue.number}: invalid verdict: {e}", file=sys.stderr)
        return Result(None, "the model's answer did not validate", model, usage), truncated
    return Result(verdict, None, model, usage), truncated


# --- GitHub (via gh) ----------------------------------------------------------------------

def gh(*args: str, input: str | None = None) -> str:
    try:
        return subprocess.run(["gh", *args], input=input, capture_output=True, text=True,
                              check=True).stdout
    except subprocess.CalledProcessError as e:
        # The traceback alone shows only the command; GitHub's reason is on stderr.
        print(f"gh {args[0]} {args[1] if len(args) > 1 else ''} failed: {e.stderr.strip()}",
              file=sys.stderr)
        raise


def triage_comments(comments: list[dict]) -> int:
    """How many of ``comments`` are the workflow's own triage comments."""
    return sum(1 for c in comments
               if MARKER in (c.get("body") or "") and (c.get("user") or {}).get("login") == BOT_LOGIN)


def fetch_issue(repo: str, number: int) -> Issue:
    data = json.loads(gh("api", f"repos/{repo}/issues/{number}"))
    comments = json.loads(gh("api", "--paginate", "--slurp", f"repos/{repo}/issues/{number}/comments"))
    flat = [c for page in comments for c in page]
    return Issue(
        number=number,
        title=data.get("title") or "",
        body=data.get("body") or "",
        labels={label["name"] for label in data.get("labels", [])},
        assignees=[a["login"] for a in data.get("assignees", [])],
        state=data.get("state", "open"),
        is_pr="pull_request" in data,
        author_is_bot=(data.get("user") or {}).get("type") == "Bot",
        triage_count=triage_comments(flat),
        author_association=data.get("author_association") or "NONE",
        updated_at=data.get("updated_at") or "",
    )


# One page of open issues, oldest first, with what skip_reason needs: labels, author and
# comments (#69). One request covers BACKFILL_PAGE issues instead of two REST calls each.
_BACKFILL_QUERY = """
query($owner: String!, $name: String!, $first: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    issues(first: $first, after: $cursor, states: OPEN,
           orderBy: {field: CREATED_AT, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number
        updatedAt
        author { __typename login }
        labels(first: 100) { nodes { name } }
        comments(first: 100) { totalCount nodes { author { __typename login } body } }
      }
    }
  }
}
"""


def _backfill_issue(node: dict) -> Issue | None:
    """An Issue from one GraphQL node, or None when its comments did not fit the page and
    the caller must read it through REST."""
    comments = node.get("comments") or {}
    if (comments.get("totalCount") or 0) > len(comments.get("nodes") or []):
        return None
    author = node.get("author") or {}
    return Issue(
        number=node["number"], title="", body="",
        labels={l["name"] for l in (node.get("labels") or {}).get("nodes") or []},
        assignees=[],
        author_is_bot=author.get("__typename") == "Bot",
        triage_count=sum(1 for c in comments.get("nodes") or []
                         if MARKER in (c.get("body") or "")
                         and (c.get("author") or {}).get("__typename") == "Bot"
                         and (c.get("author") or {}).get("login") == GRAPHQL_BOT_LOGIN),
        updated_at=node.get("updatedAt") or "",
    )


def open_untriaged(repo: str, limit: int) -> list[int]:
    """Up to ``limit`` open issues a back-fill should triage, oldest first. The limit is
    applied after skipping, so issues that stay without a priority after their one
    automated pass (needs-triage, or a type with no priority) never fill a batch. An
    issue that changed within BACKFILL_QUIET is left to its own event run (#70)."""
    owner, name = repo.split("/", 1)
    numbers, cursor, scanned = [], None, 0
    while len(numbers) < limit and scanned < MAX_SCAN:
        args = ["api", "graphql", "-f", f"query={_BACKFILL_QUERY}", "-f", f"owner={owner}",
                "-f", f"name={name}", "-F", f"first={min(BACKFILL_PAGE, MAX_SCAN - scanned)}"]
        if cursor:
            args += ["-f", f"cursor={cursor}"]
        page = json.loads(gh(*args))["data"]["repository"]["issues"]
        for node in page["nodes"]:
            scanned += 1
            if len(numbers) >= limit:
                break
            if any(l["name"].startswith("priority:")
                   for l in (node.get("labels") or {}).get("nodes") or []):
                continue
            candidate = _backfill_issue(node) or fetch_issue(repo, node["number"])
            if skip_reason(candidate) is None and not recently_updated(candidate):
                numbers.append(candidate.number)
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    return numbers


def ensure_labels(repo: str, config: dict) -> None:
    existing = {l["name"] for l in json.loads(gh("label", "list", "-R", repo, "--limit", "500",
                                                 "--json", "name"))}
    for group in ("severity", "reach", "area", "priority", "other"):
        for name, spec in config[group].items():
            if name in existing:
                continue
            try:
                gh("label", "create", name, "-R", repo, "--color", spec["color"],
                   "--description", spec["description"])
            except subprocess.CalledProcessError as e:
                # Another run created it since the list was read (#66): that is the goal.
                if "already exists" not in (e.stderr or ""):
                    raise
                print(f"label {name} was created by another run")
                continue
            print(f"created label {name}")


def _apply_skip(plan: Plan, fresh: Issue) -> str | None:
    """Why the apply job must not write ``plan`` to the issue as it is now, or None."""
    if fresh.triage_count != plan.triage_count:
        # A back-fill and an issue event can overlap; the other run applied first.
        return "triaged by another run since this plan was made"
    if text_hash(fresh) != plan.text_hash:
        # The author edited while the model ran (#58). The run that edit queued
        # classifies the new text; this plan is for the old one.
        return "the issue text changed after it was classified"
    if plan.backfill and fresh.updated_at != plan.updated_at:
        # An issue event may be triaging it now (#70); a back-fill gives way, and the
        # next back-fill picks the issue up if nobody else does.
        return "the issue changed since the back-fill read it"
    return skip_reason(fresh, retry=plan.retry)


def apply_plan(repo: str, plan: Plan) -> bool:
    """Write the plan to the issue. Returns False when it was skipped. The labels and
    the comment go on together: when a write fails, the labels this run set are taken
    off again, so a rerun triages the issue instead of skipping it for a priority that has
    no comment explaining it (#59)."""
    # Re-read the issue: a human may have set a priority or an assignee since the classify
    # job read it, the text may have changed, or another run may have triaged it.
    fresh = fetch_issue(repo, plan.number)
    if (why := _apply_skip(plan, fresh)):
        print(f"#{plan.number}: skipped at apply time ({why})")
        return False
    number = str(plan.number)
    added = [l for l in plan.add_labels if l not in fresh.labels]
    removed = [l for l in plan.remove_labels if l in fresh.labels]
    done_add = done_remove = False
    try:
        if added:
            gh("issue", "edit", number, "-R", repo, "--add-label", ",".join(added))
            done_add = True
        if removed:
            gh("issue", "edit", number, "-R", repo, "--remove-label", ",".join(removed))
            done_remove = True
        gh("issue", "comment", number, "-R", repo, "--body-file", "-", input=plan.comment)
    except subprocess.CalledProcessError:
        _undo_labels(repo, number, added if done_add else [], removed if done_remove else [])
        raise
    # Last, and only when nobody is assigned now: a maintainer may have assigned someone
    # while the model ran (#67, ADR-0003 section 4). A failure here loses nothing else.
    if plan.assignee and not fresh.assignees:
        try:
            gh("issue", "edit", number, "-R", repo, "--add-assignee", plan.assignee)
        except subprocess.CalledProcessError as e:
            print(f"#{plan.number}: could not assign {plan.assignee}: {e.stderr.strip()}",
                  file=sys.stderr)
    return True


def _undo_labels(repo: str, number: str, added: list[str], removed: list[str]) -> None:
    try:
        if added:
            gh("issue", "edit", number, "-R", repo, "--remove-label", ",".join(added))
        if removed:
            gh("issue", "edit", number, "-R", repo, "--add-label", ",".join(removed))
    except subprocess.CalledProcessError:
        print(f"::error::#{number}: the triage comment failed and the labels it explains "
              f"could not be taken off again ({', '.join(added)}); remove them by hand so "
              "the issue is triaged again", file=sys.stderr)


# --- commands -----------------------------------------------------------------------------

def load_prompt(path: Path = HERE / "prompt.md") -> str:
    """The prompt with its maintainer notes removed; refuse one still holding template text."""
    text = path.read_text(encoding="utf-8")
    if any(marker in text for marker in TEMPLATE_MARKERS):
        raise SystemExit("prompt.md still has template text (PROJECT SUMMARY or EXAMPLE); "
                         "fill it in before running triage")
    return re.sub(r"<!--.*?-->\n?", "", text, flags=re.S)


def _stamp(plan: Plan, issue: Issue, args) -> Plan:
    """Record on the plan how this run was started; the builders record the text and time."""
    plan.retry, plan.triage_count, plan.backfill = args.retry, issue.triage_count, args.all
    return plan


def run_classify(args) -> int:
    import anthropic  # here, so the apply job and the tests need no SDK installed

    config = load_config()
    if any("EXAMPLE" in spec["description"] for spec in config["area"].values()):
        raise SystemExit("labels.json still has the template's example area; replace it first")
    areas = area_names(config)
    prompt = load_prompt()
    client = claude_client(max_retries=3, timeout=120)

    numbers = open_untriaged(args.repo, args.limit) if args.all else [args.issue]
    if not numbers:
        print("no open issues without a priority")
    plans, failed = [], 0
    try:
        for number in numbers:
            issue = fetch_issue(args.repo, number)
            if (why := skip_reason(issue, retry=args.retry)):
                print(f"#{number}: skipped ({why})")
                continue
            if args.all and recently_updated(issue):
                # It changed after the scan; its own event run may be triaging it (#70).
                print(f"#{number}: skipped (changed in the last few minutes)")
                continue
            if (held := hold_back_reason(f"{issue.title}\n{issue.body or ''}")):
                plan = _stamp(held_back_plan(issue, held), issue, args)
                print(f"#{number}: not sent to the model ({held}); {', '.join(plan.add_labels)}")
                if args.dry_run:
                    print(plan.comment)
                plans.append(plan)
                continue
            try:
                result, truncated = classify_issue(client, prompt, issue, areas)
            except anthropic.RateLimitError as e:
                print(f"#{number}: rate limited, stopping: {e.message}", file=sys.stderr)
                failed += 1
                break
            except anthropic.APIStatusError as e:
                print(f"#{number}: API error {e.status_code}: {e.message}", file=sys.stderr)
                failed += 1
                continue
            except anthropic.APIConnectionError as e:
                print(f"#{number}: connection error: {e}", file=sys.stderr)
                failed += 1
                continue
            if result.verdict is None:
                plan = unclassified_plan(issue, result.failure, model=result.model,
                                         usage=result.usage, truncated=truncated)
            else:
                plan = build_plan(issue, result.verdict, config, model=result.model,
                                  usage=result.usage, truncated=truncated)
            _stamp(plan, issue, args)
            print(f"#{number}: {', '.join(plan.add_labels)}; assignee {plan.assignee}; {result.usage}")
            if args.dry_run:
                print(plan.comment)
            plans.append(plan)
    finally:
        # Whatever was classified is handed on, even when a later issue failed or could
        # not be read from GitHub.
        if args.out and not args.dry_run:
            write_plans(Path(args.out), plans)
    return 1 if failed else 0


def run_apply(args) -> int:
    config = load_config()
    plans = read_plans(Path(args.plan), config)
    if not plans:
        print("nothing to apply")
        return 0
    ensure_labels(args.repo, config)
    failed = 0
    for plan in plans:
        # One issue that cannot be written does not stop the others.
        try:
            if apply_plan(args.repo, plan):
                print(f"#{plan.number}: applied {', '.join(plan.add_labels)}")
        except subprocess.CalledProcessError:
            print(f"#{plan.number}: not applied", file=sys.stderr)
            failed += 1
    return 1 if failed else 0


def positive_int(text: str) -> int:
    """argparse type for --limit: a back-fill of zero or fewer issues is a mistake, and a
    negative one used to mean no cap at all (#68)."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be 1 or more, not {value}")
    return value


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    sub = ap.add_subparsers(dest="command", required=True)
    c = sub.add_parser("classify", help="ask the model; write the plan, never GitHub")
    target = c.add_mutually_exclusive_group(required=True)
    target.add_argument("--issue", type=int)
    target.add_argument("--all", action="store_true", help="open issues without a priority")
    c.add_argument("--limit", type=positive_int, default=20, help="cap for --all (1 or more)")
    c.add_argument("--dry-run", action="store_true", help="print the plan, write no file")
    c.add_argument("--out", help="where to write the plan (JSON)")
    c.add_argument("--retry", action="store_true",
                   help="the issue was edited: retry it if it is at needs-triage")
    a = sub.add_parser("apply", help="check the plan and write it to GitHub; no model")
    a.add_argument("--plan", required=True)
    args = ap.parse_args(argv)
    if not args.repo:
        ap.error("--repo or $GITHUB_REPOSITORY is required")
    return run_classify(args) if args.command == "classify" else run_apply(args)


if __name__ == "__main__":
    sys.exit(main())

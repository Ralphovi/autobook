"""Tests for triage_priority.py: everything after the model call, offline.

Run: python -I -m unittest discover -s .github/triage

All financial data below is made up: the IBANs have an invalid check number and the
payees and memos are invented, as the repository's fixtures must be (AGENTS.md).
"""

from __future__ import annotations

import ast
import io
import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import triage_priority as tp  # noqa: E402

CONFIG = tp.load_config()
AREAS = tp.area_names(CONFIG)
NO_FLAGS = {f: False for f in tp.FLAGS}


def verdict(**over) -> dict:
    v = {
        "type": "bug", "severity": "critical", "reach": "edge", "areas": ["correlator"],
        "flags": dict(NO_FLAGS), "review_priority": "none", "unsure": False, "missing": "",
        "financial_data": False, "secret_in_issue": False, "vulnerability_report": False,
        "reasons": {"type": "Autobook books a transfer the wrong way.",
                    "severity": "A transfer is booked from both statements, so it is booked twice.",
                    "reach": "It needs both accounts imported in the same batch.",
                    "area": "The correlator's transfer matching.",
                    "overrides": "None apply."},
    }
    v.update(over)
    return v


def issue(**over) -> tp.Issue:
    i = tp.Issue(number=7, title="Transfer between two own accounts is booked twice",
                 body="Steps: import both statements in one batch.", labels=set(), assignees=[],
                 author_association="MEMBER")
    for k, val in over.items():
        setattr(i, k, val)
    return i


def plan(i: tp.Issue | None = None, **v) -> tp.Plan:
    return tp.build_plan(i or issue(), tp.validate(verdict(**v), AREAS), CONFIG,
                         model=tp.MODEL, usage="1 in, 1 out", truncated=False)


def prio(severity, reach, flags=None, review="none", labels=()):
    return tp.compute_priority(severity, reach, flags or NO_FLAGS, review, set(labels))


def gh_stub(calls: list, fail=None, assignees=()):
    """A fake `gh`: records each call, fails the ones ``fail`` picks, and answers the
    read apply makes just before assigning."""
    def fake(*a, **k):
        calls.append(a)
        if fail and fail(a):
            raise subprocess.CalledProcessError(1, ["gh"], stderr="HTTP 502")
        if a[:1] == ("api",):
            return json.dumps({"assignees": [{"login": x} for x in assignees]})
        return ""
    return fake


def writes(calls: list) -> list:
    """The calls that change the issue."""
    return [a for a in calls if a[:1] != ("api",)]


class Table(unittest.TestCase):
    def test_matches_adr_0003(self) -> None:
        expected = {
            ("critical", "common"): 0, ("critical", "edge"): 1, ("critical", "adversarial"): 1,
            ("major", "common"): 1, ("major", "edge"): 2, ("major", "adversarial"): 2,
            ("minor", "common"): 2, ("minor", "edge"): 3, ("minor", "adversarial"): 3,
            ("trivial", "common"): 3, ("trivial", "edge"): 3, ("trivial", "adversarial"): 3,
        }
        for (sev, reach), p in expected.items():
            with self.subTest(sev=sev, reach=reach):
                self.assertEqual(prio(sev, reach)[0], p)

    def test_privacy_lifts_adversarial_major_to_p1(self) -> None:
        p, base, notes = prio("major", "adversarial", dict(NO_FLAGS, security_or_privacy=True))
        self.assertEqual((p, base), (1, 2))
        self.assertIn("security or privacy", notes[0])

    def test_booking_integrity_lifts_edge_minor_to_p1(self) -> None:
        p, _, notes = prio("minor", "edge", dict(NO_FLAGS, booking_integrity=True))
        self.assertEqual(p, 1)
        self.assertIn("booking-integrity", notes[0])

    def test_floor_never_lowers(self) -> None:
        p, _, notes = prio("critical", "common", dict(NO_FLAGS, booking_integrity=True))
        self.assertEqual((p, notes), (0, []))

    def test_unrelated_labels_are_not_floors(self) -> None:
        # Autobook has no label floors; another repository's floor labels do nothing here.
        for label in ("release-gating", "accessibility", "human-run", "build-order",
                      "booking_integrity", "security_or_privacy"):
            with self.subTest(label=label):
                self.assertEqual(prio("trivial", "common", labels={label})[0], 3)

    def test_review_priority_is_kept(self) -> None:
        # A minor/edge deferred review finding: P3 by the table, P2 from the review.
        p, base, notes = prio("minor", "edge", review="P2")
        self.assertEqual((p, base), (2, 3))
        self.assertIn("deferred review", notes[0])

    def test_review_priority_can_lower_the_table(self) -> None:
        self.assertEqual(prio("major", "common", review="P2")[0], 2)

    def test_floors_apply_after_the_review_priority(self) -> None:
        p, _, notes = prio("major", "adversarial", dict(NO_FLAGS, security_or_privacy=True),
                           review="P2")
        self.assertEqual(p, 1)
        self.assertEqual(len(notes), 1)  # the review agrees with the table; only the floor

    def test_a_floor_raises_a_lower_review_priority(self) -> None:
        p, _, notes = prio("minor", "edge", dict(NO_FLAGS, booking_integrity=True), review="P3")
        self.assertEqual(p, 1)
        self.assertIn("booking-integrity", notes[-1])

    def test_every_flag_has_a_floor(self) -> None:
        self.assertLessEqual(set(tp.FLAGS), set(tp.FLOORS))

    def test_every_type_gets_a_priority(self) -> None:
        # ADR-0003 section 4 places every issue, not only bugs.
        self.assertEqual(set(tp.PRIORITISED_TYPES), set(tp.TYPES))


class Validate(unittest.TestCase):
    def test_rejects_unknown_values(self) -> None:
        for bad in ({"severity": "blocker"}, {"reach": "rare"}, {"type": "research"},
                    {"type": "chore"}, {"areas": ["kernel"]}, {"review_priority": "P4"}):
            with self.subTest(bad=bad), self.assertRaises(tp.InvalidVerdict):
                tp.validate(verdict(**bad), AREAS)

    def test_rejects_missing_fields(self) -> None:
        for field in ("flags", "review_priority", "financial_data", "secret_in_issue",
                      "vulnerability_report"):
            v = verdict()
            del v[field]
            with self.subTest(field=field), self.assertRaises(tp.InvalidVerdict):
                tp.validate(v, AREAS)

    def test_more_than_two_areas_is_rejected(self) -> None:
        # #60: a third area did not follow the rules; it is not cut silently.
        with self.assertRaises(tp.InvalidVerdict):
            tp.validate(verdict(areas=["correlator", "book", "review"]), AREAS)
        with self.assertRaises(tp.InvalidVerdict):
            tp.validate(verdict(areas=["book", "book", "review"]), AREAS)  # Codex review
        self.assertEqual(tp.validate(verdict(areas=["book", "book"]), AREAS)["areas"], ["book"])

    def test_no_area_is_rejected(self) -> None:
        # #60: an answer with no area leaves the issue without an area label or owner.
        with self.assertRaises(tp.InvalidVerdict):
            tp.validate(verdict(areas=[]), AREAS)

    def test_schema_requires_an_area(self) -> None:
        areas = tp.verdict_schema(AREAS)["properties"]["areas"]
        self.assertEqual(areas["minItems"], 1)
        # Structured output rejects maxItems; validate() keeps the first two instead.
        self.assertNotIn("maxItems", areas)

    def test_vulnerability_report_sets_the_security_flag(self) -> None:
        got = tp.validate(verdict(vulnerability_report=True), AREAS)
        self.assertTrue(got["flags"]["security_or_privacy"])

    def test_schema_enums_match_config(self) -> None:
        schema = tp.verdict_schema(AREAS)
        self.assertEqual(schema["properties"]["areas"]["items"]["enum"], AREAS)
        self.assertEqual(set(schema["required"]), set(schema["properties"]))
        self.assertEqual(set(schema["properties"]["flags"]["properties"]), set(tp.FLAGS))

    def test_types_exist_as_repository_labels(self) -> None:
        # Autobook has `spike`, not `research`; the bot must only add labels that exist.
        self.assertIn("spike", tp.TYPES)
        self.assertNotIn("research", tp.TYPES)


class Echo(unittest.TestCase):
    BODY = ("Statement line: 2026-03-02 LASTSCHRIFT Praxis Dr. Exempel 12,50 EUR "
            "from DE00 1234 5678 9012 3456 78, booked to Ausgaben:Arzt-Rechnungen-Privat. "
            "Compact form DE00123456789012345678, paperless token 0a1b2c3d4e5f.")

    def test_withholds_a_reason_that_quotes_the_issue(self) -> None:
        r = tp.scrub("The memo LASTSCHRIFT Praxis Dr. Exempel 12,50 is misread.", self.BODY)
        self.assertIn("withheld", r)

    def test_withholds_an_iban(self) -> None:
        for reason in ("The account DE00123456789012345678 is matched wrongly.",
                       "The IBAN group 5678 is read as an amount."):
            with self.subTest(reason=reason):
                self.assertIn("withheld", tp.scrub(reason, self.BODY))

    def test_withholds_an_amount(self) -> None:
        for reason in ("A debit of 12,50 is booked twice.", "A debit of 12.50 is booked twice."):
            with self.subTest(reason=reason):
                self.assertIn("withheld", tp.scrub(reason, self.BODY))

    def test_withholds_a_single_token_secret_or_account_name(self) -> None:
        for reason in ("The token 0a1b2c3d4e5f is rejected by paperless.",
                       "It is booked to Ausgaben:Arzt-Rechnungen-Privat instead."):
            with self.subTest(reason=reason):
                self.assertIn("withheld", tp.scrub(reason, self.BODY))

    def test_hyphenated_words_are_not_identifiers(self) -> None:
        body = "A read-only export shows a half-booked transfer."
        r = "The read-only export lists one transfer as half-booked."
        self.assertEqual(tp.scrub(r, body), r)

    def test_keeps_a_general_reason(self) -> None:
        r = "A direct debit to a medical provider is booked to the wrong expense account."
        self.assertEqual(tp.scrub(r, self.BODY), r)

    def test_neutralises_mentions_and_markup(self) -> None:
        r = tp.scrub("ping @eduralph <img src=x> | `code` **bold**", "")
        self.assertNotIn("@e", r)
        for ch in "<>|`*":
            self.assertNotIn(ch, r)

    def test_one_word_is_not_a_reason(self) -> None:
        for bare in ("major", "bug", "", "area book"):
            with self.subTest(bare=bare):
                self.assertEqual(tp.scrub(bare, ""), "(no reason given)")

    def test_schema_describes_each_reason(self) -> None:
        props = tp.verdict_schema(AREAS)["properties"]["reasons"]["properties"]
        for key, spec in props.items():
            with self.subTest(reason=key):
                self.assertIn("sentence", spec["description"])

    def test_caps_length(self) -> None:
        self.assertLessEqual(len(tp.scrub("word " * 100, "")), tp.MAX_REASON)


class Notes(unittest.TestCase):
    def test_financial_data_asks_for_a_synthetic_example(self) -> None:
        c = plan(financial_data=True).comment
        self.assertIn("made-up example", c)
        self.assertIn("history", c)

    def test_vulnerability_report_is_labelled_but_not_restated(self) -> None:
        p = plan(severity="critical", reach="adversarial", vulnerability_report=True,
                 flags=dict(NO_FLAGS, security_or_privacy=True))
        self.assertIn("priority:P1", p.add_labels)
        self.assertIn("SECURITY.md", p.comment)
        for reason in verdict()["reasons"].values():
            self.assertNotIn(reason, p.comment)

    def test_vulnerability_report_hides_what_is_missing(self) -> None:
        p = plan(vulnerability_report=True, unsure=True, missing="Which memo field leaks.")
        self.assertNotIn("memo field", p.comment)

    def test_financial_data_hides_what_is_missing(self) -> None:
        p = plan(financial_data=True, unsure=True, missing="Whether Praxis Imaginary is a payee.")
        self.assertNotIn("Imaginary", p.comment)

    def test_secret_note_asks_to_rotate(self) -> None:
        self.assertIn("rotate", plan(secret_in_issue=True).comment)

    def test_no_notes_on_an_ordinary_issue(self) -> None:
        c = plan().comment
        for note in ("SECURITY.md", "rotate", "made-up example"):
            self.assertNotIn(note, c)


class RealIban(unittest.TestCase):
    # ISO 13616's published example IBAN: checksum-valid, owned by no customer.
    EXAMPLE = "GB82 WEST 1234 5698 7654 32"

    def test_checksum_valid_iban_is_held_back(self) -> None:
        for text in (f"Booked from {self.EXAMPLE} twice.",
                     f"Booked from {self.EXAMPLE.replace(' ', '')} twice.",
                     f"Booked from {self.EXAMPLE} TWICE."):
            with self.subTest(text=text):
                self.assertTrue(tp.contains_real_iban(text))

    def test_lowercase_iban_is_held_back(self) -> None:
        for text in (f"Booked from {self.EXAMPLE.lower()} twice.",
                     f"Booked from {self.EXAMPLE.replace(' ', '').lower()} twice.",
                     "Booked from gb82West12345698765432 twice."):
            with self.subTest(text=text):
                self.assertTrue(tp.contains_real_iban(text))

    def test_unicode_letters_do_not_break_the_check(self) -> None:
        # U+212A KELVIN SIGN and U+0130 fold to K and i under Unicode case-insensitivity.
        for text in ("KB121234567890123", "İB121234567890123 and more"):
            with self.subTest(text=text):
                self.assertFalse(tp.contains_real_iban(text))

    def test_made_up_iban_is_classified(self) -> None:
        self.assertFalse(tp.contains_real_iban("From DE00 1234 5678 9012 3456 78, booked twice."))

    def test_ordinary_text_is_not_an_iban(self) -> None:
        for text in ("PR 12 fixes it", "SHA256 ABCDEF0123456789", "Ausgaben:Lebensmittel 2026"):
            with self.subTest(text=text):
                self.assertFalse(tp.contains_real_iban(text))

    def test_held_back_plan_asks_for_synthetic_data_and_classifies_nothing(self) -> None:
        p = tp.held_back_plan(issue(number=12))
        self.assertEqual((p.number, p.add_labels), (12, ["needs-triage"]))
        self.assertIn("not sent to the model", p.comment)
        self.assertTrue(p.comment.startswith(tp.MARKER))

    def test_held_back_plan_passes_the_apply_check(self) -> None:
        p = tp.held_back_plan(issue())
        self.assertEqual(tp.check_plan(asdict(p), CONFIG), p)

    def test_classify_issue_refuses_a_real_iban(self) -> None:
        client = mock.MagicMock()
        for i in (issue(body=f"From {self.EXAMPLE}."), issue(title=f"IBAN {self.EXAMPLE}")):
            with self.subTest(i=i), self.assertRaises(ValueError):
                tp.classify_issue(client, "rules", i, AREAS)
        client.beta.messages.create.assert_not_called()

    def run_classify(self, found: tp.Issue, retry: bool) -> tuple[mock.MagicMock, list]:
        """Run the classify command on one issue with a fake SDK; return the client and
        the plans it wrote."""
        sdk = mock.MagicMock()
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.dict(sys.modules, {"anthropic": sdk}), \
                mock.patch.object(tp, "fetch_issue", return_value=found):
            out = Path(d) / "plan.json"
            args = ["--repo", "o/r", "classify", "--issue", str(found.number), "--out", str(out)]
            tp.main(args + (["--retry"] if retry else []))
            written = json.loads(out.read_text(encoding="utf-8"))
        return sdk.Anthropic.return_value, written

    def test_classify_never_sends_a_real_iban_to_the_model(self) -> None:
        client, written = self.run_classify(issue(body=f"Booked from {self.EXAMPLE}."), False)
        client.beta.messages.create.assert_not_called()
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0]["add_labels"], ["needs-triage"])
        self.assertIn("not sent to the model", written[0]["comment"])

    def test_held_back_issue_keeps_the_retry_on_an_edit(self) -> None:
        # An edit that adds a real IBAN to an issue at needs-triage: the hold-back plan is
        # written, and the apply step must not skip the issue as already triaged.
        edited = issue(body=f"From {self.EXAMPLE}.", labels={"needs-triage"}, triage_count=1)
        client, written = self.run_classify(edited, True)
        client.beta.messages.create.assert_not_called()
        self.assertEqual(len(written), 1)
        calls = []
        with mock.patch.object(tp, "fetch_issue", return_value=edited), \
                mock.patch.object(tp, "gh", side_effect=gh_stub(calls)):
            tp.apply_plan("o/r", tp.check_plan(written[0], CONFIG))
        self.assertTrue(any(a[:2] == ("issue", "comment") for a in calls))

    def test_classify_keeps_plans_when_a_later_issue_cannot_be_read(self) -> None:
        held = issue(number=1, body=f"From {self.EXAMPLE}.")
        def fetch(repo: str, number: int) -> tp.Issue:
            if number == 1:
                return held
            raise subprocess.CalledProcessError(1, ["gh"], stderr="HTTP 503")
        sdk = mock.MagicMock()
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.dict(sys.modules, {"anthropic": sdk}), \
                mock.patch.object(tp, "open_untriaged", return_value=[1, 2]), \
                mock.patch.object(tp, "fetch_issue", side_effect=fetch):
            out = Path(d) / "plan.json"
            # The command line allows --all only as a preview; the function stays robust.
            args = SimpleNamespace(repo="o/r", all=True, issue=None, limit=20, retry=False,
                                   dry_run=False, out=str(out))
            with self.assertRaises(subprocess.CalledProcessError):
                tp.run_classify(args)
            written = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual([p["number"] for p in written], [1])

    def test_classify_sends_an_ordinary_issue(self) -> None:
        sdk = mock.MagicMock()
        response = SimpleNamespace(
            usage=SimpleNamespace(input_tokens=10, cache_read_input_tokens=0,
                                  cache_creation_input_tokens=0, output_tokens=5),
            model=tp.MODEL, stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=json.dumps(verdict()))])
        sdk.Anthropic.return_value.beta.messages.create.return_value = response
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.dict(sys.modules, {"anthropic": sdk}), \
                mock.patch.object(tp, "fetch_issue", return_value=issue()):
            out = Path(d) / "plan.json"
            tp.main(["--repo", "o/r", "classify", "--issue", "7", "--out", str(out)])
            written = json.loads(out.read_text(encoding="utf-8"))
        sdk.Anthropic.return_value.beta.messages.create.assert_called_once()
        self.assertIn("priority:P1", written[0]["add_labels"])


class Skip(unittest.TestCase):
    def test_skips(self) -> None:
        cases = {
            "already has a priority": issue(labels={"priority:P2"}),
            "is a pull request": issue(is_pr=True),
            "is closed": issue(state="closed"),
            "was opened by a bot": issue(author_is_bot=True),
            "was already triaged": issue(triage_count=1),
        }
        for why, i in cases.items():
            with self.subTest(why=why):
                self.assertEqual(tp.skip_reason(i), why)

    def test_needs_triage_is_retried_on_an_edit(self) -> None:
        self.assertIsNone(tp.skip_reason(issue(triage_count=1, labels={"needs-triage"}), retry=True))

    def test_backfill_and_reopen_never_retry(self) -> None:
        # A back-fill batch used to pick a needs-triage issue up again and comment again.
        self.assertEqual(tp.skip_reason(issue(triage_count=1, labels={"needs-triage"})),
                         "was already triaged")

    def test_edit_does_not_retry_a_placed_issue(self) -> None:
        self.assertEqual(tp.skip_reason(issue(triage_count=1), retry=True), "was already triaged")

    def test_retries_are_capped(self) -> None:
        i = issue(triage_count=tp.MAX_RETRIES + 1, labels={"needs-triage"})
        self.assertEqual(tp.skip_reason(i, retry=True), "was retried too often")
        i = issue(triage_count=tp.MAX_RETRIES, labels={"needs-triage"})
        self.assertIsNone(tp.skip_reason(i, retry=True))

    def test_only_the_workflow_comments_count(self) -> None:
        bot, person = {"login": tp.BOT_LOGIN}, {"login": "someone"}
        comments = [{"body": tp.MARKER + " x", "user": bot},
                    {"body": "copied: " + tp.MARKER, "user": person},
                    {"body": "no marker", "user": bot},
                    {"body": None, "user": None}]
        self.assertEqual(tp.triage_comments(comments), 1)

    def test_marker_is_unchanged(self) -> None:
        # Earlier triage comments carry this marker; a new one would triage them again.
        self.assertEqual(tp.MARKER, "<!-- autobook-triage -->")

    def test_fresh_issue_is_triaged(self) -> None:
        self.assertIsNone(tp.skip_reason(issue()))


def node(number: int, labels=(), comments=(), total=None, bot=False) -> dict:
    """One issue as the back-fill's GraphQL query returns it."""
    return {"number": number,
            "author": {"__typename": "Bot" if bot else "User", "login": "someone"},
            "labels": {"nodes": [{"name": l} for l in labels]},
            "comments": {"totalCount": len(comments) if total is None else total,
                         "nodes": list(comments)}}


BOT_COMMENT = {"author": {"__typename": "Bot", "login": tp.GRAPHQL_BOT_LOGIN},
               "body": tp.MARKER + "\nlabels"}


def pages(*page_nodes: list) -> list[str]:
    """gh outputs for consecutive GraphQL pages."""
    out = []
    for i, nodes in enumerate(page_nodes):
        last = i == len(page_nodes) - 1
        out.append(json.dumps({"data": {"repository": {"issues": {
            "pageInfo": {"hasNextPage": not last, "endCursor": None if last else f"c{i}"},
            "nodes": nodes}}}}))
    return out


class Backfill(unittest.TestCase):
    """The back-fill limit counts only issues that will be triaged."""

    def scan(self, outputs: list[str], limit: int, fetched=None) -> tuple[list[int], list]:
        calls = []
        def fake_gh(*args, **kw):
            calls.append(args)
            return outputs[len(calls) - 1]
        fetch = mock.MagicMock(side_effect=lambda repo, n: fetched[n])
        with mock.patch.object(tp, "gh", side_effect=fake_gh), \
                mock.patch.object(tp, "fetch_issue", fetch):
            return tp.open_untriaged("o/r", limit), calls, fetch

    def test_already_triaged_issues_do_not_fill_the_batch(self) -> None:
        # 1-3 already had their one pass and stay at needs-triage; 4-7 are fresh.
        nodes = [node(n, labels=["needs-triage"], comments=[BOT_COMMENT]) for n in (1, 2, 3)]
        nodes += [node(n) for n in (4, 5, 6, 7)] + [node(8, labels=["priority:P2"])]
        self.assertEqual(self.scan(pages(nodes), 2)[0], [4, 5])
        self.assertEqual(self.scan(pages(nodes), 20)[0], [4, 5, 6, 7])

    def test_one_request_per_page_not_per_issue(self) -> None:
        # #69: 120 already-triaged issues cost three GraphQL requests, no REST call.
        triaged = [node(n, labels=["needs-triage"], comments=[BOT_COMMENT]) for n in range(1, 121)]
        found, calls, fetch = self.scan(pages(triaged[:50], triaged[50:100], triaged[100:]), 20)
        self.assertEqual(found, [])
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(c[:2] == ("api", "graphql") for c in calls))
        fetch.assert_not_called()
        self.assertIn("-f", calls[1])
        self.assertIn("cursor=c0", calls[1])

    def test_stops_at_the_scan_cap(self) -> None:
        many = [node(n, labels=["needs-triage"], comments=[BOT_COMMENT]) for n in range(1, 51)]
        outputs = pages(*([many] * 20))
        _, calls, _ = self.scan(outputs, 20)
        self.assertEqual(len(calls), tp.MAX_SCAN // tp.BACKFILL_PAGE)

    def test_stops_once_the_limit_is_reached(self) -> None:
        fresh = [node(n) for n in range(1, 51)]
        found, calls, _ = self.scan(pages(fresh, fresh), 3)
        self.assertEqual((found, len(calls)), ([1, 2, 3], 1))

    def test_only_the_workflow_comments_count(self) -> None:
        copied = {"author": {"__typename": "User", "login": "github-actions"},
                  "body": tp.MARKER}
        other_bot = {"author": {"__typename": "Bot", "login": "dependabot"}, "body": tp.MARKER}
        nodes = [node(1, comments=[copied]), node(2, comments=[other_bot]), node(3, bot=True)]
        self.assertEqual(self.scan(pages(nodes), 20)[0], [1, 2])

    def test_reads_an_issue_with_many_comments_through_rest(self) -> None:
        nodes = [node(1, comments=[{"author": None, "body": "x"}] * 100, total=150)]
        found, _, fetch = self.scan(pages(nodes), 20,
                                    fetched={1: issue(number=1, triage_count=1)})
        self.assertEqual(found, [])
        fetch.assert_called_once_with("o/r", 1)

class Dispatch(unittest.TestCase):
    """#70: a back-fill starts one run per issue, in that issue's concurrency group."""

    def test_starts_one_run_per_issue(self) -> None:
        calls = []
        with mock.patch.object(tp, "open_untriaged", return_value=[4, 9]), \
                mock.patch.object(tp, "gh", side_effect=gh_stub(calls)), mock.patch("sys.stdout"):
            self.assertEqual(tp.main(["--repo", "o/r", "dispatch", "--limit", "5"]), 0)
        self.assertEqual(calls, [
            ("workflow", "run", "triage-priority.yml", "-R", "o/r", "--ref", "main",
             "-f", "issue=4"),
            ("workflow", "run", "triage-priority.yml", "-R", "o/r", "--ref", "main",
             "-f", "issue=9")])

    def test_one_failed_dispatch_does_not_stop_the_others(self) -> None:
        # Codex review: a 502 starting one run used to end the back-fill.
        calls = []
        with mock.patch.object(tp, "open_untriaged", return_value=[4, 9]), \
                mock.patch.object(tp, "gh", side_effect=gh_stub(calls, fail=lambda a: "issue=4" in a)), \
                mock.patch("sys.stdout"), mock.patch("sys.stderr"):
            self.assertEqual(tp.main(["--repo", "o/r", "dispatch"]), 1)
        self.assertEqual([a[-1] for a in calls], ["issue=4", "issue=9"])

    def test_pending_runs_are_queued_not_replaced(self) -> None:
        # Codex review: a dispatched run must not replace a pending edit run.
        block = Workflow.TEXT[Workflow.TEXT.index("\nconcurrency:"):Workflow.TEXT.index("\njobs:")]
        self.assertIn("queue: max", block)
        self.assertIn("cancel-in-progress: false", block)

    def test_classify_all_only_previews(self) -> None:
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            tp.main(["--repo", "o/r", "classify", "--all", "--out", "plan.json"])

    def test_the_workflow_routes_a_backfill_through_dispatch(self) -> None:
        jobs = Workflow.TEXT[Workflow.TEXT.index("\njobs:"):]
        dispatch = jobs[jobs.index("  dispatch:"):jobs.index("  classify:")]
        self.assertIn("actions: write", dispatch)
        self.assertNotIn("id-token", dispatch)
        self.assertNotIn("issues: write", dispatch)
        self.assertIn("triage_priority.py dispatch", dispatch)
        classify = jobs[jobs.index("  classify:"):jobs.index("  apply:")]
        self.assertIn("inputs.issue || inputs.dry_run", classify)
        self.assertNotIn("actions:", classify)
        # Every run for one issue shares its group, the dispatched ones included.
        self.assertIn("issue-priority-${{ github.event.issue.number || inputs.issue",
                      Workflow.TEXT)


class Limit(unittest.TestCase):
    def test_rejects_a_limit_below_one(self) -> None:
        # #68: -1 never equalled the count, so the cap was off.
        for bad in ("-1", "0", "x"):
            with self.subTest(limit=bad), self.assertRaises(SystemExit), \
                    mock.patch("sys.stderr"):
                tp.main(["--repo", "o/r", "classify", "--all", "--limit", bad, "--dry-run"])

    def test_accepts_a_positive_limit(self) -> None:
        self.assertEqual(tp.positive_int("3"), 3)


class ClearsNeedsTriage(unittest.TestCase):
    def test_a_placed_priority_clears_needs_triage(self) -> None:
        p = plan(i=issue(labels={"needs-triage"}))
        self.assertEqual(p.remove_labels, ["needs-triage"])
        self.assertTrue(any(l.startswith("priority:") for l in p.add_labels))

    def test_still_unsure_keeps_it(self) -> None:
        p = plan(i=issue(labels={"needs-triage"}), unsure=True, missing="Which version ran.")
        self.assertEqual(p.remove_labels, [])

    def test_nothing_removed_on_a_fresh_issue(self) -> None:
        self.assertEqual(plan().remove_labels, [])


class BuildPlan(unittest.TestCase):
    def test_labels_and_priority(self) -> None:
        p = plan()
        self.assertEqual(p.number, 7)
        self.assertEqual(p.add_labels,
                         ["bug", "area:correlator", "sev:critical", "reach:edge", "priority:P1"])
        self.assertEqual(p.assignee, "eduralph")
        self.assertTrue(p.comment.startswith(tp.MARKER))
        self.assertIn("critical × edge is P1", p.comment)
        self.assertIn("ADR-0003", p.comment)

    def test_label_descriptions_fit_github_limit(self) -> None:
        for group in ("severity", "reach", "area", "priority", "other"):
            for name, spec in CONFIG[group].items():
                with self.subTest(label=name):
                    self.assertLessEqual(len(spec["description"]), 100)

    def test_does_not_clash_with_existing_labels(self) -> None:
        mine = {n for g in ("severity", "reach", "area", "priority", "other") for n in CONFIG[g]}
        self.assertFalse(mine & {"build-order", "no-code", "spike", "human-run", "new"})

    def test_every_label_it_adds_is_allowed(self) -> None:
        p = plan(flags=dict(NO_FLAGS, booking_integrity=True), areas=["book", "review"])
        self.assertLessEqual(set(p.add_labels), tp.allowed_labels(CONFIG))

    def test_keeps_existing_type_and_assignee(self) -> None:
        p = plan(i=issue(labels={"enhancement"}, assignees=["someone"]))
        self.assertNotIn("bug", p.add_labels)
        self.assertIsNone(p.assignee)
        self.assertIn("It reads more like bug", p.comment)

    def test_no_type_note_when_the_label_agrees(self) -> None:
        self.assertNotIn("reads more like", plan(i=issue(labels={"bug"})).comment)

    def test_every_type_gets_a_priority(self) -> None:
        for kind in ("enhancement", "documentation", "spike"):
            with self.subTest(kind=kind):
                p = plan(type=kind, severity="minor", reach="common")
                self.assertIn(kind, p.add_labels)
                self.assertIn("priority:P2", p.add_labels)

    def test_existing_spike_label_still_gets_a_priority(self) -> None:
        p = plan(i=issue(labels={"spike"}), severity="trivial", reach="common")
        self.assertIn("priority:P3", p.add_labels)

    def test_unsure_sets_needs_triage_and_no_priority(self) -> None:
        p = plan(unsure=True, missing="Whether the book is XML or SQL.")
        self.assertIn("needs-triage", p.add_labels)
        self.assertFalse(any(l.startswith(("priority:", "sev:", "reach:")) for l in p.add_labels))

    def test_override_is_explained(self) -> None:
        p = plan(severity="minor", reach="edge", flags=dict(NO_FLAGS, booking_integrity=True))
        self.assertIn("priority:P1", p.add_labels)
        self.assertIn("booking-integrity bug (at least P1)", p.comment)

    def test_vulnerability_report_gets_the_security_floor(self) -> None:
        p = plan(severity="trivial", reach="adversarial", vulnerability_report=True)
        self.assertIn("priority:P1", p.add_labels)
        self.assertIn("security or privacy bug", p.comment)

    def test_review_priority_is_explained(self) -> None:
        p = plan(severity="minor", reach="edge", review_priority="P2")
        self.assertIn("priority:P2", p.add_labels)
        self.assertIn("kept the deferred review's P2", p.comment)

    def test_financial_data_withholds_every_reason(self) -> None:
        # A short payee name slips past the echo check; with the flag set, no reason is posted.
        i = issue(body="Paid Praxis Dr. Imaginary, memo Rechnung, booked twice.")
        p = plan(i=i, financial_data=True,
                 reasons={"type": "A payment to Praxis Dr. Imaginary is wrong.",
                          "severity": "Dr. Imaginary is booked twice.",
                          "reach": "Any Praxis Dr. Imaginary payment.",
                          "area": "The correlator.", "overrides": "None apply."})
        self.assertNotIn("Imaginary", p.comment)
        self.assertIn("made-up example", p.comment)

    def test_secret_withholds_every_reason(self) -> None:
        # A one-word password has no digit or mark, so the echo check alone misses it.
        i = issue(body="The config holds password huntertwo and the import fails.")
        p = plan(i=i, secret_in_issue=True, unsure=True, missing="Whether huntertwo is still valid.",
                 reasons={"type": "The import fails with password huntertwo set.",
                          "severity": "Uses huntertwo.", "reach": "Anyone with huntertwo.",
                          "area": "The importer.", "overrides": "None apply."})
        self.assertNotIn("huntertwo", p.comment)
        self.assertIn("rotate", p.comment)

    def test_longest_comment_fits_the_apply_check(self) -> None:
        long = "word " * 60
        p = tp.build_plan(issue(labels={"enhancement"}), tp.validate(verdict(
            areas=["book", "review"], vulnerability_report=True, financial_data=True,
            secret_in_issue=True, review_priority="P3",
            flags={f: True for f in tp.FLAGS},
            reasons={k: long for k in verdict()["reasons"]}), AREAS), CONFIG,
            model=tp.MODEL, usage="1 in, 1 out", truncated=True)
        self.assertEqual(tp.check_plan(asdict(p), CONFIG), p)

    def test_never_touches_the_milestone(self) -> None:
        self.assertFalse(hasattr(plan(), "milestone"))

    def test_input_is_capped_and_says_so(self) -> None:
        text, truncated = tp.issue_input(issue(body="x" * (tp.MAX_BODY + 50)))
        self.assertTrue(truncated)
        self.assertIn("cut at", text)
        self.assertLess(len(text), tp.MAX_BODY + tp.MAX_TITLE + 200)

    def test_unclassified_plan(self) -> None:
        p = tp.unclassified_plan(issue(), "the model declined to classify it", model="m", usage="u")
        self.assertEqual((p.number, p.add_labels), (7, ["needs-triage"]))
        self.assertIn(tp.MARKER, p.comment)


class ApplyCheck(unittest.TestCase):
    """The apply job treats the classify job's plan as data and checks it again."""

    def entry(self, **over) -> dict:
        e = {"number": 7, "add_labels": ["bug", "area:correlator", "sev:critical", "reach:edge",
                                         "priority:P1"],
             "remove_labels": [], "assignee": "eduralph", "comment": tp.MARKER + "\nok\n",
             "retry": False, "triage_count": 0, "text_hash": tp.text_hash(issue()),
}
        e.update(over)
        return e

    def test_a_built_plan_passes(self) -> None:
        p = plan(severity="minor", reach="edge", review_priority="P2")
        self.assertEqual(tp.check_plan(asdict(p), CONFIG), p)
        self.assertEqual(tp.check_plan(self.entry(), CONFIG).number, 7)

    def test_retry_and_triage_count_are_checked(self) -> None:
        for over in ({"retry": "yes"}, {"triage_count": -1}, {"triage_count": True}):
            with self.subTest(over=over), self.assertRaises(tp.InvalidPlan):
                tp.check_plan(self.entry(**over), CONFIG)

    def apply_to(self, p: tp.Plan, fresh: tp.Issue) -> list:
        calls = []
        with mock.patch.object(tp, "fetch_issue", return_value=fresh), \
                mock.patch.object(tp, "gh", side_effect=gh_stub(calls)):
            tp.apply_plan("o/r", p)
        return calls

    def test_apply_skips_a_plan_another_run_overtook(self) -> None:
        # A back-fill and an issue event classified the same issue; the other one applied
        # first, so this plan must not post a second comment.
        p = tp.check_plan(self.entry(retry=True, triage_count=1), CONFIG)
        self.assertEqual(self.apply_to(p, issue(number=7, triage_count=2, labels={"needs-triage"})), [])

    def test_apply_keeps_the_classify_runs_retry(self) -> None:
        # A plan made without an edit never retries an issue already triaged.
        p = tp.check_plan(self.entry(retry=False, triage_count=1), CONFIG)
        self.assertEqual(self.apply_to(p, issue(number=7, triage_count=1, labels={"needs-triage"})), [])
        p = tp.check_plan(self.entry(retry=True, triage_count=1), CONFIG)
        calls = self.apply_to(p, issue(number=7, triage_count=1, labels={"needs-triage"}))
        self.assertTrue(any(a[:2] == ("issue", "comment") for a in calls))

    def test_round_trip_through_the_file(self) -> None:
        plans = [plan(), tp.unclassified_plan(issue(number=9), "x", model="m", usage="u"),
                 tp.held_back_plan(issue(number=11))]
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "plan.json"
            tp.write_plans(path, plans)
            self.assertEqual(tp.read_plans(path, CONFIG), plans)

    def test_rejects(self) -> None:
        bad = {
            "unknown label": self.entry(add_labels=["bug", "wontfix"]),
            "planning label": self.entry(add_labels=["build-order"]),
            "two priorities": self.entry(add_labels=["priority:P1", "priority:P3"]),
            "two severities": self.entry(add_labels=["sev:major", "sev:minor"]),
            "two types": self.entry(add_labels=["bug", "spike"]),
            "three areas": self.entry(add_labels=["area:book", "area:review", "area:ci"]),
            "foreign assignee": self.entry(assignee="mallory"),
            "foreign comment": self.entry(comment="Please run this script: ..."),
            "huge comment": self.entry(comment=tp.MARKER + "x" * tp.MAX_COMMENT),
            "old template marker": self.entry(comment="<!-- issue-triage -->\nok\n"),
            "bad number": self.entry(number="7"),
            "bool number": self.entry(number=True),
            "labels not a list": self.entry(add_labels="bug"),
            "removes another label": self.entry(remove_labels=["priority:P1"]),
            "remove not a list": self.entry(remove_labels="needs-triage"),
        }
        for why, e in bad.items():
            with self.subTest(why=why), self.assertRaises(tp.InvalidPlan):
                tp.check_plan(e, CONFIG)
        with self.assertRaises(tp.InvalidPlan):
            tp.check_plan({"number": 7}, CONFIG)

    def test_rejects_a_plan_that_is_not_a_list(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "plan.json"
            path.write_text(json.dumps({"number": 7}), encoding="utf-8")
            with self.assertRaises(tp.InvalidPlan):
                tp.read_plans(path, CONFIG)

    def test_apply_never_imports_the_sdk(self) -> None:
        # The SDK is imported only inside run_classify, never at module level or in apply.
        tree = ast.parse(Path(tp.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] + [getattr(node, "module", None) or ""]
                if "anthropic" in names:
                    owner = next(f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef)
                                 and node in ast.walk(f))
                    self.assertIn(owner.name, ("run_classify", "claude_client"))
        # ... and the apply path never reaches either.
        for name in ("run_apply", "apply_plan", "check_plan", "read_plans", "ensure_labels"):
            source = ast.get_source_segment(Path(tp.__file__).read_text(encoding="utf-8"),
                                            next(f for f in ast.walk(tree)
                                                 if isinstance(f, ast.FunctionDef) and f.name == name))
            with self.subTest(function=name):
                self.assertNotIn("claude_client", source)
                self.assertNotIn("run_classify", source)


class HoldBack(unittest.TestCase):
    """#57: more than an IBAN is kept from the model. Every value below is made up."""

    def test_credentials_are_held_back(self) -> None:
        for text in (
            "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAA\n",
            "key sk-ant-api03-" + "x1" * 20,
            "token ghp_" + "a1B2" * 9,
            "github_pat_" + "a1B2_" * 10,
            "AKIA" + "ABCDEFGHIJ234567",
            "AIza" + "a1" * 17 + "b",
            "xoxb-1234567890-abcdefghij",
            ".".join(["eyJ" + "a1b2" * 3, "eyJ" + "c3d4" * 3, "e5f6" * 3]),  # JWT shape
            "paperless:\n  token: " + "3f9a" * 4,
            'PASSWORD="hunter2hunter2"',
            "api_key = " + "Zq8v" * 3,
            # Codex review: a prefixed key name.
            "PAPERLESS_TOKEN=" + "abcd1234" + "efgh",
            "AWS_SECRET_ACCESS_KEY=" + "Abcd1234" * 2,
            "client_secret=" + "abcd1234",
            '"token": "' + "abc12345x" + '"',
        ):
            with self.subTest(text=text[:20]):
                self.assertEqual(tp.hold_back_reason(text), "secret")

    def test_placeholders_and_prose_are_not_credentials(self) -> None:
        for text in ("Set `token: <your paperless token>` in the config.",
                     "api_key = os.environ['KEY']", "GH_TOKEN: ${{ github.token }}",
                     "The password field is empty.", "token: changeme",
                     "A read-only token works.", "author: someone else",
                     "The tokenizer: splits words1234", "x" * 60000):
            with self.subTest(text=text):
                self.assertIsNone(tp.hold_back_reason(text))

    def test_account_paths_are_held_back(self) -> None:
        for text in ("booked to Ausgaben:Arzt", "Expenses:Medical:Dentist is wrong",
                     "from Aktiva:Girokonto", "Einnahmen:Gehalt twice",
                     "expenses:Medical", "AUSGABEN:Arzt"):
            with self.subTest(text=text):
                self.assertEqual(tp.hold_back_reason(text), "account")

    def test_ordinary_text_is_sent(self) -> None:
        for text in ("Expenses: the cost of a run is high.", "Imbalance-EUR fills up.",
                     "The income statement is wrong.", "PR 12 fixes it",
                     "Transfer between two own accounts is booked twice"):
            with self.subTest(text=text):
                self.assertIsNone(tp.hold_back_reason(text))

    def test_held_back_comment_names_the_kind_never_the_match(self) -> None:
        body = "Booked to Ausgaben:Arzt with token ghp_" + "a1B2" * 9
        for reason, word in (("iban", "IBAN"), ("secret", "rotate"), ("account", "account")):
            with self.subTest(reason=reason):
                p = tp.held_back_plan(issue(body=body), reason)
                self.assertIn(word, p.comment)
                self.assertNotIn("Arzt", p.comment)
                self.assertNotIn("ghp_", p.comment)
                self.assertEqual(p.add_labels, ["needs-triage"])
                self.assertEqual(tp.check_plan(asdict(p), CONFIG), p)

    def test_classify_never_sends_a_held_back_issue(self) -> None:
        client = mock.MagicMock()
        for i in (issue(body="booked to Ausgaben:Arzt"), issue(title="token ghp_" + "a1B2" * 9)):
            with self.subTest(i=i.title), self.assertRaises(ValueError):
                tp.classify_issue(client, "rules", i, AREAS)
        client.beta.messages.create.assert_not_called()

    def test_the_whole_body_is_checked_not_only_what_is_sent(self) -> None:
        body = "x" * (tp.MAX_BODY + 10) + " Ausgaben:Arzt"
        self.assertEqual(tp.hold_back_reason(body), "account")


class ApplyRechecks(unittest.TestCase):
    def apply_to(self, p: tp.Plan, fresh: tp.Issue, fail=None, after=None,
                 assignees=()) -> list:
        """Apply ``p``; the issue reads as ``fresh``, and as ``after`` on any later read."""
        calls = []
        reads = iter([fresh] + [after or fresh] * 5)
        with mock.patch.object(tp, "fetch_issue", side_effect=lambda r, n: next(reads)), \
                mock.patch.object(tp, "gh", side_effect=gh_stub(calls, fail, assignees)), \
                mock.patch("sys.stderr"):
            try:
                tp.apply_plan("o/r", p)
            except subprocess.CalledProcessError:
                calls.append(("raised",))
        return writes(calls)

    def test_drops_a_plan_for_text_that_changed(self) -> None:
        # #58: the author edited while the model ran; the queued edit run classifies it.
        p = plan()
        self.assertEqual(self.apply_to(p, issue(body="Edited: it only happens on SQL books.")), [])
        self.assertEqual(self.apply_to(p, issue(title="New title")), [])
        self.assertTrue(self.apply_to(p, issue()))

    def test_a_failed_comment_takes_the_labels_off_again(self) -> None:
        # #59: otherwise the priority stays with no comment and a rerun skips the issue.
        p = plan(i=issue(labels={"needs-triage", "bug"}))
        labelled = issue(labels={"bug", "area:correlator", "sev:critical", "reach:edge",
                                 "priority:P1"})
        calls = self.apply_to(p, issue(labels={"needs-triage", "bug"}), after=labelled,
                              fail=lambda a: a[:2] == ("issue", "comment"))
        self.assertEqual(calls[-1], ("raised",))
        added = [a for a in calls if "--add-label" in a]
        removed = [a for a in calls if "--remove-label" in a]
        self.assertEqual(added[0][-1], "area:correlator,sev:critical,reach:edge,priority:P1")
        self.assertEqual(removed[-1][-1], added[0][-1])   # undone
        self.assertEqual(added[-1][-1], "needs-triage")    # restored
        self.assertFalse(any("--add-assignee" in a for a in calls))

    def test_labels_it_did_not_add_are_not_removed_on_undo(self) -> None:
        p = plan()
        fresh = issue(labels={"area:correlator"})
        labelled = issue(labels={"bug", "area:correlator", "sev:critical", "reach:edge",
                                 "priority:P1"})
        calls = self.apply_to(p, fresh, after=labelled,
                              fail=lambda a: a[:2] == ("issue", "comment"))
        undo = [a for a in calls if "--remove-label" in a][-1]
        self.assertNotIn("area:correlator", undo[-1].split(","))

    def test_skips_the_assignee_when_someone_was_assigned_meanwhile(self) -> None:
        # #67: a maintainer assigned someone while the model ran.
        p = plan()
        self.assertEqual(p.assignee, "eduralph")
        calls = self.apply_to(p, issue(assignees=["maintainer"]))
        self.assertTrue(any(a[:2] == ("issue", "comment") for a in calls))
        self.assertFalse(any("--add-assignee" in a for a in calls))
        self.assertTrue(any("--add-assignee" in a for a in self.apply_to(p, issue())))

    def test_reads_the_assignees_again_just_before_assigning(self) -> None:
        # Codex review: someone assigned while the labels and comment went on.
        calls = self.apply_to(plan(), issue(), assignees=["maintainer"])
        self.assertTrue(any(a[:2] == ("issue", "comment") for a in calls))
        self.assertFalse(any("--add-assignee" in a for a in calls))

    def test_a_lost_response_with_the_comment_posted_completes_the_labels(self) -> None:
        # The comment call failed but reached GitHub: keep the labels it explains.
        p = plan(i=issue(labels={"needs-triage", "bug"}))
        posted = issue(labels={"needs-triage", "bug"}, triage_count=1)
        calls = self.apply_to(p, issue(labels={"needs-triage", "bug"}), after=posted,
                              fail=lambda a: a[:2] == ("issue", "comment"))
        self.assertEqual(calls[-1], ("raised",))
        added = [a for a in calls if "--add-label" in a]
        self.assertEqual(added[-1][-1], "area:correlator,sev:critical,reach:edge,priority:P1")
        self.assertEqual(calls[-2][-1], "needs-triage")
        self.assertIn("--remove-label", calls[-2])

    def test_undo_only_removes_labels_that_are_there(self) -> None:
        # The add-label call failed without reaching GitHub: nothing to take off.
        calls = self.apply_to(plan(), issue(), fail=lambda a: "--add-label" in a)
        self.assertFalse(any("--remove-label" in a for a in calls))

    def test_assignee_comes_after_the_comment(self) -> None:
        calls = self.apply_to(plan(), issue())
        kinds = ["comment" if a[:2] == ("issue", "comment") else a[-2] for a in calls]
        self.assertEqual(kinds[-2:], ["comment", "--add-assignee"])

    def test_one_failed_issue_does_not_stop_the_others(self) -> None:
        plans = [plan(i=issue(number=1)), plan(i=issue(number=2))]
        def fetch(repo, n):
            if n == 1:
                raise subprocess.CalledProcessError(1, ["gh"], stderr="HTTP 502")
            return issue(number=2)
        written = []
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(tp, "fetch_issue", side_effect=fetch), \
                mock.patch.object(tp, "ensure_labels"), mock.patch("sys.stderr"), \
                mock.patch.object(tp, "gh", side_effect=gh_stub(written)):
            path = Path(d) / "plan.json"
            tp.write_plans(path, plans)
            self.assertEqual(tp.main(["--repo", "o/r", "apply", "--plan", str(path)]), 1)
        self.assertTrue(any(a[:3] == ("issue", "comment", "2") for a in written))


class EnsureLabels(unittest.TestCase):
    def test_a_label_another_run_created_is_fine(self) -> None:
        # #66: two runs both saw the label missing.
        def fake_gh(*a, **k):
            if a[:2] == ("label", "list"):
                return "[]"
            raise subprocess.CalledProcessError(
                1, ["gh"], stderr=f'label with name "{a[2]}" already exists; use `--force`')
        with mock.patch.object(tp, "gh", side_effect=fake_gh), mock.patch("sys.stdout"):
            tp.ensure_labels("o/r", CONFIG)

    def test_other_failures_still_fail(self) -> None:
        def fake_gh(*a, **k):
            if a[:2] == ("label", "list"):
                return "[]"
            raise subprocess.CalledProcessError(1, ["gh"], stderr="HTTP 403")
        with mock.patch.object(tp, "gh", side_effect=fake_gh), \
                self.assertRaises(subprocess.CalledProcessError):
            tp.ensure_labels("o/r", CONFIG)


class Retry(unittest.TestCase):
    """#63: provisional areas and owner are not set by an unsure verdict."""

    def test_unsure_sets_no_area_and_no_owner(self) -> None:
        p = plan(unsure=True, missing="Whether the book is XML or SQL.")
        self.assertFalse(any(l.startswith("area:") for l in p.add_labels))
        self.assertIsNone(p.assignee)

    def test_a_placed_retry_sets_the_areas_and_owner(self) -> None:
        p = plan(i=issue(labels={"needs-triage", "bug"}, triage_count=1), areas=["book"])
        self.assertIn("area:book", p.add_labels)
        self.assertEqual(p.assignee, "eduralph")

    def test_areas_already_set_are_kept_and_not_added_to(self) -> None:
        p = plan(i=issue(labels={"area:review"}), areas=["book", "correlator"])
        self.assertFalse(any(l.startswith("area:") for l in p.add_labels))
        self.assertIn("Kept the area", p.comment)


class Truncated(unittest.TestCase):
    def test_a_failed_classification_says_the_text_was_cut(self) -> None:
        # #64
        p = tp.unclassified_plan(issue(), "the model ran out of output room", model="m",
                                 usage="u", truncated=True)
        self.assertIn(tp.TRUNCATED_NOTE, p.comment)
        self.assertNotIn(tp.TRUNCATED_NOTE, tp.unclassified_plan(issue(), "x", model="m",
                                                                  usage="u").comment)

    def test_classify_passes_the_cut_on(self) -> None:
        sdk = mock.MagicMock()
        response = SimpleNamespace(
            usage=SimpleNamespace(input_tokens=10, cache_read_input_tokens=0,
                                  cache_creation_input_tokens=0, output_tokens=5),
            model=tp.MODEL, stop_reason="refusal", content=[])
        sdk.Anthropic.return_value.beta.messages.create.return_value = response
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.dict(sys.modules, {"anthropic": sdk}), \
                mock.patch.dict("os.environ", {"ACTIONS_ID_TOKEN_REQUEST_URL": ""}), \
                mock.patch.object(tp, "fetch_issue",
                                  return_value=issue(body="x" * (tp.MAX_BODY + 1))):
            out = Path(d) / "plan.json"
            tp.main(["--repo", "o/r", "classify", "--issue", "7", "--out", str(out)])
            written = json.loads(out.read_text(encoding="utf-8"))
        self.assertIn(tp.TRUNCATED_NOTE, written[0]["comment"])


class StatedReviewPriority(unittest.TestCase):
    """#65: the issue's own "Review priority: P0" to "P3" line, from a maintainer, is kept."""

    BODY = "Deferred finding.\n\nReview priority: P1. Per ADR-0003 the issue keeps it."

    def test_a_maintainers_line_raises_the_table(self) -> None:
        p = plan(i=issue(body=self.BODY), severity="minor", reach="edge")
        self.assertIn("priority:P1", p.add_labels)
        self.assertIn("the deferred review's priority the issue states (at least P1)", p.comment)

    def test_a_maintainers_line_never_lowers_the_table(self) -> None:
        # Codex review: the line is a floor (#65), so a critical/common issue stays P0.
        p = plan(i=issue(body="Review priority: P2"), severity="critical", reach="common")
        self.assertIn("priority:P0", p.add_labels)

    def test_the_line_wins_over_the_models_reading(self) -> None:
        p = plan(i=issue(body=self.BODY), severity="minor", reach="edge", review_priority="P3")
        self.assertIn("priority:P1", p.add_labels)

    def test_a_strangers_line_and_reading_are_ignored(self) -> None:
        for assoc in ("NONE", "CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR"):
            with self.subTest(assoc=assoc):
                i = issue(body="Review priority: P0", author_association=assoc)
                p = plan(i=i, severity="minor", reach="edge", review_priority="P0")
                self.assertIn("priority:P3", p.add_labels)

    def test_floors_still_apply(self) -> None:
        p = plan(i=issue(body="Review priority: P3"), severity="minor", reach="edge",
                 flags=dict(NO_FLAGS, booking_integrity=True))
        self.assertIn("priority:P1", p.add_labels)

    def test_line_forms(self) -> None:
        for body, want in (("Review priority: P2", "P2"), ("**Review priority:** P0", "P0"),
                           ("> review priority: p3", "P3"), ("Review priority: P4", None),
                           ("The review priority: P1 was wrong", None),
                           ("Review priority: P1\nReview priority: P2", None)):
            with self.subTest(body=body):
                self.assertEqual(tp.stated_review_priority(issue(body=body)), want)


class Usage(unittest.TestCase):
    def test_fallback_attempts_are_counted(self) -> None:
        # #62: the declined first attempt is billed too.
        declined = SimpleNamespace(type="message", input_tokens=100, output_tokens=20,
                                   cache_read_input_tokens=2000, cache_creation_input_tokens=0)
        served = SimpleNamespace(type="fallback_message", input_tokens=110, output_tokens=200,
                                 cache_read_input_tokens=0, cache_creation_input_tokens=2000)
        u = SimpleNamespace(input_tokens=110, output_tokens=200, cache_read_input_tokens=0,
                            cache_creation_input_tokens=2000, iterations=[declined, served])
        self.assertEqual(tp.usage_line(u),
                         "4,210 tokens in (2,000 cached), 220 out over 2 attempts")

    def test_without_iterations_the_top_level_counts(self) -> None:
        u = SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=None,
                            cache_creation_input_tokens=0, iterations=None)
        self.assertEqual(tp.usage_line(u), "10 tokens in (0 cached), 5 out")


class Identity(unittest.TestCase):
    """#61: a fresh GitHub identity token for every exchange."""

    ENV = {"ACTIONS_ID_TOKEN_REQUEST_URL": "https://gh.example/token?api-version=2.0",
           "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "req",
           "ANTHROPIC_FEDERATION_RULE_ID": "fdrl_1", "ANTHROPIC_ORGANIZATION_ID": "org",
           "ANTHROPIC_SERVICE_ACCOUNT_ID": "svac_1", "ANTHROPIC_WORKSPACE_ID": ""}

    def test_each_call_asks_github_again(self) -> None:
        seen = []
        def urlopen(request, timeout):
            seen.append((request.full_url, request.get_header("Authorization")))
            return io.BytesIO(json.dumps({"value": f"jwt{len(seen)}"}).encode())
        with mock.patch.dict("os.environ", self.ENV), \
                mock.patch.object(tp.urllib.request, "urlopen", side_effect=urlopen):
            self.assertEqual([tp.github_identity_token(), tp.github_identity_token()],
                             ["jwt1", "jwt2"])
        self.assertEqual(seen[0], ("https://gh.example/token?api-version=2.0"
                                   "&audience=https%3A%2F%2Fapi.anthropic.com", "Bearer req"))

    def test_client_uses_the_provider(self) -> None:
        sdk = mock.MagicMock()
        creds = sdk.lib.credentials
        with mock.patch.dict(sys.modules, {"anthropic": sdk, "anthropic.lib": sdk.lib,
                                           "anthropic.lib.credentials": creds}), \
                mock.patch.dict("os.environ", self.ENV):
            tp.claude_client(max_retries=3)
        kw = creds.WorkloadIdentityCredentials.call_args.kwargs
        self.assertIs(kw["identity_token_provider"], tp.github_identity_token)
        self.assertIsNone(kw["workspace_id"])
        self.assertEqual(kw["service_account_id"], "svac_1")
        sdk.Anthropic.assert_called_once_with(
            credentials=creds.WorkloadIdentityCredentials.return_value, max_retries=3)


class Workflow(unittest.TestCase):
    TEXT = (Path(tp.__file__).parent.parent / "workflows" / "triage-priority.yml").read_text(
        encoding="utf-8")

    def test_triage_is_enabled_only_with_every_federation_variable(self) -> None:
        # #71
        step = self.TEXT[self.TEXT.index("Check the federation settings"):
                         self.TEXT.index("Install the pinned")]
        for var in ("ANTHROPIC_FEDERATION_RULE_ID", "ANTHROPIC_ORGANIZATION_ID",
                    "ANTHROPIC_SERVICE_ACCOUNT_ID"):
            with self.subTest(var=var):
                self.assertIn(f"vars.{var}", step)
                self.assertIn(f"missing+=({var})", step)

    def test_no_identity_token_is_fetched_once_up_front(self) -> None:
        self.assertNotIn("ANTHROPIC_IDENTITY_TOKEN_FILE", self.TEXT)
        self.assertNotIn("gha-jwt", self.TEXT)


class LoadPrompt(unittest.TestCase):
    def write(self, text: str) -> Path:
        d = Path(tempfile.mkdtemp())
        (d / "prompt.md").write_text(text, encoding="utf-8")
        return d / "prompt.md"

    def test_refuses_template_text(self) -> None:
        for text in ("You triage. PROJECT SUMMARY here.", "- `core`: EXAMPLE, replace: x."):
            with self.subTest(text=text), self.assertRaises(SystemExit):
                tp.load_prompt(self.write(text))

    def test_strips_maintainer_notes(self) -> None:
        p = tp.load_prompt(self.write("Rules.\n<!-- note\n  for maintainers -->\n- `a`: b.\n"))
        self.assertEqual(p, "Rules.\n- `a`: b.\n")

    def test_the_real_prompt_loads_unchanged(self) -> None:
        raw = (Path(tp.__file__).parent / "prompt.md").read_text(encoding="utf-8")
        self.assertEqual(tp.load_prompt(), raw)

    def test_the_real_prompt_states_the_review_exception(self) -> None:
        # ADR-0003 section 3: the review's priority holds unless the pull request changed
        # the impact. The model then reports `none` and the table applies.
        text = " ".join(tp.load_prompt().split())
        self.assertIn("keep the review's priority, unless the issue shows the pull request "
                      "changed the impact; then set it to `none`", text)

    def test_the_real_prompt_names_every_field(self) -> None:
        text = tp.load_prompt()
        for name in (*tp.TYPES, *tp.FLAGS, *AREAS, "review_priority", "financial_data",
                     "secret_in_issue", "vulnerability_report", "unsure", "missing"):
            with self.subTest(name=name):
                self.assertIn(f"`{name}`", text)


if __name__ == "__main__":
    unittest.main()

"""Tests for triage_priority.py: everything after the model call, offline.

Run: python -I -m unittest discover -s .github/triage

All financial data below is made up: the IBANs have an invalid check number and the
payees and memos are invented, as the repository's fixtures must be (AGENTS.md).
"""

from __future__ import annotations

import ast
import json
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
                 body="Steps: import both statements in one batch.", labels=set(), assignees=[])
    for k, val in over.items():
        setattr(i, k, val)
    return i


def plan(i: tp.Issue | None = None, **v) -> tp.Plan:
    return tp.build_plan(i or issue(), tp.validate(verdict(**v), AREAS), CONFIG,
                         model=tp.MODEL, usage="1 in, 1 out", truncated=False)


def prio(severity, reach, flags=None, review="none", labels=()):
    return tp.compute_priority(severity, reach, flags or NO_FLAGS, review, set(labels))


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

    def test_at_most_two_areas(self) -> None:
        got = tp.validate(verdict(areas=["correlator", "book", "review"]), AREAS)["areas"]
        self.assertEqual(got, ["correlator", "book"])

    def test_no_area_is_allowed(self) -> None:
        self.assertEqual(tp.validate(verdict(areas=[]), AREAS)["areas"], [])

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
                mock.patch.object(tp, "gh", side_effect=lambda *a, **k: calls.append(a) or ""):
            tp.apply_plan("o/r", tp.check_plan(written[0], CONFIG))
        self.assertTrue(any(a[:2] == ("issue", "comment") for a in calls))

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


class Backfill(unittest.TestCase):
    """The back-fill limit counts only issues that will be triaged."""

    def test_already_triaged_issues_do_not_fill_the_batch(self) -> None:
        listed = [{"number": n, "labels": []} for n in range(1, 8)]
        listed.append({"number": 8, "labels": [{"name": "priority:P2"}]})
        # 1-3 already had their one pass and stay at needs-triage; 4-7 are fresh.
        seen = {n: issue(number=n, triage_count=1, labels={"needs-triage"}) for n in (1, 2, 3)}
        old_gh, old_fetch = tp.gh, tp.fetch_issue
        tp.gh = lambda *args, **kw: json.dumps(listed)
        tp.fetch_issue = lambda repo, n: seen.get(n) or issue(number=n)
        try:
            self.assertEqual(tp.open_untriaged("o/r", 2), [4, 5])
            self.assertEqual(tp.open_untriaged("o/r", 20), [4, 5, 6, 7])
        finally:
            tp.gh, tp.fetch_issue = old_gh, old_fetch


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
             "remove_labels": [], "assignee": "eduralph", "comment": tp.MARKER + "\nok\n"}
        e.update(over)
        return e

    def test_a_built_plan_passes(self) -> None:
        p = plan(severity="minor", reach="edge", review_priority="P2")
        self.assertEqual(tp.check_plan(asdict(p), CONFIG), p)
        self.assertEqual(tp.check_plan(self.entry(), CONFIG).number, 7)

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
                    self.assertEqual(owner.name, "run_classify")


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

    def test_the_real_prompt_names_every_field(self) -> None:
        text = tp.load_prompt()
        for name in (*tp.TYPES, *tp.FLAGS, *AREAS, "review_priority", "financial_data",
                     "secret_in_issue", "vulnerability_report", "unsure", "missing"):
            with self.subTest(name=name):
                self.assertIn(f"`{name}`", text)


if __name__ == "__main__":
    unittest.main()

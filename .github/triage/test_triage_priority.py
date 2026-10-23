"""Tests for triage_priority.py: everything after the model call, offline.

Run: python -I -m unittest discover -s .github/triage

All financial data below is made up: the IBANs have an invalid check number and the
payees and memos are invented, as the repository's fixtures must be (AGENTS.md).
"""

from __future__ import annotations

import json
import sys
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import triage_priority as tp  # noqa: E402

CONFIG = tp.load_config()
AREAS = tp.area_names(CONFIG)
NO_FLAGS = {f: False for f in tp.FLAGS}


def verdict(**over) -> dict:
    v = {
        "type": "bug", "severity": "critical", "reach": "edge", "areas": ["correlator"],
        "flags": dict(NO_FLAGS), "unsure": False, "missing": "",
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
                self.assertEqual(tp.compute_priority(sev, reach, NO_FLAGS, set())[0], p)

    def test_privacy_lifts_adversarial_major_to_p1(self) -> None:
        prio, base, applied = tp.compute_priority(
            "major", "adversarial", dict(NO_FLAGS, security_or_privacy=True), set())
        self.assertEqual((prio, base), (1, 2))
        self.assertIn("security or privacy", applied[0])

    def test_booking_integrity_lifts_edge_minor_to_p1(self) -> None:
        flags = dict(NO_FLAGS, booking_integrity=True)
        self.assertEqual(tp.compute_priority("minor", "edge", flags, set())[0], 1)

    def test_floor_never_lowers(self) -> None:
        flags = dict(NO_FLAGS, booking_integrity=True)
        prio, _, applied = tp.compute_priority("critical", "common", flags, set())
        self.assertEqual((prio, applied), (0, []))

    def test_unrelated_labels_are_not_floors(self) -> None:
        for label in ("release-gating", "human-run", "build-order"):
            with self.subTest(label=label):
                self.assertEqual(tp.compute_priority("trivial", "common", NO_FLAGS, {label})[0], 3)

    def test_every_flag_has_a_floor(self) -> None:
        self.assertLessEqual(set(tp.FLAGS), set(tp.FLOORS))


class Validate(unittest.TestCase):
    def test_rejects_unknown_values(self) -> None:
        for bad in ({"severity": "blocker"}, {"reach": "rare"}, {"type": "research"},
                    {"areas": ["kernel"]}):
            with self.subTest(bad=bad), self.assertRaises(tp.InvalidVerdict):
                tp.validate(verdict(**bad), AREAS)

    def test_rejects_missing_fields(self) -> None:
        for field in ("flags", "financial_data", "secret_in_issue", "vulnerability_report"):
            v = verdict()
            del v[field]
            with self.subTest(field=field), self.assertRaises(tp.InvalidVerdict):
                tp.validate(v, AREAS)

    def test_at_most_two_areas(self) -> None:
        got = tp.validate(verdict(areas=["correlator", "book", "review"]), AREAS)["areas"]
        self.assertEqual(got, ["correlator", "book"])

    def test_schema_enums_match_config(self) -> None:
        schema = tp.verdict_schema(AREAS)
        self.assertEqual(schema["properties"]["areas"]["items"]["enum"], AREAS)
        self.assertEqual(set(schema["required"]), set(schema["properties"]))

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

    def test_held_back_issue_keeps_the_retry_on_an_edit(self) -> None:
        # An edit that adds a real IBAN to an issue at needs-triage: the hold-back note
        # must reach apply() with retry set, or apply() skips the issue as already triaged.
        edited = issue(body=f"From {self.EXAMPLE}.", labels={"needs-triage"}, triage_count=1)
        with mock.patch.dict(sys.modules, {"anthropic": mock.MagicMock()}), \
                mock.patch.object(tp, "ensure_labels"), \
                mock.patch.object(tp, "fetch_issue", return_value=edited), \
                mock.patch.object(tp, "apply") as applied:
            tp.main(["--issue", "7", "--repo", "o/r", "--retry"])
        applied.assert_called_once()
        self.assertTrue(applied.call_args.kwargs.get("retry"))

    def test_made_up_iban_is_classified(self) -> None:
        self.assertFalse(tp.contains_real_iban("From DE00 1234 5678 9012 3456 78, booked twice."))

    def test_ordinary_text_is_not_an_iban(self) -> None:
        for text in ("PR 12 fixes it", "SHA256 ABCDEF0123456789", "Ausgaben:Lebensmittel 2026"):
            with self.subTest(text=text):
                self.assertFalse(tp.contains_real_iban(text))

    def test_held_back_plan_asks_for_synthetic_data_and_classifies_nothing(self) -> None:
        p = tp.held_back_plan()
        self.assertEqual(p.add_labels, ["needs-triage"])
        self.assertIn("not sent to the model", p.comment)
        self.assertTrue(p.comment.startswith(tp.MARKER))


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

    def test_fresh_issue_is_triaged(self) -> None:
        self.assertIsNone(tp.skip_reason(issue()))


class Backfill(unittest.TestCase):
    """The back-fill limit counts only issues that will be triaged (Codex P1 on #944)."""

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
        self.assertEqual(p.add_labels,
                         ["bug", "area:correlator", "sev:critical", "reach:edge", "priority:P1"])
        self.assertEqual(p.assignee, "eduralph")
        self.assertTrue(p.comment.startswith(tp.MARKER))
        self.assertIn("critical × edge is P1", p.comment)

    def test_label_descriptions_fit_github_limit(self) -> None:
        for group in ("severity", "reach", "area", "priority", "other"):
            for name, spec in CONFIG[group].items():
                with self.subTest(label=name):
                    self.assertLessEqual(len(spec["description"]), 100)

    def test_does_not_clash_with_existing_labels(self) -> None:
        mine = {n for g in ("severity", "reach", "area", "priority", "other") for n in CONFIG[g]}
        self.assertFalse(mine & {"build-order", "no-code", "spike", "human-run", "new"})

    def test_every_label_it_adds_exists_in_config(self) -> None:
        known = {n for g in ("severity", "reach", "area", "priority", "other") for n in CONFIG[g]}
        known |= set(tp.TYPES)
        p = plan(i=issue(), flags=dict(NO_FLAGS, booking_integrity=True), areas=["book", "review"])
        self.assertLessEqual(set(p.add_labels), known)

    def test_keeps_existing_type_and_assignee(self) -> None:
        p = plan(i=issue(labels={"enhancement"}, assignees=["someone"]))
        self.assertNotIn("bug", p.add_labels)
        self.assertIsNone(p.assignee)
        self.assertIn("It reads more like bug", p.comment)

    def test_no_type_note_when_the_label_agrees(self) -> None:
        self.assertNotIn("reads more like", plan(i=issue(labels={"bug"})).comment)

    def test_unsure_sets_needs_triage_and_no_priority(self) -> None:
        p = plan(unsure=True, missing="Whether the book is XML or SQL.")
        self.assertIn("needs-triage", p.add_labels)
        self.assertFalse(any(l.startswith(("priority:", "sev:", "reach:")) for l in p.add_labels))

    def test_override_is_explained(self) -> None:
        p = plan(severity="minor", reach="edge", flags=dict(NO_FLAGS, booking_integrity=True))
        self.assertIn("priority:P1", p.add_labels)
        self.assertIn("Raised by: booking-integrity bug", p.comment)

    def test_vulnerability_report_gets_the_security_floor(self) -> None:
        p = plan(severity="trivial", reach="adversarial", vulnerability_report=True)
        self.assertIn("priority:P1", p.add_labels)
        self.assertIn("security or privacy bug", p.comment)

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

    def test_never_touches_the_milestone(self) -> None:
        self.assertFalse(hasattr(plan(), "milestone"))

    def test_input_is_capped_and_says_so(self) -> None:
        text, truncated = tp.issue_input(issue(body="x" * (tp.MAX_BODY + 50)))
        self.assertTrue(truncated)
        self.assertIn("cut at", text)
        self.assertLess(len(text), tp.MAX_BODY + tp.MAX_TITLE + 200)

    def test_unclassified_plan(self) -> None:
        p = tp.unclassified_plan(issue(), "the model declined to classify it", model="m", usage="u")
        self.assertEqual(p.add_labels, ["needs-triage"])
        self.assertIn(tp.MARKER, p.comment)


if __name__ == "__main__":
    unittest.main()

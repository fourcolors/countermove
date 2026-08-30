"""Stdlib tests for slice S5 company bootstrap and move parsing."""

import copy
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from bootstrap import (
    ACME_SITE_URL,
    DEFAULT_ELASTICITY,
    AcmeMirrorClient,
    CsvMergeError,
    Rejection,
    draft_company,
    merge_csv,
    parse_move,
)
from contracts.test_contracts import load as load_contract
from contracts.test_contracts import validate
from orchestrator import SessionStore, ToolRouter, new_session

ROOT = Path(__file__).resolve().parent
COMPANY_FIXTURE = ROOT / "contracts" / "fixtures" / "company.json"
MOVE_FIXTURE = ROOT / "contracts" / "fixtures" / "move.json"
ACME_MIRROR = ROOT / "mirrors" / "acme-stay.html"
DEMO_SENTENCE = "Raise Pro from $49 to $59"
DEMO_SENTENCE_WITH_DATE = (
    "Raise Pro from $49 to $59 and email customers next Monday"
)


def load_company():
    with COMPANY_FIXTURE.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_move():
    with MOVE_FIXTURE.open(encoding="utf-8") as handle:
        return json.load(handle)


class TestParseMove(unittest.TestCase):
    def test_demo_sentence_matches_move_fixture(self):
        move = parse_move(
            DEMO_SENTENCE,
            load_company(),
            today=date(2026, 8, 29),
        )
        self.assertEqual(move, load_move())
        self.assertEqual(move["plan"], "pro")
        self.assertEqual(move["from"], 49)
        self.assertEqual(move["to"], 59)
        self.assertEqual(move["action"], "open_pr")
        self.assertEqual(move["effective"], "2026-09-07")

    def test_demo_sentence_with_next_monday_from_fixed_today(self):
        move = parse_move(
            DEMO_SENTENCE_WITH_DATE,
            load_company(),
            today=date(2026, 9, 1),
        )
        self.assertEqual(move["plan"], "pro")
        self.assertEqual(move["from"], 49)
        self.assertEqual(move["to"], 59)
        self.assertEqual(move["action"], "open_pr")
        self.assertEqual(move["effective"], "2026-09-07")

    def test_next_monday_from_a_saturday_is_two_days_later(self):
        move = parse_move(
            DEMO_SENTENCE_WITH_DATE,
            load_company(),
            today=date(2026, 8, 29),
        )
        self.assertEqual(move["effective"], "2026-08-31")

    def test_next_monday_from_a_monday_is_the_following_week(self):
        move = parse_move(
            DEMO_SENTENCE_WITH_DATE,
            load_company(),
            today=date(2026, 8, 31),
        )
        self.assertEqual(move["effective"], "2026-09-07")

    def test_default_effective_is_today_plus_nine_days(self):
        move = parse_move(
            DEMO_SENTENCE,
            load_company(),
            today=date(2026, 8, 20),
        )
        self.assertEqual(move["effective"], "2026-08-29")

    def test_question_is_rejected_and_does_not_touch_a_tree(self):
        company = load_company()
        tree = {"nodes": [{"id": "root", "children": ["a"]}]}
        snapshot_company = copy.deepcopy(company)
        snapshot_tree = copy.deepcopy(tree)
        result = parse_move("Should I raise prices?", company)
        self.assertIsInstance(result, Rejection)
        self.assertEqual(result.kind, "question")
        self.assertIn("specific", result.reply.lower())
        self.assertNotIn("tree", result.reply.lower())
        self.assertEqual(company, snapshot_company)
        self.assertEqual(tree, snapshot_tree)

    def test_out_of_scope_is_rejected_and_does_not_touch_a_tree(self):
        company = load_company()
        tree = {"nodes": [{"id": "root"}]}
        snapshot_company = copy.deepcopy(company)
        snapshot_tree = copy.deepcopy(tree)
        result = parse_move("Launch a new onboarding flow", company)
        self.assertIsInstance(result, Rejection)
        self.assertEqual(result.kind, "out_of_scope")
        self.assertIn("price", result.reply.lower())
        self.assertEqual(company, snapshot_company)
        self.assertEqual(tree, snapshot_tree)

    def test_unknown_plan_is_not_guessed(self):
        result = parse_move(
            "Raise Enterprise from $99 to $129",
            load_company(),
            today=date(2026, 8, 29),
        )
        self.assertIsInstance(result, Rejection)
        self.assertEqual(result.kind, "unknown_plan")
        self.assertIn("not on the company", result.reply.lower())
        self.assertNotIn("enterprise", [plan["id"] for plan in load_company()["plans"]])


class TestDraftCompany(unittest.TestCase):
    def test_draft_validates_against_company_schema(self):
        session = new_session()
        router = ToolRouter(session)
        company = draft_company(
            ACME_SITE_URL,
            AcmeMirrorClient(),
            router,
            session,
        )
        schema = load_contract("company.schema.json")
        self.assertEqual(validate(company, schema), [])
        self.assertEqual(company["name"], "Acme Stay")
        self.assertEqual(len(company["plans"]), 1)
        self.assertEqual(company["plans"][0]["id"], "pro")
        self.assertEqual(company["plans"][0]["price"], 49)
        self.assertEqual(
            [item["id"] for item in company["plans"][0]["segments"]],
            ["smb", "mid"],
        )
        self.assertEqual(
            [item["name"] for item in company["competitors"]],
            ["Rival A", "Rival B", "Rival C"],
        )
        self.assertEqual(
            [item["price"] for item in company["competitors"]],
            [45, 52, 47],
        )

    def test_missing_elasticity_gets_labeled_b2b_default(self):
        session = new_session()
        company = draft_company(
            ACME_SITE_URL,
            AcmeMirrorClient(),
            ToolRouter(session),
            session,
        )
        for segment in company["plans"][0]["segments"]:
            self.assertEqual(segment["elasticity"], DEFAULT_ELASTICITY)
            self.assertIs(segment["assumed"], True)
            self.assertEqual(segment["cross_elasticity"], 0.4)
        html = ACME_MIRROR.read_text(encoding="utf-8")
        self.assertNotIn("elasticity", html.lower())
        self.assertNotIn("-0.9", html)

    def test_scrape_goes_through_the_router_and_is_traced_in_plain_language(self):
        events = []
        original = ToolRouter.call

        def tracking_call(self, name, **kwargs):
            events.append(("router", name, kwargs.get("url")))
            return original(self, name, **kwargs)

        ToolRouter.call = tracking_call
        try:
            session = new_session()
            draft_company(
                ACME_SITE_URL,
                AcmeMirrorClient(),
                ToolRouter(session),
                session,
            )
        finally:
            ToolRouter.call = original

        scrapes = [
            event
            for event in events
            if event[0] == "router" and event[1] == "brightdata.scrape_as_markdown"
        ]
        self.assertEqual(len(scrapes), 1)
        self.assertEqual(scrapes[0][2], ACME_SITE_URL)

        texts = " ".join(event["text"].lower() for event in session["trace"])
        self.assertIn("company website", texts)
        self.assertIn("pro", texts)
        self.assertIn("assumed, not measured", texts)
        self.assertIn("competitors", texts)
        self.assertNotIn("elasticity", texts)
        self.assertNotIn("yaml", texts)

        with self.assertRaises(TypeError):
            draft_company(ACME_SITE_URL, AcmeMirrorClient(), object(), new_session())

    def test_corrected_value_survives_session_store_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = new_session()
            company = draft_company(
                ACME_SITE_URL,
                AcmeMirrorClient(),
                ToolRouter(session),
                session,
            )
            company["plans"][0]["price"] = 51
            session["company"] = company
            store = SessionStore(tmp)
            store.save(session)
            loaded = store.load()
            self.assertEqual(loaded["company"]["plans"][0]["price"], 51)
            self.assertNotEqual(loaded["company"]["plans"][0]["price"], 49)
            self.assertEqual(loaded["company"]["name"], "Acme Stay")


class TestMergeCsv(unittest.TestCase):
    def test_matching_rows_update_in_place_and_unmatched_are_surfaced(self):
        company = load_company()
        smb = company["plans"][0]["segments"][0]
        self.assertEqual(smb["id"], "smb")
        self.assertEqual(smb["customers"], 300)
        csv_text = (
            "segment,customers,monthly_churn\n"
            "smb,310,0.05\n"
            "enterprise,10,0.01\n"
        )
        unmatched = merge_csv(company, csv_text)
        self.assertIs(company["plans"][0]["segments"][0], smb)
        self.assertEqual(smb["customers"], 310)
        self.assertEqual(smb["monthly_churn"], 0.05)
        self.assertEqual(company["plans"][0]["segments"][1]["customers"], 120)
        self.assertEqual(
            unmatched,
            [{"segment": "enterprise", "customers": 10, "monthly_churn": 0.01}],
        )

    def test_malformed_rows_are_rejected_loudly_and_company_is_unchanged(self):
        company = load_company()
        snapshot = copy.deepcopy(company)
        csv_text = (
            "segment,customers,monthly_churn\n"
            "smb,many,0.04\n"
        )
        with self.assertRaises(CsvMergeError) as ctx:
            merge_csv(company, csv_text)
        message = str(ctx.exception).lower()
        self.assertIn("rejected", message)
        self.assertIn("customers", message)
        self.assertEqual(company, snapshot)

    def test_missing_columns_are_rejected(self):
        company = load_company()
        with self.assertRaises(CsvMergeError) as ctx:
            merge_csv(company, "segment,customers\nsmb,300\n")
        self.assertIn("monthly_churn", str(ctx.exception))

    def test_case_insensitive_segment_match(self):
        company = load_company()
        unmatched = merge_csv(
            company,
            "segment,customers,monthly_churn\nSMB,301,0.03\n",
        )
        self.assertEqual(unmatched, [])
        self.assertEqual(company["plans"][0]["segments"][0]["customers"], 301)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""S8 session restore and watch-trigger tests."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from flow.restore import previous_decision, restore
from flow.watch import check_watch_trigger
from gather.client import MirrorScrapeClient
from orchestrator import SessionStore, ToolRouter, emit, new_session

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "contracts" / "fixtures"
MIRRORS = ROOT / "mirrors"

DENY_REASON = "Not now - occupancy is still climbing."
RIVAL_A_URL = "https://rival-a.example/pricing"


def load_json(name):
    with (FIXTURES / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def canon(obj):
    """Stable UTF-8 JSON bytes for equality checks."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def scores_from_tree(tree):
    out = {}
    for node in tree.get("nodes") or []:
        if "score" in node and "id" in node:
            out[node["id"]] = node["score"]
    return out


def make_denied_session():
    """Scored tree, a denied decision on plan pro, and a stored watch trigger."""
    session = new_session()
    session["company"] = load_json("company.json")
    session["move"] = load_json("move.json")
    session["tree"] = load_json("tree.json")
    recommendation = load_json("recommendation.json")
    session["decisions"] = [
        {
            "plan": "pro",
            "status": "denied",
            "reason": DENY_REASON,
            "deny_reason": DENY_REASON,
            "action": "open_pr",
            "from": 49,
            "to": 59,
            "watch_trigger": recommendation["watch_trigger"],
            "winning_branch_id": recommendation["path_id"],
            "root_hash": session["tree"]["root_hash"],
        }
    ]
    emit(
        session,
        "orchestrator",
        "did",
        "saved the denial and the watch trigger",
    )
    return session


def write_rival_a_price(mirrors_dir, price):
    page = Path(mirrors_dir) / "rival-a.html"
    text = page.read_text(encoding="utf-8")
    page.write_text(text.replace("$45", "$%s" % price), encoding="utf-8")


class RecordingRouter(ToolRouter):
    """ToolRouter that records every dispatched name."""

    def __init__(self, session):
        super().__init__(session)
        self.calls = []

    def call(self, name, **kwargs):
        self.calls.append(name)
        return super().call(name, **kwargs)


class TestRestore(unittest.TestCase):
    def test_reload_restores_identical_tree_scores_and_decision(self):
        session = make_denied_session()
        self.assertTrue(scores_from_tree(session["tree"]))
        self.assertEqual(session["decisions"][0]["status"], "denied")
        self.assertTrue(session["decisions"][0]["watch_trigger"])

        with tempfile.TemporaryDirectory() as tmp:
            SessionStore(tmp).save(session)
            restored = restore(tmp)

        self.assertEqual(canon(session["tree"]), canon(restored["tree"]))
        self.assertEqual(
            canon(scores_from_tree(session["tree"])),
            canon(scores_from_tree(restored["tree"])),
        )
        self.assertEqual(canon(session["decisions"]), canon(restored["decisions"]))
        self.assertEqual(canon(session["trace"]), canon(restored["trace"]))
        self.assertEqual(restored["company"]["name"], "Acme Stay")
        self.assertEqual(restored["move"]["plan"], "pro")

    def test_previous_decision_surfaces_denial_and_reason(self):
        session = make_denied_session()
        with tempfile.TemporaryDirectory() as tmp:
            SessionStore(tmp).save(session)
            restored = restore(tmp)

        prev = previous_decision(restored, "pro")
        self.assertIsNotNone(prev)
        self.assertEqual(prev["status"], "denied")
        self.assertEqual(prev["reason"], DENY_REASON)
        self.assertEqual(prev["plan"], "pro")
        self.assertEqual(prev["watch_trigger"]["competitor"], "Rival A")
        self.assertEqual(prev["watch_trigger"]["threshold"], 42)

        self.assertIsNone(previous_decision(restored, "enterprise"))

    def test_previous_decision_returns_the_last_matching_plan(self):
        session = make_denied_session()
        session["decisions"].append(
            {
                "plan": "pro",
                "status": "denied",
                "reason": "Still too soon.",
                "watch_trigger": session["decisions"][0]["watch_trigger"],
            }
        )
        prev = previous_decision(session, "pro")
        self.assertEqual(prev["reason"], "Still too soon.")

    def test_previous_decision_none_when_empty(self):
        self.assertIsNone(previous_decision(new_session(), "pro"))

    def test_previous_decision_fills_reason_from_deny_reason(self):
        session = make_denied_session()
        stored = session["decisions"][0]
        stored.pop("reason")
        prev = previous_decision(session, "pro")
        self.assertEqual(prev["reason"], DENY_REASON)
        self.assertNotIn("reason", stored)

    def test_previous_decision_matches_nested_move_plan(self):
        session = new_session()
        session["decisions"] = [
            {
                "move": {"plan": "pro"},
                "status": "denied",
                "reason": DENY_REASON,
            }
        ]
        prev = previous_decision(session, "pro")
        self.assertEqual(prev["reason"], DENY_REASON)
        self.assertEqual(prev["status"], "denied")

    def test_restore_missing_session_is_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            restored = restore(tmp)
        self.assertEqual(restored["tree"], None)
        self.assertEqual(restored["decisions"], [])
        self.assertEqual(restored["trace"], [])


class TestWatchTrigger(unittest.TestCase):
    def _new_run_from(self, saved):
        run = new_session()
        run["company"] = saved["company"]
        run["decisions"] = saved["decisions"]
        return run

    def _check_with_price(self, price, saved=None):
        if saved is None:
            saved = make_denied_session()
        with tempfile.TemporaryDirectory() as tmp:
            mirrors_dir = Path(tmp) / "mirrors"
            shutil.copytree(MIRRORS, mirrors_dir)
            write_rival_a_price(mirrors_dir, price)
            run = self._new_run_from(saved)
            router = RecordingRouter(run)
            result = check_watch_trigger(
                run,
                MirrorScrapeClient(mirrors_dir=mirrors_dir),
                router,
            )
            return result, run, router

    def test_mutated_page_below_threshold_fires(self):
        result, run, router = self._check_with_price(39)
        self.assertTrue(result["fired"])
        self.assertEqual(result["observed_price"], 39)
        self.assertEqual(result["trigger"]["threshold"], 42)
        self.assertEqual(result["trigger"]["competitor"], "Rival A")
        self.assertIn("brightdata.scrape_as_markdown", router.calls)
        text = run["trace"][0]["text"].lower()
        self.assertIn("rival a", text)
        self.assertIn("below", text)
        self.assertEqual(run["trace"][0]["detail"]["fired"], True)
        self.assertEqual(run["trace"][0]["detail"]["url"], RIVAL_A_URL)

    def test_mutated_page_above_threshold_does_not_fire(self):
        result, run, router = self._check_with_price(50)
        self.assertFalse(result["fired"])
        self.assertEqual(result["observed_price"], 50)
        self.assertIn("brightdata.scrape_as_markdown", router.calls)
        text = run["trace"][0]["text"].lower()
        self.assertIn("rival a", text)
        self.assertIn("still", text)
        self.assertEqual(run["trace"][0]["detail"]["fired"], False)

    def test_price_at_threshold_does_not_fire(self):
        result, run, _router = self._check_with_price(42)
        self.assertFalse(result["fired"])
        self.assertEqual(result["observed_price"], 42)
        text = run["trace"][0]["text"].lower()
        self.assertIn("still", text)

    def test_watch_event_is_first_on_the_new_run(self):
        saved = make_denied_session()
        self.assertTrue(saved["trace"], "prior run must already have trace events")

        with tempfile.TemporaryDirectory() as tmp:
            SessionStore(tmp).save(saved)
            restored = restore(tmp)

        run = self._new_run_from(restored)
        router = RecordingRouter(run)
        result = check_watch_trigger(run, MirrorScrapeClient(), router)
        self.assertFalse(result["fired"])
        self.assertEqual(result["observed_price"], 45)

        emit(run, "orchestrator", "doing", "building the move tree")
        emit(run, "orchestrator", "doing", "scoring each path")

        self.assertGreaterEqual(len(run["trace"]), 3)
        first = run["trace"][0]
        self.assertEqual(first["actor"], "orchestrator")
        self.assertEqual(first["column"], "did")
        self.assertEqual(first["tool"], "brightdata.scrape_as_markdown")
        first_text = first["text"].lower()
        self.assertIn("rival a", first_text)
        self.assertIn("recommendation", first_text)
        self.assertNotIn("tree", first_text)
        self.assertEqual(run["trace"][1]["text"], "building the move tree")
        self.assertEqual(run["trace"][2]["text"], "scoring each path")

        self.assertNotEqual(canon(restored["trace"]), canon(run["trace"]))

    def test_scrape_goes_through_the_router_not_around_it(self):
        saved = make_denied_session()
        run = self._new_run_from(saved)
        router = RecordingRouter(run)
        check_watch_trigger(run, MirrorScrapeClient(), router)
        self.assertEqual(router.calls, ["brightdata.scrape_as_markdown"])
        self.assertEqual(run["trace"][0]["tool"], "brightdata.scrape_as_markdown")

    def test_missing_trigger_is_a_quiet_no_op(self):
        run = new_session()
        run["company"] = load_json("company.json")
        router = RecordingRouter(run)
        result = check_watch_trigger(run, MirrorScrapeClient(), router)
        self.assertEqual(
            result,
            {"fired": False, "observed_price": None, "trigger": None},
        )
        self.assertEqual(router.calls, [])
        self.assertEqual(run["trace"], [])

    def test_malformed_trigger_is_a_quiet_no_op(self):
        run = new_session()
        run["company"] = load_json("company.json")
        run["decisions"] = [{"plan": "pro", "watch_trigger": "Rival A below 42"}]
        router = RecordingRouter(run)
        result = check_watch_trigger(run, MirrorScrapeClient(), router)
        self.assertEqual(
            result,
            {"fired": False, "observed_price": None, "trigger": None},
        )
        self.assertEqual(router.calls, [])
        self.assertEqual(run["trace"], [])

    def test_router_is_required(self):
        run = make_denied_session()
        with self.assertRaises(TypeError):
            check_watch_trigger(run, MirrorScrapeClient(), router=None)


if __name__ == "__main__":
    unittest.main()

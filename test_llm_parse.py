"""Stdlib tests for LLM-backed move normalization.

Every case injects a fake runner. The real grok CLI is never invoked.
"""

import json
import subprocess
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from bootstrap.llm_parse import normalize_move
from bootstrap.move_parse import Rejection, parse_move

ROOT = Path(__file__).resolve().parent
COMPANY_FIXTURE = ROOT / "contracts" / "fixtures" / "company.json"
TYPO_SENTENCE = "rais the price from pro to $59"
CANONICAL = "Raise Pro from $49 to $59"
LYING_CANONICAL = "Raise Pro from $59 to $49"


def load_company():
    with COMPANY_FIXTURE.open(encoding="utf-8") as handle:
        return json.load(handle)


class TestNormalizeMove(unittest.TestCase):
    def test_typo_sentence_becomes_an_executable_move(self):
        company = load_company()
        seen = {}

        def runner(prompt):
            seen["prompt"] = prompt
            return CANONICAL

        canonical = normalize_move(TYPO_SENTENCE, company, runner=runner)
        self.assertEqual(canonical, CANONICAL)
        self.assertIn("pro", seen["prompt"].lower())
        self.assertIn("49", seen["prompt"])
        self.assertIn(TYPO_SENTENCE, seen["prompt"])
        self.assertIn("EXACTLY one line", seen["prompt"])
        move = parse_move(canonical, company, today=date(2026, 8, 29))
        self.assertEqual(move["plan"], "pro")
        self.assertEqual(move["from"], 49)
        self.assertEqual(move["to"], 59)
        self.assertEqual(move["action"], "open_pr")
        self.assertEqual(move["effective"], "2026-09-07")

    def test_lying_runner_canonical_is_still_rejected_by_strict_validation(self):
        company = load_company()

        def runner(prompt):
            return LYING_CANONICAL

        canonical = normalize_move("drop Pro to forty nine", company, runner=runner)
        self.assertEqual(canonical, LYING_CANONICAL)
        result = parse_move(canonical, company, today=date(2026, 8, 29))
        self.assertIsInstance(result, Rejection)
        self.assertEqual(result.kind, "invalid_price")
        self.assertNotEqual(getattr(result, "action", None), "open_pr")

    def test_reply_line_is_a_friendly_rejection(self):
        company = load_company()
        friendly = (
            "I can only handle a price change on one plan, like Raise Pro "
            "from $49 to $59. Launching a new onboarding flow is not supported."
        )

        def runner(prompt):
            return "REPLY: " + friendly

        result = normalize_move(
            "Launch a new onboarding flow", company, runner=runner
        )
        self.assertIsInstance(result, Rejection)
        self.assertEqual(result.kind, "llm_reply")
        self.assertEqual(result.reply, friendly)
        self.assertFalse(result.reply.startswith("REPLY:"))

    def test_runner_raising_is_llm_unavailable_preserving_strict_reply(self):
        company = load_company()
        strict = parse_move(TYPO_SENTENCE, company)

        def runner(prompt):
            raise RuntimeError("cli down")

        result = normalize_move(TYPO_SENTENCE, company, runner=runner)
        self.assertIsInstance(result, Rejection)
        self.assertEqual(result.kind, "llm_unavailable")
        self.assertEqual(result.reply, strict.reply)
        self.assertTrue(result.reply)

    def test_timeout_is_llm_unavailable_preserving_strict_reply(self):
        company = load_company()
        strict = parse_move(TYPO_SENTENCE, company)

        def runner(prompt):
            raise subprocess.TimeoutExpired(cmd=["grok"], timeout=45)

        result = normalize_move(TYPO_SENTENCE, company, runner=runner)
        self.assertIsInstance(result, Rejection)
        self.assertEqual(result.kind, "llm_unavailable")
        self.assertEqual(result.reply, strict.reply)

    @mock.patch("bootstrap.llm_parse.subprocess.run")
    def test_injected_runner_does_not_call_subprocess(self, run):
        def runner(prompt):
            return CANONICAL

        normalize_move(TYPO_SENTENCE, load_company(), runner=runner)
        run.assert_not_called()

    @mock.patch("bootstrap.llm_parse.subprocess.run")
    def test_default_runner_calls_grok_no_leader(self, run):
        run.return_value = mock.Mock(returncode=0, stdout=CANONICAL + "\n", stderr="")
        result = normalize_move(TYPO_SENTENCE, load_company())
        self.assertEqual(result, CANONICAL)
        args, kwargs = run.call_args
        self.assertEqual(args[0][0], "grok")
        self.assertEqual(args[0][1], "--no-leader")
        self.assertEqual(args[0][2], "-p")
        self.assertIn(TYPO_SENTENCE, args[0][3])
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(kwargs["timeout"], 45)


class TestRunFailurePayload(unittest.TestCase):
    def test_error_field_is_only_the_friendly_reply(self):
        from serve_demo import payload_for_run

        reply = "Only a price change on one plan is supported today."
        payload = payload_for_run(
            Rejection("llm_reply", reply),
            "move rejected: llm_reply - " + reply,
        )
        self.assertFalse(payload["ok"])
        self.assertIsNone(payload["result"])
        self.assertEqual(payload["error"], reply)
        self.assertEqual(payload["reply"], reply)
        self.assertNotIn("move rejected", payload["error"])
        self.assertNotIn("llm_reply", payload["error"])

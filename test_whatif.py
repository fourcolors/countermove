#!/usr/bin/env python3
"""S9 what-if tests: grow one branch, score only that branch, rehash the path."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import provenance
import score
from tree.build import build_tree
from tree.responses import COUNTER_CHOICES, FixtureResponseProvider, RESPONSE_CHOICES
from tree.whatif import OVERRIDE_NOTE, grow_branch, infer_choice


FIXTURES = ROOT / "contracts" / "fixtures"
COMPANY = json.loads((FIXTURES / "company.json").read_text(encoding="utf-8"))
MOVE = json.loads((FIXTURES / "move.json").read_text(encoding="utf-8"))
PERSONA_CARDS = json.loads((FIXTURES / "persona_cards.json").read_text(encoding="utf-8"))

RIVAL_A = "Rival A"
CUT_TO = 39.0


def _provider():
    return FixtureResponseProvider(PERSONA_CARDS)


def _by_id(tree):
    return {node["id"]: node for node in tree["nodes"]}


def _hash_map(tree):
    return {node["id"]: node["hash"] for node in tree["nodes"]}


def _fresh_tree():
    return build_tree(COMPANY, MOVE, _provider())


class ScoreLeafSandbox:
    """Sandbox stand-in that runs score.score_leaf and records each call."""

    def __init__(self):
        self.calls = []

    def run(self, script_path, input_json):
        self.calls.append((script_path, input_json))
        return score.score_leaf(input_json["company"], input_json["move"], input_json["leaf"])


class InferChoiceTests(unittest.TestCase):
    def test_cut_below_your_new_price_is_undercut(self):
        self.assertEqual(infer_choice(39.0, 59.0, 45.0), "undercut")

    def test_exact_your_new_price_is_match(self):
        self.assertEqual(infer_choice(59.0, 59.0, 45.0), "match")

    def test_exact_current_price_is_ignore(self):
        self.assertEqual(infer_choice(45.0, 59.0, 45.0), "ignore")

    def test_above_your_new_price_is_raise(self):
        self.assertEqual(infer_choice(70.0, 59.0, 45.0), "raise")


class GrowBranchTests(unittest.TestCase):
    def setUp(self):
        self.tree = _fresh_tree()
        self.before_hashes = _hash_map(self.tree)
        self.before_ids = set(self.before_hashes)
        self.before_nodes = copy.deepcopy(_by_id(self.tree))
        self.result = grow_branch(self.tree, COMPANY, MOVE, RIVAL_A, CUT_TO)
        self.nodes = _by_id(self.tree)
        self.after_hashes = _hash_map(self.tree)
        self.new_ids = [node_id for node_id in self.after_hashes if node_id not in self.before_ids]

    def test_grows_exactly_one_response_and_three_scored_leaves(self):
        new_nodes = [self.nodes[node_id] for node_id in self.new_ids]
        responses = [node for node in new_nodes if node["actor"] == "competitor"]
        leaves = [node for node in new_nodes if node["choice"] in COUNTER_CHOICES]
        self.assertEqual(len(responses), 1, self.new_ids)
        self.assertEqual(len(leaves), 3, self.new_ids)
        self.assertEqual(len(self.new_ids), 4)
        self.assertEqual(set(self.result["new_node_ids"]), set(self.new_ids))

        response = responses[0]
        self.assertEqual(response["choice"], "undercut")
        self.assertAlmostEqual(response["price_before"], 45.0)
        self.assertAlmostEqual(response["price_after"], CUT_TO)
        self.assertEqual(response["parent"], "root")
        self.assertEqual(sorted(response["children"]), sorted(leaf["id"] for leaf in leaves))
        self.assertIn(response["id"], self.nodes["root"]["children"])

        for leaf in leaves:
            self.assertEqual(leaf["parent"], response["id"])
            self.assertEqual(leaf["actor"], "you")
            band = leaf["score"]
            for key in ("low", "mid", "high"):
                self.assertIsInstance(band[key], (int, float), leaf["id"])
            for key in ("low_pct", "mid_pct", "high_pct"):
                value = band[key]
                self.assertTrue(isinstance(value, (int, float)) or value == "n/a", leaf["id"])
            self.assertIn("c_prime_convention", leaf["assumptions"])
            self.assertAlmostEqual(leaf["assumptions"]["competitor_average_after"], 46.0)

        original_responses = [
            node for node in self.before_nodes.values() if node["actor"] == "competitor"
        ]
        original_leaves = [
            node for node in self.before_nodes.values() if node.get("choice") in COUNTER_CHOICES
        ]
        self.assertEqual(len(original_responses), 12)
        self.assertEqual(len(original_leaves), 36)
        now_responses = [node for node in self.tree["nodes"] if node["actor"] == "competitor"]
        now_leaves = [node for node in self.tree["nodes"] if node.get("choice") in COUNTER_CHOICES]
        self.assertEqual(len(now_responses), 13)
        self.assertEqual(len(now_leaves), 39)

    def test_override_assumption_marks_the_5pct_default(self):
        response_id = next(
            node_id for node_id in self.result["new_node_ids"]
            if self.nodes[node_id]["actor"] == "competitor"
        )
        assumptions = self.nodes[response_id]["assumptions"]
        self.assertEqual(assumptions["competitor"], RIVAL_A)
        self.assertTrue(assumptions["overrides_default_5pct"])
        self.assertAlmostEqual(assumptions["price_after_override"], CUT_TO)
        self.assertAlmostEqual(assumptions["default_price_after"], float(MOVE["to"]) * 0.95)
        self.assertIn("5%", assumptions["override_note"])
        self.assertEqual(assumptions["override_note"], OVERRIDE_NOTE)
        self.assertIn("5%", self.nodes[response_id]["reasoning"])
        self.assertNotAlmostEqual(assumptions["default_price_after"], CUT_TO)

    def test_verify_tree_ok_after_grow(self):
        result = provenance.verify_tree(self.tree)
        self.assertTrue(result["ok"], result["mismatches"])
        self.assertEqual(self.tree["root_hash"], self.nodes["root"]["hash"])

    def test_off_path_hashes_content_and_scores_unchanged(self):
        changed = set(self.result["changed_hash_ids"])
        off_path = [node_id for node_id in self.before_hashes if node_id not in changed]
        self.assertTrue(off_path)
        for node_id in off_path:
            self.assertEqual(self.after_hashes[node_id], self.before_hashes[node_id], node_id)
            before = self.before_nodes[node_id]
            after = self.nodes[node_id]
            self.assertEqual(after["choice"], before["choice"], node_id)
            self.assertEqual(after["price_before"], before["price_before"], node_id)
            self.assertEqual(after["price_after"], before["price_after"], node_id)
            self.assertEqual(after["reasoning"], before["reasoning"], node_id)
            self.assertEqual(after["score"], before["score"], node_id)
            self.assertEqual(after["assumptions"], before["assumptions"], node_id)

        for choice in RESPONSE_CHOICES:
            sibling_id = f"resp-rival-a-{choice}"
            self.assertIn(sibling_id, off_path)
            self.assertEqual(self.after_hashes[sibling_id], self.before_hashes[sibling_id])
            for counter in COUNTER_CHOICES:
                leaf_id = f"leaf-rival-a-{choice}-{counter}"
                self.assertEqual(self.after_hashes[leaf_id], self.before_hashes[leaf_id])

        cousin = "leaf-rival-b-ignore-hold"
        self.assertEqual(self.after_hashes[cousin], self.before_hashes[cousin])

    def test_ancestors_and_root_hashes_change(self):
        response_id = next(
            node_id for node_id in self.result["new_node_ids"]
            if self.nodes[node_id]["actor"] == "competitor"
        )
        self.assertIn("root", self.result["changed_hash_ids"])
        self.assertIn(response_id, self.result["changed_hash_ids"])
        self.assertNotEqual(self.after_hashes["root"], self.before_hashes["root"])
        self.assertEqual(self.tree["root_hash"], self.after_hashes["root"])
        for leaf_id in self.nodes[response_id]["children"]:
            self.assertIn(leaf_id, self.result["changed_hash_ids"])
            self.assertIn(leaf_id, self.result["new_node_ids"])


class GrowBranchErrorTests(unittest.TestCase):
    def test_unknown_competitor_raises(self):
        tree = _fresh_tree()
        before = _hash_map(tree)
        with self.assertRaises(ValueError) as ctx:
            grow_branch(tree, COMPANY, MOVE, "Rival Z", CUT_TO)
        self.assertIn("Rival Z", str(ctx.exception))
        self.assertIn("unknown", str(ctx.exception).lower())
        self.assertEqual(_hash_map(tree), before)
        self.assertTrue(provenance.verify_tree(tree)["ok"])


class GrowBranchSandboxTests(unittest.TestCase):
    def test_sandbox_scores_only_the_new_branch_leaves(self):
        tree = _fresh_tree()
        sandbox = ScoreLeafSandbox()
        result = grow_branch(tree, COMPANY, MOVE, RIVAL_A, CUT_TO, sandbox=sandbox)
        self.assertEqual(len(sandbox.calls), 3)
        leaf_ids = []
        for script_path, payload in sandbox.calls:
            self.assertEqual(Path(script_path).name, "score.py")
            self.assertEqual(set(payload), {"company", "move", "leaf"})
            leaf = payload["leaf"]
            leaf_ids.append(leaf["id"])
            self.assertEqual(leaf["competitor_response"]["name"], RIVAL_A)
            self.assertAlmostEqual(leaf["competitor_response"]["price_after"], CUT_TO)
            self.assertTrue(leaf["id"].startswith("leaf-rival-a-whatif-"))
        self.assertEqual(len(set(leaf_ids)), 3)
        self.assertEqual(sorted(leaf_ids), sorted(
            node_id for node_id in result["new_node_ids"] if node_id.startswith("leaf-")
        ))
        self.assertTrue(provenance.verify_tree(tree)["ok"])


if __name__ == "__main__":
    unittest.main()

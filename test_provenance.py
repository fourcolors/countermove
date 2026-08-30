import copy
import json
import math
import unittest
from pathlib import Path

from provenance import canonical, node_hash, verify_tree


ROOT = Path(__file__).parent


def load_json(relative_path):
    with (ROOT / relative_path).open(encoding="utf-8") as handle:
        return json.load(handle)


def rehash_tree(tree):
    """Return recomputed hashes without consulting stored node hashes."""
    nodes = {node["id"]: node for node in tree["nodes"]}
    hashes = {}

    def visit(node_id):
        node = nodes[node_id]
        children = {child_id: visit(child_id) for child_id in node["children"]}
        hashes[node_id] = node_hash(node, children)
        return hashes[node_id]

    root_hash = visit(tree["root"])
    return root_hash, hashes


class CanonicalTests(unittest.TestCase):
    def test_all_reference_vectors(self):
        for vector in load_json("contracts/canonical_vectors.json"):
            with self.subTest(vector=vector["name"]):
                self.assertEqual(
                    canonical(vector["input"]),
                    vector["canonical"].encode("utf-8"),
                )

    def test_float_rounding_ties_and_near_zero(self):
        cases = {
            2.3456785: b'{"x":2.345678}',
            2.3456795: b'{"x":2.34568}',
            -0.0: b'{"x":0.0}',
            -0.00000049: b'{"x":0.0}',
            -0.0000005: b'{"x":0.0}',
            -0.00000051: b'{"x":-1e-06}',
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(canonical({"x": value}), expected)

    def test_non_finite_floats_raise(self):
        for value in (math.inf, -math.inf, math.nan):
            with self.subTest(value=value), self.assertRaises(ValueError):
                canonical({"x": value})

    def test_keys_sources_and_segments_are_sorted_without_mutation(self):
        content = {
            "z": 1,
            "sources": ["z.example", "a.example"],
            "plans": [{
                "segments": [{"id": "z", "n": 1}, {"id": "a", "n": 2}],
                "id": "p",
            }],
            "a": {"z": 2, "a": 1},
        }
        original = copy.deepcopy(content)
        self.assertEqual(
            canonical(content),
            b'{"a":{"a":1,"z":2},"plans":[{"id":"p","segments":[{"id":"a","n":2},{"id":"z","n":1}]}],"sources":["a.example","z.example"],"z":1}',
        )
        self.assertEqual(content, original)


class MerkleTests(unittest.TestCase):
    def setUp(self):
        self.tree = load_json("contracts/fixtures/tree.json")

    def test_fixture_recomputes_exact_root(self):
        root_hash, hashes = rehash_tree(self.tree)
        self.assertEqual(root_hash, self.tree["root_hash"])
        for node in self.tree["nodes"]:
            self.assertEqual(hashes[node["id"]], node["hash"], node["id"])
        self.assertEqual(verify_tree(self.tree), {"ok": True, "mismatches": []})

    def test_editing_node_content_changes_root(self):
        original_root, _ = rehash_tree(self.tree)
        changed = copy.deepcopy(self.tree)
        leaf = next(node for node in changed["nodes"] if not node["children"])
        leaf["reasoning"] += " Tampered."
        changed_root, _ = rehash_tree(changed)
        self.assertNotEqual(changed_root, original_root)

    def test_each_content_field_participates_in_node_hash(self):
        node = next(node for node in self.tree["nodes"] if not node["children"])
        baseline = node_hash(node, {})
        replacements = {
            "id": node["id"] + "-edited",
            "parent": node["parent"] + "-edited",
            "actor": "competitor",
            "label": node["label"] + " edited",
            "choice": node["choice"] + "_edited",
            "price_before": node["price_before"] + 1,
            "price_after": node["price_after"] + 1,
            "reasoning": node["reasoning"] + " edited",
            "sources": ["https://new.example/source"],
            "assumptions": {"edited": True},
            "score": {**node["score"], "mid": node["score"]["mid"] + 1},
        }
        for field, replacement in replacements.items():
            with self.subTest(field=field):
                changed = copy.deepcopy(node)
                changed[field] = replacement
                self.assertNotEqual(node_hash(changed, {}), baseline)

    def test_change_rehashes_ancestors_and_no_off_path_node(self):
        _, before = rehash_tree(self.tree)
        changed = copy.deepcopy(self.tree)
        leaf = next(node for node in changed["nodes"] if not node["children"])
        parent_id = leaf["parent"]
        leaf["score"]["mid"] += 0.01
        _, after = rehash_tree(changed)

        changed_ids = {node_id for node_id in before if before[node_id] != after[node_id]}
        self.assertEqual(changed_ids, {leaf["id"], parent_id, changed["root"]})

    def test_child_hashes_are_concatenated_in_child_id_order(self):
        node = {"id": "parent", "children": ["z-child", "a-child"]}
        child_hashes = {"z-child": "f" * 64, "a-child": "0" * 64}
        self.assertEqual(
            node_hash(node, child_hashes),
            node_hash(node, {"a-child": "0" * 64, "z-child": "f" * 64}),
        )


if __name__ == "__main__":
    unittest.main()

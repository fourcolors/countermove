"""Fixture-vs-schema conformance tests for the frozen contracts.

A minimal draft-07 subset validator (type, required, properties, enum,
const, anyOf, allOf+if/then on const, items, pattern, maxItems) - enough
to fail the build on fixture/schema drift without external dependencies.
"""

import json
import re
import unittest
from pathlib import Path

HERE = Path(__file__).parent

TYPES = {
    "object": dict, "array": list, "string": str,
    "boolean": bool, "null": type(None),
}


def _type_ok(value, expected):
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, TYPES[expected])


def validate(value, schema, path="$"):
    errors = []
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_type_ok(value, item) for item in types):
            return [f"{path}: expected {types}, got {type(value).__name__}"]
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in enum")
    if "pattern" in schema and isinstance(value, str):
        if not re.search(schema["pattern"], value):
            errors.append(f"{path}: does not match {schema['pattern']}")
    if "anyOf" in schema:
        branches = [validate(value, sub, path) for sub in schema["anyOf"]]
        if not any(not b for b in branches):
            errors.append(f"{path}: no anyOf branch matched")
    for sub in schema.get("allOf", []):
        if "if" in sub:
            cond = sub["if"].get("properties", {})
            applies = isinstance(value, dict) and all(
                key in value and value[key] == spec.get("const")
                for key, spec in cond.items())
            if applies and "then" in sub:
                errors.extend(validate(value, sub["then"], path))
        else:
            errors.extend(validate(value, sub, path))
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required {key!r}")
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                errors.extend(validate(value[key], sub, f"{path}.{key}"))
    if isinstance(value, list):
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: more than {schema['maxItems']} items")
        if "items" in schema:
            for i, item in enumerate(value):
                errors.extend(validate(item, schema["items"], f"{path}[{i}]"))
    return errors


def load(name):
    return json.loads((HERE / name).read_text())


PAIRS = [
    ("company.schema.json", "fixtures/company.json"),
    ("move.schema.json", "fixtures/move.json"),
    ("score_result.schema.json", "fixtures/score_result.json"),
    ("pending_action.schema.json", "fixtures/pending_action.json"),
    ("recommendation.schema.json", "fixtures/recommendation.json"),
]


class FixtureConformanceTests(unittest.TestCase):
    def test_scalar_fixtures_match_their_schemas(self):
        for schema_name, fixture_name in PAIRS:
            with self.subTest(fixture=fixture_name):
                errors = validate(load(fixture_name), load(schema_name))
                self.assertEqual(errors, [])

    def test_every_trace_event_fixture_conforms(self):
        schema = load("trace_event.schema.json")
        for i, event in enumerate(load("fixtures/trace_events.json")):
            with self.subTest(event=i):
                self.assertEqual(validate(event, schema), [])

    def test_every_persona_card_conforms(self):
        schema = load("persona_card.schema.json")
        for card in load("fixtures/persona_cards.json"):
            with self.subTest(card=card.get("competitor")):
                self.assertEqual(validate(card, schema), [])

    def test_every_tree_node_conforms_including_actor_menus(self):
        schema = load("tree_node.schema.json")
        for node in load("fixtures/tree.json")["nodes"]:
            with self.subTest(node=node["id"]):
                self.assertEqual(validate(node, schema), [])

    def test_actor_conditional_menus_actually_reject(self):
        schema = load("tree_node.schema.json")
        node = dict(load("fixtures/tree.json")["nodes"][0])
        node["actor"] = "competitor"
        node["choice"] = "hold"
        self.assertNotEqual(validate(node, schema), [])


if __name__ == "__main__":
    unittest.main()

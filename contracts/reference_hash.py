#!/usr/bin/env python3
"""Throwaway S0 reference implementation of canonical() and Merkle hashing.

Generates contracts/fixtures/tree.json (depth-two, 3 competitors x 4 responses
x 3 counters = 36 leaves, per-node hashes, root) and contracts/canonical_vectors.json.
S2's provenance.py must reproduce every hash in both files independently.

Pinned spec (countermove.md, Provenance):
- JSON with lexicographically sorted keys, UTF-8, no insignificant whitespace
- floats rounded half-even to 6 decimal places, shortest round-trip decimal form
- negative zero normalized to zero; non-finite values invalid
- sources sorted; segments sorted by id; child hashes concatenated in child-node-id order
- node hash = sha256(canonical(content_without_hash) + concat(child hashes)) hex
"""

import hashlib
import json
import math
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path

HERE = Path(__file__).parent


def canon_number(x):
    if isinstance(x, bool):
        return x
    if isinstance(x, float):
        if not math.isfinite(x):
            raise ValueError("non-finite float is invalid in canonical()")
        q = float(Decimal(repr(x)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN))
        if q == 0.0:
            q = 0.0  # normalizes -0.0
        # repr() of a Python float is the shortest round-trip decimal form
        return q
    return x


def canon_value(v):
    if isinstance(v, dict):
        out = {}
        for k in sorted(v):
            val = v[k]
            if k == "sources" and isinstance(val, list):
                val = sorted(val)
            elif k == "segments" and isinstance(val, list):
                val = sorted(val, key=lambda s: s.get("id", "") if isinstance(s, dict) else "")
            out[k] = canon_value(val)
        return out
    if isinstance(v, list):
        return [canon_value(i) for i in v]
    return canon_number(v)


def canonical(content: dict) -> bytes:
    c = canon_value(content)
    return json.dumps(c, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def node_hash(content: dict, child_hashes: list[str]) -> str:
    payload = canonical(content) + "".join(child_hashes).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


COMPETITORS = [("rival-a", "Rival A", 45.0), ("rival-b", "Rival B", 52.0), ("rival-c", "Rival C", 47.0)]
RESPONSES = {"undercut": lambda p, mine: round(mine * 0.95, 2), "match": lambda p, mine: mine,
             "ignore": lambda p, mine: p, "raise": lambda p, mine: round(p * 1.05, 2)}
COUNTERS = ["hold", "partial_rollback", "annual_discount"]
NEW_PRICE = 59.0


def leaf_content(comp_id, resp, counter, i):
    # Deterministic placeholder bands: stable, schema-valid, not real scores (S1 owns scoring)
    base = round(-2000.0 + i * 137.5, 2)
    return {
        "id": f"leaf-{comp_id}-{resp}-{counter}",
        "parent": f"resp-{comp_id}-{resp}",
        "actor": "you",
        "label": counter,
        "choice": counter,
        "price_before": NEW_PRICE,
        "price_after": NEW_PRICE if counter != "partial_rollback" else round((NEW_PRICE + 49.0) / 2, 2),
        "reasoning": f"Fixture counter {counter} after {resp} by {comp_id}.",
        "sources": [],
        "assumptions": {"c_prime_convention": "mean of all three competitors' price_after; non-responders keep last scraped price"},
        "score": {"low": base, "mid": round(base + 800.0, 2), "high": round(base + 1600.0, 2),
                  "low_pct": -1.4, "mid_pct": -0.2, "high_pct": 1.1},
    }


def build_tree():
    nodes = []
    root_children = []
    i = 0
    for comp_id, comp_name, price in COMPETITORS:
        for resp, price_fn in RESPONSES.items():
            resp_children = []
            for counter in COUNTERS:
                content = leaf_content(comp_id, resp, counter, i)
                i += 1
                h = node_hash(content, [])
                nodes.append({**content, "hash": h, "children": []})
                resp_children.append((content["id"], h))
            resp_children.sort(key=lambda t: t[0])
            content = {
                "id": f"resp-{comp_id}-{resp}", "parent": "root", "actor": "competitor",
                "label": f"{comp_name}: {resp}", "choice": resp,
                "price_before": price, "price_after": price_fn(price, NEW_PRICE),
                "reasoning": f"Fixture response {resp} by {comp_name}.",
                "sources": [f"https://{comp_id}.example/pricing"],
                "assumptions": {}, "score": None,
            }
            h = node_hash(content, [c[1] for c in resp_children])
            nodes.append({**content, "hash": h, "children": [c[0] for c in resp_children]})
            root_children.append((content["id"], h))
    root_children.sort(key=lambda t: t[0])
    content = {"id": "root", "parent": None, "actor": "you", "label": "Raise Pro 49 to 59",
               "choice": "price_change", "price_before": 49.0, "price_after": NEW_PRICE,
               "reasoning": "Fixture root move.", "sources": [], "assumptions": {}, "score": None}
    root_h = node_hash(content, [c[1] for c in root_children])
    nodes.append({**content, "hash": root_h, "children": [c[0] for c in root_children]})
    return {"root": "root", "root_hash": root_h, "nodes": nodes}


# Each vector: canonical(input) where input is the object to canonicalize directly.
VECTORS = [
    {"name": "tie-half-even-down", "input": {"x": 0.1234565}, "canonical": None},
    {"name": "tie-half-even-up", "input": {"x": 0.1234575}, "canonical": None},
    {"name": "negative-zero", "input": {"x": -0.0}, "canonical": None},
    {"name": "near-zero", "input": {"x": 1e-9}, "canonical": None},
    {"name": "integer-float", "input": {"x": 59.0}, "canonical": None},
    {"name": "long-fraction", "input": {"x": 1.0000004999}, "canonical": None},
    {"name": "sources-sorted", "input": {"sources": ["https://z.example/b", "https://a.example/y"]}, "canonical": None},
    {"name": "segments-sorted-by-id", "input": {"segments": [{"id": "mid", "customers": 120}, {"id": "smb", "customers": 300}]}, "canonical": None},
]


def main():
    tree = build_tree()
    (HERE / "fixtures" / "tree.json").write_text(json.dumps(tree, indent=2) + "\n")
    for v in VECTORS:
        v["canonical"] = canonical(v["input"]).decode()
    (HERE / "canonical_vectors.json").write_text(json.dumps(VECTORS, indent=2) + "\n")
    print(f"root_hash={tree['root_hash']}")
    print(f"nodes={len(tree['nodes'])} (expect 1 + 12 + 36 = 49)")


if __name__ == "__main__":
    main()

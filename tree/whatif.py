"""Grow one what-if competitor branch on an existing scored tree."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping

import provenance
import score
from tree.build import slug
from tree.responses import COUNTER_CHOICES, response_price_after


_SCORE_SCRIPT = Path(__file__).resolve().parent.parent / "score.py"
_SCORE_KEYS = ("low", "mid", "high", "low_pct", "mid_pct", "high_pct")
OVERRIDE_NOTE = "per-node price_after overrides the 5% default"


def _by_id(tree: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    nodes: dict[str, dict[str, Any]] = {}
    for node in tree["nodes"]:
        nodes[node["id"]] = node
    return nodes


def _find_competitor(company: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    for item in company.get("competitors") or []:
        if str(item.get("name")) == name:
            return item
    raise ValueError(f"unknown competitor {name!r}")


def infer_choice(price_after: float, your_new_price: float, current_price: float) -> str:
    """Map a typed price onto the competitor response menu."""
    if math.isclose(price_after, your_new_price):
        return "match"
    if math.isclose(price_after, current_price):
        return "ignore"
    if price_after < your_new_price:
        return "undercut"
    return "raise"


def _price_token(value: float) -> str:
    if math.isclose(value, round(value), rel_tol=0.0, abs_tol=1e-9):
        return str(int(round(value)))
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text.replace(".", "p")


def _counter_price_after(move: Mapping[str, Any], choice: str) -> float:
    resulting, _cost, _params = score.counter_terms(
        move, {"choice": choice, "assumptions": {}}, customers=0.0, months=score.MONTHS
    )
    return resulting


def _best_counter_choice(leaves: list[dict[str, Any]]) -> str:
    ranked = sorted(
        leaves,
        key=lambda node: (-float(node["score"]["mid"]), node["id"]),
    )
    return ranked[0]["choice"]


def _sources_for(nodes: Mapping[str, Mapping[str, Any]], name: str, competitor: Mapping[str, Any]) -> list[str]:
    for node in nodes.values():
        assumptions = node.get("assumptions") or {}
        if node.get("actor") == "competitor" and assumptions.get("competitor") == name:
            return list(node.get("sources") or [])
    url = competitor.get("url")
    return [str(url)] if url else []


def _score_leaf(
    company: Mapping[str, Any],
    move: Mapping[str, Any],
    leaf: Mapping[str, Any],
    competitor_name: str,
    price_after: float,
    sandbox: Any,
) -> Mapping[str, Any]:
    payload_leaf = dict(leaf)
    payload_leaf["competitor_response"] = {
        "name": competitor_name,
        "price_after": price_after,
    }
    if sandbox is None:
        return score.score_leaf(company, move, payload_leaf)
    payload = {"company": company, "move": move, "leaf": payload_leaf}
    result = sandbox.run(str(_SCORE_SCRIPT), payload)
    if not isinstance(result, Mapping):
        raise TypeError("sandbox.run must return the score.py JSON object")
    return result


def _rehash_to_root(tree: dict[str, Any], nodes: dict[str, dict[str, Any]], start: dict[str, Any]) -> list[str]:
    """Rehash ``start`` and every ancestor through the root, matching edit.py."""
    changed: list[str] = []
    current: dict[str, Any] | None = start
    while current is not None:
        children = current.get("children") or []
        child_hashes = {child_id: nodes[child_id]["hash"] for child_id in children}
        current["hash"] = provenance.node_hash(current, child_hashes)
        changed.append(current["id"])
        parent_id = current.get("parent")
        current = nodes.get(parent_id) if parent_id else None
    tree["root_hash"] = nodes[tree["root"]]["hash"]
    return changed


def grow_branch(
    tree: dict[str, Any],
    company: Mapping[str, Any],
    move: Mapping[str, Any],
    competitor_name: str,
    price_after: float,
    sandbox: Any = None,
) -> dict[str, list[str]]:
    """Add one competitor response branch and score only its three counters.

    Choice is inferred from ``price_after`` (undercut if below your new price,
    raise if above it, match/ignore on exact hits). ``price_before`` is the
    last scraped competitor price. The new response node is marked as a
    per-node override of the 5% default. Off-path nodes keep content, scores,
    and hashes. Only the new branch is scored, via ``score.score_leaf`` or
    ``sandbox.run`` when a sandbox is provided.
    """
    competitor = _find_competitor(company, competitor_name)
    price_after = float(price_after)
    if price_after <= 0:
        raise ValueError("price_after must be strictly positive")
    price_before = float(competitor["price"])
    your_new_price = float(move["to"])
    choice = infer_choice(price_after, your_new_price, price_before)
    default_after = response_price_after(choice, price_before, your_new_price)

    nodes = _by_id(tree)
    root_id = tree["root"]
    root = nodes[root_id]
    comp_slug = slug(competitor_name)
    token = _price_token(price_after)
    resp_id = f"resp-{comp_slug}-whatif-{token}"
    if resp_id in nodes:
        raise ValueError(f"what-if node {resp_id!r} already exists")

    response = {
        "id": resp_id,
        "parent": root_id,
        "actor": "competitor",
        "label": f"{competitor_name}: {choice}",
        "choice": choice,
        "price_before": price_before,
        "price_after": price_after,
        "reasoning": (
            f"What-if: {competitor_name} {choice} to {price_after:g}, "
            f"{OVERRIDE_NOTE}."
        ),
        "sources": _sources_for(nodes, competitor_name, competitor),
        "assumptions": {
            "competitor": competitor_name,
            "overrides_default_5pct": True,
            "price_after_override": price_after,
            "default_price_after": default_after,
            "override_note": OVERRIDE_NOTE,
        },
        "score": None,
        "children": [],
    }

    leaves: list[dict[str, Any]] = []
    for counter in COUNTER_CHOICES:
        leaf_id = f"leaf-{comp_slug}-whatif-{token}-{counter}"
        leaf = {
            "id": leaf_id,
            "parent": resp_id,
            "actor": "you",
            "label": counter,
            "choice": counter,
            "price_before": your_new_price,
            "price_after": _counter_price_after(move, counter),
            "reasoning": (
                f"What-if counter {counter} after {choice} by {comp_slug}."
            ),
            "sources": [],
            "assumptions": {},
            "score": None,
            "children": [],
        }
        result = _score_leaf(
            company, move, leaf, competitor_name, price_after, sandbox
        )
        leaf["score"] = {key: result[key] for key in _SCORE_KEYS}
        leaf["assumptions"] = dict(result["assumptions"])
        leaf["hash"] = provenance.node_hash(leaf, {})
        leaves.append(leaf)
        nodes[leaf_id] = leaf
        tree["nodes"].append(leaf)

    response["children"] = sorted(leaf["id"] for leaf in leaves)
    response["best_counter"] = _best_counter_choice(leaves)
    nodes[resp_id] = response
    tree["nodes"].append(response)
    root["children"] = sorted(list(root.get("children") or []) + [resp_id])

    changed = [leaf["id"] for leaf in leaves]
    changed.extend(_rehash_to_root(tree, nodes, response))
    new_node_ids = [resp_id] + [leaf["id"] for leaf in leaves]
    return {"new_node_ids": new_node_ids, "changed_hash_ids": changed}

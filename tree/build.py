"""Build the scored, hashed depth-two response tree."""

from __future__ import annotations

import re
from typing import Any, Callable, Mapping

import provenance
import score
from tree.responses import (
    COUNTER_CHOICES,
    MAX_LEAVES,
    RESPONSE_CHOICES,
    ResponseProvider,
)


Chooser = Callable[[list[dict[str, Any]]], Mapping[str, str]]

_SCORE_KEYS = ("low", "mid", "high", "low_pct", "mid_pct", "high_pct")


def slug(name: str) -> str:
    """Stable id slug; must match score.competitor_prices parent-id convention."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _validate_response(payload: Mapping[str, Any]) -> dict[str, Any]:
    missing = [key for key in ("choice", "price_before", "price_after", "reasoning", "sources")
               if key not in payload]
    if missing:
        raise ValueError(f"response is missing {missing}")
    choice = payload["choice"]
    if choice not in RESPONSE_CHOICES:
        raise ValueError(f"response choice is not on the menu: {choice!r}")
    sources = payload["sources"]
    if not isinstance(sources, list) or not all(isinstance(item, str) for item in sources):
        raise ValueError("response sources must be a list of strings")
    return {
        "choice": choice,
        "price_before": float(payload["price_before"]),
        "price_after": float(payload["price_after"]),
        "reasoning": str(payload["reasoning"]),
        "sources": list(sources),
    }


def _plan_id(move: Mapping[str, Any]) -> str:
    return str(move["plan"])


def _hash_node(node: dict[str, Any], child_hashes: Mapping[str, str]) -> None:
    node["hash"] = provenance.node_hash(node, child_hashes)


def _leaf_score_fields(result: Mapping[str, Any]) -> dict[str, Any]:
    return {key: result[key] for key in _SCORE_KEYS}


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


def build_tree(
    company: Mapping[str, Any],
    move: Mapping[str, Any],
    provider: ResponseProvider,
    depth_choices: Chooser | None = None,
) -> dict[str, Any]:
    """Build the depth-two tree: root, 3x4 responses, 36 scored hashed leaves.

    ``depth_choices`` is None for interactive depth 0 (default): after scoring,
    each response node is annotated with ``best_counter`` for the highest-mid
    child. Pass a callable for depth 1: it is invoked ONCE with all competitor
    response nodes and must return a mapping of response id to counter choice.
    The tree then scores every counter to completion without asking again.
    """
    competitors = list(company.get("competitors") or [])
    if not competitors:
        raise ValueError("company has no competitors")

    from_price = float(move["from"])
    to_price = float(move["to"])
    plan = _plan_id(move)

    nodes: dict[str, dict[str, Any]] = {}
    root = {
        "id": "root",
        "parent": None,
        "actor": "you",
        "label": f"Raise {plan.title()} {from_price:g} to {to_price:g}",
        "choice": "price_change",
        "price_before": from_price,
        "price_after": to_price,
        "reasoning": f"Price change on {plan} from {from_price:g} to {to_price:g}.",
        "sources": [],
        "assumptions": {},
        "score": None,
        "children": [],
    }
    nodes["root"] = root

    response_nodes: list[dict[str, Any]] = []
    for competitor in competitors:
        name = str(competitor["name"])
        comp_slug = slug(name)
        for payload in provider.responses(competitor, move):
            response = _validate_response(payload)
            node_id = f"resp-{comp_slug}-{response['choice']}"
            node = {
                "id": node_id,
                "parent": "root",
                "actor": "competitor",
                "label": f"{name}: {response['choice']}",
                "choice": response["choice"],
                "price_before": response["price_before"],
                "price_after": response["price_after"],
                "reasoning": response["reasoning"],
                "sources": response["sources"],
                "assumptions": {"competitor": name},
                "score": None,
                "children": [],
            }
            nodes[node_id] = node
            response_nodes.append(node)

    chosen: Mapping[str, str] | None = None
    if depth_choices is not None:
        snapshot = [
            {
                "id": node["id"],
                "parent": node["parent"],
                "actor": node["actor"],
                "label": node["label"],
                "choice": node["choice"],
                "price_before": node["price_before"],
                "price_after": node["price_after"],
                "reasoning": node["reasoning"],
                "sources": list(node["sources"]),
            }
            for node in response_nodes
        ]
        chosen = depth_choices(snapshot)
        if not isinstance(chosen, Mapping):
            raise TypeError("depth 1 chooser must return a mapping of response id to counter")

    leaf_count = 0
    for response_node in response_nodes:
        leaves: list[dict[str, Any]] = []
        parent_id = response_node["id"]
        name = str(response_node["assumptions"]["competitor"])
        comp_slug = slug(name)
        for counter in COUNTER_CHOICES:
            leaf_id = f"leaf-{comp_slug}-{response_node['choice']}-{counter}"
            leaf_count += 1
            if leaf_count > MAX_LEAVES:
                raise ValueError(f"tree exceeds the {MAX_LEAVES}-leaf cap")
            price_after = _counter_price_after(move, counter)
            leaf = {
                "id": leaf_id,
                "parent": parent_id,
                "actor": "you",
                "label": counter,
                "choice": counter,
                "price_before": to_price,
                "price_after": price_after,
                "reasoning": (
                    f"Fixture counter {counter} after {response_node['choice']} "
                    f"by {comp_slug}."
                ),
                "sources": [],
                "assumptions": {},
                "score": None,
                "children": [],
            }
            result = score.score_leaf(company, move, leaf)
            leaf["score"] = _leaf_score_fields(result)
            leaf["assumptions"] = dict(result["assumptions"])
            _hash_node(leaf, {})
            nodes[leaf_id] = leaf
            leaves.append(leaf)

        response_node["children"] = sorted(leaf["id"] for leaf in leaves)
        if chosen is not None:
            pick = chosen.get(parent_id)
            if pick not in COUNTER_CHOICES:
                pick = "hold"
            response_node["best_counter"] = pick
        else:
            response_node["best_counter"] = _best_counter_choice(leaves)
        child_hashes = {leaf["id"]: leaf["hash"] for leaf in leaves}
        _hash_node(response_node, child_hashes)

    root["children"] = sorted(node["id"] for node in response_nodes)
    _hash_node(root, {node["id"]: node["hash"] for node in response_nodes})

    ordered: list[dict[str, Any]] = []
    for competitor in competitors:
        name = str(competitor["name"])
        comp_slug = slug(name)
        for choice in RESPONSE_CHOICES:
            resp_id = f"resp-{comp_slug}-{choice}"
            if resp_id not in nodes:
                continue
            for counter in COUNTER_CHOICES:
                ordered.append(nodes[f"leaf-{comp_slug}-{choice}-{counter}"])
            ordered.append(nodes[resp_id])
    ordered.append(root)

    return {
        "root": "root",
        "root_hash": root["hash"],
        "nodes": ordered,
        "move": dict(move),
        "interactive_depth": 1 if depth_choices is not None else 0,
    }

"""Recommend a path from a fully scored tree without extra scoring runs."""

from __future__ import annotations

from typing import Any, Mapping

from tree.responses import COUNTER_CHOICES


_WATCH_WINDOW_DAYS = 30
_WATCH_DROP = 3


def _by_id(tree: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {node["id"]: node for node in tree["nodes"]}


def _leaves(nodes: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(node)
        for node in nodes.values()
        if node.get("actor") == "you" and node.get("choice") in COUNTER_CHOICES
    ]


def _rank(leaves: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        leaves,
        key=lambda node: (-float(node["score"]["mid"]), node["id"]),
    )


def _pct(value: Any) -> float:
    if value == "n/a":
        return 0.0
    return float(value)


def _band(leaf: Mapping[str, Any]) -> dict[str, float]:
    score = leaf["score"]
    return {
        "low_pct": _pct(score["low_pct"]),
        "mid_pct": _pct(score["mid_pct"]),
        "high_pct": _pct(score["high_pct"]),
    }


def _competitor_name(response: Mapping[str, Any]) -> str:
    assumptions = response.get("assumptions") or {}
    if assumptions.get("competitor"):
        return str(assumptions["competitor"])
    label = str(response.get("label") or "")
    if ":" in label:
        return label.split(":", 1)[0].strip()
    return "a competitor"


def _flips_ranking(best: Mapping[str, Any], runner: Mapping[str, Any]) -> bool:
    """True when ranking by low or by high disagrees with ranking by mid."""
    best_score = best["score"]
    runner_score = runner["score"]
    mid_best_leads = float(best_score["mid"]) >= float(runner_score["mid"])
    low_best_leads = float(best_score["low"]) >= float(runner_score["low"])
    high_best_leads = float(best_score["high"]) >= float(runner_score["high"])
    return (low_best_leads != mid_best_leads) or (high_best_leads != mid_best_leads)


def _counter_words(choice: str) -> str:
    return choice.replace("_", " ")


def _response_clause(choice: str) -> str:
    if choice == "ignore":
        return "ignores it"
    if choice == "match":
        return "matches it"
    if choice == "undercut":
        return "undercuts it"
    if choice == "raise":
        return "raises against it"
    return choice


def recommend(tree: Mapping[str, Any]) -> dict[str, Any]:
    """Return the recommendation contract object for a scored tree.

    Best path is the leaf with the highest mid score. Sensitivity is read off
    the existing low/high bands of the top two paths; this function does not
    call the scorer. The winning branch id and original move are exposed as
    pending-action input.
    """
    nodes = _by_id(tree)
    ranked = _rank(_leaves(nodes))
    if not ranked:
        raise ValueError("tree has no scored counter leaves")
    best = ranked[0]
    runner = ranked[1] if len(ranked) > 1 else ranked[0]
    parent = nodes[best["parent"]]
    competitor = _competitor_name(parent)
    move = dict(tree.get("move") or {})
    if not move:
        root = nodes[tree["root"]]
        move = {
            "from": root["price_before"],
            "to": root["price_after"],
            "action": "open_pr",
        }
    plan = str(move.get("plan") or "the plan")
    to_price = move.get("to", best["price_before"])
    to_display = int(to_price) if float(to_price) == int(to_price) else to_price
    plan_display = plan.title() if plan == plan.lower() else plan

    best_mid = float(best["score"]["mid"])
    runner_mid = float(runner["score"]["mid"])
    runner_reason = (
        f"The runner-up {runner['id']} has a lower mid score "
        f"({runner_mid:.1f} vs {best_mid:.1f}) so its band "
        f"({runner['score']['low']:.1f} to {runner['score']['high']:.1f}) "
        f"does not beat the recommended band "
        f"({best['score']['low']:.1f} to {best['score']['high']:.1f})."
    )

    flips = _flips_ranking(best, runner)
    if flips:
        sensitivity_statement = (
            "A price-sensitivity range end flips the ranking of the top two "
            "paths; other assumptions are editable but not sensitivity-ranked."
        )
    else:
        sensitivity_statement = (
            "No price-sensitivity range end flips the ranking; other "
            "assumptions are editable but not sensitivity-ranked."
        )

    threshold = float(parent["price_before"]) - _WATCH_DROP
    watch_statement = (
        f"{competitor} below ${threshold:g} within {_WATCH_WINDOW_DAYS} days "
        f"would flip this recommendation."
    )
    sentence = (
        f"Raise {plan_display} to ${to_display} and {_counter_words(best['choice'])} "
        f"even if {competitor} {_response_clause(parent['choice'])}."
    )
    path_id = best["id"]
    return {
        "path_id": path_id,
        "sentence": sentence,
        "band": _band(best),
        "runner_up_id": runner["id"],
        "runner_up_reason": runner_reason,
        "sensitivity": {
            "flips_ranking": flips,
            "statement": sensitivity_statement,
        },
        "watch_trigger": {
            "competitor": competitor,
            "threshold": threshold,
            "window_days": _WATCH_WINDOW_DAYS,
            "statement": watch_statement,
        },
        "winning_branch_id": path_id,
        "move": move,
    }

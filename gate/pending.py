"""Typed construction of inert pending pricing actions."""

from __future__ import annotations

import difflib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping


_MONTHS = (
    "",
    "Jan",
    "Feb",
    "March",
    "April",
    "May",
    "June",
    "July",
    "Aug",
    "Sept",
    "Oct",
    "Nov",
    "Dec",
)


@dataclass(frozen=True)
class _MemoFields:
    winning_branch: str
    score_band: str
    assumptions: str
    root_hash: str
    reasoning: str


def _longest_backtick_run(content: str) -> int:
    return max((len(run) for run in re.findall(r"`+", content)), default=0)


def _fenced(content: str) -> str:
    fence = "`" * max(3, _longest_backtick_run(content) + 1)
    return f"{fence}\n{content}\n{fence}"


def _display_date(value: str) -> str:
    parsed = date.fromisoformat(value)
    return f"{_MONTHS[parsed.month]} {parsed.day}"


def _display_plan(company: Mapping[str, Any], plan_id: str) -> str:
    for plan in company.get("plans", []):
        if plan.get("id") == plan_id:
            name = plan.get("name") or plan_id
            return str(name).replace("_", " ").title()
    raise ValueError(f"company has no plan {plan_id!r}")


def _winning_path(tree: Mapping[str, Any], winning_id: str) -> list[Mapping[str, Any]]:
    nodes = tree.get("nodes")
    if not isinstance(nodes, list):
        raise ValueError("tree nodes must be a list")
    by_id = {node.get("id"): node for node in nodes if isinstance(node, Mapping)}
    current = by_id.get(winning_id)
    if current is None:
        raise ValueError(f"tree has no winning branch {winning_id!r}")
    path = []
    seen = set()
    while current is not None:
        node_id = current.get("id")
        if node_id in seen:
            raise ValueError("winning branch ancestry contains a cycle")
        seen.add(node_id)
        path.append(current)
        parent_id = current.get("parent")
        current = by_id.get(parent_id) if parent_id is not None else None
    return list(reversed(path))


def _format_band(band: Mapping[str, Any]) -> str:
    required = ("low_pct", "mid_pct", "high_pct")
    if not all(key in band for key in required):
        raise ValueError("recommendation band must contain low, mid, and high percentages")
    return (
        f"{band['mid_pct']:+g}% "
        f"(between {band['low_pct']:+g}% and {band['high_pct']:+g}%)"
    )


def _render_memo(fields: _MemoFields) -> str:
    # All headings and prose are literals.  Untrusted reasoning is inserted
    # exactly once, as the body of a dynamically sized fenced block.
    return (
        "# Pricing decision memo\n\n"
        f"Winning branch: `{fields.winning_branch}`\n\n"
        f"Score band: {fields.score_band}\n\n"
        "## Assumptions\n\n"
        f"{fields.assumptions}\n\n"
        "## Provenance\n\n"
        f"Root hash: `{fields.root_hash}`\n\n"
        "## Subagent reasoning\n\n"
        f"{_fenced(fields.reasoning)}\n"
    )


def build_pending_action(
    tree: Mapping[str, Any],
    recommendation: Mapping[str, Any],
    move: Mapping[str, Any],
    company: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a schema-compatible pending action without writing anything."""

    plan_id = move.get("plan")
    old_price = move.get("from")
    new_price = move.get("to")
    effective = move.get("effective")
    winning_id = recommendation.get("path_id")
    root_hash = tree.get("root_hash")
    if not isinstance(plan_id, str) or not isinstance(effective, str):
        raise ValueError("move must contain string plan and effective fields")
    if not isinstance(old_price, (int, float)) or isinstance(old_price, bool):
        raise ValueError("move.from must be numeric")
    if not isinstance(new_price, (int, float)) or isinstance(new_price, bool):
        raise ValueError("move.to must be numeric")
    if not isinstance(winning_id, str):
        raise ValueError("recommendation.path_id must be a string")
    if not isinstance(root_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", root_hash):
        raise ValueError("tree.root_hash must be a lowercase SHA-256 digest")

    plan_name = _display_plan(company, plan_id)
    path = _winning_path(tree, winning_id)
    winner = path[-1]
    reasoning_parts = [
        str(node["reasoning"])
        for node in path
        if isinstance(node.get("reasoning"), str) and node["reasoning"]
    ]
    reasoning = "\n\n".join(reasoning_parts) or "No subagent reasoning was recorded."
    assumptions = json.dumps(
        winner.get("assumptions") or {}, ensure_ascii=False, indent=2, sort_keys=True
    )
    fields = _MemoFields(
        winning_branch=winning_id,
        score_band=_format_band(recommendation.get("band") or {}),
        assumptions=_fenced(assumptions),
        root_hash=root_hash,
        reasoning=reasoning,
    )

    old_yaml = f"plan: {plan_id}\nprice: {old_price:g}\n"
    new_yaml = f"plan: {plan_id}\nprice: {new_price:g}\n"
    diff = "".join(
        difflib.unified_diff(
            old_yaml.splitlines(keepends=True),
            new_yaml.splitlines(keepends=True),
            fromfile="a/pricing.yaml",
            tofile="b/pricing.yaml",
        )
    )
    slug = re.sub(r"[^a-z0-9]+", "-", plan_id.lower()).strip("-") or "plan"
    return {
        "id": f"act-{uuid.uuid4().hex}",
        "sentence": (
            f"Open a change request to raise {plan_name} to ${new_price:g} "
            f"on {_display_date(effective)}?"
        ),
        "diff": diff,
        "memo_markdown": _render_memo(fields),
        "winning_branch_id": winning_id,
        "root_hash": root_hash,
        "status": "waiting",
        "deny_reason": None,
        # Typed execution data.  The frozen schema permits extension fields;
        # the gate never parses values back out of Markdown or a diff.
        "change": {
            "plan": plan_id,
            "plan_name": plan_name,
            "from": old_price,
            "to": new_price,
            "effective": effective,
            "pricing_yaml": new_yaml,
            "memo_path": f"decisions/{effective}-{slug}-price.md",
        },
    }

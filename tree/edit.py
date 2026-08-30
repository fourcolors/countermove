"""Edit a leaf assumption, rerun score.py in the sandbox, and rehash the path."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import provenance


_SCORE_SCRIPT = Path(__file__).resolve().parent.parent / "score.py"
_SCORE_KEYS = ("low", "mid", "high", "low_pct", "mid_pct", "high_pct")


def _by_id(tree: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    nodes: dict[str, dict[str, Any]] = {}
    for node in tree["nodes"]:
        nodes[node["id"]] = node
    return nodes


def edit_assumption(
    tree: dict[str, Any],
    leaf_id: str,
    changes: Mapping[str, Any],
    sandbox: Any,
    company: Mapping[str, Any],
    move: Mapping[str, Any],
) -> list[str]:
    """Rerun score.py through ``sandbox.run`` and rehash the leaf to the root.

    ``sandbox.run`` is called with the score.py script path and the same
    ``{company, move, leaf}`` JSON that test_score's CLI contract uses.
    The leaf's score and assumptions are replaced from the sandbox output.
    The leaf and every ancestor through the root are rehashed with
    ``provenance.node_hash``. Off-path hashes are left untouched.
    Returns the changed node ids from the leaf up to the root.
    """
    nodes = _by_id(tree)
    if leaf_id not in nodes:
        raise ValueError(f"unknown leaf {leaf_id!r}")
    leaf = nodes[leaf_id]
    if leaf.get("children"):
        raise ValueError(f"{leaf_id!r} is not a leaf")

    payload_leaf = dict(leaf)
    assumptions = dict(leaf.get("assumptions") or {})
    # score.py reads eta as a scalar; the displayed per-segment mapping is
    # scorer output, not a legal input, so drop it unless the edit sets eta.
    if "eta" not in changes and isinstance(assumptions.get("eta"), dict):
        assumptions.pop("eta")
    assumptions.update(changes)
    payload_leaf["assumptions"] = assumptions
    payload = {"company": company, "move": move, "leaf": payload_leaf}
    result = sandbox.run(str(_SCORE_SCRIPT), payload)
    if not isinstance(result, Mapping):
        raise TypeError("sandbox.run must return the score.py JSON object")

    leaf["score"] = {key: result[key] for key in _SCORE_KEYS}
    leaf["assumptions"] = dict(result["assumptions"])

    changed: list[str] = []
    current: dict[str, Any] | None = leaf
    while current is not None:
        children = current.get("children") or []
        child_hashes = {child_id: nodes[child_id]["hash"] for child_id in children}
        current["hash"] = provenance.node_hash(current, child_hashes)
        changed.append(current["id"])
        parent_id = current.get("parent")
        current = nodes.get(parent_id) if parent_id else None

    tree["root_hash"] = nodes[tree["root"]]["hash"]
    return changed

"""Reload a saved session and look up the last decision for a plan."""

import copy
from datetime import datetime, timezone

from orchestrator.session_store import SessionStore


def restore(session_dir):
    """Return the session stored in session_dir, exactly as saved.

    Tree, scores (on tree nodes), decisions, and trace come back through
    the session store JSON round-trip. Missing files yield a fresh session.
    """
    return SessionStore(session_dir).load()


def record_decision(session, decision):
    """Append a decision with a persisted ISO timestamp at write time.

    A caller-supplied `ts` is kept when it is a non-empty string so tests
    can backdate a window. Otherwise the current UTC instant is stored.
    """
    if not isinstance(session, dict):
        raise TypeError("session must be a dict")
    if not isinstance(decision, dict):
        raise TypeError("decision must be a dict")
    stored = copy.deepcopy(decision)
    ts = stored.get("ts")
    if not isinstance(ts, str) or not ts.strip():
        stored["ts"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    items = session.get("decisions")
    if not isinstance(items, list):
        items = []
        session["decisions"] = items
    items.append(stored)
    return copy.deepcopy(stored)


def previous_decision(session, plan_id):
    """Return the last stored decision for plan_id, including its reason.

    Matches a decision whose `plan` (or nested `move.plan`) equals plan_id.
    The returned dict is a copy with `reason` always populated from `reason`
    or `deny_reason`. Returns None when that plan has no prior decision.
    """
    last = None
    for item in _decisions(session):
        if _plan_of(item) == plan_id:
            last = item
    if last is None:
        return None
    result = copy.deepcopy(last)
    if not result.get("reason"):
        deny_reason = result.get("deny_reason")
        if deny_reason:
            result["reason"] = deny_reason
    return result


def _decisions(session):
    if not isinstance(session, dict):
        return []
    items = session.get("decisions")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _plan_of(item):
    if "plan" in item and item["plan"] is not None:
        return item["plan"]
    move = item.get("move")
    if isinstance(move, dict) and move.get("plan") is not None:
        return move.get("plan")
    return None

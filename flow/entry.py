"""Production session start: restore, mark a run, check the watch trigger first."""

import uuid

from orchestrator.tool_router import ToolRouter
from orchestrator.trace import emit

from .restore import previous_decision, restore
from .watch import check_watch_trigger


def start_session(session_dir, client, router_factory):
    """Load the session, mark a new run, and check the watch trigger first.

    All ordering guarantees live here, not in the caller:
    1. restore the session (fresh if missing)
    2. emit a run-boundary marker carrying a run_id
    3. routed watch check (no-op when the latest decision has no trigger)
    4. surface previous_decision for the pending plan

    Returns a context {session, watch_result, previous_decision}. The caller
    must consume() that context before any tree construction; begin_tree()
    raises until then.
    """
    if not callable(router_factory):
        raise TypeError("router_factory must be callable")

    session = restore(session_dir)
    run_id = uuid.uuid4().hex
    session["run_id"] = run_id
    emit(
        session,
        "orchestrator",
        "did",
        "starting a new run",
        detail={"run_id": run_id, "run_boundary": True},
    )

    router = router_factory(session)
    if not isinstance(router, ToolRouter):
        raise TypeError(
            "router_factory must return a ToolRouter; "
            "competitor pages are never fetched around it"
        )
    watch_result = check_watch_trigger(session, client, router)

    plan_id = _pending_plan_id(session)
    prev = previous_decision(session, plan_id) if plan_id is not None else None

    return {
        "session": session,
        "watch_result": watch_result,
        "previous_decision": prev,
        "run_id": run_id,
        "consumed": False,
    }


def consume(context):
    """Acknowledge watch_result and previous_decision before tree work.

    Returns the session. begin_tree raises until this has been called.
    """
    if not _is_start_context(context):
        raise TypeError("consume requires a start_session context")
    context["consumed"] = True
    return context["session"]


def begin_tree(context):
    """Return the session for tree construction after consume().

    Raises RuntimeError if the start_session context has not been consumed,
    so a tree build attempted before the caller uses the context is detected
    here rather than by test choreography.
    """
    if not _is_start_context(context) or not context.get("consumed"):
        raise RuntimeError(
            "start_session context must be consumed before building the tree"
        )
    return context["session"]


def _is_start_context(context):
    if not isinstance(context, dict):
        return False
    return (
        "session" in context
        and "watch_result" in context
        and "previous_decision" in context
    )


def _pending_plan_id(session):
    if not isinstance(session, dict):
        return None
    move = session.get("move")
    if isinstance(move, dict) and move.get("plan") is not None:
        return move.get("plan")
    decisions = session.get("decisions")
    if not isinstance(decisions, list):
        return None
    for item in reversed(decisions):
        if not isinstance(item, dict):
            continue
        if item.get("plan") is not None:
            return item.get("plan")
        nested = item.get("move")
        if isinstance(nested, dict) and nested.get("plan") is not None:
            return nested.get("plan")
    return None

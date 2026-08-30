"""Frozen trace-emit API.

Events appended here must conform to contracts/trace_event.schema.json.
Text is plain language only; callers supply the sentence, this module does not rewrite it.
"""

from datetime import datetime, timezone

COLUMNS = ("doing", "waiting", "did")


def emit(session, actor, column, text, tool=None, detail=None):
    """Append one trace event to session['trace'] and return it."""
    if not isinstance(actor, str) or not actor:
        raise ValueError("actor must be a non-empty string")
    if column not in COLUMNS:
        raise ValueError("column must be doing, waiting, or did")
    if not isinstance(text, str) or not text:
        raise ValueError("text must be a non-empty string")
    if tool is not None and not isinstance(tool, str):
        raise ValueError("tool must be a string or None")
    if detail is None:
        detail_obj = {}
    elif isinstance(detail, dict):
        detail_obj = dict(detail)
    else:
        raise ValueError("detail must be an object")

    event = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "actor": actor,
        "column": column,
        "text": text,
        "tool": tool,
        "detail": detail_obj,
    }
    trace = session.get("trace")
    if trace is None:
        trace = []
        session["trace"] = trace
    trace.append(event)
    return event

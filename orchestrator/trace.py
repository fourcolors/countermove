"""Frozen trace-emit API.

Events appended here must conform to contracts/trace_event.schema.json.
Text is plain language only; callers supply the sentence, this module does not rewrite it.
"""

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent / "contracts" / "trace_event.schema.json"
)


def _load_schema():
    with _SCHEMA_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


_SCHEMA = _load_schema()
COLUMNS = tuple(_SCHEMA["properties"]["column"]["enum"])

_JSON_TYPES = {
    "string": str,
    "object": dict,
    "array": list,
    "boolean": bool,
    "integer": int,
    "number": (int, float),
    "null": type(None),
}


def _matches_json_type(value, spec):
    names = spec if isinstance(spec, list) else [spec]
    for name in names:
        py_type = _JSON_TYPES[name]
        if name in ("integer", "number") and isinstance(value, bool):
            continue
        if isinstance(value, py_type):
            return True
    return False


def _validate_ts(value):
    if not isinstance(value, str) or not value:
        raise ValueError("ts must be a non-empty string")
    iso = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(iso)
    except ValueError as exc:
        raise ValueError("ts is not a date-time: %s" % value) from exc
    core = value[:-1] if value.endswith("Z") else value
    if "T" not in core and "t" not in core and " " not in core:
        raise ValueError("ts must be a full RFC3339 date-time, not a date")


def validate(event):
    """Raise ValueError if event does not conform to the frozen trace_event schema."""
    if not isinstance(event, dict):
        raise ValueError("trace event must be an object")

    required = _SCHEMA["required"]
    missing = [key for key in required if key not in event]
    if missing:
        raise ValueError("missing required field: %s" % ", ".join(missing))

    props = _SCHEMA["properties"]
    for key, spec in props.items():
        if key not in event:
            continue
        value = event[key]
        expected = spec.get("type")
        if expected is not None and not _matches_json_type(value, expected):
            raise ValueError("%s has the wrong type" % key)
        if "enum" in spec and value not in spec["enum"]:
            raise ValueError(
                "%s must be one of %s" % (key, spec["enum"])
            )
        if spec.get("format") == "date-time":
            _validate_ts(value)


def emit(session, actor, column, text, tool=None, detail=None):
    """Append one trace event to session['trace'] and return it."""
    if detail is None:
        detail_obj = {}
    else:
        detail_obj = copy.deepcopy(detail)

    event = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "actor": actor,
        "column": column,
        "text": text,
        "tool": tool,
        "detail": detail_obj,
    }
    validate(event)
    stored = copy.deepcopy(event)
    trace = session.get("trace")
    if trace is None:
        trace = []
        session["trace"] = trace
    trace.append(stored)
    return copy.deepcopy(stored)

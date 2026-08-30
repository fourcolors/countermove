"""Private single-use approval capability primitives."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any

from orchestrator.trace import emit


class GateRefused(RuntimeError):
    """The gate refused an action because an authorization invariant failed."""


def _mint_approval_token() -> str:
    """Create an opaque capability.

    This function deliberately does not bind or persist the token.  Only
    :func:`gate.ui.ui_allow` does that, so merely calling this primitive cannot
    authorize a queued action.  It remains private to the gate package.
    """

    return secrets.token_urlsafe(32)


def _find_waiting_action(session: dict[str, Any], action_id: str) -> dict[str, Any] | None:
    for action in session.get("decisions") or []:
        if action.get("id") == action_id and action.get("status") == "waiting":
            return action
    return None


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _refuse(session: dict[str, Any], action_id: str, reason: str) -> None:
    emit(
        session,
        "gate",
        "did",
        "Refused the change request.",
        detail={"action_id": action_id, "reason": reason},
    )
    raise GateRefused(reason)


def consume_approval_token(
    session: dict[str, Any], action_id: str, token: object
) -> dict[str, Any]:
    """Validate and consume the capability, returning its waiting action."""

    action = _find_waiting_action(session, action_id)
    if action is None:
        _refuse(session, action_id, "the action is not waiting for approval")

    expected = action.get("_approval_token_hash")
    supplied = _token_digest(token) if isinstance(token, str) else ""
    if not isinstance(expected, str) or not hmac.compare_digest(expected, supplied):
        _refuse(session, action_id, "a valid human approval token is required")

    # Consume before any write or provenance check.  A capability authorizes
    # one attempt, including an attempt stopped because the tree was tampered.
    del action["_approval_token_hash"]
    return action

"""UI-server-only entry point for binding a human Allow click.

Only the trusted UI server layer may call :func:`ui_allow`; model, orchestrator,
and general application code must use the package's narrow public API instead.
This in-process v0 boundary limits accidental capability exposure, but it is
not process isolation and does not provide HTTP-layer CSRF protection.  The
integration layer remains responsible for authenticating the human request and
enforcing CSRF protections before calling this module.
"""

from __future__ import annotations

from typing import Any

from .tokens import _find_waiting_action, _mint_approval_token, _refuse, _token_digest


def ui_allow(session: dict[str, Any], action_id: str) -> str:
    """Bind a fresh single-use approval token to one waiting action."""

    action = _find_waiting_action(session, action_id)
    if action is None:
        _refuse(session, action_id, "the action is not waiting for approval")
    token = _mint_approval_token()
    action["_approval_token_hash"] = _token_digest(token)
    return token

"""State transitions and side effects for the human approval gate."""

from __future__ import annotations

import copy
import hashlib
import re
from pathlib import Path
from typing import Any, Mapping

from orchestrator.trace import emit
from provenance import canonical, verify_tree

from .pending import _build_artifacts, _memo_path
from .repo import RepoClient
from .tokens import GateRefused, consume_approval_token


_VOLATILE_ACTION_FIELDS = {
    "_approval_token_hash",
    "_queued_action_digest",
    "local_memo_path",
    "pr_url",
    "status",
}


def _digest(content: Any) -> str:
    return hashlib.sha256(canonical(content)).hexdigest()


def _action_content(action: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in action.items()
        if key not in _VOLATILE_ACTION_FIELDS
    }


def _queued_artifacts(action: Mapping[str, Any]) -> dict[str, Any]:
    change = action.get("change")
    if not isinstance(change, Mapping):
        raise ValueError("the typed pricing change is missing")
    memo = action.get("memo_markdown")
    diff = action.get("diff")
    pricing = change.get("pricing_yaml")
    memo_path = change.get("memo_path")
    if not all(isinstance(value, str) for value in (memo, diff, pricing, memo_path)):
        raise ValueError("the queued artifacts are incomplete")
    return {
        "diff": diff,
        "memo_markdown": memo,
        "files": {"pricing.yaml": pricing, memo_path: memo},
    }


def _rendered_artifacts(artifacts: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "diff": artifacts["diff"],
        "memo_markdown": artifacts["memo_markdown"],
        "files": artifacts["files"],
    }


class GateService:
    def __init__(self, session: dict[str, Any], repo_client: RepoClient):
        self.session = session
        self.repo_client = repo_client

    def _refuse(self, action_id: str, reason: str) -> None:
        emit(
            self.session,
            "gate",
            "did",
            "Refused the change request.",
            detail={"action_id": action_id, "reason": reason},
        )
        raise GateRefused(reason)

    def queue(self, pending: Mapping[str, Any]) -> dict[str, Any]:
        action = copy.deepcopy(dict(pending))
        action_id = action.get("id")
        if not isinstance(action_id, str) or not action_id:
            raise ValueError("pending action must have an id")
        if any(item.get("id") == action_id for item in self.session.get("decisions") or []):
            raise ValueError(f"action already exists: {action_id}")
        if action.get("status") != "waiting":
            raise ValueError("a queued action must have waiting status")
        source = action.get("_gate_source")
        if not isinstance(source, Mapping):
            raise ValueError("pending action is missing its stored gate inputs")
        try:
            action["_queued_artifact_digest"] = _digest(_queued_artifacts(action))
            action["_queued_action_digest"] = _digest(_action_content(action))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"pending action cannot be sealed: {exc}") from exc
        self.session.setdefault("decisions", []).append(action)
        emit(
            self.session,
            "gate",
            "waiting",
            "Waiting for your approval to open the change request.",
            detail={"action_id": action_id},
        )
        return copy.deepcopy(action)

    def approve(self, action_id: str, token: object) -> str:
        action = consume_approval_token(self.session, action_id, token)
        tree = self.session.get("tree")
        if not isinstance(tree, Mapping):
            self._refuse(action_id, "the stored decision tree is missing")
        verification = verify_tree(tree)
        if not verification["ok"]:
            self._refuse(
                action_id,
                "the stored decision tree failed provenance verification",
            )
        source = action.get("_gate_source")
        if not isinstance(source, Mapping):
            self._refuse(action_id, "the stored gate inputs are missing")
        move = source.get("move")
        recommendation = source.get("recommendation")
        if not isinstance(move, Mapping) or not isinstance(recommendation, Mapping):
            self._refuse(action_id, "the stored move or recommendation is missing")
        try:
            artifacts = _build_artifacts(tree, recommendation, move)
            regenerated_digest = _digest(_rendered_artifacts(artifacts))
            current_artifact_digest = _digest(_queued_artifacts(action))
        except (KeyError, TypeError, ValueError):
            self._refuse(action_id, "the stored gate inputs cannot regenerate artifacts")
        queued_artifact_digest = action.get("_queued_artifact_digest")
        if (
            regenerated_digest != queued_artifact_digest
            or current_artifact_digest != queued_artifact_digest
        ):
            self._refuse(action_id, "the regenerated artifact does not match the queued one")
        try:
            current_action_digest = _digest(_action_content(action))
        except (TypeError, ValueError):
            self._refuse(action_id, "the queued action artifact was malformed")
        if current_action_digest != action.get("_queued_action_digest"):
            self._refuse(action_id, "the queued action artifact was modified")

        change = action.get("change")
        plan_name = change.get("plan_name") if isinstance(change, Mapping) else None
        if not isinstance(plan_name, str) or not plan_name:
            self._refuse(action_id, "the pricing plan name is missing")
        plan = artifacts["plan"]
        new_price = artifacts["to"]
        effective = artifacts["effective"]
        root_hash = artifacts["root_hash"]

        expected_slug = re.sub(r"[^a-z0-9]+", "-", plan.lower()).strip("-") or "plan"
        safe_action = re.sub(r"[^a-z0-9]+", "-", action_id.lower()).strip("-")
        branch = f"countermove/{effective}-{expected_slug}-{safe_action[-12:]}"
        title = (
            f"Raise {plan_name} to ${new_price:g} "
            f"effective {effective}"
        )
        memo = artifacts["memo_markdown"]
        self.repo_client.create_branch(branch)
        self.repo_client.write_files(artifacts["files"])
        url = self.repo_client.open_pr(title, memo)
        action["status"] = "approved"
        action["pr_url"] = url
        emit(
            self.session,
            "gate",
            "did",
            "Opened the approved change request.",
            tool="github",
            detail={"action_id": action_id, "url": url, "root_hash": root_hash},
        )
        return url

    def deny(self, action_id: str, reason: str) -> Path:
        action = next(
            (
                item
                for item in self.session.get("decisions") or []
                if item.get("id") == action_id and item.get("status") == "waiting"
            ),
            None,
        )
        if action is None:
            self._refuse(action_id, "the action is not waiting for a decision")
        if not isinstance(reason, str) or not reason.strip():
            self._refuse(action_id, "a denial reason is required")
        source = action.get("_gate_source")
        move = source.get("move") if isinstance(source, Mapping) else None
        if not isinstance(move, Mapping):
            self._refuse(action_id, "the stored move is missing")
        plan = move.get("plan")
        effective = move.get("effective")
        if not isinstance(plan, str) or not isinstance(effective, str):
            self._refuse(action_id, "the stored move is invalid")
        try:
            memo_path = _memo_path(plan, effective)
        except ValueError:
            self._refuse(action_id, "the stored move has an invalid effective date")

        # The session owner may pin its directory through _session_dir.  The
        # fallback is explicit and retained in the session for later reloads.
        session_dir = Path(
            self.session.setdefault("_session_dir", ".countermove-session")
        ).resolve()
        local_path = (session_dir / memo_path).resolve()
        try:
            local_path.relative_to(session_dir)
        except ValueError:
            self._refuse(action_id, "the generated decision memo path escaped the session")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        ticks = "`" * max(3, max((len(x) for x in re.findall(r"`+", reason)), default=0) + 1)
        denied_memo = (
            f"{action['memo_markdown']}\n## Decision\n\nDenied.\n\n"
            f"Reason:\n\n{ticks}\n{reason}\n{ticks}\n"
        )
        local_path.write_text(denied_memo, encoding="utf-8")
        action.pop("_approval_token_hash", None)
        action["status"] = "denied"
        action["deny_reason"] = reason
        action["local_memo_path"] = str(local_path)
        emit(
            self.session,
            "gate",
            "did",
            "Saved the declined decision locally.",
            detail={"action_id": action_id, "reason": reason, "path": str(local_path)},
        )
        return local_path

"""State transitions and side effects for the human approval gate."""

from __future__ import annotations

import copy
import re
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from orchestrator.trace import emit
from provenance import verify_tree

from .repo import RepoClient
from .tokens import GateRefused, consume_approval_token


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
        root_hash = tree.get("root_hash")
        if (
            action.get("root_hash") != root_hash
            or not isinstance(root_hash, str)
            or root_hash not in action.get("memo_markdown", "")
        ):
            self._refuse(action_id, "the decision memo does not match the tree")

        change = action.get("change")
        if not isinstance(change, Mapping):
            self._refuse(action_id, "the typed pricing change is missing")
        required = ("plan", "plan_name", "to", "effective", "pricing_yaml", "memo_path")
        if not all(key in change for key in required):
            self._refuse(action_id, "the typed pricing change is incomplete")
        plan = change["plan"]
        plan_name = change["plan_name"]
        new_price = change["to"]
        effective = change["effective"]
        if (
            not isinstance(plan, str)
            or not plan
            or not isinstance(plan_name, str)
            or not plan_name
            or not isinstance(new_price, (int, float))
            or isinstance(new_price, bool)
            or not isinstance(effective, str)
        ):
            self._refuse(action_id, "the typed pricing change has invalid values")
        try:
            date.fromisoformat(effective)
        except ValueError:
            self._refuse(action_id, "the effective date is invalid")

        expected_slug = re.sub(r"[^a-z0-9]+", "-", plan.lower()).strip("-") or "plan"
        expected_memo_path = f"decisions/{effective}-{expected_slug}-price.md"
        expected_pricing = f"plan: {plan}\nprice: {new_price:g}\n"
        if (
            change["memo_path"] != expected_memo_path
            or change["pricing_yaml"] != expected_pricing
        ):
            self._refuse(action_id, "the typed pricing files do not match the change")

        safe_action = re.sub(r"[^a-z0-9]+", "-", action_id.lower()).strip("-")
        branch = f"countermove/{effective}-{expected_slug}-{safe_action[-12:]}"
        title = (
            f"Raise {plan_name} to ${new_price:g} "
            f"effective {effective}"
        )
        memo = action["memo_markdown"]
        self.repo_client.create_branch(branch)
        self.repo_client.write_files(
            {"pricing.yaml": change["pricing_yaml"], change["memo_path"]: memo}
        )
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
        change = action.get("change") or {}
        memo_path = change.get("memo_path")
        if not isinstance(memo_path, str):
            self._refuse(action_id, "the decision memo path is missing")

        # The session owner may pin its directory through _session_dir.  The
        # fallback is explicit and retained in the session for later reloads.
        session_dir = Path(self.session.setdefault("_session_dir", ".countermove-session"))
        local_path = session_dir / memo_path
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

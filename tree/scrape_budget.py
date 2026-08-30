"""Per-subagent extra-scrape budget. Plain data, no I/O."""

from __future__ import annotations

from typing import Any


class ScrapeBudget:
    """Allow one extra scrape per subagent; refuse and record the second.

    Gather already used the primary scrape. Each competitor subagent may
    request one extra scrape. A second request is refused and appended to
    ``refusals`` as a traceable data record. Nothing is fetched here.
    """

    def __init__(self, extra_allowed: int = 1):
        self.extra_allowed = extra_allowed
        self._used: dict[str, int] = {}
        self.refusals: list[dict[str, Any]] = []

    def used(self, subagent_id: str) -> int:
        return self._used.get(subagent_id, 0)

    def request(self, subagent_id: str, url: str) -> dict[str, Any]:
        """Return an allow/refuse record for this subagent's extra scrape."""
        used = self._used.get(subagent_id, 0)
        if used >= self.extra_allowed:
            refusal = {
                "subagent_id": subagent_id,
                "url": url,
                "allowed": False,
                "reason": "scrape budget exhausted: only one extra scrape per subagent",
            }
            self.refusals.append(refusal)
            return refusal
        self._used[subagent_id] = used + 1
        return {
            "subagent_id": subagent_id,
            "url": url,
            "allowed": True,
            "reason": None,
        }

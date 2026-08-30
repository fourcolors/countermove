"""Competitor response providers for the depth-two tree.

Scraped pages and persona-card notes are untrusted input. The only values
that may influence a fixture response are schema-validated structured facts:
competitor name as a string, price as a number, and up to three source URLs.
Notes and any other free text are stored as data and never parsed as
instructions.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping, Sequence


RESPONSE_CHOICES = ("undercut", "match", "ignore", "raise")
COUNTER_CHOICES = ("hold", "partial_rollback", "annual_discount")
MAX_LEAVES = 36


def structured_facts(card: Mapping[str, Any]) -> dict[str, Any]:
    """Return the allowlisted, schema-validated facts for a persona card.

    Raw page text and ``notes`` are dropped. A later LLM subagent must receive
    only this object (price as a number, competitor name as an escaped string,
    at most three news URLs plus the pricing URL).
    """
    news = list(card.get("news_urls") or [])
    if not isinstance(news, list):
        raise TypeError("news_urls must be a list of strings")
    urls = [str(item) for item in news[:3]]
    return {
        "competitor": str(card["competitor"]),
        "price": float(card["price"]),
        "pricing_url": str(card.get("pricing_url") or ""),
        "news_urls": urls,
    }


def response_price_after(choice: str, competitor_price: float, your_new_price: float) -> float:
    """Pinned menu semantics from the Data shapes section."""
    if choice == "undercut":
        return your_new_price * 0.95
    if choice == "match":
        return your_new_price
    if choice == "ignore":
        return competitor_price
    if choice == "raise":
        return competitor_price * 1.05
    raise ValueError(f"unsupported response choice: {choice!r}")


def _competitor_name(competitor: Mapping[str, Any] | str) -> str:
    if isinstance(competitor, str):
        return competitor
    return str(competitor.get("name") or competitor.get("competitor"))


def _sources(facts: Mapping[str, Any]) -> list[str]:
    sources: list[str] = []
    pricing_url = facts.get("pricing_url") or ""
    if pricing_url:
        sources.append(str(pricing_url))
    for url in facts.get("news_urls") or []:
        text = str(url)
        if text and text not in sources:
            sources.append(text)
    return sources


class ResponseProvider(ABC):
    """Return forced-choice responses for one competitor.

    Each response is ``{choice, price_before, price_after, reasoning, sources}``.
    ``choice`` must be one of ``RESPONSE_CHOICES``. A categorical choice
    without numeric prices is not a valid node.
    """

    @abstractmethod
    def responses(self, competitor: Mapping[str, Any] | str, move: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Return the forced-choice response(s) for this competitor."""


class FixtureResponseProvider(ResponseProvider):
    """Deterministic provider: all four menu responses from pinned price semantics.

    Persona-card ``notes`` are ignored. Choices and prices come only from the
    structured ``price`` field and the move's new price.
    """

    def __init__(self, persona_cards: Sequence[Mapping[str, Any]]):
        self._cards = {
            str(card["competitor"]): dict(card) for card in persona_cards
        }

    def _card_for(self, competitor: Mapping[str, Any] | str) -> Mapping[str, Any]:
        name = _competitor_name(competitor)
        card = self._cards.get(name)
        if card is not None:
            return card
        if isinstance(competitor, Mapping):
            return {
                "competitor": name,
                "price": competitor["price"],
                "pricing_url": competitor.get("url") or competitor.get("pricing_url") or "",
                "news_urls": list(competitor.get("news_urls") or []),
            }
        raise KeyError(f"no persona card for competitor {name!r}")

    def responses(self, competitor: Mapping[str, Any] | str, move: Mapping[str, Any]) -> list[dict[str, Any]]:
        facts = structured_facts(self._card_for(competitor))
        your_new_price = float(move["to"])
        before = facts["price"]
        sources = _sources(facts)
        name = facts["competitor"]
        out: list[dict[str, Any]] = []
        for choice in RESPONSE_CHOICES:
            after = response_price_after(choice, before, your_new_price)
            out.append({
                "choice": choice,
                "price_before": before,
                "price_after": after,
                "reasoning": f"Fixture response {choice} by {name}.",
                "sources": list(sources),
            })
        return out


class LLMResponseProvider(ResponseProvider):
    """Integration seam for a later LLM-backed competitor subagent.

    Not implemented in v0. When wired, the subagent context must receive only
    schema-validated structured facts from ``structured_facts`` (price as a
    number, competitor name as an escaped string, up to three source URLs).
    Raw page text and persona-card notes never enter subagent context. The
    orchestrator validates the returned choice and every tool argument against
    the fixed menus independently of any model text.
    """

    def __init__(self, persona_cards: Sequence[Mapping[str, Any]] | None = None):
        self.persona_cards = list(persona_cards or [])

    def responses(self, competitor: Mapping[str, Any] | str, move: Mapping[str, Any]) -> list[dict[str, Any]]:
        raise NotImplementedError(
            "LLMResponseProvider is an integration seam; subagent context "
            "receives only schema-validated structured facts"
        )

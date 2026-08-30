"""Gather competitor prices and news through the tool router."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from orchestrator.tool_router import ToolRouter
from orchestrator.trace import emit

from .extract import extract_facts, validate_persona_card

_REPO_ROOT = Path(__file__).resolve().parent.parent
_FIXTURE_PATH = _REPO_ROOT / "contracts" / "fixtures" / "company.json"
_MAX_NEWS_URLS = 3


def _load_fixture_company():
    with _FIXTURE_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


_FIXTURE_COMPANY = _load_fixture_company()


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fallback_price(competitor):
    name = competitor.get("name")
    url = competitor.get("url")
    for item in _FIXTURE_COMPANY.get("competitors", []):
        if item.get("name") == name or item.get("url") == url:
            return float(item["price"])
    price = competitor.get("price")
    if isinstance(price, (int, float)) and not isinstance(price, bool):
        return float(price)
    raise ValueError("no fallback price for %s" % name)


def _clip_news_urls(result):
    urls = []
    if not isinstance(result, list):
        return urls
    for item in result:
        if isinstance(item, str) and item:
            urls.append(item)
        if len(urls) == _MAX_NEWS_URLS:
            break
    return urls


def _snapshot_store(session):
    snaps = session.get("snapshots")
    if not isinstance(snaps, dict):
        snaps = {}
        session["snapshots"] = snaps
    return snaps


def _persist_snapshot(session, url, content):
    """Store scraped bytes content-addressed by sha256 digest."""
    snaps = _snapshot_store(session)
    digest = _sha256_text(content)
    snaps[digest] = {"url": url, "ts": _now(), "content": content}
    return digest


def gather(session, company, client, router):
    """Scrape each competitor through the router and return persona cards.

    Registers scrape_as_markdown and search_engine on the router, then
    dispatches only through router.call. Direct client use is not part of
    this surface.
    """
    if not isinstance(router, ToolRouter):
        raise TypeError(
            "gather requires a ToolRouter; competitor pages are never fetched around it"
        )

    def scrape_as_markdown(url):
        return client.scrape_as_markdown(url)

    def search_engine(query):
        return client.search_engine(query)

    router.register("brightdata.scrape_as_markdown", scrape_as_markdown)
    router.register("brightdata.search_engine", search_engine)

    _snapshot_store(session)

    cards = []
    for competitor in company.get("competitors") or []:
        name = competitor["name"]
        url = competitor["url"]

        emit(
            session,
            "orchestrator",
            "doing",
            "checking %s's pricing page" % name,
            tool="brightdata.scrape_as_markdown",
            detail={"url": url},
        )
        content = router.call("brightdata.scrape_as_markdown", url=url)
        if not isinstance(content, str):
            content = "" if content is None else str(content)

        _persist_snapshot(session, url, content)

        facts = extract_facts(content, competitor=name)
        price = facts["price"]
        price_unknown = price is None
        if price_unknown:
            price = _fallback_price(competitor)
            notes = "price unknown"
            emit(
                session,
                "orchestrator",
                "did",
                "price unknown for %s; using the listed backup price" % name,
                tool="brightdata.scrape_as_markdown",
                detail={
                    "url": url,
                    "price": price,
                    "status": "price unknown",
                    "fallback": True,
                },
            )
        else:
            notes = facts["notes"]
            emit(
                session,
                "orchestrator",
                "did",
                "checked %s's pricing page" % name,
                tool="brightdata.scrape_as_markdown",
                detail={"url": url, "price": price},
            )

        emit(
            session,
            "orchestrator",
            "doing",
            "looking up news about %s" % name,
            tool="brightdata.search_engine",
            detail={"query": name},
        )
        search_result = router.call("brightdata.search_engine", query=name)
        news_urls = _clip_news_urls(search_result)
        emit(
            session,
            "orchestrator",
            "did",
            "attached news links for %s" % name,
            tool="brightdata.search_engine",
            detail={"urls": list(news_urls)},
        )

        card = {
            "competitor": facts["competitor"],
            "price": price,
            "pricing_url": url,
            "news_urls": news_urls,
            "notes": notes,
        }
        validate_persona_card(card)
        cards.append(card)

    return cards

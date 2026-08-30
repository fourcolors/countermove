"""Draft a company summary from a public site scraped through the tool router."""

import copy
import hashlib
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from gather.client import MirrorScrapeClient
from gather.extract import extract_facts, extract_price
from orchestrator.tool_router import ToolRouter
from orchestrator.trace import emit

_REPO_ROOT = Path(__file__).resolve().parent.parent
_FIXTURE_PATH = _REPO_ROOT / "contracts" / "fixtures" / "company.json"
_DEFAULT_MIRRORS = _REPO_ROOT / "mirrors"
_ACME_MIRROR = "acme-stay.html"

ACME_SITE_URL = "https://acme-stay.example/"
ACME_SITE_URLS = frozenset(
    {
        "https://acme-stay.example",
        "https://acme-stay.example/",
        "https://acme-stay.example/pricing",
    }
)

# B2B with switching costs from the Scoring section; mid is the midpoint.
DEFAULT_ELASTICITY = {"low": -0.9, "mid": -0.8, "high": -0.7}
DEFAULT_CROSS_ELASTICITY = 0.4

_PLAN_TAG = re.compile(
    r"(?is)<([a-z][a-z0-9]*)\b([^>]*\bdata-plan\s*=\s*['\"][^'\"]+['\"][^>]*)>"
    r"(.*?)</\1\s*>"
)
_SEGMENT_TAG = re.compile(
    r"(?is)<[a-z][a-z0-9]*\b([^>]*\bdata-segment\s*=\s*['\"][^'\"]+['\"][^>]*)>"
)
_ATTR = re.compile(r"""([:\w-]+)\s*=\s*(['"])(.*?)\2""")
_H1 = re.compile(r"(?is)<h1\b[^>]*>(.*?)</h1>")
_TITLE = re.compile(r"(?is)<title\b[^>]*>(.*?)</title>")
_TAGS = re.compile(r"<[^>]+>")
_DOLLAR = re.compile(r"\$\s*(\d+(?:\.\d{1,2})?)")


class AcmeMirrorClient:
    """Serve the committed Acme Stay mirror, then defer to MirrorScrapeClient.

    Unknown non-Acme URLs still raise through the inner gather client.
    Never touches the network.
    """

    def __init__(self, mirrors_dir=None, inner=None):
        self.mirrors_dir = (
            Path(mirrors_dir) if mirrors_dir is not None else _DEFAULT_MIRRORS
        )
        self.inner = inner if inner is not None else MirrorScrapeClient(
            mirrors_dir=self.mirrors_dir
        )

    def scrape_as_markdown(self, url):
        if url in ACME_SITE_URLS:
            path = self.mirrors_dir / _ACME_MIRROR
            if not path.is_file():
                raise ValueError("unknown url: %s" % url)
            return path.read_text(encoding="utf-8")
        return self.inner.scrape_as_markdown(url)

    def search_engine(self, query):
        return self.inner.search_engine(query)


def draft_company(url, client, router, session):
    """Scrape the company site through the router and return a company dict.

    Plans and prices come from structured extraction of the page. The three
    known competitors are attached from the frozen company fixture. Missing
    elasticity is filled with the labeled B2B default range.
    """
    if not isinstance(router, ToolRouter):
        raise TypeError(
            "draft_company requires a ToolRouter; the company site is never fetched around it"
        )

    def scrape_as_markdown(url):
        return client.scrape_as_markdown(url)

    router.register("brightdata.scrape_as_markdown", scrape_as_markdown)

    emit(
        session,
        "orchestrator",
        "doing",
        "checking the company website",
        tool="brightdata.scrape_as_markdown",
        detail={"url": url},
    )
    content = router.call("brightdata.scrape_as_markdown", url=url)
    if not isinstance(content, str):
        content = "" if content is None else str(content)

    if session.get("snapshots") is None:
        session["snapshots"] = []
    session["snapshots"].append(
        {
            "url": url,
            "digest": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )

    facts = extract_facts(content)
    page_price = extract_price(content)
    name = _extract_name(content) or "Company"
    plans = _extract_plans(content, page_price)
    segments = _extract_segments(content)
    used_default_elasticity = False
    for plan in plans:
        plan["segments"] = [
            _with_elasticity_defaults(copy.deepcopy(segment))
            for segment in segments
        ]
        if any(item.get("assumed") for item in plan["segments"]):
            used_default_elasticity = True

    competitors = _known_competitors()
    company = {"name": name, "plans": plans, "competitors": competitors}

    emit(
        session,
        "orchestrator",
        "did",
        "read the company website",
        tool="brightdata.scrape_as_markdown",
        detail={
            "url": url,
            "price": facts.get("price") if facts.get("price") is not None else page_price,
        },
    )
    emit(
        session,
        "orchestrator",
        "did",
        _plans_sentence(plans),
        detail={"plans": [{"id": item["id"], "price": item["price"]} for item in plans]},
    )
    if used_default_elasticity:
        emit(
            session,
            "orchestrator",
            "did",
            "filled in a typical price-sensitivity range because none was listed, and marked it assumed, not measured",
            detail={"elasticity": copy.deepcopy(DEFAULT_ELASTICITY), "assumed": True},
        )
    emit(
        session,
        "orchestrator",
        "did",
        "competitors and prices from the demo fixture (assumed)",
        detail={"competitors": copy.deepcopy(competitors)},
    )

    session["company"] = company
    return company


def _known_competitors():
    with _FIXTURE_PATH.open(encoding="utf-8") as handle:
        fixture = json.load(handle)
    competitors = copy.deepcopy(fixture["competitors"])
    for competitor in competitors:
        competitor["assumed"] = True
    return competitors


def _extract_name(content):
    match = _H1.search(content)
    if match:
        name = _plain(match.group(1))
        if name:
            return name
    match = _TITLE.search(content)
    if match:
        name = _plain(match.group(1))
        if name:
            return name.split(" - ")[0].strip()
    return None


def _extract_plans(content, fallback_price):
    plans = []
    seen = set()
    for match in _PLAN_TAG.finditer(content):
        attrs = _attrs(match.group(2))
        plan_id = (attrs.get("data-plan") or "").strip()
        if not plan_id or plan_id.lower() in seen:
            continue
        body = match.group(3)
        dollar = _DOLLAR.search(body)
        if dollar:
            price = _as_number(dollar.group(1))
        elif fallback_price is not None:
            price = _as_number(fallback_price)
        else:
            continue
        plans.append({"id": plan_id, "price": price, "segments": []})
        seen.add(plan_id.lower())
    if not plans and fallback_price is not None:
        raise ValueError(
            "the page has a price but no plan name I can use; I will not guess a plan"
        )
    if not plans:
        raise ValueError("I could not find a plan and price on that page")
    return plans


def _extract_segments(content):
    segments = []
    seen = set()
    for match in _SEGMENT_TAG.finditer(content):
        attrs = _attrs(match.group(1))
        segment_id = (attrs.get("data-segment") or "").strip()
        if not segment_id or segment_id.lower() in seen:
            continue
        customers = _optional_number(attrs.get("data-customers"), 0)
        churn = _optional_number(attrs.get("data-monthly-churn"), 0)
        segments.append(
            {
                "id": segment_id,
                "customers": customers,
                "monthly_churn": churn,
            }
        )
        seen.add(segment_id.lower())
    if not segments:
        segments.append({"id": "customers", "customers": 0, "monthly_churn": 0})
    return segments


def _with_elasticity_defaults(segment):
    if not _has_elasticity(segment.get("elasticity")):
        segment["elasticity"] = copy.deepcopy(DEFAULT_ELASTICITY)
        segment["assumed"] = True
    if "cross_elasticity" not in segment:
        segment["cross_elasticity"] = DEFAULT_CROSS_ELASTICITY
    return segment


def _has_elasticity(value):
    if not isinstance(value, dict):
        return False
    return all(key in value for key in ("low", "mid", "high"))


def _plans_sentence(plans):
    if not plans:
        return "did not find a plan on the company website"
    parts = []
    for plan in plans:
        price = plan["price"]
        shown = str(int(price)) if price == int(price) else str(price)
        parts.append("the %s plan at $%s" % (plan["id"], shown))
    if len(parts) == 1:
        return "found %s" % parts[0]
    return "found %s" % ", ".join(parts)


def _attrs(blob):
    found = {}
    for match in _ATTR.finditer(blob or ""):
        found[match.group(1).lower()] = html.unescape(match.group(3))
    return found


def _plain(text):
    stripped = _TAGS.sub(" ", text or "")
    stripped = html.unescape(stripped)
    return re.sub(r"\s+", " ", stripped).strip()


def _optional_number(raw, default):
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return _as_number(raw)
    except (TypeError, ValueError):
        return default


def _as_number(value):
    number = float(value)
    if number != number:
        raise ValueError("not a number")
    if number == int(number):
        return int(number)
    return number

"""Scrape clients for gather.

MirrorScrapeClient serves the committed snapshot pages under mirrors/.
BrightDataScrapeClient is the live-MCP adapter seam and does not call the network.
"""

from abc import ABC, abstractmethod
from pathlib import Path
import re

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_MIRRORS = _REPO_ROOT / "mirrors"

KNOWN_URLS = {
    "https://rival-a.example/pricing": "rival-a.html",
    "https://rival-b.example/pricing": "rival-b.html",
    "https://rival-c.example/pricing": "rival-c.html",
}


class ScrapeClient(ABC):
    """Page fetch and search. Callers reach these methods through the tool router."""

    @abstractmethod
    def scrape_as_markdown(self, url):
        """Return page content for url as a string."""

    @abstractmethod
    def search_engine(self, query):
        """Return a list of result URLs for query."""


class MirrorScrapeClient(ScrapeClient):
    """Serve committed snapshot mirrors for the three rival pricing URLs.

    Unknown URLs raise. search_engine returns local stand-in URLs and
    never touches the network.
    """

    def __init__(self, mirrors_dir=None):
        self.mirrors_dir = Path(mirrors_dir) if mirrors_dir is not None else _DEFAULT_MIRRORS

    def scrape_as_markdown(self, url):
        if url not in KNOWN_URLS:
            raise ValueError("unknown url: %s" % url)
        path = self.mirrors_dir / KNOWN_URLS[url]
        if not path.is_file():
            raise ValueError("unknown url: %s" % url)
        return path.read_text(encoding="utf-8")

    def search_engine(self, query):
        if not isinstance(query, str):
            raise TypeError("query must be a string")
        slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-") or "search"
        return [
            "https://news.example/%s-funding" % slug,
            "https://news.example/%s-pricing" % slug,
            "https://news.example/%s-launch" % slug,
            "https://news.example/%s-extra" % slug,
        ]


class BrightDataScrapeClient(ScrapeClient):
    """Adapter seam for live Bright Data MCP.

    Real calls go through Bright Data MCP with BRIGHTDATA_API_TOKEN
    from the environment - never hardcode.
    """

    def scrape_as_markdown(self, url):
        raise NotImplementedError(
            "BrightDataScrapeClient is the adapter seam for Bright Data MCP; "
            "real calls go through Bright Data MCP with BRIGHTDATA_API_TOKEN "
            "from the environment - never hardcode"
        )

    def search_engine(self, query):
        raise NotImplementedError(
            "BrightDataScrapeClient is the adapter seam for Bright Data MCP; "
            "real calls go through Bright Data MCP with BRIGHTDATA_API_TOKEN "
            "from the environment - never hardcode"
        )

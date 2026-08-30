"""Gather competitor data through the tool router.

Public surface: `gather(session, company, client, router)`.
Scrape and search always go through the router, never around it.
"""

from .client import BrightDataScrapeClient, MirrorScrapeClient, ScrapeClient
from .extract import extract_facts, extract_price
from .run import gather

__all__ = [
    "BrightDataScrapeClient",
    "MirrorScrapeClient",
    "ScrapeClient",
    "extract_facts",
    "extract_price",
    "gather",
]

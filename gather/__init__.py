"""Gather competitor data through the tool router.

Public surface: `gather(session, company, client, router)`.
Scrape and search always go through the router, never around it.
Clients live in `gather.client` and are not exported.
"""

from .run import gather

__all__ = ["gather"]

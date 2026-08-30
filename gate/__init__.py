"""Narrow public API for Countermove's human approval gate."""

from .pending import build_pending_action
from .service import GateService

__all__ = ["GateService", "build_pending_action"]

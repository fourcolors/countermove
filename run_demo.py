#!/usr/bin/env python3
"""Countermove demo driver: one typed sentence to a queued, gated action.

Runs the full pipeline against the committed mirrors and writes the
session JSON that ui/ renders. The gate's Allow path is exposed by
serve_demo.py; nothing here writes remotely.
"""

import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from orchestrator.session_store import SessionStore
from orchestrator.tool_router import ToolRouter
from orchestrator.trace import emit
from bootstrap.move_parse import parse_move
from bootstrap.llm_parse import (
    accept_normalized_move,
    normalize_move,
    reconstruct_canonical,
)
from bootstrap.company_draft import draft_company
import gather as gather_mod
from tree import build, responses
from tree.recommend import recommend
from gate.pending import build_pending_action
from flow.entry import start_session, consume, begin_tree

SESSION_DIR = Path(__file__).parent / "session"
MIRRORS = Path(__file__).parent / "mirrors"


def main(sentence: str, runner=None):
    client = importlib.import_module("gather.client").MirrorScrapeClient(str(MIRRORS))
    ctx = start_session(str(SESSION_DIR), client, ToolRouter)
    session = consume(ctx)
    if ctx["previous_decision"]:
        print("previous decision:", ctx["previous_decision"].get("reason"))
    if ctx["watch_result"].get("trigger"):
        print("watch check:", ctx["watch_result"])

    router = ToolRouter(session)
    company = draft_company("https://acme-stay.example", client, router, session)
    session["company"] = company

    move = parse_move(sentence, company)
    if not isinstance(move, dict):
        normalized = normalize_move(
            sentence, company, runner=runner, strict_reply=move.reply
        )
        if isinstance(normalized, str):
            move = accept_normalized_move(sentence, normalized, company)
            if isinstance(move, dict):
                emit(
                    session,
                    "orchestrator",
                    "did",
                    "interpreted your message as: %s" % reconstruct_canonical(move),
                )
            else:
                SessionStore(str(SESSION_DIR)).save(session)
                print(move.reply)
                return move
        else:
            SessionStore(str(SESSION_DIR)).save(session)
            print(normalized.reply)
            return normalized
    session["move"] = move
    emit(session, "orchestrator", "did", f"understood the move: {move['plan']} ${move['from']} to ${move['to']}")

    personas = gather_mod.gather(session, company, client, router)
    tree = build.build_tree(company, move, responses.FixtureResponseProvider(personas or _personas_from(session, company)), session=session)
    session["tree"] = tree

    rec = recommend(tree)
    session["recommendation"] = rec
    emit(session, "orchestrator", "did", "recommendation ready: " + rec["sentence"])

    pending = build_pending_action(tree, rec, move, company)
    from gate.service import GateService
    from gate.repo import LocalRepoClient
    gs = GateService(session, None)
    gs.queue(pending)
    SessionStore(str(SESSION_DIR)).save(session)
    print("root:", tree["root_hash"][:16], "| leaves:",
          sum(1 for n in tree["nodes"] if n["id"].startswith("leaf-")),
          "| pending:", pending["sentence"])


def _personas_from(session, company):
    cards = session.get("persona_cards")
    if cards:
        return cards
    return [{"competitor": c["name"], "price": c["price"],
             "pricing_url": c["url"], "news_urls": [], "notes": f"price {c['price']}"}
            for c in company["competitors"]]


if __name__ == "__main__":
    main(" ".join(sys.argv[1:]) or "Raise Pro from $49 to $59 effective 2026-09-07")

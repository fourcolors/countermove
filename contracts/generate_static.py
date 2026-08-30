#!/usr/bin/env python3
"""Throwaway S0 generator for contracts/ schemas, jargon map, and static fixtures."""

import json
from pathlib import Path

HERE = Path(__file__).parent
S = "http://json-schema.org/draft-07/schema#"


def w(rel, obj):
    p = HERE / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2) + "\n")


NUM = {"type": "number"}
STR = {"type": "string"}
PCT = {"anyOf": [{"type": "number"}, {"const": "n/a"}],
       "description": "percent of baseline revenue, or 'n/a' when baseline is zero"}
ELASTICITY = {"type": "object", "required": ["low", "mid", "high"],
              "properties": {"low": NUM, "mid": NUM, "high": NUM},
              "description": "low is the more-negative endpoint; scalar e expands to {e-0.15, e, e+0.15}, high clamped below 0"}

w("company.schema.json", {"$schema": S, "title": "company", "type": "object",
  "required": ["name", "plans", "competitors"],
  "properties": {
    "name": STR,
    "plans": {"type": "array", "items": {"type": "object", "required": ["id", "price", "segments"],
      "properties": {"id": STR, "price": NUM,
        "segments": {"type": "array", "items": {"type": "object",
          "required": ["id", "customers", "monthly_churn", "elasticity", "cross_elasticity"],
          "properties": {"id": STR, "customers": NUM, "monthly_churn": NUM,
                         "elasticity": ELASTICITY, "cross_elasticity": NUM,
                         "assumed": {"type": "boolean", "description": "true when defaults were applied; UI labels it 'assumed, not measured'"}}}}}}},
    "competitors": {"type": "array", "items": {"type": "object", "required": ["name", "url", "price"],
      "properties": {"name": STR, "url": STR, "price": NUM}}}}})

w("move.schema.json", {"$schema": S, "title": "move", "type": "object",
  "required": ["plan", "from", "to", "action", "effective"],
  "properties": {"plan": STR, "from": NUM, "to": NUM,
                 "action": {"const": "open_pr"}, "effective": {"type": "string", "format": "date"}}})

w("tree_node.schema.json", {"$schema": S, "title": "tree_node", "type": "object",
  "required": ["id", "parent", "actor", "label", "choice", "price_before", "price_after",
               "reasoning", "sources", "assumptions", "score", "hash", "children"],
  "properties": {
    "id": STR, "parent": {"type": ["string", "null"]},
    "actor": {"enum": ["you", "competitor"]}, "label": STR,
    "choice": {"enum": ["price_change", "undercut", "match", "ignore", "raise",
                        "hold", "partial_rollback", "annual_discount"]},
    "price_before": NUM, "price_after": NUM, "reasoning": STR,
    "sources": {"type": "array", "items": STR},
    "assumptions": {"type": "object"},
    "score": {"anyOf": [{"type": "null"}, {"type": "object",
      "required": ["low", "mid", "high", "low_pct", "mid_pct", "high_pct"],
      "properties": {"low": NUM, "mid": NUM, "high": NUM,
                     "low_pct": PCT, "mid_pct": PCT, "high_pct": PCT}}]},
    "hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    "children": {"type": "array", "items": STR}}})

w("score_result.schema.json", {"$schema": S, "title": "score_result", "type": "object",
  "required": ["leaf_id", "low", "mid", "high", "low_pct", "mid_pct", "high_pct", "assumptions"],
  "properties": {"leaf_id": STR, "low": NUM, "mid": NUM, "high": NUM,
                 "low_pct": PCT, "mid_pct": PCT, "high_pct": PCT,
                 "assumptions": {"type": "object"}}})

w("trace_event.schema.json", {"$schema": S, "title": "trace_event", "type": "object",
  "required": ["ts", "actor", "column", "text"],
  "properties": {"ts": {"type": "string", "format": "date-time"},
                 "actor": STR,
                 "column": {"enum": ["doing", "waiting", "did"]},
                 "text": {"type": "string", "description": "plain language, no jargon"},
                 "tool": {"type": ["string", "null"]},
                 "detail": {"type": "object"}}})

w("pending_action.schema.json", {"$schema": S, "title": "pending_action", "type": "object",
  "required": ["id", "sentence", "diff", "memo_markdown", "winning_branch_id", "root_hash", "status"],
  "properties": {"id": STR,
                 "sentence": {"type": "string", "description": "e.g. 'Open a change request to raise Pro to $59 on Sept 7?'"},
                 "diff": STR, "memo_markdown": STR, "winning_branch_id": STR,
                 "root_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                 "status": {"enum": ["waiting", "approved", "denied"]},
                 "deny_reason": {"type": ["string", "null"]}}})

w("recommendation.schema.json", {"$schema": S, "title": "recommendation", "type": "object",
  "required": ["path_id", "sentence", "band", "runner_up_id", "runner_up_reason",
               "sensitivity", "watch_trigger"],
  "properties": {"path_id": STR, "sentence": STR,
                 "band": {"type": "object", "required": ["low_pct", "mid_pct", "high_pct"],
                          "properties": {"low_pct": NUM, "mid_pct": NUM, "high_pct": NUM}},
                 "runner_up_id": STR, "runner_up_reason": STR,
                 "sensitivity": {"type": "object", "required": ["flips_ranking", "statement"],
                                 "properties": {"flips_ranking": {"type": "boolean"}, "statement": STR}},
                 "watch_trigger": {"type": "object",
                                   "required": ["competitor", "threshold", "window_days", "statement"],
                                   "properties": {"competitor": STR, "threshold": NUM,
                                                  "window_days": NUM, "statement": STR}}}})

w("persona_card.schema.json", {"$schema": S, "title": "persona_card", "type": "object",
  "required": ["competitor", "price", "pricing_url", "news_urls"],
  "properties": {"competitor": STR, "price": NUM, "pricing_url": STR,
                 "news_urls": {"type": "array", "maxItems": 3, "items": STR},
                 "notes": {"type": "string", "description": "schema-validated structured facts only; never raw page text"}}})

w("jargon.json", {
  "elasticity": {"plain": "price sensitivity",
                 "levels": {"low": "elasticity high end above -0.9",
                            "medium": "-0.9 to -1.3", "high": "below -1.3"},
                 "thresholds": {"comment": "classify by mid elasticity: e > medium_min -> low sensitivity; e < high_max -> high; else medium",
                                "medium_min": -0.9, "high_max": -1.3}},
  "cross_elasticity": {"plain": "how much your customers watch competitor prices",
                       "levels": {"a little": "below 0.3", "some": "0.3 to 0.6", "a lot": "above 0.6"},
                       "thresholds": {"some_min": 0.3, "a_lot_min": 0.6}},
  "monthly_churn": {"plain": "customers who leave each month"},
  "score_band": {"plain": "likely change in revenue over 6 months",
                 "format": "{mid_pct}% (between {low_pct}% and {high_pct}%)"}})

w("fixtures/company.json", {"name": "Acme Stay", "plans": [{"id": "pro", "price": 49,
  "segments": [
    {"id": "smb", "customers": 300, "monthly_churn": 0.04,
     "elasticity": {"low": -1.25, "mid": -1.1, "high": -0.95}, "cross_elasticity": 0.4},
    {"id": "mid", "customers": 120, "monthly_churn": 0.02,
     "elasticity": {"low": -0.95, "mid": -0.8, "high": -0.65}, "cross_elasticity": 0.3}]}],
  "competitors": [{"name": "Rival A", "url": "https://rival-a.example/pricing", "price": 45},
                  {"name": "Rival B", "url": "https://rival-b.example/pricing", "price": 52},
                  {"name": "Rival C", "url": "https://rival-c.example/pricing", "price": 47}]})

w("fixtures/move.json", {"plan": "pro", "from": 49, "to": 59, "action": "open_pr", "effective": "2026-09-07"})

# Derive per-leaf fixtures from the tree so shared leaf ids can never disagree.
tree = json.loads((HERE / "fixtures" / "tree.json").read_text())
leaves = {n["id"]: n for n in tree["nodes"]}

sr_leaf = leaves["leaf-rival-a-undercut-hold"]
w("fixtures/score_result.json", {"leaf_id": sr_leaf["id"],
  **{k: sr_leaf["score"][k] for k in ("low", "mid", "high", "low_pct", "mid_pct", "high_pct")},
  "assumptions": {"eps": {"low": -1.25, "mid": -1.1, "high": -0.95}, "eta": 0.4,
                  "c_prime_convention": "mean of all three competitors' price_after; non-responders keep last scraped price"}})

w("fixtures/trace_events.json", [
  {"ts": "2026-08-29T17:01:00Z", "actor": "orchestrator", "column": "did",
   "text": "checked Rival A's pricing page", "tool": "brightdata.scrape_as_markdown",
   "detail": {"url": "https://rival-a.example/pricing", "price": 45}},
  {"ts": "2026-08-29T17:01:20Z", "actor": "rival-a-agent", "column": "doing",
   "text": "deciding how Rival A responds", "tool": None, "detail": {}},
  {"ts": "2026-08-29T17:02:00Z", "actor": "orchestrator", "column": "waiting",
   "text": "waiting for your approval", "tool": None, "detail": {}}])

w("fixtures/pending_action.json", {"id": "act-1",
  "sentence": "Open a change request to raise Pro to $59 on Sept 7?",
  "diff": "--- a/pricing.yaml\n+++ b/pricing.yaml\n@@ -1,3 +1,3 @@\n plan: pro\n-price: 49\n+price: 59\n",
  "memo_markdown": "# Decision memo\n\nWinning branch: hold after Rival A ignores.\n",
  "winning_branch_id": "leaf-rival-a-ignore-hold",
  "root_hash": "fac0a6c8240bdbd9582a82d675ea6c00a7dcd4bc057348f1f400406a256c3a6b",
  "status": "waiting", "deny_reason": None})

rec_leaf = leaves["leaf-rival-a-ignore-hold"]
w("fixtures/recommendation.json", {"path_id": rec_leaf["id"],
  "sentence": "Raise Pro to $59 and hold even if Rival A ignores it.",
  "band": {k: rec_leaf["score"][k] for k in ("low_pct", "mid_pct", "high_pct")},
  "runner_up_id": "leaf-rival-a-undercut-partial_rollback",
  "runner_up_reason": "Partial rollback protects fewer customers than it costs in revenue.",
  "sensitivity": {"flips_ranking": False,
                  "statement": "No price-sensitivity range end flips the ranking; other assumptions are editable but not sensitivity-ranked."},
  "watch_trigger": {"competitor": "Rival A", "threshold": 42, "window_days": 30,
                    "statement": "Rival A below $42 within 30 days would flip this recommendation."}})

w("fixtures/persona_cards.json", [
  {"competitor": "Rival A", "price": 45, "pricing_url": "https://rival-a.example/pricing",
   "news_urls": ["https://news.example/rival-a-funding"], "notes": "price 45; plan count 3"},
  {"competitor": "Rival B", "price": 52, "pricing_url": "https://rival-b.example/pricing",
   "news_urls": [], "notes": "price 52"},
  {"competitor": "Rival C", "price": 47, "pricing_url": "https://rival-c.example/pricing",
   "news_urls": [], "notes": "price 47"}])

print("wrote schemas, jargon map, and static fixtures")

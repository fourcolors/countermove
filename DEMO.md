# Demo runbook

## One-time setup

1. `python3 -c "import shutil; shutil.rmtree('session', ignore_errors=True)"` - fresh session.
2. `python3 run_demo.py "Raise Pro from $49 to $59 effective 2026-09-07"` - runs the full pipeline (bootstrap -> gather -> 36-leaf tree -> recommendation -> queued action).
3. `GATE_REMOTE=1 python3 serve_demo.py 8420` - serves the UI; Approve opens a REAL PR on fourcolors/acme-stay-pricing via gh. Omit GATE_REMOTE for rehearsal (writes to session/local-pricing instead).
4. Open http://localhost:8420/ - the live session renders.

## The 3-minute script (beats from countermove.md)

- 0:00 type/show the move sentence; 0:20 company card (correct one number);
- 0:45 trace shows the routed scrape calls and prices; 1:15 open a response, click a counter, read the band sentence;
- 1:50 advanced view on, tweak an assumption (edit-rerun API);
- 2:15 approval card: click "Not now" with a reason, then Approve - the PR opens live;
- 2:40 cut to the pre-staged Qodo-reviewed PR on acme-stay-pricing (label it "a prior run's PR" on camera);
- 2:50 close on the doing / waiting / did trace.

## Pre-staged Qodo PR (before filming)

Requires the Qodo app installed on acme-stay-pricing. Then run one rehearsal
with GATE_REMOTE=1, Approve, and leave that PR open with its Qodo review as
the cut-to target.

## Rehearsal checklist

- [ ] fresh session + driver run prints "root ... | leaves: 36 | pending ..."
- [ ] page loads with zero console errors
- [ ] band sentence shows rounded percents
- [ ] Not now with a reason lands in did as denied
- [ ] Approve opens the PR (URL in trace/did)
- [ ] Qodo review visible on the pre-staged PR

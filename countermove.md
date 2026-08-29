# Countermove - scope and build plan

Working name. Change it if Sterling has a better one.

## The job

Give it one business move and your company's basics. It pulls live competitor data, simulates the full move-and-response tree with subagents, scores every path in a sandbox, recommends a path, and asks a human once before executing the chosen move.

Who hires it: a founder or operator with a specific, irreversible move this week. A pricing change is the only move type in v0.

## In / out for today

In: one move type (price change on one plan), depth-two tree, three competitors, price-shaped counter-moves only, one gated action, synthetic company with real competitors, single-page UI.

Out: non-price moves, deeper trees, CRM or database connectors, auth, multi-user, any FlowStay or Property.bot data, the MiroFish codebase (AGPL - ideas only).

## Who uses it

A business owner, not an engineer. Every screen passes this test: no YAML, no code, no field a non-technical person couldn't fill from memory.

- The interface is a conversation. The agent asks one question at a time and renders results inline: the company summary as an editable card, the tree as a widget, the pending action as an approval card.
- Jargon is translated everywhere it appears. Elasticity → "price sensitivity: low / medium / high" (mapped to the ranges below). Monthly churn → "customers who leave each month." Cross-price elasticity → "how much your customers watch competitor prices: a little / some / a lot." Score band → "likely change in revenue over 6 months: +6% (between −1% and +11%)."
- The approval card is a sentence and a diff, not a payload: "Open a change request to raise Pro to $59 on Sept 7? This changes pricing.yaml and adds a decision memo." Buttons say Approve and Not now.
- Advanced view is one toggle away for anyone who wants the raw numbers and the script.
- Stretch: expose the orchestrator as an MCP server with `setup_company`, `evaluate_move`, `approve_action`, so the same flow runs from Claude Desktop, Claude Code, or Codex. Distribution story for the write-up; not the demo surface.

## Components

1. **UI** - one page, chat-first. The conversation drives setup, the move, and the decision. Inline widgets: company card, tree, approval card. A trace panel shows doing / waiting / did in plain language ("checking Rival A's pricing page", "waiting for your approval", "opened change request #12").
2. **Orchestrator** - runs on TrueForge. Owns the session, spawns subagents, calls tools, pauses at the gate.
3. **Tools** - Bright Data MCP (`scrape_as_markdown`, `search_engine`), TrueForge sandbox exec, GitHub MCP (read repo, open PR). Nothing else.
4. **Subagents** - one per competitor. Forced-choice response from a menu, with reasoning and the data used.
5. **Scorer** - `score.py`, checked into the repo, run in the sandbox.
6. **Session store** - JSON on disk. Company, moves, trees, decisions, scrape snapshots.
7. **Provenance lib** - `provenance.py`: `canonical()` serialization and Merkle hashing per the Provenance section, used by the tree builder, the what-if path, and the memo writer.
8. **Gate service** - holds the GitHub write credential and mints approval tokens from human Allow clicks. The only component that can write remotely.

Contracts: the JSON schemas and fixtures for company, move, tree node, score result, trace event, pending action, recommendation, and persona card - plus the jargon map and a reference-hashed fixture tree - live in `contracts/` and are frozen in the rails slice, so every other slice builds against fixtures in parallel.

## Data shapes

```yaml
# company.yaml - drafted by the agent from the URL, corrected by the human
name: Acme Stay
plans:
  - id: pro
    price: 49
    segments:
      - id: smb        # name, customers, monthly_churn, elasticity range, cross_elasticity
        customers: 300
        monthly_churn: 0.04
        elasticity: { low: -1.25, mid: -1.1, high: -0.95 }   # a scalar input expands to +/-0.15
        cross_elasticity: 0.4
      - id: mid
        customers: 120
        monthly_churn: 0.02
        elasticity: { low: -0.95, mid: -0.8, high: -0.65 }
        cross_elasticity: 0.3
competitors:
  - name: Rival A
    url: https://rival-a.example/pricing
    price: 45
```

```yaml
# move.yaml - one sentence in, structured out
plan: pro
from: 49
to: 59
action: open_pr            # v0: PR to the company's pricing config + decision memo
effective: 2026-09-07
```

Tree node: `{ id, parent, actor: "you" | "competitor", label, choice, price_before, price_after, reasoning, sources: [urls], score: { low, mid, high }, assumptions: {...} }`

Competitor response menu with fixed price semantics (each editable as a per-node assumption): `undercut` = 5% below your new price, `match` = your new price, `ignore` = unchanged, `raise` = 5% above their current price. Every response node carries numeric `price_before` and `price_after` computed by these rules - a categorical choice alone is not a valid node. Your counter menu: `hold`, `partial_rollback`, `annual_discount`.

`C` and `C'` convention: `C'` is the mean of all three competitors' `price_after`, where the two non-responding competitors in a branch keep their last scraped price. This convention is displayed as an editable assumption on every leaf.

## Scoring (score.py)

Per segment `s`: `P` current price, `P'` your price after the move and your counter, `C` and `C'` competitor average price before and after their response, `N` customers, `m` monthly churn, `eps` own-price elasticity, `eta` cross-price elasticity, `months` = 6.

```
price_factor    = clamp((P'/P) ** eps * (C'/C) ** eta, 0, 1)
customer_months = N * price_factor * sum((1 - m) ** t for t in 1..months)
revenue         = customer_months * P' - move_cost
score           = sum(revenue over segments) - baseline_revenue
score_percent   = 100 * score / baseline_revenue
```

Definitions that remove all implementation freedom:

- `baseline_revenue` is the same formula evaluated at `P' = P`, `C' = C`, `move_cost = 0`, with the same monthly sum, summed over the same segments.
- Revenue sums the decaying customer base month by month (the `customer_months` sum), never end-of-horizon customers times `months`.
- `move_cost` is 0 for every move and counter except `annual_discount`.
- Counter-move semantics: `hold` keeps `P'` at the moved price, cost 0. `partial_rollback` moves `P'` a fraction back toward the old price (default 50%, editable), cost 0. `annual_discount` keeps `P'` and its `move_cost` is the per-customer discount (default 10% of `P'` times `months`, editable) times the customers who take it (uptake 30% of the segment's `N`, editable), subtracted once per segment, not per month.
- The price factor is capped at 1: a price advantage never invents customers beyond the organically surviving base. Upside from a competitor raising prices is a labeled v0 limitation ("competitor raises don't add customers"), not a silent model choice, because no acquisition mechanism exists in the model.
- `score_percent` is computed separately for low, mid, and high, against the same `baseline_revenue`. If `baseline_revenue` is 0, display "n/a", never a division result.

Run three times per leaf with `eps` at the segment's `low`, `mid`, and `high` (see the elasticity range schema in Data shapes). Report `{low, mid, high}` in dollars and percent. Never print a single confidence percentage.

Defaults with no data, in schema field terms: B2B with switching costs `{low: -0.9, high: -0.7}`; B2B without lock-in `{low: -1.3, high: -1.0}`; consumer `{low: -2.0, high: -1.5}`; `mid` is the midpoint. Cross-price default +0.4. A user-supplied scalar elasticity `e` expands deterministically to `{low: e - 0.15, mid: e, high: e + 0.15}` (high clamped below 0).

Every assumption is displayed next to the score and is editable, including the counter-move parameters above. Editing reruns the script in the sandbox.

## Recommendation

After every leaf is scored, the agent writes a verdict before proposing an action:

1. Recommended path, one sentence, with its score band.
2. Runner-up and why it lost.
3. How sensitive the ranking is to price sensitivity (own-price elasticity), read off the already-computed low and high bands of the top two paths - whether any range end flips the ranking; no extra reruns. Other assumptions are editable but not sensitivity-ranked in v0, and the verdict says so.
4. What to watch after acting: a concrete trigger that would flip the recommendation ("Rival A below $42 within 30 days").

The approval card carries the recommendation's first move. The watch trigger is stored with the decision and checked at the start of the next session.

## Provenance (Merkle tree)

Every node carries `hash = sha256(canonical(content) + child hashes)`. Node content is every field of the node except `hash` itself (see the tree node schema in Data shapes). The root hash is written into the decision memo and the PR body.

`canonical()` is pinned so two implementations cannot disagree: JSON with lexicographically sorted keys (RFC 8785 style), UTF-8, floats rounded half-even to 6 decimal places and serialized in their shortest round-trip decimal form, negative zero normalized to zero, non-finite values invalid, `sources` sorted, segments sorted by id, child hashes concatenated in child-node-id order. Reference vectors covering rounding ties and near-zero values live in `contracts/` and are part of S2's tests.

What verification means, precisely:

- Verification is always recompute-from-stored-content, never regeneration. Anyone can recompute the root from the stored tree; a mismatch means the tree or memo was edited after the decision.
- The root identifies a run, not a function of business inputs. Regenerating a tree from the same company data is NOT expected to reproduce the root - subagent reasoning is not deterministic. What is guaranteed: recomputing hashes from a stored tree always reproduces its root.
- Scrape and search results are persisted as snapshots (content digest + timestamp) alongside the tree, so the sources behind a decision are inspectable after the pages change.
- What-if edits: sandbox rescoring covers only the affected leaves; hash recomputation runs from the changed node up through every ancestor to the root. Off-path nodes keep their hashes; the root always changes.

What this does not protect against, stated honestly: an editor who regenerates the whole tree and updates the memo hash to match produces a consistent forgery. The scheme detects post-decision tampering with a stored trace, nothing more.

Not a chain, not a ledger. Content-addressed provenance for the decision trace.

## Two human moments, not many

- **Simulation** runs with no human input. Every competitor response, every counter-move, every leaf scored. The user reads it afterward.
- **Execution** is one approval, once, at the end. Approve or Not now on the recommendation's first move. This is the TrueForge gate and it never becomes a chain of questions.

**Interactive depth** is a setting for the simulation phase. It controls what happens at nodes where the user would move (their counter after each competitor response):

- `0` (default): the agent assumes the best-scoring counter at every node and finishes the tree. The user analyzes afterward.
- `1`: after competitor responses are in, the agent pauses once and lets the user pick their counter per branch, then scores the rest.

Nothing higher than 1 at depth two. The setting is a plain toggle in the conversation: "Want to choose your counter-moves yourself, or let me pick the best one at each step?"

## The gate

v0 action: open a PR against the company's pricing repo (a small public repo you create today) that changes `pricing.yaml` and adds `decisions/2026-08-29-pro-price.md` with the winning branch, the scores, and the assumptions. Allow opens the PR through GitHub MCP. Deny writes the memo locally with the reason and opens nothing.

Why this action: it's a real write to a real repo, it turns a decision into a diff, and its Qodo review is shown on camera via the pre-staged prior-run PR from the Demo script (a live review takes minutes and never fits the window). If there's time, add "send the announcement" as a second gated action to a mock endpoint. Not before the PR path works.

### Enforcement, by name

Every refusal in this plan has an enforcing actor that is not the model's own judgment:

- **The gate service holds the GitHub write credential.** The orchestrator and subagents never see it. A PR opens only when the gate service receives an approval token minted by a human Allow click in the UI. No token, no write - regardless of what any model decides.
- **`approve_action` over MCP is a request, not an authorization.** It queues the pending action and points at the approval card; the UI click remains the sole authorization event. An agent calling `approve_action` from Claude Desktop, Claude Code, or Codex cannot mint the token.
- **The tool router enforces the allowlist.** Only Bright Data MCP, sandbox exec, and GitHub MCP are registered; any other tool request fails at the router and the refusal is traced.
- **The orchestrator enforces the scrape budget.** A per-subagent counter is checked before dispatch; a second scrape request is refused and traced.

### Untrusted content boundary

Scraped pages and search results are adversarial input. v0 controls:

- The subagent context receives only allowlisted, schema-validated structured facts produced by an isolated extraction stage (price as a number, competitor name as an escaped string, up to three source URLs). Raw page text never enters subagent context in v0 - a delimiter convention would be an instruction to the model, not an enforcement boundary. The subagent's output is forced-choice, and the orchestrator validates the choice and every tool argument against the fixed menus independently of any model text.
- The decision memo and PR body are built from a typed template. Subagent reasoning renders inside a fenced block whose fence length is max(3, longest backtick run in the content + 1) - CommonMark guarantees content cannot terminate such a fence - and is never interpolated into instructions, links, or the diff. The injection test includes reasoning carrying nested fences and Markdown links.
- The demo runs against snapshot mirrors of competitor pages that the team controls, so nothing unvetted can appear on camera.

## Slices

The build is sliced for parallel agent work.
One slice = one agent = one worktree = one branch = one PR.
Work is tracked in `WORK.md` at the repo root - the single source of truth for slice status; GitHub issues are intentionally unused.

**The merge gate, identical for every slice:** a tightly scoped adversarial review of the diff against this slice's AC (run by an independent agent, verdict recorded in WORK.md), plus Qodo's PR review with every High finding fixed or dismissed in-thread.
A slice is done when both reviews pass and the PR is merged by a human.

**S0 - Rails** (serial; everything else waits on it)
Depends: nothing.
AC: TrueForge runs hello-world, and hello-world exercises every extension surface the other slices plug into - it makes one MCP call, one sandbox exec, and emits trace events through a frozen trace-emit API; the tool router is in place with the three-tool allowlist and an automated test shows a request for a fake fourth tool is refused and traced; Qodo is installed and posts a review on the first PR; `contracts/` holds frozen JSON schemas plus fixtures for company, move, tree node, score result, trace event, pending action (approval card), recommendation, and competitor persona card, plus `contracts/jargon.json` (the jargon translation map) and one complete depth-two fixture tree with per-node hashes and a root minted by a throwaway reference script committed alongside it, plus canonical() reference vectors for rounding ties and near-zero values; `.env.example` lists every variable the rails need plus named placeholders for Bright Data and GitHub credentials (standing rule: any slice introducing a variable updates `.env.example` in the same PR); the first PR is merged.
Features: Feature: Rails.

**Wave 1 - fully parallel after S0. Each slice adds its own module against S0's frozen extension surfaces and `contracts/` fixtures; no Wave-1 slice touches a shared file.**

**S1 - Scorer**
Depends: S0.
AC: `score.py` implements the Scoring section exactly (monthly-sum revenue, price factor capped at 1, baseline and move_cost definitions, counter semantics, scalar-to-range expansion, score_percent with the zero-baseline case); the deterministic Feature: Scorer scenarios (baseline zero, inelastic gain, elastic loss, undercut, cap, competitor raise, band, changed-assumption rerun) pass as automated tests; score.py runs in the sandbox on the fixture leaf and emits a trace event.
Features: Feature: Scorer (the display half of assumption editing belongs to S6).

**S2 - Provenance lib**
Depends: S0.
AC: `provenance.py` implements `canonical()` exactly as pinned in the Provenance section; recomputing S0's fixture tree reproduces its independently minted reference root; editing any node field changes the root; changing a node rehashes every ancestor and no off-path node; property tests cover float rounding and key ordering.
Features: Feature: Provenance (hash and recompute scenarios; the memo and UI scenarios belong to S7).

**S3 - Gather**
Depends: S0.
AC: three competitor pages scraped through Bright Data MCP with price extracted as a number; every call, URL, and extracted price in the trace; a failed parse yields "price unknown" plus the price from the `contracts/` company fixture as fallback, surfaced in the trace (S5 later swaps the source to the drafted file); every scrape persists a snapshot (content digest + timestamp) retrievable after the source changes, with one real gather run's snapshot and trace JSON committed as test evidence; the demo snapshot mirrors are committed under `mirrors/` with content digests and fetch timestamps; search_engine is called per competitor and up to three result URLs attach to its persona card.
Features: Feature: Gather.

**S4 - UI shell and widgets**
Depends: S0.
AC: chat-first page renders conversation plus trace panel (doing / waiting / did); company card, tree widget, approval card, and recommendation all render from `contracts/` fixtures with no backend; no YAML or field names visible outside advanced view; jargon translations are driven by `contracts/jargon.json` and tested against it.
Features: Feature: Plain language (except the assistant-client scenario, which is stretch).

**Wave 2**

**S5 - Company bootstrap**
Depends: S3, S4.
AC: a typed sentence becomes `move.yaml` per Feature: Move, and questions or non-price moves are rejected without building a tree; a URL becomes a draft company summary in the editable card; CSV drop merges matching segments and surfaces unmatched rows; missing elasticity gets the labeled default range; a corrected number persists to the session store and survives reload.
Features: Feature: Company bootstrap, Feature: Move.

**S6 - Tree**
Depends: S1, S2, S3.
AC: one subagent per competitor in parallel, each a distinct trace actor; responses are forced-choice with numeric price_before/price_after per the fixed semantics, reasoning, and sources; scraped content reaches subagents only per the untrusted-content boundary, with an automated injection test; the C-prime convention is applied and displayed as an editable assumption; every leaf scored with bands in dollars and percent, and editing an assumption reruns the scorer and updates the display; every node hashed at creation and the root exposed; at most 36 leaves; the one-extra-scrape budget is enforced by the orchestrator's counter and a second request is refused and traced; interactive depth works as specified (depth 0 default with best-scoring counters, depth 1 pauses once, the setting asked in plain language and remembered); after scoring, the recommendation names the path, the runner-up, the price-sensitivity risk read off the top two paths' bands, and a concrete watch trigger; the highest-mid-score path is highlighted and its first move queued as the pending action.
Features: Feature: Tree, Feature: Interactive depth, Feature: Recommendation (except the next-session trigger check, owned by S8), Feature: Untrusted content (subagent scenario).

**Wave 3**

**S7 - Gate**
Depends: S6, S4, S2.
AC: pending action shows the diff, memo text, winning branch, and root hash with nothing written; the gate service holds the only write credential and refuses without a token minted by a human Allow click; the approval queue API is callable programmatically but cannot authorize - only the UI Allow click mints the token (the MCP surface stays stretch); Allow opens the PR with the `pricing.yaml` change plus memo, and both the memo and the PR body carry the root hash; the memo and PR are rendered from the typed template with reasoning in fenced quote blocks, with an automated injection test; Deny writes locally with the reason; after a Deny, selecting a different branch queues a new pending action and the denied one remains in did; the UI recomputes the root from the stored tree and flags a memo mismatch; both paths traced and filmed.
Features: Feature: Gate, Feature: Untrusted content (memo/PR scenario), Feature: Provenance (memo, tamper-flag scenarios).

**S8 - Session and watch trigger**
Depends: S6.
AC: reload restores tree, scores, and decision; a new move on the same plan surfaces the previous decision and its reason first; a stored watch trigger is re-checked at session start via a fresh scrape and reported before anything else.
Features: Feature: Session, Feature: Recommendation (next-session trigger check).

**S9 - What-if** (first to cut)
Depends: S6, S2.
AC: a typed competitor alternative grows one branch with generated counters and scores; only the new branch's leaves rescore in the sandbox; hashes recompute from the changed node through every ancestor to the root; every off-path node, including other existing branches under the same competitor, keeps its hash.
Features: Feature: What-if, Feature: Provenance (what-if scope scenario).

The MCP-server surface (`setup_company`, `evaluate_move`, `approve_action` from assistant clients) is a stretch outside every v0 slice's merge gate.

**Checkpoints:** if S6 is not rendering a scored tree by 15:00, cut S9 and demo with a fixed competitor response.
If S7 is not opening a PR by 16:00, the gate writes the memo to the repo directly as the action.
A pre-staged, already-Qodo-reviewed PR from a prior run is prepared before filming (see Demo script).
Video recording starts at 17:00 whatever the state.

## Demo script (3 minutes)

0:00 - the move, typed as one sentence.
0:20 - company summary appears from the URL; correct one number on camera.
0:45 - trace shows Bright Data calls landing; competitor prices appear.
1:15 - tree grows; click Rival A's branch; show the score band and the assumptions behind it.
1:50 - change one elasticity; sandbox reruns; score moves.
2:15 - the action lands in the waiting column: open PR with diff and memo. Deny it, with a reason. Then run the alternative branch and Allow; the PR opens on camera.
2:40 - cut to a pre-staged PR from an earlier run with Qodo's completed review, labeled on camera as "a prior run's PR" - a live Qodo review takes minutes and never fits the window.
2:50 - close on the decision trace: doing, waiting, did.

## Rules check

- New repo, new code, no product core. Rule 4.
- Synthetic company, public competitor pages only, no private data, no secrets in repo or video. Rule 6.
- TrueForge visible doing MCP, sandbox, pause, subagents, session. Rule 1.
- PR trail through Qodo, every High fixed or dismissed in-thread. Rule 2.
- README has setup, `## Qodo Code Review Evidence`, and the disclosure that AI coding tools were used.
- No Twilio, no FlowStay or Property.bot accounts, no AGPL imports.

---

# BDD scenarios

Gherkin, one Feature per slice or cross-cutting concern. Each slice's AC names its Features; they become automated tests inside that slice's PR.

```gherkin
Feature: Rails
  The harness, the review trail, and the repo exist before any product code.

  Scenario: Orchestrator runs on TrueForge
    Given the repo is cloned fresh by a stranger
    When they follow the README setup
    Then the orchestrator starts inside TrueForge
    And a hello-world tool call appears in the decision trace

  Scenario: Every change goes through Qodo
    Given a branch with a substantive change
    When a PR is opened
    Then Qodo posts a review on the PR
    And the PR is merged only by a human
    And every High finding is fixed or dismissed in the Qodo thread with a reason

  Scenario: Only allowlisted tools are reachable
    Given the tool allowlist is Bright Data MCP, sandbox exec, GitHub MCP
    When the orchestrator or any subagent requests a tool outside the list
    Then the tool router refuses the request
    And the refusal appears in the trace


Feature: Scorer
  score.py is deterministic, tested, and runs in the sandbox.

  Background:
    Given a segment with 300 customers, price 49, monthly churn 0.04
    And own-price elasticity -1.1 and cross-price elasticity 0.4
    And competitor average price 45 before and 45 after
    And a horizon of 6 months

  Scenario: Baseline equals no-move revenue
    When the move is price 49 to 49
    Then score is 0

  Scenario: Inelastic segment gains revenue on a price increase
    Given own-price elasticity -0.8
    When the move is price 49 to 59
    Then score is greater than 0

  Scenario: Elastic segment loses revenue on a price increase
    Given own-price elasticity -1.5
    When the move is price 49 to 59
    Then score is less than 0

  Scenario: Competitor undercut reduces the price factor
    Given competitor average price 45 before and 39 after
    When the move is price 49 to 59
    Then the price factor is lower than with competitor price unchanged
    And the score band is lower

  Scenario: Price factor is capped at one
    Given own-price elasticity -0.1
    When the move is price 49 to 20
    Then the price factor is at most 1
    And customers never exceed the organically surviving base

  Scenario: Competitor raise does not invent customers
    Given competitor average price 45 before and 50 after
    When the move is price 49 to 49
    Then the price factor is at most 1
    And score is 0

  Scenario: Score is a band, not a number
    Given the segment's measured elasticity -1.1 expands to low -1.25, mid -1.1, high -0.95
    When the leaf is scored
    Then the result has low, mid, and high values in dollars and percent
    And no single confidence percentage is emitted

  Scenario: Scorer runs in the sandbox
    When the orchestrator scores a leaf
    Then score.py executes inside the TrueForge sandbox
    And the sandbox run appears in the trace with its inputs and outputs

  Scenario: Rerunning with a changed assumption produces a new band
    Given a scored fixture leaf
    When score.py reruns with own-price elasticity changed to -0.9
    Then the emitted band reflects the new elasticity


Feature: Gather
  Live competitor data comes from Bright Data through MCP, and every call is visible.

  Scenario: Competitor price is scraped
    Given company.yaml lists Rival A with a pricing URL
    When the gather step runs
    Then scrape_as_markdown is called on that URL through Bright Data MCP
    And a price is extracted for Rival A
    And the call, the URL, and the extracted price appear in the trace

  Scenario: Scrape failure is surfaced, not hidden
    Given Rival B's pricing URL returns no parseable price
    When the gather step runs
    Then Rival B is marked "price unknown"
    And the tree still builds using the last known or user-entered price
    And the failure appears in the trace

  Scenario: Recent news is searched
    Given a competitor name
    When the gather step runs
    Then search_engine is called through Bright Data MCP for that competitor
    And up to three result URLs are attached to the competitor's persona card

  Scenario: Every scrape persists a snapshot
    Given a competitor pricing URL
    When the gather step scrapes it
    Then a snapshot with content digest and timestamp is persisted with the session
    And the snapshot is retrievable after the source page changes


Feature: Company bootstrap
  The company summary is drafted from the public site and corrected by a human.

  Scenario: Draft from a URL
    Given a company website URL
    When the user submits it
    Then the agent scrapes the site through Bright Data MCP
    And a draft company.yaml appears with plans, prices, and competitors
    And every field is editable before continuing

  Scenario: Internal file merges into segments
    Given a draft company.yaml
    And a CSV with columns segment, customers, monthly_churn
    When the user drops the CSV
    Then matching segments are updated with the CSV values
    And unmatched rows are shown for the user to assign or discard

  Scenario: Missing elasticity gets a labeled default
    Given a segment with no elasticity value
    When the company summary is confirmed
    Then the segment gets the B2B default range
    And the UI labels it "assumed, not measured"

  Scenario: A corrected number survives reload
    Given the user corrected a price on the company card
    When the page is reloaded
    Then the corrected value is displayed, not the drafted one


Feature: Move
  One sentence becomes a structured move, or is sent back.

  Scenario: A move is parsed
    When the user types "Raise Pro from $49 to $59 and email customers next Monday"
    Then move.yaml has plan pro, from 49, to 59, effective next Monday
    And the action is open_pr

  Scenario: A question is rejected
    When the user types "Should I raise prices?"
    Then the agent asks for a specific move
    And no tree is built

  Scenario: Non-price moves are out of scope
    When the user types "Launch a new onboarding flow"
    Then the agent explains only price moves are supported today
    And no tree is built


Feature: Tree
  Competitor subagents choose from a menu; your counters come from a menu; every leaf is scored.

  Scenario: One subagent per competitor, in parallel
    Given three competitors in company.yaml
    When the tree builds
    Then three subagents are spawned
    And each appears as a separate actor in the trace

  Scenario: Competitor response is forced-choice with reasoning
    Given a competitor subagent with a persona card
    When it responds to the move
    Then its choice is one of undercut, match, ignore, raise
    And it carries numeric price_before and price_after computed by the fixed semantics
    And it includes a reasoning string
    And it lists the source URLs it used

  Scenario: The C-prime convention is a visible assumption
    Given a scored leaf
    When it is displayed
    Then the competitor-average convention appears as an editable assumption

  Scenario: Editing an assumption reruns the scorer and updates the display
    Given a scored leaf is displayed
    When the user changes own-price elasticity to -0.9
    Then score.py reruns in the sandbox
    And the displayed band updates

  Scenario: Subagent may request one extra scrape
    Given a competitor subagent
    When it requests a scrape of a URL from its persona card
    Then the scrape runs through Bright Data MCP
    And the orchestrator's scrape counter refuses any second request
    And the refusal appears in the trace

  Scenario: Counter-moves come from the fixed menu
    Given a competitor response node
    When the tree expands it
    Then the children are hold, partial_rollback, annual_discount
    And nothing else

  Scenario: Every leaf is scored
    When the tree finishes
    Then every leaf has a low, mid, high score
    And every leaf shows the assumptions used

  Scenario: Depth is capped at two
    When the tree finishes
    Then no node is deeper than your counter-move
    And the tree has at most 36 leaves for three competitors

  Scenario: Best path is proposed
    When the tree finishes
    Then the path with the highest mid score after each competitor's chosen response is highlighted
    And its first move is queued as the pending action


Feature: Gate
  The agent asks before it writes, and both answers are recorded.

  Scenario: Pending action shows the full payload
    Given a best path is proposed
    When the action reaches the waiting column
    Then the user sees the pricing.yaml diff
    And the decision memo text
    And the winning branch with its score band and assumptions
    And nothing has been written yet

  Scenario: Allow opens the PR
    Given a pending open_pr action
    When the user clicks Allow
    Then a PR is opened on the pricing repo through GitHub MCP
    And the PR contains the pricing.yaml change and the decision memo
    And the PR URL appears in the did column

  Scenario: Deny writes nothing remotely
    Given a pending open_pr action
    When the user clicks Deny with a reason
    Then no PR is opened
    And the memo and the reason are saved locally
    And the denial appears in the did column

  Scenario: Denied action can be replaced
    Given a denied action
    When the user selects a different branch
    Then a new pending action is queued
    And the old one stays in the did column as denied

  Scenario: Agent cannot bypass the gate
    Given the orchestrator wants to open a PR
    When no human has clicked Allow
    Then the gate service refuses the write because no approval token exists
    And the refusal appears in the trace

  Scenario: A programmatic approval request cannot authorize
    Given a pending action exists
    When any caller other than the UI Allow click requests approval
    Then no approval token is minted
    And no PR is opened
    And the pending action stays in the waiting column


Feature: Session
  Reloading the page or returning later loses nothing.

  Scenario: Reload keeps state
    Given a scored tree and a decision
    When the page is reloaded
    Then the same tree, scores, and decision are displayed

  Scenario: A later run remembers the last decision
    Given a previous session denied raising Pro to 59
    When a new move on plan pro is entered
    Then the agent shows the previous decision and its reason before building the tree


Feature: What-if
  The tree grows on demand.

  Scenario: Grow one branch
    Given a competitor response node
    When the user types "what if Rival A cuts to $39"
    Then a new competitor node is added with choice undercut, price_before at the last scraped price, and price_after 39
    And the node is marked as carrying an edited per-node price assumption overriding the 5% default
    And its counter-moves are generated and scored
    And off-path nodes keep their content, scores, and hashes
    And the changed node's ancestors up to the root get new hashes


Feature: Rules
  Things a judge or a stranger will check.

  Scenario: No secrets in the repo
    When the repo is scanned
    Then no API tokens, Luma tokens, or account credentials are present
    And all secrets come from environment variables listed in .env.example

  Scenario: No private data in the demo
    When the demo company is inspected
    Then it is synthetic
    And no FlowStay or Property.bot data appears anywhere

  Scenario: README carries the evidence
    When a stranger opens the README
    Then it has setup steps that work from a clean clone
    And a section "Qodo Code Review Evidence" linking a merged PR
    And a disclosure that AI coding tools were used


Feature: Plain language
  A business owner can use it without seeing code, YAML, or economics jargon.

  Scenario: Setup is a conversation
    When a new user arrives
    Then the agent asks for the company website in one sentence
    And no form, file, or config is shown first

  Scenario: Company card has no jargon
    Given the company summary is drafted
    When it is displayed
    Then plans, prices, and competitors appear as an editable card
    And no YAML or field names appear
    And price sensitivity is shown as low, medium, or high

  Scenario: Jargon is translated consistently
    When any of elasticity, cross-price elasticity, or monthly churn would be shown
    Then the user sees "price sensitivity", "how much your customers watch competitor prices", or "customers who leave each month"
    And the raw term appears only in the advanced view

  Scenario: Score reads as a sentence
    Given a scored leaf
    When it is displayed
    Then it reads "likely change in revenue over 6 months: +6% (between −1% and +11%)"

  Scenario: Approval card is one sentence and a diff
    Given a pending action
    When it is displayed
    Then it reads "Open a change request to raise Pro to $59 on Sept 7?"
    And the buttons are "Approve" and "Not now"
    And the diff is visible below

  Scenario: Advanced view is one toggle away
    Given any widget with translated values
    When the user turns on advanced view
    Then raw values, ranges, and the scoring script are visible

Feature: MCP surface (stretch - outside every v0 slice's merge gate)
  The same flow from an assistant client, if time allows.

  Scenario: Same flow from an assistant client
    Given the MCP server is enabled
    When a user in Claude Desktop, Claude Code, or Codex calls setup_company, evaluate_move, and approve_action
    Then the same orchestrator runs on TrueForge
    And approve_action queues a request but cannot authorize the action
    And only a human Allow click in the UI mints the approval token


Feature: Recommendation
  After all leaves are scored, the agent gives a verdict before it asks for anything.

  Scenario: Verdict follows the last score
    Given every leaf has a score band
    When scoring finishes
    Then a recommendation is shown before any pending action
    And it names one recommended path with its band
    And it names the runner-up and why it lost

  Scenario: Price-sensitivity risk is named
    Given the top two paths with their low, mid, and high bands
    When their band ends are compared
    Then the recommendation states whether any price-sensitivity range end flips the ranking
    And no extra scoring runs are performed
    And other assumptions are labeled editable but not sensitivity-ranked

  Scenario: Watch trigger is concrete
    When the recommendation is shown
    Then it includes one observable trigger that would flip it
    And the trigger names a competitor, a threshold, and a time window

  Scenario: Watch trigger is checked next session
    Given a stored decision with a watch trigger
    When a new session starts
    Then the agent re-scrapes the trigger's competitor price
    And reports whether the trigger has fired before anything else


Feature: Untrusted content
  Scraped pages are adversarial input and cannot steer the agent or the PR.

  Scenario: Injected page text cannot change a subagent's choice
    Given a snapshot competitor page containing instruction-like text
    When the subagent responds to the move
    Then the page reaches the subagent only as schema-validated structured facts
    And the subagent's choice and tool calls are validated against the fixed menus

  Scenario: Memo and PR render reasoning as quoted text
    Given a winning branch whose reasoning contains markup or instruction-like text
    When the memo and PR body are written
    Then the reasoning appears only inside a fenced block that its content cannot terminate
    And the pricing.yaml diff contains only the numeric price change


Feature: Provenance
  The tree is content-addressed, so the decision is verifiable and what-ifs are cheap.

  Scenario: Every node has a hash
    When the tree is built
    Then every node has a hash of its content plus its children's hashes
    And a leaf's content includes choice, reasoning, source URLs, assumptions, and score band

  Scenario: Root hash is in the memo and PR
    Given a recommended path
    When the decision memo is written
    Then it contains the tree's root hash
    And the PR body contains the same hash

  Scenario: Tampering is detectable
    Given a stored tree and memo
    When any node's reasoning or score is edited on disk
    Then recomputing the root produces a different hash
    And the UI flags the memo as not matching the tree

  Scenario: What-if rescoring and rehashing have different scopes
    Given a fully scored tree
    When the user grows one branch under Rival A
    Then only the new branch's leaves are rescored in the sandbox
    And the changed branch and every ancestor up to the root get new hashes
    And every off-path node, including other existing branches under Rival A, keeps its hash

  Scenario: Recomputing a stored tree reproduces its root
    Given a stored tree with its root hash
    When the hashes are recomputed from the stored node content
    Then the recomputed root equals the stored root


Feature: Interactive depth
  The user chooses how many simulation decisions to make themselves; execution is always one approval.

  Scenario: Default is fully automatic
    Given interactive depth is 0
    When the tree builds
    Then no question is asked until scoring finishes
    And at each of the user's nodes the best-scoring counter is chosen
    And the only human prompt is the final approval card

  Scenario: Depth one pauses once
    Given interactive depth is 1
    When competitor responses are in
    Then the agent pauses once and shows each competitor's response
    And the user picks one counter per branch
    And the tree then scores to completion without asking again

  Scenario: Execution is always one approval
    Given any interactive depth
    When the recommendation is ready
    Then exactly one approval card is shown
    And nothing is written before Approve

  Scenario: Setting is asked in plain language
    When a move is entered for the first time
    Then the agent asks whether to pick counter-moves itself or let the user choose
    And the answer is remembered for the session
```

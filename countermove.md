# Countermove — scope and build plan

Working name. Change it if Sterling has a better one.

## The job

Give it one business move and your company's basics. It pulls live competitor data, simulates the full move-and-response tree with subagents, scores every path in a sandbox, recommends a path, and asks a human once before executing the chosen move.

Who hires it: a founder or operator with a specific, irreversible move this week. A pricing change is the only move type in v0.

## In / out for today

In: one move type (price change on one plan), depth-two tree, three competitors, price-shaped counter-moves only, one gated action, synthetic company with real competitors, single-page UI.

Out: non-price moves, deeper trees, CRM or database connectors, auth, multi-user, any FlowStay or Property.bot data, the MiroFish codebase (AGPL — ideas only).

## Who uses it

A business owner, not an engineer. Every screen passes this test: no YAML, no code, no field a non-technical person couldn't fill from memory.

- The interface is a conversation. The agent asks one question at a time and renders results inline: the company summary as an editable card, the tree as a widget, the pending action as an approval card.
- Jargon is translated everywhere it appears. Elasticity → "price sensitivity: low / medium / high" (mapped to the ranges below). Monthly churn → "customers who leave each month." Cross-price elasticity → "how much your customers watch competitor prices: a little / some / a lot." Score band → "likely change in revenue over 6 months: +6% (between −1% and +11%)."
- The approval card is a sentence and a diff, not a payload: "Open a change request to raise Pro to $59 on Sept 7? This changes pricing.yaml and adds a decision memo." Buttons say Approve and Not now.
- Advanced view is one toggle away for anyone who wants the raw numbers and the script.
- Stretch: expose the orchestrator as an MCP server with `setup_company`, `evaluate_move`, `approve_action`, so the same flow runs from Claude Desktop, Claude Code, or Codex. Distribution story for the write-up; not the demo surface.

## Components

1. **UI** — one page, chat-first. The conversation drives setup, the move, and the decision. Inline widgets: company card, tree, approval card. A trace panel shows doing / waiting / did in plain language ("checking Rival A's pricing page", "waiting for your approval", "opened change request #12").
2. **Orchestrator** — runs on TrueForge. Owns the session, spawns subagents, calls tools, pauses at the gate.
3. **Tools** — Bright Data MCP (`scrape_as_markdown`, `search_engine`), TrueForge sandbox exec, GitHub MCP (read repo, open PR). Nothing else.
4. **Subagents** — one per competitor. Forced-choice response from a menu, with reasoning and the data used.
5. **Scorer** — `score.py`, checked into the repo, run in the sandbox.
6. **Session store** — JSON on disk. Company, moves, trees, decisions.

## Data shapes

```yaml
# company.yaml — drafted by the agent from the URL, corrected by the human
name: Acme Stay
plans:
  - id: pro
    price: 49
    segments:
      - id: smb        # name, customers, monthly_churn, elasticity, cross_elasticity
        customers: 300
        monthly_churn: 0.04
        elasticity: -1.1
        cross_elasticity: 0.4
      - id: mid
        customers: 120
        monthly_churn: 0.02
        elasticity: -0.8
        cross_elasticity: 0.3
competitors:
  - name: Rival A
    url: https://rival-a.example/pricing
    price: 45
```

```yaml
# move.yaml — one sentence in, structured out
plan: pro
from: 49
to: 59
action: open_pr            # v0: PR to the company's pricing config + decision memo
effective: 2026-09-07
```

Tree node: `{ id, parent, actor: "you" | "competitor", label, choice, reasoning, sources: [urls], score: { low, mid, high }, assumptions: {...} }`

Competitor response menu: `undercut`, `match`, `ignore`, `raise`. Your counter menu: `hold`, `partial_rollback`, `annual_discount`.

## Scoring (score.py)

Per segment `s`: `P` current price, `P'` new price, `C` and `C'` competitor average price before and after their response, `N` customers, `m` monthly churn, `eps` own-price elasticity, `eta` cross-price elasticity, `months` = 6.

```
retention  = clamp((P'/P) ** eps * (C'/C) ** eta, 0, 1.05)
customers  = N * retention * (1 - m) ** months
revenue    = customers * P' * months - move_cost
score      = sum(revenue over segments) - baseline_revenue
```

Run three times per leaf with `eps` at the low, mid, and high end of the segment's range. Report `{low, mid, high}`. Never print a single confidence percentage.

Defaults with no data: B2B with switching costs −0.7 to −0.9; B2B without lock-in −1.0 to −1.3; consumer −1.5 to −2.0. Cross-price default +0.4. `move_cost` for `annual_discount` is the discount times the customers who take it (assume 30% uptake, editable).

Every assumption is displayed next to the score and is editable. Editing reruns the script in the sandbox.

## Recommendation

After every leaf is scored, the agent writes a verdict before proposing an action:

1. Recommended path, one sentence, with its score band.
2. Runner-up and why it lost.
3. The assumption the answer is most sensitive to (found by rerunning the top two paths at the ends of their elasticity ranges).
4. What to watch after acting: a concrete trigger that would flip the recommendation ("Rival A below $42 within 30 days").

The approval card carries the recommendation's first move. The watch trigger is stored with the decision and checked at the start of the next session.

## Provenance (Merkle tree)

Every node carries `hash = sha256(canonical(content) + child hashes)`. Leaf content is the choice, reasoning, source URLs, assumptions, and score band. The root hash is written into the decision memo and the PR body.

- Anyone can recompute the root from the stored tree; a mismatch means the tree or memo was edited after the decision.
- What-if edits only recompute the subtree whose hashes changed; unchanged branches skip the sandbox.
- Two runs with the same root reached the same conclusion from the same inputs. A different root means something changed, and a node-level diff shows what.

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

Why this action: it's a real write to a real repo, it gets reviewed by Qodo on camera, and it turns a decision into a diff. If there's time, add "send the announcement" as a second gated action to a mock endpoint. Not before the PR path works.

## Build order

Each step ends in a PR through Qodo. No direct pushes to main.

1. **Repo and rails** — public repo, README skeleton, TrueForge running hello-world, Qodo installed, first PR merged. Nothing else counts until this exists.
2. **Scorer** — `score.py` with tests. Run it in the sandbox from the orchestrator. This is the first thing a judge sees working.
3. **Gather** — Bright Data MCP call from the orchestrator: scrape three competitor pricing pages, extract price. Log every call to the trace.
4. **Company bootstrap** — scrape the company URL, draft `company.yaml`, show it in an editable box. File drop for CSV merges into segments.
5. **Tree** — competitor subagents in parallel, forced-choice, then your counter menu, then score every leaf. Render the tree.
6. **Gate** — pending action in the waiting column, Allow opens the PR via GitHub MCP, Deny logs. Film both.
7. **Session** — reload the page and the tree and decision are still there. One more run remembers the last decision.
8. **What-if** — click a node, type a competitor alternative, grow one branch.

Checkpoints: if step 5 isn't rendering a scored tree by 15:00, cut step 8 and demo with a fixed competitor response. If step 6 isn't opening a PR by 16:00, the gate writes the memo to the repo directly as the action. Video recording starts at 17:00 whatever the state.

## Demo script (3 minutes)

0:00 — the move, typed as one sentence.
0:20 — company summary appears from the URL; correct one number on camera.
0:45 — trace shows Bright Data calls landing; competitor prices appear.
1:15 — tree grows; click Rival A's branch; show the score band and the assumptions behind it.
1:50 — change one elasticity; sandbox reruns; score moves.
2:15 — the action lands in the waiting column: open PR with diff and memo. Deny it, with a reason. Then run the alternative branch and Allow. Show the PR and Qodo's review on it.
2:50 — close on the decision trace: doing, waiting, did.

## Rules check

- New repo, new code, no product core. Rule 4.
- Synthetic company, public competitor pages only, no private data, no secrets in repo or video. Rule 6.
- TrueForge visible doing MCP, sandbox, pause, subagents, session. Rule 1.
- PR trail through Qodo, every High fixed or dismissed in-thread. Rule 2.
- README has setup, `## Qodo Code Review Evidence`, and the disclosure that AI coding tools were used.
- No Twilio, no FlowStay or Property.bot accounts, no AGPL imports.

---

# BDD scenarios

Gherkin, one Feature per build step. Paste into `features/countermove.feature` or keep here for review.

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
    Then the request is refused
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

  Scenario: Competitor undercut reduces retention
    Given competitor average price 45 before and 39 after
    When the move is price 49 to 59
    Then retention is lower than with competitor price unchanged

  Scenario: Retention is clamped
    Given own-price elasticity -0.1
    When the move is price 49 to 20
    Then retention is at most 1.05

  Scenario: Score is a band, not a number
    Given the segment's elasticity range is -1.0 to -1.3
    When the leaf is scored
    Then the result has low, mid, and high values
    And no single confidence percentage is emitted

  Scenario: Scorer runs in the sandbox
    When the orchestrator scores a leaf
    Then score.py executes inside the TrueForge sandbox
    And the sandbox run appears in the trace with its inputs and outputs

  Scenario: Editing an assumption reruns the scorer
    Given a scored leaf is displayed
    When the user changes own-price elasticity to -0.9
    Then score.py reruns in the sandbox
    And the displayed band updates


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
    And it includes a reasoning string
    And it lists the source URLs it used

  Scenario: Subagent may request one extra scrape
    Given a competitor subagent
    When it requests a scrape of a URL from its persona card
    Then the scrape runs through Bright Data MCP
    And the subagent may not request a second one

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
    Then GitHub MCP write calls are refused
    And the refusal appears in the trace


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
    Then a new competitor node is added with choice undercut and price 39
    And its counter-moves are generated and scored
    And the rest of the tree is unchanged


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
    Then the user sees "price sensitivity", "how closely customers watch competitors", or "customers who leave each month"
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

  Scenario: Same flow from an assistant client
    Given the MCP server is enabled
    When a user in Claude Desktop, Claude Code, or Codex calls setup_company, evaluate_move, and approve_action
    Then the same orchestrator runs on TrueForge
    And approve_action does nothing until called by the human


Feature: Recommendation
  After all leaves are scored, the agent gives a verdict before it asks for anything.

  Scenario: Verdict follows the last score
    Given every leaf has a score band
    When scoring finishes
    Then a recommendation is shown before any pending action
    And it names one recommended path with its band
    And it names the runner-up and why it lost

  Scenario: Most sensitive assumption is named
    Given the top two paths
    When each is rerun at the ends of its price-sensitivity range
    Then the recommendation names the assumption whose change moves the ranking most

  Scenario: Watch trigger is concrete
    When the recommendation is shown
    Then it includes one observable trigger that would flip it
    And the trigger names a competitor, a threshold, and a time window

  Scenario: Watch trigger is checked next session
    Given a stored decision with a watch trigger
    When a new session starts
    Then the agent re-scrapes the trigger's competitor price
    And reports whether the trigger has fired before anything else


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

  Scenario: What-if recomputes only the changed subtree
    Given a fully scored tree
    When the user grows one branch under Rival A
    Then only nodes under Rival A are rescored in the sandbox
    And every other node keeps its hash

  Scenario: Same inputs give the same root
    Given the same company data, competitor prices, and assumptions
    When the tree is built twice
    Then both roots are identical


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

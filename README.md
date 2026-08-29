# Countermove

Give it one business move and your company's basics.
It pulls live competitor data, simulates the move-and-response tree with subagents, scores every path in a sandbox, recommends a path, and asks a human once before executing.

v0 scope: a price change on one plan, a depth-two tree, three competitors, one gated action (a PR against a pricing repo).
Full scope, build order, and BDD scenarios live in [countermove.md](countermove.md).

## Status

Rails only.
The build follows the 8 steps in the plan; each lands through a Qodo-reviewed PR.

## Setup

Prerequisites: TODO (pinned as part of build step 1).

```sh
git clone git@github.com:fourcolors/countermove.git
cd countermove
cp .env.example .env   # fill in your own tokens; nothing in this repo contains secrets
```

Run instructions land with the orchestrator in build step 1.

## Architecture

- **UI** - one page, chat-first, inline widgets (company card, tree, approval card, trace panel).
- **Orchestrator** - runs on TrueForge; owns the session, spawns subagents, calls tools, pauses at the gate.
- **Tools** - Bright Data MCP, TrueForge sandbox exec, GitHub MCP. Nothing else.
- **Subagents** - one per competitor, forced-choice responses with reasoning and sources.
- **Scorer** - `score.py`, run in the sandbox.
- **Session store** - JSON on disk.

## Qodo Code Review Evidence

Every substantive change goes through a PR reviewed by Qodo; PRs are merged only by a human.
Direct pushes to `main` do not count toward the review trail.

Evidence (merged PRs with Qodo reviews) will be linked here as they land.

- First Qodo-reviewed PR: (link after merge)

## Disclosure

AI coding tools (Claude Code and the OpenAI Codex CLI) were used to plan, review, and build this project.
The demo company is synthetic; competitor data comes from public pages only.

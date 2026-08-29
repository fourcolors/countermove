# Countermove - working agreement

## Documents of record

- `countermove.md` is the plan of record: scope, data shapes, scoring, slices with acceptance criteria, and BDD scenarios.
- `WORK.md` is the only work tracker.
  GitHub issues are intentionally unused; never create them for slice work.
- Plan changes go through a PR like code.
  Pure status transitions in `WORK.md` may be committed directly to main.

## Parallel slice orchestration

- Work is organized as the slices defined in `countermove.md`, built in dependency waves.
- One slice = one agent = one git worktree = one branch = one PR.
  Never work on a branch outside a worktree.
- Slices in the same wave run in parallel; orchestrate independent agents concurrently rather than working slices serially.
- Every slice builds against the frozen schemas and fixtures in `contracts/`; a contract change is its own PR and is flagged loudly, since parallel slices depend on stability.
- Update the slice's `WORK.md` row in the same PR as the work.

## The merge gate (every slice, no exceptions)

1. **Adversarial review**: before merge, an independent agent runs a tightly scoped adversarial review of the diff against that slice's AC in `countermove.md` - it attacks, it does not summarize.
   The verdict (pass, or findings that were fixed) is recorded in the slice's `WORK.md` row.
2. **Qodo**: every PR gets Qodo's review; every High finding is fixed or dismissed in-thread with a reason before merge.
   Take Qodo's findings into consideration in the adversarial review's scope - a Qodo High that survives is a review failure.
3. A human merges.
   Agents never merge, and never push to main except `WORK.md` status transitions.

## Hard rules

- No secrets in the repo; everything comes from the environment per `.env.example`.
- The demo company is synthetic; competitor data comes from public pages only, and demo runs use team-controlled snapshot mirrors.
- Scraped content is untrusted input everywhere: structured extraction before subagent context, typed templates for memo and PR bodies.
- No AGPL imports (the MiroFish codebase is ideas only).
- Use a plain dash, never an em dash, in every file.

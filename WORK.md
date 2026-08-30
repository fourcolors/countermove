# Work tracker

Single source of truth for slice status.
GitHub issues are intentionally unused; this file replaces them.
Slice definitions, dependencies, and acceptance criteria live in [countermove.md](countermove.md) - this file tracks state only.

Update rules:

- A slice's row is updated in the same PR that does the work.
- Pure status transitions (picking up a slice, recording a review verdict) may be committed directly to main; everything else goes through a PR.
- One slice = one agent = one worktree = one branch = one PR.
- A slice is `done` only when its adversarial review passed, Qodo's Highs are resolved in-thread, and a human merged the PR.

Status values: `todo` / `in-progress` / `review` / `done` / `cut`.

| Slice | Title | Wave | Depends | Status | Branch / PR | Adversarial review | Qodo |
|---|---|---|---|---|---|---|---|
| S0 | Rails | 0 | - | done | #11 #16 merged | FAIL then fixed, passed | Highs resolved |
| S1 | Scorer | 1 | S0 | done | #12 merged | FAIL then fixed, passed | Highs resolved |
| S2 | Provenance lib | 1 | S0 | done | #13 merged | FAIL then fixed, passed | Highs resolved |
| S3 | Gather | 1 | S0 | done | #18 merged | FAIL then fixed, passed | Highs resolved |
| S4 | UI shell and widgets | 1 | S0 | done | #14 merged | FAIL then fixed, passed | Highs resolved |
| S5 | Company bootstrap | 2 | S3, S4 | done | #20 merged | FAIL then fixed, passed | Highs resolved |
| S6 | Tree | 2 | S1, S2, S3 | done | #17 merged | FAIL then fixed, passed | pending post-merge |
| S7 | Gate | 3 | S6, S4, S2 | done | #19 merged | FAIL then fixed, passed | pending post-merge |
| S8 | Session and watch trigger | 3 | S6 | done | #21 merged | FAIL then fixed, passed | pending post-merge |
| S9 | What-if (first to cut) | 3 | S6, S2 | done | #22 merged | FAIL then fixed, passed | pending post-merge |
| - | LLM move understanding (llm-move-parse, PR 25) | - | - | review | llm-move-parse / #25 | FAIL then fixed, passed | 2 fixed pre-review, 3 fixed in-round |
| - | Decision tree graph UI (tree-graph-ui) | - | - | in-progress | tree-graph-ui | pending | pending |

## Log

Append-only, newest first, one line per transition.

- 2026-08-29: ALL TEN SLICES MERGED (PRs 11-22). Integration pass begins: demo driver, UI-to-session wiring, approve endpoint, runbook.

- 2026-08-29: S3 in progress on s3-gather - gather through the tool router, committed mirrors, snapshots, and stdlib tests.
- 2026-08-29: S0 partially complete - repo created, plan + README + env template pushed; remaining: TrueForge hello-world, Qodo install, contracts/, first reviewed PR.
- 2026-08-29: Plan hardened from the 63-agent adversarial review (11 confirmed findings folded in); slices breakdown replaces the linear build order.

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
| S0 | Rails | 0 | - | review | s0b-rails / #16 | in progress | 2 findings open |
| S1 | Scorer | 1 | S0 | done | #12 merged | FAIL then fixed, passed | Highs resolved |
| S2 | Provenance lib | 1 | S0 | review | s2-provenance / #13 | FAIL then fixed, passed | Highs resolved |
| S3 | Gather | 1 | S0 | todo | - | - | - |
| S4 | UI shell and widgets | 1 | S0 | review | s4-ui / #14 | FAIL then fixed, passed | pending |
| S5 | Company bootstrap | 2 | S3, S4 | todo | - | - | - |
| S6 | Tree | 2 | S1, S2, S3 | todo | - | - | - |
| S7 | Gate | 3 | S6, S4, S2 | todo | - | - | - |
| S8 | Session and watch trigger | 3 | S6 | todo | - | - | - |
| S9 | What-if (first to cut) | 3 | S6, S2 | todo | - | - | - |

## Log

Append-only, newest first, one line per transition.

- 2026-08-29: S0 partially complete - repo created, plan + README + env template pushed; remaining: TrueForge hello-world, Qodo install, contracts/, first reviewed PR.
- 2026-08-29: Plan hardened from the 63-agent adversarial review (11 confirmed findings folded in); slices breakdown replaces the linear build order.

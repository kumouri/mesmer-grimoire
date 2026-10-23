# The next phase starts on push, not on merge

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-23 |
| Deciders | Ceryce Armstrong |
| Source | Ceryce's ruling, 2026-10-22: "in integration branch mode PRs being merged is NOT required to move on to the next phase, only pushing to the PR is required" |
| Enforced where | [`../skills/implement-phase/SKILL.md`](../skills/implement-phase/SKILL.md) (preconditions, step 6); the *Branch model* section of [`../agents/zethus.agent.md`](../agents/zethus.agent.md); [`../skills/zethus-pr-description/SKILL.md`](../skills/zethus-pr-description/SKILL.md); [`../copilot-instructions.md`](../copilot-instructions.md); [`../instructions/docs.instructions.md`](../instructions/docs.instructions.md) and the spec templates (status words); `tests/test_zethus.py` |
| Supersedes | the `branch-per-change` precondition "every earlier phase has merged" |
| Superseded by | — |

## Decision

A phase may start once the phase before it is **committed, green on the local gates, and pushed to
its PR**. Its PR does not have to be merged. Merging stays a person's call, made whenever the
team's process allows.

## Context

`branch-per-change` is the default branch model, the one where every phase branch is cut from the
integration branch and its PR targets it. Ceryce calls it "integration branch mode". In that model
`implement-phase` required every earlier phase to have **merged** before the next one started,
because the next branch was cut from `origin/<base>` and needed the earlier phase on it.

On a team that merges only when a whole feature is done, after several days of testing, product
review and demos, that gate stops all work: phase 1 waits for days on phase 0's merge. The
`rebase` style never had this gate. There, a phase only had to be complete on the branch.

## How it works now

| | `branch-per-change` (default) | `rebase` |
|---|---|---|
| Next phase starts when | The previous phase is committed, its gates are green, and it is pushed to its PR | The same |
| Where the next phase goes | A new branch **stacked** on the previous phase's branch | The next commit series on the same branch, pushed to the same PR |
| Its PR targets | The previous phase's branch, so the PR shows only this phase | The one PR already open against `<base>` |
| Earlier PR merges | GitHub retargets the next PR to `<base>` when the merged branch is deleted. With a merge commit nothing else changes. After a squash or rebase merge, run `git rebase --onto origin/<base> <old tip of the merged phase>` | — |
| `<base>` moves (freshness STALE) | From the top of the stack, `git rebase --update-refs origin/<base>` rebases every phase branch in one go; push each with `--force-with-lease` | `git rebase origin/<base>`, then push with `--force-with-lease` |
| How the team merges | Bottom-up, when the feature is done: phase 0 into `<base>`, then each PR above it once it is retargeted | The one PR, when the feature is done |

A team that wants one PR per feature should use `rebase` style. A team that wants each phase to be
reviewable alone should use stacked branches.

## Status words stay honest

A phase that is pushed but not merged is **in review**, not built. In the spec's phase table, a
phase is marked `in review (PR #n)` when it is pushed and `merged (PR #n)` when its PR merges. The
spec's status splits the two: `PARTIAL(merged: phases 0–1; in review: phase 2)`, with an empty half
left out. `BUILT` still means the last phase has merged.

## Options considered

| Option | What it means | What it costs | |
|---|---|---|---|
| A — stack on the previous branch, PR targets it | Phase N+1 branches from phase N; its PR diff is that phase alone | Merges go bottom-up, and a moved base means a stack rebase (`--update-refs`) | **Chosen** |
| B — stack on the previous branch, every PR targets `<base>` | No retargeting | Each PR shows every earlier unmerged phase too, so review repeats, and merging a later PR first silently merges the earlier ones | |
| C — keep the merge gate and add a config switch to drop it | Old behaviour by default | Keeps the default that blocks work on any team with a slow merge process | Declined |

## Consequences

- **Easier:** the work moves at the speed of pushing, not at the speed of the team's merge
  process.
- **Harder:** a stack of open PRs has to be kept fresh as a stack, and merged in order.
- **New obligations:**
  - Every safety rule stays: never merge your own PR; a person merges only on green CI at the
    reviewed head; the base is checked for freshness at Stage 0 and before every push.
  - A spec never says `merged` or `BUILT` for a phase whose PR is still open.
  - `tests/test_zethus.py` pins the push gate, the stacked-branch wording and the status words, so
    the merge gate can't creep back.

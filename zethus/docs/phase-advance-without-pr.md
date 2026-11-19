# The next phase can start with no PR open: `pr-later` style

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-11-19 |
| Deciders | Ceryce Armstrong |
| Source | Ceryce's ruling, 2026-11-19, paraphrased below |
| Enforced where | `branchModel.style` in [`../scripts/base-freshness.py`](../scripts/base-freshness.py) (accepts `pr-later`); [`../skills/implement-phase/SKILL.md`](../skills/implement-phase/SKILL.md) (preconditions, steps 5 and 6); the stage table, stop table and *Branch model* section of [`../com.github.copilot/agents/zethus.agent.md`](../com.github.copilot/agents/zethus.agent.md); [`../skills/pre-push-gates/SKILL.md`](../skills/pre-push-gates/SKILL.md); [`../skills/zethus-pr-description/SKILL.md`](../skills/zethus-pr-description/SKILL.md) (*In `pr-later` style*); [`../copilot-instructions.md`](../copilot-instructions.md); [`../com.github.copilot/rules/zethus-docs.instructions.md`](../com.github.copilot/rules/zethus-docs.instructions.md) and the spec templates (status words); `tests/test_zethus_pr_later.py` |
| Extends | [The next phase starts on push, not on merge](phase-advance-on-push.md) (2026-10-22) |
| Supersedes | — |
| Superseded by | — |

## Decision

A third branch style, **`pr-later`**, sits beside `branch-per-change` and `rebase`. In it, a phase
may start once the phase before it is **committed on the working branch with every local gate
green**. No PR is required, and no merge. Pushing the branch is allowed and preferred, as a backup,
but Zethus opens no PR, draft or otherwise, until the person says to. The default style is still
`branch-per-change`, so nothing changes for a repo that doesn't choose it.

## Context

The 2026-10-22 ruling dropped the merge gate: the next phase starts once the previous one is
pushed to its PR. That still left a PR gate. Every style required the previous phase to sit in an
open PR before the next could start.

Ceryce's ruling, paraphrased: on busier, closely watched repos, the team sometimes doesn't want a PR
open yet, but still needs several phases or stories done on the branch. Zethus blocked the next
phase unless the previous one was in an open PR or already merged to the base. She worked round it
by opening the PR as a draft, and Zethus should offer a proper path instead of needing that
workaround.

A PR is outward-facing. On a busy repo, opening one notifies reviewers and code owners, starts
review automation and invites comments on work that isn't ready to be looked at. A draft PR still
does most of that. Committing and pushing a branch does none of it, and the local gates already
give the evidence the next phase needs: the previous one builds, passes and is recorded.

## How it works now

| | `branch-per-change` (default) | `rebase` | `pr-later` |
|---|---|---|---|
| Next phase starts when | The previous phase is committed, its gates are green, and it is pushed to its PR | The same | The previous phase is committed on the working branch with its gates green. No PR, no merge |
| Where the next phase goes | A new branch stacked on the previous phase's branch | The next commit series on the same branch | The next commit series on the same working branch |
| Push | Required: the PR needs it | Required: the PR needs it | Allowed and preferred, after the pre-push gates, as a backup of finished work. The next phase doesn't wait on it |
| PR | One per phase, stacked | One, open against `<base>` | None until the person says to open it |
| Stage 7 exit | PR opened, not merged | The same | Branch pushed (or the reason it wasn't), PR body drafted in the spec, **no PR opened** |
| `<base>` moves (freshness STALE) | `git rebase --update-refs origin/<base>` from the top of the stack | `git rebase origin/<base>` | `git rebase origin/<base>`; push with `--force-with-lease` if the branch was pushed; note the rebase in the spec's *As built* list, since there's no PR body to say it in |

Every other rule is unchanged: sign-off before code, Phase 0 first, one phase at a time, every
local gate green before a phase is committed as done and again before any push, and the base checked
for freshness at Stage 0 and before every push.

### When to use it

- A busy or closely watched repo, where an open PR draws reviewers, code owners or automation before
  the work is ready to be looked at.
- A feature the team wants to see as one PR once several phases or stories are done, without
  opening it early.
- Not for a quiet repo where an early PR costs nothing. There, `branch-per-change` or `rebase` gives
  reviewers the work phase by phase, which is cheaper to review.

Select it in `.github/zethus.config.json`:

```json
{ "branchModel": { "style": "pr-later" } }
```

### Status words in this style

A phase is never `in review` or `merged` without a PR, and the spec never says `BUILT` before the
last phase's PR merges.

| Phase state | Phase table says |
|---|---|
| Committed on the working branch, gates green, not pushed | `committed (<short sha>)` |
| The same, and pushed to the remote working branch | `on branch (<short sha>)` |
| The PR is open and the phase is in it | `in review (PR #n)` |
| The PR has merged | `merged (PR #n)` |

The spec's status names each non-empty group: `PARTIAL(on branch: phases 0–1; committed: phase 2)`.
Once the PR is open, it returns to the usual form, `PARTIAL(merged: …; in review: …)`.

Each phase's *As built* list carries what a PR would otherwise hold: the deviations, the gate table
from `run-local-gates`, and any rebase onto `origin/<base>`. So the PR body is ready to assemble the
moment it is wanted.

### When the PR is eventually opened

Opening it is the person's call: they say so, or they change `branchModel.style`. Zethus never
opens it on its own judgement in this style. Then:

1. Run Stage 6 on the tip of the working branch: `base-freshness` (rebasing if STALE) and
   `run-local-gates` on the exact tree being pushed.
2. Push, and open **one** PR against `<base>` covering every phase committed so far, with
   [zethus-pr-description](../skills/zethus-pr-description/SKILL.md). The body lists each phase,
   its *As built* list and evidence from the spec, and the fresh gate table.
3. Mark every phase in it `in review (PR #n)`, and set the status to the usual form.
4. Later phases are pushed to that PR, as in `rebase` style. Offer, in one question, to change
   `branchModel.style` to `rebase` in config, so the config says what the branch is now doing.

## Options considered

| Option | What it means | What it costs | |
|---|---|---|---|
| A — a third `branchModel.style`, `pr-later` | One working branch, phases as commit series, no PR until the person says | Another style to document. Stacked per-phase branches without PRs aren't offered | **Chosen** |
| B — a separate switch (say `branchModel.openPr: false`) that combines with either style | No PR in either style, including stacked branches with no PRs | Four combinations to document and test, and a stack of PR-less branches is a lot of bookkeeping for a team that wants one PR later | Declined |
| C — keep the PR gate, and document the draft-PR workaround | Nothing new to learn | The draft still notifies people and runs automation, which is what the team wanted to avoid | Declined |

## Consequences

- **Easier:** work on a watched repo moves at the speed of committing, without a PR before the team
  wants one.
- **Harder:** the evidence for each phase lives in the spec until the PR opens, so the spec's
  *As built* lists have to be kept complete.
- **New obligations:**
  - Zethus never opens a PR in this style unless the person says to, and never opens a draft as a
    stand-in.
  - The goal-complete stop in this style is: the last phase is committed with green gates (pushed,
    or the reason it wasn't), and opening the PR is waiting on the person.
  - `tests/test_zethus_pr_later.py` pins the style, the advance gate, the status words and the
    no-PR-until-asked rule, and `base-freshness` accepts `pr-later` and says what to do when it
    is stale.

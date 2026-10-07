# Base freshness runs at two checkpoints, not at every stage

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-07 |
| Deciders | Ceryce Armstrong |
| Source | Ceryce's report of using the kit, 2026-10-07 |
| Enforced where | [`../agents/zethus.agent.md`](../agents/zethus.agent.md) ("Check the base at two points"), [`../copilot-instructions.md`](../copilot-instructions.md), [`../skills/pre-push-gates/SKILL.md`](../skills/pre-push-gates/SKILL.md) step 0, and `--merge-base-only` in [`../scripts/base-freshness.py`](../scripts/base-freshness.py) |
| Supersedes | the original cadence: `base-freshness.py` at the start of every stage, plus separately inside several skills |
| Superseded by | — |

This repo keeps no `docs/adr/` of its own (`zethus/scripts/new-adr.py` writes ADRs into a
*consuming* project), so the kit's own decisions are recorded here, in ADR shape.

## Decision

Run the base-freshness gate at exactly two points in a change — Stage 0 (Orient) and immediately
before the push and PR (`pre-push-gates`) — and nowhere else. A stage that needs the merge-base to
diff against obtains it without a gate.

## Context

The gate was wired in at the start of **every** stage, and then again, independently, inside
`research-existing-code`, `implement-phase`, `pre-push-gates` and `zethus-pr-description`. With the
default `branchModel.maxBehind` of `0`, any one of those runs can stop work for a rebase.

Ceryce, reporting on using the kit (2026-10-07):

> "Zethus checks branch freshness WAAAAAAAAY too often. It does it at the beginning of every stage,
> sometimes it goes through all 7 stages in an hour, though."

Two facts in that sentence decide it. Seven stages can pass in an hour, so the gate fires roughly
every few minutes, on a base that moves at the speed of other people's merges — far slower. And a
check that stops the work has a cost of its own, paid every time it fires, whether or not anything
had moved.

What staleness actually costs is unchanged, and is why the gate exists at all: a stale base doesn't
look stale, every diff and measurement taken on one compares *branch drift* instead of the change,
and a PR cut from one can revert work that already landed. But that cost is only realised at two
moments — when the branch is **created or rebased** (everything downstream inherits the base chosen
here) and when a diff **leaves the machine** (the gates check a tree that must be the one that
merges; the PR body describes a diff against the base as it stands). Between those two, a base that
moves costs nothing yet: the next checkpoint catches it before any of it is published.

## Options considered

| Option | What it means | What it costs | |
|---|---|---|---|
| A — two checkpoints | Stage 0 and `pre-push-gates`; `--merge-base-only` for stages that just need a diff base | A base that moves mid-change is noticed at the gates, not the moment it moves — one rebase late in the change rather than one early | **Chosen** |
| B — keep every stage | No change | The reported friction: up to seven stop-the-work checks an hour, on a base that rarely moves that fast | |
| C — raise `maxBehind` | Leave the cadence, widen the tolerance to (say) 10 commits | Fires less often but weakens the gate everywhere, including at the push, which is the one place the count must be exact | |
| D — one checkpoint, at the push only | Drop the Stage 0 check too | Work gets built on a base that was never confirmed, so a rebase lands after the implementation instead of before it — the expensive order | |

## Consequences

- **Easier:** a change runs end to end with two freshness checks instead of seven-plus; stages 1–4
  and 6–7 never interrupt for a rebase.
- **Harder:** a base that moves while a phase is being built is now found at the gates. The rebase
  then happens with the work already written. This is the deliberate trade: it is one rebase, at a
  point where the branch has to be touched anyway, instead of a possible stop at every stage.
- **New obligations:**
  - `--merge-base-only` must stay non-gating. It prints the merge-base and exits 0 whatever the
    branch's freshness, and a failed fetch falls back to the last one rather than returning 3.
    Any stage that needs a diff base uses that mode, never the gating form.
  - The two checkpoints stay non-skippable. The agent's refusal table covers "skip the freshness
    check" at both; a tolerance remains a config decision (`branchModel.maxBehind`), recorded once.
  - A new or rewritten skill must not add a third gate call. `tests/test_zethus.py` holds the
    cadence to the two checkpoints, so a third would land red rather than quietly accumulate.

## Why not the others

- **B — every stage:** the reported problem.
- **C — raise `maxBehind`:** trades precision for quiet in both directions. The push checkpoint
  needs the count exact.
- **D — push only:** gets the order wrong. A rebase before the work is cheap; after it is not.

## Revisit when

The gate stops catching anything at the push (meaning Stage 0 is sufficient in practice), or a
change routinely runs long enough that a base confirmed at Stage 0 is reliably stale by the gates —
in which case the right fix is a cheap non-blocking *notice* mid-change, not a third gate.

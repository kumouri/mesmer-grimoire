# Base freshness runs at two checkpoints, not at every stage

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-07 |
| Deciders | Ceryce Armstrong |
| Source | Ceryce's report of using the kit, 2026-10-07 |
| Enforced where | [`../com.github.copilot/agents/zethus.agent.md`](../com.github.copilot/agents/zethus.agent.md) ("Check the base at two points"), [`../copilot-instructions.md`](../copilot-instructions.md), [`../skills/pre-push-gates/SKILL.md`](../skills/pre-push-gates/SKILL.md) step 0 and *Bring a stale branch up to date*, `--merge-base-only` and the STALE message in [`../scripts/base-freshness.py`](../scripts/base-freshness.py), and the stale-base refusal in [`../com.github.copilot/hooks/stop_guard.py`](../com.github.copilot/hooks/stop_guard.py) |
| Supersedes | the original cadence: `base-freshness.py` at the start of every stage, plus separately inside several skills |
| Superseded by | — |
| Amended | 2026-10-19: Docs moved before Gates, so the stages between the checkpoints are now 1–5 and 7 ([run each check once per phase](run-once-per-phase.md)). The two checkpoints are unchanged. 2026-11-10: the agent rebases a stale branch itself instead of asking the person to ([below](#amendment-2026-11-10-zethus-rebases-a-stale-branch-itself)). The two checkpoints, and that neither is skippable, are unchanged. |

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

- **Easier:** a change runs end to end with two freshness checks instead of seven-plus; stages 1–5
  and 7 never interrupt for a rebase.
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

## Amendment, 2026-11-10: Zethus rebases a stale branch itself

| Field | Value |
|---|---|
| Status | Accepted |
| Deciders | Ceryce Armstrong |
| Source | Ceryce's report, paraphrased, 2026-11-10 |

**What was wrong.** At either checkpoint, a STALE result was a stop: the agent told the person how
many commits behind the branch was and asked them to rebase it, and `rebase` style said outright
that the person rebases. Ceryce's report, paraphrased: Zethus shouldn't break off its work to make
the person rebase the branch; when it notices the branch is behind its configured base, it should
fix that itself.

Bringing a branch up to date is mechanical work the agent can do and check: it has the fetch, the
diff, the spec and the gates. Handing it over cost a round trip at exactly the two points the
change is busiest, and at the pre-push checkpoint it stranded finished, green work behind a step
nobody needed to be asked for.

**Decision.** When `base-freshness` reports STALE, at Stage 0 or before the push and in either
branch style, the agent brings the branch up to date itself and carries on. The steps are in
[pre-push-gates, *Bring a stale branch up to date*](../skills/pre-push-gates/SKILL.md#bring-a-stale-branch-up-to-date):

- `branch-per-change`: rebase onto the freshly fetched `origin/<base>` (a stack from its top with
  `--update-refs`), or cut a fresh branch from it and move the work across when that is cleaner.
- `rebase`: `git rebase origin/<base>`, with `--update-refs` for anything stacked on it.
- Both: resolve conflicts keeping both sides' intent, re-run `base-freshness` until it is FRESH,
  re-run the gates if work was already written, push a rewritten branch with `--force-with-lease`,
  and say in the PR body that it was rebased.

It still stops in two cases, because a rebase can't settle them:

- **No answer (exit 3).** The fetch failed, so there is no known base to rebase onto. Since
  2026-11-10 that is a stop only after the agent has retried and diagnosed the fetch itself, and
  what is left is a credential or network access only the person has
  ([do the work yourself](do-the-work-yourself.md)).
- **A conflict that needs a decision the spec and diff can't make,** such as the base changing the
  very behaviour this change edits, incompatibly. It names the file, the hunk and why, and leaves
  the rebase paused cleanly at that commit (every other file resolved and staged, nothing partly
  resolved committed or pushed) or aborted, never half-applied.

**What doesn't change.** The two checkpoints, and that neither is skippable. A stale base is still
never built on or pushed: what changed is who brings it up to date, not whether it is. The
re-run of `base-freshness` after the rebase finishes the same checkpoint; it is not a third one.

**Enforcement.** The STALE line `base-freshness.py` prints says what the agent is about to do, not
what a person should do. The `agentStop` hook refuses a stop whose `Why:` is a stale base, unless it
names a failed fetch or a conflict. `tests/test_zethus_self_rebase.py` holds the agent files, the
working agreement and the skills to it, including that no agent file asks the person to rebase.

**Kept small in the agent file on purpose.** The change to `zethus.agent.md` is four lines that
used to hand the rebase over: the stop-table row, the STALE row of the exit-code table, the
`rebase`-style Stage 0 bullet, and the refusal-table row. The procedure lives in the skill, the
script and this record, so a customized copy of the agent file can take the change by hand.

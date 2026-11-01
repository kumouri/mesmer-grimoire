# Hand off to the next stage, and never stop silently

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-11-01 |
| Deciders | Ceryce Armstrong |
| Source | Ceryce's report of using the kit, 2026-11-01 (below) |
| Enforced where | *Hand off to the next stage, and never stop silently* and *How you behave at every turn* in [`../com.github.copilot/agents/zethus.agent.md`](../com.github.copilot/agents/zethus.agent.md); *Keep moving, and never stop silently* in [`../copilot-instructions.md`](../copilot-instructions.md); the **Next** line closing every stage skill, including *On sign-off* in [`../skills/write-spec-full/SKILL.md`](../skills/write-spec-full/SKILL.md) and [`../skills/write-spec-minimum/SKILL.md`](../skills/write-spec-minimum/SKILL.md); `tests/test_zethus.py`. Convention only at runtime: no hook or script checks it (see *Why no hook*) |
| Supersedes | — |
| Superseded by | — |

## Decision

When a stage's exit condition is met, start the next stage in the same turn; end a turn only at a
listed stop, and end it with where you stopped, what's next and why.

## Context

Ceryce's report, verbatim:

> "For some reason (and this may have nothing to do with the agent and everything to do with
> GPT-6-Luna or the Copilot CLI or something else) but it stopped after pointer checks and git diff
> --check after updating documentation but never started the phase 0 test implementation part that
> goes next, but it also didn't tell me it was done, it just sat there doing nothing in the middle
> of a thought with Copilot saying "processing" until I interrupted it and asked wtf was happening."

Documentation, then Phase 0, is the Stage 2 → Stage 3 transition: after sign-off the agent records
the decisions as ADRs and marks the spec `SIGNED-OFF` (both are doc edits), and Phase 0 is the next
work. The kit as it stood left that handoff implicit:

| What the kit said | Where | The gap |
|---|---|---|
| *On sign-off*: record the ADRs and set the status to `SIGNED-OFF`. Nothing after | `write-spec-full` and `write-spec-minimum` | No next action. Research, Implement and Docs each named theirs (`research-existing-code`'s *Next* section, `implement-phase`'s "Next: that verify step", `docs-sync-check`'s "Next: [pre-push-gates]") |
| The stage table gave each stage an exit condition | the agent file | Nothing said what to do when one is met. The only spelled-out transition was "After the PR opens, go back to stage 3" |
| "While you wait, you may improve the spec" and the header example "waiting for sign-off" | the agent file | The only turn-ending point described anywhere, and no rule on which other points may end a turn, or what a turn that ends must say |
| `test-plan`'s verify step, `pre-push-gates`, `zethus-pr-description` | the skills | No next action either |

`git diff --check` appears nowhere in the kit; the agent added it itself, which is fine. The pointer
check is [`../scripts/docs-pointer-check.py`](../scripts/docs-pointer-check.py), which only reads
files and runs local `git` commands, and exits.

### What the kit can't fix

Copilot showing "processing" for over thirty minutes with no output means the host still held the
turn. By her account both checks had returned, so no kit process was running, and nothing in the
kit runs in the background. A model or CLI that stops emitting mid-turn is outside anything
instructions or scripts control. This record doesn't claim a fix for it. It fixes the gap the kit
does own, at the point where the stall happened, and makes any turn that does end say why. Whether
the missing handoff contributed to the stall can't be shown from the files.

### Why no hook

A hook that forces a status line at phase boundaries was considered and not added:

- **It wouldn't have fired.** The turn never ended, so neither `agentStop` nor `sessionStart`
  runs. A stop hook catches a turn that ends silently, not one that never ends.
- **Copilot's `agentStop` isn't known to block.** Whether it can hold a turn open is marked
  unverified in the [lessons-capture spec](../../docs/lessons-capture-spec.md) (§4.7, channel 2).
- **The other events don't help.** `sessionStart`'s `additionalContext` reaches the start of a
  session, which the standing instructions already reach on every request, and a
  `userPromptSubmitted` hook's output is dropped (same spec, §3.1).

The rule is held the way the plan rule is ([plan update cadence](plan-update-cadence.md)): in the
agent file, in the working agreement, in each skill's closing line, and pinned by tests.

## Options considered

| Option | What it means | What it costs | |
|---|---|---|---|
| A — explicit handoffs, listed stops, a stop block | Every stage skill names its next action; the agent file lists the only points where a turn ends; a turn that ends says where, what's next and why | A few lines per skill and one section in the agent file | **Chosen** |
| B — a stop hook | `agentStop` checks the last reply for the stop block | Unverified on Copilot, and it wouldn't have fired in the reported case | Declined |
| C — the docs-check script prints a "next" line | One deterministic nudge at the point it stalled | The script is shared by Stage 5 and by people, so it can't know the next step; a generic line is noise | Declined |

## Consequences

- **Easier:** a turn that ends says why, so "is it working or stuck?" has an answer on screen. A
  hang inside the host now shows as a missing stop block, since a turn the agent ended itself
  should have one.
- **Harder:** nothing new to run; replies at a stop are three lines longer.
- **New obligations:** a new stage skill ends with its next action; a new turn-ending point is
  added to the agent file's stop table, not improvised. `tests/test_zethus.py` pins both.

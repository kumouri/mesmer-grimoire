# Update the plan at stage entry and when it changes, not at every step

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-19 |
| Deciders | Ceryce Armstrong |
| Source | Ceryce's ruling, 2026-10-19 |
| Enforced where | *Keep the plan visible*, rule 2, in [`../agents/zethus.agent.md`](../agents/zethus.agent.md); `tests/test_zethus.py` |
| Supersedes | the visible-plan rule's "Mark it done the moment it's done, not in a batch at the end of the turn" |
| Superseded by | — |

## Decision

Update the todo list when a stage is entered and when the plan changes; let the header line on
every reply name the current step in between.

## Context

The visible-plan rule told the agent to mark each step done the moment it was done. With a todo
tool, that is one tool call, and one model round trip, per finished step: roughly 40–60 extra
round trips per change, each paying for the whole context. The analysis behind
[run each check once per phase](run-once-per-phase.md) couldn't measure that cost, but named it as
a likely share of the time spent between stages.

The point of the rule was that the person can always see the plan and where the agent is in it.
The header line already does the second half on every reply
(`Stage 3 · Implement — Phase 1, step 2 of 4: …`), and the list is rewritten anyway at each stage
entry and whenever the plan changes, with the reason in the reply.

Ceryce ruled on it after the other three changes:

> "Actually do the coarser todo updates, too. I do remember seeing it do a lot of todos."

## Options considered

| Option | What it means | What it costs | |
|---|---|---|---|
| A — coarser updates | Write the list at stage entry and when the plan changes; tick finished steps at the next update; the header names the current step on every reply | Between updates the list can show a finished step as still open; the header is then the live marker | **Chosen** |
| B — keep per-step ticks | No change | One extra round trip per finished step | |
| C — drop the list | Header line only | Loses the plan itself, not just its ticks. The refusal table already declines this | |

## Consequences

- **Easier:** a change makes a todo call per stage entry and per plan change, not per step.
- **Harder:** the list lags by up to one stage. The header line closes that gap, so it now carries
  the step on every reply without exception.
- **New obligations:** the rest of the rule is unchanged. The steps are written before the stage's
  work, exactly one is in progress, a plan change updates the list in the same turn with its
  reason, and no stage exits with open steps. `tests/test_zethus.py` pins both the new wording and
  the absence of the old one.

## Why not the others

- **B — per-step ticks:** the cost she saw in use.
- **C — no list:** the plan is how the person follows the work; only its update rate changes.

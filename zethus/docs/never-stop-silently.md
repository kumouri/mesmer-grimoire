# Hand off to the next stage, and never stop silently

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-11-01 |
| Deciders | Ceryce Armstrong |
| Source | Ceryce's report of using the kit, 2026-11-01 (below) |
| Enforced where | The `agentStop` / `userPromptSubmitted` hook [`../com.github.copilot/hooks/stop_guard.py`](../com.github.copilot/hooks/stop_guard.py) (see *Enforcement*); *Hand off to the next stage, and never stop silently* and *How you behave at every turn* in [`../com.github.copilot/agents/zethus.agent.md`](../com.github.copilot/agents/zethus.agent.md); *Keep moving, and never stop silently* in [`../copilot-instructions.md`](../copilot-instructions.md); the **Next** line closing every stage skill, including *On sign-off* in [`../skills/write-spec-full/SKILL.md`](../skills/write-spec-full/SKILL.md) and [`../skills/write-spec-minimum/SKILL.md`](../skills/write-spec-minimum/SKILL.md); `tests/test_zethus.py`. The first version was convention only; the hook was added after a recurrence (below) |
| Supersedes | — |
| Superseded by | — |

## Decision

When a stage's exit condition is met, start the next stage in the same turn; end a turn only at a
listed stop, and end it with where you stopped, what's next and why.

## Context

Ceryce's report, paraphrased: after updating the documentation, the agent ran the pointer check and
`git diff --check`, then stopped. It never started the Phase 0 test implementation that comes next,
and it never said it had stopped. It sat mid-thought, with Copilot showing "processing", until she
interrupted to ask what had happened. She noted that the cause might lie in the model (GPT-6-Luna),
the Copilot CLI or something else rather than in the agent.

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
kit runs in the background (*correction, 2026-11-06: true of the kit's own scripts, but a session can
start a command that runs in the background, and the kit had no rule for waiting on one; see the
[addendum](#addendum-2026-11-06-waiting-on-a-background-command)*). A model or CLI that stops emitting mid-turn is outside anything
instructions or scripts control. This record doesn't claim a fix for it. It fixes the gap the kit
does own, at the point where the stall happened, and makes any turn that does end say why. Whether
the missing handoff contributed to the stall can't be shown from the files.

### Why no hook (superseded by *Enforcement* below)

A hook that forces a status line at phase boundaries was considered and not added:

- **It wouldn't have fired.** The turn never ended, so neither `agentStop` nor `sessionStart`
  runs. A stop hook catches a turn that ends silently, not one that never ends.
- **Copilot's `agentStop` wasn't known to block.** It has since been checked: it can (see
  *Enforcement*).
- **The other events don't help.** `sessionStart`'s `additionalContext` reaches the start of a
  session, which the standing instructions already reach on every request, and a
  `userPromptSubmitted` hook's output is dropped (same spec, §3.1).

The rule is held the way the plan rule is ([plan update cadence](plan-update-cadence.md)): in the
agent file, in the working agreement, in each skill's closing line, and pinned by tests.

## Recurrence, 2026-11-03: stopped between Phase 0 and Phase 1

Ceryce's report, paraphrased: two days after the rule above, a session ended its turn after Phase 0
with a short update saying the phase was committed, had no errors and had passed the local gates.
Phase 1 was never started, and nothing in the turn was a listed stop. The plan allowed it to go
on: the work it could do was waiting, and no approval or open question was in the way.

What the files show, and what they can't:

| Question | Finding |
|---|---|
| Was the rule in the text the model saw? | On the machine checked, the installed plugin was the version that already carried it, in the agent file and in both plugin layouts. A different machine's install can't be seen from the repo, and the session didn't announce its plugin version, so a stale install would have been invisible. It now announces it (`sessionStart`) |
| Was anything in code enforcing it? | No. The record above declined a hook; the rule was prose only. The kit has no plan-state file for a hook to read: `_session_state.py` and `_ledger.py` are the web-app session inventory and the rule ledger, not a session plan |
| Did the wording leave a gap? | Yes. The stop table had one row about the end (*the PR is open*) and said nothing about a turn that ends after a commit or green gates but before the push, and nothing treated a progress update as a non-stop. It also had no general rule for the two real walls (an approval, or a question with no citation) or for presenting all of them together |

Which of these was *the* cause can't be told from here: no transcript of the session is in the
repo. The prose was present on the checked install, so the likeliest causes are the missing
enforcement and the wording gap; both are closed below, and the version line closes the third.

## Enforcement: the stop guard hook

[`stop_guard.py`](../com.github.copilot/hooks/stop_guard.py) is registered for two events in the
plugin's hook file:

- **`agentStop`** (Copilot CLI: checked that it can block, and that a block's reason arrives as a
  queued message the model acts on). It reads the last assistant message from the transcript. If it
  is a Zethus turn (it opens with the `Stage N ·` header) and does not end with `Stopped at:` and a
  `Why:` that names a real wall, the hook refuses the stop and states the next action. After two
  refusals in a session it lets the turn end, so it cannot trap one.
- **`userPromptSubmitted`**: the fallback for a host whose stop event can't block. If the previous
  turn ended without a real stop, the next prompt carries a reminder to continue first.

It also refuses a Stage 3+ stop that asks leave to move a failing local gate's remediation into the
phase being pushed, even though a decision looks like a wall: [every local gate is green before a
push](gate-remediation-in-the-plan.md), so there is nothing to ask. The Stage 2 planning stop is
exempt, since asking for that ruling there is the point.

It refuses a stop whose `Why:` is a stale base, too: the agent [rebases a stale branch
itself](base-freshness-cadence.md#amendment-2026-11-10-zethus-rebases-a-stale-branch-itself). A
`Why:` that names a failed fetch or a rebase conflict it can't decide is still a real stop.

Since 2026-11-10 it also refuses a stop that hands the person a job the agent can do itself
([do the work yourself](do-the-work-yourself.md)): a `Why:` that waits on the person to run,
install, fix or regenerate something, unless it names what only they can give; a failed-fetch
`Why:` that doesn't name the credential or network left; and a done stop over red CI.

Limits, stated plainly:

- The hook cannot see the plan. The kit keeps it in the host's todo tool, which a hook can't read,
  so the test is on the closing block, not on whether a phase is unfinished. A model can still write
  a `Why:` that names a wall it hasn't reached; the hook only catches the progress-report ending.
- The transcript's shape isn't verified on every host. A transcript it can't read means allow.
- IntelliJ's Copilot server may not run `agentStop` at all; the same registration is mirrored to
  its root and is simply inert there if so. Repo-mode and user-mode `install.py` copies carry the
  text rules but no hook, because the kit's hooks ship only in the plugin.

## Addendum, 2026-11-06: waiting on a background command

Ceryce's report, paraphrased: in a Copilot CLI session the model started an install that takes a few
minutes as a background shell. It then spent its reasoning working out how to wait: it believed it had
no wait tool, could not ask the person, and considered reading the shell's output as a silent wait.
It got there, but with effort and some risk each time, because the kit said nothing.

The gap: a command still running in the background is not a listed stop, so ending the turn is
silent, yet the kit never said how to wait. The stop table, the stage hand-offs and the independent
work rules all assumed the work was in the foreground.

What changed, adding to the decision above and replacing none of it:

| Where | Change |
|---|---|
| The agent file, in *Hand off to the next stage* | When a command runs in the background and its result is needed, block on the harness's output read with a long delay (on the Copilot CLI, `read_powershell` with the shell's id; the tool describes a delay of 120 seconds or more as right for waiting, and documents no cap), repeat until it exits, don't narrate each read, don't end the turn, don't start work that depends on the result |
| The stop table | A new row: the command outlived the wait bound (the one the person gave, else 30 minutes of waiting). The stop block says it is still running in the background, how long was waited, what it waits on and what is next |
| [`stop_guard.py`](../com.github.copilot/hooks/stop_guard.py) | See below |
| The working agreement | The short form of the rule |

**Can the guard fire on a turn that is legitimately waiting?** Not while it waits: the model is inside
a tool call, and `agentStop` runs when a turn ends. It could fire on the report after the bound runs
out, because the guard's wall words did not include a running command, so that honest stop would have
been refused as a progress report. The guard now accepts a `Stopped at:` block whose `Why:` says the
command is still running in the background **and** whose closing lines give a duration waited
("waited 30 minutes"). It is deliberately narrow:

- "Waiting on the background install" with no duration is still refused, which is the silent stop
  the rule exists to prevent. Its refusal now says to block on the output read, not to start the next
  phase, since the next phase may read the result.
- The guard can't see the bound or check the duration against it, only that a duration is stated, so
  a model can still write one it didn't wait. That is the same limit as a `Why:` naming a wall it
  hasn't reached (see the limits above), and the same bounded refusals apply.

The next-prompt reminder gets the same distinction: a turn that ended to wait on a background command
is told to resume the wait first.

Declined: a "sleep" or poll loop run as a command, since it holds the shell and hides the real
command's output; and asking the person whether to keep waiting, since a wait is not a decision and
the person can't be asked in a headless run.

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

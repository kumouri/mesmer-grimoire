# Local gates are green before every push, and a plan that defers one says so

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-11-04 |
| Deciders | Ceryce Armstrong |
| Source | Ceryce's report of using the kit, 2026-11-04 (below) |
| Enforced where | `run-local-gates.py` and `_gate_rulings.py` (verdict, exit 4); `gate-remediation-check.py` (the spec section); the `agentStop` / `userPromptSubmitted` hook [`../com.github.copilot/hooks/stop_guard.py`](../com.github.copilot/hooks/stop_guard.py); *Local gates are green before every push* in [`../com.github.copilot/agents/zethus.agent.md`](../com.github.copilot/agents/zethus.agent.md) and [`../copilot-instructions.md`](../copilot-instructions.md); [`../skills/implement-phase/SKILL.md`](../skills/implement-phase/SKILL.md), [`../skills/pre-push-gates/SKILL.md`](../skills/pre-push-gates/SKILL.md), the two write-spec skills; the *Gate remediation* section of both spec templates; `tests/test_zethus_gate_remediation.py` |
| Supersedes | — |
| Superseded by | — |

## Decision

Every local gate, SonarQube included, is green before a phase pushes, whatever the phase plan says.
A plan that schedules a remediation phase for what a gate checks must say so, prominently, in the
plan the person signs, and ask for a ruling that is recorded in the spec.

## Context

Ceryce's report, paraphrased: Zethus sometimes plans SonarQube remediation for a phase after phase
0. SonarQube is among the local gates, so a phase 0 that fails it can't push, and the later phase
that would fix it is never reached. The agent then stopped to ask permission to move the
remediation into phase 0. She wanted it to treat the local gates as binding, fix what they report
before pushing, and, when a plan really does schedule such a phase, put that in the plan being
approved with a choice of how to handle it.

The kit had the pieces for this to go wrong. `pre-push-gates` said to fix anything red, and the
stop table accepted "a decision" as a wall, so a model that read "my plan says later" as a
conflict could stop on it, and the stop looked legitimate. The plan templates had no place for the
fact at all: a remediation phase was one row in a phase list.

## What happens now

**Planning.** The spec has a *Gate remediation* section. It says `None — …` when no phase
remediates anything a local gate checks, and asks nothing new. Otherwise it is a table, one row per
gate, and the sign-off request puts it first as its own decision, "Gate left for a later phase":

| Ruling | Meaning | What `run-local-gates` does |
|---|---|---|
| `push-red` | Push with the gate red, because its remediation is scheduled | Exit 4 when that gate's failure is the only one, naming the spec |
| `limited-phase-0` | Phase 0 makes the gate pass with the smallest remediation that does | Gate must pass |
| `reorder` | The phases are reordered so the gates pass from phase 0 on | Gate must pass |
| `other: <what>` | An equivalent the plan names | Gate must pass (it waives nothing) |

`Approved` is `PENDING` until the person answers, then `yes — who, date`. The spec lives on the
branch and in the PR, so a later phase and a later session read the same answer.

**Implementing.** A red gate is fixed in the phase being pushed, without stopping to ask, even
when the plan put its remediation in a later phase. The fix is only as large as turns the gate
green, and the phase's report (*As built*, and the PR's *Gates pulled forward*) says it was pulled
forward and why. The exception is an approved `push-red` ruling.

## Code and prose

Prose had already failed here, in the form of a stop that cited a decision as its reason, so the
rule is enforced in three places rather than by one more sentence:

| What | Enforced by |
|---|---|
| A plan states the deferral | `gate-remediation-check.py` fails a spec with no section, with `None` beside a phase that reads like gate remediation, with an unreadable ruling, or signed off with a `PENDING` one |
| A red gate is not waved through, and a ruled one is | `run-local-gates.py`: only an approved `push-red` row in a signed-off or partly built spec changes the verdict; every other red stays exit 1, and its message says to fix it in this phase |
| The agent doesn't stop to ask | The stop guard refuses a Stage 3+ stop whose closing lines pair a gate with fix or remediation, a phase move and a request for authorization (twice at most, like every refusal). It doesn't touch the Stage 2 stop, where the question belongs |

What stays prose: choosing the smallest fix, and writing the report line. The check can't judge
either. The hook is a keyword test on the closing lines, so a stop worded to avoid those words
gets through; the verdict message and the skills still say what to do.

## Options considered

| Option | What it means | What it costs | |
|---|---|---|---|
| A — the rule above | Gates bind; a deferral is put to the person at planning and recorded | A spec section, a check, an exit code, a hook rule | **Chosen** |
| B — prose only | A sentence in the agent file and the skills | Prose is where this already failed | Declined |
| C — always pull every gate forward, no waiver | No ruling to record | Takes away the choice to push red, which she named | Declined |
| D — waive any gate the plan mentions | Match the phase list against gate names | A later phase's name would silently waive a gate | Declined |

## Consequences

- **Easier:** a phase 0 that hits a red gate carries on instead of asking; the person decides the
  deferral once, where they are already reviewing the plan.
- **Harder:** a spec needs one more section, and a signed-off spec with a `PENDING` row fails its
  check.
- **New obligations:** a new ruling kind goes in `_gate_rulings.py`, the templates and this note
  together. A gate name in a ruling must match the name `run-local-gates --list` shows.
  `tests/test_zethus_gate_remediation.py` pins all of it.

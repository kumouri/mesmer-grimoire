# The person's questions come first

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-11-01 |
| Deciders | Ceryce Armstrong |
| Source | Ceryce's report of using the kit, 2026-11-01 (below) |
| Enforced where | *The person's questions come first* in [`../agents/zethus.agent.md`](../agents/zethus.agent.md); *Questions come first* in [`../copilot-instructions.md`](../copilot-instructions.md); `tests/test_zethus.py`. Convention only at runtime |
| Supersedes | — |
| Superseded by | — |

## Decision

When the person asks a question or raises a concern mid-task, make it the current task: answer it
fully, investigating if needed, and only then offer to resume.

## Context

Ceryce's report, verbatim:

> "It sticks way too hard to the task it's on; I was trying to diagnose wtf happened with it just
> freezing there for 30+ minutes and every time I would ask something—reading its thoughts—it was
> trying to figure out how to answer the question with the least effort possible so it could focus
> on moving my original request forward."

The kit gave the procedure a lot of weight: a stage table, exit conditions, a refusal table, rules
against skipping. It said nothing about questions asked mid-task, so the model ranked them below
the procedure. The effort-saving rulings ([run each check once per phase](run-once-per-phase.md),
[plan update cadence](plan-update-cadence.md)) could be read as a general push to spend less, when
they were about repeated checks.

## Where it's placed

Both files every Zethus session reads, with the same weight as the process rules:

| File | Read by |
|---|---|
| The agent file, its own section beside the stages | Every session that picks the **zethus** agent: VS Code, the CLI, JetBrains and the cloud agent; and VS Code's Claude-harness sessions, which read `~/.copilot/agents` in user mode |
| The working agreement (`copilot-instructions.md`) | Every request on every Copilot surface, with or without the agent; in user mode it is `~/.copilot/instructions/zethus.instructions.md`, which VS Code's Claude-harness sessions also read |

The kit ships no Claude Code instruction file (`CLAUDE.md`, `AGENTS.md`). Claude Code proper reads
only the kit's `SKILL.md` files, which hold one procedure each and no standing rules. A Claude Code
session running a Zethus skill on its own doesn't get this rule from the kit.

## Options considered

| Option | What it means | What it costs | |
|---|---|---|---|
| A — a rule of the same weight, in the agent file and the working agreement | The question becomes the task; full effort; investigation if needed; then an offer to resume, and a wait | Two short sections | **Chosen** |
| B — a row in the refusal table | "Answer briefly and continue" listed as something the agent declines | A refusal table lists requests from the person, not the agent's own habits | Declined |
| C — repeat the rule in every skill | Covers a skill run alone, including under Claude Code | A standing rule copied into a dozen procedures, which drift | Declined |

## Consequences

- **Easier:** asking "what happened?" gets an investigation, not a deflection.
- **Harder:** a question pauses the work until the person says to resume, which costs one reply.
- **New obligations:** the effort-saving rules apply to the procedure, never to an answer, and the
  agent file says so. `tests/test_zethus.py` pins the rule in both files.

# Logging is the first deliverable, added at creation

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-11-19 |
| Deciders | Ceryce Armstrong |
| Source | Ceryce's ruling, 2026-11-19, paraphrased below |
| Enforced where | [`../skills/implement-phase/SKILL.md`](../skills/implement-phase/SKILL.md) (step 2, and *Logging is the first deliverable, in every phase*); the *How you behave at every turn* section of [`../com.github.copilot/agents/zethus.agent.md`](../com.github.copilot/agents/zethus.agent.md); [`../copilot-instructions.md`](../copilot-instructions.md) (*Log from the start*); [`../skills/write-spec-full/SKILL.md`](../skills/write-spec-full/SKILL.md), [`../skills/write-spec-minimum/SKILL.md`](../skills/write-spec-minimum/SKILL.md) and the spec templates (phase guidance); `tests/test_zethus_log_first.py` |
| Supersedes | — |
| Superseded by | — |

## Decision

Logging is the first deliverable of any script, tool or feature Zethus builds. It goes in when the
thing is created, never later when something breaks. At minimum the code keeps a run log holding:

- the configuration it started with;
- the decisions it made, with the input that decided each one;
- every state change that matters (a file written, a record updated, a retry, a fallback taken);
- full errors: the message, the stack trace, and the input that caused them.

Write each line as it happens, so the log survives a crash. A long or repeated run gets its own log
path, so a crashed run can't overwrite or block the next one.

## Context

Ceryce's ruling, paraphrased: Zethus should always add logging from the start, because it finds and
fixes errors faster.

The cost runs one way. A log written at creation costs a few lines. A failure with no log costs
rounds of inference, each one a guess at what the code did that the log would have shown. Logging
added only once debugging starts arrives after the failure it needed to record, so the first
occurrence is lost and has to be reproduced.

The kit already said that Phase 0 "instruments, logs, measures or reports". That made logging a
kind of Phase 0, a change with no behaviour of its own. It didn't make it part of every phase's
code. This ruling does, and leaves the Phase 0 line as it was: a Phase 0 that only adds logging is
still a valid Phase 0.

## How it works now

- **Implement.** Every new script, tool or feature written in a phase has its run log in the same
  commit that creates it. A phase that changes existing code with no log adds one to the paths it
  touches, as part of that phase, and lists it under *As built* if the spec didn't plan it.
- **Plan.** The spec's phases name the logging each phase adds. Phase 0 is often where a log goes
  into existing code, before behaviour changes, so later phases can be judged by what it records.
- **Debug.** When something fails and there is no log, add the log before forming a theory, then
  reproduce.
- **Fit the codebase.** Use the project's own logging library and levels where it has them. A
  stdlib script uses the stdlib logger. A log never holds secrets, tokens or personal data: log
  that a credential was present, not its value.

## Options considered

| Option | What it means | What it costs | |
|---|---|---|---|
| A — a standing rule: logging is part of creating the code | Every phase, every new script or tool | A few lines per thing built | **Chosen** |
| B — logging only in Phase 0 | Leaves the existing line as it is | Code written in later phases has no log, so its first failure goes unrecorded | Declined |
| C — add logs when debugging | Nothing up front | Debugging starts from guesses, and the first failure is lost | Declined |

## Consequences

- **Easier:** a failure points at its cause from the first run, without rounds of inference.
- **Harder:** every phase carries a little more code, and log output has to stay free of secrets.
- **New obligations:** the rule appears wherever Zethus says how to build: `implement-phase`, the
  agent, the working agreement, and the spec skills and templates.
  `tests/test_zethus_log_first.py` pins it in each.

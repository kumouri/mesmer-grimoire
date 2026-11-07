# Ask with the question tool, never for an exact phrase

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-11-04 |
| Deciders | Ceryce Armstrong |
| Source | Ceryce's report of using the kit, 2026-11-04 (below) |
| Enforced where | *Decisions* in [`../copilot-instructions.md`](../copilot-instructions.md); *How you behave at every turn* in [`../com.github.copilot/agents/zethus.agent.md`](../com.github.copilot/agents/zethus.agent.md) and its plugin-root mirror; the confirm steps of the CLI tool skills; `tests/test_zethus_question_tool.py` |
| Supersedes | The "short numbered list of options" wording in the same places |
| Superseded by | — |

## Decision

When Zethus needs a decision and the choices can be listed, it asks with the question tool of the
harness it is running in, so the choice arrives as a picker. Each option has a plain label and a
description of what it means and costs; the recommendation comes first, marked **(Recommended)**;
related decisions share one call. Prose stays right for a truly open question. No prompt makes the
person type an exact phrase.

Without a question tool in the session, Zethus asks a short numbered list and accepts the number or
any clear wording.

## Context

Ceryce's report, paraphrased: Zethus asked her to reply with one of two exact phrases to make a
choice. A choice should be a tap, not a magic word to retype.

The kit already said to ask decisions "as a short numbered list of options", which a model
satisfies in prose. The mutating-command skills said to wait for a "yes", which reads as a literal
reply.

## The tool, per harness

| Harness | Tool | How it was checked |
|---|---|---|
| GitHub Copilot CLI | `ask_user` | Verified: Copilot CLI's own built-in prompts, recorded in a local session log, tell it to use `ask_user` "if available" and otherwise present a numbered list |
| VS Code (Copilot Chat) | `vscode/askQuestions` (`#vscode/askQuestions`) | Verified against the VS Code Copilot cheat sheet, which lists it as the built-in questions-carousel tool; not run in a live session |
| Claude Code | `AskUserQuestion` | Taken from the tool Ceryce's own Claude Code setup names for this; it was not in the tool list of the non-interactive session that wrote this, so not seen live |
| Codex | `request_user_input` | The name is present in the installed Codex binary; whether a session exposes it (a planning-mode tool in some builds) is not verified |
| JetBrains / IntelliJ Copilot | none known | **Not verified.** Falls back to the numbered list |
| Cloud agent, any headless run | none | There is no one to ask; see the safety rule |

The prompts name the tools as examples and say "the equivalent anywhere else", so a harness that
renames its tool, or one in the table that was not verified, still gets a picker where one exists.

## Gates that guard something irreversible

A confirm step that exists for safety keeps its safety when it becomes a picker:

- The options say what happens. The mutating-command skills use **Run it** (with the exact effect
  shown beside it) and **Don't run it**.
- No option is preselected, and a dismissed picker, no answer, or a run with no one to ask means
  *don't*.
- Free-text approval ("go ahead", "approved") still counts, since a person may type instead of tap,
  but it is never required.

Converted gates: the mutation confirmations in `confluence-cli`, `datadog-cli`, `jenkins-cli`,
`jira-cli` and `sonarqube-cli`; the per-issue creation in `spec-to-stories`; the write-back in
`story-enrich`; the Stage 2 spec sign-off; the "Gate left for a later phase" ruling; the session
selection in `session-review`, where no answer scans nothing.

## Options considered

| Option | What it means | What it costs | |
|---|---|---|---|
| A — one shared rule in the agent and the working agreement, skills point at it | Every harness copy gets the same short rule | A few lines in two auto-loaded files | **Chosen** |
| B — name one tool | Simple | Wrong on every other harness | Declined |
| C — leave prose lists | No change | The report that prompted this | Declined |

## Consequences

- **Easier:** a decision is one tap, with the cost beside each option.
- **Harder:** a harness with no picker gets a numbered list, which is the old behaviour.
- **New obligations:** `tests/test_zethus_question_tool.py` fails when a Zethus prompt or skill asks
  for an exact reply, and when the rule is missing from a harness copy.

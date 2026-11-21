# The agent file keeps its rules short, under a character budget

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-11-20 |
| Deciders | Ceryce Armstrong |
| Source | Ceryce's request, 2026-11-20, paraphrased below |
| Enforced where | [`../../scripts/check_zethus_agent_budget.py`](../../scripts/check_zethus_agent_budget.py) and `tests/test_zethus_agent_budget.py` (the budget); [`../skills/zethus-conduct/SKILL.md`](../skills/zethus-conduct/SKILL.md) (the long form); the *Maintaining this kit* section of [`../README.md`](../README.md) |
| Supersedes | — |
| Superseded by | — |

## Decision

The agent file, [`../com.github.copilot/agents/zethus.agent.md`](../com.github.copilot/agents/zethus.agent.md),
holds every rule Zethus follows and routes to the skill that holds the procedure, each rule in a few
lines. Its examples, formats, long explanations and edge cases live in a skill it links:
[`zethus-conduct`](../skills/zethus-conduct/SKILL.md) for the standing rules, or the stage's own
skill. Both copies of the file (the canonical one and the generated IntelliJ mirror) stay within a
budget: over 28,000 characters fails the test suite, and over 24,000 prints a warning.

## Context

GitHub's custom-agent reference caps an agent's prompt at 30,000 characters. Phase -1 (PR #73)
left the file about 66 characters under that, and the mirror, whose generated header adds about 50,
about 14 under. Every feature after that would have had to cut pinned sentences to fit.

Ceryce's request, paraphrased: make the room now rather than later, because her own edits to her
copy of the agent file could push it over the limit.

Moving the detail out cost the file nothing it needs on every turn. The full wording of the
parallel-work rules was already in the working agreement and the `sessionStart` hook; the plan
format, the commit example and the long form of each branch model are read when that rule applies,
not on every turn.

**Why a skill and not a doc here.** `install.py` copies skills into a repo or a user's
`~/.copilot/` but not `docs/`, so a procedure in `docs/` would be missing in every install except
the plugin. Decision records like this one stay in `docs/`: they say why, and nothing breaks
without them.

**What is measured.** `len()` of the whole file as text, frontmatter included. GitHub's reference
counts "the prompt" and doesn't say whether the frontmatter is part of it, so the check counts it.
That only makes the check stricter than the limit.

## Options considered

1. **Move the detail to a skill and add a budget (chosen).** About 6,600 characters freed, and a
   failing test before the next 4,600 or so are spent.
2. **Tighten the wording in place.** That was how Phase -1 fit. Each round frees a few hundred
   characters and leaves none for the next feature.
3. **Split the agent into two agents.** Copilot runs the one agent the person selected, so the
   rules in the other file would not apply to that session.

## Consequences

- A new rule's long form goes in the linked skill first; the agent file gets the rule and a link.
- `scripts/check_zethus_agent_budget.py <file>` measures any copy, including an edited personal one,
  with `--max` and `--warn` (or `ZETHUS_AGENT_MAX_CHARS` and `ZETHUS_AGENT_WARN_CHARS`) to change the
  limits.
- Tests that pinned wording which moved now read it in `zethus-conduct`; the rules they pin in the
  agent file are unchanged.

## Revisit when

- GitHub changes the limit, or documents what it counts.
- The file passes 24,000 characters again: move detail out before adding more.

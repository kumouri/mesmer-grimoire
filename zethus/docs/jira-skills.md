# Zethus extension: Jira integration skills

**Status:** PARTIAL — v1 built, below · **Owner:** Ceryce Armstrong · **Date:** 2026-09-28 ·
**Related:** [`../README.md`](../README.md), [`../skills/spec-to-stories/SKILL.md`](../skills/spec-to-stories/SKILL.md),
[`../skills/story-enrich/SKILL.md`](../skills/story-enrich/SKILL.md)

## The ask

Ceryce, 2026-09-28 02:30 CT:

> "a spec->Jira Story translator that will write decent stories ... And a skill that looks at Jira
> stories, researches them, and fills them out with relevant information so that it's something
> like the spec for that story would be (except only with the human relevant information)."

She flagged, half-joking, that "decent" was undefined. This doc defines it, for review.

- **Answers:** what "decent" means for a generated story, what an enriched story must and must not
  contain, and what has to happen before either skill writes anything to a real Jira instance.
- **Does not answer:** how to authenticate to a specific Jira instance (that's the consuming repo's
  own `JIRA_*` environment, or its Jira/Atlassian MCP server, or its CLI login — this kit only
  detects what's already configured, never configures it).

## What "decent" means

A story is **decent** when both are true:

1. **It passes every INVEST check, or is honestly flagged where it doesn't.** Independent,
   Negotiable, Valuable, Estimable, Small, Testable — each one checked explicitly, per story, in a
   table, not asserted in prose. A story that fails a check ships anyway only when splitting it
   would cost more coordination than the flag does, and the flag says which check and why.
2. **A tester could act on it without asking the author what "done" means.** The acceptance
   criteria are concrete enough to verify — Given/When/Then or a checklist, never "works as
   expected."

Decent is explicitly **not**:

- Padded with boilerplate criteria to look complete.
- A user story statement forced onto something with no user-facing behaviour — an enabler states
  its value in Context instead, or gets folded into the story it enables.
- An invented story point, T-shirt size, or hour estimate. Sizing notes are a rough signal at most
  ("touches one module, no migration"); a number is the team's job at estimation time.
- One story concealing what should be several, or an epic with one story pretending to be several
  phases.
- **An unsourced concrete value stated as a requirement.** A count, duration, limit, threshold, or
  the name of a new thing that doesn't trace to the spec, the code, config, or a doc is a **proposal
  for the PO**, not a fact — marked inline (e.g. "retried up to *N* times *(proposed: 3; PO to
  confirm)*") and listed as an open question, never asserted as settled. This applies to both skills:
  a value spec-to-stories can't trace to the spec, and a value story-enrich can't trace to the story
  or the code it researched.

[`../skills/spec-to-stories/SKILL.md`](../skills/spec-to-stories/SKILL.md) is the full procedure
this backs; [`../skills/spec-to-stories/example/`](../skills/spec-to-stories/example/) is a worked
example, including one story that ships flagged on purpose so the mechanism is visible.

For the enrichment skill, "decent" means the same standard applied to the *output shape*: every
claim about the code is cited to `file:line` (the same discipline
[research-existing-code](../skills/research-existing-code/SKILL.md) already enforces), every
concrete value in a requirement is either cited or flagged as a proposal (the rule above), and the
result reads as something a PO can act on — not a transcript of how the research happened. See
[`../skills/story-enrich/SKILL.md`](../skills/story-enrich/SKILL.md)'s "Human-relevant only" and "No
invented values" sections for exactly what that excludes and requires.

## The approval guardrail

Both skills write Markdown drafts and stop. **Neither creates, updates, or comments on a real Jira
issue without an explicit human approval, given in the same session, after being shown exactly what
would be written.** This mirrors the guardrail `zethus-pr-description` already uses for the one other
shared-system action in this kit ("open it — don't merge it",
[`../skills/zethus-pr-description/SKILL.md`](../skills/zethus-pr-description/SKILL.md)):

- Only an explicit "create these" / "go ahead" / "approved" / "update it" / "post this", said
  *after* the drafts or the diff are shown, counts as approval. Silence, a question, or "looks
  reasonable so far" doesn't.
- Approval covers exactly the batch shown. A person asking to create ten stories after seeing eight
  gets asked again for the other two.
- As with the rest of Zethus, this is enforced by the skill's own instructions, not by a technical
  hook. Both hosts now offer a blocking pre-tool-use hook, but Zethus doesn't install one (see the
  README's "The limit of enforcement"). The discipline is the same one
  `zethus-pr-description`, `write-adr`, and the agent's refusal table already rely on.

## Jira access, and how it's detected

Three tiers, tried in order, documented in
[`../scripts/jira-access.py`](../scripts/jira-access.py)'s own docstring:

1. **An Atlassian/Jira MCP tool**, if the session has one. Only the calling agent can see its own
   tool list, so this tier is checked by the skill itself, in prose — no script can see it.
2. **A CLI on `PATH`** — `acli` or `jira` (go-jira) by default, overridable via `jira.cli` in
   config.
3. **REST, via an environment token** — `JIRA_BASE_URL`, `JIRA_EMAIL`, and one of
   `JIRA_API_TOKEN`/`JIRA_TOKEN` by default, overridable via `jira.baseUrlEnv`, `jira.emailEnv`,
   `jira.tokenEnvVars`.

If none of the three is available, both skills degrade to asking the person to paste the relevant
text — a normal path, not an error state. `jira-access.py` never prints a token's value, only which
environment variable held it.

## Config keys

All optional, read the same way as every other Zethus key (see the README's
[Configuration](../README.md#configuration) table): `stories.dir` (default `docs/stories`, where
`spec-to-stories` writes its output), `jira.cli`, `jira.baseUrlEnv`, `jira.emailEnv`,
`jira.tokenEnvVars`.

## Harness

Like the rest of Zethus, these two skills are plain `SKILL.md` files (`name` and `description`
frontmatter, then prose) and install into `.github/skills/`, so GitHub Copilot (CLI, VS Code,
JetBrains) picks them up the same way it picks up the other ten. Unlike `agents/zethus.agent.md`,
the `SKILL.md` format is not Copilot-specific — Claude Code reads folders of `SKILL.md` files from
`.claude/skills/` the same way, so copying `skills/spec-to-stories/` and `skills/story-enrich/`
there (as-is, no rewriting) works under Claude Code too. Nothing in either skill calls a
Copilot-only or Claude-only tool; both harnesses can run the shell commands (`jira-access.py`,
`research-existing-code`'s own procedure) either one names.

## Decided and unchanged

- **No new script writes to Jira.** `jira-access.py` only detects access; the actual write, once
  approved, goes through whichever mechanism was detected (an MCP tool call, a CLI invocation, or a
  REST call), made by the agent in the moment, not by a stdlib script this kit ships and forgets to
  update when an API changes.
- **No dedicated scaffolding script for stories.** Slicing a spec into stories is a judgment call,
  the same reason `batch-type-spring-jpa-jdbc` has no dedicated script
  (`../README.md`'s modernization table) — the template and the INVEST table keep the *shape*
  testable; the slicing itself isn't mechanical.

## Open questions

1. **Should a future v2 add a script that writes to Jira directly** (given an approved batch),
   rather than leaving the write to the agent's own tool call? Deferred until a real usage pattern
   shows the agent's per-call approach is actually a problem — see the modernization extension's
   own "triggered by evidence, not schedule" precedent
   ([`modernization-shared.md`](modernization-shared.md)).

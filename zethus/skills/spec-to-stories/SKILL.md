---
name: spec-to-stories
description: Translate a Markdown spec (a Zethus spec or any spec-shaped Markdown) into a set of Jira-ready stories, one Markdown file per story plus an index — each with a user-value title, a user story statement where it fits, 2-4 sentences of context, testable acceptance criteria, out-of-scope, dependencies, a traceability link back to the spec section, and optional sizing notes with no invented story points. Every story carries an explicit INVEST self-check and a flag on any criterion it fails; epics group stories when the spec has phases. Produces drafts only — nothing is created in Jira without explicit human approval in this session. Use when a spec is signed off, or far enough along, and needs to become a batch of stories, or when asked to turn a spec into stories or tickets.
---

# Spec to stories

> `<kit root>` is the folder holding Zethus's `scripts/` and `templates/`: the path announced at session start, else two folders above this skill's folder.

A spec describes a change. A story is a unit of work someone can pick up, estimate, and mark done.
This skill does the translation, and refuses to call the output "decent" until it's earned that.

## What "decent" means here

See [`../../docs/jira-skills.md`](../../docs/jira-skills.md) for the full definition. In short: a
story is decent when it passes all six INVEST checks below, or is honestly flagged where it
doesn't, and a tester could act on its acceptance criteria without asking the author what "done"
means. Decent is not: padded with boilerplate to look complete, forced into "As a user…" phrasing
it doesn't fit, or a compound piece of work hiding behind one title.

| Criterion | It means |
|---|---|
| Independent | Ships and is understood without waiting on another story from this batch. If it can't, the dependency is named in *Dependencies*, not hidden. |
| Negotiable | States the outcome, not the implementation. There's still room for a developer and the PO to discuss *how*. |
| Valuable | A human — a user, an operator, the business — is better off once this ships. A technical enabler still gets one sentence, in Context, on who benefits and why. |
| Estimable | There's enough here to size, even roughly. An open question the story depends on makes it inestimable — resolve it first, or note it under *Dependencies*. |
| Small | Fits a single sprint, or one PR-sized effort. When in doubt, split it. |
| Testable | The acceptance criteria let a tester say pass or fail without asking the author what "done" means. |

## Procedure

1. **Read the whole spec first**, not just its "Design" section. The ask, the facts, the phases,
   the out-of-scope list, and the open questions all shape what becomes a story and what doesn't.
2. **Map phases to epics.** If the spec has a `## Phases` table, each phase becomes an epic. A spec
   with no phases produces one flat batch of stories, no epic grouping.
3. **Slice into stories**, preferring smaller. A phase usually becomes more than one story. For a
   technical enabler with no direct user-facing behaviour, either fold it into the story it enables
   or give it its own one-sentence value statement in Context — never ship a story that reads as
   pure implementation with nobody able to say why it matters.
4. **Write each story** from [`../../templates/story.md`](../../templates/story.md): title, user
   story statement (or none, per the note above), context, acceptance criteria, out of scope,
   dependencies, and traceability back to the spec's file and section (a heading, a fact id, or a
   phase row).
5. **Run the INVEST self-check** for each story, filling every row Pass or Flag. A `Flag` gets a
   one-line note under the table naming the criterion and why. Before accepting a flagged story,
   try to split it instead — a flag should be rare, not routine. Ship it flagged only when a split
   would create more coordination cost than the flag itself.
6. **Write the index** from
   [`../../templates/stories-index.md`](../../templates/stories-index.md): one row per story,
   under its epic heading when epics are in use, linking to the file once it exists, and marking
   any flagged story in the Flagged column so a reader never has to open every file to find one.
7. **Sizing notes are optional and never invented.** A rough signal ("touches one module, no
   migration") is fine; a story point, T-shirt size, or hour estimate is not — that's the team's
   call at estimation time, not this skill's.
8. **No invented values in acceptance criteria either.** A count, duration, limit, threshold, or the
   name of a new thing goes in only if the spec actually states it, traced back to the section it
   came from. If a criterion needs a number the spec doesn't give, don't supply one — mark it a
   proposal, e.g. "retried up to *N* times *(proposed: 3; PO to confirm)*", and list it under a
   dependency or a note in Context; the same rule story-enrich applies to a criterion's numbers
   applies here to a story's.
9. **Stop.** Present the drafts and wait — see the guardrail below.

## Output

- `<stories.dir>/<spec-slug>/index.md` — the index (config key `stories.dir`, default
  `docs/stories`).
- `<stories.dir>/<spec-slug>/NNNN-<story-slug>.md` — one file per story, numbered in the order
  they're written.

A worked example, including one intentionally flagged story, is in
[`example/`](example/): [`example/spec.md`](example/spec.md) is the synthetic input,
[`example/index.md`](example/index.md) and the numbered files beside it are the output.

## Splitting an oversized story

Split along a seam the acceptance criteria already show: a story with two unrelated Given/When/Then
blocks is two stories. Split along the same seam whether the spec's phase boundary agrees with it
or not — the phase becomes the epic either way. Every split story still gets its own INVEST
self-check; a split that only moves the "Small" flag onto a different combination of stories didn't
help.

## Guardrail: drafts only

This skill never creates, updates, or comments on anything in Jira. It writes Markdown files and
stops.

**Only an explicit "create these" / "go ahead" / "approved", said after being shown the drafts,
counts as approval.** Silence, a question, or "looks reasonable so far" doesn't. "Just push them,
I trust it" gets the same answer zethus-pr-description gives to "just push it, CI will tell us": decline,
and show the drafts first — approval covers what was actually shown, not what might have been meant.

If, after approval, the batch is to be created in Jira: check whether an Atlassian/Jira MCP tool is
available in this session first (only the calling agent can see its own tool list); otherwise run
`python <kit root>/scripts/jira-access.py` to check for a CLI or a REST token. Create issues one
at a time, report each created key back, and stop and ask again before creating anything beyond the
approved batch.

## Anti-patterns

- **Forcing "As a…" onto an infrastructure story.** State the value in Context instead; a strained
  persona is worse than none.
- **Padding acceptance criteria with boilerplate** ("Given nothing, when nothing, then it works")
  to look complete. An unfillable criterion means the story isn't sliced finely enough yet.
- **Inventing a story point or T-shirt size** because a sizing field looks empty otherwise.
- **Inventing an acceptance-criteria value** (a count, duration, limit, or threshold) the spec never
  stated, and presenting it as a requirement instead of a flagged proposal.
- **One story labeled as an epic**, or an epic with only one story in it — either means the slicing
  step was skipped.
- **A silent split.** If a story became two, the index says so; don't let a reader wonder where a
  described piece of work went.
- **Creating Jira issues before, or beyond, an explicit approval.**

## Next

Once a story exists (in Jira or as a draft here), [story-enrich](../story-enrich/SKILL.md) can go
deeper on any one of them later, closer to when work starts.

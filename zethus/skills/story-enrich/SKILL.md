---
name: story-enrich
description: Research one or more existing Jira stories against the real codebase, cited to file:line via research-existing-code, and produce an enriched version — what it actually touches, current behaviour, tightened or added acceptance criteria, risks and edge cases, and open questions for the PO — human-relevant only, no agent chatter, stack traces, or code dumps. Detects available Jira access (an Atlassian/Jira MCP tool, the jira/acli CLI, or REST via an env token) and degrades to pasted story text when none is available. Outputs a proposed update plus a diff against the original; nothing is written back to Jira without explicit human approval. Use when a story needs fleshing out before estimation or before work starts, or when asked to enrich, flesh out, or research a ticket.
---

# Story enrich

> `<kit root>` is the folder holding Zethus's `scripts/` and `templates/`: the path announced at session start, else two folders above this skill's folder.

A Jira story is usually written before anyone reads the code it touches. This skill closes that
gap: it researches what's actually there, then hands back a version a person can act on — never a
transcript of how the research happened.

## Step 1: get the story

Try these in order, and use the first that works:

1. **An Atlassian/Jira MCP tool**, if this session has one — check your own available tools; this
   is a fact about the session, not something a script can detect. Use it read-only: fetch the
   story's title, description, acceptance criteria, and key.
2. **A CLI or REST access**, detected with `python <kit root>/scripts/jira-access.py`. Exit `0`
   names a `jira`/`acli` CLI or a REST token; use it read-only, the same way. For a `jira` CLI,
   [jira-cli](../jira-cli/SKILL.md) has the setup and auth check, the read commands and their
   output flags: run its setup first and use only its read commands here. The script can't tell
   which tool a `jira` binary is, and that skill's commands are for `ankitpokhrel/jira-cli`, so if
   they aren't recognised, treat the CLI as unavailable and go on to REST or pasted text.
3. **Pasted text.** If neither is available, look in the repo first: a draft under `stories.dir`
   or the spec the story traces to may already hold it. Failing that, ask the person to paste the
   story's title, description, acceptance criteria, and key (if it has one), and name the one thing
   that would let you fetch it yourself next time (the `JIRA_*` variables `jira-access.py` reports
   missing, or a Jira MCP tool). This is a normal path, not a
   fallback to apologize for — plenty of repos have no Jira access wired up at all.

## Step 2: research

Hand the story's description and acceptance criteria to
[research-existing-code](../research-existing-code/SKILL.md) as the question: what does this
actually touch, and what does it do today? That skill's output — a facts table cited to
`file:line`, plus what it didn't cover — is the evidence base for the enrichment. Don't skip it and
write the enrichment from the story text alone; the story text is exactly the thing being checked.

## Step 3: produce the enrichment

| Section | Content |
|---|---|
| Summary | One or two sentences, plus the original key/link if there is one. |
| What it actually touches | Files, modules, or services, cited to `file:line`. |
| Current behaviour | What the code does today, as observed — not what the story assumed. |
| Acceptance criteria | The original criteria, each marked kept / tightened / added, plus any new ones the research surfaced. Given/When/Then or a checklist. Every concrete value — a count, duration, limit, threshold, or the name of a new thing — is either cited to the story, a `file:line`, config, or a doc, or explicitly marked as a proposal (see below). |
| Risks & edge cases | What the research found that could go wrong, and any case the current acceptance criteria don't cover. |
| Open questions for the PO | Anything only a person can decide — scope, priority, a tradeoff the code doesn't resolve. |
| Evidence | A short, cited list — see below. |
| Links | The spec or ADR this traces to, if any, and related stories. |

### Human-relevant only

The output is read by a person deciding whether to start this work, not by another agent
continuing it. Leave out:

- Internal deliberation, tool-call narration, or anything describing *how the search went* rather
  than *what it found*.
- Stack traces and raw error output — describe the failure mode in a sentence instead.
- Code dumps. A citation (`file:line`) is enough; an inline snippet is fine only when it's a handful
  of lines that the sentence around it can't say more plainly, and even then it's still cited.

The **Evidence** section is where citations live: a short list, each line one fact and its
`file:line`, in the same style [research-existing-code](../research-existing-code/SKILL.md) uses.
It is not a place to paste the research transcript.

### No invented values

Research surfaces what the code does, not what a good number would be. When an acceptance
criterion needs a concrete value — a retry count, a timeout, a size limit, a threshold, the name of
a new field or component — and neither the story, the code, config, nor a doc actually states it,
that value is **not a requirement**. Mark it as a proposal instead, inline, e.g. "retried up to *N*
times *(proposed: 3; PO to confirm)*", and add a matching line under **Open questions for the PO**
naming exactly what's unsourced. A confidently-stated number that came from nowhere is the failure
this whole skill exists to prevent — an enricher that invents requirements is worse than one that
flags a gap.

## Step 4: diff against the original

Produce the enrichment as a proposed update, then a diff against the original story text (a unified
diff is fine) so the reviewer sees exactly what changed rather than re-reading the whole thing.
[`example/`](example/) has a worked pair: [`example/story-before.md`](example/story-before.md),
[`example/story-enriched.md`](example/story-enriched.md), and the diff between them.

## Guardrail: drafts only

This skill never updates, comments on, or edits a field on a real Jira issue. It produces the
proposed update and the diff, and stops.

**Only an explicit approval, given after being shown the diff, counts as approval:** a picked "Update it" on the question tool, or any clear "update it" / "post this" / "approved" (no exact phrase is required). Silence or a question doesn't. Once approved, write back using whichever access was
detected in Step 1 — MCP, CLI, or REST — one issue at a time, and report what was written (which
fields or comment, on which key). A CLI write also follows the confirmation steps in
[jira-cli](../jira-cli/SKILL.md), which state the exact command and get a picked go-ahead: that is on top
of the approval above, never in place of it. If access is pasted-input only, hand the person the proposed
update to paste in themselves; that's not a lesser outcome, it's the guardrail working as intended.

## Anti-patterns

- **Skipping Step 2** and rewriting the story from its own text — that just launders the story's
  existing assumptions with more words.
- **A citation that doesn't support the claim next to it.** Same rule as
  [research-existing-code](../research-existing-code/SKILL.md).
- **Stating an invented value as a requirement.** A retry count, timeout, or threshold that isn't in
  the story, the code, config, or a doc gets marked *(proposed: ...)* and raised as an open question
  — never presented as settled fact.
- **Pasting a stack trace or a 40-line function** into the output because it was handy. Cite it.
- **Writing back to Jira before an explicit approval of the diff shown.**

## Next

If the story traces back to a spec, [spec-to-stories](../spec-to-stories/SKILL.md) may already
have produced the traceability link this skill's *Links* section can point to.

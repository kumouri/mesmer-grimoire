---
name: write-adr
description: Record a decision as an Architecture Decision Record — one imperative decision sentence, context, options with the chosen one marked, consequences, where the decision is enforced, and when to revisit it. Plain Markdown that pastes cleanly into a wiki page or ticket. Use whenever a decision is made in chat, a meeting, a spec review or a PR thread, or when a spec's open question is answered.
---

# Write an ADR

> `<kit root>` is the folder holding Zethus's `scripts/` and `templates/`: the path announced at session start, else two folders above this skill's folder.

A decision made in conversation binds nobody. It gets forgotten, then asked again, and sometimes
answered differently the second time. It counts as a decision only once it is recorded somewhere
tracked, in the same change that acts on it.

## Procedure

1. **Create the record:**
   `python <kit root>/scripts/new-adr.py "<decision as a short title>" --deciders "<who>"`.
   This writes `docs/adr/<YYYY-MM-DD>-<slug>.md` (or `adr.dir` from config) and adds a row to that
   directory's `README.md` index. The id is keyed to the date, not numbered, so two branches
   adding ADRs at the same time never collide.
2. **Decision.** Write one imperative sentence with no reasoning in it: "Retry webhook deliveries
   with exponential backoff, capped at 1 hour." If it takes two sentences, it is two decisions and
   needs two ADRs.
3. **Context.** Say what forced the decision, citing `file:line` or the spec's facts by number.
4. **Options considered.** Include "do nothing". Mark the chosen option.
5. **Consequences.** Say what gets easier, what gets harder, and what new obligations it creates.
6. **Enforced where.** Name the mechanism: a file and symbol, a CI check, a branch-protection rule,
   a lint rule. If nothing enforces it, write "convention only". That tells readers the rule will
   decay unless someone builds a mechanism for it.
7. **Revisit when.** Name the condition that would reopen the decision.
8. **Link both ways.** Cite the ADR id in the spec, where the open question now reads
   `DECIDED (date, ADR id)`, and in the PR description.

## Changing a decision

Don't edit an accepted ADR's decision. Write a new ADR, fill in its `Supersedes`, set the old
record's `Superseded by` and status, and update both rows in the index.

## Pasting into a wiki or ticket

The template is plain Markdown: headings, one field table, one options table. There is no HTML and
there are no diagrams. It pastes as-is into Markdown-aware wikis and trackers. The file in the repo
stays the canonical copy: link to it from the wiki page, not the other way round.

## Asking for the decision

If the decision hasn't been made yet, ask for it first. Give a short numbered list of options,
recommendation first and marked **(Recommended)**, with a one-line cost each. Write the ADR once
you have the answer.

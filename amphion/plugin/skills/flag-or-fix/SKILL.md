---
name: flag-or-fix
description: Decision framework for in-flight situations not covered by the project's standard playbook. Use when working through a phase or spec-driven implementation and you encounter something the briefing, spec, or CLAUDE.md doesn't directly address — a missing file, a layout that won't accommodate the spec's copy, an out-of-scope issue, a voice or naming judgment call, or unexpected breakage. Walks through fix-now / fix-and-flag / defer / stop.
---

# Flag or fix

You're mid-implementation and you've hit something the briefing or spec doesn't directly address.
This skill walks a decision framework rather than letting you improvise.

The default for spec-driven work is: **the decisions are already made — implement, don't
re-decide.** This skill helps you act consistently with that default when the spec runs out.

Before invoking it, check the project's `CLAUDE.md` "when you hit something unexpected" table, if
one exists — most situations are covered there. This skill is for the ones that aren't.

## Step 1: Classify the situation

Pick the closest match. If several fit, use the most severe.

| Class | What it looks like | Default action |
|---|---|---|
| **Trivial breakage** | Build/type error from your last edit, unclosed tag, missing import | **Fix now**, no flag |
| **Layout/spec mismatch** | The spec's content is longer or shorter than the slot it goes in | **Adapt the layout** — the spec's content is the constraint |
| **Out-of-scope issue** | A real problem in another phase's territory | **Flag in the PR**, don't fix |
| **Voice / naming judgment call** | Two phrasings both plausible; the spec didn't pick one | **Defer to the project's voice guide** (`context.core[].role == "voice"`); flag if still ambiguous |
| **Missing reference** | A file the spec cites doesn't exist | **Verify the path** with Glob, then flag if it really is missing |
| **Regression of a verified fix** | An earlier phase's fix has un-fixed itself | **Stop**, investigate why; don't re-fix forward over it |
| **Briefing/spec conflict** | The two say different things | **The spec wins**; note the briefing's drift in the PR |
| **Genuine novel situation** | None of the above fit | Continue to Step 2 |

If your situation matched a row, take that action and stop. You don't need the rest of this skill.

## Step 2: For genuinely novel situations — apply the decision tree

Answer in order. Stop at the first "yes."

1. **Is the cost of getting it wrong reversible in under five minutes?**
   → Take your best guess and proceed. Note the choice in the PR description so a reviewer can
   correct it cheaply.

2. **Does it block the rest of your phase?**
   → Stop and ask the user. Don't proceed against an unknown constraint.

3. **Does it change a user-visible surface, a public claim, or an outbound link?**
   → Flag it in the PR description **without making the change**. The reviewer decides.

4. **Is it a refactor or cleanup unrelated to your phase?**
   → Don't take it opportunistically. Flag it with `file:line` under the PR's "Noticed but out of
   scope" heading. If your harness can spawn an independent task and the fix is genuinely
   standalone, that's the place for it — not this branch.

5. **Otherwise**
   → Take the action closest to existing patterns in the codebase. Note what you chose and why in
   the PR.

## Step 3: Document the decision

Whichever path you took, capture it. A reviewer should see what you did and why without reading
the full diff. These headings are the ones [`pr-description`](../pr-description/SKILL.md) emits:

- **Fix now** — usually nothing beyond the commit message.
- **Fix and flag** — a line in the PR's verification block.
- **Defer and flag** — a bullet under "Not in this PR (intentional)" or "Noticed but out of scope".
- **Stop** — a question for the user, framed as: *situation, what you tried, what you need to know
  to proceed.*

If the situation cost you real time or had no clear path, it is also a friction point —
`log-friction`, Amphion's skill, where it is installed.

## Anti-patterns

- **Don't silently expand scope.** Even a one-line fix to an out-of-scope file pollutes the PR.
  Flag it.
- **Don't paper over non-trivial breakage.** If the build breaks and you don't understand why,
  revert and document — don't add a `try`/`catch`, a stub, or a `// TODO: investigate` to make it
  pass.
- **Don't write content from scratch when a spec exists.** Apply the spec's text verbatim, or with
  minimal adaptation to the layout.
- **Don't ask the user a question the spec already answers.** Read first.
- **Don't escalate everything.** Trivial breakage and minor phrasing calls don't need a flag — fix
  and move on.

---
name: write-spec-full
description: Write a full specification for a change that spans more than one PR, has a measurement behind it, or has decisions a reviewer will want to argue with. Covers the verbatim ask, measured problem, cited facts, assumptions checked, options with a recommendation, phases where Phase 0 changes no behaviour, test plan, rollback, out-of-scope, and open questions — then stops for sign-off. Use when asked to spec, design, or plan a non-trivial change.
---

# Write a full spec

A spec is where decisions are cheap. Every question settled here is one that won't come up
halfway through a PR. The full template is for work big enough to need that. For a single-PR
change, use [write-spec-minimum](../write-spec-minimum/SKILL.md). Its headings are a strict subset
of these, so a minimum spec can be promoted later by adding sections.

## Procedure

1. **Create the file:**
   `python .github/zethus/scripts/new-spec.py full "<title>" --owner "<who signs off>"`.
   It writes `docs/specs/<slug>.md` (or `spec.dir` from config) from
   `.github/zethus/templates/spec-full.md`, with status `DRAFT`.
2. **The ask.** Paste the request verbatim, with its source and date. List which parts the spec
   answers and which it doesn't.
3. **The problem, measured.** Give the evidence that this matters, from one snapshot, with sources.
   If you can't measure it yet, say so, and plan Phase 0 to measure it.
4. **What is true today.** Run [research-existing-code](../research-existing-code/SKILL.md) and
   paste its facts table and its *Not covered* list. Every design claim below cites a fact by
   number.
5. **Assumptions checked.** List each place where the code contradicted the ask, and which section
   it changed. Phrase it neutrally, as "the ask assumed X; the code shows Y (F3)". If the code
   confirmed everything, write "None found".
6. **Design.** Describe the approach, then an options table with one row marked **Recommended**,
   then what it costs (saying which figures are measured and which estimated), then what it does
   not stop.
7. **Phases.** Put the smallest useful step first. **Phase 0 changes no behaviour**: it
   instruments, logs, measures or reports, so it is safe to ship alone. Give each later phase what
   it is gated on: Phase 0 data (the default window is one week), or a named decision.
8. **Test plan.** Fill it in with [test-plan](../test-plan/SKILL.md).
9. **Rollout and rollback** per phase, and **Before and after**: the headline metric, its baseline,
   and how "after" will be measured.
10. **Out of scope.** List each non-goal with its reason.
11. **Open questions.** Number each one. Give its options, a **recommended** answer and its
    reasoning, and whose call it is.
12. **Self-check.** Does the core recommendation reduce to "be more careful"? If so, replace it
    with something that runs, blocks or measures.
13. **Stop.** Present the spec. Then ask the open questions as one batched list: options,
    recommendation first and marked **(Recommended)**, one-line cost each. Wait for explicit
    sign-off.

## On sign-off

- Record each answered question as an ADR with [write-adr](../write-adr/SKILL.md). In the spec,
  edit the question in place to `DECIDED (date, ADR id)`. Never delete it.
- Set the status to `SIGNED-OFF`. It becomes `PARTIAL(merged: …; in review: …)` as phases are
  pushed and merged, and `BUILT` once the last one merges. A pushed phase is in review, not built.

## Anti-patterns

- **Writing code "to see if it works" before sign-off.** Spikes are allowed only as research,
  thrown away, and reported as findings.
- **Open questions without a recommendation.** A question without a recommendation hands your work
  to the reviewer.
- **A Phase 0 that changes behaviour.** If it can't ship alone without anyone noticing, it isn't
  Phase 0.
- **Numbers from memory or from different moments.** One snapshot, cited.

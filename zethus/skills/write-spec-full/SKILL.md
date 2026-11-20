---
name: write-spec-full
description: Write a full specification for a change that spans more than one PR, has a measurement behind it, or has decisions a reviewer will want to argue with. Covers the verbatim ask, measured problem, cited facts, assumptions checked, options with a recommendation, phases where Phase 0 changes no behaviour, test plan, rollback, out-of-scope, and open questions — then stops for sign-off. Use when asked to spec, design, or plan a non-trivial change.
---

# Write a full spec

> `<kit root>` is the folder holding Zethus's `scripts/` and `templates/`: the path announced at session start, else two folders above this skill's folder.

A spec is where decisions are cheap. Every question settled here is one that won't come up
halfway through a PR. The full template is for work big enough to need that. For a single-PR
change, use [write-spec-minimum](../write-spec-minimum/SKILL.md). Its headings are a strict subset
of these, so a minimum spec can be promoted later by adding sections.

## Procedure

1. **Create the file:**
   `python <kit root>/scripts/new-spec.py full "<title>"`.
   It writes `docs/specs/<slug>.md` (or `spec.dir` from config) from
   `<kit root>/templates/spec-full.md`, with status `DRAFT`. *Owner* and *Requested by* default to
   the person you work for, resolved by `<kit root>/scripts/identity.py`; pass `--owner` or
   `--requester` only for someone else, named as they write it. *Written by* is you, the agent,
   never the owner. If nobody can be resolved it exits 2: ask the person once for the name to
   record, offer to save it (`identity.py --save`), and re-run. Never write a placeholder.
2. **The ask.** Paste the request verbatim, with who asked, its source and date. List which parts
   the spec answers and which it doesn't.
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
   it is gated on: Phase 0 data (the default window is one week), or a named decision. **Every
   phase logs what it builds**, not only Phase 0: name in each phase's *What* the run log it adds
   (starting config, decisions, state changes, full errors), built with the code, not when
   debugging ([why](../../docs/log-from-the-start.md)).
   **Gate remediation.** If any phase remediates something a local gate checks (SonarQube
   findings, lint, types), the plan can't leave that in the phase list: phase 0 couldn't push past
   a red gate. Fill in the spec's **Gate remediation** section, naming each such gate, and in the
   sign-off request put it first, as its own decision labelled "Gate left for a later phase":
   (1) **limited remediation in phase 0** to make the gate pass, (2) **push with the gate red**
   because its remediation is scheduled, (3) **a different phase order** so the gates pass from
   phase 0 on, or (4) an equivalent you name. Recommend one, with its cost. If no phase does, write
   `None — …` and ask nothing new. Run `python <kit root>/scripts/gate-remediation-check.py <spec>`
   before asking.
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
- Record the answer to the gate-remediation question in the spec's **Gate remediation** table
  (`Ruling`, and `Approved` as `yes — who, date`), so a later phase and a later session can read it.
  *Who* is the person who gave the ruling, as they write their name, never you.
- Set the status to `SIGNED-OFF` and *Signed off* to `who, date`, the person who signed it off.
  Then run `gate-remediation-check.py` on the spec: it fails while a ruling is still `PENDING`.
  The status becomes `PARTIAL(merged: …; in review: …)` as phases are pushed and merged, and
  `BUILT` once the last one merges. A pushed phase is in review, not built.
  In `pr-later` style, before any PR opens, it is `PARTIAL(on branch: …; committed: …)`
  ([why](../../docs/phase-advance-without-pr.md)).
- **Next:** in the same turn, start Phase 0 with [implement-phase](../implement-phase/SKILL.md).
  Write its steps, then begin the first one. These records, and any check you run over them
  (`docs-pointer-check`, `git diff --check`), finish the spec stage. They are not a place to stop.

## Anti-patterns

- **Writing code "to see if it works" before sign-off.** Spikes are allowed only as research,
  thrown away, and reported as findings.
- **Open questions without a recommendation.** A question without a recommendation hands your work
  to the reviewer.
- **A Phase 0 that changes behaviour.** If it can't ship alone without anyone noticing, it isn't
  Phase 0.
- **Numbers from memory or from different moments.** One snapshot, cited.

---
name: write-spec-minimum
description: Write a one-screen minimum spec for a change that fits in one PR — the verbatim ask, a cited facts table, the design, phases (Phase 0 changes no behaviour), a test plan, out-of-scope, and open questions with a recommendation — then stop for sign-off. Use for small behaviour changes, bug fixes that change behaviour, and whenever someone says "just code it" (this is the fast path).
---

# Write a minimum spec

This is the fast path, not a way around the process. A minimum spec takes about ten minutes. It
still catches the two most expensive mistakes: building the wrong thing, and building on a wrong
belief about the code.

**Use the full spec instead** ([write-spec-full](../write-spec-full/SKILL.md)) if any of these is
true:

- the change needs more than one PR;
- a measurement justifies it;
- there is more than one open decision;
- it changes a public contract: an API, a schema, a message format, a CLI.

## Procedure

1. **Create the file:** `python .github/zethus/scripts/new-spec.py minimum "<title>"`.
2. **The ask.** Paste the request verbatim, then say what the spec answers and what it doesn't.
3. **What is true today.** Write two to six facts cited to `file:line`, from
   [research-existing-code](../research-existing-code/SKILL.md), plus a one-line *not covered*.
4. **Design.** A short paragraph that cites the facts. If there was a real alternative, name it in
   one line, along with why you didn't choose it.
5. **Phases.** Phase 0 changes no behaviour. For many small changes Phase 0 is "add the test that
   shows the current behaviour", which ships green. Phase 1 changes the behaviour and flips the
   test.
6. **Test plan.** At least one test for the change, and one for its failure or refusal path.
7. **Out of scope.** At least one line, even for a small change.
8. **Open questions.** At most one, with a **recommended** answer. If there are more, you need the
   full spec.
9. **Stop and ask for sign-off.** Ask the open question, if there is one, as a short option list
   with your recommendation first and marked **(Recommended)**.

On sign-off, record the decision with [write-adr](../write-adr/SKILL.md), if there was one, and
set the status to `SIGNED-OFF`.

**Next:** in the same turn, start Phase 0 with [implement-phase](../implement-phase/SKILL.md).
Write its steps, then begin the first one. These records, and any check you run over them
(`docs-pointer-check`, `git diff --check`), finish the spec stage. They are not a place to stop.

## When it grows

If the minimum spec starts to need a second open question, a second PR, or a measurement, promote
it. Add the missing full-template headings from `.github/zethus/templates/spec-full.md` in their
template order. Don't start over.

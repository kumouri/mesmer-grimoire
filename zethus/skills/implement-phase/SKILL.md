---
name: implement-phase
description: Implement exactly one phase of a signed-off spec on its own branch (or as one commit series on a long-lived branch, in rebase or pr-later style) — Phase -1 first when the base already fails a gate (it fixes only that), then Phase 0, which changes no behaviour, and logging first in every phase — keeping the diff inside the phase, flagging anything the spec didn't cover instead of silently deciding it, and recording deviations as an "As built" list. Use when a spec has been signed off and it's time to write code, or when resuming a phase.
---

# Implement a phase

> `<kit root>` is the folder holding Zethus's `scripts/` and `templates/`: the path announced at session start, else two folders above this skill's folder.

Implementation is where a plan quietly turns into something else. The spec said one thing, the
code needed another, and a decision got made inside a diff where no reviewer will see it. This
procedure keeps each phase small and keeps its deviations visible.

## Preconditions — check, don't assume

- The spec's status is `SIGNED-OFF` or `PARTIAL(…)`. If it is still `DRAFT`, stop: there is nothing
  to implement yet.
- You know which phase you're building, and every earlier phase is **committed, green on the
  local gates, and pushed to its PR**. Its PR does not have to be merged: merging is a person's
  call, made whenever the team's process allows ([why](../../docs/phase-advance-on-push.md)).
  If `branchModel.style` is `pr-later`, no PR is needed either: every earlier phase is
  **committed on the working branch with every local gate green**, pushed or not, and no PR is
  opened for it ([why](../../docs/phase-advance-without-pr.md)).
- You're on a branch for **this phase only**. If this phase needs a **new** branch (every phase
  after the first), stack it on the previous phase's branch as pushed:
  `git switch -c <this-phase> <previous-phase>`, and open its PR against that branch, so the PR
  shows this phase alone. If the previous phase's PR has already merged, cut it from the freshly
  fetched base instead: `git fetch` first, then branch from `origin/<base>`, where `<base>` is
  this branch's own base (`base-freshness.py --base-for <branch>` prints it, without gating; a
  child of a long-lived branch gets that branch, [per-branch bases](../../docs/per-branch-bases.md)). If
  you're on the branch Stage 0 just cut or rebased, it already sits on a base fetched and confirmed
  minutes ago, so check that it's the branch you expect and don't fetch again. If
  `branchModel.style` is `rebase`, you're instead on the one long-lived branch, and this phase is
  the next commit series on it, pushed to the same PR (below). If it is `pr-later`, you're on the
  one working branch, and this phase is the next commit series on it, with no PR.
- The base was confirmed fresh when the branch was created or rebased (Stage 0). **Don't re-run
  the freshness gate to start a phase** — it runs twice per change, at Stage 0 and again before
  the push ([pre-push-gates](../pre-push-gates/SKILL.md)), which is where a base that moved while
  you were building gets caught. Either checkpoint that finds the branch stale rebases it then and
  there, by you, not the person
  ([how](../pre-push-gates/SKILL.md#bring-a-stale-branch-up-to-date)).

## Procedure

1. **Re-read the phase row** in the spec: *What*, *Behaviour change*, *Gated on*, *Verified by*. If
   it is gated on data or a decision that doesn't exist yet, stop and say so. If the spec has a
   Phase -1 row, build it first ([below](#phase--1-remediate-existing-issues)).
2. **Phase 0 changes no behaviour.** It only instruments, logs, measures, reports, or adds tests
   that describe today's behaviour. Test yourself: if Phase 0 shipped and nothing followed, would
   any user or caller notice? If they would, it isn't Phase 0. A Phase 0 that only adds logging is
   a valid Phase 0, but logging isn't only Phase 0's job: every phase logs what it builds
   ([below](#logging-is-the-first-deliverable-in-every-phase)).
3. **Write the tests the spec's test plan names for this phase,** in the same change as the code.
   See [test-plan](../test-plan/SKILL.md).
4. **Stay inside the phase.** If you find something that needs doing but isn't in this phase, don't
   fold it in. Classify it:

   | Situation | Action |
   |---|---|
   | Needed for this phase to work, obvious, small, and reversible | Do it, and list it under **As built** |
   | Needed, but it's a real choice between options | **Stop.** Ask with the question tool, recommendation first, then record an ADR |
   | Not needed for this phase | Leave it. Note it for the PR's *Noticed but out of scope* |
   | It invalidates the spec's design | **Stop.** Amend the spec and get sign-off again |

5. **Keep commits small and conventional:** `type(scope): summary`. Every AI-assisted commit
   carries the co-author trailer from `commits.aiTrailer`, and a commit Zethus authors is signed
   with `commits.signature` (default `— Zethus`) on its own line just before the trailer block,
   which stays last, with a blank line on each side. The agent file's *Sign your commits* section
   shows the exact shape. In `rebase` style the phase is a contiguous commit series on the
   long-lived branch, not a branch: name the phase in each
   subject (`feat(retry): phase 1 — …`), don't interleave commits from two phases, and start the
   next phase only once this one is committed, green on the gates, and pushed to the PR. Committing is not the end of a phase: the gates, the push and the PR follow in the same turn.
   In `pr-later` style the phase is a commit series on the working branch in the same way, but the
   next phase starts once this one is committed with every local gate green. Then push the branch
   as a backup, after the pre-push gates, unless the person said not to; **open no PR**, not even a
   draft, until the person says to.
6. **Update the spec** in the same branch. Mark the phase `in review (PR #n)`, and any earlier
   phase whose PR has merged since `merged (PR #n)`; add an **As built** list with every deviation
   and its reason. The status names both halves, leaving out an empty one:
   `PARTIAL(merged: phases 0–1; in review: phase 2)`. A pushed phase is in review, not built:
   leave `BUILT` for when the last phase's PR merges. In `pr-later` style there is no PR to name:
   mark the phase `on branch (<short sha>)` once it is pushed, or `committed (<short sha>)` while
   it is only local, never `in review` or `merged`. The status reads
   `PARTIAL(on branch: phases 0–1; committed: phase 2)`, leaving out an empty group. With no PR to
   hold it, the **As built** list also carries this phase's gate table and any rebase onto
   `origin/<base>`, so the PR body is ready when the person asks for it
   ([when the PR opens](../../docs/phase-advance-without-pr.md#when-the-pr-is-eventually-opened)).
7. **Code in progress doesn't hold work that doesn't run it.** A deployed run, a remote job or a
   long-running task starts as soon as this phase's pending change doesn't touch what it runs.
   Check the image or artifact build and the deploy definition instead of guessing, say in one
   line what you checked, and if they don't settle it, ask once, with the question tool. Results
   collected while local tooling was still changing get re-judged with its final version, and the
   run log says so ([why](../../docs/independent-work-runs-concurrently.md)).

## Phase -1: remediate existing issues

When the Stage 0 survey (`<kit root>/scripts/baseline-gates.py survey`) found gates already
failing on the untouched base, the spec's *Pre-existing gate failures* section lists them and its
Phases table has a Phase -1 row. Phase -1 comes before Phase 0, so the planned change starts from
green ([why](../../docs/phase-minus-one.md)). If the section says `None`, there is no Phase -1:
start with Phase 0.

1. **Its own branch, or its own series.** In `branch-per-change`, cut Phase -1's branch from the
   freshly fetched `origin/<base>`, with its own PR against the base; Phase 0's branch is then
   stacked on it (`git switch -c <phase-0> <phase-minus-1>`), its PR targeting Phase -1's branch.
   In `rebase` and `pr-later`, Phase -1 is the first commit series on the branch, each subject
   naming `phase -1` (`fix(style): phase -1 — LF line endings in Foo.java`).
2. **Fix every `fix` row, and nothing else.** Only the files and rules the findings name, as small
   as turns each gate green: convert the line endings, drop the trailing whitespace, apply the
   lint rule, repair the broken test setup. No refactoring, no reformatting beyond the rule, and
   none of the planned change. A file the fix truly needs that no finding names (a
   `.gitattributes` entry, say) goes under *As built*. The spec rides with this, the bottom phase.
3. **Change no behaviour.** If a fix would change what the code does, it isn't a Phase -1 fix:
   it is an `ask` row, and the person rules on it. Mid-phase, that is step 4's "real choice" row.
4. **Log it.** The survey's run log and record hold what ran and what failed. Add to the *As
   built* list what Phase -1 fixed, gate by gate, and run
   `python <kit root>/scripts/baseline-gates.py scope` (with `--also <path>` for each file from
   step 2): it fails on a file no finding names, or a layout-only file changed beyond whitespace,
   and logs each finding as changed or untouched.
5. **Then it is a phase like any other:** its tests (often none beyond the gates themselves), docs,
   gates, push, PR and spec status. Its PR says what was already red, and that the planned change
   isn't in it. Don't stop to ask leave to fix a pre-existing failure, or to skip one: the
   `agentStop` hook refuses that stop. An `ask` row was ruled on at sign-off; apply the ruling.

## Logging is the first deliverable, in every phase

Any script, tool or feature this phase creates gets its logging **in the same commit that creates
it**, before its features, never later when debugging. It finds and fixes errors faster than any
amount of inference afterwards ([why](../../docs/log-from-the-start.md)).

- **What the log holds, at minimum:** the configuration the run started with, the decisions it made
  and the input behind each, the state changes that matter (a file written, a record updated, a
  retry, a fallback taken), and full errors: message, stack trace, and the input that caused them.
- **How it is written:** line by line as it happens, so it survives a crash, at a path of its own
  per run for anything long or repeated. Use the project's logging library and levels where it has
  them, the stdlib logger in a stdlib script. Never log a secret's value: log that it was present.
- **Existing code without a log:** this phase adds one to the paths it changes. If the spec didn't
  plan it, it is the first row of step 4's table (needed, small, reversible): do it and list it
  under **As built**.
- **A failure with no log:** add the log first, then reproduce, then form a theory.

## Every local gate is green before this phase pushes

Whatever the phase plan says. Before the push, `run-local-gates` must be green on every gate,
SonarQube and every other local gate included ([why](../../docs/gate-remediation-in-the-plan.md)).
In `pr-later` style the same green run is also what lets the next phase start, pushed or not. If a
gate is red:

1. **Fix it in this phase, without stopping to ask,** even when the plan put that gate's
   remediation in a later phase. A later phase's name is not a waiver.
2. **Keep the fix as small as turns the gate green:** only the findings or failures that gate
   reports, not the later phase's whole remediation. Leave the rest for that phase.
3. **Say it in this phase's report** (the *As built* list and the PR): the gate, that its fix was
   pulled forward from the later phase, and why (the gate would have blocked the push).
4. **The one exception** is a `push-red` ruling already approved in the spec's *Gate remediation*
   table. `run-local-gates` honours it itself (exit 4, naming the spec). If it exits 1, no ruling
   covers that gate, so fix it.

Don't ask the person for leave to move remediation into the phase, and don't end the turn on it:
the `agentStop` hook refuses that stop. If the smallest fix is a real design choice between
options, that is an ordinary decision (step 4's table), not a request to move the phase.

## Done when

Every test the plan names for this phase is written and compiles (build the tests without running
them: `mvn test-compile`, `gradle testClasses`, `tsc --noEmit`, `cargo test --no-run`,
`pytest --collect-only`), every deviation is written down, and nothing outside the phase changed.
Running a test while you debug is fine, but don't run the phase's tests again as this stage's exit
check: [test-plan](../test-plan/SKILL.md)'s verify step (Stage 4) runs them once, and that run is
the one that counts. Next: that verify step.

## If the spec runs out, or work was interrupted

If the classification table in step 4 is too coarse for the situation, Amphion's `flag-or-fix`
skill is the fuller decision framework. If a previous session or delegate died partway through,
Amphion's `resume-interrupted-phase` rebuilds progress from git rather than from anyone's summary.
If `git status` says a rebase is in progress, a checkpoint paused it at a conflict that needed the
person's ruling: apply the ruling and `git rebase --continue`, then re-run the gates
([pre-push-gates](../pre-push-gates/SKILL.md#bring-a-stale-branch-up-to-date), steps 4 to 6).
Both come from the same author and install alongside this kit. See the Zethus README.

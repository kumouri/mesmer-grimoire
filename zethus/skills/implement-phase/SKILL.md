---
name: implement-phase
description: Implement exactly one phase of a signed-off spec on its own branch (or as one commit series on a long-lived branch, in rebase style) — Phase 0 first, which changes no behaviour — keeping the diff inside the phase, flagging anything the spec didn't cover instead of silently deciding it, and recording deviations as an "As built" list. Use when a spec has been signed off and it's time to write code, or when resuming a phase.
---

# Implement a phase

Implementation is where a plan quietly turns into something else. The spec said one thing, the
code needed another, and a decision got made inside a diff where no reviewer will see it. This
procedure keeps each phase small and keeps its deviations visible.

## Preconditions — check, don't assume

- The spec's status is `SIGNED-OFF` or `PARTIAL(…)`. If it is still `DRAFT`, stop: there is nothing
  to implement yet.
- You know which phase you're building, and every earlier phase has merged (in `rebase` style:
  is complete on the branch).
- You're on a branch for **this phase only**, cut from the freshly fetched integration branch
  (`git fetch` first, then branch from `origin/<base>`). If `branchModel.style` is `rebase`, you're
  instead on the one long-lived branch, and this phase is the next commit series on it (below).
- The base was confirmed fresh when the branch was created or rebased (Stage 0). **Don't re-run
  the freshness gate to start a phase** — it runs twice per change, at Stage 0 and again before
  the push ([pre-push-gates](../pre-push-gates/SKILL.md)), which is where a base that moved while
  you were building gets caught.

## Procedure

1. **Re-read the phase row** in the spec: *What*, *Behaviour change*, *Gated on*, *Verified by*. If
   it is gated on data or a decision that doesn't exist yet, stop and say so.
2. **Phase 0 changes no behaviour.** It only instruments, logs, measures, reports, or adds tests
   that describe today's behaviour. Test yourself: if Phase 0 shipped and nothing followed, would
   any user or caller notice? If they would, it isn't Phase 0.
3. **Write the tests the spec's test plan names for this phase,** in the same change as the code.
   See [test-plan](../test-plan/SKILL.md).
4. **Stay inside the phase.** If you find something that needs doing but isn't in this phase, don't
   fold it in. Classify it:

   | Situation | Action |
   |---|---|
   | Needed for this phase to work, obvious, small, and reversible | Do it, and list it under **As built** |
   | Needed, but it's a real choice between options | **Stop.** Ask as an option list with a recommendation, then record an ADR |
   | Not needed for this phase | Leave it. Note it for the PR's *Noticed but out of scope* |
   | It invalidates the spec's design | **Stop.** Amend the spec and get sign-off again |

5. **Keep commits small and conventional:** `type(scope): summary`. Every AI-assisted commit
   carries the co-author trailer from `commits.aiTrailer`, and a commit Zethus authors is signed
   with `commits.signature` (default `— Zethus`) on its own line just before the trailer block,
   which stays last, with a blank line on each side. The agent file's *Sign your commits* section
   shows the exact shape. In `rebase` style the phase is a contiguous commit series on the
   long-lived branch, not a branch: name the phase in each
   subject (`feat(retry): phase 1 — …`), don't interleave commits from two phases, and start the
   next phase only once this one is complete.
6. **Update the spec** in the same branch. Mark the phase built (or partly built), and add an
   **As built** list with every deviation and its reason. Set the status to `PARTIAL(phases 0–N)`.
   Leave `BUILT` for when the last phase merges.

## Done when

The phase's tests exist and pass locally, every deviation is written down, and nothing outside the
phase changed. Next: [pre-push-gates](../pre-push-gates/SKILL.md).

## If the spec runs out, or work was interrupted

If the classification table in step 4 is too coarse for the situation, Amphion's `flag-or-fix`
skill is the fuller decision framework. If a previous session or delegate died partway through,
Amphion's `resume-interrupted-phase` rebuilds progress from git rather than from anyone's summary.
Both come from the same author and install alongside this kit. See the Zethus README.

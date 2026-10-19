# Run each expensive check once per phase

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-19 |
| Deciders | Ceryce Armstrong |
| Source | Ceryce's ruling, 2026-10-19, on a read-only analysis of where the kit repeats work between stages |
| Enforced where | The stage table in [`../agents/zethus.agent.md`](../agents/zethus.agent.md); [`../skills/implement-phase/SKILL.md`](../skills/implement-phase/SKILL.md) (preconditions, *Done when*); [`../skills/test-plan/SKILL.md`](../skills/test-plan/SKILL.md) (*After implementing — verify*); [`../skills/pre-push-gates/SKILL.md`](../skills/pre-push-gates/SKILL.md); [`../skills/docs-sync-check/SKILL.md`](../skills/docs-sync-check/SKILL.md); [`../skills/zethus-pr-description/SKILL.md`](../skills/zethus-pr-description/SKILL.md) step 1; `tests/test_zethus.py` |
| Supersedes | the stage order Gates (5) → Docs (6), and the Stage 3 exit "tests exist and pass" |
| Superseded by | — |

## Decision

Run Docs before Gates, run the phase's tests once (in Stage 4), and fetch only where a fetch can
change what happens next.

## Context

An analysis of `develop` found the same checks running several times per phase over a tree that
had barely changed. Three repetitions came from the procedure itself:

1. **The full gate suite ran twice.** Gates was Stage 5 and Docs Stage 6. Docs edits the tree after
   the green run, and three standing rules then call for another full run before the push: run
   every gate before every push, commit after green so what you push is what you checked, and
   `pre-push-gates` is for "before opening or updating a PR". On a Maven or Gradle repo one extra
   `verify` costs minutes. The cause was the order, not the rules.
2. **The phase's tests ran up to four times before the gates.** Stage 3 exited on "tests exist and
   pass". Stage 4 checked "exists and passes" again on the same tree, and the mutation check ran a
   failing run and then a restored run. Each separate run pays for compiling and starting the test
   runner, and its raw output fills the context.
3. **The base was fetched three to five times.** The two freshness checkpoints (Stage 0 and
   pre-push) fetch, which [the cadence decision](base-freshness-cadence.md) requires.
   `implement-phase` also told the agent to fetch before every phase, including the first, whose
   branch Stage 0 had cut minutes earlier, and `zethus-pr-description` opened with "Fetch first",
   immediately after the pre-push check had fetched. Neither fetch could change anything: the PR
   skill forbids re-gating.

Ceryce ruled on 2026-10-19 to build these three, together with a coarser todo cadence
([plan update cadence](plan-update-cadence.md)), in one change.

## Options considered

| Option | What it means | What it costs | |
|---|---|---|---|
| A — reorder and de-duplicate | Docs becomes Stage 5 and Gates Stage 6, last before the PR. Stage 3 exits on "tests written and compiling". Stage 4 runs them once, mutation-checks the key test, and proves the restore with `git diff --quiet`. Stage 7 reuses the pre-push fetch; only a new phase branch fetches | Renumbers the stage table and every cross-reference to it | **Chosen** |
| B — cache gate results | `run-local-gates` reuses a green result keyed on the tree | A cached green isn't a run, which brushes against "never report a gate as passed if you didn't run it", and SNAPSHOT dependencies make it impure | Declined |
| C — do nothing | Keep the order and the runs | The second full suite and two to three extra test runs, every phase | |

## Consequences

- **Easier:** a phase runs the full gate suite once instead of twice, and its own tests once (plus
  the key test's mutated run) before that suite instead of up to four times. The gates are also
  *more* accurate: their one green run is on the exact tree that is pushed, docs included.
- **Harder:** anything edited after the gates go green sends the agent back to Stage 6. That was
  always true; the new order just makes it rare.
- **New obligations:**
  - Nothing that edits the tree may sit between Gates and the push. A new stage goes before Gates.
  - The two freshness checkpoints, the full-suite run and the sign-off stop are unchanged, and stay
    so: each has inputs that can change in between, so they protect rather than repeat.
  - The mutation check's restore is proven, not assumed: `git diff --quiet` must exit 0.
  - `tests/test_zethus.py` pins the stage order, the single-run wording and the absence of the PR
    skill's fetch, so a repetition creeping back lands red.

## Why not the others

- **B — cache gate results:** declined; a cache only hides the second run that A removes.
- **C — do nothing:** the cost is paid on every phase of every change.

# Phase -1: remediate existing issues, so the change starts from green

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-11-20 |
| Deciders | Ceryce Armstrong |
| Source | Ceryce's request, 2026-11-20, paraphrased below |
| Enforced where | [`../scripts/baseline-gates.py`](../scripts/baseline-gates.py) (the survey, its record and log, and the scope check); `gate-remediation-check.py` and [`../scripts/_gate_rulings.py`](../scripts/_gate_rulings.py) (the spec's *Pre-existing gate failures* section); the `agentStop` / `userPromptSubmitted` hook [`../com.github.copilot/hooks/stop_guard.py`](../com.github.copilot/hooks/stop_guard.py); *Phase -1* in [`../com.github.copilot/agents/zethus.agent.md`](../com.github.copilot/agents/zethus.agent.md) and [`../copilot-instructions.md`](../copilot-instructions.md); [`../skills/implement-phase/SKILL.md`](../skills/implement-phase/SKILL.md), [`../skills/pre-push-gates/SKILL.md`](../skills/pre-push-gates/SKILL.md), the two write-spec skills; both spec templates and the PR template; `tests/test_zethus_phase_minus_one.py` |
| Supersedes | — |
| Superseded by | — |

## Decision

Before any planned change, Zethus runs every local gate on the untouched base and fixes whatever
already fails, as **Phase -1**, in its own branch and PR (or its own commit series), before Phase 0.
A failure it can't fix safely is named in the plan and asked about once, at sign-off.

## Context

Ceryce's report, paraphrased: she makes her change, runs the tests or the build, and the gates fail
on problems that were already there and have nothing to do with her work. Checkstyle findings such
as CRLF line endings are the usual case, in repos where people routinely skip checkstyle locally.
She wanted Zethus to run the repo's own gates first and fix what already fails, so her change
starts from green.

The kit already said every local gate is green before a phase pushes
([gate remediation in the plan](gate-remediation-in-the-plan.md)). That rule catches pre-existing
failures, but late and in the wrong place: they surface at Stage 6 of Phase 0, after the change is
written, and the fix lands in the same PR as the change, where a reviewer has to separate the two.
Nothing looked at the base before the work started.

## The rules

1. **Survey the untouched base.** At Stage 0, once the branch is cut or rebased and before any
   edit, run `baseline-gates.py survey`. It runs every gate `run-local-gates --list` shows (the
   same list `pre-push-gates` compares against the CI config, a Jenkinsfile or a workflow) on a
   working tree with no tracked changes, and refuses a tree that has them. It records each failure
   with its gate, file and rule. It runs alongside Stage 1's research, which reads and doesn't
   write, and must finish before the spec is written, since the spec records it.
2. **Green means no-op, in one line.** If every gate passes, the survey prints one line saying
   Phase -1 has nothing to do, and the spec's *Pre-existing gate failures* section says
   `None — …`. No branch, no PR, no commit. Phase 0 starts on the task branch as before.
3. **Red means Phase -1.** Each failure becomes a row in the spec's *Pre-existing gate failures*
   table (gate, file, rule), marked `fix` or `ask`, and the Phases table gets a Phase -1 row.
   After sign-off, Phase -1 is built first:
   - `branch-per-change`: its own branch, cut from `origin/<base>`, and its own PR against the
     base. Phase 0's branch stacks on Phase -1's, and its PR targets Phase -1's branch, like any
     stacked phase.
   - `rebase` and `pr-later`: its own commit series, first on the branch, each subject naming
     `phase -1`.
4. **As small as turns the gates green, never mixed with the planned change.** Phase -1 changes
   only the files its findings name, plus the spec (which rides with the bottom phase of the
   stack, as it does with Phase 0 today) and any file a fix truly needs, named with `--also` and
   listed under *As built*. For a layout rule (line endings, trailing whitespace, tabs, a final
   newline, indentation) the diff of that file is whitespace only. `baseline-gates.py scope`
   checks both before Phase -1 pushes.
5. **Phase -1 changes no behaviour of the product.** It makes the existing gates pass on the
   existing code. A fix that would change behaviour is not a Phase -1 fix: it is `ask`.
6. **What is `ask`.** A failure Phase -1 can't fix safely: a real failing test whose fix needs a
   decision about which side is right, a gate that needs a credential or access this machine
   lacks, a fix that would change behaviour. Each `ask` row has a matching row in the spec's
   *Gate remediation* table, with *Remediation phase* `Phase -1`, and is put to the person **once,
   at sign-off**, with the other Gate remediation rulings and the existing options (`push-red`,
   `limited-phase-0`, `reorder`, `other: …`). A missing toolchain is never `ask`: install it and
   re-run, as for any `SKIP`.
7. **Phase -1 is a phase like any other.** Its gates, its push, its PR, its *As built* list, the
   `run-local-gates` verdict and the stop hook all treat it the way they treat Phase 0. Asking
   leave to fix a pre-existing failure, or to skip it, is not a stop at any stage but sign-off.
8. **Log it.** The survey writes what it ran, what failed and each finding to its run log, and a
   machine-readable record beside the clone's git metadata. The scope check logs what Phase -1
   changed against each finding. The Phase -1 PR carries the survey table and the scope result.

## Where each piece lives

| What | Where |
|---|---|
| The survey and the record | `baseline-gates.py survey`. The record is `baseline-gates.json` in a `zethus` folder of the worktree's git directory (`git rev-parse --git-path`), so it is never committed and each worktree has its own. The run log is `~/.copilot/zethus/logs/baseline-gates.log` unless `--log` or `$ZETHUS_BASELINE_LOG` names another |
| The plan | The spec's **Pre-existing gate failures** section, between *Phases* and *Gate remediation*, and a Phase -1 row in *Phases* |
| The ruling on an `ask` | The spec's **Gate remediation** table, *Remediation phase* `Phase -1`, read by `run-local-gates` exactly as before |
| The check on the plan | `gate-remediation-check.py`: the section is present in a spec not yet being built, each row is `fix` or `ask`, each `ask` has its Gate remediation row, and a `fix` row means a Phase -1 row in *Phases* |
| The check on the fix | `baseline-gates.py scope` before Phase -1 pushes |
| Not stopping to ask | `stop_guard.py` refuses a stop outside Stage 2 whose closing lines ask leave to fix or skip a pre-existing gate failure |

`_gate_rulings.py` doesn't count the Phase -1 row as a phase that leaves a gate for later: it
fixes pre-existing failures before Phase 0, so a *Gate remediation* section of `None — …` beside
it is still right.

## Options considered

| Option | What it means | What it costs | |
|---|---|---|---|
| A — Phase -1, surveyed at Stage 0, built first after sign-off | The base's failures are found before the change and fixed in their own PR | A full gate run at the start, a spec section, one script, a hook rule | **Chosen** |
| B — keep relying on the pre-push rule | Pre-existing failures are pulled forward into Phase 0 at Stage 6 | The fix lands mixed with the change, and is found only after the change is written | Declined: it is what she reported |
| C — fix the base before the spec, without sign-off | Faster for layout-only fixes | Code before sign-off, and a broken test can need a decision | Declined |
| D — a ruling per failure instead of a phase | Reuses the Gate remediation table alone | Her ask is that they get fixed, not deferred | Declined; the table is kept for the `ask` rows only |

## Limits

- **Findings are read from gate output.** The survey's verdict is each gate's exit code, as in
  `run-local-gates`. The file and rule columns come from the output's `path:line` and rule tokens
  (checkstyle, ruff and flake8, ESLint, javac, `git diff --check` shapes). A failure it can't
  place is recorded once with file `—` and its exit code, so it is never dropped.
- **A `push-red` ruling still waives the whole gate,** for Phase -1 and every phase after it, as it
  always has. A new failure in that gate is not told apart from the pre-existing one. The survey
  record lets the agent compare by hand; `run-local-gates` doesn't.
- **A broken build can hide failing tests.** Fixing it in Phase -1 can reveal failures the survey
  never saw. Those are found by Phase -1's own gate run and handled the same way: fixed, or, if a
  fix needs a decision, asked then as an ordinary decision, with the question tool.
- **The hook is a keyword test on the closing lines,** like the gate-deferral rule beside it. A
  stop worded around it gets through.

## Consequences

- **Easier:** the person's change starts from green, and its PR holds the change alone. The
  pre-existing fixes can be reviewed and merged on their own.
- **Harder:** every change starts with a full gate run, and a red base adds a branch and a PR.
- **New obligations:** a new finding shape goes in `baseline-gates.py` with a test; the spec
  section, its check and this note change together. `tests/test_zethus_phase_minus_one.py` pins
  them.

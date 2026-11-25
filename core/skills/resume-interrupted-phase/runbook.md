# Recovery runbook (deep operational detail)

`SKILL.md` is the decision framework; this is the precise mechanical procedure it points to. The
doctrine in one line: **git history plus the in-repo ledger are the source of truth — never the
dead agent's memory.** Reconstruct, re-validate, resume; never assume.

Paths and commands below come from `.claude/amphion.config.json`:

| Config key | Used for | Default if absent |
|---|---|---|
| `ledger.path` | The in-repo progress ledger | `docs/PHASE-PROGRESS.md` |
| `gates.build` / `gates.test` | The re-validation commands | Derive from the plan or the repo's build files, and say which you used |
| `gates.mandatedChecks[]` | Project-specific checks (`name`, `command`, `expect`) | The plan's acceptance criteria |
| `branchModel.base` | The branch point for `<base>..HEAD` | The repo's integration branch |

## Step 1 — Confirm it's a crash (classify the return)

| Return looks like | Verdict | Action |
|---|---|---|
| A contract-shaped `REPORT` block (see `report-contract.md`) | Not a crash | Hand to the orchestrator's normal validate step. This skill does not apply. |
| An API error string (`API Error: 500 …`, timeout, transport error) | **Crash** | Continue this runbook. |
| Empty / truncated / cut mid-sentence | **Crash** | Continue this runbook. |
| Generic "completed" / a summary with NO `REPORT` block, no SHAs | **Suspected crash** | Continue this runbook — never mark done on an unverifiable summary. |
| Clean report, but you are picking up cold (new session, post-compaction) | Resume, not crash | Skip Step 1; start at Step 2 to re-anchor on durable state. |

Record the raw return verbatim somewhere durable — you will need its failure class for the friction
log in Step 8.

## Step 2 — Forensics (read-only; reconstruct *what* exists)

Run, against the phase repo and branch:

```
git -C <repo> fetch --quiet
git -C <repo> rev-parse --abbrev-ref HEAD            # confirm you're on the phase branch
git -C <repo> status -sb                             # uncommitted / untracked WIP
git -C <repo> log --oneline <base>..HEAD             # committed sub-phases
git -C <repo> diff --stat <base>..HEAD               # surface area
git -C <repo> stash list                             # any stashed WIP
git -C <repo> diff --stat                            # unstaged changes vs HEAD
```

`<base>` is the branch point — `branchModel.base`, or the repo's integration branch (`develop`
under Git Flow, otherwise the default branch).

## Step 3 — Read the ledger; classify the frontier

Read the ledger at `ledger.path`. Cross-check it against `git log` from Step 2. Each sub-phase
falls into exactly one bucket:

| Bucket | Signal | Meaning |
|---|---|---|
| **Validated** | ledger row `done` + verification recorded, commit present in `git log` | Trust it. Do not touch. |
| **Committed-unvalidated** | commit present, but ledger row missing / `in-progress` / no verification | Code exists; *quality unknown*. Must re-validate (Step 4). |
| **Uncommitted WIP** | untracked files / unstaged diff / `wip(…)` commit / stash | Partial. Inspect and decide (Step 4). |
| **Not started** | no commit, ledger `todo` | The resume target. |

The **frontier** is the boundary between validated and everything after. If the ledger is absent or
stale (the originating failure mode), rebuild the picture from `git log` plus reading the diffs
directly — the ledger is a convenience, git is the authority.

## Step 4 — Re-validate the frontier (establish the lost signal)

You cannot trust validation that died with the agent. Re-establish it:

1. **Last committed sub-phase** — check it out or inspect it; run the build/test gate the plan
   specifies for that sub-phase (`gates.build` / `gates.test`). Record the real result in the
   ledger now; you are repaying the checkpoint debt the crash left.
2. **Re-run every mandated check** in `gates.mandatedChecks[]` that applies to the committed range.
   Compare each against its `expect` value and record the actual evidence, not a "looks fine."
   These are exactly what is lost on a no-report crash — a build status survives in your ability to
   re-run it, but nobody knows a project-specific invariant was checked unless it is written down.
3. **Uncommitted WIP / `wip(…)` / stash** — read it, then decide deliberately:
   - Coherent and consistent with the plan → keep it; fold it into the resumed sub-phase; note the
     decision in the ledger.
   - Incomplete, inconsistent, or unclear → `git reset` or drop it and redo that sub-phase clean;
     note the decision in the ledger.

   Never silently keep, and never silently discard, unreviewed WIP.
4. If re-validation **fails** (a committed sub-phase doesn't build, or a mandated check is red) the
   frontier moves back to *before* that commit. Fix forward from there, or `git revert` / `reset`
   the bad commit deliberately and record why. Do not build new work on an unverified-red base.

## Step 5 — Choose continuation mode

| Remaining work | Mode |
|---|---|
| Small surface, high-judgment, or trust is the issue (validation, security, the load-bearing seam) | **Orchestrator-direct** — the orchestrating session finishes it inline. No fresh delegate. |
| Substantial, mechanical, on established patterns, well-specified by the plan | **Relaunch a fresh agent** with the resume brief (`resume-brief-template.md`) plus the report contract, scoped to ONE chunk. |

When in doubt for the *immediately next* chunk after a crash, prefer orchestrator-direct for one
chunk to re-establish a clean checkpoint, then delegate the rest. The orchestrator always holds the
cross-chunk thread.

## Step 6 — Resume

Resume from the first **not-started** (or reset-to-clean) sub-phase. Enforce the checkpoint
discipline going forward — this is what makes the *next* crash cheap:

- Per-sub-phase commit; never batch.
- Ledger row → `in-progress` + commit **before** the work; → `done` + verification + commit
  **after**, then the sub-phase's own commit.
- `wip(<sub-phase>): <what>` checkpoint before any long or risky operation.
- Re-chunk the remaining work so no single delegated run is a long unhedged bet — size each to one
  build/test gate.

## Step 7 — Transient-error retry policy (bounded)

If Step 1's failure class is a **transient** API error (500 / timeout / transport) **and** the
failed chunk is ledger-idempotent (the resume brief makes a re-run safe):

- The orchestrator MAY auto-relaunch that one chunk **once**, with the resume brief, after a short
  backoff.
- Exactly **one** auto-retry. A second failure ends the auto-loop: surface the state summary from
  Steps 2–4 to the user. Never sleep-loop retries.
- A non-transient failure (bad diff, failing tests, plan conflict) is **not** retried — it is fixed
  or escalated. See `flag-or-fix`.

## Step 8 — Log the friction

Every invocation of this runbook is, by definition, friction. If a friction sink is configured
(`frictionLog` in `.claude/amphion.config.json`), invoke the `log-friction` skill with:

- **What happened** — the failure class from Step 1, verbatim error if there was one.
- **Signal lost** — what the missing report cost (build status, which mandated checks, which
  deviations) and how it was re-established.
- **Recovery cost** — orchestrator-direct vs relaunch; retries; wall-time; whether the user had to
  intervene.
- **Tuning hint** — was the chunk too big, the run too long, the model wrong?

This builds the orchestration-failure dataset that tunes chunk size, model assignment, and retry
policy over time. With no sink configured, put the same summary in the PR description — the point
is that the failure is written down somewhere durable, not which tool holds it.

## Exit

Recovery is complete when: the frontier is re-validated with real recorded results, the ledger
matches `git log`, the resume path is chosen and underway (or the user is holding a clear state
summary), and the friction is recorded. Hand the now-clean frontier back to the normal loop —
implement → validate → final pass.

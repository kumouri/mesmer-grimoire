---
name: resume-interrupted-phase
description: Recovery runbook for orchestration interruptions in phase or spec-driven implementation. Use when a delegated implementation sub-agent returned no usable report — an API error string, an empty or truncated result, or a generic "completed" with no commits/PR/test results — or when picking up multi-commit phase work cold after a crash, context compaction, user interruption, or machine restart. Reconstructs progress and per-sub-phase validation status from git history plus the in-repo progress ledger (never the agent's memory), re-validates the frontier, and resumes from the first unverified sub-phase. Not for normal phase work where the implementer returned a clean structured report (that is the orchestrator's ordinary validate step); not for in-implementer judgment calls (that is flag-or-fix).
---

# Resume interrupted phase

A delegated implementation sub-agent died, or you are picking up multi-commit phase work cold. The
work is partially done and the agent's account of it is gone or untrustworthy. This skill walks the
recovery rather than letting you guess or restart from zero.

**Doctrine, in one line:** git history plus the in-repo progress ledger are the source of truth —
*never* the dead agent's summary. Reconstruct, re-validate, resume.

A missing or non-contract report is itself the signal. What was actually lost is not the code (git
has it) but the **validation status**, which must be re-established, never assumed.

Supporting files in this skill directory:

- [`runbook.md`](runbook.md) — the precise mechanical procedure (commands, truth tables, decision
  trees). The steps below summarize it; follow it for the detail.
- [`report-contract.md`](report-contract.md) — what every implementer must return, and how you
  decide a return is a crash.
- [`resume-brief-template.md`](resume-brief-template.md) — the verbatim block to prepend to any
  relaunched implementer so it is idempotent.

**Config** (`.claude/amphion.config.json`): `ledger.path` is the progress ledger (default
`docs/PHASE-PROGRESS.md`); `gates.build` / `gates.test` are the commands to re-run; and
`gates.mandatedChecks[]` is the list of project-specific checks — each with a `name`, a `command`,
and the `expect`ed evidence — that a crash silently eats. If there is no config, derive the gate
commands from the plan or the repo's build files and say which you used.

## Step 1: Classify the return

| Return looks like | Verdict | Action |
|---|---|---|
| Contract-shaped `REPORT` block (`report-contract.md`) with real SHAs | **Not a crash** | Hand to the orchestrator's normal validate step. Stop — this skill does not apply. |
| API error string (`API Error: 500 …`, timeout, transport) | **Crash** | Continue. |
| Empty / truncated / cut mid-output | **Crash** | Continue. |
| "Completed" / a summary with no `REPORT` block, no SHAs | **Suspected crash** | Continue — never mark done on an unverifiable summary. |
| Clean report, but you are cold (new session / post-compaction) | **Resume** | Continue (skip the crash framing; re-anchor on durable state). |

Capture the raw return verbatim — its failure class is needed for the retry decision in Step 5 and
for the friction log.

## Step 2: Reconstruct from durable state (read-only)

Run the forensics block in `runbook.md` Step 2 (`git fetch`, `status -sb`,
`log --oneline <base>..HEAD`, `diff --stat`, `stash list`). Read the ledger at `ledger.path`.
Cross-check it against `git log` — if the ledger is absent or stale (the classic failure), rebuild
the picture from `git log` plus reading the diffs directly. **Git is the authority; the ledger is
the convenience.**

Classify every sub-phase into exactly one bucket: **validated** (trust, don't touch) /
**committed-unvalidated** (code exists, quality unknown) / **uncommitted WIP** (inspect and decide)
/ **not started** (the resume target). The boundary between validated and everything after is the
**frontier**.

## Step 3: Re-validate the frontier

Validation that died with the agent does not exist. Re-establish it (`runbook.md` Step 4): run
`gates.build` / `gates.test` on the last committed sub-phase; re-run **every check in
`gates.mandatedChecks[]`** that applies to the committed range; record the real results in the
ledger now (repay the checkpoint debt). Inspect any `wip(…)` commit, stash, or untracked WIP and
**deliberately** keep or reset it, noting the decision.

If a committed sub-phase fails re-validation, the frontier moves back to before it — fix forward or
revert deliberately. Never build on an unverified-red base.

## Step 4: Choose mode and resume

- **Orchestrator-direct** when the remainder is small, high-judgment, or trust is the issue
  (validation, security, the load-bearing seam). The orchestrating session finishes it inline.
- **Relaunch a fresh agent** when the remainder is substantial, mechanical, and well-specified —
  scoped to **one chunk**, briefed with `resume-brief-template.md` plus the report contract.

Right after a crash, prefer orchestrator-direct for one chunk to re-establish a clean checkpoint,
then delegate subsequent chunks. Resume from the first not-started (or reset-to-clean) sub-phase.
Going forward, enforce the checkpoint discipline (`runbook.md` Steps 5–6): per-sub-phase commit;
ledger `in-progress` + commit before, `done` + verification + commit after; a `wip(…)` checkpoint
before any long operation; and re-chunk so that no delegated run is a long unhedged bet.

## Step 5: Bounded retry, then log the friction

If the failure was **transient** (500 / timeout / transport) **and** the chunk is
ledger-idempotent, the orchestrator MAY auto-relaunch that one chunk **once**, with the resume
brief, after a short backoff. Exactly one auto-retry. A second failure, or any non-transient
failure, means stop and surface a state summary to the user — see
[`flag-or-fix`](../flag-or-fix/SKILL.md) for the escalation framing.

Then, if the project keeps a friction log, invoke `log-friction` (Amphion's skill, where it is installed) with
the failure class (verbatim error), the signal lost and how it was re-established, the recovery
cost (mode, retries, wall-time, whether the user had to intervene), and a tuning hint (chunk too
big? run too long? wrong model?). Every recovery is friction by definition, and the accumulated
dataset is what tunes chunk size and delegation policy. If no `frictionLog` sink is configured,
put the same summary in the PR description instead — don't drop it.

## Anti-patterns

- **Don't trust the agent's summary over git.** A confident summary with no verifiable SHAs is not
  evidence. Read the diff.
- **Don't restart the whole phase.** Committed sub-phases are durable checkpoints — recover onto
  them, don't bulldoze them.
- **Don't redo or "improve" committed sub-phases.** Your job is the frontier onward.
- **Don't skip re-validation** because the code "looks done." Done ≠ verified, and the verification
  is exactly what the crash ate.
- **Don't silently keep or silently discard WIP.** Inspect, decide, record.
- **Don't sleep-loop retries.** One bounded auto-retry for transient errors, then a human.
- **Don't continue past an unverified-red frontier.** Stop, fix, or revert deliberately first.

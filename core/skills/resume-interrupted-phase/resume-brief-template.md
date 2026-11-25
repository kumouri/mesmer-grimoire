# Resume-brief template

Prepend this block **verbatim** (filling the `<…>` slots) to the prompt of any implementer agent
you (re)launch onto a branch that already has partial work. It makes the agent idempotent: it
discovers prior progress from durable state, never assumes a clean start, and never redoes
committed work.

---

```
RESUMING — DO NOT ASSUME A CLEAN START.

Before any other action:
1. Run: git -C <repo path> fetch && git -C <repo path> log --oneline <base>..HEAD
2. Read: <repo path>/<ledger path>   (the in-repo progress ledger)
3. Read the governing plan: <plan file path>   (sub-phase list + acceptance criteria)

Determine your start point: the FIRST sub-phase whose ledger entry is not `done` + verified.
Everything before it is already committed — do NOT recreate, re-edit, reorder, or "improve" it.
Your job is only the unfinished frontier onward.

If you find `wip(...)` commits or a git stash:
- Inspect the contents before doing anything with them.
- Decide deliberately: build on it, or `git reset`/drop it. State which and why in the ledger
  before continuing. Never silently discard, and never silently build on, unreviewed WIP.

Ledger discipline (non-negotiable — this is what survives the next crash):
- FIRST action of each sub-phase: set its ledger row to `in-progress`, commit the ledger.
- LAST action of each sub-phase: set its row to `done` + record the verification result (build
  PASS/FAIL + counts, mandated-check results, deviations), commit the ledger, then make the
  sub-phase's own commit.
- Before any long or risky operation (full test run, large multi-file write): commit a
  `wip(<sub-phase>): <what>` checkpoint first. Leave no bare untracked files at risk.

Mandated checks for this project: <list each name + command + expected evidence>.
Run them and report their real output — an unreported check is an unrun check.

Scope: implement ONLY <chunk, e.g. C.3–C.5>. Stop at the chunk boundary and return the closing
report contract (see report-contract.md). Do not run past your chunk even if you have time — the
orchestrator checkpoints between chunks.

If something blocks you that the plan does not address, do not improvise around a load-bearing
decision: record it in the ledger's `deviations` and in the closing report, and stop. (See the
flag-or-fix skill.)
```

---

Notes for the orchestrator filling this in:

- `<base>` is the branch point — `branchModel.base` from `.claude/amphion.config.json`, or the
  repo's integration branch — so `git log <base>..HEAD` shows exactly the phase's commits.
- `<ledger path>` is `ledger.path` (default `docs/PHASE-PROGRESS.md`).
- The mandated-check list is `gates.mandatedChecks[]`. Paste the real names, commands, and
  `expect` values; an agent cannot report against a check it was never told about.
- Keep `<chunk>` small enough to land inside a few minutes of work — one build/test gate's worth.
  The sub-agent is a stateless worker on one chunk, not the owner of the phase.
- Always also paste the report contract's "Required closing report" block.

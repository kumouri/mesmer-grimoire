# Implementer report contract

Every delegated implementation sub-agent MUST end its run by returning a report in this shape. The
orchestrator uses it two ways:

1. **When briefing an implementer** — paste the "Required closing report" block below into the
   agent's prompt, so the agent knows the contract.
2. **When the agent returns** — check the return against this contract. A return that does not
   match is a **suspected crash** → run the recovery runbook (`runbook.md`); do NOT mark the work
   done.

## Required closing report (give this to every implementer)

> **Close your run with EXACTLY this report (no prose before it):**
>
> ```
> REPORT
> branch: <branch name>
> chunk: <which sub-phases this run owned, e.g. C.3–C.5>
> commits:
>   - <sha> <subject>            # one line per commit you landed
> ledger: <ledger path> @ <sha>  # the progress-ledger commit
> build: <PASS|FAIL|NOT-RUN> — <command run> — <counts>
> mandated-checks:
>   - <name>: <PASS|FAIL|N/A> — <evidence: the actual output, measured against the check's `expect`>
> deviations: <NONE | numbered list, each with file:line and why>
> pr: <url | NONE — why>
> next: <first sub-phase NOT done, or DONE>
> ```

`<ledger path>` and the mandated-check names come from `.claude/amphion.config.json`
(`ledger.path`, `gates.mandatedChecks[]`). Fill them in when you brief the agent so it reports
against the project's real checks rather than inventing its own.

## What makes a return contract-shaped (orchestrator check)

A return is **valid** only if ALL of these hold:

- It contains a `REPORT` block in the shape above — not prose, not just an error.
- `commits:` lists at least one SHA that actually exists on the branch. Verify with `git log`; do
  not trust the text.
- `build:` is `PASS`, or an explicit and owned `FAIL` / `NOT-RUN` with a reason — never silently
  absent.
- `mandated-checks:` accounts for **every** check the plan or brief required, each with real
  evidence rather than an assertion.
- `next:` is present and consistent with `git log` plus the ledger.

If ANY of these fail — including the return being an API error string, an empty result, a truncated
message, or a generic "completed" with no `REPORT` block — treat it as a **non-report ⇒
assume-crash** signal. The code may well be fine (git is the truth); what is lost is the
*validation signal*, and that must be re-established by the runbook, never assumed.

## Why this exists

The originating incident: a sub-agent died on an API 500 *after* landing five good commits. The
code survived in git, but the build status, the results of the project's mandated checks, and the
deviations the agent had flagged all died with the report.

Per-commit git history answers **what** was done. This contract plus the in-repo ledger answer
**whether it was validated** — the half that otherwise dies with the agent, silently, looking
exactly like success.

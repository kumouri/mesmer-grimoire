---
name: run-one-off
description: "Carry out a one-off: operational work whose only output is an action or an answer, leaving no tracked change — run a Kubernetes job, restart or scale a service, tail logs, run a query or report, kick a pipeline, check a status, a throwaway script you don't commit. No spec, ADR, sign-off, phase, PR or gate. Find the repo's own way first, state the resolved target and exact command in one line then run it, wait for and check the real result, and report what it left behind and how to undo it. If the work turns out to need a tracked-file change, switch to the staged spec path."
---

# Run a one-off

> `<kit root>` is the folder holding Zethus's `scripts/` and `templates/`: the path announced at session start, else two folders above this skill's folder.

This is the third path, beside [write-spec-minimum](../write-spec-minimum/SKILL.md) and
[write-spec-full](../write-spec-full/SKILL.md). It is not a way around the process; it is for work
the process was never about. A one-off **leaves no tracked change** — it performs an action or
returns an answer, and nothing lands in the repo — so there is no spec, no ADR, no sign-off, no
phase, no PR and no gate to run.

## Is it a one-off?

Decide from what the finished work leaves behind, not from what the request is called.

- **One-off** — the output is an action or an answer and no tracked file changes: run or scale a
  job, restart a service, tail or search logs, run a query or a report, kick or check a pipeline, a
  throwaway script you run and discard.
- **Staged, not a one-off** — the work changes tracked code, config or docs: anything that becomes
  a commit. Take the staged path (minimum or full spec), however the request is phrased. "Just run
  it" or "it's a one-off" does not move a tracked-file change off that path.

The person's word wins in either direction: they can ask for the full procedure on an action, or
name an action a one-off. The one thing their word cannot do is turn a tracked-file change into a
no-spec one-off — the output decides that, not the label. **If a one-off turns out to need a
tracked edit**, say so, switch to [write-spec-minimum](../write-spec-minimum/SKILL.md) (or full),
and carry what you already learned into it. Don't refuse the work, and don't commit under this path.

The person asking **is** the go-ahead. Add no confirmation prompt and no refusal of your own; the
only gate is the host's own permission prompt on the command you run. Extra caution is a setting,
not a wall you invent: with `oneOff.confirm: true` in config, ask once with the question tool before
running; absent or `false` (the default), don't.

## Procedure

1. **Find the repo's or team's own way first.** Read, don't invent: existing manifests, scripts,
   runbooks, Makefile targets, CLI-tool skills ([datadog-cli](../datadog-cli/SKILL.md),
   [jenkins-cli](../jenkins-cli/SKILL.md), [sonarqube-cli](../sonarqube-cli/SKILL.md)), the config.
   Use the established command and target, not one you guessed.
2. **State the resolved target and the exact command in one line, then run it.** Name the context,
   namespace or environment and the command, so the person sees what runs and where — then run it.
   One line, not a picker: `context prod-use1, namespace batch → kubectl -n batch create -f …`.
3. **Wait for the real result, and check it.** Not that the command returned — the actual outcome:
   the job reached `Complete`, the pods are `Ready`, the exit code is 0, the logs show what you
   expected. Block on it the way you'd block on any long command; don't end the turn to wait.
4. **Report plainly.** What ran, what happened, where the output or logs are, what it left behind (a
   Job object, a changed replica count, a file), and **how to undo it or clean it up**.
5. **A failure is investigated, not retried.** Read the logs and events read-only, find the cause,
   and report it with the cause named. Don't silently retry: a second attempt is a fresh one-line
   target-and-command statement saying what you changed, never a loop.

**Optional:** if the repo already has a place for an operations note (a runbook log, an ops-channel
file), add one line there. Never a new required artifact, and never a commit the person didn't ask
for.

## A one-off turn

Open the reply with a `One-off · <what you're doing>` header, not `Stage N`. The staged rules — the
stage map, the visible plan, the stop table in the agent file — don't apply: the turn ends when the
result is in and reported, not at an approval wall. The person's questions still come first: if
they ask one mid-flight, answer it fully before carrying on.

## Worked example: run a Kubernetes job

> Request: "run the nightly reconciliation job in staging for me."

1. **Their way.** The repo ships `deploy/jobs/reconcile.yaml`, a `Job` template, and its `README`
   says staging is context `staging-use1`, namespace `batch`. Use that; write no new manifest.
2. **One line, then run.**
   `context staging-use1, namespace batch → kubectl --context staging-use1 -n batch create -f deploy/jobs/reconcile.yaml`
3. **Check the real result.**
   `kubectl -n batch wait --for=condition=complete job/reconcile-nightly --timeout=15m`, then
   `kubectl -n batch logs job/reconcile-nightly --tail=20` — `Complete`, exit 0, "reconciled 412
   rows, 0 errors".
4. **Report.** Ran the template unchanged against staging; job `reconcile-nightly` completed in 6m,
   logs above. It left one `Job` object and its pod in namespace `batch`. Undo:
   `kubectl -n batch delete job reconcile-nightly`.
5. **If it had failed** (say `BackoffLimitExceeded`): read `kubectl -n batch describe job/reconcile-nightly`
   and the pod logs, report the cause (a missing `DB_URL`, say), and stop there — no blind re-run.

If instead the ask were "raise the reconcile job's retry limit", that edits `reconcile.yaml`, a
tracked file: not a one-off. Switch to [write-spec-minimum](../write-spec-minimum/SKILL.md),
carrying what you found here.

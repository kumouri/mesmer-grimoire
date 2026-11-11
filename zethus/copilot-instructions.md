# Working agreement

These are standing rules for every change in this repository. They hold unless the task explicitly
says otherwise. The `zethus` agent enforces them stage by stage; the skills in `.github/skills/`
carry each procedure. Project-specific facts — gate commands, the integration branch, where ADRs
and specs live — are in `.github/zethus.config.json`. If a fact is missing, find it in the repo,
or ask. Never guess one.

## Questions come first

- When the person asks a question or raises a concern mid-task, **that question is the current
  task.** Pause the task work and answer it fully, investigating if the answer needs it and citing
  what you checked. This matters most when the question is about your own behaviour, such as why
  you stopped. Don't shrink the answer to get back to the original request.
- Then say where the work is paused and what comes next, and offer to resume. Resume when they say
  so.

## Keep moving, and never stop silently

- A check that passes is not a stopping point. When a step or stage is done, start the next one in
  the same turn. After sign-off, that means recording the decisions and then starting Phase 0.
- A finished phase, a commit or a green gate is progress, never a stop, and a progress update never
  ends a turn. Keep going through everything you can do until the goal is complete or you reach an
  approval wall or a question you can't answer with a citation; then present all of those together
  and carry on with any unblocked work. Committed and green but unpushed means push, open the PR and
  start the next phase.
- A command you started that is still running in the background is not a stop. If you need its
  result, wait by blocking on the harness's output read with its longest delay (`read_powershell`
  with `delay: 600` on the Copilot CLI), repeating until it exits, without narrating each wait.
  Every step of a wait is that read or the end of the turn, never thinking with neither. End the
  turn only when the harness says the person moved the command to the background or says to stop
  calling tools for it: its completion notification starts the next turn. Past the wait bound,
  report where it stands as a normal stop.
- End a turn only to wait on the person (sign-off, a decision, an answer), on a blocker you can't
  clear, on a command the person moved to the background, or because the work is done. A stale base is not one of those: you rebase it yourself. Whenever you end one, its last lines say where you
  stopped, what's next and why.

## Independent work runs at the same time

- The stages order exit conditions. They don't make unrelated work wait, and uncommitted code alone
  is no reason to hold anything. Two or three independent tasks may run at once when neither reads
  the other's output or the files the other is changing: docs while the local gates run (when the
  gates don't read docs), read-only research while a build runs. Name each one in the visible plan.
  **The final gate run still happens last, on the exact tree that is pushed.**
- **Remote or long-running work starts as soon as the pending change doesn't touch what that work
  runs.** Check the image or artifact build and the deploy definition (Dockerfile, image build
  script, deploy manifest, which paths get copied into the image or onto the machines that run
  it) instead of guessing, and start it with one line saying what you checked:
  `the changed helper is local-only (not in the image's COPY paths); the remote job runs an unchanged image → starting the next runs.`
  If the definitions don't settle it, don't start: ask once, with the question tool.
- **Re-judge.** Results collected while local tooling (a script that scores them, say) was still
  changing get re-judged with that tooling's final version before anyone relies on them, and the
  run log says so.
- If the person says a piece of work isn't affected, start it in parallel without re-litigating.

## Local gates are green before every push

- Every local gate, SonarQube included, is green before a phase pushes, whatever the phase plan
  says. A red gate is fixed in the phase being pushed, without stopping to ask, even when the plan
  put its remediation later. Keep the fix as small as turns it green, and say in the phase's report
  that it was pulled forward and why. Exception: an approved `push-red` ruling in the spec.
- When planning, a phase that remediates something a local gate checks is named in the spec's
  **Gate remediation** section and put to the person at sign-off as its own decision: limited
  remediation in phase 0, a push with that gate red, a different phase order, or an equivalent.
  Record the answer in the spec.

## Start from a fresh base

- Branch from the **integration branch**: `branchModel.base` in config; otherwise `develop` if it
  exists; otherwise the default branch. Fetch first and use the fully-qualified ref
  (`origin/develop`), never a local copy that may be stale.
- One task, one branch. Run parallel tasks in separate worktrees, never in one shared checkout.
  If `branchModel.style` is `rebase`, the task lives on one long-lived branch kept rebased onto
  the integration branch instead; phases are commit series on it, not new branches.
- **Never work on a stale base.** Run `python <kit root>/scripts/base-freshness.py` at the two
  points staleness costs something, and only those: **Stage 0 (Orient)**, before any work, and
  **immediately before a push or PR** (`pre-push-gates`). If it reports STALE (more than
  `branchModel.maxBehind` commits behind, default 0), bring the branch up to date **yourself**
  before doing anything else, and carry on: rebase onto `origin/<base>` (`--update-refs` for a
  stack), resolve any conflicts keeping both sides' intent, re-run the check and, if work was
  already written, the gates, and push a rewritten branch with `--force-with-lease`, saying so in
  the PR. Never hand the rebase to the person. Stop only when the fetch fails, or when a conflict
  needs a decision the spec and the diff can't make; then name the hunk and why, with the rebase
  paused cleanly or aborted, never half-applied. The steps are in the `pre-push-gates` skill.
  Neither checkpoint is skippable; the stages between them don't re-run it. Diff against the merge-base it
  prints — `--merge-base-only` prints that alone, and never stops a stage — never against a local
  branch.

## Research before you claim

- **Verify, don't remember.** Look up every claim about the code. Cite it as `file:line`, or hedge it
  out loud. Don't state something confidently when you haven't checked it.
- Run the cheapest check that could prove you wrong first: grep, read the function, run the one
  test.
- **Say what a check did not cover.** "I read `a.py` and `b.py`; I did not read the callers in `c/`"
  is a complete answer. "It's only used here" without the search behind it is not.
- Measure before claiming an improvement. Take all the numbers for one claim from one snapshot, and
  say when you took it.

## Spec before code

- For any change that alters behaviour, write a spec first. Use the minimum spec for one PR and the
  full spec for anything bigger. Then **stop and get explicit sign-off** before you write any
  implementation code.
- Every spec has a facts table cited to `file:line`, an out-of-scope list with reasons, and open
  questions, each with a recommended answer.
- Implement in phases. **Phase 0 changes no behaviour**: it only instruments, measures or reports.
  Each phase is green on its own. The next phase starts once the last is pushed to its PR, not
  once it merges; a pushed phase is in review, not built.

## Decisions

- When you need a decision, **ask it with the harness's question tool** so it arrives as a picker:
  `ask_user` in the Copilot CLI, `vscode/askQuestions` in VS Code, `AskUserQuestion` in Claude Code,
  `request_user_input` in Codex, the equivalent anywhere else ([why](docs/ask-with-the-question-tool.md)).
  Put related decisions in one call. Each option gets a plain label and a description of what it
  means and costs, with your recommendation first, marked **(Recommended)**. Prose is for a truly
  open question. With no question tool in this session, ask a short numbered list and accept the
  number or any clear wording. Never ask the person to type an exact phrase.
- A choice guarding something destructive or irreversible stays an explicit choice: its options say
  what happens, none is preselected, and no answer (a dismissed picker, silence, a run with no one
  to ask) means don't.
- A decision made in chat binds nothing until it is written down. Record it as an ADR
  (`python <kit root>/scripts/new-adr.py "…"`) in the same change.
- If a question is still open, label it open. Never fill it in with a default you invented.

## Tests and gates

- Tests prove the change *and* its refusals and failure paths, not only the happy path.
- Before every push, run every gate CI would run, on the working tree:
  `python <kit root>/scripts/run-local-gates.py`. The run that counts comes last, after the
  docs are updated, so one green run covers what you push. Fix anything red before pushing.
- **A skipped gate is not a passed gate.** Never claim a check passed if you didn't run it; write
  "not run" and say why.

## Pull requests

- Open the PR against the integration branch, or, for a phase stacked on an unmerged one, against
  that phase's branch. Its body carries evidence: the gate table, the tests
  added, and what was *not* checked (template: `<kit root>/templates/pr.md`).
- Never merge your own PR. A person merges it, and only when CI is green on the exact head commit
  they reviewed. Red or pending CI is not green.
- Use Conventional Commits: `type(scope): summary`. Every AI-assisted commit carries the AI
  co-author trailer (`commits.aiTrailer` in config). If none is configured, ask once and record the
  answer.
- A commit the Zethus agent authors is also signed: its signature (`commits.signature`, default
  `— Zethus`; `""` for none) goes on its own line before the trailer block, with a blank line on
  each side. Trailers stay last. The signature goes alongside the trailer, never instead of it.

## Docs stay in sync

- When code changes, fix the docs that describe it **in the same change**, without being asked.
  Stale documentation is a bug.
- Put detail in the doc next to the code (module README, docstring, spec). A root README or
  instructions file only routes: it says what exists and where to look.
- Markdown is the canonical source for documents. Other formats are rendered from it.

## When you are stuck

- After two failed attempts at the same thing, stop retrying. Run a **fresh-eyes investigation**:
  give it only the failing artifact and one line of intent. It returns a ranked list of places to
  look, never a diagnosis. An empty list is a valid answer.

## Shell

- Anything longer than one short command goes in a script file, then gets run. Don't chain it into
  a one-liner. Keep scratch scripts out of the working tree.

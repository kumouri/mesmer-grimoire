# Working agreement

These are standing rules for every change in this repository. They hold unless the task explicitly
says otherwise. The `zethus` agent enforces them stage by stage; the skills in `.github/skills/`
carry each procedure. Project-specific facts — gate commands, the integration branch, where ADRs
and specs live — are in `.github/zethus.config.json`. If a fact is missing, find it in the repo,
or ask. Never guess one.

## Start from a fresh base

- Branch from the **integration branch**: `branchModel.base` in config; otherwise `develop` if it
  exists; otherwise the default branch. Fetch first and use the fully-qualified ref
  (`origin/develop`), never a local copy that may be stale.
- One task, one branch. Run parallel tasks in separate worktrees, never in one shared checkout.
  If `branchModel.style` is `rebase`, the task lives on one long-lived branch kept rebased onto
  the integration branch instead; phases are commit series on it, not new branches.
- **Never work on a stale base.** Run `python .github/zethus/scripts/base-freshness.py` at the two
  points staleness costs something, and only those: **Stage 0 (Orient)**, before any work, and
  **immediately before a push or PR** (`pre-push-gates`). If it reports STALE (more than
  `branchModel.maxBehind` commits behind, default 0), rebase before doing anything else. Neither
  checkpoint is skippable; the stages between them don't re-run it. Diff against the merge-base it
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
  Each phase merges green on its own.

## Decisions

- When you need a decision, ask it as a short numbered list of options. Put your recommendation
  first, mark it **(Recommended)**, and give each option a one-line cost. Ask related decisions
  together, in one message.
- A decision made in chat binds nothing until it is written down. Record it as an ADR
  (`python .github/zethus/scripts/new-adr.py "…"`) in the same change.
- If a question is still open, label it open. Never fill it in with a default you invented.

## Tests and gates

- Tests prove the change *and* its refusals and failure paths, not only the happy path.
- Before every push, run every gate CI would run, on the working tree:
  `python .github/zethus/scripts/run-local-gates.py`. Fix anything red before pushing.
- **A skipped gate is not a passed gate.** Never claim a check passed if you didn't run it; write
  "not run" and say why.

## Pull requests

- Open the PR against the integration branch. Its body carries evidence: the gate table, the tests
  added, and what was *not* checked (template: `.github/zethus/templates/pr.md`).
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

---
name: pre-push-gates
description: Run every lint, build and test gate CI would run, locally on the working tree, before pushing — and report the result honestly, where a skipped gate is not a passed gate. Uses run-local-gates for a PASS/FAIL table to paste into the PR. Also holds the procedure for bringing a stale branch up to date yourself (rebase, resolve conflicts, re-run the gates), used at both freshness checkpoints. Use before any push, before opening or updating a PR, or when asked "is this ready".
---

# Pre-push gates

> `<kit root>` is the folder holding Zethus's `scripts/` and `templates/`: the path announced at session start, else two folders above this skill's folder.

CI's job is to show that a different machine agrees with yours. It shouldn't be where you first
find out a gate is red. Every red found in CI after a push costs a round trip that a local run
would have saved, and it tells the reviewer the author didn't check.

## Procedure

Run this stage last, after [docs-sync-check](../docs-sync-check/SKILL.md) and immediately before
the push, so one full run covers everything you push, docs and spec edits included. If you edit
anything after it goes green, run it again.

That binds the final run, not an earlier one. An early run may overlap docs work when the gates
don't read docs ([why](../../docs/independent-work-runs-concurrently.md)), but it can only find a
red. The run that clears the push starts after the last edit, on the exact tree that is pushed.

0. **Check the base is fresh:** `python <kit root>/scripts/base-freshness.py`.
   Gates run on a stale base check a tree that won't be the one that merges, and the PR describes
   a diff against a base that has moved. Exit 1 (STALE) means bring the branch up to date
   **yourself**, now, with [the procedure below](#bring-a-stale-branch-up-to-date), then go on to
   step 1. Don't stop for it, and don't hand the rebase to the person. Exit 3 means the fetch
   failed and freshness is unknown; say so, and don't treat the base as fresh. That one is a stop,
   because no rebase can fix it.

   **This is one of the change's two freshness checkpoints** — the other is Stage 0, when the
   branch is created or rebased. The stages in between don't check, because staleness costs
   nothing until a diff leaves the machine; that makes this run the one that catches a base which
   moved while you were building, so don't skip it on the grounds that Stage 0 was green.
1. **See what will run:** `python <kit root>/scripts/run-local-gates.py --list`.
   Gates come from `gates.steps` in `.github/zethus.config.json`, or else from the repo's build
   files (`package.json`, `Makefile`, `pyproject.toml`, Gradle, Maven, .NET, Go, Cargo). **Compare
   the list against the CI workflow.** If CI runs a gate the list doesn't have, add it to
   `gates.steps` now. A local run that skips a CI gate is a partial run.
2. **Run them all:** `python <kit root>/scripts/run-local-gates.py`.
   The script checks the **working tree on disk**, uncommitted changes included, and its header
   says so. Commit after it goes green, not before, so what you push is what you checked.
3. **Read the verdict line, not just the table:**

   | Exit | Verdict | What you do |
   |---|---|---|
   | 0 | `GREEN — every gate ran and passed` | Push. |
   | 1 | `RED — fix before pushing: …` | Fix it **in this phase**, with the smallest change that turns it green, even if the plan scheduled that gate's remediation for a later phase, and without asking first. Say in the phase's report that it was pulled forward and why. The failing gate's output tail is printed below the table. Don't push. |
   | 4 | `GREEN except gate(s) the approved plan lets stay red` | The person approved a `push-red` ruling for those gates in the spec's *Gate remediation* table. Push, and say in the PR which gates are red and where the ruling is. |
   | 3 | `GREEN on what ran, but N gate(s) NOT checked` | Install the missing toolchain and re-run. If that's genuinely impossible, push, and list those gates under *What was not checked* in the PR. |
   | 2 | No gates found / usage error | Configure `gates.steps`. No gates is not a green run. |

4. **Paste the table into the PR's *Evidence* section,** unedited.

A green verdict is progress, not a report to hand over and wait on. Next, in the same turn once the verdict lets you push: commit, push, and open the PR with
[zethus-pr-description](../zethus-pr-description/SKILL.md).

## Bring a stale branch up to date

Both freshness checkpoints use this: Stage 0 (Orient), before any work, and step 0 above, before
the push. A stale base is never built on and never pushed, and catching the branch up is your job,
not the person's ([why](../../docs/base-freshness-cadence.md#amendment-2026-11-10-zethus-rebases-a-stale-branch-itself)).
`base-freshness` has just fetched, so `origin/<base>` is current.

1. **Keep uncommitted work safe.** `git stash push --include-untracked`, and `git stash pop` after
   the rebase. A pop that conflicts is resolved like any other conflict (step 3).
2. **Rebase, by branch style:**

   | Style | What you run |
   |---|---|
   | `branch-per-change`, one branch | `git rebase origin/<base>`. When replaying the commits one by one is the messier route (many commits each conflicting on the same lines), cut a fresh branch instead: keep the old tip (`git branch <branch>-pre-rebase`), `git switch -C <branch> origin/<base>`, and move the work across with `git cherry-pick <old merge-base>..<branch>-pre-rebase`. Delete the kept tip once step 6 is green |
   | `branch-per-change`, a stack of phase branches | From the top of the stack, `git rebase --update-refs origin/<base>`, which moves every phase branch in one go |
   | `rebase` | `git rebase origin/<base>` on the long-lived branch, with `--update-refs` if other branches are stacked on it |

3. **Resolve conflicts yourself, keeping both sides' intent.** For each conflicted file, read what
   the base changed (`git log -p <old merge-base>..origin/<base> -- <file>`) and what this change
   does (its own commit, and the spec), then write the result that keeps both: the base's change
   and this change's behaviour. `git add` it and `git rebase --continue`. Most conflicts are of this
   kind: both sides edited nearby lines, or the base renamed or moved something the change touches.
4. **Stop only for a conflict you can't decide.** That is one where the base changed the very
   behaviour this change edits, in a way the two can't both keep, and neither the spec nor the diff
   says which wins. Then:
   - Leave the rebase clean and resumable, never half-applied. Stay paused at that commit with
     every other file in it resolved and staged and the undecided hunk's conflict markers intact,
     so `git rebase --continue` finishes it once the person rules. Commit nothing partly resolved,
     build nothing on the paused tree, and push nothing. If the tree has to be usable meanwhile,
     `git rebase --abort` returns the branch exactly to where it was.
   - Ask with the question tool: the file and the hunk (its line range), what the base did (commit
     id and subject), what this change does there, why the spec and the diff don't settle it, and
     your recommendation first. That is the stop-table row *a rebase conflict needs a decision*.
5. **Confirm:** re-run `python <kit root>/scripts/base-freshness.py`. It must report FRESH. This is
   the same checkpoint finishing, not a third one.
6. **Re-run what the rebase made stale.** If work was already written (always at the pre-push
   checkpoint, and at Stage 0 when resuming a branch with commits of its own), run
   `run-local-gates` again on the rebased tree: a green run from before the rebase cleared a tree
   that no longer exists. Take diffs, research notes and the PR body against the new merge-base.
7. **Push with a lease, and say it was rebased.** A branch that was already pushed has been
   rewritten: push it (each branch of a stack) with `git push --force-with-lease`, never a plain
   `--force`. The PR body says it was rebased, onto what, and which conflicts you resolved and how
   ([zethus-pr-description](../zethus-pr-description/SKILL.md)).

Then carry on where you were: at Stage 0, the next stage; here, step 1. A stale base stops the
turn in only two cases: exit 3 (the fetch failed, so there is nothing to rebase onto), and a
conflict you can't decide (step 4). The number of commits behind, a conflict you can resolve, and a
force-push of the branch you are working on are not stops.

## Rules

- **Every local gate is green before a phase pushes, whatever the phase plan says,** unless the
  signed-off spec records an approved `push-red` ruling for that gate
  ([why](../../docs/gate-remediation-in-the-plan.md)).
- **Never report a gate as passed if you didn't run it.** Write "not run", with the reason.
- **Don't weaken a gate to get green:** no skipped tests, loosened lint, or `--no-verify`. If a gate
  is wrong, fixing it is a separate decision for a person, recorded as an ADR.
- **A new gate starts report-only.** If you're adding a gate to the repo, clear the existing
  findings before making it blocking. A gate that is red on the day it lands gets switched off.
- **Pending CI is not green,** and neither is red CI that "looks unrelated". Neither one merges.
  Surface it and let a person decide.

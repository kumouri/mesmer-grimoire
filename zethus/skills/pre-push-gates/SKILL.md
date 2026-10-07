---
name: pre-push-gates
description: Run every lint, build and test gate CI would run, locally on the working tree, before pushing — and report the result honestly, where a skipped gate is not a passed gate. Uses run-local-gates for a PASS/FAIL table to paste into the PR. Use before any push, before opening or updating a PR, or when asked "is this ready".
---

# Pre-push gates

CI's job is to show that a different machine agrees with yours. It shouldn't be where you first
find out a gate is red. Every red found in CI after a push costs a round trip that a local run
would have saved, and it tells the reviewer the author didn't check.

## Procedure

0. **Check the base is fresh:** `python .github/zethus/scripts/base-freshness.py`.
   Gates run on a stale base check a tree that won't be the one that merges, and the PR describes
   a diff against a base that has moved. Exit 1 (STALE) means stop: rebase onto `origin/<base>`
   first, then come back here. Exit 3 means the fetch failed and freshness is unknown; say so, and
   don't treat the base as fresh.

   **This is one of the change's two freshness checkpoints** — the other is Stage 0, when the
   branch is created or rebased. The stages in between don't check, because staleness costs
   nothing until a diff leaves the machine; that makes this run the one that catches a base which
   moved while you were building, so don't skip it on the grounds that Stage 0 was green.
1. **See what will run:** `python .github/zethus/scripts/run-local-gates.py --list`.
   Gates come from `gates.steps` in `.github/zethus.config.json`, or else from the repo's build
   files (`package.json`, `Makefile`, `pyproject.toml`, Gradle, Maven, .NET, Go, Cargo). **Compare
   the list against the CI workflow.** If CI runs a gate the list doesn't have, add it to
   `gates.steps` now. A local run that skips a CI gate is a partial run.
2. **Run them all:** `python .github/zethus/scripts/run-local-gates.py`.
   The script checks the **working tree on disk**, uncommitted changes included, and its header
   says so. Commit after it goes green, not before, so what you push is what you checked.
3. **Read the verdict line, not just the table:**

   | Exit | Verdict | What you do |
   |---|---|---|
   | 0 | `GREEN — every gate ran and passed` | Push. |
   | 1 | `RED — fix before pushing: …` | Fix it. The failing gate's output tail is printed below the table. Don't push. |
   | 3 | `GREEN on what ran, but N gate(s) NOT checked` | Install the missing toolchain and re-run. If that's genuinely impossible, push, and list those gates under *What was not checked* in the PR. |
   | 2 | No gates found / usage error | Configure `gates.steps`. No gates is not a green run. |

4. **Paste the table into the PR's *Evidence* section,** unedited.

## Rules

- **Never report a gate as passed if you didn't run it.** Write "not run", with the reason.
- **Don't weaken a gate to get green:** no skipped tests, loosened lint, or `--no-verify`. If a gate
  is wrong, fixing it is a separate decision for a person, recorded as an ADR.
- **A new gate starts report-only.** If you're adding a gate to the repo, clear the existing
  findings before making it blocking. A gate that is red on the day it lands gets switched off.
- **Pending CI is not green,** and neither is red CI that "looks unrelated". Neither one merges.
  Surface it and let a person decide.

---
name: pr-description
description: Writes pull request descriptions. Use when creating a PR, writing a PR, or when the user asks to summarize changes for a pull request. Diffs against the repo's real integration branch and emits the headings the flag-or-fix skill files decisions under.
---

# PR description

The stage that hands the work to a human reviewer. A good description is the difference between a
reviewer reading the diff and a reviewer reading the diff *knowing what to look for*.

## Step 1: Diff against the right base

Determine the integration branch — do not assume `main`:

1. `branchModel.base` in `.claude/amphion.config.json`, if set.
2. Otherwise, `develop` if it exists (Git Flow), else the repo's default branch
   (`git remote show origin | sed -n 's/.*HEAD branch: //p'`).

Then run `git diff <base>...HEAD` (three dots — the merge-base diff, so you describe *your*
changes and not everything that landed on the base since you branched) and `git log --oneline
<base>..HEAD`.

## Step 2: Write the description

```markdown
## What
One sentence explaining what this PR does.

## Why
Brief context on why this change is needed.

## Changes
- Bullet points of specific changes made
- Group related changes together
- Mention any files deleted or renamed

## Verification
- The build/test commands you actually ran, and their real results.
- Say "not run" where you didn't run something. Never imply a gate passed that you didn't run.

## Not in this PR (intentional)
- Work deliberately deferred, and to what.

## Noticed but out of scope
- `file:line` — what you saw and why you left it. Omit the heading if empty.
```

Drop `Verification` only if the repo has no gates at all. Drop the last two headings when they're
empty — but they are where [`flag-or-fix`](../flag-or-fix/SKILL.md) files its deferred decisions,
so check whether anything was flagged before dropping them.

## Anti-patterns

- **Don't diff against `main` in a Git Flow repo.** You'll describe every commit since the last
  release instead of your branch.
- **Don't claim a passing build you didn't run.** "Not run" is a fine answer; a false green is not.
- **Don't restate the diff line by line.** The reviewer has the diff. Give them the shape and the
  judgment calls.

---
description: Promote local reflexion lesson(s) to the shared store — or export up to a team/enterprise tier
argument-hint: [lesson id(s), e.g. L-0009  |  L-0007 L-0009 --to team]
---

Promote lesson(s) **$ARGUMENTS** from the local tier to a shared, PR-reviewed store for review.

1. Run the engine with the Bash tool (reads `$MNEMOSYNE_REPO`, or pass `--repo`; use
   `python -m mnemosyne …` if needed):

   ```
   mnemosyne promote $ARGUMENTS
   ```

   - **Default** (`mnemosyne promote L-0009`): commits the lesson alone on a review branch for
     *this repo's* shared tier. The working tree and current branch are left alone.
   - **Multiple ids** are accepted: `mnemosyne promote L-0007 L-0009`.
   - **Broader tiers** — send lesson(s) UP to a configured team/enterprise store with `--to`:
     `mnemosyne promote L-0007 L-0009 --to team` (see `mnemosyne stores` for configured tiers).
   - **Manifest file** — promote many lessons across tiers at once:
     `mnemosyne promote --from-file promos.json` where the file is
     `[{"tier":"team","lessons":["L-0007"]},{"tier":"enterprise","lessons":["L-0008"]}]`.

2. **Relay the `PROMOTED:` / `EXPORTED:` line and the push/PR step it prints verbatim.** The local
   copy stays, marked `proposed`, until the PR merges. Merging the PR is the approval, and a human
   reviewer does it before the lesson becomes team-wide truth (agent proposes, human disposes).
   Exports open the PR in the *destination store's* repo. Either way the local original retires
   automatically on the next `sync` once that PR is merged.
3. If the user asks, run the printed push/PR command to open the review PR — but do not merge it
   yourself; that's the reviewer's call.

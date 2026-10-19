---
name: docs-sync-check
description: Before the pre-push gates and the PR, find the documentation that describes the code this change touched and confirm each is still true — updating it in place in the same change — and check every Markdown pointer still resolves. Uses docs-pointer-check with the docSync map. Use before opening a PR, after renaming or moving files, or when asked whether the docs are up to date.
---

# Docs sync check

Stale documentation is a bug, and it's the one reviewers are least likely to catch: the diff shows
the code that changed, not the README that now describes it wrongly. So fix the docs **in the same
change**, without being asked. Change only the docs that describe code this diff actually touched.

## Procedure

1. **Check pointers, and list docs whose code changed:**

   ```bash
   python .github/zethus/scripts/docs-pointer-check.py --sync-base origin/<base>
   ```

   - Broken pointers (exit 1) must be fixed. A relative link to a moved or renamed file breaks, and
     a link whose case differs breaks on Linux CI and on the web even if it works on your laptop.
   - `REVIEW <doc>` lines come from `docSync.map` in config: each lists a doc whose described
     paths changed while the doc didn't. This is report-only. It tells you to read the doc; it
     doesn't prove the doc is wrong.
2. **Find the docs the map doesn't know about.** Search the docs for the names this diff changed:
   renamed functions, flags, config keys, commands, file paths. `git grep -n "<old name>" -- "*.md"`
   is usually enough.
3. **For each doc found, read the passage and decide:**
   - **Still true:** leave it. Record it as confirmed.
   - **Now false:** rewrite that passage **in place**. Don't append a "Note: as of …" line after
     wrong text. Fix the text.
   - **Needs a new section:** the detail goes in the doc next to the code (module README, spec,
     docstring). A root README or instructions file gets at most a one-line pointer to it.
4. **Specs.** If this PR builds a phase, update the spec's status and *As built* list (see
   [implement-phase](../implement-phase/SKILL.md)).
5. **Report** under the PR's *Docs updated* heading: each doc, and whether it was updated or
   confirmed. "No doc describes this code" is a valid answer once you've done step 2.

Next: [pre-push-gates](../pre-push-gates/SKILL.md). This stage runs before the gates, not after
them, so the one full gate run covers these edits too and doesn't have to be repeated.

## Rules

- **Don't touch docs about code this diff didn't change.** Wide "tidy the docs" edits make every PR
  conflict with every other PR. If you see an unrelated stale doc, note it under *Noticed but out of
  scope*.
- **Don't grow router files.** If a root doc needs more than a line, the content belongs in a leaf.
- **No hand-maintained counts.** Don't fix a stale number by typing the new one into prose. Say
  how to measure it instead.

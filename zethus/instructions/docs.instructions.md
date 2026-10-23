---
name: Documentation rules
description: Rules for writing or editing Markdown documentation, specs and ADRs.
applyTo: "**/*.md"
---

# Documentation rules

- **Markdown is the canonical source.** PDF, Word, and wiki pages are rendered from the `.md` file;
  never edit them as the source. To paste into a wiki or ticket tracker, paste the Markdown.
- **Router or leaf — decide which this file is.** A root README or instructions file is a router:
  one line per item, saying what exists and where to look. The explanation belongs in the leaf
  beside the code. If a router section grows past a paragraph, move the detail into a leaf and
  leave a pointer behind.
- **Every pointer must resolve.** Relative links must name files that exist, with exact case. Check
  with `python .github/zethus/scripts/docs-pointer-check.py`.
- **No hand-maintained counts.** Don't type test totals, file counts or line counts into prose;
  they are wrong by the next commit. Say how to measure them instead.
- **Spec status is one of** `DRAFT`, `SIGNED-OFF`, `PARTIAL(merged: …; in review: …)`, `BUILT`, or
  `MEMO`. A phase pushed to an open PR is `in review`, never `merged` or `BUILT`. A spec is not
  `BUILT` until the PR that builds its last phase has merged.
- **Open questions are edited in place, never deleted.** When one is answered, mark it
  `DECIDED (date, ADR id)` or `DEFERRED (to what)`.
- **ADRs are append-only in spirit.** To change a decision, write a new ADR that supersedes the old
  one, and fill in both records' `Supersedes` / `Superseded by` fields. Don't rewrite history.

## What

One sentence: what this PR does.

## Why

The problem, in two or three lines. Link the spec and the ticket.

- **Spec:** path or link, and the phase this PR implements
- **Decisions:** ADR ids this PR relies on or creates

## Changes

- Grouped by concern, not file by file. Name anything deleted or renamed.
- Say which phase of the spec this is. If this is Phase 0, confirm it changes no behaviour.

## Evidence

The gates you ran on this exact tree, and what they said. Paste the `run-local-gates` table as-is.

| Gate | Result | Time | Command | Note |
|---|---|---|---|---|
| … | PASS | … | … | |

- **Tests added or changed:** what each one proves, including failure and refusal paths.
- **Measured:** any before/after number, with its source and when it was taken.

## What was not checked

Gates that were skipped or manual, environments not exercised, and anything verified only by
reading. Write "Nothing — every gate ran" only if that is true.

## Not in this PR (intentional)

- Work deliberately deferred, and where it goes (a later phase, a ticket).

## Noticed but out of scope

- `file:line` — what you saw and why you left it.

## Decisions needed from the reviewer

1. **…?** Options: A / B. **Recommended: A**, because …

## Docs updated

The docs that describe the changed code, and whether each was updated in this PR.

## AI assistance

Name the AI tool that helped, and confirm that the commits carry the co-author trailer this repo
requires, signed `— Zethus` (or the configured `commits.signature`) just before it.

<!-- Delete any heading that is empty, except "Evidence" and "What was not checked". -->

---
name: research-existing-code
description: Research how existing code actually behaves before specifying or changing it. Produces a facts table where every claim is cited to file:line, records the search behind each negative claim, and states what the research did not cover. Use before writing a spec, before estimating, when asked "how does X work" or "what calls Y", or when inheriting someone else's claims about a codebase.
---

# Research existing code

The goal is a set of facts about today's code, each tied to where it is, that a spec can build on
and a reviewer can check in seconds. What this guards against is a claim that goes further than
the look behind it: "it's only called from here" when only one directory was searched.

## Procedure

1. **Write down the question in one line.** "How are failed webhook deliveries retried today?" If
   you can't state it, you aren't ready to research.
2. **Run the cheapest check that could prove your first guess wrong,** before any broad reading.
   That might be a `git grep` for the symbol, reading the one function, or running the one test.
   Widen only if that check is inconclusive.
3. **Read the code, not the docs about it.** Use docs to find the code, then verify against the
   code. If a doc and the code disagree, the code wins, and the disagreement becomes a fact in its
   own right (the doc needs fixing).
4. **Record each fact as you confirm it,** with its location pinned to a commit:

   | # | Fact | Where (`file:line` @ commit) | How verified |
   |---|---|---|---|
   | F1 | Retries use a fixed 30 s delay | `src/webhooks/retry.py:48` @ `abc1234` | read `schedule_retry()` |
   | F2 | Nothing outside `src/webhooks/` calls `schedule_retry` | — | `git grep -n "schedule_retry("` → 4 hits, all in `src/webhooks/` |

   Record the commit once, at the top, if every fact comes from the same one:
   `git rev-parse --short HEAD`. The base was confirmed fresh at Stage 0, so don't re-run the
   freshness gate here; research on the base it confirmed. On a long-lived branch
   (`branchModel.style` `rebase`), `HEAD` ids change at every rebase, so cite code on the base at
   the **merge-base**, and cite `HEAD` only for code this branch changed. If you don't have that
   merge-base to hand, `python .github/zethus/scripts/base-freshness.py --merge-base-only` prints
   it and cannot stop this stage.
5. **Back every negative claim with the search that proved it.** "Nothing else calls X" is only
   true to the extent of the search, so record the command and its result.
6. **Re-check inherited claims before you rely on them.** A claim from a ticket, an older spec, or
   a colleague's summary is a lead, not a fact. Re-run it, and mark it `(verified)` or
   `(not re-checked)`.
7. **Measure once.** If you report numbers (counts, sizes, timings), take them all from one
   snapshot and write down when. If a number changes while you're working, report that it moved.
8. **Say what you did not cover.** List the directories, services, environments, generated code and
   runtime data you didn't examine. This section is required. An empty one means you claim to have
   looked at everything.

## Output

- The facts table.
- **Not covered:** the list from step 8.
- **Contradictions:** anything you found that contradicts the ask or an existing doc. A spec puts
  these under "Assumptions checked".
- **Open questions** that the code can't answer and a person has to.

## Anti-patterns

- **Describing the code from memory,** or from what a function's name suggests. Open the file.
- **A citation that doesn't support the claim.** If `file:line` only shows the call and not the
  behaviour you describe, cite the line that shows the behaviour.
- **Hedging everything.** "It might possibly be…" is not research. Check it and state it, or say
  "not verified" once and move on.
- **Reading everything.** Breadth isn't rigor. Answer the question, and name what you didn't read.

## Next

Facts in hand → [write-spec-minimum](../write-spec-minimum/SKILL.md) or
[write-spec-full](../write-spec-full/SKILL.md).

# {{title}}

**Status:** {{status}} · **Owner:** {{owner}} · **Date:** {{date}} · **Related:** tickets, ADRs, prior specs

> Status is one of `DRAFT` → `SIGNED-OFF` → `PARTIAL(merged: …; in review: …)` → `BUILT`, or
> `MEMO` for a write-up that proposes nothing to build. A phase pushed to an open PR is
> `in review`, not merged; the spec is `BUILT` only once its last phase's PR merges. Delete this
> note.

## The ask

Quote the request verbatim — the ticket text, the message, the meeting note — with its date and
source. Then say which parts of it this spec answers and which it does not. Quoting it exactly is
what makes later scope drift visible.

> "…the requester's exact words…" — source, date

- **Answers:** …
- **Does not answer:** … (and where that goes instead)

## The problem, measured

The evidence that this matters: an incident, a metric, a log query, ticket history. Take every
number from **one snapshot** and give its timestamp and source. If a number moved while you were
measuring, say it moved; don't average it away. If the problem can't be measured yet, say so —
and let Phase 0 be what measures it.

| Measure | Value | Source (query, dashboard, file) | Taken at |
|---|---|---|---|
| … | … | … | … |

## What is true today

Every claim about the current code, pinned to where it lives. A claim without a `Where` is a
memory, not a fact. For a negative claim ("nothing else calls this"), record the search that
proved it.

| # | Fact | Where (`file:line` @ commit) | How verified |
|---|---|---|---|
| F1 | … | `path/to/file.ext:42` @ `abc1234` | read the function |
| F2 | Nothing outside `module/` calls `thing()` | — | `git grep -n "thing("` → 3 hits, all in `module/` |

**What this research did not cover:** name the files, services, environments or data you did
*not* read, so nobody mistakes a partial look for a complete one.

## Assumptions checked

Where reading the code changed the premise of the ask. Number each one and point at the section it
changed. If the reading confirmed everything, write "None found" — an empty section is a result.

1. The ask assumed … ; the code shows … (F2). This changes **Design**.

## Design

### Approach

What will be built, in prose a reviewer can argue with. Cite facts by number (F1, F2).

### Options considered

| Option | What it means | What it costs | |
|---|---|---|---|
| A — … | … | … | **Recommended** — why |
| B — … | … | … | |

### What it costs

Runtime, build time, money, complexity, on-call load. Say which figures are measured and which are
estimated.

### What it does not stop

The residual risk after this ships, stated rather than implied.

## Phases

Smallest useful step first. **Phase 0 changes no behaviour**: it records, measures, logs or
reports, so it is safe to ship alone, and its data sizes the phases after it. Each phase is green
on its own, and the next starts once it is pushed to its PR, not once it merges.

| Phase | What | Behaviour change | Gated on | Verified by |
|---|---|---|---|---|
| 0 | Instrument / report only | **None** | Sign-off of this spec | … |
| 1 | … | … | Phase 0 data (default window: one week) or a named decision | … |

When a phase is pushed, mark it `in review (PR #n)` here, and `merged (PR #n)` once its PR merges.
Add an **As built** list: every deviation from this spec, each with its reason.

## Test plan

What proves each phase works, including the refusals and failure paths — not just the happy path.

| Phase | Test | Level (unit / integration / e2e / manual) | Proves |
|---|---|---|---|
| 0 | … | unit | … |

**Mutation check:** for the key test, what change to the code makes it fail? If none does, the test
proves nothing.

## Rollout and rollback

Flags, migrations, ordering, who needs to know. For each phase: how to undo it and how long that
takes.

## Before and after

| Headline metric | Baseline (n, window) | Target | After (n, window) |
|---|---|---|---|
| … | … | … | filled in after the build |

"Not measurable at this sample size" is an honest result when the change is smaller than normal
day-to-day variation.

## Out of scope

What this deliberately does not build, each with the reason, so none of it is re-proposed later as
an oversight.

- **…** — because …

## Open questions

Numbered. Each gives the options, a **recommended** answer, and whose call it is. When answered,
edit it in place to `DECIDED (date, ADR link)` or `DEFERRED (to what)`. Never delete a question.

1. **…?** Options: A / B. **Recommended: A**, because … · Decides: …

## Decisions

The ADRs this spec created or depends on, by id.

- …

## Docs updated in this change

The READMEs, guides, instruction files and comments that describe the code this changes, and
whether each was updated. "None describe it" is a valid answer if you checked.

## Self-check

Does the core recommendation reduce to "be more careful"? If yes, it is a wish, not a design:
replace it with something that runs, blocks or measures.

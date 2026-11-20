# {{title}}

**Status:** {{status}} · **Owner:** {{owner}} · **Date:** {{date}} · **Related:** tickets, ADRs

**Requested by:** {{requester}} · **Signed off:** {{signedOff}} · **Written by:** {{writtenBy}}

> The minimum spec: for one PR, a short fact table, and at most one open decision. Its headings are
> a strict subset of the full spec's, so promoting it later only adds sections. *Owner*,
> *Requested by* and *Signed off* name people as they write their names (by default the person
> Zethus works for, from `identity.py`), never a placeholder; *Signed off* reads `who, date` once
> a person approves it. The agent is only ever *Written by*. Delete this note.

## The ask

> "…the exact words of the ask…" — who asked, as they write their name; source; date

- **Answers:** …
- **Does not answer:** …

## What is true today

| # | Fact | Where (`file:line` @ commit) | How verified |
|---|---|---|---|
| F1 | … | `path/to/file.ext:42` @ `abc1234` | … |

**What this research did not cover:** …

## Design

What will be built, citing facts by number. If there were real alternatives, name the one you
recommend and why in one line each.

## Phases

> Phase 0 changes no behaviour. Every phase logs what it builds: name in *What* the run log it adds
> (starting config, decisions, state changes, full errors), in the commit that creates the code.
> Delete this note.

| Phase | What | Behaviour change | Verified by |
|---|---|---|---|
| 0 | Instrument / log / report only | **None** | … |
| 1 | … (and its run log) | … | … |

## Gate remediation

> Does any phase remediate something a local gate checks (SonarQube findings, lint, types, a
> coverage floor)? Every local gate must be green before a phase pushes, so a phase 0 that can't
> pass a gate can't push. Write `None — no phase remediates anything a local gate checks.` if that
> is so. If a phase does, **name the gate here and ask for one ruling per gate** at sign-off:
> `push-red` (push with the gate red because its remediation is scheduled), `limited-phase-0`
> (phase 0 makes the gate pass with the smallest remediation that does), `reorder` (a phase order
> in which the gate passes from phase 0 on), or `other: <what>` (an equivalent; it waives nothing).
> Leave `Approved` as `PENDING` until the person answers, then `yes — who, date`. Delete this note.

| Gate | Remediation phase | Ruling | Approved |
|---|---|---|---|
| … | Phase N | … | PENDING |

## Test plan

| Test | Level | Proves |
|---|---|---|
| … | unit | the change works |
| … | unit | the refusal / failure path |

## Out of scope

- **…** — because …

## Open questions

1. **…?** Options: A / B. **Recommended: A**, because … · Decides: …

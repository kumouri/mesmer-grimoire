---
name: reflexion-memory
description: >
  Recall durable lessons from past work and reflect real failures into new ones, using the
  Mnemosyne git-backed reflexion memory. Use at the START of a task to recall prior lessons
  (before planning or implementing), and AFTER a task when a real mistake, a settled decision,
  or a reusable convention emerges. Triggers include "recall lessons", "what have we learned",
  "reflect on this", "remember this decision", "save a lesson", "capture a convention", "apply
  our past mistakes", "promote a lesson", or any moment worth not repeating a known mistake.
  Not for general note-taking — only durable, reusable lessons.
---

# Reflexion memory (Mnemosyne)

Mnemosyne is a git-backed **reflexion memory**: the agent recalls durable *lessons* into new
work and reflects feedback into new lessons so the same miss never happens twice
([Reflexion, Shinn et al. 2023](https://arxiv.org/abs/2303.11366)). This skill is how you use it.

## The loop

1. **Recall** relevant lessons *before* you plan or implement, and **apply** them.
2. **Announce** which lessons you applied (transparency — never use memory behind the user's back).
3. **Reflect / capture** when a real, reusable lesson emerges from the work.
4. **Promote** a good local lesson so the team gets it (a human reviews the PR).

## Setup

The engine is the `mnemosyne` CLI (or `python -m mnemosyne`). It is not on PyPI yet; install it with
`pip install "git+https://github.com/kumouri/mesmer-grimoire#subdirectory=mnemosyne"`.
It reads/writes a **memory repo** (a directory with a `memory/` folder). Point at it with the
`MNEMOSYNE_REPO` environment variable, or run commands with `--repo <path>`. Create one with
`mnemosyne --repo <path> init --example software-eng` (the `--example` seeds a config with useful
recall axes; omit it for the minimal default). If the plugin's hooks are active, recall happens
automatically on each prompt and the shared memory is pulled on session start.

## Recall (start of a task)

```
mnemosyne recall --query "<what you're about to do>" --stage <stage>
mnemosyne recall --from-brief <path-or-->            # extract context from a brief/plan/ticket
mnemosyne recall --tags idempotency,replay           # match tags directly (strongest signal)
```

Read the digest, **apply** the lessons (as defaults, checks, or questions), and tell the user
plainly: *"Applied reflexion lessons L-0001, L-0006 — pinning idempotency and routing the
cross-service write."* Low-confidence lessons are flagged — confirm those before relying on them.

## Reflect (a real failure) and capture (a decision/convention)

- **`reflect`** — a mistake or gap surfaced by feedback (a review catch, a broken assumption, a
  landmine hit during implementation). It needs `--reflection-of "<what went wrong>"`.
- **`capture`** — a reusable decision or convention (a default, a naming rule, a settled choice).

```
mnemosyne reflect --title "Pin idempotency for every new POST endpoint" \
  --lesson "Decide the idempotency contract (key, dedup window, replay) up front and add it as an acceptance criterion." \
  --reflection-of "A new POST double-posted on replay because idempotency was never specified." \
  --tags idempotency,replay --stage plan --confidence high

mnemosyne capture --category convention \
  --title "Page list endpoints at 50 by default" \
  --lesson "Our standard pagination default is 50; propose it and confirm." \
  --tags pagination --confidence medium
```

New lessons land in the **local** tier (per-developer). Tell the user a lesson was saved and how
to promote it. Then **announce** the saved id.

### Write a good lesson

- **Title**: short and imperative ("Pin idempotency for every new POST endpoint").
- **Lesson**: what to *do* next time — not just what went wrong.
- **Tags**: the primary recall signal; use concrete, reusable keywords.
- **Confidence**: `high` only when you're sure; `low` gets surfaced flagged-for-confirmation.

## What NOT to reflect (hygiene)

The engine **refuses** missing-deliverable / transient failures ("the build produced no output",
"the test timed out", "a re-run fixed it") — those are process retries, not lessons. It also
**reinforces** a near-duplicate instead of adding noise. Don't fight these guards with `--force`
unless the lesson really is new and durable. A genuine *domain* failure (a trigger that didn't
fire, an idempotency gap that double-posted) saves normally.

## Promote (share with the team) / Export (broader tiers)

```
mnemosyne promote L-0009                     # local → this repo's shared tier
mnemosyne promote L-0007 L-0009 --to team    # export up to a configured team/enterprise store
mnemosyne promote --from-file promos.json    # batch across tiers via a manifest
mnemosyne stores                             # list configured shared stores + whether each is fetched
```

Promotion commits the lesson alone on a review branch, keeps the local copy marked `proposed`, and
prints the push/PR step. Merging the PR is the approval, and a human reviewer does it before the
lesson becomes team-wide truth. **Stores** are additional git repos (e.g. `team`, `enterprise`)
declared in `mnemosyne.config.json`; `recall` federates over the ones `sync` has fetched (it never
touches the network), `--to <tier>` exports up to one (opening the PR in *that* repo), and the
local original retires automatically on the next `sync` once its PR merges. Relay the
promotion/export line.

## Curate on demand

```
mnemosyne hygiene            # health report: duplicates, never-recalled, cap headroom
mnemosyne prune              # dry-run: retire aged / over-cap low-value lessons (--apply to commit)
mnemosyne validate           # schema + spine consistency
```

## Transparency contract

Every command prints a quotable line (`RECALL: …`, `SAVED: …`, `PROMOTED: …`). **Relay these
verbatim.** Memory is never applied silently and never shared unreviewed — the user can veto any
recalled lesson and gates every promoted one.

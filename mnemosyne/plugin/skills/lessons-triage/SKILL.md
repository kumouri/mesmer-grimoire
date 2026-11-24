---
name: lessons-triage
description: >
  Triage the Mnemosyne lessons-capture spool at a checkpoint: auto-store the obvious lessons an
  ADR or a red-then-green gate produced, and ask about the rest, in one batched question set. Use
  when a Stop hook says "capture candidate(s) await triage", when a session-start digest reports a
  pending count, or when `mnemosyne candidate triage` lists untriaged candidates. Not for recalling
  or writing lessons from scratch — that is the reflexion-memory skill.
---

# Lessons triage (Mnemosyne, Phase 1)

Zethus's scripts and the capture hooks detect *signals* and append *candidates* to a local spool;
they never store or ask. This skill is the one place judgement happens: you run the rule table
(docs/lessons-capture-spec.md §4.3) over the spool at a checkpoint, **auto-store** the two obvious
signals to your local tier, and **ask** about everything else. Everything stays in the **local
tier** — sharing always asks and is a separate `promote` (spec Q7).

## When it runs

- The **Stop** hook blocks once with "N capture candidate(s) await triage" (Claude Code, active
  mode). That is your cue.
- A **session-start** digest, or `mnemosyne candidate triage`, reports a pending count.

## 1. Get the plan

```
mnemosyne candidate triage          # the untriaged candidates for this project, auto vs ask
```

Each row is a candidate with pointers only (an ADR id, a gate name, a matched phrase) — never tool
output or transcript text. The plan marks each **AUTO** or **ASK**.

## 2. Auto-store the AUTO candidates (S1, S2)

These are the two deterministic, script-emitted signals:

- **S1 — an ADR was recorded** (`decision`). Open the ADR, and write a one-line lesson in your own
  words: the decision and when it applies. Never paste the ADR's text.
- **S2 — a gate went red then green in this phase** (`mistake`). Write the one-line *fix* that made
  it pass — what to do next time, not the error text. If you can't name a durable fix (it was a
  flake or a re-run), don't auto-store it: `mnemosyne candidate resolve <id> skipped`.

Store each with its candidate id so the spool clears:

```
mnemosyne capture --category decision --captured-by hook:S1 --candidate <id> \
  --title "<imperative title>" --lesson "<what to do next time>"

mnemosyne reflect --category mistake --captured-by hook:S2 --candidate <id> \
  --title "<imperative title>" --lesson "<the fix>" --reflection-of "<what went red>"
```

Relay each `SAVED:` line. Auto-store lands in **local** at **medium** confidence, undoable in one
command: `mnemosyne retire <lesson-id> --reason "<why>"`.

**The engine enforces the limits — you don't have to.** A `--captured-by` capture is **refused**
(and nothing is stored) if it is `security`-category, if it would supersede a lesson, if it targets
any tier but local, or if its text carries a credential shape. When the engine refuses one, don't
fight it: route that candidate to **ask** instead (step 3). You still judge the two no pattern can:
if the lesson would be **a judgement about a person**, or would have to **quote** tool output, the
web, an issue or the transcript — **ask**, don't auto-store.

## 3. Ask about the ASK candidates — one batched question set

Gather every ASK candidate into **one** question set at this checkpoint (never mid-step). On Claude
Code, use the question tool; each candidate is one option set: *save as is*, *save edited*, *skip*,
*never ask about this kind*. For a candidate the user accepts, capture it (add `--candidate <id>`);
for a skip, record the negative so it isn't asked again:

```
mnemosyne candidate resolve <id> skipped --note "<why not worth a lesson>"
```

## 4. Done

The spool is empty for this project when every candidate is stored, asked or skipped — then the
Stop hook won't block again. Confirm with `mnemosyne candidate triage` (0 untriaged) or
`mnemosyne doctor`.

## What this never does

- Never stores beyond the local tier, never opens a PR (Q7). Sharing is a separate, reviewed
  `promote` — see the reflexion-memory skill.
- Never writes into `AGENTS.md`, `CLAUDE.md` or Copilot instructions; those are routers.
- Never pastes tool output, web pages, issue bodies or transcript text into a lesson. You write the
  lesson; the candidate only points at where the signal came from.

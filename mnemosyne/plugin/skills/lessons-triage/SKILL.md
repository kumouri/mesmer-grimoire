---
name: lessons-triage
description: >
  Triage the Mnemosyne lessons-capture spool at a checkpoint: auto-store the obvious lessons an
  ADR or a red-then-green gate produced, and ask about the rest in one batched question set. Use
  when a Stop hook says "capture candidate(s) await triage", when a session-start digest reports a
  pending count, or when `mnemosyne candidate triage` lists untriaged candidates. Not for recalling
  or writing lessons from scratch — that is the reflexion-memory skill.
---

# Lessons triage (Mnemosyne, Phases 1 and 2)

Zethus's scripts and the capture hooks detect *signals* and append *candidates* to a local spool;
they never store or ask. This skill is the one place judgement happens: you run the rule table
(docs/lessons-capture-spec.md §4.3) over the spool at a checkpoint, **auto-store** the two obvious
signals to your local tier, and **ask** about the rest in **one** question set. Everything stays in
the **local tier** — sharing always asks and is a separate `promote` (spec Q7).

## When it runs

- The **Stop** hook blocks once with "N capture candidate(s) await triage" (Claude Code `Stop`,
  Copilot CLI `agentStop`; active mode). That is your cue.
- A **session-start** digest, or `mnemosyne candidate triage`, reports a pending count. This is the
  checkpoint on a host whose stop hook has not been seen to block (VS Code, the Copilot cloud agent).

## 1. Get the plan

```
mnemosyne candidate triage          # the untriaged candidates for this project, auto vs ask
```

Each row is a candidate with pointers only (an ADR id, a gate name, a path, a matched phrase) —
never tool output or transcript text. The plan marks each **AUTO** or **ASK**, and ends with what it
left out and why. **A signal still in shadow never appears here**: S4, S5, S6 and S12 are recorded
but not asked until their own precision has been measured (`mnemosyne doctor` shows where each
stands). Don't go looking for them in the spool and ask about them anyway.

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

`mnemosyne candidate triage --format json` has a `questions` list: one question per ASK candidate,
each with the same four options. Put **all** of them in **one** question set at this checkpoint,
never one at a time and never mid-step.

- **Claude Code:** the question tool, one question per candidate, with the options *save it as
  proposed*, *save it edited*, *skip it*, *never ask about this kind*. Recommend *save* only where
  you can already write a durable, general lesson; otherwise recommend *skip*.
- **Copilot (CLI, VS Code) and anything with no question tool:** print
  `mnemosyne candidate triage --numbered` and ask the person to answer with `question.option`
  (for example `1.1 2.3`) or any clear wording. Never require an exact string.

Then act on each answer. For *save* and *save edited*, write the lesson yourself (a distilled
sentence, never pasted text) and file it under the question's `category`:

```
mnemosyne capture --category <category> --candidate <id> --title "<imperative title>" --lesson "<...>"
```

That is an ordinary capture, not a `hook:` one: the person said yes, so it is theirs. For *skip*
and *never*:

```
mnemosyne candidate resolve <id> skipped --note "<why not worth a lesson>"   # same thing isn't asked again
mnemosyne candidate resolve <id> never                                      # mutes the whole kind
```

What each kind of question is:

| Signal | The question is about | Category |
| --- | --- | --- |
| S8 | A fresh-eyes investigation was needed (stuck twice): what should be remembered next time? | process |
| S9–S11 | A watched file was written (a spec, a friction-log entry, the phase ledger): is there a decision or lesson in it? The path is all you have: open the file | decision, or process for a friction entry |
| S4, S5, S6 | Only if the project opted in: the person's own words, or a command that failed then passed | convention, convention, mistake |
| S12 | Lessons recalled this session were then corrected: should a new lesson replace one? | convention, with `--supersede <id>` |

For **S12**, if the person agrees, capture the replacement with `--supersede <old-id>`. The engine
refuses a hook-made supersede, so this must be a plain capture the person approved, never
`--captured-by`.

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
- Never asks about a signal that is still in shadow, a kind the person muted, or a thing they
  already skipped.

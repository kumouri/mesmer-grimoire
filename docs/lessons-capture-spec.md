# Lessons capture and harness convergence: verification and spec (2026-10-29)

**Status:** DRAFT. This is a verification report and a spec, nothing more: no feature is built.
**Seven of the eight questions are ruled** (2026-10-29), every one as recommended: Zethus and
Amphion stay two kits on a shared core (Q1); auto-store never stores the six excluded classes (Q2)
and never writes beyond the local tier (Q7); a standard is three occurrences across two or more
specs or tickets within 180 days (Q4, Q5); merging a review PR approves its lesson (Q6); and the
engine bugs are fixed first, as Phase 0 (Q8). Phase 0 can start. **Q3, the federation target, is
still open.** Nothing before Phase 3 shares a lesson, so it blocks only Phase 3. See
[Rulings](#rulings-2026-10-29).

**The ask** (Ceryce, Telegram, 2026-10-29 21:33 CT, verbatim):

> We can actually probably start on the Mesmer-Grimoire update now. The main thing is I want to make
> sure Mnemosyne works and that it's integrated first-class into Zethus and Amphion. Also possibly
> fuse Zethus and Amphion since most harnesses seem to be converging on certain features that—I
> believe—are designed to make it so agents, skills, etc., designed for one harness work with most
> other harnesses, too. But the main thing is to incorporate an identification of errors, lessons,
> decisions, etc., that should be recorded and remembered by the agent AND possibly shared with one
> of the federated tiers. Zethus should automatically store obvious lessons and such and it should
> ask on things that aren't as obvious or things where the answer has been the same multiple times
> in different situations and stuff (i.e. identifying patterns that are standards in the agents
> current environment).

This builds on the [stage 1 assessment](stage1-assessment-2026-09-30.md), whose rulings (D1–D10)
still stand. Nothing here reopens them.

## Summary

- **Mnemosyne mostly works, and its test suite is green, but three defects block wiring it into
  anything.** The CLI, library, Claude Code hook bridge, hygiene guards, federation and
  retire-on-merge all behave as documented. Broken: the **MCP server hangs on every tool call on
  Windows**; **lesson ids are reused across branches**, so a merged promotion is silently shadowed;
  and **a promotion PR sweeps in any earlier uncommitted promotion**. Also missing: there is no
  engine command that approves a proposed lesson, so the export loop only closes if a reviewer
  hand-edits the JSONL, which the design forbids. Details and output in [§1](#1-does-mnemosyne-work-today).
- **Zethus and Amphion do not use Mnemosyne at all.** No file in either kit mentions it
  ([§2](#2-the-integration-as-it-stands)).
- **The harnesses really have converged, but not on everything this needs.** `SKILL.md` skills,
  `AGENTS.md`, MCP and the Claude-format plugin and hook files now work across most hosts. Memory
  has **no** standard anywhere, and hooks are only partly shared. In particular, GitHub Copilot
  **drops the output of `userPromptSubmitted` hooks**, so per-prompt recall injection, the way the
  Mnemosyne plugin works today, cannot work there ([§3](#3-harness-convergence)).
- **The spec ([§4](#4-spec-capturing-errors-lessons-decisions-and-standards)) captures through two
  deterministic channels and leaves judgement to the agent at fixed checkpoints.** Zethus's own
  scripts are one channel: their output reaches the agent on every host and every surface,
  including the Copilot cloud agent. Lifecycle hooks are the other, for signals no script sees.
  Both append *candidates* to a local spool. A rule table then sorts each candidate into **store
  automatically** (local tier only), **ask**, or **ask to promote a recurring answer into a
  standard**.
- **The engine is fixed first** ([§5](#5-phases), Q8 ruled): Phase 0 fixes B1–B6 and runs the
  candidate spool in shadow mode. **Phase 1 is then small:** auto-store the two most obvious
  signals in Zethus (recorded ADRs, and a gate that went red then green), with an end-of-turn
  triage hook on Claude Code.

---

## 1. Does Mnemosyne work today?

### 1.1 How this was checked

Every check ran on 2026-10-29, on Windows 10 with Python 3.14, against branch
`docs/lessons-and-harness-convergence-spec` cut from `origin/develop` at `72d6d4e`. Mnemosyne is
not installed on the author's machine, so it was installed into a throwaway venv with
`pip install ./mnemosyne`, which also tests the documented install route. Every store was a scratch
directory with a local bare git remote. The repo's demo store (`mnemosyne/memory/`) was not
touched. Absolute scratch paths in the output below are shortened to `<scratch>`.

**Nothing was fixed.** No test path needed fixing.

### 1.2 Verdict

| Area | Verdict | Evidence |
| --- | --- | --- |
| Test suite (`python -m unittest discover -s tests -t .`) | **Works** | 285 tests OK in 41.7 s, which includes `tests/test_mnemosyne.py` |
| `mnemosyne selftest` (installed package) | **Works** | `SELFTEST: ALL PASS` |
| MCP server import (the CI smoke step) | **Works** | `MCP server import OK` |
| `pip install ./mnemosyne` and the `mnemosyne` console script | **Works** | installs; `mnemosyne --help` lists 18 subcommands |
| `init`, `config`, `capture`, `reflect`, `list`, `show`, `stats`, `validate`, `render`, `hygiene`, `prune` | **Works** | [§1.3](#13-output-what-works) |
| Hygiene guards: transient-failure refusal and near-duplicate reinforcement | **Works** | exit 3 on "timed out"; `REINFORCED: L-0001 (similarity 1.00 >= 0.6)` |
| `recall` by query, tags, stage, `--from-brief`, JSON format, no-match | **Works** | ranked, budgeted, reasons shown |
| `promote` (prints steps) and `promote --push` (to a bare remote) | **Works, with a defect** | it pushes, but sweeps in other promotions ([B3](#b3-a-promotion-pr-sweeps-in-earlier-uncommitted-promotions)) |
| Federation: `stores`, `promote --to team`, recall collapse, `sync`, retire-on-merge | **Works** once a lesson is approved upstream; nothing in the engine can approve it ([B4](#b4-nothing-in-the-engine-approves-a-proposed-lesson)) | `EXPORTED: … (L-0001->T-0001)`, then `retired-on-merge (approved upstream): L-0001` |
| Unreachable store | **Works** (skipped with a note) | but recall *tries to clone* it, every time ([B5](#b5-recall-clones-url-stores-on-the-hot-path)) |
| Claude Code hook bridge (`mnemosyne/plugin/hooks/mnemosyne_hook.py`) | **Works** | injects a digest on a matching prompt; silent on no match, on `session-start`, and with the package absent |
| **MCP server tool calls** | **Broken on Windows** | every call times out ([B1](#b1-the-mcp-server-hangs-on-every-tool-call-on-windows)) |
| **Lesson ids across branches** | **Broken** | id reuse silently shadows a merged lesson ([B2](#b2-lesson-ids-are-reused-across-branches-and-a-merged-lesson-vanishes)) |
| `wizard` (interactive) | **Untested** by hand; the selftest drives it with scripted input | — |
| MCP server on Linux or macOS | **Untested** | CI only imports it; no CI step calls a tool |
| Plugin install through a marketplace | **Untested; cannot be done.** The repo has no `marketplace.json` (stage 1 §2.1) | — |
| Hooks under Copilot, Codex or Cursor | **Untested** | — |

### 1.3 Output: what works

```text
$ mnemosyne reflect --title "Pin idempotency for every new POST endpoint" … --stage plan --confidence high
SAVED: L-0002 captured to LOCAL reflexion memory — "Pin idempotency for every new POST endpoint" [mistake/episodic].
$ mnemosyne reflect --title "Re-run the build" … --reflection-of "the test timed out and a re-run fixed it"
error: this reads as a missing-deliverable / transient failure (matched: 'timed out'). …
-> exit 3
$ mnemosyne capture --category convention --title "Page list endpoints at 50 by default" …   (second time)
REINFORCED: L-0001 (similarity 1.00 >= 0.6) — not banking a duplicate; …
$ mnemosyne recall --query "adding a new POST endpoint that may be replayed" --stage plan
RECALL: 1 reflexion lesson(s) applied to this context (L-0002). …
- L-0002 [mistake/intake+plan/local] Pin idempotency for every new POST endpoint
    matched: tags:replay | stage:plan
$ mnemosyne promote L-0001 --to team
EXPORTED: 1 lesson(s) to the 'team' store as proposed (L-0001->T-0001).
$ mnemosyne sync          (after T-0001 was set to approved by hand, see B4)
  retired-on-merge (approved upstream): L-0001
$ echo '{"prompt":"refactor toward composition instead of a deep class tree"}' | python mnemosyne_hook.py prompt
[Mnemosyne reflexion memory] Relevant prior lessons — apply them and tell the user which you applied:
RECALL: 1 reflexion lesson(s) applied to this context (L-0001). …
```

### 1.4 What is broken

#### B1. The MCP server hangs on every tool call on Windows

`tools/list` answers, but `hygiene`, `capture` and `recall` each time out after 20 s, against a
fresh store with no federation. The calls do run: the `capture` lesson was on disk afterwards. Only
the response never arrives.

```text
tools: ['capture', 'export', 'hygiene', 'promote', 'prune', 'recall', 'reflect']
hygiene -> TIMEOUT after 20s
capture -> TIMEOUT after 20s
recall -> TIMEOUT after 20s
```

**Cause, confirmed:** `core.git()` (`mnemosyne/src/mnemosyne/core.py:400`) runs
`subprocess.run(..., capture_output=True)` without setting `stdin`. The `git` child inherits the
server's stdin, which over stdio *is* the MCP channel. With a diagnostic wrapper that defaults
`stdin=subprocess.DEVNULL` (and changes nothing else), all three calls answer at once. Every tool
reaches `git` through the digest banner's `git_sha`, so every tool is affected. The fix is one
argument; per the brief it is not made here. CI cannot see this, because it only imports the
server on Linux.

#### B2. Lesson ids are reused across branches, and a merged lesson vanishes

`promote` moves a lesson out of the gitignored local tier into `lessons.jsonl` and commits it on a
`reflexion/<id>` branch. Back on the default branch the lesson now exists nowhere, so recall cannot
find it, and the next capture is given the **same id**:

```text
main shared: []
local: ['L-0001:Prefer composed helpers over d']      <- new capture, re-used L-0001
```

After the review branch merges, shared `L-0001` ("Page list endpoints at 50") and local `L-0001`
("Prefer composed helpers") collide. The local one wins, and the shared lesson disappears from
`list`, `show` and `recall`. `validate` does not report it:

```text
VALIDATE: 0 problem(s) — 3 lessons (1 shared, 1 local) @ 5a0eb80
  - note: LESSONS.md is stale; run `mnemosyne render`
$ mnemosyne recall --tags pagination
RECALL: no reflexion lessons matched this context.
```

Two things cause it: `next_id` counts only what is on the current branch, and `promote` *moves* the
lesson instead of keeping a local copy until the PR merges, which is what `export` already does.

#### B3. A promotion PR sweeps in earlier uncommitted promotions

`promote L-0001` (without `--push`) left `lessons.jsonl` modified. A later `promote L-0002 --push`
then committed that file whole. The commit says L-0002, but it carries both lessons:

```text
reflexion: promote L-0002 — Pin idempotency for every new POST endpoint
ids in that commit: ['L-0001:Page list endpoints at 50 by d', 'L-0002:Pin idempotency for every new ']
```

#### B4. Nothing in the engine approves a proposed lesson

`review.state` goes `local` → `proposed` and never reaches `approved` through any command, MCP tool
or API call. The schema enum and `sync`'s retire-on-merge both depend on `approved`, and the
selftest gets there by writing the JSONL directly (`mnemosyne/src/mnemosyne/cli.py:691`). So in
real use an exported lesson's local original never retires, unless a reviewer hand-edits the store,
which the design doc forbids. Recall ignores review state entirely, so `proposed` and `approved`
rank the same. The fix is decided: merging the review PR is the approval
([Q6](#q6-how-a-proposed-lesson-becomes-approved), [§4.8](#48-engine-changes-this-needs)).

#### B5. Recall clones URL stores on the hot path

The design doc says recall "never touches the network". But `recall` → `federated_load` →
`ensure_cloned` (`mnemosyne/src/mnemosyne/stores.py:92`) clones any URL store it hasn't cloned yet,
and while the store stays unreachable it tries again **on every recall**, which means on every
prompt once the hook is installed. `GIT_TERMINAL_PROMPT=0` stops it hanging on credentials, but
not the network round trip. Either the code or the doc is wrong; this spec assumes the code
changes ([§4.8](#48-engine-changes-this-needs)).

#### B6. Exports carry machine identifiers up a tier unscrubbed

Without `MNEMOSYNE_AUTHOR`, `author` falls back to `$USER` / `$USERNAME`, a machine login
(`mnemosyne/src/mnemosyne/core.py:970`). `export` deep-copies the lesson, including `author`,
`source.anchors` (which may be absolute paths) and free-text `reflection_of`, into the store
verbatim. Nothing scrubs it. This matters as soon as any store is shared beyond one person
([§4.6](#46-privacy-and-scrub-rules)).

### 1.5 Drift found along the way (docs only)

- [`zethus/README.md`](../zethus/README.md#copilot-formats-used-and-where-theyre-documented) says "Copilot
  has no hook that can block a tool call the way a pre-tool-use hook can". Copilot now documents
  `preToolUse` hooks in `.github/hooks/*.json` on the CLI and the cloud agent [S2]. The claim needs
  re-checking before it is relied on, and correcting in the PR that touches that section.
- [`mnemosyne/docs/design.md`](../mnemosyne/docs/design.md) states recall never touches the
  network (see B5).
- Stage 1 §2.1 says Cursor loads Claude hooks "by default". Cursor's current third-party-hooks page
  describes an opt-in mapping of eight events [S9]. Verify before the installer relies on either.

---

## 2. The integration as it stands

**There is none.** A case-insensitive search for `mnemosyne`, `reflexion`, `lesson`, `recall` and
`memory` across `zethus/` and `amphion/` finds only unrelated uses of the word "memory" (heap
sizes, "from memory").

| Kit | File | Mnemosyne today | Natural seam |
| --- | --- | --- | --- |
| Zethus | [`zethus/agents/zethus.agent.md`](../zethus/agents/zethus.agent.md) | none | Stage table: recall on entering a stage; triage at stage 7 exit |
| Zethus | [`zethus/copilot-instructions.md`](../zethus/copilot-instructions.md) | none | none needed; stays a router |
| Zethus | [`zethus/scripts/base-freshness.py`](../zethus/scripts/base-freshness.py) | none | Runs at stage 0 on every host: can print the recall digest |
| Zethus | [`zethus/scripts/new-adr.py`](../zethus/scripts/new-adr.py) | none | Every ADR is a human-signed decision: auto-capture |
| Zethus | [`zethus/scripts/new-spec.py`](../zethus/scripts/new-spec.py) | none | Spec creation: recall for the spec's title |
| Zethus | [`zethus/scripts/run-local-gates.py`](../zethus/scripts/run-local-gates.py) | none | Red → green on the same gate: a mistake candidate |
| Zethus | [`zethus/skills/implement-phase/SKILL.md`](../zethus/skills/implement-phase/SKILL.md) | none | *As built* deviations and the "real choice" stop |
| Zethus | [`zethus/skills/fresh-eyes-investigation/SKILL.md`](../zethus/skills/fresh-eyes-investigation/SKILL.md) | none | "Stuck twice" is a lesson signal |
| Zethus | [`zethus/install.py`](../zethus/install.py) | none | Would place a hook file and a Mnemosyne config |
| Zethus | [`zethus/zethus.config.example.json`](../zethus/zethus.config.example.json) | none | A `memory` block (§4.7) |
| Amphion | [`amphion/plugin/skills/flag-or-fix/SKILL.md`](../amphion/plugin/skills/flag-or-fix/SKILL.md) | none | Step 3 outcomes are classified decisions |
| Amphion | [`amphion/plugin/skills/log-friction/SKILL.md`](../amphion/plugin/skills/log-friction/SKILL.md) | none | A friction entry with a workaround is a lesson candidate |
| Amphion | [`amphion/plugin/skills/load-context/SKILL.md`](../amphion/plugin/skills/load-context/SKILL.md) | none | Recall alongside the decided context |
| Amphion | [`amphion/plugin/skills/resume-interrupted-phase/SKILL.md`](../amphion/plugin/skills/resume-interrupted-phase/SKILL.md) | none | A crashed delegate is a process candidate |
| Amphion | [`amphion/amphion.config.example.json`](../amphion/amphion.config.example.json) | none | The same `memory` block, shared key names |
| Amphion | [`amphion/plugin/.claude-plugin/plugin.json`](../amphion/plugin/.claude-plugin/plugin.json) | none, and no hooks | — |
| Mnemosyne | [`mnemosyne/plugin/hooks/hooks.json`](../mnemosyne/plugin/hooks/hooks.json) | `SessionStart` (sync) and `UserPromptSubmit` (recall) | No capture hook exists anywhere |

Two facts shape the design. **Amphion has no runtime**, so the only deterministic seams there are
hooks. **Zethus already has stdlib scripts at exactly the moments that matter**, and their output
reaches the agent as tool output on every host.

---

## 3. Harness convergence

### 3.1 What the hosts share now

Researched 2026-10-29 from vendor docs. The hook rows for Copilot and VS Code, and the Agent Skills
donation, were re-checked by hand. Other cells are from the research pass and are marked where no
primary source was found. Stage 1 §2.1 holds the fuller matrix for Claude Code, Copilot, Codex and
Cursor; this table updates it and adds Gemini and Antigravity.

| Artifact | Claude Code | Copilot (CLI · VS Code · cloud) | Codex | Gemini CLI / Antigravity | Cursor |
| --- | --- | --- | --- | --- | --- |
| `SKILL.md` (Agent Skills) | native `.claude/skills` [S1] | native `.github`/`.claude`/`.agents` skills [S3] | native `.agents/skills` [S4] | native `.gemini/skills`, `.agents/skills` [S5] | native, also reads `.claude`, `.codex` [S8] |
| `AGENTS.md` | only when no `CLAUDE.md`, unless a setting loads both [S1] | yes [S3] | yes, nested [S4] | Antigravity yes; Gemini CLI via `context.fileName` [S5] | yes, nested [S8] |
| Custom agents | `.claude/agents/*.md` | `.agent.md`; **reads `.claude/agents`** [S3] | TOML `.codex/agents` [S4] | own Markdown [S5] | **reads `.claude/agents`, `.codex/agents`** [S8] |
| Hooks, native | `settings.json` / plugin `hooks.json` [S1] | `.github/hooks/*.json` [S2] | `hooks.json` / `config.toml` [S4] | own `settings.json` events / `.agents/hooks.json` [S5] | `.cursor/hooks.json` [S9] |
| Reads Claude-format hooks | — | **CLI and VS Code: yes** (`.claude/settings*.json`); **cloud agent: no** [S2], [S6] | no [S4] | no [S5] | opt-in mapping, 8 events [S9] |
| Session-start context injection | yes | **yes**: `additionalContext` on `sessionStart` [S2] | yes, Claude-shaped [S4] | unverified | yes, `additional_context` [S9] |
| **Per-prompt context injection** | yes (`UserPromptSubmit`) | **no**: "config-file `userPromptSubmitted` hooks have their output dropped" [S2]; VS Code: "command-hook output is ignored" [S6] | yes [S4] | unverified | no documented output [S9] |
| MCP | yes | yes | yes | yes | yes (config files differ per host) |
| Plugin format | `.claude-plugin/` | **loads Claude plugins** (CLI, VS Code) [S3], [S6] | root `plugin.json`, accepts Claude manifests [S4] | Antigravity imports Claude plugins; Gemini extensions [S5] | the `.cursor-plugin` manifest / Agent Plugins [S8] |
| Memory | auto memory, local Markdown | Copilot Memory, server-side | memories, off by default | `save_memory` into `GEMINI.md` | unverified |

The Agent Skills standard was donated to the Agentic AI Foundation (Linux Foundation) on
2026-10-22. Anthropic cites more than 70 adopting platforms, including Copilot, VS Code, Cursor and
ChatGPT [S7]. `AGENTS.md` is also stewarded by AAIF [S10]. A second plugin pole, Agent Plugins 1.0,
backed by Microsoft, OpenAI, Cursor and others, standardises only skills and MCP and namespaces
everything else by vendor (from the research pass, unverified by hand).

### 3.2 Converged, converging, still per-host

- **Converged, one file works today:** `SKILL.md` skills (ship them in both `.claude/skills` and
  `.agents/skills` to reach every host), `AGENTS.md`, MCP servers, and Claude-format agents
  (`.claude/agents/*.md` reaches Claude Code, Copilot and Cursor).
- **Converging:** hooks. The event set (session start, prompt submit, pre/post tool, pre-compact,
  stop, session end) exists almost everywhere under different names. Claude's file format is the
  closest thing to a lingua franca: Copilot CLI and VS Code read it natively and Cursor maps it.
  But **what a hook's output can do differs**, and that matters more than the file format. The
  plugin format is converging on Claude's `.claude-plugin/` for Copilot and Antigravity, with
  Agent Plugins as a rival.
- **Still per-host:** memory (no standard at all), agent files for Codex (TOML) and Gemini, hook
  files for Codex, Gemini, Antigravity and the Copilot cloud agent, and path-scoped rules.

### 3.3 What this implies for Zethus and Amphion

Ceryce's premise holds for **format**. Neither kit is tied to its host any more: Amphion's
`.claude-plugin/` loads in Copilot CLI and VS Code, Zethus's `SKILL.md` skills load in Claude Code,
and Copilot reads `.claude/agents`. The format split that once justified two kits is mostly gone.

It does not hold for **memory or hook behaviour**. Those are exactly what this feature needs, so
any design must carry per-host adapters whichever way the kits are packaged. And the two kits still
differ in **philosophy**, which convergence does not touch: Zethus is an enforcer that refuses to
skip stages, while Amphion is six optional skills that compose and "don't depend on each other".
Zethus already shares Amphion's config vocabulary and points to Amphion's exception handlers
([`zethus/README.md`](../zethus/README.md#how-it-relates-to-amphion)).

**Decided: both kits stay, on a shared core** ([Q1](#q1-fuse-zethus-and-amphion), ruled
2026-10-29). One source tree holds what both need: the memory hooks and their registration, the
`memory` config schema, the shared skills (`flag-or-fix`, `resume-interrupted-phase`, one
`pr-description`), and the installer stage 1 already planned. Zethus remains the enforcing agent and
Amphion the à-la-carte skill set; each installs the core it needs, and installing both installs it
once. The packaging is Phase 4 ([§5](#5-phases)); nothing before it waits on it.

The options that were not chosen:

- **Fuse into one kit.** One name, one install. The Zethus agent would become the enforcer,
  Amphion's skills its exception handlers, and an "enforcement off" mode would stand in for
  Amphion's composable use.
- **Keep them separate.** Wire Mnemosyne into each independently.

---

## 4. Spec: capturing errors, lessons, decisions and standards

### 4.1 What is worth remembering

Mnemosyne already has the vocabulary: `category` (mistake, decision, convention, security,
architecture, process) and `memory_type` (episodic, semantic, procedural). This spec adds no
category. It adds one marker: a **standard** is a `convention` with `memory_type: procedural` that
has recurred across distinct contexts (§4.4).

| Kind | Worth remembering when | Not worth remembering |
| --- | --- | --- |
| **Error** (`mistake`) | It cost a retry, a red gate or a reviewer catch, and the *fix* generalises beyond this line of code | A transient failure, a flake, or a re-run that fixed it. The engine's guard already refuses these |
| **Lesson** (`mistake`/`process`, episodic) | Feedback changed what the agent should do next time | A restatement of the task, or anything the repo's own docs already say |
| **Decision** (`decision`/`architecture`) | A choice between real options was made by a person, or recorded as an ADR | A choice the spec already made |
| **Convention** (`convention`) | The user stated or corrected a house rule ("we page at 50", "never squash") | A one-off preference scoped to this task |
| **Standard** (`convention` + procedural + recurrence) | The same answer was given three times across at least two distinct contexts within 180 days (Q4, Q5) | The same answer in the same context, however often |

### 4.2 How the agent identifies one in-session

Identification is split by what can be done deterministically. Hooks and scripts **detect
signals** and write *candidates*. The agent **judges** candidates at fixed checkpoints. No
transcript is parsed and no model is called from a hook, which is what killed Morpheus
([retrospective](morpheus-retrospective.md)).

| # | Signal | Detected by | Kind | Default outcome |
| --- | --- | --- | --- | --- |
| S1 | An ADR is recorded (`new-adr.py` ran) | Zethus script | decision | **auto** |
| S2 | The same gate goes red, then green, within a phase (`run-local-gates.py`) | Zethus script | mistake | **auto**, if the agent supplies a one-line fix at triage; otherwise ask |
| S3 | `base-freshness` reports STALE at stage 6 after a FRESH stage 0 | Zethus script | process | ignore (expected), unless it recurs → standard |
| S4 | The user explicitly says "remember", "always", "never", "from now on" | prompt hook (side effect only) | convention | **auto**: an explicit instruction is consent |
| S5 | The user corrects the agent ("no,", "don't", "instead", "that's wrong") | prompt hook | convention / mistake | **ask** |
| S6 | Tool failure followed by success on a similar command | post-tool hook | mistake | **ask** (high noise; Phase 0 measures it) |
| S7 | A decision question is answered with the same option as a prior ADR or decision lesson | triage (lesson match) | standard | **ask to promote** |
| S8 | `fresh-eyes-investigation` invoked (stuck twice) | post-tool hook on the skill / Zethus stage rule | lesson | **ask** at the next stage exit |
| S9 | An *As built* deviation is written to a spec | post-tool hook on a watched path | decision | **ask** |
| S10 | A friction-log entry with a workaround (Amphion `log-friction`) | post-tool hook on the watched path | process | **ask** |
| S11 | A `flag-or-fix` outcome other than "fix now" | post-tool hook on the PR body / spec path | decision | **ask** |
| S12 | A lesson recalled this session was overridden by the user | triage | supersede | **ask** (offer `--supersede`) |

**Watched paths** (S9–S11) are a config list, not code: the ADR directory, the spec directory, the
friction-log path. Any write the post-tool hook sees to one of them becomes a candidate carrying
the path and nothing else. Matching keywords in a prompt (S4, S5) gives cheap, explainable signals
with known false positives. That is why S5 asks instead of storing.

### 4.3 The three outcomes

Every candidate goes through one rule table, in this order. The first matching row wins.

| Order | Rule | Outcome |
| --- | --- | --- |
| 1 | Scrub finds a secret or credential shape (§4.6) | **drop**, never stored anywhere; say so |
| 2 | Category would be `security`; it is a judgement about a person (a colleague, a reviewer); it would supersede an existing lesson; or its text would have to quote tool output, web or issue text, or the transcript | **ask** |
| 3 | The candidate matches an existing lesson (dedup threshold) | **reinforce** it and record the context; then check rule 6 |
| 4 | Signal default is *auto* (S1, S2 with a fix line, S4) and the session's auto budget isn't spent | **store automatically**, local tier |
| 5 | Anything else | **ask** |
| 6 | After a reinforce: the lesson has occurred three times across at least two distinct contexts within 180 days (§4.4) and isn't yet a standard | **ask to promote into a standard** |

Rules 1 and 2 hold five of the six classes [Q2](#q2-what-may-auto-store-never-store-multi-select)
ruled auto-store must never store. The sixth, anything beyond the local tier, is the first bullet
below. All six are fixed, not config keys. The engine refuses the four it can check mechanically on
any capture marked `captured_by: hook:*`: a secret shape, the `security` category, a supersede, and
a tier other than local (§4.8). The triage skill judges the other two, a judgement about a person
and quoted text, because no pattern can. A refused candidate stays in the spool for the next ask,
except a secret, which is dropped.

**Store automatically** always:

- lands in the **local** tier only (gitignored, per developer), never shared: anything beyond local
  always asks, and auto-store never opens a PR (Q2 and Q7, ruled);
- stores only text the agent wrote: a distilled lesson, never pasted tool output, web or issue text,
  or transcript excerpts (Q2, ruled; §4.6 *Untrusted text*);
- is announced with the engine's `SAVED:` line in the same reply;
- is marked `source.captured_by: hook:<signal>` so auto-captures can be listed, reviewed and pruned
  as a group;
- starts at `confidence: medium`, so only reinforcement can raise it;
- respects a per-session budget (default 5) and can be undone in one command (a new
  `mnemosyne retire <id> --reason`).

**Ask** batches every pending candidate into **one** question set at a checkpoint, never in the
middle of a step. Each candidate becomes an option set: *save as proposed*, *save edited*, *skip*,
*never ask about this kind*. Claude Code renders it with its question tool; on Copilot it uses
Zethus's numbered-options convention. A *skip* is remembered as a negative fingerprint, so the same
candidate isn't asked twice.

**Ask to promote into a standard** proposes that the recurring lesson becomes:

1. a shared-tier lesson with `memory_type: procedural`, confidence high, and the `standard` marker,
   via the normal promote PR; and
2. where the answer maps to a config key (a gate command, `branchModel.maxBehind`, a commit
   trailer), a **config default**, so Zethus stops asking the question at all.

It never proposes writing into `AGENTS.md`, `CLAUDE.md` or Copilot instructions: those are routers
and carry no detail (repo [`AGENTS.md`](../AGENTS.md)).

### 4.4 Recurrence: "the same answer in different situations"

Mnemosyne's `reinforced` counter already counts near-duplicates, but it doesn't know *where* each
one came from. So twenty reinforcements in one spec look the same as three across three repos.

- Every reinforce appends a **context fingerprint** to the lesson:
  `{ctx: <hash>, stage, date, signal}`.
- **A context is a spec or ticket** ([Q5](#q5-what-counts-as-a-distinct-context), ruled): two
  pieces of work in the same repo are different contexts, and one long ticket counts once however
  many sessions it spans. Where there is no spec or ticket id, the branch stands in.
- The hash is a salted hash of the repo's identity plus the spec or ticket id (else the branch). A
  shared tier can then count distinct contexts **without learning repo or ticket names** (§4.6).
- *Distinct contexts* means distinct hashes inside a rolling window of 180 days, the existing
  `prune_max_age_days`.
- **A lesson becomes a standard candidate at three occurrences across at least two distinct
  contexts** within that window ([Q4](#q4-recurrence-threshold-for-a-standard), ruled).
- For decisions (S7), the match is on the *question class* plus the *chosen option*. Each ADR
  records both, so the same answer across three ADRs in three specs is a standard candidate even
  where the wording differs.

The thresholds are config keys (`memory.standard`, §4.7) whose defaults are the Q4 ruling. What
counts as a context is not configurable.

### 4.5 Where each outcome lands

These are Mnemosyne's own tiers ([design](../mnemosyne/docs/design.md#architecture)). The
"federated tiers" in the ask are its **stores**: separate memory repos declared in `config.stores`,
each with its own id prefix, read at recall time and written to only through a review PR in *that*
store's repo.

| Outcome | Tier | Mechanism | Human gate |
| --- | --- | --- | --- |
| Auto | **local** (`local.jsonl`) | `capture` / `reflect` | none (announced, undoable) |
| Ask → yes | **local** | `capture` / `reflect` | the answer |
| Promote to the project | **shared** (`memory/lessons.jsonl` in the primary repo) | `promote` → PR | PR review |
| Standard, or an explicit share | a **store** (e.g. `personal`, `team`, `enterprise`) | `promote --to <tier>` → PR in the store repo, **after scrub** | PR review in the store |

**Sharing defined in Mnemosyne's terms:** a lesson is *shared* when it sits in a committed file of
any repo other than the developer's own gitignored local tier. Sharing therefore always means a
`promote` or `export`, always produces a PR, and always runs the scrub. Which store the agent
offers by default is [Q3](#q3-federation-target). **Nothing from Ceryce's work may ever land in
this repository**: its `mnemosyne/memory/` is a public demo store.

### 4.6 Privacy and scrub rules

The repo is public, and stores may be shared with an organisation. The engine runs the scrub on
every write to a committed tier: `promote`, `export`, and `capture --shared`. The secrets rule runs
on every write, the local tier included. None of it is left to the agent.

| Rule | What it catches | Action |
| --- | --- | --- |
| **Secrets** | Key and token shapes: cloud access keys, `ghp_`/`gho_`/`github_pat_`, `sk-`, `xox?-`, PEM blocks, JWTs, `password=`/`token=` assignments | **Hard block at every tier, local included** (Q2, ruled). Auto-store drops the candidate (rule 1) |
| **Machine identifiers** | The identifier guard's shapes: home-directory paths, drive paths, WSL mounts, non-allowlisted emails, repo URLs under foreign orgs ([`scripts/check_identifiers.py`](../scripts/check_identifiers.py)) | Block; show the match; offer the placeholder |
| **Author** | The `$USER`/`$USERNAME` fallback (B6) | Never fall back to the login. Require `MNEMOSYNE_AUTHOR` or a configured handle, else write `unknown` |
| **Anchors** | Absolute paths, or paths outside the repo | Rewrite to repo-relative; drop what can't be |
| **Provenance** | `spec_id`, ticket keys, branch names | Kept in local and shared tiers; **replaced by the context hash** when exporting to a store marked `scope: "external"` |
| **Private terms** | Client, employer and project names | Optional denylist file **outside any repo** (`MNEMOSYNE_DENYLIST`), the same pattern as the private sweep in the guard's docstring. The list's content is never committed |
| **Untrusted text** | Tool output, web pages, issue bodies | Never copied into a lesson verbatim. A candidate carries pointers (path, signal, exit code); the agent or user writes the lesson text |

A green scrub is not clearance to publish, for the reasons the guard's own docstring gives. The
review PR stays the gate. The [lesson review checklist](../mnemosyne/docs/lesson-review-checklist.md)
gains a line for the context hash and the scrub result.

### 4.7 How Zethus and Amphion call it first-class

Two channels, both deterministic. Neither depends on the agent remembering a paragraph of prose.

**Channel 1: Zethus's scripts (every host, every surface).** Script stdout is the one way to put
context in front of the agent that works on Claude Code, Copilot CLI, VS Code, JetBrains, the
Copilot cloud agent, Codex and Cursor alike. Each script imports `mnemosyne` if it is installed and
does nothing otherwise, which keeps Zethus's stdlib-only, fail-open rule:

| Script | Stage | Adds |
| --- | --- | --- |
| `base-freshness.py` (gating form) | 0 | Prints the recall digest for the task branch and the spec, if any, with the stage; prints the count of pending candidates from earlier sessions |
| `new-spec.py` | 2 | Prints the recall digest for the spec title |
| `new-adr.py` | any | Writes candidate S1; the agent's triage auto-stores it as a `decision` |
| `run-local-gates.py` | 6 | Writes candidate S2 when a gate that failed earlier in the phase now passes |

**Channel 2: lifecycle hooks** for signals no script sees: the user's words, tool failures, and
end-of-turn triage. One hook script (the existing bridge, grown new modes) lives in the shared core
([Q1](#q1-fuse-zethus-and-amphion), ruled), so Zethus and Amphion ship the same script rather than
a copy each. It is registered once per host, never twice, even with both kits installed (stage 1
§3.1 rule):

| Mode | Claude Code | Copilot CLI / VS Code | Copilot cloud agent | Codex | Cursor |
| --- | --- | --- | --- | --- | --- |
| `session-start`: recall digest + pending count | `SessionStart` stdout | `sessionStart` `additionalContext` | same, via `.github/hooks/*.json` | `SessionStart` `additionalContext` | `sessionStart` `additional_context` |
| `prompt`: S4/S5 detection, and recall where output is honoured | `UserPromptSubmit` (injects) | `userPromptSubmitted`, **side effect only**: output dropped | same | `UserPromptSubmit` (injects) | `beforeSubmitPrompt`, side effect only |
| `post-tool`: S6, S8–S11 | `PostToolUse` | `postToolUse` | `postToolUse` | `PostToolUse` | `postToolUse` |
| `stop`: triage checkpoint | `Stop`: block once with "N candidates pending, triage them" (guarded by `stop_hook_active`) | `agentStop`: can it block? **unverified**; fallback is the next `session-start` | same | `Stop`: **unverified** | `stop`: **unverified** |
| `pre-compact`: flush the spool | `PreCompact` | `preCompact` | auto-compaction only | `PreCompact` | `preCompact` |

Registration lives in one neutral file: Claude-format `hooks.json` in the shared core's plugin. It is read
as-is by Claude Code, Copilot CLI and VS Code (from `.claude/settings.json` in repo installs), and
by Cursor if opted in. A Copilot-format copy under `.github/hooks/*.json` covers the cloud agent,
installed **only** when the repo doesn't already carry the Claude file, so the CLI never fires
twice. Codex gets its own `hooks.json`. Gemini and Antigravity are out of scope until asked.

**Hook rules, from the Morpheus retrospective:**

- Hooks only append to the spool and exit. No git, no network, no model, no lock on the store. Each
  is bounded at 200 ms.
- Every hook writes one log line per decision. A `mnemosyne doctor` command shows the last N
  decisions, so a fail-open hook never fails silently.
- Every guard is tested with the variable set the way the host sets it.

**Where judgement happens:** the agent triages the spool at three checkpoints, using a new
`lessons-triage` skill that runs the rule table in §4.3 through the engine. The checkpoints are
the `stop` hook (Claude Code), the stage 7 exit in Zethus's stage table (one row: "pending
candidates triaged"), and `session-start` on hosts where `stop` cannot block. The stage-table row
is a pointer to the skill, not the procedure, so the agent file grows by one line.

**Amphion** has no scripts, so it gets channel 2 only. Its config gains the same `memory` block,
and its watched paths come from its existing keys (`frictionLog.markdown.path`, `ledger.path`).

**Config** (`memory`, one schema in the shared core, read from `zethus.config.json` and
`amphion.config.json` alike; every key optional. Q2's exclusions are not keys here, by design):

```json
"memory": {
  "enabled": true,
  "repo": "",
  "autoStore": { "signals": ["adr", "gate-red-green", "explicit-remember"], "perSession": 5 },
  "watch": ["docs/adr/", "docs/specs/", "docs/friction-log.md"],
  "standard": { "minOccurrences": 3, "minContexts": 2, "windowDays": 180 },
  "offerTier": "personal"
}
```

### 4.8 Engine changes this needs

All of these are inside Mnemosyne and stay stdlib-only.

| Change | Why | Size |
| --- | --- | --- |
| `stdin=subprocess.DEVNULL` in `core.git`, plus a CI test that calls an MCP tool on Windows and Linux | B1 | S |
| Ids that can't collide across branches (date- or hash-keyed, as `new-adr.py` already does), and `promote` keeps the local copy until merge, as `export` does | B2 | S–M |
| `promote` stages only its own lesson's lines, or refuses on a dirty store | B3 | S |
| Merged means approved ([Q6](#q6-how-a-proposed-lesson-becomes-approved), ruled): `promote` and `export` write `review.state: approved` into the review PR's commit, so merging the PR is the approval; the local original stays `proposed` until `sync` sees the id on the store's default branch and retires it | B4 | S |
| Recall never clones; only `sync` and `stores` do | B5 | S |
| The scrub (§4.6) on every committed-tier write, and its secrets rule on every write, local included; the author fallback removed | B6, Q2 | M |
| `capture` / `reflect` refuse a `captured_by: hook:*` lesson that is `security`, supersedes another, or targets a tier other than local | Q2 | S |
| Candidate spool `candidates.local.jsonl` beside the local tier (gitignored) with `candidate add/list/triage/dismiss` | §4.2 | M |
| Context fingerprints on reinforce, and the `standard` marker | §4.4 | S–M |
| `retire <id> --reason` and `doctor` | §4.3, §4.7 | S |
| The bridge grows `post-tool`, `stop` and `pre-compact` modes, plus per-host output shapes | §4.7 | M |

### 4.9 Out of scope

- **Transcript mining or "dreaming".** That was Morpheus, and it was retired for good reasons.
- **Writing into a host's native memory** (Claude auto memory, Copilot Memory, Codex memories).
  A second writer races the native one ([retrospective](morpheus-retrospective.md#why-it-was-retired-rather-than-fixed)).
- **Vector recall.** The lexical scorer is fine for procedural rules, and the design doc already
  names the upgrade path.
- **Gemini CLI and Antigravity hook adapters**, until a user needs them.
- **Building the shared core.** Q1 chose it, and it is Phase 4; Phases 0–3 don't wait on it.
  Fusing the kits is not planned at all.

---

## 5. Phases

Sizes follow stage 1: S is under half a day, M is half a day to two days, L is two to five days.

| Phase | What | Behaviour change | Exit, verified by | Size |
| --- | --- | --- | --- | --- |
| **0** | Engine fixes B1–B6 before any capture (Q8, ruled), with tests that fail before each fix. B4 is fixed as merged-means-approved (Q6); B6 is the scrub (§4.6) and the author fallback. Candidate spool and hooks in **shadow mode**: they record candidates and log decisions, but store nothing and ask nothing. Verify the unverified hook cells in §4.7 on real installs | Bug fixes only; capture is observe-only | An MCP tool-call test green on Windows and Linux; an id-collision test; a merged review PR retires its local original with no hand edit; an export carrying a home-directory path or a login as author is blocked; one week of spool data showing the count and precision of each signal | M–L |
| **1** | Auto-store for S1 (ADR) and S2 (gate red → green) through Zethus's scripts. `session-start` recall digest. Claude Code `stop` triage of pending candidates through the `lessons-triage` skill. Local tier only (Q7). The Q2 exclusions hold from here: an S1 or S2 candidate in an excluded class is asked at the same triage, never saved | Yes: auto-store to local, one triage checkpoint | A Zethus run that records an ADR and fixes a red gate ends with two `SAVED:` lines and an empty spool; `retire` undoes either; no write outside `local.jsonl`; a `security` ADR is asked, not saved, and the engine refuses it as a hook capture | M |
| 2 | Ask outcomes (S4–S6, S8–S12), batched; Copilot `sessionStart` and `.github/hooks/*.json`; Amphion watched paths | Yes | Triage on Copilot CLI and VS Code; no double-fire with both files present | M |
| 3 | Context fingerprints (a context is a spec or ticket, Q5), standards (S7), promotion to shared or store, and config-default proposals. The default store depends on Q3, which is open | Yes | Three ADRs with the same answer across two specs produce exactly one "promote to standard?" question; three in one spec produce none (Q4) | M |
| 4 | The shared core (Q1, ruled), inside the stage 1 installer: one source tree for the memory hook script and its `hooks.json`, the `memory` config schema, and the shared skills. Zethus and Amphion each install from it and keep their own names, READMEs and install paths | Packaging | Stage 1 §3.4 CI additions green; installing both kits registers each hook once; `tests/test_zethus.py` green | M, on top of the stage 1 installer |

Phase 0 deliberately ships no capture. Building capture on an engine that loses lessons on merge
(B2) would bank data straight into the bug, which is why Q8 ruled the fixes first. And the signal
table in §4.2 is a hypothesis about precision: a week of shadow data is cheaper than tuning
auto-store against real lessons. Phase 0 is M–L rather than M because the scrub (B6, M) moved into
it from Phase 1.

---

## 6. Verification run for this document

Before this PR was pushed, the repo's CI steps ran locally on Windows. All green:

| Step | Command | Result |
| --- | --- | --- |
| Identifier guard tests | `python -m unittest discover -s scripts -p "test_check_identifiers.py" -t scripts` | 27 OK |
| Identifier guard scan | `python scripts/check_identifiers.py` | clean |
| Doc pointer tests | `python -m unittest discover -s scripts -p "test_check_doc_pointers.py" -t scripts` | 29 OK |
| Doc pointer scan | `python scripts/check_doc_pointers.py` | every pointer resolves |
| Unit suite | `python -m unittest discover -s tests -t .` | 285 OK |
| MCP import smoke | `python -c "import mnemosyne.mcp_server"` | OK |
| JSON | every tracked `*.json` parses | OK |
| Markdown lint | `npx markdownlint-cli2 "**/*.md"` | 0 issues |

YAML validation and shellcheck were not run locally: no YAML or shell file changed, and the repo
has no `*.sh` files.

---

## 7. Open questions for Ceryce

Each lists the recommended option first. Costs use the sizes in §5. **Q1, Q2 and Q4–Q8 are ruled,
every one as recommended; Q3 is open.**

### Rulings (2026-10-29)

Ceryce answered by Telegram picker. Each tap is quoted verbatim, with the option description the
picker showed beside it.

- **Q1**, at 22:03 CT: **"Shared core"**: "One core both kits use (wiring written once), Zethus
  keeps enforcing process, Amphion stays optional skills. Cost: medium, on top of the planned
  installer."
- **Q2** (multi-select), at 22:04 CT, all six tapped:
  - **"Secrets, at any tier"**: "Keys, tokens, credentials, anywhere."
  - **"Raw tool or web text"**: "Only the agent's distilled lesson, never pasted output."
  - **"Anything beyond local"**: "Auto-store writes the local tier only; sharing always asks."
  - **"Security lessons"**: "Always asked, never auto."
  - **"Judgements about people"**: "Never auto-stored."
  - **"Replacing an existing lesson"**: "A superseding lesson always asks."
- **Q4**, at 22:05 CT: **"3 times across 2+ contexts within 180 days"**: "Recurs enough to be a
  pattern, across situations. Cost: slower to notice."
- **Q5**, at 22:06 CT: **"A different spec or ticket"**: "Same repo can still be different work.
  Cost: a long ticket can't count twice."
- **Q6**, at 22:06 CT: **"Merging its review PR is the approval"**: "Uses the PR you already
  review; fixes the 'nothing approves a lesson' bug. Cost: none new."
- **Q7**, at 22:06 CT: **"Local only"**: "Anything leaving your machine always asks. Cost: you
  approve every share."
- **Q8**, at 22:06 CT: **"Bugs first, as Phase 0"**: "MCP hang on Windows, reused lesson ids,
  swept-in promotions, no approve path, recall cloning offline, unscrubbed exports. Cost: capture
  waits a PR."
- **Q3** has not been answered.

Two picker texts differ from the options below, and the spec follows the picker in both cases:

- **Q8's picker listed six bugs, B1–B6.** Option 1 below says B1–B5. "Unscrubbed exports" is B6,
  so Phase 0 now fixes B1–B6, and the scrub moved there from Phase 1.
- **Q5's picker label omitted option 1's "else a distinct branch" fallback.** The spec keeps it,
  for work that has no spec or ticket id. It does not change her tap: the branch stands in only
  where there is no spec or ticket.

| Question | Status |
| --- | --- |
| Q1 | **Ruled: option 1** ("Shared core"). Reflected in [§3.3](#33-what-this-implies-for-zethus-and-amphion), [§4.7](#47-how-zethus-and-amphion-call-it-first-class), [§4.9](#49-out-of-scope) and Phase 4 |
| Q2 (multi-select) | **Ruled: all six options** (1–6). Reflected in [§4.3](#43-the-three-outcomes), [§4.6](#46-privacy-and-scrub-rules), [§4.8](#48-engine-changes-this-needs) and Phase 1 |
| Q3 | **Open** |
| Q4 | **Ruled: option 1** ("3 times across 2+ contexts within 180 days"). Reflected in [§4.1](#41-what-is-worth-remembering), [§4.3](#43-the-three-outcomes), [§4.4](#44-recurrence-the-same-answer-in-different-situations), the `memory.standard` config and Phase 3 |
| Q5 | **Ruled: option 1** ("A different spec or ticket"). Reflected in [§4.4](#44-recurrence-the-same-answer-in-different-situations) and Phase 3 |
| Q6 | **Ruled: option 1** ("Merging its review PR is the approval"). Reflected in [B4](#b4-nothing-in-the-engine-approves-a-proposed-lesson), [§4.8](#48-engine-changes-this-needs) and Phase 0 |
| Q7 | **Ruled: option 1** ("Local only"). Reflected in [§4.3](#43-the-three-outcomes) and Phase 1 |
| Q8 | **Ruled: option 1** ("Bugs first, as Phase 0"), as B1–B6. Reflected in the summary and Phases 0 and 1 |

### Q1. Fuse Zethus and Amphion?

**Ruled 2026-10-29, 22:03 CT: option 1** ("Shared core").

1. **Keep both on a shared core *(recommended; ruled)*.** Convergence removed the *format* reason
   for two kits but not the *philosophy* one: an enforcer and a set of optional skills serve
   different users. A shared core gives one copy of the memory hooks, config schema and shared
   skills, and it is the shape the stage 1 installer already plans. Cost: M on top of the stage 1
   installer; two READMEs and two names to keep.
2. **Fuse into one kit.** One name, one install, one story for the portfolio. Cost: L. It breaks
   both kits' documented install paths and `tests/test_zethus.py`'s layout, needs a naming
   decision, and turns Amphion's "any one is useful alone" into a mode of an enforcer.
3. **Keep them separate.** Cost: S now, more later: the hook wiring is written twice, and installing
   both risks double-firing hooks.

### Q2. What may auto-store never store? (multi-select)

**Ruled 2026-10-29, 22:04 CT: all six options** (1–6). None was left untapped.

1. **Secrets or credential shapes, at any tier *(recommended; ruled)*.** Cost: none; the scrub
   already needs the matcher.
2. **Raw tool output, web or issue text, or transcript excerpts *(recommended; ruled)*.** Lessons
   are written by the agent or the user, never pasted. Cost: some auto-captures become questions.
3. **Anything beyond the local tier *(recommended; ruled)*.** Cost: none now; sharing stays a PR.
4. **`security`-category lessons *(recommended; ruled)*.** Always asked. Cost: a few more
   questions.
5. **Judgements about people**, such as colleagues or reviewers *(recommended; ruled)*. Cost: none.
6. **Anything that would supersede an existing lesson *(ruled)*.** Cost: one more question when the
   user corrects a recalled lesson. Recommended as well; listed separately because it slows S12.

### Q3. Federation target

1. **A private personal memory repo as the default store, plus each project's own shared tier
   *(recommended)*.** Cross-repo standards live in the personal store, and project facts stay with
   the project. Cost: one private repo, and `stores` configured once per machine.
2. **One private memory repo as the primary for everything, with no project tiers.** Cost: the
   simplest setup, but project conventions leave the project, and teammates never see them.
3. **An organisation `enterprise` store for work repos, alongside option 1.** Cost: per-org setup,
   and needs `scope: "external"` scrubbing from day one.

### Q4. Recurrence threshold for a standard

**Ruled 2026-10-29, 22:05 CT: option 1** ("3 times across 2+ contexts within 180 days").

1. **Three occurrences across at least two distinct contexts within 180 days *(recommended;
   ruled)*.** Cost: a standard takes a few weeks to surface.
2. **Two occurrences across two contexts.** Cost: faster, but more false standards to decline.
3. **Five occurrences across three contexts.** Cost: few false positives, but rarely fires on a
   personal workload.

### Q5. What counts as a distinct context?

**Ruled 2026-10-29, 22:06 CT: option 1** ("A different spec or ticket"). The picker label left out
the branch fallback; see [Rulings](#rulings-2026-10-29).

1. **A distinct spec or ticket, else a distinct branch *(recommended; ruled)*.** Cost: needs the
   spec id at capture time, which Zethus has.
2. **A distinct repository.** Cost: a single-repo standard can never surface.
3. **A distinct session.** Cost: one long task spread over sessions counts many times.

### Q6. How a proposed lesson becomes approved

**Ruled 2026-10-29, 22:06 CT: option 1** ("Merging its review PR is the approval").

1. **Merged means approved *(recommended; ruled)*.** The review PR's commit carries `approved`, so merging
   *is* the approval, and `sync` retires local originals when the id reaches the store's default
   branch. Cost: S; no separate "proposed but merged" state.
2. **A `mnemosyne approve <id>` command** the reviewer runs on the PR branch. Cost: S, plus a
   manual step that is easy to forget.
3. **A GitHub Action in each store** flips the state on merge. Cost: M, and CI to maintain in every
   store repo.

### Q7. Auto-store's ceiling

**Ruled 2026-10-29, 22:06 CT: option 1** ("Local only"). This agrees with Q2 option 3 ("Anything
beyond local"), ruled a few minutes earlier.

1. **Local tier only *(recommended; ruled)*.** Cost: anything shared needs one promote.
2. **Auto-promote high-confidence lessons as a PR.** Cost: PR noise, and an unattended path into a
   shared tier.

### Q8. Engine fixes first, or alongside?

**Ruled 2026-10-29, 22:06 CT: option 1** ("Bugs first, as Phase 0"). The picker listed all six bugs,
so Phase 0 fixes B1–B6, not B1–B5 as written below; see [Rulings](#rulings-2026-10-29).

1. **Fix B1–B5 first, as Phase 0 *(recommended; ruled, as B1–B6)*.** Building capture on an engine
   that loses lessons on merge (B2) would bank data straight into the bug. Cost: about a day before
   visible capture.
2. **Fix them alongside Phase 1.** Cost: faster to a demo, but Phase 1's results can't be trusted
   until B2 lands.

---

## 8. Sources

Read 2026-10-29. [S2], [S6] and [S7] were re-checked by hand; the rest come from a research pass
over vendor docs.

- [S1] Claude Code: hooks, memory, skills, sub-agents — <https://code.claude.com/docs/en/hooks>, <https://code.claude.com/docs/en/memory>, <https://code.claude.com/docs/en/skills>
- [S2] GitHub Copilot hooks configuration (file locations, events per surface, Claude-format compatibility, `additionalContext` on `sessionStart`, dropped `userPromptSubmitted` output) — <https://docs.github.com/en/copilot/reference/hooks-configuration>
- [S3] GitHub Copilot custom instructions, skills and CLI plugin reference — <https://docs.github.com/en/copilot/concepts/agents/about-agent-skills>, <https://docs.github.com/en/copilot/reference/cli-plugin-reference>
- [S4] OpenAI Codex: hooks, `AGENTS.md`, skills, subagents, plugins — <https://learn.chatgpt.com/docs/hooks>, <https://learn.chatgpt.com/docs/agent-configuration/agents-md>, <https://developers.openai.com/codex/plugins/build>
- [S5] Gemini CLI and Antigravity: skills, hooks, `GEMINI.md`, plugins — <https://geminicli.com/docs/hooks/>, <https://geminicli.com/docs/cli/skills/>, <https://antigravity.google/docs/plugins>
- [S6] VS Code Copilot hooks (Preview; reads `.claude/settings.json`; `userPromptSubmitted` output ignored) and agent plugins — <https://code.visualstudio.com/docs/copilot/customization/hooks>, <https://code.visualstudio.com/docs/copilot/customization/agent-plugins>
- [S7] Anthropic, "Donating Agent Skills to the Agentic AI Foundation", 2026-10-22 — <https://www.anthropic.com/news/donating-agent-skills-to-the-agentic-ai-foundation>
- [S8] Cursor: skills, rules, subagents, plugins — <https://cursor.com/docs/context/skills>, <https://cursor.com/docs/context/subagents>, <https://cursor.com/docs/plugins>
- [S9] Cursor hooks and third-party (Claude) hook mapping — <https://cursor.com/docs/agent/hooks>, <https://cursor.com/docs/reference/third-party-hooks>
- [S10] `AGENTS.md` — <https://agents.md>

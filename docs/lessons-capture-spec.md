# Lessons capture and harness convergence: verification and spec (2026-10-29)

**Status:** Phases 0 to 4 are built. The engine fixes B1–B6 merged on 2026-10-30 (PR #46). The
candidate spool and the capture hooks ran in **shadow mode** for a month on one developer's
machine; the result is in [§5.1](#51-shadow-week-result-2026-11-24). Phase 1 then added
**auto-store** of the two deterministic, script-emitted signals (S1 an ADR, S2 a gate red→green),
a **session-start recall digest**, and a **Claude Code `stop` triage** through a new
`lessons-triage` skill — **local tier only** (Q7), with the Q2 exclusions enforced by the engine.
**Phase 2** tightened the keyword detectors, re-measured them on that spool
([§5.2](#52-tightened-detectors-measured-on-the-same-spool-2026-11-24)), and added **ask outcomes**,
batched, for the signals that have earned a question; the signals that are still noisy stay in
shadow and say so. It also added Copilot's session-start output shape and Amphion's and Zethus's
watched paths. Phase 1 and 2's visible behaviour is **opt-in** (`memory.mode: "active"`, else
`MNEMOSYNE_CAPTURE_MODE`), so the default stays shadow and a package upgrade changes nothing on its
own. **Phase 3** added context fingerprints (a context is a spec or ticket, Q5), standards (S7: a
lesson that recurs across contexts raises one "promote to standard?" question), promotion to the
shared tier or any store in `config.stores` (Q3), and config-default proposals, all in active mode
only ([§5.3](#53-phase-3-standards-and-the-exit-test-2026-11-24)). **Phase 4** built the shared core
and the installer over it ([§5.4](#54-phase-4-the-shared-core-and-what-of-the-stage-1-installer-existed)):
one source tree for the hook script, its registrations, the `memory` schema and the shared skills,
and each hook registering once however many kits install it. Still open: the §4.7 cells that
couldn't be checked from that host (VS Code, the Copilot cloud agent and Cursor), now including
Phase 2's Copilot output shapes there, and every installer path on a real Claude Code or Copilot.
**All eight questions are ruled** (2026-10-29). Seven went as recommended: Zethus and Amphion
stay two kits on a shared core (Q1); auto-store never stores the six excluded classes (Q2) and
never writes beyond the local tier (Q7); a standard is three occurrences across two or more specs
or tickets within 180 days (Q4, Q5); merging a review PR approves its lesson (Q6); and the engine
bugs are fixed first, as Phase 0 (Q8). Q3, the federation target, needed none of its options:
Mnemosyne's existing N-tier federation already answers it. No question blocks any phase, and
Phase 0 can start. See [Rulings](#rulings-2026-10-29).

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
  has **no** standard anywhere, and hooks are only partly shared. GitHub's docs say Copilot
  **drops the output of `userPromptSubmitted` hooks**. On a real Copilot CLI install that holds
  only for plain stdout: JSON `additionalContext` was injected and `modifiedPrompt` replaced the
  prompt ([§4.7.1](#471-hook-cells-checked-on-real-installs-2026-11-01)). So the Mnemosyne plugin's
  plain-text recall reaches the model on Claude Code but not on Copilot ([§3](#3-harness-convergence)).
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
| Hooks under Copilot, Codex or Cursor | **Untested** on 2026-10-29. Copilot CLI and Codex were checked on 2026-11-01; Cursor still can't be | [§4.7.1](#471-hook-cells-checked-on-real-installs-2026-11-01) |

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
| Zethus | [`zethus/com.github.copilot/agents/zethus.agent.md`](../zethus/com.github.copilot/agents/zethus.agent.md) | none | Stage table: recall on entering a stage; triage at stage 7 exit |
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
| Mnemosyne | [`mnemosyne/plugin/hooks/hooks.json`](../mnemosyne/plugin/hooks/hooks.json) | `SessionStart` (sync) and `UserPromptSubmit` (recall). Phase 0 has since added `PostToolUse`, `PostToolUseFailure`, `Stop` and `PreCompact`, all capturing in shadow mode | The capture hooks (§4.7) |

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
| Hooks, native | `settings.json` / plugin `hooks.json` [S1] | `.github/hooks/*.json` [S2]; the IntelliJ plugin also reads `~/.copilot/hooks` (§4.7) | `hooks.json` / `config.toml` [S4] | own `settings.json` events / `.agents/hooks.json` [S5] | `.cursor/hooks.json` [S9] |
| Reads Claude-format hooks | — | **CLI and VS Code: yes** (`.claude/settings*.json`); **cloud agent: no** [S2], [S6]. On a real CLI it **depends on the runtime**: 1.0.88 runs them, 1.0.106 loads them but never runs them ([§4.7.1](#471-hook-cells-checked-on-real-installs-2026-11-01)) | no [S4] | no [S5] | mapping of 8 events; the docs re-read on 2026-11-01 say it is **on by default** [S9] |
| Session-start context injection | yes | **yes**: `additionalContext` on `sessionStart` [S2]; confirmed on a real CLI | yes, Claude-shaped [S4]; confirmed on a real install | unverified | yes, `additional_context` [S9] |
| **Per-prompt context injection** | yes (`UserPromptSubmit`) | docs: **no**, "config-file `userPromptSubmitted` hooks have their output dropped" [S2]; VS Code: "command-hook output is ignored" [S6]. **On a real CLI, JSON `additionalContext` was injected**; plain stdout was dropped ([§4.7.1](#471-hook-cells-checked-on-real-installs-2026-11-01)) | yes [S4]; confirmed on a real install | unverified | no documented output [S9] |
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
| S7 | A lesson recurs: three occurrences across two or more contexts in the window, or a decision's question class and chosen option repeat across ADRs | engine, after a capture (`mnemosyne.standards`) | standard | **ask to promote** |
| S8 | `fresh-eyes-investigation` invoked (stuck twice) | post-tool hook on the skill / Zethus stage rule | lesson | **ask** at the next stage exit |
| S9 | An *As built* deviation is written to a spec | post-tool hook on a watched path | decision | **ask** |
| S10 | A friction-log entry with a workaround (Amphion `log-friction`) | post-tool hook on the watched path | process | **ask** |
| S11 | A `flag-or-fix` outcome other than "fix now" | post-tool hook on the PR body / spec path | decision | **ask** |
| S12 | A lesson recalled this session was overridden by the user | triage | supersede | **ask** (offer `--supersede`) |

**Watched paths** (S9–S11) are a config list, not code: the ADR directory, the spec directory, the
friction-log path. Any write the post-tool hook sees to one of them becomes a candidate carrying
the path and nothing else. Matching keywords in a prompt (S4, S5) gives cheap, explainable signals
with known false positives. That is why S5 asks instead of storing.

**Phase 2 changed the detection and the outcomes** ([§5.2](#52-tightened-detectors-measured-on-the-same-spool-2026-11-24)
has the measurement):

- **S4** no longer fires on the bare words *never* and *always*. It needs `remember to|that|this`,
  `from now on`, or *always* / *never* plus a verb at the start of a clause.
- **S5** no longer fires on *don't*, *do not* or *instead* wherever they appear. It needs `no,`
  opening the prompt, `that's wrong`, a clause that opens *don't <verb>*, or an imperative verb with
  *instead* in its clause.
- **S4 and S5 never fire inside a brief**: a prompt over 1,200 characters, with four or more list or
  heading lines, a fenced block, or a leading markup tag. Its imperatives are the brief's.
- **S6 skips** a watchdog kill (exit 124, 130, 137, 143), navigation and plain reads (`cd`, `ls`,
  `cat`, `sleep` and kin), a heredoc or quoting retry, and the same command re-run unchanged.
- **S9–S11 carry a kind** (`spec` S9, `friction` S10, `ledger` S11, `adr`), are one candidate per
  session and path, and take their paths from the kits' own config keys ([§4.7](#47-how-zethus-and-amphion-call-it-first-class)).
- **S12** is raised when a correction (S5) lands in a session whose recall digest listed lessons.
  The hook records the ids it printed, and nothing else, so the triage can offer `--supersede`.
- **Which signals ask.** S8 and S9–S11 are facts a hook saw, so they ask; they have no shadow data
  yet. S4, S5, S6 and S12 ask only after at least 10 of their candidates from the current detectors
  are labelled and half were worth a lesson, or when a project opts one in (`memory.ask.signals`);
  until then they are recorded and never asked. Candidates from before the tightening never count.

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
   trailer), a **config default**, so Zethus stops asking the question at all. **Built as a
   proposal**: an ADR (or a capture) names the key and value (`--config-key`, `--config-value`),
   and a promotion prints them as a JSON snippet to merge by hand. Nothing writes a config file.

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

**As built (Phase 3).** `mnemosyne.standards` holds all of it:

- **The reference** is, in order, an explicit spec or ticket id (`new-adr.py --spec`, `capture
  --spec`), a ticket key found in the branch name, then the branch itself. The hash is
  `sha256(salt, repo identity, reference)` cut to 16 hex digits. The repo identity is the origin URL
  without scheme, login or `.git`, else the folder name. The salt is `MNEMOSYNE_CONTEXT_SALT`, else a
  random per-memory-repo salt in the spool (`memory/.capture/salt`, which ignores itself). **Hashes
  compare only under one salt**: a team that wants one count across machines sets one value.
- **The lesson carries** `contexts` (`{ctx, date, signal[, stage][, k]}`, capped at 60; `k` hashes
  the candidate so one candidate counts once), and for a decision `decision: {class, option}`. A
  reinforce matches that pair first, folded for case and punctuation, and the similarity score
  second. Neither the spec id, the ticket nor the branch is ever written to a lesson by this path.
- **The question is raised once per lesson, ever** (`standards.raise_candidate`): any earlier S7
  candidate for it, answered or not, stops another, so a skip or "never ask about this kind" is
  final. It is raised after a `capture` or `reflect` that lands on a qualifying lesson, or by
  `mnemosyne standard scan`. A lesson already promoted, retired or proposed is not raised.
- **Active mode only.** In shadow mode (the default) `capture` records no fingerprint and reads no
  decision key from a candidate, and nothing raises S7. A decision class and option typed on the
  command line are always honoured.

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
| Standard, or an explicit share | a **store** (any declared in `config.stores`, e.g. `team`, `enterprise`) | `promote --to <tier>` → PR in the store repo, **after scrub** | PR review in the store |

**Sharing defined in Mnemosyne's terms:** a lesson is *shared* when it sits in a committed file of
any repo other than the developer's own gitignored local tier. Sharing therefore always means a
`promote` or `export`, always produces a PR, and always runs the scrub. Where it can go is
[Q3](#q3-federation-target), ruled (**Phase 3 builds it as `standard promote <id> --to <tier>`**,
offering the shared tier and every writable store, `memory.offerTier` first): the tiers Mnemosyne's federation already defines, which are
local, then the repo's shared tier, then any number of stores in `config.stores`, each its own
git repo with a distinct id prefix. The spec adds no default store of its own. **Nothing from
Ceryce's work may ever land in this repository**: its `mnemosyne/memory/` is a public demo store.

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
| **Provenance** | `spec_id`, ticket keys, branch names | Kept in local and shared tiers; **replaced by the context hash** when exporting to a store marked `scope: "external"`. **Built (Phase 3)**: the store's `scope` key is `internal` (default) or `external`, and an external export drops `spec_id`, `repo`, `anchors` and `reflection_of`, keeping `contexts` |
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

Each cell says what the mode uses on that host, then whether it was **checked** on a real install
(evidence E1–E5 in [§4.7.1](#471-hook-cells-checked-on-real-installs-2026-11-01)) or is
**unverified**, and why. The Copilot column is split, because only the CLI could be driven from
this host. The IntelliJ column has one known fact: where the plugin looks for hook files. Ceryce
read those from the plugin's own settings on 2026-11-01 (the page and its other locations are in
[Zethus's README](../zethus/README.md#which-copilot-clients-read-the-user-level-files)). Nothing has
been run there, so every mode cell in that column is unverified.

| Mode | Claude Code | Copilot CLI | VS Code (Copilot) | Copilot cloud agent | Codex | Cursor | IntelliJ (Copilot plugin) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Hook files read | `settings.json`, plugin `hooks.json` [S1] | `.github/hooks/*.json`. **Checked** (E2). User level **unverified** | `.github/hooks/*.json` [S2]. User level **unverified** | `.github/hooks/*.json` [S2]. User level **unverified** | `.codex/hooks.json`. **Checked** (E3). User level **unverified** | `.cursor/hooks.json` [S9]. User level **unverified** | `.github/hooks` and `~/.copilot/hooks`, plus any folder added in its settings. Source: Ceryce, from the plugin's own settings, 2026-11-01 |
| `session-start`: recall digest + pending count | `SessionStart` stdout. **Checked** (E1): plain stdout reached the model | `sessionStart` `additionalContext`. **Checked** (E2): JSON `additionalContext` reached the model; plain stdout did not | `sessionStart` `additionalContext`. **Unverified**: VS Code's agent can't be driven non-interactively | same, via `.github/hooks/*.json`. **Unverified**: needs a GitHub-hosted run | `SessionStart` `additionalContext`. **Checked** (E3): JSON and plain stdout both reached the model; it re-fires after each compaction | `sessionStart` `additional_context`. **Unverified**: `cursor-agent` isn't logged in (E4) | **Unverified**: nothing has been run under the plugin |
| `prompt`: S4/S5 detection, and recall where output is honoured | `UserPromptSubmit`, injects. **Checked** (E1, E5) | `userPromptSubmitted`. **Contradicts the docs** (E2): JSON `additionalContext` was injected and `modifiedPrompt` replaced the prompt; only plain stdout is dropped | `userPromptSubmitted`, side effect only per [S6]. **Unverified**, as above | same as the CLI. **Unverified**, as above | `UserPromptSubmit`, injects. **Checked** (E3): plain stdout and `additionalContext` | `beforeSubmitPrompt`. **Unverified** (E4); its docs list `continue`/`user_message` outputs but no context injection | **Unverified**: nothing has been run under the plugin |
| `post-tool`: S6, S8–S11 | `PostToolUse` + `PostToolUseFailure`. **Checked** (E1, E5): a failing command fires only `PostToolUseFailure` | `postToolUse`. **Checked** (E2, E5): fires for failures too; the exit code is only in the result text | `postToolUse`. **Unverified**, as above | `postToolUse`. **Unverified**, as above | `PostToolUse`. **Checked** (E3), but it carries **no failure indicator**, so S6 can't be seen, and `apply_patch` has no path field | `postToolUse`. **Unverified** (E4) | **Unverified**: nothing has been run under the plugin |
| `stop`: triage checkpoint | `Stop`: block once with "N candidates pending, triage them" (guarded by `stop_hook_active`). **Checked** (E1): blocks, and `stop_hook_active` is true on the re-fire | `agentStop`. **Checked, it can block** (E2): `{"decision":"block","reason":…}` forces another turn, with `stop_hook_active` on the re-fire | `agentStop`. **Unverified**, as above | `agentStop`. **Unverified**, as above; fallback is the next `session-start` | `Stop`. **Checked, it can block** (E3) with the JSON decision; on Windows the exit-2 form is lost | `stop`. **Unverified** (E4); its docs say it can't block, but a `followup_message` is submitted as the next user message | **Unverified**: nothing has been run under the plugin |
| `pre-compact`: flush the spool | `PreCompact`. **Checked** (E1), with a manual `/compact` | `preCompact`. **Checked** (E2), with a manual `/compact`; auto unverified | `preCompact`. **Unverified**, as above | auto-compaction only. **Unverified**, as above | `PreCompact`. **Checked** (E3), with forced auto-compaction | `preCompact`. **Unverified** (E4) | **Unverified**: nothing has been run under the plugin |

In Phase 0 every mode runs in **shadow mode** on every host: the bridge records candidates and logs
one decision per invocation, `stop` logs "would block" instead of blocking, and no capture mode
prints anything. So the output-shape cells above decide Phase 1 and 2 behaviour, not Phase 0's.

**Phase 2 output shapes (active mode only; shadow prints nothing new on any host).** The bridge
prints context in the shape the host injects:

| Host | `session-start` digest and pending count | `prompt` recall | `stop` block |
| --- | --- | --- | --- |
| Claude Code, Codex | plain stdout (E1, E3) | plain stdout (E1, E3) | `{"decision":"block","reason":…}` (E1, E3) |
| Copilot CLI | JSON `{"additionalContext": …}`, the form E2 saw injected; plain stdout was dropped | JSON `additionalContext`, as E2; in shadow mode plain stdout, as before | the same JSON decision from `agentStop` (E2) |
| VS Code (Copilot), Copilot cloud agent | **unverified.** Printed as the CLI's JSON when the event is recognised as Copilot, else plain | **unverified**; VS Code's docs say a prompt hook's output is ignored | **unverified** |
| Cursor, IntelliJ | not built; no registration yet | not built | not built |

Copilot is recognised by `COPILOT_CLI` in the environment, by the camelCase fields its events carry,
or by `--host copilot` / `--host copilot-cli`. No installer registration passes `--host`, because
one file serves the CLI, VS Code and the cloud agent. A VS Code or cloud event with none of those
cues gets plain stdout, which is harmless there and unverified. With both the repo's
Copilot hook file and the user's copy present, the double-fire guard lets one run print
and act: `tests/test_mnemosyne_capture_phase2.py` runs the bridge from both and sees one digest.
Which CLI runtime reads which file (E2: 1.0.88 ran the Claude-format file too, 1.0.106 did not) is
still the guard's job, not the registration's.

**The Copilot plugin is a third registration of the same bridge.** `mnemosyne@mesmer-grimoire`
(`com.github.copilot/hooks/hooks.json` in the plugin) ran on Copilot CLI 1.0.105 and 1.0.106-2,
with a local marketplace and a temporary `COPILOT_HOME`, and each event fired once: `sessionStart`,
`userPromptSubmitted`, `postToolUse` and `agentStop` were observed, and `preCompact` was not run.
With the plugin, `.github/hooks` and `$COPILOT_HOME/hooks` all present, both runtimes ran all three
registrations of every event. The engine's claim let one through and logged two as `duplicate`.
That is the Phase 2 exit criterion on a real host, and the first evidence that the CLI reads the
user-level folder. The Claude file beside the plugin's did not fire, so it stays Claude Code's.
`install.py --user` skips the user file when it finds the plugin; the guard is what holds where it
can't see one.

Registration lives in one neutral file: Claude-format `hooks.json` in the shared core's plugin. It is read
as-is by Claude Code, Copilot CLI and VS Code (from `.claude/settings.json` in repo installs), and
by Cursor if opted in. A Copilot-format copy under `.github/hooks/*.json` covers the cloud agent,
installed **only** when the repo doesn't already carry the Claude file, so the CLI never fires
twice. Codex gets its own `hooks.json`. Gemini and Antigravity are out of scope until asked.
**The real CLI breaks the first assumption** (E2): the default Copilot CLI runtime (1.0.106) loads
`.claude/settings.json` hooks but never runs them, and the bundled 1.0.88 runs them *and* any
`.github/hooks` copy, so the same event fires twice. Phase 2 has to choose registration per CLI
runtime, not per surface.

**A user-level Copilot copy** in `~/.copilot/hooks` (`install.py --user`) has the same format, but
names the script by absolute path, because it fires in repos that have no bridge of their own. A
repo may also commit its own `.github/hooks/*.json` copy, and the installer can't know which do, so
registration alone can't keep each event to one run. The engine does that instead: the first run
claims the event with an exclusive marker keyed on the session and the event's normalized content,
and the second logs `duplicate` and stops (`mnemosyne.candidates`). Normalizing means a
Claude-format and a Copilot-format run of one event also match, which is the 1.0.88 case above.
This is tested by running the bridge twice, not on a host: no host has yet been seen loading both
files.

**Hook rules, from the Morpheus retrospective:**

- Hooks only append to the spool and exit (and refresh the spool's read index, a cache: see "Spool
  read cost" below). No git, no network, no model, no lock on the store. Each is bounded at 200 ms.
- Every hook writes one log line per decision. A `mnemosyne doctor` command shows the last N
  decisions, so a fail-open hook never fails silently.
- Every guard is tested with the variable set the way the host sets it.

**Spool read cost.** `stop`, `pre-compact` and `session-start` count pending and untriaged
candidates, so they fold the spool, and parsing every line of a 13,490-line spool took over 150 ms
(§5.2 measured about 0.3 s). They read it through an index instead: `index.bin` beside the spool
holds the slim rows folded so far (the fields the rules read, as lists) and the byte offset they end
at, so a run parses only the lines appended since. The index is a cache of a fold, never a source
of truth, and it is rebuilt from the spool whenever it can't be trusted:

- **Missing, damaged or foreign:** a checksum on the payload, a version and the Python's marshal
  format are checked before anything is decoded. Any failure folds the whole spool and writes a
  fresh index. A read that fails for any reason at all falls back to the whole read, so a hook
  never fails on the index (fail-open).
- **S7 through the index:** an S7 stays in scope on every branch of its project, so the slim row keeps
  the signal, repo and branch that rule reads, and a hook's count equals the full read's. `context.ref`
  and `context.ctx` (an S1's work) are not in the row: they are read from the full fold when a capture
  needs them. A change to the row's shape bumps the index version.
- **The spool changed under it:** the offset must still be inside the file, the hash of the file's
  first and last 4 KiB (up to that offset) must match, and, when nothing was appended, so must the
  modification time. A spool that shrank, was archived, or lost a line is read whole. The one
  edit this can't see is one that keeps the size, the first and last 4 KiB and the modification
  time; delete `index.bin` after hand-editing the middle of a spool.
- **A torn last line:** only complete lines (up to the last newline) are indexed. A line still
  being written, or one whose newline hasn't landed, counts for that run but is never indexed, so
  it is counted once when it completes and not at all if it is withdrawn.
- **Concurrent hooks:** no lock. Each run writes the index for the offset it reached, to a temp
  file in the same directory and then renames it, so a reader sees the old index or the new one.
  The last rename wins, and an older index is still valid, just behind: the next run reads the
  difference. On Windows a rename onto an index another run has open is refused; the run that
  loses it leaves the work to the next, and costs nothing else.
- **Same answers:** `tests/test_mnemosyne_spool_index.py` compares the hook's read with the full
  read (`_fold`, `untriaged`) after appends, labels, resolutions, deletions, a truncated last line,
  a damaged index and racing hooks. The rules themselves are shared, not copied (`_pool_rows`).

Measured on the same 13,490-line synthetic spool, 30 cold runs each, back to back on one machine
(Windows, Python 3.14, a busy desktop, so the absolute numbers are loose): the hook body, which is
what the 200 ms bound covers, went from p50 164–179 ms (p95 216–236) at `stop` to p50 21 ms (p95
32–59), and at `session-start` from p50 167–185 ms (p95 225–229) to p50 22 ms (p95 30–36). A whole
`stop` invocation, interpreter start-up included, went from p50 330–348 ms to 168–176 ms, and a
whole `session-start` (which reads the spool twice, once to capture and once for the digest) from
512–561 ms to 188–204 ms. At 50,000 lines the body is p50 about 110–200 ms with a p95 past the
bound on that machine, so the index buys roughly a fourfold margin, not an unbounded one;
archiving old lines remains the answer to a spool that large.

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
  "mode": "shadow",
  "repo": "",
  "autoStore": { "signals": ["adr", "gate-red-green", "explicit-remember"], "perSession": 5 },
  "ask": { "signals": [] },
  "watch": ["docs/adr/", "docs/specs/", "docs/friction-log.md"],
  "standard": { "minOccurrences": 3, "minContexts": 2, "windowDays": 180 },
  "offerTier": ""
}
```

`mode` is `shadow` (the default) or `active`. `ask.signals` opts a signal that is still in shadow
into asking ([§4.2](#42-how-the-agent-identifies-one-in-session)); a name or an id works. `watch`
entries are paths, globs or `{"path", "kind"}`. **Left out, `watch` comes from the kits' own keys**:
Zethus's `spec.dir` and `adr.dir`, and Amphion's `frictionLog.markdown.path` (only when its sink is
markdown) and `ledger.path`, so neither kit repeats a path it already names. A kind the config
doesn't name keeps its conventional default. `autoStore.signals` lists `explicit-remember` for
forward compatibility only: auto-store takes S1 and S2 whatever it says.

`offerTier` names the tier the agent suggests first when it asks to share: `shared`, or a store
declared in `config.stores`. Empty, the default, means it suggests none and offers every tier the
repo's federation reaches ([Q3](#q3-federation-target), ruled).

#### 4.7.1 Hook cells checked on real installs (2026-11-01)

Everything here ran on Windows 10 with Python 3.14, in scratch projects outside any repo, and no
user-global hook file was edited. Two hosts wrote global files of their own, and both were reverted
afterwards:

- Codex added a project-trust entry to its `config.toml`.
- Copilot created a `settings.json` during an `--experimental` run.

Each run used a cheap model (Claude Haiku on Claude Code and Copilot, `gpt-5.6-luna` at low effort
on Codex).

There were two kinds of run:

- **Probe runs (E1–E3):** a probe hook that logged each event's stdin and could print or block on
  cue.
- **Bridge runs (E5):** the real `mnemosyne_hook.py`.

Context injection was tested with an unguessable codeword printed by the hook. The model was then
asked to repeat any codeword in its context.

**E1. Claude Code 2.1.309**, run with `claude -p --setting-sources project,local --settings <file>`,
so the user's own hooks didn't load.

- **`SessionStart`:** plain stdout reached the model. It fires with `source` `startup`, `resume` and
  `compact`.
- **`UserPromptSubmit`:** stdout reached the model. The prompt is in `prompt`.
- **Tool hooks:**
  - A successful Bash call fires `PostToolUse`. Its `tool_response` has `stdout`, `stderr` and
    `interrupted`, but no exit code.
  - A failing call (exit 3) fires **only** `PostToolUseFailure`, with `error: "Exit code 3\n…"`.
  - Write and Edit put the path in `tool_input.file_path`. A Skill call puts the skill's name in
    `tool_input.skill`.
- **`Stop`:** `{"decision":"block","reason":…}` made the model continue. The reason arrived as
  "Stop hook feedback". The re-fired event had `stop_hook_active: true`.
- **`PreCompact`:** fired on `claude -p "/compact" --resume <id>` with `trigger: "manual"`.
- **Environment:** Claude Code sets `CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT` and `CLAUDE_PROJECT_DIR`
  for hooks.
- **Errors and timeouts:** a hook's nonzero exit or timeout shows up only in the debug log and the
  `stream-json` hook events. The run carries on.

**E2. Copilot CLI**, reporting `copilot --version` 1.0.89-3. By default it runs a newer cached
runtime, **1.0.106-2**; with `--no-auto-update` it runs the bundled **1.0.88**. Hooks went in
`.github/hooks/*.json`.

- **Trust gate:** in `-p` mode, repo hooks load only when the folder is trusted or
  `COPILOT_ALLOW_ALL=true`. `--allow-all-tools` alone loaded none.
- **`sessionStart`:** JSON `additionalContext` reached the model on both runtimes. Plain stdout did
  not.
- **`userPromptSubmitted`:** the prompt is in `prompt`. JSON `additionalContext` was injected (as a
  system reminder), and `modifiedPrompt` **replaced the prompt the model saw**, on both runtimes.
  Plain stdout was dropped. This **contradicts** the docs' "output dropped" [S2].
- **`postToolUse`:**
  - It fires for a failing command too, with `toolResult.resultType` still `"success"`. The only
    failure signal is the trailer `<shellId: N completed with exit code 128>` in
    `toolResult.textResultForLlm`. `postToolUseFailure` never fired.
  - `toolArgs` is an object. The file path is `toolArgs.path`. Tool names were `powershell`,
    `create` and `edit`.
- **`agentStop` can block:** `{"decision":"block","reason":…}` delivered the reason as a queued
  user message, and the model acted on it. The re-fired event had `stop_hook_active: true`.
- **`preCompact`:** fired on a manual `/compact` after `--resume`, with `trigger: "manual"`. Auto
  compaction was not tested.
- **Claude-format hooks depend on the runtime:**
  - On **1.0.88**, `.claude/settings.json` hooks ran with snake_case stdin and Claude tool names
    (`powershell` became `Bash`). With a `.github/hooks` copy as well, the same event fired twice.
  - On **1.0.106**, the `.claude/settings.json` hooks were counted at load but never ran. PascalCase
    event names inside `.github/hooks/*.json` did run, with snake_case stdin.
- **Environment:** Copilot sets `COPILOT_CLI` and also `CLAUDE_PROJECT_DIR`. So
  `CLAUDE_PROJECT_DIR` doesn't identify Claude Code.

**E3. Codex CLI 0.159.2**, run with `codex exec --dangerously-bypass-hook-trust --ephemeral` and a
project `.codex/hooks.json`. Its Windows sandbox made every shell call fail to start, so these runs
used full access in the scratch project.

- **`SessionStart` and `UserPromptSubmit`:** both plain stdout and JSON `additionalContext`
  reached the model. `SessionStart` fires again (`source: "compact"`) after every compaction.
- **`PostToolUse`:**
  - Shell commands arrive as `tool_name: "Bash"` with `tool_input.command`. `tool_response` is only
    the output text: no exit code and no failure flag.
  - `apply_patch` has no path field. The path is only in the patch's `*** Update File:` lines.
  - A failed `apply_patch` fired no `PostToolUse` at all.
- **`Stop` can block:** the JSON decision forced another model pass, and `stop_hook_active` was
  true on the re-fire. Exit code 2 also blocks, but only if the command ends `; exit
  $LASTEXITCODE`. Codex runs every hook as `pwsh -NoProfile -Command "<command>"`, and pwsh turns a
  native exit 2 into 1. Without that ending, a blocking exit is silently ignored.
- **`PreCompact`:** fired on auto compaction, forced with `-c model_auto_compact_token_limit=3000`.
- **Environment:** Codex adds no variable of its own and passes its parent's environment through.
  Host detection must therefore come from the event's shape (`turn_id`), not from the environment.

**E4. Cursor:** nothing could be run. `cursor-agent` (2026.06.24) reports `Not logged in`, and
logging in needs an interactive browser flow. Its docs, re-read on 2026-11-01, say:

- `stop` cannot block, but a non-empty `followup_message` is submitted as the next user message,
  with `loop_count` and `loop_limit` as the guard;
- `beforeSubmitPrompt` can block a prompt (`continue`, `user_message`) but not add context;
- `preCompact` is observational;
- Claude-format hooks are loaded **by default** ("Include Third-Party Plugins…" is on).

All of this is docs only, still unverified.

**E5. The real bridge, end to end, on Claude Code 2.1.309 and Copilot CLI 1.0.106-2.**

- **Setup:** each host got the bridge registered for every mode, a scratch project on branch
  `feat/e2e-demo`, and a scratch memory repo. The prompt said "from now on", ran a failing
  `git rev-parse --verify no-such-ref`, then a passing `git rev-parse HEAD`, then created a spec
  file, demo.md, in the project's docs/specs.
- **Result:** both hosts recorded the same three candidates (S4, S6 with `failed_exit` 128, and
  S9–S11 for the spec file). Both logged `would-block` at stop, printed nothing, and wrote no
  `local.jsonl`.
- **Timing:** hook bodies took 1–38 ms. A whole invocation took 143–164 ms median on this machine:
  about 58 ms is interpreter start-up and about 90 ms importing the package, both standard-library
  cost. That is inside the 200 ms bound, but with little headroom.

**E6. `session-start` against a git memory repo (2026-11-01).** The Mnemosyne install job
measured the session-start hook at about 730 ms with a memory repo that was a git repo, against
about 350 ms without git. A re-run on the same machine timed the bridge 15 times against each kind
of temp memory repo, using a fresh `mnemosyne init`, with and without `git init` plus one commit,
and no remote:

| Memory repo | Median before | Median after |
| --- | --- | --- |
| Plain folder | 354 ms | 148 ms |
| Git repo, no remote | 658 ms | 147 ms |

- **Cause:** the mode ran `sync`, which spawns about ten git children (`pull`, `fetch`,
  `rev-parse`, `show`, …) even when there is nothing to pull. Each one fails or finds nothing.
- **Fix:** the bridge now asks `core.sync_has_work` first. That reads the git config from disk to
  see whether the repo has a remote, and checks the config for any store; no git child runs. With
  neither, `sync` is skipped.
- **Cost that remains:** a memory repo with a remote still pays for `sync` at every session start.
  Moving that out of the hook is the hook rule above ("No git"); it hasn't been done yet.

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
| Candidate spool beside the local tier (gitignored) with `candidate add/list/triage/dismiss`. **Built in Phase 0, shadow mode:** it lives in a `.capture` directory under the memory repo's `memory/`. That directory ignores itself, so a memory repo whose `.gitignore` predates it can't commit it. It has `candidate add/list/label/stats`; `label` records whether a candidate was worth a lesson, which is the precision data Phase 0 needs. `triage` and `dismiss` come with Phase 1 | §4.2 | M |
| Context fingerprints on reinforce, and the `standard` marker. **Built in Phase 3** (`mnemosyne.standards`, `core.add_context`, `core.find_decision_match`, the `standard` commands, `core.export(shape=…)`) | §4.4 | S–M |
| `retire <id> --reason` and `doctor`. **`doctor` built in Phase 0**: it shows the last N hook decisions, counts and the slowest hook body. `retire` comes with Phase 1 | §4.3, §4.7 | S |
| The bridge grows `post-tool`, `stop` and `pre-compact` modes, plus per-host output shapes. **The modes are built in Phase 0, shadow only**: they read every host's field names (§4.7.1) but print nothing. The output shapes come with Phase 1 and 2 | §4.7 | M |

### 4.9 Out of scope

- **Transcript mining or "dreaming".** That was Morpheus, and it was retired for good reasons.
- **Writing into a host's native memory** (Claude auto memory, Copilot Memory, Codex memories).
  A second writer races the native one ([retrospective](morpheus-retrospective.md#why-it-was-retired-rather-than-fixed)).
- **Vector recall.** The lexical scorer is fine for procedural rules, and the design doc already
  names the upgrade path.
- **Gemini CLI and Antigravity hook adapters**, until a user needs them.
- **Building the shared core.** Q1 chose it, and it is Phase 4; Phases 0–3 don't wait on it.
  Fusing the kits is not planned at all. (Built in Phase 4, [§5.4](#54-phase-4-the-shared-core-and-what-of-the-stage-1-installer-existed).)

---

## 5. Phases

Sizes follow stage 1: S is under half a day, M is half a day to two days, L is two to five days.

| Phase | What | Behaviour change | Exit, verified by | Size |
| --- | --- | --- | --- | --- |
| **0** | Engine fixes B1–B6 before any capture (Q8, ruled), with tests that fail before each fix. B4 is fixed as merged-means-approved (Q6); B6 is the scrub (§4.6) and the author fallback. Candidate spool and hooks in **shadow mode**: they record candidates and log decisions, but store nothing and ask nothing. Verify the unverified hook cells in §4.7 on real installs. **Built:** B1–B6 (PR #46); the spool, `doctor` and the bridge's capture modes, which detect S4–S6, S8 and S9–S11 (`tests/test_mnemosyne_capture.py`); hook cells checked on Claude Code, Copilot CLI and Codex (§4.7.1); the week of shadow data collected and read (§5.1). **Open:** VS Code, the cloud agent and Cursor | Bug fixes only; capture is observe-only | An MCP tool-call test green on Windows and Linux; an id-collision test; a merged review PR retires its local original with no hand edit; an export carrying a home-directory path or a login as author is blocked; one week of spool data showing the count and precision of each signal (`mnemosyne candidate stats`, after labelling with `candidate label`) | M–L |
| **1** | Auto-store for S1 (ADR) and S2 (gate red → green) through Zethus's scripts. `session-start` recall digest. Claude Code `stop` triage of pending candidates through the `lessons-triage` skill. Local tier only (Q7). The Q2 exclusions hold from here: an S1 or S2 candidate in an excluded class is asked at the same triage, never saved. **Built:** `new-adr.py` emits S1 and `run-local-gates.py` emits S2 (`mnemosyne.candidates.record_adr` / `record_gate_results`, fail-open); `capture --captured-by hook:<signal> --candidate <id>` with the engine's Q2 refusals (security / supersede / non-local / secret) + confidence pinned to medium; `candidate triage` / `candidate resolve`, `retire`; the bridge's active-mode `session-start` digest and `stop` block; the `lessons-triage` skill; opt-in via `memory.mode: "active"`. Tests: `tests/test_mnemosyne_capture.py` (Phase1* classes), `tests/test_zethus_lessons_capture.py` | Yes: auto-store to local, one triage checkpoint | A Zethus run that records an ADR and fixes a red gate ends with two `SAVED:` lines and an empty spool; `retire` undoes either; no write outside `local.jsonl`; a `security` ADR is asked, not saved, and the engine refuses it as a hook capture | M |
| 2 | Ask outcomes (S4–S6, S8–S12), batched; Copilot `sessionStart` and `.github/hooks/*.json`; Amphion watched paths. **First, tighten detection** (§5.1) and measure it on the shadow spool. **Built:** the tightened S4/S5/S6 detectors and the brief gate (`mnemosyne.detect`); measurement in §5.2; per-signal ask status (S8 and S9–S11 ask, S4/S5/S6/S12 stay in shadow until labelled precision earns them a question, or a project opts in); negative fingerprints and "never ask about this kind"; S12 from recalled ids; one batched question set (`candidate triage --format json`, `--numbered`); S9–S11 kinds, once per session and path; watched paths from Zethus's and Amphion's own keys; Copilot's JSON `additionalContext` for session-start and prompt in active mode; the double-fire guard (§4.7) also holds the digest to one print. Tests: `tests/test_mnemosyne_capture_phase2.py`. **Not seen on a real host:** VS Code, the Copilot cloud agent, and the `agentStop` block with these changes (it was seen in E2 with the Phase 1 reason text) | Yes, opt-in | Triage on Copilot CLI and VS Code; no double-fire with both files present. **Met in tests** (one digest from two files); **not met on a host**: no VS Code run, and the CLI was not driven again in this phase | M |
| 3 | Context fingerprints (a context is a spec or ticket, Q5), standards (S7), promotion to shared or store, and config-default proposals. Promotion targets the tiers Mnemosyne's federation already has: the shared tier or any store in `config.stores` (Q3, ruled). **Built:** `mnemosyne.standards`; fingerprints on capture and reinforce; the decision-key match; `new-adr.py --question-class/--option/--spec/--config-key/--config-value` and two ADR template rows; S7 raised once per lesson and asked in the batched set with one option per tier; `standard list/scan/promote/config`; a store `scope` of `internal` or `external`; the opt-in gate (active mode only). Tests: `tests/test_mnemosyne_standards.py` | Yes, opt-in | Three ADRs with the same answer across two specs produce exactly one "promote to standard?" question; three in one spec produce none (Q4). **Met**, end to end through `new-adr.py`, `capture --candidate` and `candidate triage` ([§5.3](#53-phase-3-standards-and-the-exit-test-2026-11-24)) | M |
| 4 | The shared core (Q1, ruled), inside the stage 1 installer: one source tree for the memory hook script and its `hooks.json`, the `memory` config schema, and the shared skills. Zethus and Amphion each install from it and keep their own names, READMEs and install paths. **Built toward it (2026-11-01):** Mnemosyne has its own installer, `mnemosyne/install.py`. It sets up the package, a local git memory repo (`~/repos/mnemosyne-local` by default, no remote), a persistent `MNEMOSYNE_REPO`, the Claude Code plugin through a local marketplace, and, with `--target`, a Copilot `.github/hooks/*.json` file (`mnemosyne.json`) generated from the plugin's `hooks.json`, so registration keeps one source; `--user` writes the same file to `~/.copilot/hooks`. `zethus/install.py --with-mnemosyne` calls it rather than copying it (`tests/test_mnemosyne_install.py`, `tests/test_zethus.py`). **Built (2026-11-25):** the shared core (`core/`), `catalog.json`, the root `install.py` (install and uninstall for Claude Code and Copilot, user and repo scope, `--check`, `--list`, `--sync-core`), Amphion's installer, `zethus/install.py --with-core`, and the stage 1 §3.4 CI additions ([§5.4](#54-phase-4-the-shared-core-and-what-of-the-stage-1-installer-existed)). **Open:** Codex and Cursor, and every installer path on a real host | Packaging | Stage 1 §3.4 CI additions green; installing both kits registers each hook once; `tests/test_zethus.py` green. **Met in tests and CI** (temp dirs, fakes for pip, `claude` and the registry); **not met on a real host** | M, on top of the stage 1 installer |

Phase 0 deliberately ships no capture. Building capture on an engine that loses lessons on merge
(B2) would bank data straight into the bug, which is why Q8 ruled the fixes first. And the signal
table in §4.2 is a hypothesis about precision: a week of shadow data is cheaper than tuning
auto-store against real lessons. Phase 0 is M–L rather than M because the scrub (B6, M) moved into
it from Phase 1.

### 5.1 Shadow-week result (2026-11-24)

The spool ran in shadow mode on one developer's machine from 2026-11-01 to 2026-11-24 across a real
multi-project workload, recording **13,283 candidates**. Only the hook-detected signals appeared —
**S4 5,657, S5 6,465, S6 1,161** — and **no S1 or S2 at all**, because those come from Zethus's
scripts and Zethus was not installed on that machine, so the week measured the keyword signals, not
the script ones. Read by hand (sampling across the month; nothing was labelled in the live spool,
which stayed read-only):

- **S4 (explicit-remember):** ~97% matched the bare word *never*, almost all of it standing agent
  instructions re-fired each session and ordinary prose, not a user asking to remember a new
  convention. Precision for a worthwhile new lesson is in the low single digits.
- **S5 (correction):** dominated by *do not* / *don't* inside standing instructions and task
  briefs, not a mid-task correction of the agent. Similarly low.
- **S6 (fail-then-succeed):** of 1,161, ~410 were a watchdog kill of a long-running command
  (exit 143/137/124), ~414 were `cd` / `ls` / `sleep` navigation retries, and of the rest ~140 were
  heredoc / quoting retries; genuine, generalisable mistake-fixes were a small minority.

**What it supports.** The keyword signals are too noisy to auto-store, which is exactly why Phase 1
auto-stores **only S1 and S2** — deterministic facts emitted by a script (an ADR genuinely recorded;
a named gate that genuinely went red then green), gated at triage by the agent and the Q2 refusals —
and routes S4/S5/S6 to *ask*. S1 and S2 have no shadow precision number here because the environment
that emits them was never installed; a short Zethus-side shadow run should measure them before any
later phase widens auto-store. S4 stays at *ask* until its detection is tightened (drop the bare
*never* / *always*; require an imperative shape), tracked for Phase 2.

### 5.2 Tightened detectors, measured on the same spool (2026-11-24)

Phase 2 tightened the detectors first ([§4.2](#42-how-the-agent-identifies-one-in-session)), then
measured them on the same shadow spool, read-only. Every figure below is a count or a hand-read
tally; no candidate text, prompt or path from the spool appears in this repo.

**Method.** The live spool was copied once to a scratch folder and every step ran on the copy
(`mnemosyne candidate stats`, `candidate label`, `doctor`; the live spool got `stats` and `doctor`
only, which write nothing). The copy held 13,490 candidates from 2026-11-01 to 2026-11-24 across
4,618 sessions: S4 5,738, S5 6,541, S6 1,203 and S1 8. The new detectors were replayed over what
the spool kept. For S4 and S5 that is the candidate's excerpt, the matched phrase with about 60
characters either side, because the spool never held the whole prompt (by design). For S6 it is the
command head and the failed exit code. Hand-read means one reader's judgement of whether a sampled
candidate was a person teaching the agent something durable, or for S6 whether its pointers show a
retry whose fix could generalise. Samples were uniform random, 30 per cell.

**What the replay cannot see.** The brief gate needs the whole prompt's length and structure,
which the spool does not hold, so it is **not replayed**. Stage A below is the shape rules plus the
existing per-session duplicate guard, and over-counts what the gate will keep. As a proxy for the
gate, stage B counts survivors whose directive opens the prompt (the excerpt has no leading
ellipsis), which are the most likely to be a person's own words. Unreplayable is also the S6 heredoc
and quoting rule, and the unchanged-re-run rule, which need the command text; the replay applied
the heredoc rule only where the head still showed it (24 of them).

| Signal | Phase 0 detector (all) | Stage A: shape rules + duplicate guard | Stage B: directive opens the prompt |
| --- | --- | --- | --- |
| S4 explicit-remember | 5,738 | **3,758** (−35%) | **2** |
| S5 correction | 6,541 | **3,702** (−43%) | **7** |
| S6 fail-then-succeed | 1,203 | **186** (−85%): 428 watchdog kills, 565 navigation or reads, 24 heredoc | not applicable |

**Hand-read precision** (worthwhile / read):

| Signal | Before (Phase 0) | After, stage A | After, stage B |
| --- | --- | --- | --- |
| S4 | 0 / 30 | 0 / 30 | 0 / 2 (a test probe and a fragment of a brief) |
| S5 | 0 / 30 | 0 / 30 | 3 / 7 (the other four were one probe prompt repeated across sessions) |
| S6 | 2 / 30 | 9 / 30 | not applicable |

**How to read them.**

- **S4 and S5: the keyword shapes alone were not the problem, the briefs were.** Every one of the 60
  stage A survivors read was a fragment of a task brief or a standing instruction re-fired inside
  one. The brief gate is built to drop exactly those, but that is an expectation: the gate could not
  be replayed (above), so the measured claim stops at stage A. Only 9 of 7,460 survivors open the
  prompt with the directive, and the 3 that were a person correcting the agent are the only
  precision signal the spool holds: 3 of 7, and 0 of 2 for S4. That is too few to certify either
  signal, so **S4 and S5 stay in shadow**.
- **S6: the precision is an upper bound.** The spool keeps a command head and an exit code, not the
  command, so "worthwhile" here means "a named tool command (`git`, `gh`, a package manager) that
  failed and passed", and the 9 of 30 counts every one of those. Most survivors are a person's own
  throwaway script run again after an edit. 0.30 is below the 0.5 bar even as an upper bound, so
  **S6 stays in shadow**.
- **S12 has no shadow data at all** (it needs a recall in the session and a correction after it),
  and rests on S5, so it stays in shadow too.
- **S8 and S9–S11 have no shadow data either**: they come from the Zethus-side hooks and watched
  paths this machine never had. They ask from the start and are marked **unmeasured**. Measure
  them with `candidate label` before relying on them; the status in `mnemosyne doctor` switches
  nothing by itself for these.
- **The labelling bar is built in.** A shadow signal moves to ask when at least 10 of its
  candidates from the current detectors are labelled and at least half were worth a lesson
  (`mnemosyne candidate stats --current`). The spool's own labels will decide S5 first.
- **Cost.** Reading the whole spool at `stop` and `session-start` took about 0.3 s on these 13,490
  lines, over the 200 ms body bound (§4.7). That is fixed: the hooks read the spool through an
  index and a body now takes about 20 ms on the same size (§4.7, "Spool read cost"). Archiving old
  lines is still not built, and the index doesn't need it at this size.

Nothing was labelled on the live spool, and no hook, config or plugin on the machine was touched.

### 5.3 Phase 3: standards, and the exit test (2026-11-24)

**The exit test** is `TestExitCriterion` in `tests/test_mnemosyne_standards.py`. It drives the real
pieces in a scratch memory repo: Zethus's `new-adr.py` (a subprocess) records each ADR with
`--question-class "merge strategy" --option "merge commits" --spec <id>`; `mnemosyne capture
--captured-by hook:S1 --candidate <id>` stores it, with three different wordings; `mnemosyne candidate
triage --format json` is read for S7 questions.

| Case | Result |
| --- | --- |
| Three ADRs, one answer, specs A, A, B | After two: no question. After the third: the capture prints `STANDARD?`, and triage has **exactly one** S7 question, with options `promote:shared`, `skip`, `never`. One lesson, `reinforced` 2, three fingerprints over two distinct hashes. A fourth ADR in a third spec, or `standard scan`, raises no second one |
| Three ADRs, one answer, all in spec A | **No question**, however often triage or `scan` runs. One lesson, three fingerprints, one distinct hash; `standard list` says `3 occurrences / 1 context`, below the rule |
| A skip | Final: two more occurrences in two more specs raise nothing |

The same file covers the rest: the window and `memory.standard` thresholds; the reference order
(spec, then a ticket key in the branch, then the branch) and the salted, stable hash; no spec,
ticket or branch name on a lesson; promotion to the shared tier (a review branch whose copy is a
procedural `convention` at high confidence with the `standard` marker, the local original kept and
unmarked) and to a configured store, internal and external; `offerTier` ordering with a read-only
store left out; a config-default proposal that is printed and never written; and shadow mode, where
`capture` records no fingerprint and nothing raises S7.

**Not verified.**

- **No real host.** The question set, its numbered form and the `standard promote` answer were run
  through the CLI, not through a Claude Code or Copilot session: the Stop block, the host's question
  tool and `lessons-triage` following the new S7 section are unobserved.
- **Counting across machines.** Hashes compare only under one salt. Two developers who each keep the
  default per-repo salt will not recognise one another's contexts, so a store that gathers promoted
  standards from several people would count each of their hashes as distinct. Setting
  `MNEMOSYNE_CONTEXT_SALT` to one value fixes it; nothing checks that they did.
- **The shared tier is not re-offered.** Only a local lesson is promoted, so a recurring lesson that
  already sits in a committed tier is not raised, and a lesson promoted to the shared tier cannot
  later be offered to a store. That would need an in-place edit of a committed file, which no phase
  has built.
- **Real-spool precision.** There are no S7 candidates on any real spool, so nothing says how often
  a raised S7 is worth a promotion. It asks from the start, like S8 and S9–S11, and is unmeasured.
- **Config proposals are by hand.** The key and value come from the ADR author; the engine checks
  only that the key is a dotted name and the value carries no credential shape. Whether the key
  exists in a kit's config is not checked.
- **`validate` on an auto-captured lesson.** A capture with no tags has an empty `trigger`, which
  `validate` reports as a missing required field. That is older than this phase and is untouched.

### 5.4 Phase 4: the shared core, and what of the stage 1 installer existed

**What existed before this phase** (checked against `origin/develop` at `aa808db`, 2026-11-25), and
what Phase 4 did about each:

| Stage 1 piece | Before | Phase 4 |
| --- | --- | --- |
| §3.2 root `install.py`, `--platform`, `--bundle`, `--list`, `--check` | **Absent.** No root installer | Built: `install.py`, with `--check`, `--list` and `--sync-core` first |
| §3.1 `catalog.json` | **Absent** | Built: `catalog.json` (bundles, what each needs, hosts, the marketplace entries) |
| §3.2 generalised engine: manifest, SHA check, foreign-file protection, conflict handling, dry run, prune | **Exists, Copilot-only,** in `zethus/install.py` (user scope: manifest and uninstall; repo scope: neither) | Kept as it is and **called**, not copied |
| Package, memory repo, `MNEMOSYNE_REPO`, Claude plugin, Copilot hook files | **Exists** in `mnemosyne/install.py` (user and `--target`; manifest; uninstall) | Kept as it is and **called**, not copied |
| §3.3 marketplaces | **Exists:** `.claude-plugin/marketplace.json` (Amphion, Mnemosyne) and `.github/plugin/marketplace.json` (Zethus, Mnemosyne) | Kept. `install.py --check` now holds them to the catalog and the plugin manifests |
| Amphion's installer | **Absent.** Amphion was a plugin, or `cp -r` | Built, on the new root installer |
| §3.4 CI: `install.py --check` | Absent | Built, a blocking CI step |
| §3.4 CI: skill frontmatter lint | **Partly.** `tests/test_frontmatter.py` proved every file parses, `tests/test_zethus.py` held Zethus's names and lengths | Built for every skill in the repo: `tests/test_skill_rules.py`, its own CI step |
| §3.4 CI: doc-pointer check | **Exists** (`scripts/check_doc_pointers.py`, blocking) | Unchanged; `core/skills` joins its example-docs list |
| §3.4 CI: a dry run of `--platform all --user` and `--target` into a temp directory, on Linux and Windows | Absent | Built, with the installer |
| Codex and Cursor strategies, their manifests, §3.1 neutral agent and instruction layout, the platforms reference doc, the shims | Absent | **Not built.** They are stage 2's host port (D7), not Phase 4; a Codex or Cursor `--platform` is refused until they are |

**The shared core.** `core/` is the one source tree ([`core/README.md`](../core/README.md)): the memory
hook script, its Claude-format and Copilot-format registrations, `memory.schema.json` and the skills
both kits use (`flag-or-fix`, `resume-interrupted-phase`, the general `pr-description`).

- **Copies, not references.** A plugin installed from a marketplace is copied on its own, so
  `mnemosyne/plugin/` and `amphion/plugin/` cannot point out of their folders. They carry byte copies
  of the core's files, listed under `core.mirrors` in the catalog and held in step by `install.py
  --check`, as `scripts/sync_zethus_plugin_root.py` already does for Zethus's agent. No path an
  existing install reads moved: `mnemosyne/install.py` still copies `mnemosyne/plugin/`, and the
  marketplaces still point at the same folders.
- **One `pr-description`.** Zethus keeps `zethus-pr-description` (D8, ruled: its other skills are
  process-specific, and the general one is Amphion's). The core carries the general one, so a kit that
  needs it gets one copy, and no skill was renamed.
- **The `memory` schema** is derived from what `mnemosyne.candidates` and `mnemosyne.standards`
  read, not from the example in §4.7. Both kits' example configs now carry `"memory": {"enabled":
  true, "mode": "shadow"}`, which is what an absent block already meant, and `--check` holds them to
  the schema.
- **Fixed on the way:** the two shared skills linked to a sibling `log-friction` skill, which only
  Amphion has; they now name the skill in prose, so neither kit has a dead link.

**The installer.** [`install.py`](../install.py) composes what existed and adds what was missing.

- **Called, not copied.** The `mnemosyne` and `zethus` bundles are *delegates*: the installer runs
  `mnemosyne/install.py` and `zethus/install.py` through their own `main()`. Only the `core` and
  `amphion` bundles are files it copies itself (their skills, and in a repo Amphion's example config,
  never over a file that is there). `zethus/install.py --with-core` and the new `amphion/install.py`
  are each kit's own door into the same code.
- **Needs, not duplicates.** `core` needs `mnemosyne`; `zethus` and `amphion` each need `core`. A run
  resolves the set once, in dependency order, so the core and Mnemosyne are installed once however
  many kits ask. Only Mnemosyne's installer writes a hook registration (the Claude plugin, and for
  Copilot `.github/hooks` or `~/.copilot/hooks`), and it is called once per run, so each hook
  registers once.
- **All or nothing.** The run is planned first and each delegate is rehearsed with its own
  `--dry-run`; any conflict, in any bundle, writes nothing. A file the installer did not write is
  never overwritten, even with `--force`; one it wrote and you edited needs `--force`. `--force` is
  not passed to Mnemosyne's installer, where it would repoint `MNEMOSYNE_REPO`.
- **Its own manifest.** `~/.mesmer-grimoire/install-manifest.json`, or `.mesmer-grimoire/` in a repo
  (repo-relative keys, so a committed manifest names no machine). It records each file's hash, bundle
  and host, and the bundles asked for per host. It never lists Zethus's or Mnemosyne's files, which
  keep their manifests where they always were: that is what lets an older Zethus installer re-run over
  a newer install leave the core alone.
- **Uninstall** removes the unedited files of the bundles that leave, keeps a bundle something still
  needs (removing Amphion keeps the core for Zethus), and hands Zethus and Mnemosyne to their own
  uninstallers (user scope; in a repo their committed files go with git). The memory repo stays.
- **Hosts.** Claude Code and Copilot. `--platform codex` and `cursor` are refused with a pointer here.
  Zethus is Copilot-only, so `--platform all` skips it on Claude with a note.

**Exit test** (`tests/test_shared_core_install.py`, 50 tests, every one on a temp home and repo with
fakes for pip, `claude` and the Windows registry; git runs for real):

| Claim | Evidence |
| --- | --- |
| Installing both kits into a temp target registers each hook once | Every JSON hook file under the temp home and repo is scanned: the six Claude events and the five Copilot events each appear exactly once, and the Claude plugin is installed once. Repeated for `--user`, for either install order, for a second run (the whole tree is byte-identical), and with `zethus/install.py --with-mnemosyne` or `--with-core` run first |
| An older Zethus installer re-run over a new install loses, duplicates and renames nothing | `tests/fixtures/zethus_install_pre_phase4.py` is `zethus/install.py` as it stood at `aa808db`, run beside a copy of the kit. Over a new user install the whole tree and Zethus's manifest are unchanged; its `--uninstall` removes only Zethus's files and leaves the core's skills and the new manifest; over its own repo install the new installer refuses writing nothing, and with `--force` loses and changes nothing |
| Upgrading an existing install loses, duplicates and renames nothing | An install made by that older installer plus `mnemosyne/install.py`, with a user config carrying its own keys, is upgraded by `--platform all --user --bundle zethus,amphion`: every earlier file is byte-identical, the config is byte-identical, Zethus's and Mnemosyne's manifest entries are unchanged, the hooks stay registered once, and the only additions are the core's and Amphion's skills and the new manifest. An edited kit file refuses the upgrade and is left as it was |
| `tests/test_zethus.py` green | The full suite (1,100+ tests) passes locally and in CI |
| Stage 1 §3.4 CI additions | `install.py --check`, the installer dry run on Linux and Windows, the skill lint and the doc-pointer check are blocking CI steps |

**Open, with a recommendation each** (none blocks the layer; each needs Ceryce):

1. **Claude Code in a repo: committed hooks?** A `--target` install on Claude registers the memory
   hooks through the user-scope plugin only, because Mnemosyne's installer does not write
   `.claude/settings.json`. A teammate on Claude Code without the plugin gets the skills and no hooks.
   Merging a managed block into `.claude/settings.json` would fix that, at the cost of the 1.0.88
   double-fire the engine's guard already handles. **Recommend: not yet.** Build it only when a team
   asks for committed Claude hooks, as its own change.
2. **The `all` skills layout.** Each host gets its native folder (`.claude/skills`, `.github/skills`),
   so a host that reads both (VS Code reads `.claude/skills`) may list a skill twice. Stage 1 §2.4's
   duplicate-skills test, which decides this, was not run: it needs each host installed. **Recommend:**
   keep native folders; if a host shows duplicates, put Copilot's copy in `.agents/skills` for `all`.
3. **The Zethus plugin does not carry the core's skills.** A Copilot user who installs only the
   `zethus` plugin gets Zethus's skills, not `flag-or-fix` and the other two. **Recommend:** leave it,
   and say so in the README: they arrive with `--with-core`, the Amphion plugin or the installer.
   Mirroring them into the Zethus plugin would add three skills to every Zethus user's list and move
   Zethus's agent-file link tests.
4. **Codex and Cursor** (stage 2, D7): strategies, manifests and the neutral agent layout. Not Phase 4.

**Not verified on a real host.** Every installer path ran against fakes and temp dirs. No real Claude
Code or Copilot CLI, VS Code or IntelliJ was driven: the plugin install through `claude plugin`, the
hook registrations being loaded and fired once, the skills being listed once, and `agentStop` and
friends with the installed files are all unobserved. The CI dry run on a Windows runner reads (never
writes) the registry. `--force` on a skill that an installed plugin also carries is untested beyond
the fake.

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

Each lists the recommended option first. Costs use the sizes in §5. **All eight are ruled. Q1, Q2
and Q4–Q8 went as recommended; Q3 is settled by Mnemosyne's existing federation, not by any of its
options.**

### Rulings (2026-10-29)

Ceryce answered Q1, Q2 and Q4–Q8 by Telegram picker. Each tap is quoted verbatim, with the option
description the picker showed beside it. She answered Q3 in chat instead, quoted verbatim below.

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
- **Q3**, at 22:05 CT, in chat (the picker was settled by this reply, not a tap): "Mnemosyne
  should already use an N-tier federated design with github repos as the stores, so this should
  already be answered." She is right. The [design doc](../mnemosyne/docs/design.md#architecture)
  ("Two tiers, then N" and "Broader tiers (federation)") already defines the tiers: local, then
  the repo's shared tier, then any number of federated stores declared in `config.stores`, each
  its own git (GitHub) repo with a distinct id prefix, with a promotion opened as a PR in that
  store's repo. None of the three options the spec invented is needed.

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
| Q3 | **Ruled: none of the options**; settled by Mnemosyne's existing N-tier federation. Reflected in the status line, [§4.5](#45-where-each-outcome-lands), the `memory.offerTier` config and Phase 3 |
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

**Ruled 2026-10-29, 22:05 CT, in chat: none of the options.** Mnemosyne's existing N-tier
federation already answers it: local, then the repo's shared tier, then any number of stores in
`config.stores`, each its own git repo; see [Rulings](#rulings-2026-10-29). The options are kept
for the record, struck as not needed.

1. ~~**A private personal memory repo as the default store, plus each project's own shared tier
   *(recommended)*.** Cross-repo standards live in the personal store, and project facts stay with
   the project. Cost: one private repo, and `stores` configured once per machine.~~ *Not needed.*
2. ~~**One private memory repo as the primary for everything, with no project tiers.** Cost: the
   simplest setup, but project conventions leave the project, and teammates never see them.~~
   *Not needed.*
3. ~~**An organisation `enterprise` store for work repos, alongside option 1.** Cost: per-org setup,
   and needs `scope: "external"` scrubbing from day one.~~ *Not needed.*

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

# Stage 1 assessment: memory engines and platform-agnostic plan (2026-09-30)

<!-- doc-pointers: point-in-time -->

**Status:** assessment and plan only. Nothing here has been built. **All ten
[decisions](#4-decisions-for-ceryce) are ruled** (2026-09-30), every one as recommended. D1–D8 and
D10 were ruled first. D9 was ruled after the
[`sync-claude-md` deep dive](#appendix-a-d9-deep-dive-does-sync-claude-md-earn-its-place): retire
it, add a CI check for dead doc pointers, and write a "leaf, not root" rule. Stage 2 can start. See
[Rulings](#rulings-2026-09-30).

**The ask:**

1. Review mnemosyne and morpheus. Do they still make sense, what should improve, and is morpheus
   still worth anything?
2. Make every Claude-only piece of the repo platform-agnostic.
3. If needed, add an install script that installs the right variant for **Claude Code, GitHub
   Copilot, OpenAI Codex and Cursor**.

## Summary

- **Morpheus should be retired.** Its automatic hooks have been installed on the author's machine
  since 2026-07-15 and have **never produced a single dream**: its own recursion guard switches it
  off inside every Claude Code hook. Nobody has called its MCP tools either. Meanwhile Claude Code's
  native auto-memory writes the same `MEMORY.md` store, and the only real consumer already runs its
  own safer consolidation. Porting it to four hosts would mean four transcript parsers, four
  headless adapters and four memory stores, all to duplicate features every host now has natively.
- **Mnemosyne is worth keeping.** It has no users yet, but it is the one platform-neutral engine
  here: a stdlib CLI plus an MCP server with no Claude dependency. It needs a small correctness pass
  (non-atomic writes), and its install instructions need to become true: it is not on PyPI.
- **The grimoire umbrella should be retired along with morpheus.** With one engine left it wraps
  nothing, since mnemosyne's own server already exposes the same seven tools. The name lives on as
  the repo and as the new installer.
- **Going platform-agnostic is much cheaper than it sounds.** All four hosts have converged on the
  [Agent Skills](https://agentskills.io/specification) `SKILL.md` format, on MCP, on `AGENTS.md`,
  and on a Claude-shaped plugin, hook and subagent model. Every skill in the repo already uses only
  `name` and `description` frontmatter. The actual work is:
  - converting commands to skills;
  - un-Claude-ing a handful of paths and words;
  - one per-platform format each for instructions, agents and MCP registration;
  - an installer, which should grow out of the existing `zethus/install.py` (it already has a
    SHA-manifest, conflict-safe, uninstallable user-scope engine).
- **Estimated stage 2 effort:** about 7–10 working days end to end with the ruled options. That
  includes about 1 day for D9's retire-plus-check outcome over the rename first assumed, and about
  2 days for the Zethus port. See the [effort table](#35-effort).
- **`sync-claude-md` goes; it is not renamed (D9, ruled).** Every run on record wrote to a repo-root
  `CLAUDE.md`, and 72% of the bytes it added were new detail rather than corrections. It stopped
  running in July, yet the bloat kept growing, so the real fix is a rule about *where* detail lands,
  plus a CI check. See [Appendix A](#appendix-a-d9-deep-dive-does-sync-claude-md-earn-its-place).

---

## 1. Mnemosyne, Morpheus and the Grimoire umbrella

### 1.1 Evidence base

- **Code:** read-only review of the three engines' source, tests, docs and git history.
- **Real usage:** a search of Ceryce's private personal-assistant repository, the author's user-level
  Claude Code configuration and runtime directories, and a scan of local session transcripts for
  tool calls. The consumer is described but not named, and private paths are left out, because
  this repo is public.
- **Checked by hand in this pass:** the dispatcher guard (`morpheus/src/morpheus/dispatch.py:38-42`,
  `:124`), the test fixture that hides it (`tests/_util.py:34`), the empty runtime directories, the
  live hook registrations, and the MCP tool counts.

### 1.2 Mnemosyne: reflexion lessons memory

**What it does today:**

- It is a git-backed *lessons* store with two tiers:
  - a **local** tier;
  - a **shared** tier that is PR-governed and can be federated with `team` and `enterprise` stores
    in other repos (`src/mnemosyne/stores.py`).
- **Recall** scores lessons along config-defined axes (`mnemosyne.config.json`), so the scorer is
  domain-agnostic.
- **Capture and reflect** turn real failures into lessons, with filters for low-value and duplicate
  lessons.
- **Promote, export and sync** move lessons up a tier through a pull request. **Prune and hygiene**
  keep the store tidy.
- It ships as an **MCP server with 7 tools**, a CLI (`mnemosyne`), a config wizard, and a Claude
  Code plugin (1 skill, 3 commands, 3 hooks).

**Size and activity:** about 3,200 LOC across 9 modules. The suite has 3 unit tests wrapping a
41-check `selftest`, all green. There are 12 commits; the last feature landed 2026-07-06 (the
wizard) and the last change 2026-09-01.

**Platform coupling:** low. The engine, CLI and MCP server are pure stdlib and host-neutral. Only
the plugin wrapper (manifest, 3 commands, 3 hooks) is Claude-specific.

**Real users:** **none found.** It is not installed on the author's machine, the store directory
has been empty since 2026-07-04, and the consumer repo never references it.

**Does it still make sense?** Yes, as the repo's genuinely portable engine and as a portfolio piece.
But it should be described honestly as having no production user yet.

**Improvements, ranked by value for cost:**

| # | Improvement | Value | Cost |
| --- | --- | --- | --- |
| 1 | **Atomic writes and a lock around every rewrite.** `write_jsonl` (`core.py:139-144`) opens with `open("w")`, which truncates the file before writing, so a crash mid-write loses the whole store. Recall's usage-count update and `promote` rewrite files with no lock. | High (data loss) | S |
| 2 | **Make install instructions true.** Nothing is on PyPI (`pip index versions` finds none of the three packages) and there is no release workflow, yet every README says `pip install`. Either document `pip install "git+https://github.com/kumouri/mesmer-grimoire#subdirectory=mnemosyne"` (S) or add a tagged PyPI release workflow (M). Also align package versions (0.5.0) with repo tags (v0.7.0). | High | S / M |
| 3 | **Drop the SessionEnd "remember to /reflect" nudge** (`mnemosyne_hook.py:70-82`). Claude Code discards SessionEnd output ([C4]), so nobody ever sees it. | Medium | S |
| 4 | **Make MCP `promote` match the CLI.** Its description says it "stages the governance PR", but only the CLI creates the branch (`cli.py:251`). Fix the behaviour or the wording. | Medium | S |
| 5 | **Keep `git` out of the per-prompt hook path.** The hook currently runs `git rev-parse` on every prompt and `git pull` at session start. Cache the repo root and make the pull opt-in. | Medium | S |
| 6 | Convert the 3 commands to skills and ship the MCP server in the plugin (`.mcp.json` is currently missing). This is part of the platform work in §3. | Medium | S |
| 7 | **Find one real consumer before adding features.** Candidates are amphion's `log-friction` and `flag-or-fix` outcomes, or Zethus's retrospective step. | High (proves the design) | M |

### 1.3 Morpheus: automatic session dreaming

**What it does today:**

- `PreCompact` and `SessionEnd` hooks queue a durable job.
- A detached worker then reads the transcript since the last run and "dreams" over it with one of
  three engines:
  - `headless`: `claude -p --bare …`;
  - `hybrid`: a Haiku extraction plus deterministic writing;
  - `deterministic`: regex, no LLM.
- It writes durable facts into Claude Code's own per-project auto-memory store
  (`~/.claude/projects/<slug>/memory/<type>-<slug>.md` plus `MEMORY.md`), and a log into
  `memory/dreams/`.
- `SessionStart` injects a recall digest.
- It also ships as a 3-tool MCP server (`dream`, `wake`, `dreams`), a CLI, a skill, a command,
  scheduler templates and a settings-merge installer.

**Size and activity:** about 1,856 LOC across 23 modules, with 35 unit tests plus a selftest, all
green. The last functional change was 2026-07-15.

**Platform coupling:** total.

- It depends on Claude Code at every layer: hook events and payloads, `claude -p --bare`, Claude's
  transcript JSONL (which its own code calls "version-unstable"), the `~/.claude/projects/<slug>`
  naming rule, `CLAUDE_*` environment variables, and Claude's auto-memory file format.
- Only the deterministic engine and the MCP wrapper are neutral, and even the MCP `dream` tool
  expects a Claude transcript and writes into `~/.claude/`.

#### Why it has never run

**It has never actually worked in production.** It was installed on the author's machine on
2026-07-15, with hooks registered for SessionStart, SessionEnd and PreCompact and a user-scope MCP
server, and it has produced nothing since:

- **No output at all.** The runtime directory holds only the default `config.json` and empty
  `spool/`, `state/` and `locks/` directories, all dated 2026-07-15. There is no high-water file,
  no worker log and no failed job. None of the local per-project memory directories has a `dreams/`
  folder.
- **No manual use either.** Across the local transcript archive there are **zero** calls to its
  MCP tools, and only two CLI calls, both on 2026-07-01 while it was being built.
- **Root cause.** `dispatch.py` exits silently whenever `CLAUDE_CODE_CHILD_SESSION=1`
  (`dispatch.py:38-42`, `:124`). Claude Code sets that variable in the environment it builds for
  hook commands:
  - The string `setChildSession(Boolean(a.CLAUDE_CODE_CHILD_SESSION))` is present in the 2.1.285
    CLI.
  - A sandbox run enqueued a job only once the variable was removed.
  - The empty spool after 2.5 months of registered hooks is consistent with this.
- **CI hides it.** `tests/_util.py:34` removes the variable before every test, so the suite is
  green while the real thing does nothing. The repo's own `CLAUDE.md` tells maintainers to
  *preserve* this guard.
- **A second failure is queued behind it.** The default `headless` engine passes `--bare`, and
  `--bare` authenticates only with `ANTHROPIC_API_KEY` ([C10]). That key is deliberately unset
  (subscription billing), and the morpheus docs never mention the requirement.
- **Silent by design.** The dispatcher swallows every error and always exits 0, so 2.5 months of
  doing nothing produced no signal. The consumer's own notes still record morpheus as "fully
  enabled".

#### Other defects found

- **Keeps the wrong end of long sessions.** `render()` keeps the *first* 24,000 characters of the
  transcript and cuts the rest (`transcript.py:103-118`). The worker then marks the whole delta as
  processed (`worker.py:124`), so the most recent part of a long session is silently lost. Tool
  output uses up the budget first.
- **Would rewrite the index destructively.** `update_index` (`memory.py:112-131`) rewrites
  `MEMORY.md` keeping only lines that start `- [`, sorted alphabetically. That would destroy a
  hand-ordered index. It also coordinates with nothing but itself, so it would race Claude Code's
  own memory writer.
- **The deterministic engine would write junk.** It treats tool output as user corrections and
  matches words like "should" and "instead", which would produce junk feedback memories. It also
  overwrites files instead of the promised "merging and deduping".
- **The lock is shorter than the job.** The lock waits 30 s but a dream can run 240 s, so a second
  worker on the same project fails, counts a retry, and can shelve a healthy job.
- **Untrusted text reaches an editing child.** The headless child can edit files while reading
  untrusted transcript text. Nothing marks that text as untrusted, and the child's working
  directory is inside the package.
- **Dead and stale material.** `prompts/wake.system.md` is never used. There are stale doc paths:
  `config.py:3` says `~/.claude/dreaming/`, and `usage.md` and `reconcile.py` point at an
  `install/` directory that doesn't exist. `commands/dream.md` refers to a `dreaming` skill that is
  now called `morpheus`.

#### The hosts now do this natively

- **Claude Code:** auto memory writes `MEMORY.md` plus typed topic files into the same directory
  morpheus targets ([C1]). The 2.1.285 CLI also contains an `autoDreamEnabled` setting ("Enable
  background memory consolidation (auto-dream)") with a consolidation lock. That setting is **not**
  in the public docs pages read for this assessment, so treat it as unverified.
- **Codex:** has opt-in background "memories" under `~/.codex/memories/` ([X13]).
- **Copilot:** has Copilot Memory, stored server-side ([G21]).
- **Cursor:** documents no memory feature ([R-gap]).

**Its only real consumer already outgrew it.** The private assistant runs its own SessionEnd
consolidation, which morpheus lacks. That consolidation:

- skips trivial and watch sessions and handles small and large ones differently;
- wraps transcript text as untrusted;
- keeps model-written summaries out of its search index;
- bills to the subscription;
- is backed by a curated, size-capped `MEMORY.md` and a nightly consolidation pass.

It borrowed exactly one thing from morpheus: the Windows no-console-window spawn pattern.

#### Keep, slim, fold or retire

| Option | What it means | Verdict |
| --- | --- | --- |
| **Retire** *(recommended)* | Tag the last state (e.g. `archive/morpheus-v0.5.0`), remove `morpheus/` and its tests from `develop`, and replace them with a short retrospective (`docs/morpheus-retrospective.md`). The retrospective records what was learned: the durable spool and per-session high-water design, the no-console-window spawn, and why hook-driven consolidation is fragile. | It never ran, the hosts cover the need natively, and the one consumer has a better version. Retiring costs S. |
| Freeze in place | Keep the code with an ARCHIVED banner and stop maintaining it. | Keeps portfolio visibility, but leaves a known-broken artifact in a showcase repo, and CI keeps running 35 tests for it. The platform port would have to carve it out. |
| Slim down | Keep only the deterministic engine plus MCP, and drop hooks and headless. | The deterministic engine is the weakest part (see above). What remains is a regex over a Claude-only transcript format. |
| Fold into mnemosyne | Add a "reflect from transcript" path to mnemosyne. | Contradicts mnemosyne's deliberate, failure-driven design. It would need per-host transcript parsers, and it has no consumer. |
| Fix and keep | Remove the child-session guard (add a test with it set), drop `--bare` (fall back to deterministic on auth failure), log every dispatch decision plus `morpheus doctor`, keep the transcript *tail* without tool output, stop reordering `MEMORY.md`, mark transcript text untrusted, lengthen the lock. | About M (2–3 days) just to reach "works on Claude Code". Each extra host is another L: its own transcript format, headless CLI and memory store. |

**Independent of the ruling:** the live hook registrations on the author's machine should come out
now. They point at an old pre-rename checkout, so fixes in this repo never reach them, and they
spawn Python on every session start, compaction and session end for nothing. The consumer's note
calling morpheus "fully enabled" should be corrected at the same time. Both are outside this repo
and are **not** done by this PR.

### 1.4 Grimoire: the umbrella

**What it is:** about 290 LOC.

- One MCP server re-exports all **10** tools: 7 from mnemosyne and 3 from morpheus.
- One plugin carries byte-identical copies of the engines' 2 skills and 4 commands, plus a combined
  hook dispatcher (`grimoire_hook.py`).
- Tests are only an import smoke test plus 2 import-guard tests. The hook has no tests.

**Problems found:**

- The hook has the same self-disabling guard (`grimoire_hook.py:21-25`).
- Its SessionStart path ignores the "light digest" setting.
- Its 7 memory tools duplicate `mnemosyne/mcp_server.py` almost line for line.
- The docs disagree on the tool count: "nine tools" in `grimoire/README.md`, the plugin description
  and `docs/grimoire/architecture.md`, which also omits `export`. The repo `CLAUDE.md`'s "ten" is
  correct.
- The install hint `pip install "grimoire[mcp]"` names a package and an extra that don't exist
  (`grimoire/mcp_server.py:8,32`).

**Verdict:** if morpheus retires, the umbrella has nothing to compose, so retire it too and make
mnemosyne the featured engine. The *name* survives as the repo (`mesmer-grimoire`) and as the new
cross-platform installer ("install the grimoire"). If morpheus is kept, grimoire is still marginal:
its only job is to stop two plugins double-firing hooks. In that case, fix the tool count and the
install hint.

---

## 2. Platform-agnostic audit

### 2.1 What the four hosts support today

Every claim below was checked against the vendor's current docs on **2026-09-30**; source IDs are
listed in [§5](#5-sources). A few pages came back as model-written summaries rather than verbatim
text, and claims resting on them are marked \*. Anything no vendor page confirmed is listed in
[§2.4](#24-unverified-claims-verify-in-stage-2).

| Capability | Claude Code | GitHub Copilot (VS Code · CLI · cloud agent) | OpenAI Codex (CLI · IDE · app) | Cursor (editor · `agent` CLI) |
| --- | --- | --- | --- | --- |
| **Always-on instructions** | `CLAUDE.md` / `.claude/CLAUDE.md` / `CLAUDE.local.md`; user `~/.claude/CLAUDE.md`; `@path` imports; `.claude/rules/*.md` and `~/.claude/rules/` (optional `paths`) [C1]. Reads `AGENTS.md` natively (≥2.1.277) **only when no CLAUDE.md exists** by default [C1]. | `.github/copilot-instructions.md`; `.github/instructions/**/*.instructions.md` with `applyTo` [G1\*]. Reads `AGENTS.md` and root `CLAUDE.md` on all surfaces [G1\*, G5\*, V1\*]. User: `~/.copilot/instructions/` (CLI and VS Code) [G5\*, V1\*]. VS Code also reads `.claude/rules/` and `~/.claude/CLAUDE.md` [V1\*]. | `AGENTS.override.md` → `AGENTS.md` → `project_doc_fallback_filenames`, git root down to cwd, 32 KiB cap; user `~/.codex/AGENTS.md` (`CODEX_HOME`) [X3]. **No CLAUDE.md** unless added as a fallback name [X3]. (Codex "rules" are Starlark command policy, not instructions [X4].) | `.cursor/rules/*.mdc` with `description`/`globs`/`alwaysApply`; plain `.md` there is ignored [R1]. Reads `AGENTS.md` (nested too) **and `CLAUDE.md`** [R1]. User Rules exist only in the app (**no file**) [R1, R2]. `.cursorrules` is legacy [R1]. |
| **Skills** (agentskills.io `SKILL.md`) | `.claude/skills/`, `~/.claude/skills/`, plugin `skills/` [C2]. Does **not** read `.agents/` [C1]. | `.github/skills`, `.claude/skills`, `.agents/skills`; user `~/.copilot/skills`, `~/.agents/skills` [G3\*, G6\*]; VS Code also `~/.claude/skills` [V4\*]. | `.agents/skills` (cwd up to repo root); user `~/.agents/skills` [X6]. Optional `agents/openai.yaml` for UI and implicit-invocation policy [X6]. | `.agents/`, `.cursor/`, `.claude/`, `.codex/` `skills/`, project and user (`~/…`) [R5]. |
| **Slash commands / prompts** | Folded into skills; `.claude/commands/*.md` is legacy [C2]. | `.prompt.md` files are **deprecated** in favour of skills [V2\*]. CLI: skills run as `/name` [G6\*]. | `~/.codex/prompts/*.md` is **deprecated**: "Use skills" [X5]. | `.cursor/commands/*.md` [R4]; `/migrate-to-skills` converts commands to skills [R5]. |
| **Subagents / custom agents** | `.claude/agents/*.md`, `~/.claude/agents/`; frontmatter `name`, `description`, `tools`, `model`, … [C3]. | `*.agent.md` in `.github/agents/`, `~/.copilot/agents/`; tool aliases `read`/`edit`/`search`/`execute`/`agent`/`web`/`todo`; 30,000-char cap [G4\*, G9\*]. VS Code also reads `.claude/agents` and `~/.claude/agents` [V3\*]. `.chatmode.md` is replaced [V3\*]. | **TOML**, one file per agent, in `.codex/agents/` or `~/.codex/agents/`; required `name`, `description`, `developer_instructions` [X7]. | `.cursor/agents/`, also `.claude/agents/` and `.codex/agents/` (project and user); `name`, `description`, `model`, `readonly`, `is_background` [R7]. |
| **Hooks** | `settings.json` or plugin `hooks/hooks.json`; about 30 events including SessionStart, UserPromptSubmit, PreCompact, SessionEnd; stdin includes `transcript_path`; SessionEnd output is discarded [C4]. | `.github/hooks/*.json` `{"version":1,…}`; CLI and cloud agent events include sessionStart, sessionEnd, userPromptSubmitted, preCompact [G12\*]. **The CLI and VS Code also load `.claude/settings.json` hooks** [G12\*, V5\*]. VS Code (Preview) has **no SessionEnd** [V5\*]. | `hooks.json` or `[hooks]` in `config.toml`, user or project; SessionStart, SessionEnd, UserPromptSubmit, PreCompact, …; Claude-shaped stdin and output (`hookSpecificOutput`, `additionalContext`); must be trusted via `/hooks` [X8]. | `.cursor/hooks.json`, `~/.cursor/hooks.json` `{"version":1,…}`; sessionStart (can return `additional_context`), sessionEnd, beforeSubmitPrompt, preCompact, stop, … [R8]. **Also loads Claude `.claude/settings*.json` and `~/.claude/settings.json` hooks by default**, mapping event names [R9]. |
| **MCP servers** | `.mcp.json` (`mcpServers`); user and local scope in `~/.claude.json`; `claude mcp add --scope` [C5\*]. | VS Code: `.vscode/mcp.json` (`servers`) or root `.mcp.json` [V7\*]. CLI: `~/.copilot/mcp-config.json` or repo `.mcp.json` / `.github/mcp.json`; `copilot mcp add` [G7\*]. Cloud agent: repo settings UI [G15\*]. | `[mcp_servers.<name>]` in `~/.codex/config.toml` or trusted `.codex/config.toml`; `codex mcp add` [X9]. | `.cursor/mcp.json`, `~/.cursor/mcp.json` (`mcpServers`) [R10]. |
| **Plugins and marketplace** | `.claude-plugin/plugin.json`; marketplace `.claude-plugin/marketplace.json`; `claude plugin install name@mkt` [C6, C7, C8]. | CLI finds `plugin.json` at the root, `.plugin/`, `.github/plugin/` **or `.claude-plugin/`**; marketplace `.github/plugin/` **or `.claude-plugin/marketplace.json`**; `copilot plugin install OWNER/REPO:PATH` [G8\*, G16\*]. VS Code agent plugins detect `.claude-plugin/plugin.json` [V8\*]. | Root `plugin.json` (`.codex-plugin/plugin.json` is a fallback); marketplace `.agents/plugins/marketplace.json` or legacy `.claude-plugin/marketplace.json`; entries need `policy.*` and `category` [X10, X11]. | `.cursor-plugin/plugin.json` and `.cursor-plugin/marketplace.json`; bundles rules, skills, agents, commands, MCP and hooks [R12]. |
| **Headless runs / transcripts** | `claude -p`; `--bare` needs `ANTHROPIC_API_KEY`; JSONL at `~/.claude/projects/<slug>/<id>.jsonl`, format internal [C9, C10]. | `copilot -p`; sessions under `~/.copilot/session-state/` [G17\*, G19\*]. | `codex exec`; `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` [X12]. | `agent -p` (`cursor-agent` is an alias) [R6, R14]; the on-disk transcript location is **not documented** [R8]. |

**What this means for the design:**

1. **`SKILL.md` is the universal unit.** Commands and prompt files are deprecated on three of the
   four hosts and folded into skills on the fourth, so every command here should become a skill.
2. **A shared user-scope location is enough for three hosts.** `~/.agents/skills` (project:
   `.agents/skills`) reaches Copilot CLI, Codex and Cursor. Claude Code alone needs
   `~/.claude/skills`. But Cursor and VS Code *also* read `~/.claude/skills`, so installing into
   both places can show them duplicates (see [§2.4](#24-unverified-claims-verify-in-stage-2)).
3. **Copilot and Cursor already read Claude's formats:** `CLAUDE.md`, `.claude/skills`,
   `.claude/agents` and `.claude/settings.json` hooks. That is convenient, but it means an "all"
   install that also writes native hooks for those hosts would **fire twice**. The installer must
   put each hook in exactly one place per host.
4. **Always-on instructions are the one area without a clean shared file.**
   - `AGENTS.md` reaches Copilot, Codex and Cursor, and Claude Code reads it when no `CLAUDE.md`
     exists.
   - At user scope, Cursor has **no instructions file** at all, and Codex has only a single
     `~/.codex/AGENTS.md`. Codex is therefore the one host where the installer must merge into an
     existing file, using a delimited managed block.
5. **Plugin manifests are close to shared.** A `.claude-plugin/plugin.json` directory installs in
   Claude Code, Copilot CLI and VS Code as-is. Codex wants a root `plugin.json` and Cursor wants
   `.cursor-plugin/plugin.json`: two extra generated files per plugin. A single
   `.claude-plugin/marketplace.json` at the repo root is also read by Copilot and, as a legacy
   path, by Codex. **The repo has no marketplace today**, which is why `amphion/README.md`'s
   "install the plugin from this repo" can't actually be done.

### 2.2 Inventory: every Claude-specific piece and its equivalents

**Counts:**

- 4 Claude plugin manifests (amphion, grimoire, mnemosyne, morpheus); **no** `marketplace.json`.
- 9 unique Claude skills: amphion 7, mnemosyne 1, morpheus 1. Grimoire carries 2 byte-identical
  copies.
- 4 unique commands: mnemosyne 3, morpheus 1. Grimoire carries 4 copies.
- 3 `hooks.json` files plus 1 `settings.snippet.json`, using only SessionStart, UserPromptSubmit,
  PreCompact and SessionEnd.
- 3 MCP servers.
- **0** Claude subagents.
- The Zethus Copilot kit: 1 agent, 22 skills, 2 instruction files, 9 templates, 20 stdlib scripts
  and `install.py`.
- The top-level `skills/`, `hooks/`, `commands/` and `agents/` directories contain **only a README
  each**; all four point at `~/.claude/…`.
- **No Anthropic API or SDK calls anywhere.** The only model access is morpheus shelling out to
  `claude -p`.

"→ skill" below means: install the same `SKILL.md` into that host's skills directory (§2.1 row 2).

| Artifact (path) | Claude-specific today | Claude Code | Copilot | Codex | Cursor |
| --- | --- | --- | --- | --- | --- |
| amphion's 7 skills (`amphion/plugin/skills/*`) | Mentions `CLAUDE.md`, `/init`, Claude tool names; config at `.claude/amphion.config.json`; `sync-claude-md` is named after Claude | → skill (unchanged) | → skill | → skill | → skill |
| └ content changes for all hosts | — | Neutral config path with the old path as fallback; "the agent instructions file (`AGENTS.md`/`CLAUDE.md`/`copilot-instructions.md`)"; describe tool *actions*, not tool names. `resume-interrupted-phase` needs subagents, which all four hosts now have [C3, G9\*, X7, R7]. | | | |
| amphion plugin (`amphion/plugin/.claude-plugin/plugin.json`) | Claude manifest | as is plus marketplace entry | reads `.claude-plugin/` as is [G8\*] | generated root `plugin.json` | generated `.cursor-plugin/plugin.json` |
| mnemosyne skill `reflexion-memory` | "if the plugin's hooks are active…" | → skill | → skill | → skill | → skill |
| mnemosyne commands `recall`, `reflect`, `promote` | `$ARGUMENTS`; "use the Bash tool" | **convert to skills** (`disable-model-invocation: true`) | skill | skill (implicit invocation off via `agents/openai.yaml`) | skill |
| mnemosyne hook: SessionStart `git pull` | Claude hook JSON | keep, opt-in | `sessionStart` (`.github/hooks`) or Claude settings (read either way) | `SessionStart` in `hooks.json` | `sessionStart` (or via the Claude hooks it already reads) |
| mnemosyne hook: UserPromptSubmit recall injection | plain-stdout context | keep | `userPromptSubmitted`; can it inject context? **unverified** | `UserPromptSubmit` + `additionalContext` [X8] | `beforeSubmitPrompt` has **no documented context output** [R8]; use the MCP and skill path instead |
| mnemosyne hook: SessionEnd nudge | output discarded [C4] | **delete** | — | — | — |
| mnemosyne MCP server (`mnemosyne.mcp_server`) | docstring says `claude mcp add` | `.mcp.json` / `claude mcp add` | `.vscode/mcp.json` + `~/.copilot/mcp-config.json` | `[mcp_servers.mnemosyne]` / `codex mcp add` | `.cursor/mcp.json` / `~/.cursor/mcp.json` |
| morpheus: skill, command, 3 hooks, MCP, 3 engines, transcript parser, reconcile sweep, schedulers, settings installer | everything (§1.3) | **retire** (D1) | no equivalent of the whole: different transcript store, headless CLI and native memory | same | same; transcript location undocumented |
| grimoire umbrella: plugin, `grimoire_hook.py`, MCP server, copied skills and commands | Claude manifest and hooks; `CLAUDE_*` guard | **retire** with morpheus (D2) | — | — | — |
| Zethus working agreement (`zethus/copilot-instructions.md`) | none (Copilot-native) | `.claude/rules/zethus.md` (always loaded) / `~/.claude/rules/` | as today | managed block in `AGENTS.md` / `~/.codex/AGENTS.md` | `.cursor/rules/zethus.mdc` `alwaysApply: true`; user scope: **no file** (print a hint) |
| Zethus docs instruction (`com.github.copilot/rules/zethus-docs.instructions.md`, `applyTo: **/*.md`) | none | `.claude/rules/*.md` with `paths: ["**/*.md"]` | as today | fold into the `AGENTS.md` block | `.mdc` with `globs: **/*.md` |
| Zethus agent (`com.github.copilot/agents/zethus.agent.md`) | none | generated `.claude/agents/zethus.md` (map tool aliases or omit `tools`) | as today | generated **TOML** `.codex/agents/zethus.toml` (`developer_instructions` = body) | generated `.cursor/agents/zethus.md` |
| Zethus's 22 skills, templates and scripts | skill bodies hard-code `.github/zethus/…` paths | → skill + path rewrite (the rewrite engine exists: `install.py` `user_rewrites()`) | as today | → skill + rewrite | → skill + rewrite |
| `zethus/install.py` | Copilot-only destinations | becomes the core of the multi-host installer (§3.2) | | | |
| Repo `CLAUDE.md` (maintainer guidance) | Claude-only filename | `CLAUDE.md` containing `@AGENTS.md` | reads `AGENTS.md` | reads `AGENTS.md` | reads `AGENTS.md` |
| `skills/`, `hooks/`, `commands/`, `agents/` READMEs | point at `~/.claude/…` | rewrite as host-neutral "where things go", or fold into the root README (they hold no artifacts) | | | |
| Root `README.md` tagline "A grimoire of Claude Code creations"; pyproject descriptions and `claude` keywords | branding | reword to "agent" or "coding-agent" after PR #36 lands | | | |
| Tests (`tests/_util.py`, `test_morpheus_*`) and CI | Claude env vars and payloads | morpheus tests leave with morpheus. **New:** CI validation of every generated manifest and a skill frontmatter lint (nothing checks `plugin.json` or `hooks.json` today). | | | |

### 2.3 Other drift found along the way

These are docs-and-code corrections for stage 2; none needs a ruling.

- **Stale repo name.** Twenty-eight files still say `claude-grimoire`, including the identifier
  guard's `REPO_SLUG` (`scripts/check_identifiers.py:104`). PR #36 covers the rename; stage 2 must
  rebase on it rather than touch those lines.
- **Skill name collision.** `pr-description` exists in both amphion and Zethus. On a host that
  reads both install locations, the two collide (see D8).

### 2.4 Unverified claims (verify in stage 2)

No vendor page confirmed any of these. Each must be tested against a real install before the
installer relies on it.

- **Duplicate skills across two roots.** How do Cursor and VS Code handle the same skill name in
  both `~/.claude/skills` and `~/.agents/skills`? This decides the "all" layout.
- **Copilot `userPromptSubmitted` output.** Does it inject context?
- **Copilot CLI and `~/.claude/skills` / `.claude/agents`.** Does the CLI read them? The VS Code
  pages say VS Code does.
- **Codex on Windows.** Is the home really `%USERPROFILE%\.codex`? Only third-party sources say
  so; the vendor pages show `~/.codex`.
- **Codex `~/.codex/skills` and `.codex/skills`.** Are they still read? The current page lists only
  `.agents/skills`.
- **Codex hooks under `codex exec`.** Do they run?
- **Codex and a Claude-style `.claude-plugin/plugin.json`.** Does it accept the manifest? Only the
  legacy marketplace path is documented.
- **Cursor user commands.** The `~/.cursor/commands` path and the argument syntax are documented
  only by third parties.
- **Cursor transcripts and memories.** The transcript location and whether Memories were removed
  come only from third parties. This only matters if morpheus were kept.
- **VS Code on-disk paths.** The per-OS user-profile folder for prompts and `mcp.json` is not
  documented. Prefer `~/.copilot/…`, which VS Code reads [V1\*, V4\*, V7\*].
- **Claude Code `autoDreamEnabled`.** The setting appears in the CLI build but not in the docs read.

---

## 3. Proposed architecture

### 3.1 One neutral source, generated per-host output

The repo is already 90% neutral: skills are `SKILL.md` with `name` and `description` only, the
engines are stdlib, and MCP is a standard. So "source of truth" means:

```text
<artifact>/                       # e.g. amphion/, mnemosyne/, zethus/
  skills/<name>/SKILL.md          # agentskills.io; name + description (+ license/metadata) only
  agents/<name>.agent.md          # one neutral agent format (Copilot's .agent.md, the richest
                                  # superset); generated per host
  instructions/<name>.md          # always-on text + optional `applies_to` glob; generated per host
  mcp.json                        # neutral {name: {command, args, env}}; serialized per host
  hooks.json                      # neutral {event: command}; mapped per host, Claude + Codex only
catalog.json                      # repo root: bundles → artifacts → which hosts each supports
```

The per-host transforms are small and all live in the installer, so no generated trees are
committed:

| Neutral piece | Claude Code | Copilot | Codex | Cursor |
| --- | --- | --- | --- | --- |
| skill | copy | copy | copy (+ optional `agents/openai.yaml`) | copy |
| instructions | `.claude/rules/<n>.md` (`paths:` from `applies_to`) | `.github/instructions/<n>.instructions.md` (`applyTo:`) | managed block in `AGENTS.md` | `.cursor/rules/<n>.mdc` (`alwaysApply`/`globs`) |
| agent | `.claude/agents/<n>.md` | `.github/agents/<n>.agent.md` | `.codex/agents/<n>.toml` | `.cursor/agents/<n>.md` |
| MCP | `claude mcp add` if present, else `.mcp.json` | `.vscode/mcp.json` + `~/.copilot/mcp-config.json` | `codex mcp add` if present, else a managed TOML block | `.cursor/mcp.json` |
| hooks | `settings.json` merge (salvage morpheus's `install.py` merge logic before it is removed) | *none*: Copilot already reads Claude's hooks, so avoid double-firing | `hooks.json` | *none*: Cursor already reads Claude's hooks |
| path rewrite | `.github/zethus/` → `.claude/zethus/` | as today | `.codex/zethus/` | `.cursor/zethus/` |

**The only committed generated files are plugin and marketplace manifests,** because marketplace
installs need them in the repo:

- `.claude-plugin/marketplace.json` (read by Claude, Copilot and Codex);
- `.agents/plugins/marketplace.json` (Codex);
- `.cursor-plugin/marketplace.json` (Cursor);
- per-plugin root `plugin.json` and `.cursor-plugin/plugin.json`.

A `--check` mode in the generator, run in CI, fails the build if they drift from `catalog.json`.

### 3.2 Installer design

**A single `install.py`** at the repo root: Python 3.8+ stdlib, the same floor as the engines. It is
grown from `zethus/install.py`, whose manifest, SHA check, foreign-file protection, all-or-nothing
conflict handling, dry run and empty-directory pruning are already host-agnostic. Only its
destination tables, `user_rewrites()` and `copilot_home()` are Copilot-specific; those become one
strategy class per host.

```text
python install.py --platform claude|copilot|codex|cursor|all   (repeatable)
                  (--user | --target DIR)
                  [--bundle amphion,mnemosyne,zethus]   default: all bundles that support the host
                  [--dry-run] [--force] [--uninstall] [--list]
```

- **Scopes.** `--user` writes to each host's home (`~/.claude`, `~/.copilot`, `~/.agents`, `~/.codex`
  honouring `CODEX_HOME`, `~/.cursor`). `--target DIR` writes project-scope files into a repo.
- **Idempotent.** A manifest records `{path: sha256}` plus, for merged files (`settings.json`,
  `AGENTS.md`, `config.toml`, `mcp.json`), the exact managed keys or delimited block it owns. A
  re-run with unchanged sources is a no-op, and a changed source updates in place.
- **User edits are safe.** A file the user has edited since install is a conflict, overwritten only
  with `--force`. A file the manifest doesn't know about is never overwritten, even with `--force`.
  This is already Zethus's behaviour.
- **Uninstall** removes only what the manifest owns: whole files, JSON keys and managed blocks. It
  works for **both** scopes; today Zethus's repo-scope install has no uninstall. Manifests live in
  `~/.mesmer-grimoire/install-manifest.json` and `<target>/.mesmer-grimoire/install-manifest.json`.
- **Host CLIs are preferred where they exist.** `claude mcp add/remove` avoids hand-editing the
  large, live-written `~/.claude.json`. `codex mcp add/remove` avoids writing TOML, since stdlib
  `tomllib` can only read it. When a CLI is absent, the installer falls back to a managed block.
- **`all` never double-installs a hook,** because Copilot and Cursor read Claude's hooks
  (§2.1 point 3). The skills-root layout for `all` is settled by the §2.4 duplicate-skills test.
- **Cross-platform.** Paths come from `pathlib.Path.home()`; there are no shell-outs except the
  host CLIs, and `shutil.which` finds those. The existing `PLATFORM = sys.platform` seam keeps
  per-OS branches testable. Output prints `~/`-relative paths, so pasted logs leak no username,
  which Zethus already does.
- **Optional shims.** `install.sh` and `install.ps1` are about 10 lines each: they find a Python
  3.8+ and `exec` `install.py`, for people who expect a shell entry point. They are not a second
  implementation.
- **Zethus's own `install.py`** becomes a thin wrapper, `install.py --bundle zethus --platform
  copilot`, so its documented commands keep working.

### 3.3 Distribution: installer plus marketplaces

- **Marketplace channel.** The committed marketplaces make `amphion` and `mnemosyne` one-command
  plugin installs on Claude Code (`claude plugin install amphion@mesmer-grimoire`), Copilot CLI
  (`copilot plugin install kumouri/mesmer-grimoire:amphion/plugin`), Codex and Cursor.
- **Installer channel.** The installer covers everything a plugin can't:
  - project-scope drop-ins;
  - Zethus into `.github/`;
  - hosts or setups without marketplace access;
  - MCP registration on Codex and Cursor;
  - uninstall.

### 3.4 Repo-level changes

- **Instructions file.** Rename the repo `CLAUDE.md` to `AGENTS.md` (canonical) and leave a
  one-line `CLAUDE.md` containing `@AGENTS.md`. Claude follows the import; Copilot and Cursor read
  both, and a one-line import is harmless to them; Codex reads `AGENTS.md`.
- **Docs.** Update the root README tagline and table; replace the four placeholder directory
  READMEs with one host-neutral "where things go" section; and add `docs/platforms.md` with the
  §2.1 matrix as the maintained reference. Per the docs-in-the-leaf rule, the matrix lives there,
  not in the root.
- **CI additions.**
  - `python install.py --check`, which validates the catalog and flags manifest drift;
  - a dry run of `install.py --platform all --user` and `--target` into a temp directory on Linux
    and Windows runners;
  - skill frontmatter lint (the agentskills.io name and description rules, which
    `tests/test_zethus.py` already enforces for Zethus);
  - a blocking doc-pointer check that fails on links and backticked file paths that no longer
    exist (D9).

### 3.5 Effort

Sizes: S is under half a day, M is half a day to 2 days, and L is 2–5 days (agent-assisted
working days, including tests and docs).

| Piece | Size | Notes |
| --- | --- | --- |
| Retire morpheus: tag, remove the tree, retrospective doc, tests and CI, README and `AGENTS.md` | S | D1 |
| Retire the grimoire umbrella and promote mnemosyne to featured | S | D2 |
| Mnemosyne hardening (§1.2 items 1–5) | M | D3 |
| Commands → skills (3 left once morpheus is gone) | S | |
| Neutralize amphion text and its config path (with fallback); carry out the D9 outcome for `sync-claude-md` | S–M | D9 ruled: retire + doc-pointer CI check + "leaf, not root" rule. About 1 day net over the rename this row first assumed |
| `catalog.json` + neutral agent, instructions and MCP layout | S | |
| `install.py` core: generalize Zethus's engine, four host strategies, both scopes, manifest uninstall, merged-file blocks, host-CLI preference | L | The bulk of stage 2 |
| Installer tests: 4 hosts × 2 scopes × install / re-run / edit / uninstall, with `PLATFORM` patched for 3 OSes | M | |
| Plugin and marketplace manifests + drift check | S | |
| Port Zethus to Claude, Codex and Cursor (agent transforms, instructions mapping, path rewrites) | M | D7; skip to save about 2 days |
| Stage 2 verification of the §2.4 unknowns against real installs of each host | S–M | Needs each host installed locally |
| Docs sweep: README, `AGENTS.md`, `docs/platforms.md`, per-bundle READMEs | S–M | |
| **Total** | **about 7–10 days** | Includes D9 option 1 (about 1 day) and the Zethus port (about 2 days, D7) |

**Sequencing:** first PR #36 (the rename) lands. Then:

1. retirements (D1 and D2) and mnemosyne correctness fixes;
2. the neutral layout and `catalog.json`;
3. the installer and its tests;
4. manifests and marketplaces;
5. the Zethus port;
6. the docs sweep.

Each step is its own PR into `develop`.

---

## 4. Decisions for Ceryce

Each decision lists the recommended option first. **All ten are ruled.**

### Rulings (2026-09-30)

Ceryce, by Telegram at 16:46 CT, verbatim:

> "Recs. Do a deeper dive on D9, we found a lot of context bloat from Claude.md files was coming from
> that skill without much benefit. It was originally designed to keep all of the documentation in
> sync, but it wasn't doing a good job at that."

After the deep dive, Ceryce answered the D9 picker at 16:59 CT, verbatim: **"Retire + CI check +
rule"**.

| Decision | Status |
| --- | --- |
| D1–D6, D8, D10 | **Ruled: recommended option** ("Recs.") |
| D7 (multi-select) | **Ruled: the three recommended options** (1, 2 and 3) |
| D9 | **Ruled: option 1** ("Retire + CI check + rule"), after the [deep dive](#appendix-a-d9-deep-dive-does-sync-claude-md-earn-its-place) |

### D1: The fate of morpheus

1. **Retire *(recommended)*:** tag it, remove it from `develop`, and write a short retrospective.
   It never ran, the hosts now cover the need, and the only consumer has a better version.
2. Freeze in place with an ARCHIVED banner. This keeps portfolio visibility but ships known-broken
   code in a showcase repo.
3. Fix and keep, Claude Code only: about M (2–3 days) of P0 fixes, and still a second writer
   racing native auto-memory.
4. Fix and port to all four hosts: L per host, duplicating native memory features.

### D2: The grimoire umbrella

1. **Retire the package and plugin *(recommended)*.** The name lives on as the repo and the
   installer.
2. Keep it as a thin alias for mnemosyne. That is a second name for the same seven tools.
3. Keep it as is. This only makes sense if D1 is option 3 or 4.

### D3: Mnemosyne

1. **Keep and harden *(recommended)*:** atomic writes, truthful install, drop the dead nudge,
   `promote` parity, then find one real consumer.
2. Keep it frozen: fix only the atomic-write bug.
3. Retire it too. It has no users, but it is the most portable piece in the repo.

### D4: The mnemosyne install story (`pip install` is currently false)

1. **Document `git+https://…#subdirectory=` installs now; defer PyPI *(recommended)*.**
2. Add a tagged PyPI release workflow (M, plus you own a PyPI project).
3. Drop pip entirely and install only via `install.py` and plugins.

### D5: Source-of-truth format

1. **agentskills.io `SKILL.md` + neutral agent and instruction files + one `catalog.json`, with
   per-host transforms at install time *(recommended)*.** Nothing generated is committed except the
   plugin and marketplace manifests, which get a CI drift check.
2. Commit generated per-host trees under `dist/<host>/` with a CI drift check. You can browse the
   output on GitHub, but it multiplies files by four and every change touches several copies.
3. Adopt an existing third-party cross-agent converter. This pass did not evaluate any; it would
   add a non-stdlib dependency to a stdlib-only repo.

### D6: Installer language and shape

1. **One stdlib Python `install.py`, grown from `zethus/install.py`, plus optional 10-line
   `install.sh` and `install.ps1` shims *(recommended)*.** It is one implementation and already
   tested, and the repo already requires Python.
2. Paired `install.sh` and `install.ps1` implementations: two codebases to keep in sync, and JSON
   and TOML merging in shell is fragile.
3. A Node or `npx` installer: a new runtime dependency for a Python repo.

### D7: Which artifacts to port where (multi-select)

1. **amphion → all four hosts *(recommended)*:** pure markdown, only a text and config-path
   cleanup.
2. **mnemosyne → all four via skill + MCP; hooks on Claude Code and Codex only *(recommended)*:**
   Copilot and Cursor either lack per-prompt context injection or have it unverified.
3. **Zethus → Claude Code and Cursor now, Codex later *(recommended)*.** Claude and Cursor agent
   formats are near-identical Markdown. Codex needs a TOML agent and an `AGENTS.md` block. Zethus
   stays Copilot-first.
4. Zethus stays Copilot-only. This saves about 2 days.

### D8: The duplicate `pr-description` skill (amphion and Zethus)

1. **Rename Zethus's to `zethus-pr-description` *(recommended)*.** Zethus's other skills are
   process-specific, and amphion's is the general one.
2. Rename amphion's.
3. Leave both and rely on plugin namespacing. That only works for plugin installs, not for
   `~/.agents/skills`.

### D9: The fate of `sync-claude-md` (ruled: option 1)

The stage-1 draft treated this as a naming question. Ceryce asked for evidence first, and the
[deep dive](#appendix-a-d9-deep-dive-does-sync-claude-md-earn-its-place) changes the
recommendation. In short: across every run that can still be found, the skill mostly **added**
text, always to a repo-root `CLAUDE.md`, and caught very little real drift.

**Ruled 2026-09-30: option 1** ("Retire + CI check + rule").

1. **Retire it and replace it with a mechanical check and a written rule *(recommended; ruled)*.**
   - Delete both copies: amphion's, and the user-level one that actually runs.
   - Ship a stdlib doc-pointer lint as a blocking CI step. It fails on links and backticked paths
     that no longer resolve.
   - Add a "leaf, not root" rule to `AGENTS.md` and to amphion's pipeline docs. It also bans
     volatile state (statuses, counts, dates, phase lists) from any auto-loaded instruction file.
   - Cost: S–M, about 1–2 days. Amphion drops to six skills.
2. Retire it outright with nothing in its place. Cost: under half a day. It gives up nothing the
   evidence shows it provided, but it leaves dangling pointers undetected and "where does the
   detail go" unwritten.
3. Rewrite it as a router-only pruner. It would only remove or relocate detail from a root to a
   leaf and report drift, never add. Cost: M, about 2–3 days. The one pruning pass on record worked
   but did not stick, and it hands an agent the power to delete context.
4. Keep and rename it (the stage-1 recommendation): `sync-agent-docs` plus a one-release alias.
   Cost: S. It ports to four hosts a skill whose measured yield was 3 real in-place fixes in 24
   edits.

### D10: The repo's own maintainer guidance

1. **`AGENTS.md` canonical, `CLAUDE.md` = `@AGENTS.md` *(recommended)*.** It reaches all four
   hosts with no duplication.
2. Keep `CLAUDE.md` and add `CLAUDE.md` to Codex's fallback filenames. Copilot and Cursor already
   read it, but this needs per-machine Codex config.
3. Both files with duplicated content: this will drift.

---

## 5. Sources

All read **2026-09-30**. Every `developers.openai.com/codex/*` URL now redirects (308) to
`learn.chatgpt.com`; the redirected pages are cited. IDs marked \* in §2.1 came back from the fetch
tool summarized rather than verbatim.

### Claude Code (`https://code.claude.com/docs/en/…`)

- [C1] <https://code.claude.com/docs/en/memory>
- [C2] <https://code.claude.com/docs/en/skills>
- [C3] <https://code.claude.com/docs/en/sub-agents>
- [C4] <https://code.claude.com/docs/en/hooks>
- [C5] <https://code.claude.com/docs/en/mcp>
- [C6] <https://code.claude.com/docs/en/plugins-reference>
- [C7] <https://code.claude.com/docs/en/plugin-marketplaces>
- [C8] <https://code.claude.com/docs/en/plugins/install>
- [C9] <https://code.claude.com/docs/en/sessions> and <https://code.claude.com/docs/en/claude-directory>
- [C10] <https://code.claude.com/docs/en/headless>

### GitHub Copilot: docs.github.com

- [G1] <https://docs.github.com/en/copilot/how-tos/configure-custom-instructions/add-repository-instructions>
- [G3] <https://docs.github.com/en/copilot/concepts/agents/about-agent-skills>
- [G4] <https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/create-custom-agents-for-cli>
- [G5] <https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions>
- [G6] <https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills>
- [G7] <https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers>
- [G8] <https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference>
- [G9] <https://docs.github.com/en/copilot/reference/custom-agents-configuration>
- [G12] <https://docs.github.com/en/copilot/reference/hooks-reference>
- [G15] <https://docs.github.com/en/copilot/how-tos/use-copilot-agents/coding-agent/extend-coding-agent-with-mcp>
- [G16] <https://docs.github.com/en/copilot/concepts/agents/copilot-cli/about-cli-plugins>
- [G17] <https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-programmatic-reference>
- [G19] <https://docs.github.com/en/copilot/how-tos/copilot-cli/use-copilot-cli/chronicle>
- [G21] <https://docs.github.com/en/copilot/concepts/agents/copilot-memory>

### GitHub Copilot: VS Code

- [V1] <https://code.visualstudio.com/docs/copilot/customization/custom-instructions>
- [V2] <https://code.visualstudio.com/docs/copilot/customization/prompt-files>
- [V3] <https://code.visualstudio.com/docs/copilot/customization/custom-agents>
- [V4] <https://code.visualstudio.com/docs/copilot/customization/agent-skills>
- [V5] <https://code.visualstudio.com/docs/copilot/customization/hooks>
- [V7] <https://code.visualstudio.com/docs/copilot/customization/mcp-servers>
- [V8] <https://code.visualstudio.com/docs/copilot/customization/agent-plugins>

### OpenAI Codex

- [X3] <https://learn.chatgpt.com/docs/agent-configuration/agents-md>
- [X4] <https://learn.chatgpt.com/docs/agent-configuration/rules>
- [X5] <https://learn.chatgpt.com/docs/custom-prompts>
- [X6] <https://learn.chatgpt.com/docs/build-skills>
- [X7] <https://learn.chatgpt.com/codex/agent-configuration/subagents>
- [X8] <https://learn.chatgpt.com/docs/hooks>
- [X9] <https://learn.chatgpt.com/docs/extend/mcp?surface=cli>
- [X10] <https://developers.openai.com/plugins/build/plugins>
- [X11] <https://learn.chatgpt.com/docs/plugins>
- [X12] <https://learn.chatgpt.com/docs/non-interactive-mode>
- [X13] <https://learn.chatgpt.com/docs/customization/memories>

### Cursor

- [R1] <https://cursor.com/docs/context/rules>
- [R2] <https://cursor.com/help/customization/rules>
- [R4] <https://cursor.com/changelog/1-6>
- [R5] <https://cursor.com/docs/skills>
- [R6] <https://cursor.com/changelog/cli-jan-08-2026>
- [R7] <https://cursor.com/docs/subagents>
- [R8] <https://cursor.com/docs/agent/hooks>
- [R9] <https://cursor.com/docs/reference/third-party-hooks>
- [R10] <https://cursor.com/docs/mcp>
- [R12] <https://cursor.com/docs/plugins>
- [R14] <https://cursor.com/docs/cli/headless>
- [R-gap] No current Cursor docs page mentions a memory feature (searched 2026-09-30).

### Agent Skills standard

- [A1] <https://agentskills.io/specification>

---

## Appendix A: D9 deep dive: does `sync-claude-md` earn its place?

Ceryce's premise: the skill caused a lot of the `CLAUDE.md` context bloat without much benefit, and
it did not keep documentation in sync well. This appendix tests that premise against the skill
text, the transcripts and git history, not against the skill's own description. The evidence
**mostly confirms it, with one qualification that changes the fix.**

### A.1 Method and limits

- **Skill text:** both copies were read in full (§A.2).
- **Transcripts:** all 10,008 local Claude Code session transcripts were scanned (6.2 GB).
  - About 9,350 of them mention the skill's name, but only because it sits in every session's
    skill listing. Only real invocations were counted: a `Skill` tool call or a
    `/sync-claude-md` command.
  - For each run, every `Edit` or `Write` to a `CLAUDE.md` or `AGENTS.md` was collected up to the
    next genuine user prompt. Each of those edits was then classified by hand.
- **Git history:** the private assistant repository's history of its eight `CLAUDE.md` files.
  - This is the repo whose context-budget and countermeasure-binding specs measured context cost
    and findability.
  - Sizes are git-object bytes on its integration branch as of 2026-09-30.
  - A "sync-labelled" commit is one whose message mentions a sync or `CLAUDE.md` pass. This is a
    message heuristic.
- **Tokens** use the assistant repo's measured **2.59 bytes/token**. Its spec found that the usual
  4:1 estimate understates by about 1.55×.
- **Limits:**
  - Transcript retention is uneven: 9,785 of the files were last written in September. The run
    count below is a floor, not a census.
  - Everything here is aggregated. No private content is reproduced, and the repos other than
    this one are not named.

### A.2 What the skill actually tells the agent to do

There are **two different skills with the same name**, and the one this repo ships is not the one
that has been running.

| | User-level copy (`~/.claude/skills/sync-claude-md/`, 2,811 B) | amphion copy (`amphion/plugin/skills/sync-claude-md/`) |
| --- | --- | --- |
| Trigger | After an implementation phase, or whenever files moved, "branches have been merged; deliverables have shipped; or decisions have been resolved" | Only when the current diff changed code that some document describes |
| Scope | The client-folder, repo-level and workspace-root `CLAUDE.md`: **roots only**, never a sub-directory leaf | The document nominated by a `docSync.map` glob. Without config, the nearest `CLAUDE.md` or `README.md` up to the repo root |
| What it maintains | Phase branch lists, "current contents" tables, active deliverables, open decisions and blockers, and the repo structure tree. **Four of the five are volatile state** | Only lines that the diff made factually wrong |
| May it add? | Yes. The structure row said only "Add the new entries" until a 2026-09-05 patch changed it to "one-line pointer" and added a size-delta report | **No.** It rewrites in place, never appends, and reports gaps instead |

**Does the design push content into root files?**

- **The user-level copy does, by construction.** Every file in its scope is a root. It runs after
  every phase, whatever the diff. Its instruction is to make each root "reflect actual current
  state", and every phase changes that state. Growth is the expected output, not a misuse.
- **The amphion copy does not.** It was narrowed for exactly these reasons (its "Why this skill is
  narrow" section). But once narrowed, it is the author's global rule ("docs stay in sync with
  code in the same change") restated as a skill, minus appending. The agent that makes a change is
  already told to do everything it does.

### A.3 Effect on real repos: the transcripts

| Measure | Value |
| --- | --- |
| Runs found | **14**, between 2026-06-29 and 2026-07-17, across four repos: the assistant repo (8), this repo (2) and two other private project repos (4) |
| Runs that edited anything | 10. The other 4 were no-ops |
| Edits to instruction files | **24** |
| … in a repo-root `CLAUDE.md` | **24 (100%)** |
| … in a leaf, or a new leaf created | **0** |
| Net bytes added to roots | **+6,438 B, about 2,500 tokens.** This loads into every later session in those repos |
| Runs after 2026-07-17 | **0**, although the skill's ~300 B listing entry was in about 9,800 September sessions |

Each of the 24 edits, classified by hand:

| What the edit did | Edits | Net bytes |
| --- | ---: | ---: |
| **Fixed drift in place, without growing.** A tool count ("nine tools" → "ten"), a renamed test file, and a test count. The test count was a number an earlier sync run had written into the root itself | **3** | −14 |
| Corrected a statement that had become false, but grew it while doing so. Examples: a dependency claim, a transport description, a list of supported sites | 8 | +1,800 |
| **Added new detail:** feature paragraphs, directory-listing lines, dated "shipped" notes, a test count "as of" a date | **13** | **+4,652 (72%)** |

**Verdict on "not doing a good job":** confirmed. One edit in eight was a clean in-place fix. Most
of the output was new root content, including the volatile numbers that later needed their own
"fix".

### A.4 Effect on real repos: the assistant repo's git history

- **Sync passes only ever grew the root.**
  - 21 of the 555 non-merge commits that touch a `CLAUDE.md` are sync-labelled.
  - Before the 2026-09-05 patch, the 14 sync-labelled commits that touched the root added
    **+19,335 B (about 7,500 tokens)** and removed **0 B**. Not one of them made it smaller.
- **But they were not the main producer.** Those 19 KB are about **12%** of the root's gross growth
  in that period (+157.8 KB). Ordinary feature commits carried the rest, each one documenting
  itself in the root.
- **The repo's own context-budget spec reaches the same split:**
  - "Who writes it: the feature commits themselves, not a separate sync pass."
  - It names three host-side instructions: the old global "run `/sync-claude-md`" line, the global
    same-change rule (which it calls "the real producer"), and the skill's "Add the new entries"
    row (which it calls "the specific instruction that produced" the growth history).
  - "None of the three says a word about *where* the detail should land."
  - "137 merges touched the two big grounding files. 137 made them bigger. Zero made them smaller."
- **Root timeline:** 5.4 KB (06-28) → 29.2 KB (07-15) → **118.5 KB** (08-01) → trimmed to 29.8 KB
  (08-15) → 37.9 KB (09-30). The current size is over its own budget.
- **The growth moved down a level; it did not stop.**
  - The "put the detail in the leaf, not the root" rule landed on 2026-09-05, together with two
    one-off router rewrites that cut the sub-directory `CLAUDE.md` files from 365 KB to 59.8 KB.
  - By 09-30 those same files were back to **223.0 KB**, and one of them is 158 KB.
  - The skill did not run once in that period.
  - Nested `CLAUDE.md` files are auto-loaded instruction files too, so moving the detail into them
    moved the cost; it did not remove it.

### A.5 Did the added text buy findability?

A correction to the premise first. The **0 findability score** was measured on the assistant
repo's *docs router*, a nested `CLAUDE.md` that lists every spec. It was not measured on the root.
Both results point the same way:

- **The docs router was almost never loaded.** It loaded on 4 of 9,260 instruction-load events
  between 2026-08-05 and 08-26 (0.043%). The root loaded on 5,863 (63%).
  - A nested `CLAUDE.md` loads only when a file in its own directory is `Read`, and `grep` never
    triggers it.
- **It scored 0 on each of six words a searcher would actually type.**
- **Its byte budget never bound:** "39 raise requests, 39 grants, 0 refusals".

So text added to roots was expensive, because the root loads every session. Text added to routers
was largely not found. Neither bought much. And a size budget that is raised on request is not a
control, so it should not be ported.

### A.6 Measured against the standing rule

The rule: docs stay in sync **in the same change**; "Put the detail in the leaf, not the root … A
repo-root `CLAUDE.md` is a router: it says what exists and where to look, not how it works."

| Clause | User-level copy | amphion copy |
| --- | --- | --- |
| Same change | **No.** It is a separate pass after a phase, often its own commit. The assistant repo has 14 commits that touch only `CLAUDE.md` files | Yes. It is diff-gated |
| Detail in the leaf | **No.** Its scope is roots only, and 0 of the 24 edits touched a leaf | Neutral. It adds nothing anywhere |
| Root is a router, not "how it works" | **No.** Four of its five maintained sections are status or history | Neutral |
| Add to the root only when no pointer reaches it | Only for the structure row, and only since 09-05 | Never adds |

The amphion copy complies, but it duplicates the rule. The user-level copy contradicts it. And
neither is what actually stops bloat. The rule decides where text lands, and nothing checks that.

### A.7 What a mechanical check would and would not catch

- **The three clean fixes:**
  - The renamed test file is a dangling pointer, which a lint catches.
  - The tool count and the test count are volatile numbers. The proposed rule keeps those out of
    instruction files entirely, so there would be nothing to drift.
- **The eight grow-while-correcting edits** fixed behaviour descriptions. A lint cannot see those.
  The same-change rule already obliges the agent that changed the behaviour to fix them.
- **Prior art: the assistant repo's `check_context_pointers.py`.**
  - It is stdlib only: about 700 lines plus about 600 lines of tests.
  - It resolves each link or backticked path against the doc's directory, its ancestors, the
    tracked files and `.gitignore`, with a reasons-required allowlist.
  - It blocks in CI.
  - Its naive first version had **2.6% precision** (2 real findings of 77). 76 standing findings
    had to be cleared before it could block. A generic port should budget for that resolution
    logic from day one.

### A.8 Options

Ceryce ruled option 1 on 2026-09-30 (see [Rulings](#rulings-2026-09-30)).

| Option | Cost | What the evidence says |
| --- | --- | --- |
| **1. Retire + pointer lint + "leaf, not root" rule *(recommended; ruled)*** | S–M, about 1–2 days | Retiring loses about 3 clean fixes per 24 edits, and a lint catches the pointer class among them. The rule targets the real producer (§A.4). A lint is cheap to keep green and cannot append |
| 2. Retire, nothing in its place | Under half a day | Loses nothing measured, but leaves dangling pointers unchecked and "where does detail go" unwritten, which is the gap the assistant repo's spec identified |
| 3. Router-only pruner (remove or relocate, report, never add) | M, about 2–3 days | The one pruning pass on record cut 365 KB to 60 KB, and growth rebuilt 223 KB within 25 days. Pruning without stopping the producer is a treadmill. It also gives an agent standing permission to delete context. Better as an occasional pass on request, which needs no skill |
| 4. Keep and rename (the stage-1 recommendation) | S | This ports a 12%-yield skill to four hosts under a new name. It keeps two diverging copies alive unless the user-level one is also removed |

**Two host-side follow-ups apply to the ruling.** Neither is a change to this repo, and this PR
does neither:

1. **Delete the user-level copy.** It is the one that ran, and it is still in every session's
   skill listing.
2. **Tighten the global rule's definition of "leaf".** The detail belongs in a document that is
   not auto-loaded, such as a spec, a README or a docstring. A nested `CLAUDE.md` is a router too.
   The 09-05 rule counted the sub-directory's own `CLAUDE.md` as a leaf, and that is where the
   growth went (§A.4).

# Zethus 🪨

**A development process for GitHub Copilot, in a form Copilot can follow and enforce.** One custom
agent runs every change through research → spec → sign-off → phased implementation → tests → local
gates → a PR with evidence, and refuses to skip a stage. Ten standalone skills hold one procedure
each. Four Markdown templates and five stdlib Python scripts do the mechanical parts. It installs into
a repository's `.github/` folder, or once for your user account under `~/.copilot/` so it follows
you into every repo without changing any of them. Nothing in it is specific to one organization.

> Amphion and his twin Zethus built the walls of Thebes. Amphion played his lyre and the stones set
> themselves. Zethus carried each stone by hand and set it true. [Amphion][amphion] is the
> Claude Code pipeline. This is its Copilot twin: same walls, the other brother's method.

## The procedure

```mermaid
flowchart LR
    O["0 · Orient<br/><i>fresh base</i>"] --> R["1 · Research<br/><i>facts cited to file:line</i>"]
    R --> S["2 · Spec<br/><i>minimum or full</i>"]
    S --> SO{{"sign-off"}}
    SO -->|"decisions → ADRs"| I["3 · Implement<br/><i>one phase; Phase 0 changes nothing</i>"]
    I --> T["4 · Tests<br/><i>incl. refusals · mutation check</i>"]
    T --> G["5 · Gates<br/><i>run-local-gates</i>"]
    G --> D["6 · Docs<br/><i>docs-pointer-check</i>"]
    D --> P["7 · PR<br/><i>evidence · never self-merged</i>"]
    P -.->|"next phase"| I
    I -.->|"stuck twice"| F["fresh-eyes<br/>investigation"]
    F -.->|"ranked leads"| I
```

The agent states which stage and step it's on at the top of every reply, and keeps its plan visible
throughout (see [Seeing the plan](#seeing-the-plan)). It asks decisions as a short list
of options with the recommendation first and marked, and it records each answer as an ADR. Its
refusals are written into the agent file as a table. "Skip the spec" gets the minimum spec, about
ten minutes. "Just push, CI will tell us" gets the local gates. "Merge it" gets a no: a person
merges, only on green. One narrow exemption is written down too. A change with no behaviour change
(a typo, a comment, formatting) may skip research, spec and tests, but never gates, docs or the PR.

### Seeing the plan

On starting, and on entering each stage, the agent writes the plan before doing the stage's work.
The plan is the stage map (done, current, still to come) plus the current stage's concrete steps,
each worded so you can tell what "done" means. Exactly one step is in progress at a time. A step is
ticked the moment it's done. When the plan changes, the list changes in the same turn and the reply
says what changed and why. A stage isn't exited while any of its steps is open, unless the step was
dropped with a reason you've seen.

Where you see it depends on the Copilot surface, because only some of them render the `todo` tool:

| Surface | `todo` tool | Where the plan shows |
|---|---|---|
| VS Code agent mode | Supported ([GitHub][gh-agents-config]); the list shows at the top of the Chat view. It shipped as experimental in 1.103, behind `chat.todoListTool.enabled` ([VS Code][vsc-todo]) | The todo list. Each reply's header names the current step, and the full checklist appears in the reply only on the turn the plan is written or changes. |
| Copilot CLI | Not documented as supported, and reported to resolve to nothing ([copilot-sdk#1641][cli-todo]) | The checklist under the header of every reply |
| JetBrains agent mode | Not documented either way | Whichever the agent has. If it has the tool but you can't see a list, say so once, or set `plan.checklist` to `"always"` |
| Copilot cloud agent | "Not supported in cloud agent today" ([GitHub][gh-agents-config]) | The checklist under the header of every reply |

The checklist looks like this, directly under the header line:

```markdown
Stage 3 · Implement — Phase 1, step 2 of 4: wire `retryLimit` into the retry loop

✓ 0 Orient · ✓ 1 Research · ✓ 2 Spec · **▶ 3 Implement** · 4 Tests · 5 Gates · 6 Docs · 7 PR

- [x] Add `retryLimit` to the config loader, default 3; a test reads it back
- [ ] ▶ Wire `retryLimit` into the retry loop in `RetryingClient.send`
- [ ] Log the attempt number at WARN on each retry
- [ ] Flag anything outside Phase 1's scope in the *As built* list
```

Where the todo tool is shown, the agent doesn't repeat the full list in every reply. Two copies of
the same list would be noise, and the step named in the header is enough to tie a reply to the
plan. `plan.checklist: "always"` turns the copy back on.

**No script checks the plan.** The kit's scripts check the repository, and the plan lives in the
chat. A script could check a plan file the agent wrote, but not that you saw it, so a green result
would vouch for the wrong thing. The plan is held instead the way the rest of the procedure is: a
rule in the agent file, a stage exit condition (no open steps), a row in the refusal table, and a
header on every reply that names the step, so a missing plan shows straight away.
[`tests/test_zethus.py`](../tests/test_zethus.py) pins those rules into the agent file.

## What's in the kit

| File | Installs to | Purpose |
|---|---|---|
| [`copilot-instructions.md`](copilot-instructions.md) | `.github/copilot-instructions.md` | The standing rules, short and imperative. Copilot loads them for every request in the repo. |
| [`instructions/docs.instructions.md`](instructions/docs.instructions.md) | `.github/instructions/` | Path-scoped rules (`applyTo: "**/*.md"`): Markdown is canonical, router vs leaf docs, pointers resolve, spec status vocabulary, ADRs superseded rather than rewritten. |
| [`agents/zethus.agent.md`](agents/zethus.agent.md) | `.github/agents/` | **The enforcer.** The stage table with exit conditions, the visible plan, per-turn behaviour, and the refusal table. |
| [`skills/research-existing-code`](skills/research-existing-code/SKILL.md) | `.github/skills/` | Facts cited to `file:line`, the search behind every negative claim, and what the research did *not* cover. |
| [`skills/write-spec-minimum`](skills/write-spec-minimum/SKILL.md) | `.github/skills/` | The one-screen spec for one PR, and the fast path when someone says "just code it". |
| [`skills/write-spec-full`](skills/write-spec-full/SKILL.md) | `.github/skills/` | Verbatim ask, measured problem, facts, assumptions checked, options, phases, rollback, out of scope, open questions, then stop for sign-off. |
| [`skills/write-adr`](skills/write-adr/SKILL.md) | `.github/skills/` | One imperative decision sentence, options, consequences, *enforced where*, *revisit when*. Pastes cleanly into a wiki or ticket. |
| [`skills/fresh-eyes-investigation`](skills/fresh-eyes-investigation/SKILL.md) | `.github/skills/` | Artifact plus one line of intent in; ranked leads out, each established or conjecture. Never a diagnosis; an empty list is valid. |
| [`skills/implement-phase`](skills/implement-phase/SKILL.md) | `.github/skills/` | One phase per branch (or per commit series, in `rebase` style), Phase 0 first. Stay inside the phase; classify anything unplanned; keep an *As built* list. |
| [`skills/test-plan`](skills/test-plan/SKILL.md) | `.github/skills/` | Per-phase tests covering the change, the failure path, the refusal, and what must not change, plus a mutation check. |
| [`skills/pre-push-gates`](skills/pre-push-gates/SKILL.md) | `.github/skills/` | Every CI gate run locally, on the working tree, before a push. A skip is not a pass. |
| [`skills/zethus-pr-description`](skills/zethus-pr-description/SKILL.md) | `.github/skills/` | An evidence-first PR body diffed against the real integration branch, including *What was not checked*. |
| [`skills/docs-sync-check`](skills/docs-sync-check/SKILL.md) | `.github/skills/` | Fix the docs that describe the changed code in the same PR, in place. Leave every other doc alone. |
| [`templates/spec-full.md`](templates/spec-full.md) · [`spec-minimum.md`](templates/spec-minimum.md) | `.github/zethus/templates/` | Both spec shapes. The minimum spec's headings are a strict subset of the full spec's, so promoting one only adds sections. A test enforces this. |
| [`templates/adr.md`](templates/adr.md) | `.github/zethus/templates/` | The ADR record: a field table (including *Enforced where*), decision, context, options, consequences. |
| [`templates/pr.md`](templates/pr.md) | `.github/zethus/templates/` | The PR body: What · Why · Changes · Evidence · What was not checked · deferrals · decisions · docs · AI assistance. |
| [`scripts/run-local-gates.py`](scripts/run-local-gates.py) | `.github/zethus/scripts/` | Discovers and runs lint/build/test, then prints a PASS/FAIL/SKIP table and an explicit verdict. Prefers a repo's `mvnw`/`gradlew` wrapper; on Windows a bare `mvn` or `./mvnw` resolves to `mvn.cmd`/`mvnw.cmd` through `PATHEXT`. Exit codes: `0` full green · `1` red · `3` green but incomplete · `2` nothing to run. |
| [`scripts/base-freshness.py`](scripts/base-freshness.py) | `.github/zethus/scripts/` | Fetches, counts the commits in `HEAD..origin/<base>`, and stops the stage if there are more than `branchModel.maxBehind`. Prints the merge-base to diff against, and whether the branch was rewritten since its last push. The agent runs it at the start of every stage. Exit codes: `0` fresh · `1` stale, rebase first · `2` usage error · `3` no answer (the fetch failed). |
| [`scripts/new-adr.py`](scripts/new-adr.py) | `.github/zethus/scripts/` | Creates `docs/adr/YYYY-MM-DD-slug.md` and adds its row to the ADR index. Ids are keyed by date, so parallel branches never collide. |
| [`scripts/new-spec.py`](scripts/new-spec.py) | `.github/zethus/scripts/` | `new-spec.py full\|minimum "Title"` creates `docs/specs/<slug>.md` as `DRAFT`. |
| [`scripts/docs-pointer-check.py`](scripts/docs-pointer-check.py) | `.github/zethus/scripts/` | Fails on relative Markdown links that don't resolve, including case mismatches that only break on Linux. With `--sync-base`, it also lists docs whose described code changed (report-only). |
| [`zethus.config.example.json`](zethus.config.example.json) | `.github/zethus.config.json` | Project facts: integration branch, gate commands, spec and ADR dirs, the doc-to-code map, the AI co-author trailer. |
| [`install.py`](install.py) | — | Copies all of the above into place: into a repo (`--target`) or for your user account (`--user`, with `--uninstall`). Never clobbers a file it didn't write, and writes nothing if there are conflicts. |

The scripts are Python 3.10+ standard library only. There are no PowerShell twins: Python runs
natively on Windows, and a second implementation would be a second thing to drift.

## Install

There are two modes. Pick one per machine and repo; they don't need each other.

| | Repo mode (`--target`) | User mode (`--user`) |
|---|---|---|
| Where it goes | The repo's `.github/`, committed | `~/.copilot/`, on your machine only |
| Who gets it | Everyone who clones the repo, plus the Copilot cloud agent | You, in every repo you open |
| Changes the repo | Yes: a PR adding `.github/` files | No. Optional per-repo config stays untracked |
| Right when | The team adopts the process | You may not commit to `.github/`, or you want it everywhere |

### Install into a repository

```bash
git clone https://github.com/kumouri/mesmer-grimoire.git
python mesmer-grimoire/zethus/install.py --target path/to/your-repo --dry-run   # see the plan
python mesmer-grimoire/zethus/install.py --target path/to/your-repo
```

Then, in the target repo:

1. Edit `.github/zethus.config.json`. Set `gates.steps` to mirror your CI workflow, gate for gate.
   `run-local-gates.py --list` shows what it would run.
2. Commit the `.github/` changes in a PR like any other change.
3. In your Copilot chat, pick the **zethus** agent to run the whole procedure. Or invoke a single
   skill, such as `/write-spec-minimum` or `/fresh-eyes-investigation`, on its own.

If the repo already has a `.github/copilot-instructions.md`, the installer leaves it alone and
installs the rules as `.github/instructions/zethus.instructions.md` with `applyTo: "**"`. Copilot
combines path-specific and repository-wide instructions, so both apply. Copying by hand works too:
the *Installs to* column above is the whole mapping.

Repo mode never deletes anything. If you are upgrading a repo from a kit where the PR skill was
called `pr-description`, delete `.github/skills/pr-description/` in the same PR, unless it is
Amphion's skill of that name. User mode removes files that left the kit by itself.

### Install for your user account (every repo, no commit)

```bash
python mesmer-grimoire/zethus/install.py --user --dry-run   # see the plan
python mesmer-grimoire/zethus/install.py --user
python mesmer-grimoire/zethus/install.py --user --uninstall # later, to remove it
```

Add `--jetbrains-legacy` only for an older JetBrains Copilot plugin that doesn't read
`~/.copilot/instructions` (see the support table below).

| Kit piece | User-mode location |
|---|---|
| Working agreement (`copilot-instructions.md`) | `~/.copilot/instructions/zethus.instructions.md`, with `applyTo: "**"`. Your own `~/.copilot/copilot-instructions.md` is left alone. |
| `instructions/docs.instructions.md` | `~/.copilot/instructions/zethus-docs.instructions.md` |
| `agents/zethus.agent.md` | `~/.copilot/agents/` |
| `skills/<name>/` | `~/.copilot/skills/<name>/` |
| Templates, scripts | `~/.copilot/zethus/templates/`, `~/.copilot/zethus/scripts/` |
| Example config | `~/.copilot/zethus/config.example.json`, for reference only |
| Working agreement, for older JetBrains builds | Only with `--jetbrains-legacy`: `global-copilot-instructions.md` in JetBrains' Copilot folder, and only if you don't have one |

The installed Markdown is rewritten on the way. Every `.github/zethus/…` path becomes the absolute
path of your user-level copy, and each mention of the config lists the full resolution order
below. So the agent and skills run `python <home>/.copilot/zethus/scripts/run-local-gates.py`
from any repo.

The user install is careful about your files:

- **A file it didn't write is never overwritten**, even with `--force`. If you already have a
  `~/.copilot/skills/zethus-pr-description/`, for example, it stops, lists the clash, and writes nothing.
- Every file it writes is recorded with its SHA-256 in `~/.copilot/zethus/install-manifest.json`.
  Re-running it upgrades the files you haven't edited. A kit file you *have* edited is a conflict
  unless you pass `--force`.
- `--uninstall` removes only the manifest's files that you haven't edited (`--force` removes
  edited ones too), then any folders that became empty. Your own files, including
  `~/.copilot/zethus/config.json`, stay.
- It writes no `config.json`. A user default holding example gates would override discovery in
  every repo, so `npm run lint` would run in a Maven project.

`~/.copilot` is used even when `COPILOT_HOME` is set. Only the Copilot CLI honours that variable, so
a kit installed there would be invisible to VS Code and JetBrains.

#### Which Copilot clients read the user-level files

VS Code and the CLI were checked against GitHub's and VS Code's documentation in September 2026.
The JetBrains column rests on something stronger than the docs: a user's own IntelliJ settings
screen (below). User-level files are local, so **the Copilot cloud agent on github.com never sees
them**; it needs repo mode.

| Piece | VS Code Copilot Chat | Copilot CLI | JetBrains (IntelliJ etc.) |
|---|---|---|---|
| Agent, `~/.copilot/agents/` | Yes ([docs][vsc-agents]) | Yes ([docs][cli-ref]) | Yes: a default location in the settings screen ([changelog][jb-agents] agrees) |
| Skills, `~/.copilot/skills/` | Yes ([docs][vsc-skills]) | Yes ([docs][cli-skills]) | Yes: a default location in the settings screen ([docs][gh-skills] agree). Older builds: see bug #1517 below |
| Instructions, `~/.copilot/instructions/*.instructions.md` | Yes ([docs][vsc-instructions]) | Yes ([docs][cli-instr]) | Yes: a default location in the settings screen. The docs still describe only `global-copilot-instructions.md` ([docs][jb-instr]) |
| JetBrains `global-copilot-instructions.md` (`--jetbrains-legacy` only) | — | — | Windows: `%LOCALAPPDATA%\github-copilot\intellij\`. macOS: `~/.config/github-copilot/intellij/`. **Linux: not documented**, so the installer skips it and says so ([docs][jb-instr]) |

**The JetBrains evidence.** In September 2026, the IntelliJ Copilot settings page *Tools → GitHub
Copilot → Customizations* listed these default locations, all enabled. The plugin version wasn't
visible, so it is unknown which build introduced them.

| Setting | Default locations |
|---|---|
| Instruction File Locations (`*.instructions.md`) | `.github/instructions`, `~/.copilot/instructions` |
| Agent File Locations (`*.agent.md`) | `.claude/agents`, `.github/agents`, `~/.copilot/agents` |
| Skill File Locations (folders of `SKILL.md`) | `.agents/skills`, `.claude/skills`, `.github/skills`, `~/.agents/skills`, `~/.claude/skills`, `~/.copilot/skills` |
| Prompt File Locations (`*.prompt.md`) | `.github/prompts`, `~/.copilot/prompts` |
| Hook File Locations (`*.json`) | `.github/hooks`, `~/.copilot/hooks` |

The same page has toggles for organization instructions, `AGENTS.md` and `CLAUDE.md` (nested
variants experimental), plus a *Plugin Marketplaces* list.

**Older JetBrains builds.** Before this settings page, the docs described one global instructions
file, `global-copilot-instructions.md`, and no `~/.copilot/instructions` ([docs][jb-instr]). An open
report says user-level `.copilot` skills weren't detected on Windows ([#1517][jb-skills-bug]). If
your plugin has no *Customizations* page, or the kit doesn't show up:

- update the plugin; or
- re-run with `--jetbrains-legacy` to also write `global-copilot-instructions.md`.

Don't use the flag on a current build. Copilot would then read the working agreement twice, once
from each file.

Sources, with the sentence each claim rests on:

- [VS Code: custom agents][vsc-agents]: Agent Host reads agents "from the selected host's folder",
  `~/.copilot/agents` or `~/.claude/agents`.
- [VS Code: agent skills][vsc-skills]: personal skills in `~/.copilot/skills/`, `~/.claude/skills/`
  or `~/.agents/skills/`.
- [VS Code: custom instructions][vsc-instructions]: "For personal, always-on instructions in Copilot
  Agent Host sessions, use `~/.copilot/copilot-instructions.md`", and "User instructions in Agent
  Host folders, such as `~/.copilot/instructions` … do not roam through Settings Sync."
- [VS Code: Copilot settings reference][vsc-settings]: the defaults of `chat.agentFilesLocations`,
  `chat.agentSkillsLocations` and `chat.instructionsFilesLocations`, each deprecated and used only
  by the Local agent.
- [Copilot CLI: customization reference][cli-ref]: user agents in `~/.copilot/agents/` load first.
- [Copilot CLI: add skills][cli-skills]: personal skills in `~/.copilot/skills` or `~/.agents/skills`.
- [Copilot CLI: add custom instructions][cli-instr]: `$HOME/.copilot/copilot-instructions.md` and
  `$HOME/.copilot/instructions/**/*.instructions.md`; `COPILOT_HOME` replaces `$HOME/.copilot`.
- [About agent skills][gh-skills]: lists `~/.copilot/skills` and `~/.agents/skills` for agent mode
  in IDEs, JetBrains included.
- [GitHub changelog, 2026-05-13][jb-agents]: in JetBrains, "define custom agents at the global level
  using the `.agent.md` file under `~/.copilot/agents`."
- [copilot-intellij-feedback #1517][jb-skills-bug]: open report that the JetBrains plugin doesn't
  detect user-level `.copilot` skills on Windows. It predates the settings screen above.
- [Repository instructions in your IDE, JetBrains tab][jb-instr]: a global
  `global-copilot-instructions.md` on macOS and Windows. The page documents no path-specific
  instruction files for JetBrains, and no Linux location. The settings screen above contradicts
  the first point for current builds.

Notes:

- VS Code has two kinds of session. **Agent Host** sessions (the Copilot or Claude harness) read
  `~/.copilot/` directly ([agents][vsc-agents], [instructions][vsc-instructions]). **Local
  agent** sessions read the folders listed in `chat.agentFilesLocations`,
  `chat.agentSkillsLocations` and `chat.instructionsFilesLocations`. All three default to include
  `~/.copilot/agents`, `~/.copilot/skills` and `~/.copilot/instructions` ([docs][vsc-settings]).
  Those settings are deprecated but still work, and they are also how you would add another folder.
- Files under `~/.copilot/` don't roam through Settings Sync ([docs][vsc-instructions]). Run the
  installer on each machine.
- In JetBrains, the settings page above is where to look if the **zethus** agent doesn't appear.
  Check that `~/.copilot/agents` and `~/.copilot/skills` are listed and enabled.
- With `--jetbrains-legacy`, an existing `global-copilot-instructions.md` is left alone. Paste the
  rules from `~/.copilot/instructions/zethus.instructions.md` into it yourself. On an older build,
  the path-scoped docs rules have no user-level equivalent.
- No current documentation lists a **repository** `.copilot/` folder for agents, skills or
  instructions; the repo-level folders are `.github/`, `.claude/` and `.agents/`. Zethus uses a
  repo's `.copilot/` only for its own untracked config (below).

#### Config for user-level use

The scripts take the first config they find. `--config` beats all of them.

| # | Location | Use it for |
|---|---|---|
| 1 | `.github/zethus.config.json` | The team's committed answers (repo mode). |
| 2 | `$ZETHUS_CONFIG` | A path, relative to the repo root unless absolute. Point it anywhere. |
| 3 | `.copilot/zethus.config.json` | Per-repo answers you may not commit. Keep it untracked (below). |
| 4 | `.claude/amphion.config.json` | Amphion's config; the shared keys mean the same thing. |
| 5 | `~/.copilot/zethus/config.json` | Your defaults for every repo, such as `commits.aiTrailer`. Leave `gates` out unless every repo you use runs the same gates. |
| — | *(none)* | Discovery from the repo's build files, then ask. |

To keep a per-repo config out of git without touching the repo's `.gitignore` (which is itself a
tracked change), use the clone's private exclude file:

```bash
mkdir -p .copilot
cp ~/.copilot/zethus/config.example.json .copilot/zethus.config.json   # then edit it
echo ".copilot/" >> .git/info/exclude
git status --short          # .copilot/ must not appear
```

In a worktree, `.git` is a file, not a folder. `git rev-parse --git-path info/exclude` prints the
exclude file to use.

For a Maven project on Windows, discovery alone gives `./mvnw.cmd -B verify` if the repo has the
wrapper, else `mvn -B verify`, which resolves to `mvn.cmd`. To mirror a CI that runs
`mvn verify`, write that gate explicitly:

```json
{ "gates": { "steps": [ { "name": "maven verify", "command": "mvn -B verify" } ] } }
```

### Configuration

Every key is optional. Where a value is missing, the scripts and agent work it out from the
repository, then ask.

Where the config file lives is covered in [Config for user-level use](#config-for-user-level-use).
The keys are the same in every location.

| Key | Used by | Meaning |
|---|---|---|
| `branchModel.base` | agent, `zethus-pr-description`, `docs-sync-check`, `base-freshness` | The integration branch. Default: `develop` if it exists, else the default branch. |
| `branchModel.style` | agent, `implement-phase`, `zethus-pr-description`, `base-freshness` | `"branch-per-change"` (default): a new branch per change, cut from the freshly fetched base, one branch and PR per phase. `"rebase"`: one long-lived branch kept rebased onto the base; phases are commit series on it, every diff is taken against the merge-base with `origin/<base>`, and the PR body says when the branch was rebased. See [Branch models](#branch-models). |
| `branchModel.maxBehind` | `base-freshness`, agent, `pre-push-gates` | How many commits the branch may be behind `origin/<base>` before a stage refuses to start. Default `0`: any commit behind means rebase first. |
| `gates.steps[]` | `run-local-gates` | Ordered `{name, command, exitCode?}`. `command` is a string or an argv list; there's no shell. |
| `gates.lint` / `.build` / `.test` / `.mandatedChecks[]` | `run-local-gates` | Amphion's gate keys, read when `gates.steps` is absent. A mandated check with only a prose `expect` shows as **MANUAL** (not checked). |
| `spec.dir`, `spec.templates.{full,minimum}` | `new-spec` | Default `docs/specs`, and the kit's templates. |
| `adr.dir`, `adr.template` | `new-adr` | Default `docs/adr`, and the kit's template. |
| `docSync.map[]` | `docs-pointer-check --sync-base` | `{doc, describes[globs]}`: which code each doc describes. Globs use `fnmatch` rules, so `*` also matches `/`. |
| `docs.pointerIgnore[]` | `docs-pointer-check` | Markdown files to skip, such as generated changelogs. |
| `commits.aiTrailer` | agent | The co-author trailer that AI-assisted commits carry. |
| `plan.checklist` | agent | `"auto"` (default): the plan goes in the todo tool where the agent has one, else as a checklist in every reply. `"always"`: the checklist goes in every reply as well, for a surface that accepts the tool but doesn't show it. See [Seeing the plan](#seeing-the-plan). |

### Branch models

Zethus assumes nothing about how long a branch lives. It insists only that the base is fresh.

| | `branch-per-change` (default) | `rebase` |
|---|---|---|
| Branches | A new one per change, cut from `origin/<base>` | One long-lived branch, rebased onto `origin/<base>` every few days |
| Phases | One branch and one PR each | One commit series each, on the same branch, Phase 0 first |
| Diff base | `origin/<base>...HEAD` | The same: the merge-base with the freshly fetched `origin/<base>`, never a local ref |
| After a rebase | — | Push with `--force-with-lease`; the PR body names the new base |

In both, the agent runs `base-freshness.py` at the start of every stage, and `pre-push-gates`
runs it before the gates. A stale base doesn't look stale. Diffs, measurements and research notes
taken on one quietly compare branch drift instead of the change, and the PR can revert work that
already landed. So the check counts commits rather than trusting the checkout. Raise
`branchModel.maxBehind` only as a recorded decision; the default of `0` means any commit behind
stops the stage.

```json
{ "branchModel": { "base": "develop", "style": "rebase", "maxBehind": 0 } }
```

## Copilot formats used, and where they're documented

The formats were checked against GitHub's and VS Code's documentation in September 2026.

| Piece | Format | Documentation |
|---|---|---|
| Repository instructions | `.github/copilot-instructions.md`, plain Markdown | [Adding repository custom instructions][gh-repo-instructions] · [support matrix][gh-instructions-support] |
| Path-specific instructions | `.github/instructions/*.instructions.md` with `applyTo` | [VS Code custom instructions][vsc-instructions] |
| Custom agent | `.github/agents/*.agent.md`: `name`, `description`, `tools` | [Custom agents configuration][gh-agents-config] · [Creating custom agents][gh-agents-create] · [VS Code custom agents][vsc-agents] |
| Skills | `.github/skills/<name>/SKILL.md`: `name` (matches the folder), `description` | [About agent skills][gh-skills] · [Creating skills][gh-skills-create] · [VS Code agent skills][vsc-skills] |

**Why skills and not prompt files.** Prompt files (`.github/prompts/*.prompt.md`) work only in
IDEs, are in public preview, and are deprecated in current VS Code in favour of skills. Skills load
in VS Code and JetBrains agent mode, the Copilot CLI, and the Copilot cloud agent, and they can be
invoked by `/name` as well as picked automatically from their description. The agent's tool list
uses GitHub's portable aliases (`read`, `search`, `edit`, `execute`, `web`, `todo`, `agent`).
Surfaces that don't support a tool ignore it; for example, `web` and `todo` aren't used by the
cloud agent, and `todo` is documented only for VS Code. The agent's plan falls back to a checklist
in its replies wherever `todo` isn't available (see [Seeing the plan](#seeing-the-plan)).

**The limit of enforcement.** Copilot has no hook that can block a tool call the way a
pre-tool-use hook can. So the agent enforces the process through its instructions, its stage
gates and its refusal table. The scripts give each stage an objective exit condition: an exit code
is harder to talk around than a sentence. Merging is protected by your platform's branch
protection, not by this kit.

## Modernization extensions

Two design specs for pluggable Zethus extensions — specialized skill families that recover
business rules from legacy source, pin exact legacy behaviour in a "constitution" before any
rewrite, and add a stage-gate overseer. The shared design and both consuming extensions now have a
v1 build:

| Doc | Targets | Status |
|---|---|---|
| [`docs/modernization-shared.md`](docs/modernization-shared.md) | The shared design both extensions build on: rule recovery, the constitution template, the overseer gate | PARTIAL — v1 built, below |
| [`docs/batch-modernization.md`](docs/batch-modernization.md) | Spring/JPA/JDBC batches, `ksh` scripts, Control-M-scheduled jobs, stored-procedure-heavy jobs; first dialect Oracle/PL-SQL | PARTIAL — v1 built, below |
| [`docs/webapp-modernization.md`](docs/webapp-modernization.md) | Struts, old Spring MVC + JSP, plain JSP/servlets, and thirteen other legacy web targets, ranked | PARTIAL — v1 built, below |

### v1 — batch modernization (Copilot CLI)

Installs the same way as the core kit, alongside it: copy the pieces below into your repo's
`.github/`, or run `install.py` (its skill/script discovery is generic — it finds these
automatically, no separate flag needed). Nothing here is required by the core ten-skill pipeline;
install it only if you're recovering rules from legacy batch source.

| Piece | Installs to | Purpose |
|---|---|---|
| [`skills/recover-business-rules`](skills/recover-business-rules/SKILL.md) | `.github/skills/` | The generic rule-recovery shape (in the manner of `research-existing-code`), aimed at legacy source |
| [`skills/dialect-oracle-plsql`](skills/dialect-oracle-plsql/SKILL.md) | `.github/skills/` | Oracle 12c-era PL/SQL reader: packages, triggers, autonomous transactions, a keep/wrap/port disposition per procedure |
| [`skills/batch-type-spring-jpa-jdbc`](skills/batch-type-spring-jpa-jdbc/SKILL.md) | `.github/skills/` | Reading guide for plain Spring JPA/JDBC batch loops — commit boundaries, restart/idempotency, skip policy — no dedicated script; see the skill for why |
| [`skills/batch-type-ksh-scripts`](skills/batch-type-ksh-scripts/SKILL.md) | `.github/skills/` | `ksh` wrapper reader: `getopts` args, exit codes, `trap`, locking, retry/backoff loops |
| [`skills/batch-type-cron-scheduler-wrappers`](skills/batch-type-cron-scheduler-wrappers/SKILL.md) | `.github/skills/` | Scheduler reader, Control-M first: dependency graph + calendar rules, mapped onto a Spring Batch flow or a cloud workflow orchestrator |
| [`templates/constitution.md`](templates/constitution.md) | `.github/zethus/templates/` | The behaviour-constitution artifact: nine fixed sections, each rule cited to the ledger |
| [`templates/fixture-manifest.example.json`](templates/fixture-manifest.example.json) | `.github/zethus/templates/` | Example shape for a golden-master fixture manifest |
| [`scripts/overseer-gate.py`](scripts/overseer-gate.py) | `.github/zethus/scripts/` | The overseer's three script-gates: constitution completeness before Implement, golden-master coverage before Tests report done, and a standing higher-environment-credential detector |
| [`scripts/hla-input-check.py`](scripts/hla-input-check.py) | `.github/zethus/scripts/` | Stops before Stage 2 unless a target HLA document with a default stored-procedure disposition is configured |
| [`scripts/plsql-ddl-intake.py`](scripts/plsql-ddl-intake.py) | `.github/zethus/scripts/` | PL/SQL DDL intake: objects, provenance, wrapped/invisible-body flags, repo-vs-live-extract drift, `DBMS_SCHEDULER`/`DBMS_JOB` batch discovery |
| [`scripts/control-m-reader.py`](scripts/control-m-reader.py) | `.github/zethus/scripts/` | Control-M job-definition reader: dependency graph, calendar rules, Spring Batch flow / Step Functions mapping |
| [`scripts/ksh-wrapper-reader.py`](scripts/ksh-wrapper-reader.py) | `.github/zethus/scripts/` | `ksh` wrapper reader used by `batch-type-ksh-scripts` |
| [`scripts/_ledger.py`](scripts/_ledger.py) | `.github/zethus/scripts/` | Shared rule-ledger and constitution parsing every script above uses |

New config keys these scripts read, all optional (see
[`zethus.config.example.json`](zethus.config.example.json)): `modernization.hlaDoc`,
`overseer.environments`, `overseer.currentEnvironment`, `overseer.credentialCheck.*`.

**Decided and unchanged from the design docs:** the overseer stays a script-gate, no second agent
("script-gates now, agent later"); this build targets the Copilot CLI, matching the base kit's own
primary validation target.

**Deferred, per the batch spec's own "ship the ask's named first target" phasing:**
`batch-type-spring-batch-xml`, `batch-type-stored-procedure-heavy`, and the `dialect-db2-sql-pl` /
`dialect-tsql` / `dialect-postgres-plpgsql` named seams — none built yet, no code or skill files
exist for them. Reporting a flagged credential to security and rotating it stay manual steps in v1;
the overseer's job stops at detection.

### v1 — legacy web-app modernization (Copilot CLI)

Installs the same way, alongside the core kit and the batch pieces above — `install.py`'s discovery
finds these automatically too. Built for this build's own first real target shape: a **hybrid** app
where Struts actions are wrapped in or invoked from Spring MVC controllers, rendering JSP views,
already part-way migrated to REST microservices plus a new frontend (the frontend and the auth
strategy are both read from the target HLA — see
[`docs/webapp-modernization.md`](docs/webapp-modernization.md#open-questions) — never a hardcoded
default).

| Piece | Installs to | Purpose |
|---|---|---|
| [`skills/webapp-target-struts`](skills/webapp-target-struts/SKILL.md) | `.github/skills/` | Struts 1.x/2.x reader: routes, form-beans/validation, session scope, `roles` authz, hybrid Spring delegation |
| [`skills/webapp-target-spring-mvc-jsp`](skills/webapp-target-spring-mvc-jsp/SKILL.md) | `.github/skills/` | Old Spring MVC + JSP reader: routes, view resolution, `@SessionAttributes`, method-security authz, hybrid Struts delegation, already-migrated-to-REST detection |
| [`skills/webapp-target-plain-jsp-servlets`](skills/webapp-target-plain-jsp-servlets/SKILL.md) | `.github/skills/` | Plain JSP + scriptlets/JSTL + servlet reader: `web.xml` routes/authz/session-timeout, inline scriptlet/JSTL logic, and the shared raw `HttpSession` scan every reader's Java sources can use |
| [`skills/webapp-strangler-planner`](skills/webapp-strangler-planner/SKILL.md) | `.github/skills/` | Groups recovered routes into cutover units — per-screen-flow where they share session state, per-route otherwise — and excludes already-migrated routes |
| [`skills/webapp-session-state-to-stateless`](skills/webapp-session-state-to-stateless/SKILL.md) | `.github/skills/` | Classifies every recovered session attribute into one of five stateless destinations, and the auth-shim decision |
| [`templates/fixture-manifest-http.example.json`](templates/fixture-manifest-http.example.json) | `.github/zethus/templates/` | Example shape for an HTTP-shaped, scripted-synthetic-walk golden-master fixture manifest, including a session-carrying fixture sequence |
| [`scripts/webapp-hla-input-check.py`](scripts/webapp-hla-input-check.py) | `.github/zethus/scripts/` | Stops before Stage 2 unless the target HLA names a frontend and an auth strategy (`shim`/`replace`) |
| [`scripts/struts-reader.py`](scripts/struts-reader.py) | `.github/zethus/scripts/` | Reader backing `webapp-target-struts` |
| [`scripts/spring-mvc-jsp-reader.py`](scripts/spring-mvc-jsp-reader.py) | `.github/zethus/scripts/` | Reader backing `webapp-target-spring-mvc-jsp` |
| [`scripts/jsp-servlet-reader.py`](scripts/jsp-servlet-reader.py) | `.github/zethus/scripts/` | Reader backing `webapp-target-plain-jsp-servlets` |
| [`scripts/strangler-planner.py`](scripts/strangler-planner.py) | `.github/zethus/scripts/` | Reader backing `webapp-strangler-planner` |
| [`scripts/_routes.py`](scripts/_routes.py) | `.github/zethus/scripts/` | Shared route-manifest shape the three readers emit and the planner consumes |
| [`scripts/_session_state.py`](scripts/_session_state.py) | `.github/zethus/scripts/` | Shared session/state ledger shape, the raw `HttpSession` scan, and the still-reads-`HttpSession` check the overseer uses |

Also extends pieces the batch v1 build shipped, rather than forking them: `templates/constitution.md`
gains two sections, **Session / state** and **Auth shim** (a batch constitution with neither marks
both "No rule found," same as any other inapplicable section); `scripts/overseer-gate.py` gains two
subcommands, `session-state` (a flow can't be marked migrated while any session attribute is
unclassified or still read from `HttpSession` by the new code) and `http-fixtures` (alongside
`golden-master`: HTTP-shaped fixtures have the fields a replay needs, and none looks like it
captured real user data).

**Decided (2026-09-28, Telegram pickers — see
[`docs/webapp-modernization.md`](docs/webapp-modernization.md#open-questions) for the full
rationale):** no hardcoded frontend default (React/Vite and Next.js stay documented guidance for
what to write into the HLA, not an assumption); strangler cutover is per-screen-flow where routes
share session state, per-route otherwise; the auth strategy is read from the HLA, with a missing
answer stopping the pipeline and recommending shim first; HTTP golden masters are a scripted
synthetic walk first, live recording deferred; targets with no clean HTTP boundary get a
constitution convention, not a new skill family.

**Deferred, per Open question 5's own recommendation:** ranked targets 4-16 (JSF, Web Flow, EJB,
SOAP, Velocity/FreeMarker, Wicket, GWT, Vaadin, Seam, Tapestry, portlets, legacy JS frontends,
app-server packaging) — no reader exists for any of them yet; live-traffic golden-master recording;
the OAuth2/OIDC auth-replacement phase itself.

## How it relates to Amphion

[Amphion][amphion] is a spec-to-PR pipeline of six Markdown skills for Claude Code. Zethus uses
the same design where they overlap, rather than duplicating it:

- **One config vocabulary.** The keys that exist in both (`gates.*`, `branchModel.base`) mean
  the same thing. `branchModel.style` and `branchModel.maxBehind` are Zethus's
  own; Amphion ignores them. When no Zethus config is found in the repo, the scripts read
  `.claude/amphion.config.json`, so a repo using both answers each question once.
- **Different stages.** Amphion covers what happens *after* the decisions: loading decided
  context, `flag-or-fix` when the spec runs out, `resume-interrupted-phase` when a delegate dies,
  `initialize-ci`, and `log-friction`. Zethus covers the *front* of the process, which Amphion
  assumes already happened: research, specs, ADRs and fresh-eyes investigation. It also covers the
  enforcement, which Amphion leaves to the operator. `implement-phase` points to Amphion's two
  exception handlers rather than re-implementing them.
- **Shared headings.** Zethus's `zethus-pr-description` keeps Amphion's *Not in this PR (intentional)*
  and *Noticed but out of scope* headings, so `flag-or-fix` deferrals land in the same place.
  `docs-sync-check` keeps the narrow rule Amphion's retired `sync-claude-md` followed: change
  only the docs that describe code this diff touched, in place.
- **Installing both.** Amphion's skills use the same `SKILL.md` format, and Copilot can load
  them. The two PR skills have different names, so both can be installed side by side:
  `zethus-pr-description` is Amphion's `pr-description` plus evidence, what was not checked, and
  decisions. Pick one per repo so the agent doesn't have to choose.

## Jira integration

Two optional, standalone skills that translate between specs and Jira stories. Like the
modernization extensions above, neither is part of the core ten and both install the same way,
alongside them. Neither writes to Jira without an explicit human approval given in the same
session — see [`docs/jira-skills.md`](docs/jira-skills.md) for what "decent" means and the full
guardrail.

| Piece | Installs to | Purpose |
|---|---|---|
| [`skills/spec-to-stories`](skills/spec-to-stories/SKILL.md) | `.github/skills/` | Turns a Markdown spec into one Jira-ready story per file plus an index, each INVEST-checked with a self-check table and a flag on any failing criterion; groups stories into epics when the spec has phases |
| [`skills/story-enrich`](skills/story-enrich/SKILL.md) | `.github/skills/` | Researches an existing Jira story against the real codebase (via `research-existing-code`, cited to `file:line`) and proposes a human-relevant enrichment plus a diff against the original |
| [`scripts/jira-access.py`](scripts/jira-access.py) | `.github/zethus/scripts/` | Detects a `jira`/`acli` CLI or a REST token in the environment. An available Jira/Atlassian MCP tool is checked by the skill itself, not this script. Exit codes: `0` CLI or REST found · `1` neither, degrade to pasted input · `2` usage error |
| [`templates/story.md`](templates/story.md) | `.github/zethus/templates/` | One story: user story statement, context, acceptance criteria, out of scope, dependencies, INVEST self-check |
| [`templates/stories-index.md`](templates/stories-index.md) | `.github/zethus/templates/` | The index a batch of stories is listed under, grouped by epic when the spec has phases |

New config keys, all optional (see [`zethus.config.example.json`](zethus.config.example.json)):
`stories.dir`, `jira.cli`, `jira.baseUrlEnv`, `jira.emailEnv`, `jira.tokenEnvVars`.

Unlike the rest of this kit, these two skills also work unmodified under Claude Code — the
`SKILL.md` format is shared between the two harnesses, see
[`docs/jira-skills.md`](docs/jira-skills.md#harness).

## Maintaining this kit

- Keep it **organization-neutral**. It must contain no company, client, or project names and no
  private paths. A project-specific fact goes in a config key, not in the text.
- Keep the skills standalone. Each one must work when invoked alone, and cross-links between skills
  are relative (`../<skill>/SKILL.md`).
- Keep the scripts stdlib-only, with no shell and no network, and cover them in
  [`tests/test_zethus.py`](../tests/test_zethus.py). That file also enforces Copilot's frontmatter
  rules on every skill, the minimum ⊂ full spec contract, and that this kit's own Markdown has no
  broken pointers.
- When a Copilot format changes, update the table above along with the files that use it.

## License

[Apache-2.0](../LICENSE) © 2026 Ceryce Armstrong

[amphion]: https://github.com/kumouri/mesmer-grimoire/tree/develop/amphion
[gh-repo-instructions]: https://docs.github.com/en/copilot/how-tos/configure-custom-instructions/add-repository-instructions
[gh-instructions-support]: https://docs.github.com/en/copilot/reference/custom-instructions-support
[vsc-instructions]: https://code.visualstudio.com/docs/copilot/customization/custom-instructions
[gh-agents-config]: https://docs.github.com/en/copilot/reference/custom-agents-configuration
[gh-agents-create]: https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/create-custom-agents
[vsc-agents]: https://code.visualstudio.com/docs/copilot/customization/custom-agents
[gh-skills]: https://docs.github.com/en/copilot/concepts/agents/about-agent-skills
[gh-skills-create]: https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/create-skills
[vsc-skills]: https://code.visualstudio.com/docs/copilot/customization/agent-skills
[vsc-settings]: https://code.visualstudio.com/docs/copilot/reference/copilot-settings
[vsc-todo]: https://code.visualstudio.com/updates/v1_103
[cli-todo]: https://github.com/github/copilot-sdk/issues/1641
[cli-ref]: https://docs.github.com/en/copilot/reference/cli-plugin-reference
[cli-skills]: https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills
[cli-instr]: https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions
[jb-agents]: https://github.blog/changelog/2026-05-13-introducing-copilot-cli-agent-and-unified-sessions-view-in-github-copilot-for-jetbrains-ides/
[jb-skills-bug]: https://github.com/microsoft/copilot-intellij-feedback/issues/1517
[jb-instr]: https://docs.github.com/en/copilot/how-tos/configure-custom-instructions-in-your-ide/add-repository-instructions-in-your-ide?tool=jetbrains

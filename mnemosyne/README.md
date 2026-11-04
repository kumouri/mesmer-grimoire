# Mnemosyne

**A generic, git-backed reflexion memory for agent pipelines.** An agent (or a team) captures
durable *lessons* from its work, recalls the relevant ones into future work, and governs
promotion of local lessons to a shared, PR-reviewed store. It implements the Reflexion loop
([Shinn et al., 2023](https://arxiv.org/abs/2303.11366)) with a domain-agnostic, config-driven
recall engine and five hygiene mechanisms that keep signal above noise.

> Named for Mnemosyne, the Greek titaness of memory.

The engine is **stdlib-only Python** (no runtime dependencies) and uses **git as both the store
and the distribution channel**. It ships in three forms — a **CLI/library**, a **Claude Code
plugin**, and an **MCP server** — all over the same engine.

## The loop

```
        recall relevant lessons                 reflect feedback into a lesson
   (before you plan/implement) ──▶ apply ──▶ do the work ──▶ (a real, reusable miss)
              ▲                                                        │
              └──────────────── promote (local ▶ shared, human-reviewed) ◀┘
```

- **Recall** durable lessons for the task and **apply** them.
- **Announce** which lessons you applied (transparency — never silent memory).
- **Reflect / capture** when a real, reusable lesson emerges.
- **Promote** a good local lesson so the team gets it (a human reviews the PR).

## Install

### GitHub Copilot: the plugin

For VS Code, IntelliJ and the Copilot CLI, the plugin is the default way to get the hooks. Add the
marketplace `kumouri/mesmer-grimoire#main` and install **mnemosyne** from it. Pin `#main`: the
repo's default branch is `develop`, which would serve unreleased work.

```bash
copilot plugin marketplace add kumouri/mesmer-grimoire#main
copilot plugin install mnemosyne@mesmer-grimoire
```

[Zethus's README](../zethus/README.md#install-the-plugin-default) has the VS Code and IntelliJ
steps. A plugin can't install a Python package, so run the installer below as well: it sets up the
package, the memory repo and `MNEMOSYNE_REPO`, and the hooks stay silent without them. On Copilot:

- The plugin brings the `reflexion-memory` skill and every hook. The `/recall`, `/reflect` and
  `/promote` commands are Claude Code's, so run the `mnemosyne` CLI instead.
- **Recall doesn't reach the model from a hook yet.** The bridge prints plain text, which Copilot
  drops (spec §4.7.1, E2), so it runs and its result is lost. Sync and shadow capture work. Until
  Phase 2 changes the output shape, use the skill or `mnemosyne recall`.
- `install.py --user` finds a plugin the Copilot CLI recorded and skips `~/.copilot/hooks`, and
  `--migrate-to-plugin` removes hook files from an earlier `--user` run. `--target` still writes a
  repo's files, for teammates and the cloud agent, which never loads a user's plugins. If two
  registrations do fire, the guard below lets one through.

### One step: the installer

From a clone, one command sets up everything the hooks need:

```bash
git clone https://github.com/kumouri/mesmer-grimoire.git
python mesmer-grimoire/mnemosyne/install.py --dry-run     # see the plan
python mesmer-grimoire/mnemosyne/install.py
```

It does these things:

1. **Package.** It pip-installs the package for the Python the hooks run, which is `python` on
   PATH unless you pass `--python`.
2. **Memory repo.** It creates `~/repos/mnemosyne-local` with `mnemosyne init`, `git init` and a
   first commit, and no remote. `--repo PATH` picks another folder. If `MNEMOSYNE_REPO` already
   names a memory repo, that repo is used. An existing memory repo is never written to.
3. **`MNEMOSYNE_REPO`.** It sets the variable persistently, so hooks find the repo with no manual
   step. On Windows it goes in the user environment, which new terminals and apps see. Elsewhere
   it goes in a managed block in your shell's rc file.
4. **Claude Code plugin.** It copies `plugin/` into a local marketplace under `~/.mnemosyne/` and
   installs it with the `claude` CLI. A `mnemosyne` plugin you already installed from another
   marketplace is left alone, so the hooks don't fire twice.
5. **Copilot hooks for one repo.** With `--target REPO`, it also writes
   `.github/hooks/mnemosyne.json` and a copy of the bridge into that repo, for you to commit. The
   Copilot CLI runs that file; VS Code and the cloud agent read it too, but that is unverified
   (spec §4.7). The step is skipped if the repo's `.claude/settings.json` already runs the bridge,
   because the Copilot CLI would then fire it twice.
6. **Copilot hooks for every repo.** With `--user`, it writes the same two files to
   `~/.copilot/hooks/`. `--copilot-hooks-dir PATH` writes them to a folder of your choosing
   instead, such as an extra one you added in the IntelliJ Copilot plugin's settings. These commands
   name the script by absolute path, so the file belongs to this machine: don't commit it. The
   IntelliJ plugin reads `~/.copilot/hooks`; other hosts are unverified (spec §4.7).

**Both hook files at once are safe.** A repo with its own `.github/hooks/mnemosyne.json` doesn't
double-fire with the user-level file. The same goes for the Copilot plugin alongside
either file: every registration runs the same engine, which claims each event once, by session and
content, and the second run logs `duplicate` and stops. With capture off nothing may be written, so the
guard is off too, and each file runs recall.

Re-running it is safe: finished steps print `same` or `keep`, and the package is refreshed from
the clone. It checks everything before writing anything. A folder that isn't a memory repo is
refused, and so is an existing `MNEMOSYNE_REPO` pointing somewhere else; `--force` repoints the
variable. A file in the user-level hook folder that the installer didn't write is never
overwritten. `--uninstall` reverses it all, using the record in
`~/.mnemosyne/install-manifest.json`, and removes only what that record lists. It never removes
the memory repo. The script's docstring has the full contract.

Zethus users can run this as part of the Zethus install:
`python mesmer-grimoire/zethus/install.py --user --with-mnemosyne` (see
[Zethus's README](../zethus/README.md#add-mnemosyne-in-the-same-step)).

**A git memory repo has one known cost, now mostly removed.** A memory repo that is a git repo
made the session-start hook spend about 300 ms on Windows in `sync`'s git calls, even with no
remote to pull from. The hook now skips `sync` when there's nothing to fetch (no remote and no
configured store). Run `mnemosyne sync` yourself after merging a review branch locally. The
timings are in the [spec's §4.7.1](../docs/lessons-capture-spec.md#471-hook-cells-checked-on-real-installs-2026-11-01).

### By hand

Pick whichever surface fits — they all drive the same git-backed store.

Mnemosyne is **not published on PyPI yet**, so `pip install mnemosyne-reflexion` will not find it.
Install the package straight from this repository instead (Python 3.8+, no runtime dependencies):

```bash
pip install "git+https://github.com/kumouri/mesmer-grimoire#subdirectory=mnemosyne"

# with the MCP server's optional dependency:
pip install "mnemosyne-reflexion[mcp] @ git+https://github.com/kumouri/mesmer-grimoire#subdirectory=mnemosyne"
```

Append `@v<tag>` to the repository URL (before `#subdirectory`) to pin a release. From a clone,
`pip install ./mnemosyne` (or `pip install -e ./mnemosyne` to hack on it) does the same.

**1. CLI / Python library** (the foundation)

```bash
mnemosyne --repo ./my-memory init --example software-eng
```

```python
import mnemosyne as mn
mn.recall("migrating the ledger POST endpoint", stage="plan")
```

**2. Claude Code plugin** — a skill + hooks (auto-recall on each prompt, sync on session start,
and lessons capture in shadow mode, below) + `/recall`, `/reflect`, `/promote` commands. The
installer above is the supported way in: it builds a local marketplace and runs
`claude plugin install mnemosyne@mesmer-grimoire-local`. By hand, add this repo's marketplace with
`claude plugin marketplace add kumouri/mesmer-grimoire#main`, run
`claude plugin install mnemosyne@mesmer-grimoire`, then set `MNEMOSYNE_REPO` to your memory repo.
(The plugin's hooks import the `mnemosyne` package and its commands run the `mnemosyne` CLI, so
install it as above first. The installer leaves a plugin from another marketplace alone, so the
hooks never fire twice.)

**3. MCP server** — the same operations as MCP tools for any MCP client (install with the `[mcp]`
extra, as above). Its `promote` tool takes the same options as the CLI command: one or more ids, a
destination tier, and `push`.

```bash
claude mcp add mnemosyne -e MNEMOSYNE_REPO=/path/to/memory-repo -- python -m mnemosyne.mcp_server
```

## Quickstart (CLI)

```bash
export MNEMOSYNE_REPO=./my-memory
mnemosyne init --example software-eng           # scaffold memory/ + a config

# recall before starting work
mnemosyne recall --query "adding a new POST that mutates customer PII" --stage implement

# reflect a real failure into a lesson (lands in your local tier)
mnemosyne reflect \
  --title "Pin idempotency for every new POST endpoint" \
  --lesson "Decide the idempotency contract up front and add it as an acceptance criterion." \
  --reflection-of "A new POST double-posted on replay because idempotency was never specified." \
  --tags idempotency,replay --stage plan --confidence high

# share it with the team (moves local ▶ shared, stages a review PR)
mnemosyne promote L-0006
```

## Configuration

A `mnemosyne.config.json` (resolved from `--config`, `$MNEMOSYNE_CONFIG`,
`<repo>/mnemosyne.config.json`, or the bundled default) makes the engine domain-agnostic. It
defines the lifecycle **stages**, the recall **axes** (each with a `weight` and a `match` strategy:
`set`, `glob`, or `glob_scalar`), a controlled **vocab** + **stopwords** for extracting context
from a brief, and the enums/thresholds. Adding an axis to the config automatically adds its CLI
flag and makes it scored — **no code change**.

The fastest way to author one is the **wizard** — an interactive, self-documenting builder that
explains every setting as it asks, seeds from a preset, validates the result, and writes a config
carrying an `_about` block that documents each field (the engine ignores it):

```bash
mnemosyne wizard                       # writes <repo>/mnemosyne.config.json
mnemosyne wizard --output ./my.config.json
```

Three examples ship: `default` (minimal — tags + stages + free-text), `software-eng` (tags,
components, work-types, source-systems, services, endpoint-patterns), and `multi-store` (default
axes plus a `stores` block wiring in `team`/`enterprise` tiers — see below). Inspect the active
config with `mnemosyne config`.

A config may also declare **stores** — additional shared memory repos federated in as broader
tiers. Each store has a `tier` label, a distinct id `prefix` (so federated ids never collide), and
a git `url` (cloned into a cache by `sync`) or a `path` to an existing repo:

```json
"stores": [
  {"tier": "team",       "prefix": "T", "url": "git@github.com:org/team-memory.git"},
  {"tier": "enterprise", "prefix": "E", "url": "git@github.com:org/enterprise-memory.git"}
]
```

## Commands

| Command | What it does |
|---|---|
| `recall` | Context in → ranked, budgeted lesson digest out (the hot path). |
| `capture` / `add` | Save a decision/convention/… to the local tier. |
| `reflect` | Save a learned-from-failure lesson (needs `--reflection-of`). |
| `promote <id…>` | Propose local lesson(s) for the shared tier, or `--to <tier>` / `--from-file <manifest>` to export up to a store. Commits each lesson alone on a review branch (your working tree and branch are untouched) and prints the push step; `--push` pushes too. Merging the PR is the approval. |
| `sync` | The only network path: `git pull` the shared memory, clone or pull every configured store, and retire local originals whose review PR has merged. |
| `stores` | List configured shared stores (broader tiers) + whether each is fetched yet. |
| `render` | Regenerate `memory/LESSONS.md` from the JSONL. |
| `list` / `show` / `stats` | Browse and summarize lessons (`list --tier`/`--store`; `stats` shows counts by tier). |
| `validate` | Schema + spine consistency (exit 0 ok / 1 problems). |
| `prune` | Retire (never delete) aged / over-cap low-value lessons (dry-run unless `--apply`). |
| `hygiene` | Health report: duplicates, never-recalled, cap headroom, prune candidates. |
| `init` | Scaffold a memory repo (`--example <name>` seeds a config, e.g. `multi-store`). |
| `wizard` | Interactively build a documented `mnemosyne.config.json` (self-documenting prompts + `_about` block). |
| `config` | Print the resolved active config and its source. |
| `candidate list` / `add` / `label` / `stats` | The lessons-capture spool (shadow mode, below): list recorded candidates, add one by hand, label one `lesson` or `noise`, and show each signal's count and precision. |
| `doctor` | What the capture hooks recorded and decided, newest last, plus the spool's health. |
| `selftest` | Zero-dependency test suite. |

Everything is also available as the Python API (`mn.recall/capture/reflect/promote/export/prune/…`)
and as MCP tools.

Environment: `MNEMOSYNE_REPO` (primary repo), `MNEMOSYNE_CONFIG` (config path), `MNEMOSYNE_AUTHOR`
(lesson author; without it lessons record `unknown`, never your login name), `MNEMOSYNE_CACHE` (where url-stores are cloned; default `~/.mnemosyne/stores`),
`MNEMOSYNE_LOCK_TIMEOUT` (seconds a save waits for the store lock; default 10), and
`MNEMOSYNE_CAPTURE` (`off` turns the capture hooks off; recall is unaffected).

## Layout

```
mnemosyne/
├── install.py                     # one-step installer: package, memory repo, MNEMOSYNE_REPO, hooks
├── pyproject.toml                 # package metadata (console script + [mcp] extra; not on PyPI yet)
├── src/mnemosyne/
│   ├── core.py                    # the engine (axis-driven scorer, hygiene, git, export/sync)
│   ├── stores.py                  # federation: clone/pull stores + federated load across tiers
│   ├── candidates.py              # lessons-capture spool + signal detection for the hooks (shadow mode)
│   ├── config.py                  # config loader/validator
│   ├── wizard.py                  # interactive, self-documenting config builder
│   ├── cli.py                     # CLI (dynamic per-axis flags) + self-test
│   ├── mcp_server.py              # MCP server (recall/capture/reflect/promote/export/prune/hygiene)
│   └── data/                      # bundled schema + default, software-eng & multi-store configs
├── plugin/                        # Claude Code plugin (skill + hooks + commands)
├── memory/                        # a working demo store (lessons.jsonl + generated LESSONS.md)
├── mnemosyne.config.json          # this repo's active config (software-eng) — also a demo
└── docs/design.md                 # architecture, recall algorithm, hygiene, governance
```

`memory/local.jsonl` and `memory/usage.local.json` are per-developer and gitignored; only
`memory/lessons.jsonl` (+ the generated `LESSONS.md`) is committed and shared.

Every save is **atomic**: the engine writes a temp file beside the target, fsyncs it, and swaps it
in with `os.replace`, so a process that dies mid-save leaves the previous store intact rather than
a truncated one. A crash can at worst leave a stray `memory/.*.tmp`, which is gitignored and safe
to delete.

Saves are also **serialised**: each one holds an OS lock on `memory/.store.lock` (gitignored) from
read to write, so two agents or terminals saving at once both keep their lessons. The OS drops the
lock if its holder crashes. A save waits up to `MNEMOSYNE_LOCK_TIMEOUT` seconds (default 10) and
then exits 4 with an error naming the holder; see [`docs/design.md`](docs/design.md) for details.
A memory repo scaffolded by an older `mnemosyne init` should add `.store.lock` to its
`memory/.gitignore`.

## Tiers & transparency

- **local** (`memory/local.jsonl`, gitignored) — instant, per-developer capture.
- **shared** (`memory/lessons.jsonl`, committed) — team-wide truth; entered only via a reviewed
  promotion PR (see [`docs/lesson-review-checklist.md`](docs/lesson-review-checklist.md)).
- **stores** (`config.stores`) — broader shared repos (e.g. `team`, `enterprise`) federated in at
  recall time and written up to with `promote --to <tier>`. `recall` reads only stores already
  fetched and never touches the network (any other store is skipped with a note, never a
  failure); `sync` fetches them and retires a local original once its copy's review PR merges.
  See [`docs/design.md`](docs/design.md).

Every command prints a quotable `RECALL:` / `SAVED:` / `PROMOTED:` / `EXPORTED:` line meant to be
relayed verbatim. Memory is never applied silently and never shared unreviewed.

## Lessons capture (shadow mode)

The plugin's hooks also watch for moments worth a lesson and record them as **candidates**. This is
Phase 0 of the [lessons-capture spec](../docs/lessons-capture-spec.md), so it runs in **shadow
mode**: it records and logs, but **nothing is stored as a lesson and nothing is asked**, and no
capture hook prints anything. It is there to measure how often each signal fires, and how often a
candidate was worth keeping, before any of it is automated.

| Hook (Claude Code event) | Mode | Records |
|---|---|---|
| `UserPromptSubmit` | `prompt` | S4 "remember / always / never / from now on"; S5 a correction ("no,", "don't", "instead", "that's wrong") |
| `PostToolUse`, `PostToolUseFailure` | `post-tool` | S6 a shell command that failed and then passed; S8 the `fresh-eyes-investigation` skill; S9–S11 a write to a watched path |
| `Stop` | `stop` | logs whether it *would* block for triage; never blocks |
| `PreCompact` | `pre-compact` | logs the spool state |
| `SessionStart` | `session-start` | logs the pending count (and syncs, as before, when the memory repo has a remote or a store to pull) |

- **Where it goes:** `memory/.capture/` in the memory repo. The directory ignores itself, so the
  spool is never committed. `candidates.jsonl` holds candidates and labels; `decisions.jsonl` holds
  one line per hook run; a `fired` folder holds the short-lived markers that stop one event being
  handled twice.
- **What a candidate holds:** pointers only (signal, tool, repo-relative path, exit code, a short
  command head such as `npm test`), never tool output. The prompt signals keep a short excerpt of
  the user's words, with machine paths replaced by `<path>`. A candidate that carries a credential
  shape (an access key, a token, a private key, a `password=` assignment) is dropped, and only the
  shape's name is logged.
- **Watched paths:** a project sets them with a `memory` block in `.github/zethus.config.json`,
  `.copilot/zethus.config.json` or `.claude/amphion.config.json` (the first one that has the block
  wins). Without one, the defaults are these:

  ```json
  "memory": { "enabled": true, "watch": ["docs/adr/", "docs/specs/", "docs/friction-log.md"] }
  ```

  `"enabled": false` there, or `MNEMOSYNE_CAPTURE=off`, turns capture off.
- **Reviewing it:** `mnemosyne candidate list` shows what was recorded. Label each candidate with
  `mnemosyne candidate label <id> lesson|noise`, then `mnemosyne candidate stats` shows each
  signal's count and precision. `mnemosyne doctor` shows the hooks' recent decisions, so a hook
  that fails open never fails silently, and counts any line written past a busy lock.
- **Other hosts:** the same `mnemosyne_hook.py` reads each host's field names, as observed on real
  Claude Code, Copilot CLI and Codex installs. A host-specific registration can pass `--host <name>`
  after the mode. The spec's §4.7 has the per-host matrix, and what was and wasn't verified.

## Development

```bash
PYTHONPATH=src python -m mnemosyne selftest     # zero-dep test suite
python -m unittest tests.test_mnemosyne tests.test_mnemosyne_review_flow tests.test_mnemosyne_mcp_stdio tests.test_mnemosyne_capture tests.test_mnemosyne_install
```

The engine has no runtime dependencies; only the MCP server needs the `mcp` package (installed via
the `[mcp]` extra).

---

Part of [mesmer-grimoire](../README.md) — a collection of standalone AI coding-agent artifacts.
Apache-2.0 licensed.

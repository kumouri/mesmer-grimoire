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

**2. Claude Code plugin** — a skill + hooks (auto-recall on each prompt, sync on session start) +
`/recall`, `/reflect`, `/promote` commands. Install the `mnemosyne` plugin from this repo, then set
`MNEMOSYNE_REPO` to your memory repo. (The plugin's hooks import the `mnemosyne` package and its
commands run the `mnemosyne` CLI, so install it as above first.)

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
| `selftest` | Zero-dependency test suite. |

Everything is also available as the Python API (`mn.recall/capture/reflect/promote/export/prune/…`)
and as MCP tools.

Environment: `MNEMOSYNE_REPO` (primary repo), `MNEMOSYNE_CONFIG` (config path), `MNEMOSYNE_AUTHOR`
(lesson author; without it lessons record `unknown`, never your login name), `MNEMOSYNE_CACHE` (where url-stores are cloned; default `~/.mnemosyne/stores`),
and `MNEMOSYNE_LOCK_TIMEOUT` (seconds a save waits for the store lock; default 10).

## Layout

```
mnemosyne/
├── pyproject.toml                 # package metadata (console script + [mcp] extra; not on PyPI yet)
├── src/mnemosyne/
│   ├── core.py                    # the engine (axis-driven scorer, hygiene, git, export/sync)
│   ├── stores.py                  # federation: clone/pull stores + federated load across tiers
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

## Development

```bash
PYTHONPATH=src python -m mnemosyne selftest     # zero-dep test suite
python -m unittest tests.test_mnemosyne tests.test_mnemosyne_review_flow tests.test_mnemosyne_mcp_stdio
```

The engine has no runtime dependencies; only the MCP server needs the `mcp` package (installed via
the `[mcp]` extra).

---

Part of [mesmer-grimoire](../README.md) — a collection of standalone AI coding-agent artifacts.
Apache-2.0 licensed.

# The shared core

One source tree for what Zethus and Amphion both need, so it is written once:

| Path | What it is |
| --- | --- |
| [`hooks/mnemosyne_hook.py`](hooks/mnemosyne_hook.py) | The memory hook script: recall, capture, triage. Stdlib only, fail-open |
| [`hooks/hooks.json`](hooks/hooks.json) | Its registration in Claude Code's format (also read by Copilot's CLI and VS Code from `.claude/`) |
| [`hooks/com.github.copilot/hooks.json`](hooks/com.github.copilot/hooks.json) | The same registration in Copilot's format |
| [`memory.schema.json`](memory.schema.json) | The `memory` block of `zethus.config.json` and `amphion.config.json`, one schema for both |
| [`skills/`](skills) | `flag-or-fix`, `resume-interrupted-phase` and the general `pr-description` |

Zethus and Amphion stay two kits with their own names, READMEs and install paths
([spec Q1](../docs/lessons-capture-spec.md#q1-fuse-zethus-and-amphion)). Zethus keeps its own
`zethus-pr-description`; the core's `pr-description` is the general one.

## Edit here, then sync

A plugin must be self-contained to install from a marketplace, so `mnemosyne/plugin/` and
`amphion/plugin/` each carry a **byte copy** of the files they need. The pairs are listed under
`core.mirrors` in [`catalog.json`](../catalog.json). Never edit a copy.

```bash
python install.py --sync-core   # rewrite every copy from core/
python install.py --check       # CI: fails while a copy differs, is missing, or has no source
```

`--check` also holds the catalog to the marketplaces and plugin manifests (names, sources, versions)
and each kit's example config to `memory.schema.json`.

## Installing from it

```bash
python install.py --list                                          # the bundles
python install.py --platform all --user --dry-run                 # the plan: writes nothing
python install.py --platform all --user                           # Zethus (Copilot) + Amphion, for you
python install.py --platform claude --target path/to/repo --bundle amphion
python install.py --platform all --user --uninstall
```

`core` needs `mnemosyne`, and `zethus` and `amphion` each need `core`, so installing either installs
the core once, and **each hook registers once** however many kits ask: only
[`mnemosyne/install.py`](../mnemosyne/install.py) writes a hook registration, and it is called once
per run. The installer **calls** it, and [`zethus/install.py`](../zethus/install.py) for Zethus; it
copies neither. Each kit keeps its own entry point too: `zethus/install.py --with-core` and
[`amphion/install.py`](../amphion/install.py).

| Host | Skills go to | Hooks come from |
| --- | --- | --- |
| Claude Code | `~/.claude/skills`, or the repo's `.claude/skills` | the Claude plugin Mnemosyne's installer adds (user scope) |
| GitHub Copilot | `~/.copilot/skills`, or the repo's `.github/skills` | `~/.copilot/hooks`, or the repo's `.github/hooks`, from Mnemosyne's installer |

Codex and Cursor are refused until stage 2 builds them. The installer plans the whole run first and
rehearses each kit installer with its own `--dry-run`, so a conflict anywhere writes nothing; a file it
did not write is never overwritten, even with `--force`. Its own manifest is
`~/.mesmer-grimoire/install-manifest.json` (a repo's is `.mesmer-grimoire/` inside it) and never lists
Zethus's or Mnemosyne's files, so an older Zethus installer re-run over this one leaves the core
alone. The design and what is still open are in the
[lessons-capture spec, Phase 4](../docs/lessons-capture-spec.md#54-phase-4-the-shared-core-and-what-of-the-stage-1-installer-existed).

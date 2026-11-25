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

## Who installs from it

`python install.py --list` shows the bundles: `core` needs `mnemosyne`, and `zethus` and `amphion`
each need `core`. The package, the memory repo and the hooks come from
[`mnemosyne/install.py`](../mnemosyne/install.py), which the core's installer calls and never copies.
The design is in the [lessons-capture spec, Phase 4](../docs/lessons-capture-spec.md#5-phases).

# AGENTS.md — mesmer-grimoire

Maintainer guidance for any coding agent working in this repo. This file is the canonical copy;
`CLAUDE.md` only imports it.

## What this repo is

A personal collection ("grimoire") of standalone AI coding-agent artifacts (skills, hooks,
commands, agents, MCP servers and plugins) that don't belong to any other project. It showcases
Ceryce's work on her portfolio, so each artifact should be self-contained, documented and
presentable. It was formerly `claude-grimoire`; the identifier guard rejects links that still use
the old name.

## Where things go

| Path | Contents | Read next |
| --- | --- | --- |
| `mnemosyne/` | Reflexion-memory engine: package, CLI, MCP server, plugin | [`mnemosyne/README.md`](mnemosyne/README.md), [`mnemosyne/docs/design.md`](mnemosyne/docs/design.md) |
| `amphion/` | Spec-to-PR pipeline: markdown skills under one plugin, config-driven, no runtime | [`amphion/README.md`](amphion/README.md), [`amphion/docs/pipeline.md`](amphion/docs/pipeline.md) |
| `zethus/` | GitHub Copilot process kit: agent, skills, templates, stdlib scripts, installer | [`zethus/README.md`](zethus/README.md) |
| `skills/`, `hooks/`, `commands/`, `agents/` | Standalone artifacts of each kind, one folder or file each | the directory's `README.md` |
| `.github/plugin/`, `.claude-plugin/` | The Copilot and Claude Code plugin catalogues, kept separate | [`zethus/README.md`](zethus/README.md#install-the-plugin-default) |
| `docs/` | Cross-cutting docs and retrospectives | [`docs/morpheus-retrospective.md`](docs/morpheus-retrospective.md) |
| `scripts/` | Repo-maintenance checks run by CI, each with its tests | the script's docstring |
| `tests/` | Python `unittest` suite, gated by CI | `python -m unittest discover -s tests -t .` |

A new artifact goes in the matching directory with a short README or header comment saying what it
does and how to install it.

## Instruction files are routers: detail lives in the leaf

Auto-loaded instruction files load into every session, so every line in them is paid for on every
turn. That covers this file, `CLAUDE.md`, any nested `AGENTS.md` or `CLAUDE.md`, Copilot
instruction files and Cursor rules. They are **routers**: they say what exists and where to look,
not how it works.

- **Detail goes in the leaf:** the module docstring, the spec or design doc under a `docs/`
  directory, the README beside the code. None of those loads automatically. A nested `CLAUDE.md`
  or `AGENTS.md` is a router too, not a leaf.
- **No volatile state in any auto-loaded instruction file:** no statuses, counts, dates, version
  numbers, phase lists or "shipped" notes. That is the text that goes stale first, and a router
  that needs updating every release is a changelog.
- **Add to a router only when no existing pointer reaches the new thing,** and then add the
  pointer, not the explanation.
- **Docs change with the code, in the same change.** When behaviour changes, fix the leaf that
  describes it. There is no separate docs pass afterwards.

[`scripts/check_doc_pointers.py`](scripts/check_doc_pointers.py) enforces the mechanical part as a
blocking CI step: every relative Markdown link and backticked repo path must resolve.

```bash
python scripts/check_doc_pointers.py
```

## Rules per artifact

- **mnemosyne:** keep the engine dependency-free (the `mcp` package is an optional extra), drive new
  recall dimensions through config axes rather than code, keep federated-store clone and pull
  best-effort (never fail a recall) with distinct id prefixes, and keep `mnemosyne selftest` green.
- **amphion:** keep the skills config-driven and org-neutral. A new project-specific fact becomes a
  config key, not a literal. Keep the resolution order: config, then repo evidence, then ask the
  user; never guess silently.
- **zethus:** targets GitHub Copilot. Keep it org-neutral and its scripts stdlib-only; its
  maintenance rules are in [`zethus/README.md`](zethus/README.md#maintaining-this-kit), and its
  coverage in `tests/test_zethus.py`.

## This repo is public: the identifier guard

Every byte committed here is published. [`scripts/check_identifiers.py`](scripts/check_identifiers.py)
is a blocking CI step that rejects machine-specific identifiers in tracked files. Its docstring says
what it matches and, just as important, what it cannot see: a green run is not clearance to publish.

```bash
python scripts/check_identifiers.py
python -m unittest discover -s scripts -p "test_check_identifiers.py" -t scripts
```

When extending it:

- **Match by shape, never by secret string.** A denylist would have to contain the private terms
  it protects. Before adding any literal, ask: *would I be comfortable seeing this on the repo's
  GitHub page?*
- **Use the sanctioned placeholders** (`<user>`, `alice`, `%USERNAME%`, `/home/runner`, …) when
  docs need to show the shape of a path; add new ones to `PLACEHOLDER_NAMES`, documented.
- **Keep the author.** Ceryce's name, her `@kumouri` handle and her contact address in package
  author metadata are deliberate attribution; never "fix" them. Allowlist entries need a comment
  saying why they are safe.
- **Keep it green.** A check that lands red is a check someone disables.

## Branching and merging

- Git Flow: `main` holds tagged releases (tags prefixed `v`); `develop` is the integration branch
  and PR target; work happens on short-lived `feature/*`, `bugfix/*`, `release/*`, `hotfix/*` and
  `support/*` branches.
- Merge PRs with merge commits (`gh pr merge --merge`), never squash or rebase.
- Never merge a PR with red or pending CI.
- Markdown is the canonical source for any document deliverable; other formats are rendered from it.

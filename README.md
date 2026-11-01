# 🔮 mesmer-grimoire

[![made by kumouri](https://img.shields.io/badge/made%20by-kumouri-8e00ff?style=flat-square)](https://github.com/kumouri)
[![license: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-00ff0f?style=flat-square)](LICENSE)
[![Git Flow](https://img.shields.io/badge/workflow-git--flow-8e00ff?style=flat-square)](#-git-flow)

> A grimoire of spells for the mind of an AI — the skills, hooks, slash commands, agents, and
> kits I conjure up that don't belong to any other project.

**Formerly `claude-grimoire`** — renamed because it's no longer Claude-specific (see
[Zethus](zethus/), a GitHub Copilot kit). A *mesmer* is one who mesmerizes: the word comes from
Franz Anton Mesmer, and in EverQuest it's the enchanter's craft of "mezzing" a mind.

This is a curated showcase of the [Claude Code](https://claude.com/claude-code) extensions I
build for myself: reusable **skills**, automation **hooks**, custom **slash commands**, and
purpose-built **subagents**. Each one is a small, self-contained artifact — collected here so
they're easy to share, reuse, and point at from my portfolio.

## ✨ Featured — Mnemosyne

**🧠 [Mnemosyne](mnemosyne/)** — reflexion *lessons* memory for agent pipelines (recall / reflect /
promote): git-backed, PR-governed, deliberate. One stdlib-only engine behind a **CLI, an MCP
server and a plugin**, with config-driven recall axes, so the scorer is domain-agnostic. Design:
[mnemosyne/docs/design.md](mnemosyne/docs/design.md).

> Its companion engine, Morpheus (automatic session consolidation), and the Grimoire umbrella that
> composed the two have been retired. Why, and what was worth keeping:
> [docs/morpheus-retrospective.md](docs/morpheus-retrospective.md).

## 🎼 Also featured — Amphion

**[Amphion](amphion/)** — a spec-to-PR implementation pipeline as six composable skills: load
the decided context, handle what the spec didn't cover, recover from a crashed delegate, add CI,
write the PR, and log the friction. Pure markdown,
config-driven, no runtime. Named for the twin who built Thebes' walls by playing his lyre while the
stones set themselves. Pipeline + diagram: [amphion/docs/pipeline.md](amphion/docs/pipeline.md).

## 📜 Structure

| Directory | What lives here |
| --- | --- |
| [`mnemosyne/`](mnemosyne/) | Reflexion-lessons memory engine (package · CLI · MCP server · plugin). |
| [`amphion/`](amphion/) | Spec-to-PR implementation pipeline — six composable skills, one plugin. |
| [`skills/`](skills/) | Standalone custom Skills not tied to an engine or package. |
| [`hooks/`](hooks/) | Standalone Claude Code hooks. |
| [`commands/`](commands/) | Standalone custom slash commands. |
| [`zethus/`](zethus/) | GitHub Copilot process kit — enforcing agent, ten skills, templates, scripts. |
| [`.github/plugin/`](.github/plugin/marketplace.json) | Copilot plugin catalogue (Zethus, Mnemosyne). Add `kumouri/mesmer-grimoire#main`. |
| [`.claude-plugin/`](.claude-plugin/marketplace.json) | Claude Code plugin catalogue (Amphion, Mnemosyne). |
| [`agents/`](agents/) | Custom subagent definitions. |
| [`docs/`](docs/) | Cross-cutting docs, such as the [Morpheus retrospective](docs/morpheus-retrospective.md). |
| [`scripts/`](scripts/) | Repo-maintenance scripts: the CI identifier guard and the doc-pointer check. |
| [`tests/`](tests/) | Python `unittest` suite covering mnemosyne and zethus. |

Each directory has its own README describing conventions and what belongs there.

## 🪨 For GitHub Copilot — Zethus

**[Zethus](zethus/)** — my development process, packaged for GitHub Copilot and installable into
any repository's `.github/`, or once per user into `~/.copilot/` so it follows you into every repo
without touching any of them. One custom agent walks every change through research → spec →
sign-off → phased implementation (Phase 0 changes no behaviour) → tests → local gates → a PR with
evidence, and refuses to skip a stage; ten standalone skills, spec/ADR/PR templates, and stdlib
scripts (`run-local-gates`, `new-adr`, `new-spec`, `docs-pointer-check`) carry the procedures.

## 🧪 CI

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs two jobs on every PR into
`develop` or `main`:

- **Validate artifacts** — markdownlint, JSON/YAML well-formedness, shellcheck.
- **Python tests** — the identifier guard (below), the doc-pointer check (below), the
  `unittest` suite, and an MCP-server smoke import.

Run the suite locally with:

```bash
python -m unittest discover -s tests -t .
```

### 🧭 The doc-pointer check

[`scripts/check_doc_pointers.py`](scripts/check_doc_pointers.py) is a blocking CI step that fails
when a Markdown link or a backticked path to a repo file or directory names something that no
longer exists. It is the mechanical half of the repo's docs rule: detail lives in the leaf beside
the code, and auto-loaded instruction files stay short routers (see [`AGENTS.md`](AGENTS.md)).
Its docstring lists what it deliberately skips, such as example paths in skills that run inside
another project.

```bash
python scripts/check_doc_pointers.py
python -m unittest discover -s scripts -p "test_check_doc_pointers.py" -t scripts
```

### 🔒 The identifier guard

**This repository is public — every byte committed here is published.**
[`scripts/check_identifiers.py`](scripts/check_identifiers.py) is a blocking CI step that
scans every tracked text file for machine-specific identifiers: Windows user-profile paths
(`C:\Users\<name>\…`), other drive-absolute paths, POSIX home directories (`/home/<name>/`,
`/Users/<name>/`), WSL drive mounts, this project's GitHub URL under the wrong org or its
retired `claude-grimoire` name, and email addresses outside a small justified allowlist.

Run it and its tests locally:

```bash
python scripts/check_identifiers.py
python -m unittest discover -s scripts -p "test_check_identifiers.py" -t scripts
```

The guard matches by **shape, not by a list of secret strings** — deliberately. A denylist of
the private terms to forbid would have to *contain* those terms, and committing it to a public
repo would publish exactly what it was written to protect. Documented placeholders
(`<user>`, `alice`, `%USERNAME%`, CI's `/home/runner`, …) are accepted so docs can still show
the shape of a path. Ceryce's name, her `@kumouri` handle and her contact address in package
author metadata are **deliberate attribution** and stay: the rule is *scrub the machine, keep
the author*.

> [!IMPORTANT]
> **What this guard cannot see.** It has no knowledge of any private denylist — the real
> names of clients, businesses and workspace trees live only in a private scrub workspace
> outside this repo. A green run means "no identifier of a *known shape* was found", **not**
> "this repo is free of private information". It also scans only the current working tree, so
> it can never notice something already committed and later deleted. The pre-release gate
> remains a private `pii_sweep.py --repo … --history` run against that denylist; this check is
> a cheap always-on **subset** of it, not a replacement. Do not read a green tick here as
> clearance to publish.

## 🌿 Git Flow

This repo follows the [Git Flow](https://nvie.com/posts/a-successful-git-branching-model/)
branching model:

- **`main`** — stable, tagged releases.
- **`develop`** — integration branch; day-to-day work lands here first.
- **`feature/*`**, **`bugfix/*`**, **`release/*`**, **`hotfix/*`**, **`support/*`** — short-lived working branches.

Release tags are prefixed with `v` (e.g. `v1.0.0`).

## 🪪 License

[Apache-2.0](LICENSE) © 2026 Ceryce Armstrong

---

<sub>Built with care by **Ceryce** ([@kumouri](https://github.com/kumouri)) · brand purple `#8e00ff`</sub>

# Amphion 🎼

**A spec-to-PR implementation pipeline for Claude Code, as six composable skills.** You describe
the wall; it assembles. Feed it a story and a goal, and the stages carry the work from *what was
decided* through implementation, CI, and a reviewable pull request — with defined behaviour for the
two things that actually break long runs: hitting something the spec didn't cover, and a delegated
agent dying mid-phase.

> Amphion and his twin Zethus built the walls of Thebes. Zethus carried the stones by hand; Amphion
> played his lyre and the stones rose and set themselves into place.

Every skill here is plain markdown — no runtime, no dependencies. Project-specific paths, gates,
and vocabulary live in `.claude/amphion.config.json`, so the same six skills work on any repo.

## The pipeline

```
  ┌─ load-context ──────── what was already decided; read in an order that prevents rework
  │
  ├─ implement ─────────── (your work)
  │     ├─ flag-or-fix ─────────────── the spec ran out: fix / fix-and-flag / defer / stop
  │     └─ resume-interrupted-phase ── a delegate died: reconstruct, re-validate, resume
  │
  ├─ initialize-ci ─────── the repo has no gates yet; give it some
  │
  ├─ pr-description ────── hand it to a human, with the judgment calls surfaced
  │
  └─ log-friction ──────── what cost time, written down where it can be designed out
```

| Stage | Skill | What it's for |
|---|---|---|
| **Context** | [`load-context`](plugin/skills/load-context/SKILL.md) | Reads the project's plan, decisions, voice, and conventions **in a deliberate order** — decisions before specs, so you implement rather than re-decide. |
| **In-flight** | [`flag-or-fix`](plugin/skills/flag-or-fix/SKILL.md) | The decision framework for what the spec didn't cover. Classify, then fix now / fix and flag / defer and flag / stop — instead of improvising. |
| **Recovery** | [`resume-interrupted-phase`](plugin/skills/resume-interrupted-phase/SKILL.md) | A delegated agent returned an error, a truncation, or an unverifiable "completed". Reconstructs progress from git plus the in-repo ledger — never the dead agent's summary — re-validates the frontier, and resumes. |
| **Gates** | [`initialize-ci`](plugin/skills/initialize-ci/SKILL.md) | Generates a GitHub Actions workflow adapted to the repo's *real* build/test/lint commands. Seven stack references; never clobbers existing CI; detects Git Flow vs single-branch triggers. |
| **Handoff** | [`pr-description`](plugin/skills/pr-description/SKILL.md) | Diffs against the actual integration branch and writes the description — including the headings `flag-or-fix` files its deferrals under. |
| **Feedback** | [`log-friction`](plugin/skills/log-friction/SKILL.md) | Records what cost real time — to a markdown file, a Notion page, or GitHub issues — so recurring friction gets designed out rather than re-solved. |

The stages compose but don't depend on each other: any one is useful alone.

### Keeping docs in sync: a rule, not a stage

Amphion used to ship a seventh skill, `sync-claude-md`, that corrected the docs a diff made wrong.
It was retired: the agent that changes the code is already the one that should fix its docs, in the
same change, and a separate docs pass mostly *added* text to always-loaded instruction files. What
replaced it is in [the pipeline doc](docs/pipeline.md#docs-are-a-rule-not-a-stage).

## Install

**Plugin (recommended).** Install the `amphion` plugin from this repo; it carries all six skills.

**Manual.** Copy the skill folders into your skills directory — user-level for all projects, or
`.claude/skills/` inside one project:

```bash
git clone https://github.com/kumouri/mesmer-grimoire.git
cp -r mesmer-grimoire/amphion/plugin/skills/* ~/.claude/skills/
```

```powershell
git clone https://github.com/kumouri/mesmer-grimoire.git
Copy-Item mesmer-grimoire\amphion\plugin\skills\* $HOME\.claude\skills\ -Recurse
```

Take a subset if you want one — each skill folder is self-contained. Cross-references between
skills degrade to a mention of a skill you don't have installed, which is harmless.

## Configure

Copy [`amphion.config.example.json`](amphion.config.example.json) to
`.claude/amphion.config.json` in your project and edit it.

**Every key is optional.** A skill that finds no config falls back to discovery and asks before
guessing — it never silently invents a path. The config exists so it doesn't have to ask twice.

| Key | Used by | What it is |
|---|---|---|
| `vocabulary.spec` / `.phase` | `load-context` | What your project calls a spec and a phase — `spec`, `audit`, `brief`, `ticket`. Used when reporting back to you. |
| `context.core[]` | `load-context` | The ordered core document set: `role` (`plan` / `decisions` / `voice` / `conventions`), `path`, `note`. **Array order is the read order.** |
| `context.phase.*` | `load-context` | Path template for a phase briefing (`{phase}` is substituted), plus globs for specs and supporting documents. |
| `ledger.path` | `resume-interrupted-phase` | The in-repo progress ledger. Default `docs/PHASE-PROGRESS.md`. |
| `gates.build` / `gates.test` | `resume-interrupted-phase`, `initialize-ci` | The real commands to run. |
| `gates.mandatedChecks[]` | `resume-interrupted-phase` | Project-specific invariants — `name`, `command`, `expect`. These are what a crashed delegate silently eats, so they're named explicitly rather than assumed. |
| `branchModel.base` | `pr-description`, `resume-interrupted-phase`, `initialize-ci` | The integration branch, when it isn't the default. |
| `branchModel.gitFlowOwners[]` | `initialize-ci` | GitHub owners/orgs whose repos use Git Flow by convention. Empty by default — add your own. |
| `frictionLog.*` | `log-friction` | `sink` (`markdown` / `notion` / `githubIssues`), its target, and your `categories[]`. Defaults to a markdown file in-repo, which needs no credentials. |

### What the skills assume of your project

Most of the pipeline needs nothing. Two stages want a convention to exist, and say so rather than
inventing one:

- **`load-context`** needs planning documents to exist somewhere. On a project with no plan and no
  written decisions, there is nothing to load in order — the skill will say so instead of
  manufacturing a document set.
- **`resume-interrupted-phase`** works best with an **in-repo progress ledger** (`ledger.path`) — a
  file the implementer updates to `in-progress` before each sub-phase and `done` + verification
  after. Without one it falls back to `git log` plus reading diffs, which recovers *what* was done
  but not *whether it was validated*. The ledger is what makes the second question answerable.

## License

[Apache-2.0](../LICENSE) © 2026 Ceryce Armstrong

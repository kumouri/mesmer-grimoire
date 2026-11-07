---
name: initialize-ci
description: Set up GitHub Actions CI for a repository that has none. This skill should be used when the user asks to "set up CI", "add CI", "initialize CI", "configure CI", "add a GitHub Actions workflow", "add a CI pipeline", "set up continuous integration", "create a build/test workflow", "add .github/workflows", "this repo has no CI", "this repo needs CI", "there's no CI yet", or "wire up automated tests on push"; and proactively when working in or right after running /init on a git repository whose remote is (or is intended to be) on GitHub and which has no .github/workflows directory. Detects the project type (Java/Spring Boot+Gradle, TypeScript/Vite+React, C#/.NET, Lua, Node, Python, or generic), generates a CI workflow adapted to the repo's real build/test/lint commands, language version, and package manager, flags monorepos, never clobbers existing workflows, and verifies the workflow before finishing. Detects the repo's branch model and emits Git Flow trigger shapes (develop + main) where applicable.
---

# Initialize CI

Set up a GitHub Actions CI workflow for a repository that doesn't have one. The
goal: a single `.github/workflows/ci.yml` that builds, tests, and (where the
stack supports it) lints on every push and PR, adapted to *this* repo's real
commands and tooling — not a generic template. Works for brand-new repos
(during/after `/init`) and existing repos that lack CI.

**Doctrine:** detect, don't assume; adapt to the repo's actual build/test
commands; never clobber existing CI; verify before declaring done. Scope is CI
only (build/test/lint) — no deploy/publish/release.

When triggered, proceed and create the workflow (it's local, reversible, and
this skill never overwrites existing CI) — then report. Do not ask permission to
create the file; do pause only for correctness inputs (monorepo sub-project
list, genuinely undeterminable commands). Never `git push` on the user's behalf.

Per-stack detail lives in `references/<type>.md` (shared conventions, detection
rules, version & tooling detection, a complete `ci.yml`, and gotchas). Load only
the matching one(s) in Step 4 — do not preload all of them.

**Config** (`.claude/amphion.config.json`, optional): `branchModel.gitFlowOwners`
lists GitHub owners whose repos use Git Flow by convention, and
`branchModel.base` names the integration branch when it isn't the default.
`gates.build` / `gates.test` give the real commands if the repo's build files
don't make them obvious. Everything here still works with no config — detection
just has fewer hints.

## Step 1: Confirm git + GitHub target

Run `git rev-parse --is-inside-work-tree` and `git remote -v`.

| Situation | Action |
|---|---|
| Git repo, remote on `github.com` | Proceed. |
| Git repo, no remote, GitHub intended | Proceed; note CI runs only once pushed to GitHub. |
| Git repo, remote is NOT GitHub | Stop. State this emits GitHub Actions only; proceed only if they confirm GitHub will also host it, else decline cleanly. |
| Not a git repo | Stop. Explain CI needs a repo; offer `git init` only if the user confirms. Do not auto-init. |

Capture the default branch (`git symbolic-ref --short HEAD`, or
`git remote show origin` if a remote exists). Hold it for Steps 6–7.

### Step 1a: Detect the branch model

Determine whether the repo uses **Git Flow** (two long-lived branches:
`develop` = default/integration, `main` = release) or a **single-branch**
model. Signals for Git Flow, in priority order:

1. A `develop` branch exists alongside `main` (local or remote).
2. The repo's owner is listed in `branchModel.gitFlowOwners` in
   `.claude/amphion.config.json` — a list of GitHub owners/orgs whose repos use
   Git Flow by convention. For a brand-new repo under such an owner, build for
   Git Flow even if `develop` doesn't exist yet. The list is empty by default;
   add your own owners to it.
3. `branchModel.base` names an integration branch other than the default.
4. The user says so.

Hold the answer for Steps 6–7. Under Git Flow: feature PRs target `develop`
and run fast CI only; release PRs `develop` → `main` run the full/expensive
tier; push-to-main is the CD/deploy trigger (out of this skill's scope).

## Step 2: Do not clobber existing CI

Glob `.github/workflows/*.{yml,yaml}`.

- None → continue.
- Exists → DO NOT overwrite or add a competing `ci.yml`. Read each, summarize
  coverage (build? test? lint? triggers?), tell the user what's there, and offer
  to (a) extend an existing workflow, (b) add a distinctly named complementary
  workflow if a real gap exists, or (c) stop. Proceed only on explicit choice.

## Step 3: Detect project type(s)

Marker files at repo root (and one level down for monorepos):

| Type | Markers |
|---|---|
| `java-spring-boot-gradle` | `build.gradle`/`build.gradle.kts`, `gradlew`, `settings.gradle*` (Maven fallback: `pom.xml`, `mvnw`) |
| `typescript-vite-react` | `package.json` + `vite.config.*` + `tsconfig.json` (react dep) |
| `node` | `package.json`, no Vite/React/other-bundler signal |
| `python` | `pyproject.toml`, `requirements*.txt`, `setup.py`, `tox.ini` |
| `csharp-dotnet` | `*.csproj`/`*.sln`, `global.json` |
| `lua` | `*.rockspec`, `.luacheckrc`, lua sources + `Makefile` |

- Exactly one → happy path, go to Step 4.
- None → `references/generic-fallback.md` (see "Unsupported stacks"). Don't
  force-fit a wrong reference.
- Multiple / monorepo → do NOT emit one tangled workflow. Enumerate each
  sub-project + its directory; plan one job (or one workflow file) per
  sub-project, each scoped with a `paths:` filter. Confirm the sub-project list
  with the user before generating. Handle each via its own reference.

## Step 4: Load the matching reference

Read `references/<type>.md` for each detected type. It is the source of truth
for workflow structure and verified action versions; Step 5 adapts it.

## Step 5: Detect this repo's specifics (don't assume defaults)

| Dimension | Where to look |
|---|---|
| Runtime/lang version | `.nvmrc`/`engines` (Node); `toolchain`/`<java.version>` (Gradle/Maven); `requires-python`/`.python-version` (Python); `<TargetFramework>`/`global.json` (.NET); rockspec/`.luacheckrc` (Lua) |
| Package/dep manager | Lockfile: `package-lock.json`→npm, `pnpm-lock.yaml`→pnpm, `yarn.lock`→yarn, `bun.lockb`→bun; `poetry.lock`→poetry, `uv.lock`→uv, else pip; Gradle/Maven wrapper present → use it |
| Real build command | Gradle tasks / `package.json` scripts / `Makefile` / `.csproj`. Use the script that actually exists, not a guessed name |
| Real test command | Same sources. Watch non-standard names (`test:ci`, custom Gradle `test` task, `pytest`, `dotnet test`) |
| Lint/typecheck (optional) | Include only if a real config/script exists (eslint, `tsc --noEmit`, checkstyle/spotless, ruff/flake8). Never invent one |

If a command genuinely can't be determined, ask the user — don't guess.

## Step 6: Generate `.github/workflows/ci.yml`

Start from the reference's `ci.yml`; adapt detected version, lockfile-based
caching, the *real* build/test/(lint) commands, and `paths:` filters for
monorepos. Triggers depend on the Step 1a branch model:

- **Single-branch**: `push` + `pull_request` on the **actual default branch**
  from Step 1 (default to `branches: [main, master]` as a safety net — never
  hardcode just one).
- **Git Flow**: `pull_request: branches: [develop, main]` + `workflow_dispatch`,
  and NO `push` triggers (develop merges are validated by their PRs; push-to-main
  belongs to a CD/deploy workflow, out of scope here). If the stack has an
  expensive tier (E2E, integration shards), emit it as a separate workflow gated
  to `pull_request: branches: [main]` + `workflow_dispatch` so it runs only on
  release PRs — never on every develop merge. See each reference's "Trigger
  shape by branch model" callout.

Pin actions to the verified major versions in the reference.
Minimal, readable, fail-on-error (no `|| true`, no `continue-on-error` on
test/lint). Write only `.github/workflows/ci.yml` (or the agreed names).

## Step 7: Verify before finishing

1. **YAML validity** — use `actionlint` or `gh workflow view` if present; else
   `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml'))"`;
   else a careful manual structural read.
2. **Commands pass locally (adaptive)** — if quick/feasible, run the real
   build/test once locally to confirm green before it ever runs in CI. If it
   fails, fix the workflow or report the repo's own breakage — don't ship a
   known-red pipeline. If infeasible (long build, missing toolchain), say so
   explicitly and flag the workflow as **unverified**.
3. **Branch-trigger gotcha** — confirm `on:` branches include the repo's actual
   default branch. A workflow on `main` in a `master` repo (or vice-versa)
   silently never runs. Fix to the real branch or keep both `[main, master]`.
   Git Flow repos: confirm `pull_request` covers BOTH `develop` and `main`,
   and that no `push: develop` trigger snuck in.

## Step 8: Hand off

- Tell the user exactly how to see the first run: commit `.github/workflows/`,
  `git push`, then `gh run watch` / `gh run list` or the Actions tab. If no
  remote yet, give the push-to-GitHub steps. Do not push for them.
- Surface limitations: unverified commands, needed secrets, fork-PR caveats.
- Git Flow repos where `develop` doesn't exist yet: offer (with consent) to
  create it from `main` after the first push and set it as the repo's default
  branch, so feature PRs auto-target `develop`.
- Offer to add a short **CI** section to the repo's own `CLAUDE.md` (one line:
  what the workflow does + the local command to reproduce it). Add only with
  consent; keep terse; don't duplicate this skill's logic. If the repo already
  documents its CI, correct that text in place rather than adding a second
  description of the same thing.

## Unsupported stacks

If Step 3 found no known type, follow `references/generic-fallback.md`: discover
the build/test entrypoint generically (Makefile → build script → README/
CONTRIBUTING → ask the user), emit a minimal `ci.yml` running those commands on
`ubuntu-latest`, and be loudly explicit that it's generic and lightly tested.
Escalate (stop, explain) if the entrypoint can't be found or supplied.

## Anti-patterns

- Don't clobber or shadow an existing workflow — Step 2 is a hard stop.
- Don't hardcode `main`/`master` blindly — the silent-trigger gap is the #1
  failure mode; verify against the real default branch.
- Don't guess build/test commands from convention — read the repo's actual
  build files; ask when undeterminable.
- Don't `|| true` / `continue-on-error` a test or lint step — CI that can't
  fail is theater.
- Don't ship a known-red pipeline — fix it or report the breakage.
- Don't `git push` for the user — generate and report; they push.
- Don't emit a deploy/publish/release job — scope is CI only.
- Don't preload all references or add a competing `ci.yml` to a monorepo.

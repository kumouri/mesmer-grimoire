---
name: sonarqube-cli
description: Drive SonarQube (Server or Cloud) from the terminal — trigger analysis with sonar-scanner, and read/query/transition projects, quality gates, issues, and hotspots with the official sonarqube-cli (`sonar`). Use whenever the user asks about SonarQube quality gates, code-quality/security issues, hotspots, coverage/measures, or wants to kick off a scan.
---

# SonarQube (Server + SonarQube Cloud)

Two tools, two jobs. Do not blur them:

- **`sonar-scanner`** — triggers an analysis run. Write-only from the caller's point of view: it
  uploads code + metadata for the server to analyze. It cannot answer "what's my quality gate" or
  "what issues are open" — it can only *wait and print pass/fail* for the gate computed from the run
  it just submitted.
- **`sonar`** (the official `sonarqube-cli`) — everything else: list projects, read quality gate
  status, search issues, and (via its generic API passthrough) hotspots, measures, analysis
  history, and issue/hotspot transitions.

`sonarqube-cli` is SonarSource's own, actively-maintained CLI, explicitly positioned for both
interactive terminal use and AI-agent integration — no bespoke client was needed for this skill.
Third-party alternatives (`sonar-tools`, `sonar-client`, `python-sonarqube-api`) exist on PyPI but
are redundant with it: none add coverage the official tool lacks, and it's vendor-maintained rather
than something that needs patching against API drift by hand. Minimum supported SonarQube Server
version for `sonarqube-cli` is **25.1** (per its 1.8.0 release notes) — confirm the target instance
meets that floor before relying on it; older instances may need the raw Web API fallback in the
failure table below instead.

Analysis results and issue lists can describe unfixed vulnerabilities. Keep them, and every token,
out of version control: never commit either into a repository.

## Setup

Both tools read credentials from the environment only. Never put a token on a command line where an
env var will do — command lines land in shell history and process listings.

**`sonar-scanner`** (analysis):

```powershell
$env:SONAR_HOST_URL = "<SONAR_HOST_URL>"     # e.g. https://sonarqube.example.internal
$env:SONAR_TOKEN = "<SONAR_TOKEN>"
sonar-scanner -Dsonar.projectKey=<PROJECT_KEY>
```

`SONAR_TOKEN` and `SONAR_HOST_URL` are documented environment-variable overrides for the scanner,
taking precedence over any properties file — exactly what you want for a CI-style, non-interactive
invocation.

**`sonar` / sonarqube-cli** (reads + mutations):

```powershell
# Self-hosted SonarQube Server
$env:SONARQUBE_CLI_SERVER = "<SONAR_HOST_URL>"
$env:SONARQUBE_CLI_TOKEN = "<SONAR_TOKEN>"

# SonarQube Cloud instead uses:
# $env:SONARQUBE_CLI_ORG = "<SONAR_ORG_KEY>"
# $env:SONARQUBE_CLI_TOKEN = "<SONAR_TOKEN>"

sonar auth status     # sanity check — confirms the env vars are wired up, prints who/where
```

If `sonar auth status` fails, stop and report the failure verbatim rather than falling back to
`sonar auth login` (that opens an interactive browser flow — wrong for an agent session).

Install (`sonar` only — `sonar-scanner` is usually already provisioned by the build tooling: look
for it yourself, Maven's `sonar:sonar` goal, Gradle's `org.sonarqube` plugin or npm's
`sonarqube-scanner`, and use that before installing anything):

```powershell
irm https://raw.githubusercontent.com/SonarSource/sonarqube-cli/refs/heads/master/user-scripts/install.ps1 | iex
sonar --version                          # verify
```

(also available via `brew install sonarqube-cli` on macOS/Linux, or `mise use -g sonarqube-cli@latest`
cross-platform.) That line downloads and runs a script, so read it first, then offer the install
once with the question tool ("Install sonarqube-cli" / "Don't install"), and on a picked yes run it
yourself.

## Triggering analysis

```powershell
sonar-scanner -Dsonar.projectKey=<PROJECT_KEY> -Dsonar.sources=.
```

This is fire-and-forget from the CLI's perspective: it uploads the analysis and (optionally, with
`-Dsonar.qualitygate.wait=true`) blocks until the server computes the gate for *this* run,
printing pass/fail. It is **not** a general query tool — for anything else (existing issues, gate
status of a project you didn't just scan, history), switch to `sonar`.

Never run `sonar-scanner` against a project without explicit instruction — an analysis run mutates
server-side history (new analysis entries, potentially a new baseline) even though it feels
read-adjacent. Treat "run a scan" as an action the user asked for, not something to do speculatively
while investigating a question.

## Reads

All read commands default to JSON. Pass `--format table` when a human wants to eyeball it in the
terminal; keep JSON when you're going to parse the output yourself with `ConvertFrom-Json`.
Pagination on `list` commands is `--page` (1-based) and `--page-size` (max 500) — the same `p`/`ps`
shape the underlying Web API uses. `sonar api` passthrough calls page with the raw `p`/`ps` params
in the `-d` JSON body since they're just Web API parameters at that point.

Quote every placeholder that stands as its own argument. In PowerShell a bare `<PROJECT_KEY>` after a
flag is a parse error, because `<` is a reserved operator there.

**List projects:**

```powershell
sonar list projects -q "<search text>" --page 1 --page-size 500
```

**Search issues** (project key is required):

```powershell
sonar list issues -p "<PROJECT_KEY>" `
  --statuses OPEN,CONFIRMED `
  --severities BLOCKER,CRITICAL `
  --branch "<branch>" --pull-request "<pr-id>" `
  --file "<path>" `
  --page-size 500 --page 1
```

`--statuses` and `--severities` take the Web API's own vocabularies (statuses: `OPEN`, `CONFIRMED`,
`FALSE_POSITIVE`, `ACCEPTED`, `FIXED`, etc.; severities: `BLOCKER`, `CRITICAL`, `MAJOR`, `MINOR`,
`INFO`). There is no `--assignee` flag on the dedicated command as of this writing — for
assignee-filtered search, drop to the passthrough:

```powershell
sonar api get /api/issues/search -d '{"componentKeys":"<PROJECT_KEY>","assignees":"<username>"}'
```

**Quality gate status:**

```powershell
sonar quality-gate status -p "<PROJECT_KEY>" --branch "<branch>" --pull-request "<pr-id>" --all --format json
```

Without `--all`, only failing conditions are listed — pass `--all` when the user wants the whole
picture, not just what's broken. `--format json` when you're going to parse it; the default is a
human-readable table.

## Hotspots, measures, analysis history — via the generic passthrough

`sonar` has no dedicated subcommand for these yet:

```powershell
# List hotspots for a project
sonar api get /api/hotspots/search -d '{"projectKey":"<PROJECT_KEY>"}'

# Get measures/metrics for a project (bugs, vulnerabilities, coverage, etc.)
sonar api get /api/measures/component -d '{"component":"<PROJECT_KEY>","metricKeys":"bugs,vulnerabilities,code_smells,coverage,duplicated_lines_density"}'

# List analysis history for a project
sonar api get /api/project_analyses/search -d '{"project":"<PROJECT_KEY>"}'
```

`sonar api get <endpoint> -d '{...}'` puts the JSON body's keys on the query string for GET requests
(that's how the CLI encodes read parameters) and prints the raw JSON response — pipe to
`ConvertFrom-Json` for further filtering, e.g. `... | ConvertFrom-Json | Select-Object -ExpandProperty
hotspots`. Add `-v` when a call behaves unexpectedly; it prints the literal request made, which is
the fastest way to catch a typo'd parameter name.

**Pagination on the passthrough:** pass `p` and `ps` directly in the `-d` body, e.g.
`-d '{"projectKey":"<PROJECT_KEY>","p":2,"ps":500}'`. `/api/issues/search` enforces a hard
server-side cap of `p * ps <= 10000` — past that it returns an error rather than more results. If a
query needs more than 10,000 issues, narrow by rule, severity, or date range and issue multiple
queries rather than trying to page past the cap.

## Mutations — dry-run and confirm, every time

**`sonar api` has no built-in `--dry-run` flag.** The CLI will send exactly the request you give it,
with real side effects. The dry-run discipline is this skill's responsibility, not the tool's — this
is in addition to, not instead of, Copilot's own shell-command approval prompt, which still applies
separately to the command itself:

1. **Always construct and print the exact command first** — method, endpoint, and the full `-d` JSON
   body — without executing it. Show this to the user as the proposed action.
2. **Wait for explicit confirmation** (a picked "Run it", or any clear "yes" / "do it" / "go ahead" — not silence, not a topic change)
   before running the real command. Ask it with the harness's question tool ([why](../../docs/ask-with-the-question-tool.md)): two options, "Run it" (describe the exact effect) and "Don't run it" (nothing changes), neither preselected. Only a picked "Run it" runs it; a dismissed picker, no answer or a run with no one to ask means don't. With no question tool, ask a numbered list that accepts the number or any clear wording, never an exact phrase.
3. **Never chain a mutation off a read in the same turn** without that pause, even if the read made
   the next step obvious. "I found issue X, transitioning it to resolved" without a stop is the
   failure mode this rule exists to prevent.
4. **Verify it yourself, then state what changed** after a mutation runs — which issue/hotspot,
   what transition, and what the read-back showed: run the read command (e.g. `sonar list issues`
   with the same filter) and confirm the item is gone or its status changed.

Common mutating calls, all through the passthrough:

```powershell
# Transition an issue (confirm / resolve / falsepositive / reopen / accept — vocabulary is
# server-version-dependent; confirm with `sonar api get /api/issues/search` on the target issue
# first to see its current `transitions` array before picking one)
sonar api post /api/issues/do_transition -d '{"issue":"<ISSUE_KEY>","transition":"confirm"}'

# Mark a security hotspot reviewed
sonar api post /api/hotspots/change_status -d '{"hotspot":"<HOTSPOT_KEY>","status":"REVIEWED","resolution":"SAFE"}'

# Assign an issue
sonar api post /api/issues/assign -d '{"issue":"<ISSUE_KEY>","assignee":"<username>"}'
```

Never issue a mutating `sonar api post|put|delete` call without having shown the exact request to
the user first and gotten a "go" — this holds even for something that looks reversible (e.g.
reopening an issue you just confirmed).

## Common failure signatures

| Symptom | Likely meaning | What to do |
|---|---|---|
| `401 Unauthorized` / `sonar auth status` fails | Token missing, expired, or wrong `SONARQUBE_CLI_SERVER`/`SONARQUBE_CLI_ORG` pairing | Check the env vars are actually set in this shell (`$env:SONARQUBE_CLI_TOKEN`, etc.); report which var looks wrong rather than retrying blindly |
| `403 Forbidden` on a transition/mutation | Token's permission doesn't cover that action (e.g. hotspot transitions need "Administer Security Hotspot") | Report plainly — do not attempt to escalate scope or find a workaround endpoint |
| Project key not found / empty `list projects` result for a known key | Wrong key, wrong branch, or the token can't see that project (visibility/permissions) | Re-run `sonar list projects -q "<partial name>"` to confirm the real key before assuming the project doesn't exist |
| Quality gate shows "not computed yet" / no gate data | The project hasn't been analyzed yet, or the specific branch/PR you asked about has no analysis | This is not an error to retry — say plainly that no analysis exists for that ref yet; if triggering one is in scope, offer to run `sonar-scanner` yourself, under the confirm discipline above |
| `/api/issues/search` errors past `p*ps` near 10000 | Hit the hard pagination cap | Narrow the query (severity/rule/date range) instead of paging further |
| `sonar-scanner` hangs with `-Dsonar.qualitygate.wait=true` | Server-side background task queue is backed up, or webhook/CE processing is slow | This is expected occasionally; don't kill and retry immediately. Keep waiting, read-only: poll `api/ce/component?component=<key>` for the task's status, up to the same bound as any background wait, and report only past it |
| `sonar` command not found, or `--version` reports below the expected floor | `sonarqube-cli` not installed, or an old copy on PATH — this skill needs SonarQube Server 25.1+ compatibility | Offer the install (above). Meanwhile, and if the target server predates 25.1, fall back to `curl`/`Invoke-RestMethod` against the self-describing Web API at `<SONAR_HOST_URL>/web_api` instead of assuming `sonar` will work |

## Secrets rule

- Tokens live in `SONAR_TOKEN` / `SONARQUBE_CLI_TOKEN` (and the paired `SONAR_HOST_URL` /
  `SONARQUBE_CLI_SERVER` or `SONARQUBE_CLI_ORG`) — environment only.
- Never echo a token value back in output, logs, or an error message. If a command's `-v` verbose
  output would print an `Authorization` header, redact it before showing the user.
- Never pass a token as a bare CLI argument — both tools support env-var auth precisely so this is
  never necessary.
- Placeholders in every example and every draft you write: `<SONAR_HOST_URL>`, `<SONAR_TOKEN>`,
  `<SONAR_ORG_KEY>`, `<PROJECT_KEY>`, `<ISSUE_KEY>`, `<HOTSPOT_KEY>`. Never a real hostname.

## Acceptance

This checklist is for reviewing the skill itself. The live checks need a SonarQube instance.

- [ ] `sonar auth status` (or `sonar-scanner --version`) succeeds with only env-var credentials set
      — no token typed into a command.
- [ ] `sonar list projects` returns JSON and the agent can find a project by partial name via `-q`.
- [ ] `sonar quality-gate status -p <PROJECT_KEY>` correctly distinguishes "passing", "failing with
      named conditions", and "not computed yet".
- [ ] `sonar list issues -p <PROJECT_KEY> --statuses OPEN --severities BLOCKER,CRITICAL` returns a
      filtered, paginated list.
- [ ] A hotspot list, a measures pull, and an analysis-history pull all work via `sonar api get ...`
      with correctly quoted JSON in `-d`.
- [ ] Any attempted mutation (issue transition, hotspot resolution, assignment) is shown to the user
      as an exact command **before** it runs, and does not run without explicit confirmation —
      Copilot's own approval prompt is named as a second, separate layer rather than a substitute.
- [ ] No real hostname, token, or organisation-internal project name ever appears in a draft, log,
      or example — only the bracketed placeholders above.
- [ ] Every command block is PowerShell-valid (backtick line continuations, `$env:` assignments, no
      bare `export`); no unlabeled bash-only construct appears anywhere in this file.
- [ ] Nothing here points outside the kit except the tools' own public links.

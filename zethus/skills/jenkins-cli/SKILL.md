---
name: jenkins-cli
description: Drive a Jenkins controller from the terminal — plain Jenkins OR CloudBees CI, which is Jenkins-compatible — using the official jenkins-cli.jar plus the JSON REST API for reads (jobs, builds, console logs, queue, nodes), plus CloudBees RBAC/service-accounts/CasC-bundle-reload when the target is CloudBees CI. Use when the user asks to list/trigger/inspect/abort Jenkins jobs or builds, tail console output, check queue or agent state, fetch a job's config.xml, or manage CloudBees CI's RBAC/service-accounts/CasC bundles. Requires JENKINS_URL, JENKINS_USER, JENKINS_API_TOKEN in the environment (CloudBees CI targets may instead use CLOUDBEES_SERVICE_ACCOUNT / CLOUDBEES_SERVICE_ACCOUNT_TOKEN) plus a local JRE for jenkins-cli.jar. Never fires a mutating command (trigger, abort, config change, RBAC grant, CasC reload) without explicit user confirmation in the current turn.
---

# Jenkins skill

Wraps two things Jenkins itself ships — **`jenkins-cli.jar`** (bundled with every controller at
`<JENKINS_URL>/jnlpJars/jenkins-cli.jar`) and the **JSON REST API** (`/api/json` and friends) — no
third-party CLI, no new tool needed. Two alternatives were considered and passed over: the
community `jenkins-zh/jcli` project's last tagged release is over a year stale with no visible
activity since — a bad bet for tooling you need to keep supportable — and Blue Ocean's REST API has
no dedicated CLI to begin with and is on a deprecation clock (full deprecation announced for July
2026); everything it would give you (pipeline stage/run data) is already reachable via `/api/json`
and `/wfapi/` without depending on a plugin that's going away.

This skill covers **both** plain open-source Jenkins and **CloudBees CI** (a Jenkins-compatible
commercial distribution) — everything below works unmodified against either. If the target is
CloudBees CI, also read "CloudBees CI specifics" at the end of this file before assuming a
CloudBees-only feature (RBAC, service accounts, CasC bundle reload) isn't covered — it is, just
down there rather than mixed into the plain-Jenkins command list above.

Build logs and job configuration can hold sensitive values. Keep them, and every credential, out of
version control: never commit either into a repository.

## 0. Setup / auth check — run this before anything else

Required environment variables (placeholders — never hardcode real values):

```
JENKINS_URL           # e.g. https://ci.example.internal
JENKINS_USER          # the Jenkins account username
JENKINS_API_TOKEN     # Manage Jenkins > Users > <user> > Security > API Token
```

`jenkins-cli.jar` needs a local JRE on this machine to run at all:

```powershell
java -version
```

If this fails, the jar-based commands (trigger, abort via CLI, console `-f` tail, `who-am-i`) can't
run — report that a JRE is missing rather than installing one unattended. The REST-based commands
(everything using `Invoke-RestMethod`/`Invoke-WebRequest` below) need no JRE at all and still work.

Confirm the three env vars are set, then build the Basic-auth header used by every REST call below:

```powershell
if ($env:JENKINS_URL -and $env:JENKINS_USER -and $env:JENKINS_API_TOKEN) { "env present" } else { "env MISSING" }

$pair = "$($env:JENKINS_USER):$($env:JENKINS_API_TOKEN)"
$basicAuth = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
$headers = @{ Authorization = "Basic $basicAuth" }
```

Then verify auth actually works — don't assume a stale token is good:

```powershell
try {
  $resp = Invoke-WebRequest -Uri "$($env:JENKINS_URL)/api/json" -Headers $headers
  "$($resp.StatusCode) - auth good, proceed"
} catch {
  $status = $_.Exception.Response.StatusCode.value__
  "request failed: HTTP $status"
}
```

(bash equivalent, if ever running under Git Bash/WSL instead of PowerShell:
`curl -s -o /dev/null -w "%{http_code}" -u "$JENKINS_USER:$JENKINS_API_TOKEN" "$JENKINS_URL/api/json"`)

- `200` → auth good, proceed.
- `401` → bad user/token — stop and tell the user, don't retry blindly (see Common failure signatures).
- `403` → reachable and authenticated identity may be fine, but the account lacks a permission —
  stop and say which call got the 403.
- connection error/timeout (the outer `catch`, no `$status`) → `JENKINS_URL` unreachable from this
  machine (VPN? typo?) — stop and say so.

Never print `$env:JENKINS_API_TOKEN` in any command output, log line, or chat message. Prefer the
Basic-auth header built once above over re-assembling credentials inline in every call.

## 1. CSRF crumb (HTTP mode)

Requests authenticated with an API token are, per Jenkins' own docs, **exempt from crumb
protection** — so the token-based calls in this skill normally need no crumb step. But some
hardened Jenkins instances disable that exemption, so every mutating call below should be prepared
to fall back to the two-step crumb pattern if it gets a 403 whose body mentions "No valid crumb":

```powershell
# Step 1 — fetch the crumb (GET, safe, no confirmation needed)
$crumb = Invoke-RestMethod -Uri "$($env:JENKINS_URL)/crumbIssuer/api/json" -Headers $headers
# $crumb looks like: { crumbRequestField = "Jenkins-Crumb"; crumb = "<value>" }

# Step 2 — include it as a header on the mutating call
$mutHeaders = $headers + @{ $crumb.crumbRequestField = $crumb.crumb }
Invoke-RestMethod -Method Post -Uri "$($env:JENKINS_URL)/job/<JOB_NAME>/build" -Headers $mutHeaders
```

If a 403 with "No valid crumb" appears anywhere below, retry that same call once with the crumb
header added before treating it as a real failure.

## 2. Commands / operations

Reads use `Invoke-RestMethod`/`Invoke-WebRequest` against `/api/json` (structured JSON, no JVM
startup cost). Actions (trigger/abort) use the jar or the equivalent REST endpoint. All job names
below are placeholders (`<JOB_NAME>`); substitute the real one, but never hardcode a real job name
into a file you commit.

### 2.1 List jobs

```powershell
(Invoke-RestMethod -Uri "$($env:JENKINS_URL)/api/json?tree=jobs[name,url,color]" -Headers $headers).jobs
```

`color` encodes status (`blue`=success, `red`=failed, `yellow`=unstable, `_anime` suffix=building).

### 2.2 Get job info

```powershell
Invoke-RestMethod -Uri "$($env:JENKINS_URL)/job/<JOB_NAME>/api/json" -Headers $headers
```

### 2.3 Get job config.xml

```powershell
Invoke-RestMethod -Uri "$($env:JENKINS_URL)/job/<JOB_NAME>/config.xml" -Headers $headers
```

Returns a parsed `[xml]` object (its content-type is `application/xml`); use `.OuterXml` if you need
the raw text to diff or write back. Read-only by default. If the user wants to **write** a modified
config.xml back (`POST .../config.xml`), that's a mutating call — apply the confirm discipline below.

### 2.4 Trigger a build (no parameters) — MUTATING, confirm first

```powershell
java -jar jenkins-cli.jar -s "$env:JENKINS_URL" -auth "$($env:JENKINS_USER):$($env:JENKINS_API_TOKEN)" `
  build "<JOB_NAME>"
```

REST equivalent:

```powershell
Invoke-RestMethod -Method Post -Uri "$($env:JENKINS_URL)/job/<JOB_NAME>/build" -Headers $headers
```

### 2.5 Trigger a parameterised build — MUTATING, confirm first

```powershell
java -jar jenkins-cli.jar -s "$env:JENKINS_URL" -auth "$($env:JENKINS_USER):$($env:JENKINS_API_TOKEN)" `
  build "<JOB_NAME>" -p PARAM_NAME=value -p OTHER_PARAM=value2
```

REST equivalent (use `Invoke-WebRequest`, not `Invoke-RestMethod`, so the `Location` response header
is visible):

```powershell
$body = @{ PARAM_NAME = "value"; OTHER_PARAM = "value2" }
$resp = Invoke-WebRequest -Method Post -Uri "$($env:JENKINS_URL)/job/<JOB_NAME>/buildWithParameters" `
  -Headers $headers -Body $body
$resp.Headers.Location
```

Both return a `Location` header pointing at `.../queue/item/<id>/` — that's a **queue item ID, not a
build number** (see Common failure signatures — queue item vs. build number, and §2.12 below).

### 2.6 Get build status

```powershell
Invoke-RestMethod -Uri "$($env:JENKINS_URL)/job/<JOB_NAME>/<BUILD_NUMBER>/api/json?tree=result,building,duration,timestamp" -Headers $headers
```

`result` is `null` while `building:true`; otherwise one of `SUCCESS`/`FAILURE`/`ABORTED`/`UNSTABLE`.

### 2.7 Get console output — progressive/tailing (large logs)

```powershell
$start = 0
while ($true) {
  $resp = Invoke-WebRequest -Uri "$($env:JENKINS_URL)/job/<JOB_NAME>/<BUILD_NUMBER>/logText/progressiveText?start=$start" -Headers $headers
  Write-Output $resp.Content
  $more = $resp.Headers['X-More-Data']
  $start = $resp.Headers['X-Text-Size']
  if ($more -ne 'true') { break }
  Start-Sleep -Seconds 2
}
```

This is the pattern to use for **running** builds. For an already-**finished** build, prefer a
single fetch instead of looping from `start=0` — hitting `progressiveText` against a large completed
log can exhaust heap on the Jenkins side (a known upstream issue):

```powershell
Invoke-RestMethod -Uri "$($env:JENKINS_URL)/job/<JOB_NAME>/<BUILD_NUMBER>/consoleText" -Headers $headers
```

Jar equivalent for a live tail:
`java -jar jenkins-cli.jar -s "$env:JENKINS_URL" -auth "$($env:JENKINS_USER):$($env:JENKINS_API_TOKEN)" console "<JOB_NAME>" -f`

### 2.8 Stop / abort a running build — MUTATING, confirm first

```powershell
Invoke-RestMethod -Method Post -Uri "$($env:JENKINS_URL)/job/<JOB_NAME>/<BUILD_NUMBER>/stop" -Headers $headers
```

No dedicated jar `stop` sub-command exists on all Jenkins versions consistently — the REST `/stop`
endpoint is the reliable path. Confirm the exact build number with the user before firing; aborting
the wrong number wastes someone else's build.

### 2.9 List the build queue

```powershell
(Invoke-RestMethod -Uri "$($env:JENKINS_URL)/queue/api/json?tree=items[id,task[name],why,stuck]" -Headers $headers).items
```

`why` explains what's blocking a queued item (e.g. waiting for an executor); `stuck:true` flags an
item that's been waiting abnormally long.

### 2.10 Get last successful / last failed build

```powershell
Invoke-RestMethod -Uri "$($env:JENKINS_URL)/job/<JOB_NAME>/lastSuccessfulBuild/api/json?tree=number,timestamp,result" -Headers $headers
Invoke-RestMethod -Uri "$($env:JENKINS_URL)/job/<JOB_NAME>/lastFailedBuild/api/json?tree=number,timestamp,result" -Headers $headers
```

Other useful aliases on the same pattern: `lastBuild`, `lastStableBuild`, `lastUnstableBuild`,
`lastCompletedBuild`.

### 2.11 List nodes / agents

```powershell
(Invoke-RestMethod -Uri "$($env:JENKINS_URL)/computer/api/json?tree=computer[displayName,offline,numExecutors]" -Headers $headers).computer
```

### 2.12 Resolve a queue item to its eventual build number

Right after triggering (2.4/2.5), poll the queue item, not a guessed build number:

```powershell
$item = Invoke-RestMethod -Uri "$($env:JENKINS_URL)/queue/item/<QUEUE_ID>/api/json" -Headers $headers
if ($item.executable.number) { $item.executable.number } else { "not started yet" }
```

Once that number is non-null, that's the real build number to use in 2.6/2.7/2.8.

### 2.13 Who am I / token sanity check

```powershell
java -jar jenkins-cli.jar -s "$env:JENKINS_URL" -auth "$($env:JENKINS_USER):$($env:JENKINS_API_TOKEN)" who-am-i
```

Useful as a lighter-weight auth probe than a full job list.

### 2.14 Fetch the CSRF crumb (see §1) — read-only, safe any time

Already shown in §1 — repeated here only as a catalog entry, not a new command.

## 3. Output parsing: jar text/XML vs. `/api/json`

- The jar's `build`, `console`, `get-job` etc. return **plain text or raw XML** — fine for a human
  to read, awkward to parse reliably in a script (no stable schema guarantee across Jenkins
  versions).
- **Prefer `/api/json`** (with a `tree=` filter to keep the payload small) for anything you intend
  to parse or branch logic on: status checks, queue polling, node lists, "did it succeed."
  `Invoke-RestMethod` deserializes JSON into a PowerShell object automatically — no separate parsing
  step needed.
- Reserve the jar for the two things REST doesn't do as directly: **triggering** a build with the
  `build` sub-command's built-in "follow console and exit with the build's exit code" behavior
  (`-f`), and interactive-style console tailing (`-f`/`console`).

## 4. Pagination / large-output handling

- Console logs: use the progressive fetch pattern (§2.7) for running builds; a single `consoleText`
  fetch for finished ones. Never loop `progressiveText` from `start=0` against a build you already
  know has finished.
- Job/build lists: always pass `tree=` to `/api/json` to select only the fields you need
  (`tree=jobs[name,url,color]`, not a bare `/api/json`) — Jenkins will otherwise walk and serialize
  far more of the object graph (nested builds, actions, etc.) than you want.
- Queue/computer listings are typically small; no special handling needed beyond the `tree=` filter
  above.

## 5. Dry-run / confirm discipline

Every command marked **MUTATING** above (§2.4 trigger, §2.5 trigger-with-params, §2.8 abort, and any
`POST .../config.xml` write) requires an explicit, in-turn confirmation from the user before it
runs — not an inferred "they probably want this." This is in addition to, not instead of, Copilot's
own shell-command approval prompt — the command itself will still need to clear that separately.
Concretely:

1. State exactly what will run: which job, which build number (for abort), which parameters (for a
   parameterised trigger), against which `JENKINS_URL`.
2. Wait for the user to say yes in this turn. A prior general instruction to "keep builds green" or
   similar does not count as standing authorization for a specific trigger/abort.
3. If they decline or don't respond, don't run it — report back that it's pending.
4. Only then issue the mutating call, and report back the queue item ID / build number it returned
   so the user can follow along.

Reads (§2.1, §2.2, the read path of §2.3, §2.6, §2.7, §2.9, §2.10, §2.11, §2.12, §2.13, §2.14) need
no confirmation — they change nothing on the Jenkins controller.

## 6. Common failure signatures

| Symptom | Meaning |
|---|---|
| `403` + body mentions "No valid crumb" | CSRF crumb required and missing/stale — retry once with the crumb pattern above. |
| `401 Unauthorized` | `JENKINS_USER`/`JENKINS_API_TOKEN` wrong, expired, or revoked. Stop and tell the user — don't guess at a different token. |
| `403` without a crumb message | Authenticated fine, but this account lacks the Jenkins permission (e.g. `Job/Build`) for this action. Report which permission looks missing. |
| `404` on `/job/<name>/...` | Job name wrong, or it lives in a folder (`/job/<folder>/job/<name>/...` — Jenkins folder jobs need every path segment). |
| Trigger returns a `Location: .../queue/item/<id>/` but polling `/job/<name>/lastBuild` doesn't show it | You're looking at the wrong build — resolve the **queue item** (§2.12) to get the real build number before checking build-numbered endpoints. A queue item is not a build number and the two are easy to conflate. |
| `progressiveText` hangs or returns huge payload on a finished build | Known upstream heap-exhaustion pattern on large completed logs — switch to a single `consoleText` fetch instead. |
| Jar reports transport/connection errors under a reverse proxy | Try `-http` explicitly, or the default WebSocket transport, per whichever the proxy in front of this Jenkins tolerates — WebSocket has been the default since Jenkins 2.391 and avoids the reverse-proxy breakage the raw HTTP mode is known for; SSH (`-ssh -user <JENKINS_USER>`, keypair-based) is a third transport if both are blocked. |

## 7. Secrets rule

- `JENKINS_API_TOKEN` lives in the environment only — never in a command-line argument if an
  env-var/`@file` form is available (the jar supports `-auth @/path/to/token-file`, which keeps the
  token out of shell history/process listings), never echoed to logs or chat, never written into a
  file this skill produces.
- Rotate-on-suspicion: if a 401 shows up unexpectedly (not from a typo), treat the token as possibly
  compromised and tell the user to check/rotate it rather than retrying blind.
- Never commit `JENKINS_URL`/`JENKINS_USER`/`JENKINS_API_TOKEN` values, and keep this skill's output
  out of any repository.

## Acceptance checklist

This checklist is for reviewing a session that used the skill, and the skill itself.

- [ ] Auth check (`/api/json` probe via `Invoke-WebRequest`) run and green before any other call
      this session.
- [ ] Every read in this session used `/api/json` with a `tree=` filter, not an unfiltered fetch.
- [ ] Every mutating call (trigger, abort, config write) was confirmed by the user in-turn before it
      ran, and its target (job, build number, parameters) was stated back first — Copilot's own
      approval prompt is named as a second, separate layer rather than a substitute.
- [ ] Console log fetches used the progressive pattern for running builds and a single `consoleText`
      fetch for finished ones — never a `progressiveText` loop from zero against a completed build.
- [ ] Any triggered build's queue item was resolved to a real build number before further
      status/log calls referenced "the build."
- [ ] No token value appeared in a command-line argument, log line, or chat message.
- [ ] No real hostname, job name, or credential ended up in this skill's own files — only
      placeholders.
- [ ] Every command block is PowerShell-valid; the one bash variant given (§0's auth probe) is
      explicitly labeled as such.
- [ ] Nothing here points outside the kit except the tools' own public links.
- [ ] If the target is CloudBees CI: the "CloudBees CI specifics" section below was checked before
      concluding a CloudBees-only capability (RBAC, service accounts, CasC bundle reload) isn't
      available, and every mutating call in that section got the same in-turn confirmation as any
      other write in this skill.

## CloudBees CI specifics

CloudBees CI is a commercial Jenkins distribution. **Everything above in this skill —
`jenkins-cli.jar`, the stock Jenkins REST API, the `-auth username:apiToken` pattern — works
unmodified against a CloudBees CI instance.** Download `jenkins-cli.jar` from the operations
center's own "Jenkins CLI" page rather than assuming a copy from elsewhere matches the target's
Jenkins core version. CloudBees CI adds a small number of extra REST endpoints and one extra CLI
subcommand on top of that stock surface — nothing here requires a different tool.

### Extra auth option: service accounts

Alongside `username:apiToken`, CloudBees CI supports service-account credentials in the same
`-auth` slot: `service-account-name:token`. Prefer a service account (`CLOUDBEES_SERVICE_ACCOUNT` /
`CLOUDBEES_SERVICE_ACCOUNT_TOKEN` placeholders) over a personal API token for anything scripted —
it's built for automated processes and isn't tied to a human's session. Bonus: POSTs authenticated
with a service-account token skip the CSRF-crumb dance that personal-token POSTs need.

### Extra REST surface (curl or jenkins-cli, no special client needed)

- **RBAC (folders+ / roles / groups)** — `${JENKINS_URL}/groups/api/json`, `.../groups/createGroup`,
  `.../groups/{name}/addUser`, `.../groups/{name}/grantRole`, `${JENKINS_URL}/roles/api/json`,
  `.../roles/createRole`, `.../roles/{name}/grantPermissions`, etc. — same POST-with-token pattern
  as every other Jenkins REST write. Read-only listing (`.../api/json`) is safe to call freely;
  every create/delete/grant/revoke call is a mutation and needs the same dry-run/confirm discipline
  as any other Jenkins-CLI write in this skill.
- **Service accounts** — `${OPERATIONS_CENTER_URL}/serviceAccounts/api/` (root) and per-item scopes,
  for listing/creating accounts and tokens. Treat any returned token as a secret exactly like an API
  token — never log it, never write it to disk.
- **CasC bundle management** — `POST /casc-bundle-mgnt/check-bundle-update` (read-only check),
  `POST /casc-bundle-mgnt/reload-bundle` (hot-reloads the instance's Configuration-as-Code bundle
  with no restart). `check-bundle-update` is safe to call freely; `reload-bundle` is a mutation —
  confirm before calling, same as any other apply/deploy action. REST and CLI callers get
  synchronous behavior by default (UI defaults to async); both are configurable via a request
  parameter, so don't assume one without checking the response.

### Extra `jenkins-cli.jar` subcommand

`plugin-catalog` — manages CloudBees's enterprise plugin-catalog governance feature. Every other
documented CLI command is stock Jenkins CLI; this is the one CloudBees adds.

### High Availability gotcha (read consistency, not a new API)

If the target runs CloudBees CI in HA (active/active) mode, a load balancer may route each request
to a different controller replica. Two consequences for an agent reading state rather than assuming
a single source of truth:

- `/computer/api/json` returns an **aggregated** agent list across all replicas (this one's
  consistent).
- The **build list** returned by other endpoints can differ slightly depending on which replica
  answered the request. Don't treat one read as authoritative if results look incomplete or
  inconsistent between calls — re-query rather than concluding data is missing.

### UI-only, not API-reachable (don't go looking for an endpoint that isn't there)

- **Pipeline Explorer** (visual stage/log browser, Test Insights, Build Failure Analyzer summaries)
  is browser-only. No REST/CLI surface is documented for it. If test-failure or build-failure data
  is needed programmatically, go to the underlying (stock, non-CloudBees) JUnit / Build Failure
  Analyzer plugin APIs instead of looking for a Pipeline-Explorer-specific endpoint.
- **DevOptics** (deployment-frequency/lead-time/MTTR/change-failure-rate analytics) is a separate,
  dashboard-oriented product layered on top of CI, not an endpoint of the CI instance itself. Out of
  scope for a CI-driving agent.

### Not the same product — don't conflate

"CloudBees Platform" (also branded "CloudBees Unify") is a **different product** from CloudBees CI
— its own SaaS platform with its own docs tree and its own API introduction. Nothing in this
section applies to it, and no standalone CLI for it exists either. If a task ever targets that
product specifically, it needs its own research — don't reuse anything above against it.

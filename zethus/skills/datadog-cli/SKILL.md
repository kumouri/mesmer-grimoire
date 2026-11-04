---
name: datadog-cli
description: Query and lightly operate a Datadog org (logs, metrics, monitors, events, APM traces/spans, dashboards) from the terminal using the official Pup CLI, with a narrow PowerShell REST fallback for logs cursor pagination. Use when the user asks to search logs, chart/query a metric, list or inspect monitors, mute/unmute a monitor, post or search events, search APM spans/traces, or list/inspect a dashboard. Requires DD_API_KEY, DD_APP_KEY, DD_SITE in the environment. Never fires a mutating command (mute/unmute a monitor, post an event) without explicit user confirmation in the current turn.
---

# Datadog skill

Wraps **Pup CLI** (`DataDog/pup` — official, Apache-2.0, Rust binary, built for exactly this: an AI
agent driving Datadog from a command line) for every read and mutation this skill needs, with a
narrowly-scoped REST fallback against the raw Logs Search API for cursor pagination past the first
page. `dogshell` is explicitly deprecated by Datadog's own docs in favor of Pup and can't do logs
search or APM span search at all; `datadog-ci` covers none of this skill's surface (it's
CI/CD-pipeline tooling, not a query/operate tool for a live org). Run this skill on your own
machine, in your own session, with your own keys. Don't run it from shared automation or a
repository's CI, and keep its output out of version control.

## Setup / auth check

Required environment variables (placeholders — never hardcode real values):

```powershell
$env:DD_API_KEY = "<dd-api-key>"
$env:DD_APP_KEY = "<dd-app-key>"
$env:DD_SITE = "datadoghq.com"   # Datadog's own default public SaaS site (US1) — a safe placeholder
                                  # value, never an organisation-internal name. Other real values exist
                                  # (datadoghq.eu, us3/us5.datadoghq.com, ap1/ap2.datadoghq.com,
                                  # ddog-gov.com) — set whichever this org actually uses; a wrong
                                  # one fails closed (see below).
```

Pup also supports an interactive `pup auth login` (OAuth2, browser-based). This skill deliberately
does **not** use that flow — a browser-based login is a poor fit for a locked-down or headless
session — and relies on the env-var fallback above instead.

Before doing anything else in a session, verify the three are set and that auth actually works:

```powershell
pup monitors list --limit 1 -o json
```

- Returns JSON (even an empty list) → auth and site are good, proceed.
- `403` → see Common failure signatures (app-key scope, or wrong `DD_SITE`).
- `401` → bad/expired API key — stop and tell the user, don't retry blindly.
- connection error/timeout → `DD_SITE` unreachable from this machine (VPN? wrong region?) — stop and
  say so.

Never print `$env:DD_API_KEY` or `$env:DD_APP_KEY` in any command output, log line, or chat message.
Prefer the environment over a bare CLI argument — Pup reads both env vars automatically, so there is
normally no reason to ever pass a key on the command line at all.

**Pup releases very frequently** (multiple times some weeks) and flag names can drift from what's
documented here. Before relying on an unfamiliar flag, run `pup <command> --help` (or
`pup <command> <subcommand> --help`) rather than trusting this file blind — this file is a starting
map, not a frozen contract.

## Commands / operations

All IDs/queries below are placeholders (`<MONITOR_ID>`, `<DASHBOARD_ID>`, `<QUERY>`); substitute the
real value at call time, but never hardcode a real monitor/dashboard ID or query string into a file
you commit.

### 1. Auth / connectivity check

```powershell
pup monitors list --limit 1 -o json
```

Already shown above — repeated here only as a catalog entry.

### 2. List monitors

```powershell
pup monitors list --tags="<TAG_QUERY>" -o json
```

Omit `--tags` to list everything visible to this app key. Add `--limit N` to bound a noisy org.

### 3. Get a monitor's full definition

```powershell
pup monitors get "<MONITOR_ID>" -o json
```

### 4. Search logs — single page

```powershell
pup logs search --query="<QUERY>" --from="1h" --limit 100 -o json
```

`--from` accepts relative windows (`15m`, `1h`, `7d`) or ISO8601 timestamps. Prefer an absolute
`--from`/`--to` pair over a bare relative window when you intend to page through results — Datadog's
own pagination guidance warns that using `now` as a moving boundary makes cursor pagination
inconsistent across calls.

### 5. Search logs — cursor pagination past the first page (raw API fallback)

Pup's documented `logs search` surface does not expose a confirmed cursor/next-page flag — for a
query that plausibly has more matches than one `--limit` page holds, use the raw Logs Search API
directly, which is fully documented cursor pagination:

```powershell
$ddHeaders = @{
  "DD-API-KEY"          = $env:DD_API_KEY
  "DD-APPLICATION-KEY"  = $env:DD_APP_KEY
  "Content-Type"        = "application/json"
}

$cursor = $null
do {
  $page = if ($cursor) { @{ limit = 1000; cursor = $cursor } } else { @{ limit = 1000 } }
  $body = @{
    filter = @{ query = "<QUERY>"; from = "2026-09-15T00:00:00Z"; to = "2026-09-16T00:00:00Z" }
    page   = $page
  } | ConvertTo-Json -Depth 5

  $resp = Invoke-RestMethod -Method Post -Uri "https://api.$($env:DD_SITE)/api/v2/logs/events/search" `
    -Headers $ddHeaders -Body $body
  $resp.data

  $cursor = $resp.meta.page.after
} while ($cursor)
```

Stop when `meta.page.after` is absent/empty — that's the documented "no more pages" signal (the loop
above stops naturally once `$cursor` is `$null`). Always use absolute `from`/`to` timestamps here
(not a relative window recomputed each loop iteration).

### 6. Query a metric (timeseries)

```powershell
pup metrics query --query="avg:<METRIC_NAME>{<SCOPE>}" --from="1h" -o json
```

### 7. Post an event — MUTATING, confirm first

```powershell
pup events post --tags="<TAG1>,<TAG2>" --alert_type=info "<TITLE>" "<TEXT>"
```

### 8. Search events

```powershell
pup events search --query="<QUERY>" --from="1h" -o json
```

### 9. Search APM spans / traces

```powershell
pup traces search --query="<QUERY>" --from="1h" -o json
```

Example query shape: `service:<SERVICE_NAME> @duration:>500ms`. Same cursor-pagination caveat as
logs applies in principle (the underlying `/api/v2/spans/events/search` endpoint is cursor-paginated
and rate-limited to 300 requests/hour) — check `pup traces search --help` for a `--cursor`/`--limit`
flag before assuming a single call returns everything.

### 10. List dashboards

```powershell
pup dashboards list -o json
```

### 11. Get a dashboard's definition

```powershell
pup dashboards get "<DASHBOARD_ID>" -o json
```

### 12. List current downtimes (see what's already muted)

```powershell
pup downtime list -o json
```

Read-only — check this before muting anything, so you don't stack a redundant downtime on a monitor
that's already silenced.

### 13. Mute a monitor (create a scoped downtime) — MUTATING, confirm first

Pup deliberately has no direct `monitors mute` verb — Datadog's own guidance is to use the more
auditable Downtimes API instead:

```powershell
$payload = @'
{
  "data": {
    "type": "downtime",
    "attributes": {
      "monitor_identifier": {"monitor_id": <MONITOR_ID>},
      "scope": "<SCOPE, e.g. env:staging>",
      "display_timezone": "UTC",
      "schedule": {
        "start": "2026-09-16T20:00:00Z",
        "end": "2026-09-16T22:00:00Z"
      },
      "message": "<REASON>"
    }
  }
}
'@
$payloadPath = Join-Path $env:TEMP "downtime-payload.json"
Set-Content -Path $payloadPath -Value $payload

pup downtime create --file $payloadPath -o json
```

Print the payload file's contents in-chat as the "what this will do" preview **before** running the
create call — that file *is* the dry-run artifact for this command.

### 14. Unmute a monitor (cancel the downtime) — MUTATING, confirm first

```powershell
pup downtime cancel "<DOWNTIME_ID>"
```

Get `<DOWNTIME_ID>` from #12's output (match on `monitor_identifier.monitor_id`), not by guessing.

## Output parsing

- Every `pup` command above uses `-o json` — Pup's own docs describe JSON as the default and the
  format aligned with agent/machine consumption; `-o table`/`-o yaml` also exist for a human-facing
  glance but this skill standardizes on JSON so results can be piped to `ConvertFrom-Json` reliably.
- The one operation that requires the **raw HTTP API instead of the CLI**: logs search past the
  first page (#5). Everything else in this file has direct, documented `pup` coverage.
- Pipe every JSON result through `ConvertFrom-Json` for filtering rather than eyeballing raw output —
  e.g. `pup monitors list -o json | ConvertFrom-Json | Select-Object id, name, overall_state`.

## Pagination

- **Logs search:** cursor-based via the raw API (`page.cursor` request field, `meta.page.after`
  response field) — see #5. `pup logs search --limit N` alone only ever returns one bounded page;
  don't assume it auto-walks further pages.
- **APM spans/traces search:** same cursor shape at the API level (`/api/v2/spans/events/search`,
  rate-limited 300 req/hour) — check `pup traces search --help` for a pagination flag before
  assuming one call is exhaustive; fall back to the equivalent raw-API cursor loop (#5's pattern,
  pointed at `/api/v2/spans/events/search`) if it has none.
- **Everything else** (monitors, dashboards, events, downtimes lists): these are typically bounded
  collections for a single org/team and haven't shown a pagination requirement in research — but if
  a list command's output looks truncated at a suspiciously round number, check its `--help` for a
  `--limit`/`--cursor`/`--page` flag before assuming you have the full set.

## Dry-run / confirm discipline

Every command marked **MUTATING** above (#7 post event, #13 mute/downtime create, #14
unmute/downtime cancel) requires an explicit, in-turn confirmation from the user before it runs —
this is in addition to, not instead of, Copilot's own shell-command approval prompt, which still
applies separately to the command itself:

1. State exactly what will run and its effect: which monitor/event, what scope, what time window
   (for a downtime), what message/tags. For #13, show the full JSON payload file content as the
   preview — that file is the "dry run" artifact.
2. Wait for the user to say yes in this turn. A prior general instruction (e.g. "keep the noisy
   monitor quiet") does not count as standing authorization for a specific mute action today.
3. If they decline or don't respond, don't run it — report back that it's pending.
4. Only then issue the mutating call, and report back what it returned (event ID, downtime ID) so
   the user can verify or reverse it later.
5. **Never** pass `--yes`/`-y` or set `$env:DD_AUTO_APPROVE = "true"` to skip Pup's own confirmation
   prompts automatically — those exist for exactly the moment this skill is supposed to pause and
   ask the user instead. Likewise never use `--agent`-mode auto-approval as a way to route around
   the human-in-the-loop step above; agent mode's JSON-output behavior is fine to use, its
   confirmation-skipping behavior is not.

Reads (#1, #2, #3, #4, #5, #6, #8, #9, #10, #11, #12) need no confirmation — they change nothing in
the Datadog org.

## Common failure signatures

| Symptom | Meaning |
|---|---|
| `403` on a read that has data (e.g. `monitors list` returns empty when monitors should exist) | The app key most likely lacks the scope for that resource type (e.g. missing `monitors_read`) — report which call 403'd and which scope looks missing; don't retry with a guessed different key. |
| `403` specifically on `traces search`/spans | OAuth apps need the `apm_read` scope on this endpoint per Datadog's docs — same shape as the monitors case, different scope name. |
| `429 Too Many Requests` | Rate limited. Respect any `Retry-After` header if present; back off and retry once, don't hammer the endpoint in a loop. The spans list endpoint in particular is capped at 300 requests/hour. |
| `401 Unauthorized` | `DD_API_KEY` wrong, expired, or revoked. Stop and tell the user — don't guess at a different key. |
| Everything 403/404s even though the keys "look right" | Likely a **wrong `DD_SITE`** — the keys are valid for a different regional site than the one being called (e.g. keys minted on `datadoghq.eu` used against `datadoghq.com`). Confirm the org's actual site before assuming the keys themselves are bad. |
| A logs/spans search returns fewer results than expected and no error | You hit `--limit` on a single-page `pup` call without pagination — switch to the cursor-loop pattern (#5) rather than assuming that's the whole result set. |
| `pup <command>` flag rejected / "unrecognized argument" | Pup ships new releases very frequently — the flag name may have changed since this file was written. Run `pup <command> --help` before concluding the operation isn't supported. |

## Secrets rule

- `DD_API_KEY` and `DD_APP_KEY` live in the environment only — never in a command-line argument,
  never echoed to logs or chat, never written into a file this skill produces (the downtime payload
  file in #13 contains no secret — keep it that way).
- Rotate-on-suspicion: if a 401 shows up unexpectedly (not from a typo), treat the key as possibly
  compromised and tell the user to check/rotate it rather than retrying blind.
- Never commit `DD_API_KEY`/`DD_APP_KEY`/real `DD_SITE` values, and keep this skill's output out of
  any repository.

## Acceptance

This checklist is for reviewing a session that used the skill, and the skill itself.

- [ ] Auth check (`pup monitors list --limit 1 -o json`) run and green before any other call this
      session.
- [ ] Every command used `-o json` and its output was parsed with `ConvertFrom-Json`, not eyeballed
      as text.
- [ ] Any logs or spans search that could plausibly exceed one page used the cursor pattern (#5, or
      the spans equivalent) rather than trusting a single bounded `--limit` call.
- [ ] Every mutating call (event post, downtime create/mute, downtime cancel/unmute) was confirmed
      by the user in-turn, with the exact payload/effect stated back first, before it ran —
      Copilot's own approval prompt is named as a second, separate layer rather than a substitute.
- [ ] No `--yes`/`-y`/`DD_AUTO_APPROVE=true` was ever used to bypass that confirmation step.
- [ ] No API/app key value appeared in a command-line argument, log line, or chat message.
- [ ] No real hostname, org name, monitor ID, dashboard ID, or credential ended up in this
      skill's own files — only placeholders.
- [ ] Every command block is PowerShell-valid (`$env:` assignments, `Invoke-RestMethod`/
      `ConvertFrom-Json` instead of curl/jq, `@'...'@` here-strings instead of heredocs); no
      unlabeled bash-only construct appears anywhere in this file.
- [ ] Nothing here points outside the kit except the tools' own public links; the only cross-links
      are relative links to sibling skills.

---
name: confluence-cli
description: Drive Confluence (Cloud REST v2, DC REST v1 where noted) from the terminal via the `cfl` CLI (open-cli-collective/atlassian-cli), with a documented PowerShell Invoke-RestMethod fallback for the two operations `cfl` does not implement (comments, labels). Use for searching/reading/creating/updating Confluence pages, listing spaces and child pages, managing attachments, and adding labels/comments. Never runs a mutating command without first showing it and getting a yes; credentials come only from environment variables.
---

# Confluence via `cfl`

This skill drives Confluence Cloud (and, where noted, Data Center) using the `cfl` CLI from
[`open-cli-collective/atlassian-cli`](https://github.com/open-cli-collective/atlassian-cli), plus a
small PowerShell fallback for the two things `cfl` cannot do (comments, labels — confirmed absent
from its source tree, not just undocumented). `cfl` was picked over Atlassian's own `acli` because
`acli` has **zero Confluence coverage** as of this research (Jira-only); every other OSS Confluence
CLI surveyed was either Data-Center-only, feature-thin, or a single-star/no-release hobby project.
`cfl`'s own known gaps beyond comments/labels: no first-class page-tree/ancestors command (CQL
`ancestor=` substitutes), no bulk space export, no `--json` output (removed upstream — `-o plain`
TSV is the machine-readable mode instead).

Content from your organisation's Confluence can be sensitive. Keep it, and every credential, out of
version control: never commit either into a repository.

## 0. Setup and auth check

Credentials come from environment variables only, using the same three-variable shape as the
[jira-cli](../jira-cli/SKILL.md) skill:

```
CONFLUENCE_BASE_URL     # e.g. https://example.atlassian.net  (placeholder — never a real host)
CONFLUENCE_EMAIL        # the Atlassian account email these actions run as
CONFLUENCE_API_TOKEN    # a classic API token from https://id.atlassian.com/manage-profile/security/api-tokens
```

`cfl` itself expects `ATLASSIAN_URL` / `ATLASSIAN_EMAIL` / `ATLASSIAN_API_TOKEN` (shared with the
sibling `jtk` Jira CLI) or its own config file. Map the skill's env vars onto `cfl`'s at the start of
every session — never hardcode a value on either side:

```powershell
$env:ATLASSIAN_URL = $env:CONFLUENCE_BASE_URL
$env:ATLASSIAN_EMAIL = $env:CONFLUENCE_EMAIL
$env:ATLASSIAN_API_TOKEN = $env:CONFLUENCE_API_TOKEN
```

Then verify:

```powershell
cfl --version                 # confirm the binary is installed (this skill targets cfl v1.0.36+)
cfl config test                # confirms URL + identity resolve; fails loudly and specifically if not
```

If either command fails or a `CONFLUENCE_*` variable is unset: stop and say exactly which variable is
missing or which check failed. Do not guess a base URL, do not fall back to a previously-seen value,
and do not print the token in the error.

**Never**: print `$env:CONFLUENCE_API_TOKEN` in a command whose output gets logged, write it to a
file, or include it in any output shown back to the user. Passing it inside an auth header built from
the env var (as in §6/§7 below) is fine — that's an env expansion, not a literal.

**Build the auth header once per session** (used by every `Invoke-RestMethod` fallback call below):

```powershell
$pair = "$($env:CONFLUENCE_EMAIL):$($env:CONFLUENCE_API_TOKEN)"
$basicAuth = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
$headers = @{ Authorization = "Basic $basicAuth" }
```

## 1. Search — CQL

```powershell
cfl search --cql "type=page AND space=DEVOPS AND lastModified > now('-7d')" --limit 25
cfl search "runbook" --space DEVOPS --type page          # simple query-builder form
cfl search --label "onboarding" --limit 10
```

Raw `--cql` is mutually exclusive with the positional query and the `--space`/`--type`/`--title`/
`--label` builder flags — pick one form, not both.

Common CQL patterns:

| Intent | CQL |
|---|---|
| Pages in a space | `type=page AND space=KEY` |
| Recently modified | `type=page AND lastModified > now('-7d')` |
| By label | `type=page AND label="onboarding"` |
| Child pages of a page (the page-tree substitute — see §5) | `type=page AND ancestor=123456` |
| Title contains | `type=page AND title~"deploy"` |

## 2. Get a page by ID

```powershell
cfl page view 123456                                  # markdown, truncated at 5000 chars
cfl page view 123456 --no-truncate                    # full content
cfl page view 123456 --content-only                   # body only, no metadata header (pipe-friendly)
cfl page view 123456 --body-format xhtml --content-only   # exact storage XHTML — see §4a for why this matters
cfl page view 123456 --full                            # add parent ID, created time, author ID
```

## 3. Get a page by title (`cfl` has no direct "get by title" — resolve via search first)

```powershell
$line = cfl search --title "Deployment Runbook" --space DEVOPS -o plain | Select-Object -First 1
$pageId = ($line -split "`t")[0]
cfl page view $pageId
```

`-o plain` emits TSV with the ID in the first column — that's the one machine-readable output mode
`cfl` has (see §10). `-split "`t"` splits on a literal tab.

## 4. Create a page

```powershell
cfl page create --space DEVOPS --title "New Runbook" --file content.md
cfl page create --space DEVOPS --title "New Runbook" --parent 123456 --file content.md   # as a child page
"# Hello" | cfl page create -s DEVOPS -t "Quick Note"                                     # stdin works too
```

Default input format is Markdown, converted to the Cloud editor format (ADF). Use `--body-format
xhtml` with content that must round-trip exactly (macros, certain link types) — see §4a.

## 4a. Update a page — version-number handling (the documented failure point)

**No version number needs to be tracked or passed.** `cfl page edit` fetches the page's current
version internally and increments it before sending the update — verified by reading `cfl`'s own
source (`internal/cmd/page/edit.go`): it calls `existingPage.Version.Number + 1` and never exposes
that number as a flag. This is the opposite of the raw REST API, which requires the caller to supply
`version.number = current + 1` and 409s if it's stale — `cfl` absorbs that.

```powershell
cfl page edit 123456 --file content.md                     # replace body from file
cfl page edit 123456 --title "New Title"                    # title-only update (resends existing body)
cfl page edit 123456 --parent 654321                        # move to a new parent
"# Updated" | cfl page edit 123456                          # update body from stdin
```

**Lossless round-trip for macro-heavy pages** (Markdown round-tripping is lossy — it can silently
drop emphasis-around-inline-code and turn internal links into plain URLs; `cfl` refuses a write that
would lose such content unless `--allow-lossy` is passed):

```powershell
cfl page view 123456 --body-format xhtml --content-only > page.xhtml
# ...edit page.xhtml...
cfl page edit 123456 --body-format xhtml --file page.xhtml
```

For an exact body format (`xhtml`/`adf`), `cfl` reads the page back after writing and diffs what it
sent against what Confluence actually stored (Confluence is known to silently normalize some content
on write). Use `--no-verify` only to deliberately skip that check.

**Remaining race:** between `cfl`'s internal read and its write, someone else could save the page. If
that happens the update call returns a 409 — the fix is simply to re-run the same `cfl page edit`
command; it re-fetches the now-current version on the retry. Never hand-construct a version number to
work around this.

## 5. List child pages / page tree

`cfl` has no dedicated page-tree command. Use CQL's `ancestor` field:

```powershell
cfl search --cql "type=page AND ancestor=123456" --limit 50
```

For pages directly in a space (not nested), `cfl page list --space DEVOPS` also works and is simpler
when the parent/child relationship itself isn't needed.

## 6. Comments — not in `cfl`; PowerShell REST fallback

`cfl` has no comment command (confirmed by reading its source tree, not just its docs). Use the Cloud
REST v2 comment endpoints directly, reusing `$headers` from §0:

```powershell
# Get footer comments for a page
$resp = Invoke-RestMethod -Uri "$($env:CONFLUENCE_BASE_URL)/wiki/api/v2/pages/123456/footer-comments" -Headers $headers
$resp.results | Select-Object id, status, @{n='body'; e={$_.body.storage.value}}

# Add a comment to a page (top-level, not a reply)
$body = @{
  pageId = "123456"
  body   = @{ representation = "storage"; value = "<p>Looks good.</p>" }
} | ConvertTo-Json -Depth 5

$resp = Invoke-RestMethod -Method Post -Uri "$($env:CONFLUENCE_BASE_URL)/wiki/api/v2/footer-comments" `
  -Headers $headers -ContentType "application/json" -Body $body
$resp | Select-Object id, status
```

Data Center note: the equivalent v1 endpoint is `POST /rest/api/content/{id}/child/comment`.

Bash equivalent (only if ever running under Git Bash/WSL instead of PowerShell):

```bash
curl -s -u "$CONFLUENCE_EMAIL:$CONFLUENCE_API_TOKEN" \
  "$CONFLUENCE_BASE_URL/wiki/api/v2/pages/123456/footer-comments" | jq '.results[] | {id, status, body: .body.storage.value}'
```

## 7. Labels — `cfl` can read but not write; v2 read, v1 write

The Cloud REST **v2** label endpoint is read-only as of this research; **adding** a label still
requires **v1**.

```powershell
# Get labels on a page (v2, read-only)
$resp = Invoke-RestMethod -Uri "$($env:CONFLUENCE_BASE_URL)/wiki/api/v2/pages/123456/labels" -Headers $headers
$resp.results.name

# Add a label (v1 — v2 has no create endpoint for labels yet)
$body = @(@{ prefix = "global"; name = "onboarding" }) | ConvertTo-Json
$resp = Invoke-RestMethod -Method Post -Uri "$($env:CONFLUENCE_BASE_URL)/wiki/rest/api/content/123456/label" `
  -Headers $headers -ContentType "application/json" -Body $body
$resp
```

## 8. Attachments

```powershell
cfl attachment list --page 123456
cfl attachment list --page 123456 --unused              # orphaned attachments not referenced in the body
cfl attachment upload --page 123456 --file ./diagram.png -m "updated diagram"
cfl attachment download 789 -O diagram.png
cfl attachment delete 789 --force                        # skips the interactive confirm — see §12
```

## 9. Space info

```powershell
cfl space list --limit 25
cfl space list --type global                             # or --type personal
cfl space view DEVOPS                                     # alias: `get`
```

## 10. Output parsing

`cfl` has **no `--json` flag** — it was removed upstream. Two machine-readable options instead:

- `-o plain` for list/search commands — TSV; the first column is always the ID. Split on a tab
  (`-split "`t"`) and take the first element.
- `--body-format xhtml` or `--body-format adf` on `page view` for an exact, complete body — never
  truncated regardless of `--no-truncate`.

For the `Invoke-RestMethod` fallback calls (§6, §7), the response is already a deserialized
PowerShell object — no separate JSON-parsing step needed.

## 11. Pagination

- `cfl space list --cursor CURSOR` — cursor pagination; take the cursor from the previous response
  and pass it back for the next page.
- `cfl page list --limit N` and `cfl search --limit N` cap result count but don't expose a cursor flag
  directly — if more than one page of results is needed from these, page manually against the raw v2
  API using its `Link`/`next` cursor:

  ```powershell
  $resp = Invoke-RestMethod -Uri "$($env:CONFLUENCE_BASE_URL)/wiki/api/v2/spaces/$SpaceId/pages?limit=50" -Headers $headers
  $resp._links.next
  ```

  and follow `_links.next` until it's absent.
- CQL search (`cfl search --cql`, and the raw v1 `/wiki/rest/api/search` it wraps) returns `next`/
  `prev` links with an embedded cursor the same way.

## 12. Show it, then run it — for every mutating command

`cfl` has no universal `--dry-run` flag. Treat this as the discipline instead, for every mutating
operation (create, edit, delete, move, upload, attachment delete, label add, comment add) — **in
addition to, not instead of, Copilot's own shell-command approval prompt**, which still applies
separately to the command itself:

1. **Read before writing.** Before any `page edit`, run `cfl page view` first and show what's
   currently there. Before any `attachment delete`/`page delete`, confirm the target ID against a
   fresh `list`/`search`, never a remembered ID from earlier in the conversation.
2. **State the action before running it.** One line: what will change, on what page ID/title, in
   what space — before the command that mutates it runs. Show the exact command, then put the go-ahead to the person as a choice. Ask it with the harness's question tool ([why](../../docs/ask-with-the-question-tool.md)): two options, "Run it" (describe the exact effect) and "Don't run it" (nothing changes), neither preselected. Only a picked "Run it" runs it; a dismissed picker, no answer or a run with no one to ask means don't. With no question tool, ask a numbered list that accepts the number or any clear wording, never an exact phrase.
3. **Prefer the non-`--force` path.** `page delete` and `attachment delete` prompt for confirmation
   by default; only pass `--force` once the user has already explicitly confirmed in this
   conversation. Never pre-emptively add `--force` to "save a step."
4. **Labels and comments (the REST fallback) have no confirmation prompt at all** — the discipline
   above (state the action, confirm the target ID) is the only gate. Never batch multiple label/comment
   additions without restating each target.
5. **Never skip §4a's version handling** by hand-crafting a `version.number` in a raw REST call unless
   the current value was just read in that same turn.

## 13. Common failure signatures

| Symptom | Meaning | What to do |
|---|---|---|
| `401` / `unauthorized` / "invalid credentials" | Missing/expired/wrong API token, or email mismatch | Re-check `CONFLUENCE_EMAIL`/`CONFLUENCE_API_TOKEN`; regenerate the token at the URL in §0 if needed. Never retry blindly with the same creds more than once. |
| `403` / `permission denied` on a specific page/space | The authenticated account lacks access to that space/page, not a config problem | Say so plainly; don't retry, don't assume a typo in the ID. Ask whether a different account or a space-admin grant is needed. |
| `409` on `page edit`/update | Version conflict — someone else saved between the read and the write (§4a) | Re-run the same `cfl page edit` command; it re-fetches the current version. Do not hand-set a version number to force it. |
| `404`/`not found` on a plausible page ID | Wrong ID, page deleted/trashed, or (Confluence quirk) a permission failure disguised as 404 | Re-locate with `cfl search --title "..." --space KEY` rather than guessing at nearby IDs. |
| CQL syntax error (400, message mentions the query) | Malformed CQL — usually an unquoted value or a bad field name | Quote string literals, check field names against §1's table, and test the query with `--limit 1` before widening it. |
| Space key/ID not found | Typo, or using a space **key** (`DEVOPS`) where an **ID** was required (they're not interchangeable in every endpoint) | `cfl space list` to confirm the exact key/ID before use. |
| `page create`/`page edit` silently drops content on read-back verification | Confluence normalized the ADF/XHTML sent (see §4a's write-drift check) | This is `cfl` correctly catching a Confluence-side lossy write, not a bug in the command — inspect what it reports, don't suppress with `--allow-lossy` reflexively. |

## Acceptance

This checklist is for reviewing the skill itself. The live checks need a Confluence instance and a
throwaway test page.

- [ ] `cfl --version` succeeds and `cfl config test` resolves identity against
      `$env:CONFLUENCE_BASE_URL` with no hardcoded host/token anywhere in this skill.
- [ ] `cfl search --cql "type=page AND space=<a real space key>" --limit 5` returns results.
- [ ] `cfl page create ... --file <tmp>.md` creates a page and prints its ID; the page is visible via
      `cfl page view <id>` immediately after.
- [ ] `cfl page edit <id> --file <tmp>.md` updates it with **no version number supplied by the caller
      anywhere**, and a manual concurrent edit followed by the same command reproduces and resolves a
      409 by simple re-run (§4a, §13).
- [ ] `cfl page list --space <key>` and the CQL `ancestor=<id>` pattern (§5) both return the expected
      child pages for a page known to have children.
- [ ] The `Invoke-RestMethod` label-add (§7) and comment-add (§6) recipes each succeed once against a
      throwaway test page, and their GET counterparts show the result back.
- [ ] `cfl attachment upload`/`download`/`delete` round-trips a small test file.
- [ ] No command in this skill ever printed `$env:CONFLUENCE_API_TOKEN` to stdout/stderr/logs.
- [ ] Every command block is PowerShell-valid; the `curl`/`jq` variant appears only as an explicitly
      labeled bash alternative.

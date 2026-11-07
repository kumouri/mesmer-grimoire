# The session review report stays generic by construction

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-11-06 |
| Deciders | Ceryce Armstrong |
| Source | Ceryce's request of 2026-11-06, for use in a workplace where transcripts can't leave |
| Enforced where | [`../scripts/session-review.py`](../scripts/session-review.py) (`action`, `pair`, `render`, `check_report`); [`../skills/session-review/SKILL.md`](../skills/session-review/SKILL.md); `tests/test_zethus_session_review.py` |
| Supersedes | — |
| Superseded by | — |

## Decision

The report is written by a script, from a fixed vocabulary, integers, dates and "Session N" labels.
The script checks its own output against that vocabulary and refuses to write anything else. The
model hands the file over as written.

## Context

A reader who must learn nothing about the work should still be able to learn how the agent failed.
Scrubbing a summary can't promise that: a scrubber has to recognize every private term, and the
terms that matter are the ones nobody listed. A model can't promise it either, since it would
compose the report with the transcript in front of it. So the transcript's text has no route to the
report, and the design is built to keep it that way.

## How the guarantee works

| Layer | What it does | Where |
|---|---|---|
| 1. Strings stop early | `action` and `pair` turn a transcript into enum values, integers, booleans and in-memory hashes. An `Action` and an `Exchange` hold no text. The hashes are salted per process and never written | `action`, `pair` |
| 2. Fixed text only | `render` builds lines from `TEMPLATES` and `PATTERNS`, filling holes with numbers, dates and session labels. It takes no string from a session | `render` |
| 3. The check | `check_report` matches every line against regexes built from those same constants. Each hole is typed: digits, a date, a duration, a session label or one of the fixed names. Anything else, or any non-ASCII byte, refuses the write. Its error names no text | `check_report` |
| 4. Quiet failures | Errors during a scan are fixed sentences. An exception's message can quote a transcript, so it's never printed, and neither is a traceback | `main`, `read_session` |
| 5. Categories, not tools | An MCP server or plugin name can name an internal system, so a tool is only ever one of shell, file read, file edit, search, web or other. The lookup is exact, so an unknown name is "other" even if it contains a known word | `CATEGORY` |
| 6. One file, outside git | It reads read-only, makes no network calls, spawns nothing and writes one file. The default path is outside any git working tree, and a path inside one is refused unless the user passes `--allow-inside-git` | `cmd_scan` |

The list of sessions is the one place a title or an ask's opening words appear. It goes to the
screen because the user needs it to recognize a session, and the scan doesn't use it.

Timestamps are too specific, so the report has dates and whole-minute durations and no time of day.
`--no-date` leaves every date out, and the check then refuses a date too.

The canary test fills every field an adapter touches with a marker, for every store, then asserts
that none reaches the report, the scan's output or any file written. It also asserts that the
patterns fired on that same data, because an adapter that dropped everything would otherwise pass.

## What it can't catch

- **What the counts themselves say.** Dates, durations and counts are facts about the work's rhythm:
  that someone used an agent on those days, for that long, with that many failures. `--no-date`
  removes the dates and nothing else. Someone who already knows a lot may narrow things down from
  the rest.
- **The choice of what to scan.** Selecting only certain sessions is itself information the report
  doesn't show, and the numbers follow from it.
- **What classification reacts to.** An ask's opening words decide which row it counts in, so a count
  depends on the text in a very small way. No text can be reconstructed from it, but the dependence
  exists.
- **Anything outside the file.** The on-screen list, this chat and the host's own session log all
  hold titles and possibly text from the list step. Reading a list aloud, or photographing that
  screen, isn't covered. The next session review would list this session too.
- **A model that ignores the skill.** It's told to hand over the file untouched, and not to open
  session files. Nothing can enforce that in a chat. What's enforced is that the file came from the
  script: check that it's the file the script named.
- **Edits after writing.** The check runs once, before the write. A file edited later is just a file.
- **A sync folder.** The default path is outside git, not outside everything. A home folder that a
  sync client copies elsewhere would copy the report too, though the report is what's meant to leave.
- **Whether the report is right.** The check proves the words are safe, not true. Every pattern is
  a heuristic and says what it can't tell.

## Where sessions live, and how that was checked

Checked in November 2026. No session file from this machine's real use was read: the three verified
stores were checked with throwaway sessions running an invented task, then deleted.

| Store | Path | Status | Evidence |
|---|---|---|---|
| Copilot CLI | `~/.copilot/session-state/<id>/events.jsonl`; `$COPILOT_HOME` moves the root | **Verified** on 1.0.108-1 (runtime 1.0.106-9) | GitHub publishes no schema; third-party parsers call it reverse-engineered ([toolpath-copilot][toolpath]). Seen on a real run: `success` stays `true` on a nonzero exit, and the exit code is in `shellExecution.exitCode` and in a `<shellId: N completed with exit code M>` trailer. A background command is `mode: "async"`, and its end is a `system.notification` of `shell_completed`. An interrupt was not seen on that run: `abort` comes from the same third-party list. An older `~/.copilot/history-session-state/*.json` is listed so it shows as could-not-read rather than vanishing |
| Claude Code | `~/.claude/projects/<project>/<id>.jsonl`; `$CLAUDE_CONFIG_DIR` moves the root | **Verified** on 2.1.309 | Real run. `is_error` is on the `tool_result` block and a turn end is `stop_reason: "end_turn"`. Not seen on that run: a background command, an interrupt, a title line. Those branches rest on the [community format notes][claude-format] and on what's known of the tool |
| Codex | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`; `$CODEX_HOME` moves the root | **Verified** on 0.159.2 | Real run: `item_completed` items (`UserMessage`, `AgentMessage`, `CommandExecution` with `exit_code` and `status`), with a mirror in `response_item`. The older spelling (`user_message`, `exec_command_end`) rests on [third-party notes][codex-format] only |
| JetBrains | `~/.copilot/jb/<id>/*.jsonl` | **Not verified** | File names `partition-N.jsonl` were seen on one machine, with the contents not read. The event names rest on [a third party's parser][codeburn], and are read with the CLI's adapter |
| VS Code | `workspaceStorage/<hash>/chatSessions/*.json` or `.jsonl`, and `globalStorage/emptyWindowChatSessions/*`, under each edition's user folder | **Not verified** | Read from VS Code's source: the [mutation log][vsc-log] and the [serialized tool invocation][vsc-chat]. Never run. Response parts carry no timestamps, so stalls can't be detected there |
| Copilot cloud agent | None local | Nothing to read | Its sessions run on GitHub, so `list` finds nothing and says so |

Tool names beyond the ones seen on those runs come from the same sources. An unknown one is counted
as "other", which can undercount shell or edit activity on a host that renames its tools.

On that Codex run, files were written through shell commands, so they count as shell and not as
file edit. The edit patterns undercount wherever a host does that.

A stop hook's refusal reaches the model as a queued message. If a store logs that as a user message, it counts as an ask, which splits one exchange into two.

**A format that drifts shows up.** A file with no recognisable event is *could not read*. Copilot
tool events under names the adapter doesn't know make a session *partly read* rather than quietly
turning it into talk with no actions. A session with no asks says *no exchanges*. Nothing in that
list reads as a clean session.

## The patterns

Every pattern is a heuristic, and the report says so. Where a detector could guess, it doesn't count:

| Pattern | Kind | Fires on | Leans towards undercount because |
|---|---|---|---|
| Command failed at the parser | mistake | A nonzero shell whose output has the shell's own parse wording | Only those wordings; a program's own parse errors don't count |
| Retried straight after its own error | mistake | Same tool and same command start, right after failing | A read, a search, or 80 characters of message between them counts as a diagnosis |
| Files edited, nothing run after | process | A code edit with no later command in the exchange that could test it | Documentation edits are left out, and any command outside a short non-testing list counts as testing |
| Turn ended with a background command running | process | A turn end while a command started in the background hadn't reported finishing | A format with no background marker never fires |
| Turn ended with no reply | process | A tool call as the last thing before the next ask | The final exchange isn't counted, since a file that just ends can't show why |
| Long stall | process | A gap over the limit while the agent owed the next move | Time after a finished turn isn't counted, and neither is a user's wait before asking |
| Claimed done after a failed command | mistake | Finished-sounding final message, with the last command failed | A message that also mentions a problem isn't counted |
| Question answered with edits | mistake | A question, by its opening words or final `?`, then an edit | Polite requests are classed as changes first; unclassified asks never fire |
| Change request answered with only talk | mistake | A change ask, then a reply with no edit or command | A reply ending in a question isn't counted |
| Run request with no command run | mistake | A run or check ask, then a reply with no command | A reply ending in a question isn't counted |
| Asked to stop or wait, kept acting | mistake | A short stop or wait ask, then an edit or command | A longer instruction that opens with "stop" isn't treated as a stop |
| User corrected or interrupted the agent | mistake | An interrupt, or an ask opening as a correction, with the kind of action before it and how soon | Only opening words; a polite correction isn't seen |
| Flip-flopped between two edits | process | An exact edit, its reversal, and the edit again, in one file | Only exact reversals, and only in tools that record the text |
| Same failure in more than one session | mistake | A failed command with the same start and first error line in two or more sessions | Numbers are ignored, and any other difference hides the match |

The classification is English only. An ask in another language is "other", and fires nothing.

**Mnemosyne's vocabulary, with no dependency on it.** *Mistake* and *process* are its lesson
categories, and *correction* is its signal S5 ([lessons capture spec](../../docs/lessons-capture-spec.md#42-how-the-agent-identifies-one-in-session)).
S5 matches anywhere in a prompt, which is cheap for a hook that only asks; here a count stands alone
in a report, so the same words have to open the ask. Its S6, fail-then-succeed, wasn't added: it
measures a recovery, and the report is about failures. Mnemosyne's spool holds the user's own words
and paths by design, so this script doesn't read it, and nothing here imports Mnemosyne.

## Options considered

| Option | What it means | What it costs | |
|---|---|---|---|
| A — fixed vocabulary, a script writes, a check refuses | Text has no route to the report | A pattern's wording can only change in code; the report can't explain a specific failure | **Chosen** |
| B — the model summarises, and a scrubber cleans it | Richer findings | A scrubber can't know every private term, and that's the guarantee gone | Declined |
| C — the identifier guard's shapes over free text | Reuses `check_identifiers.py` | Shape matching catches paths and misses a client's name in plain words. Its docstring says so | Declined |
| D — read Mnemosyne's spool instead of transcripts | One data source | It only holds what its hooks saw, and only where they're installed. Pairing needs the whole session | Declined |

## Consequences

- **Easier:** a report can leave a restricted environment without anyone reading it for leaks first.
- **Harder:** a finding can't name what happened. The reader learns the shape, and the user goes back
  to the session for the detail, by the list's number and handle.
- **New obligations:** a new pattern or line goes in `PATTERNS` or `TEMPLATES`, which also makes it
  allowed, so read it as public text. A new adapter adds a canary fixture. A hole in a template stays
  typed: `tests/test_zethus_session_review.py` fails on one that accepts free text.

[toolpath]: https://docs.rs/crate/toolpath-copilot/0.1.0/source/README.md
[claude-format]: https://claude-dev.tools/docs/jsonl-format
[codex-format]: https://docs.rs/crate/txcript/latest/source/docs/formats/codex.md
[codeburn]: https://github.com/getagentseal/codeburn/pull/433
[vsc-log]: https://raw.githubusercontent.com/microsoft/vscode/main/src/vs/workbench/contrib/chat/common/model/objectMutationLog.ts
[vsc-chat]: https://raw.githubusercontent.com/microsoft/vscode/main/src/vs/workbench/contrib/chat/common/chatService/chatService.ts

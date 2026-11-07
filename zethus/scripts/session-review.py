#!/usr/bin/env python3
"""List local agent sessions, then scan the ones the user selects into a generic report.

For use in a workplace where transcripts can't leave. The report says what went wrong in fixed
words, so it can be shown to someone who must learn nothing about the work.

    python session-review.py list                               # on-screen only, newest first
    python session-review.py scan --select a1b2c3d4,e5f6a7b8    # by the handles the list printed
    python session-review.py scan --select 1,3,5-7 --listing 7f3a9c01
    python session-review.py scan --select all --no-date

**The guarantee.** Nothing from a transcript reaches the report: no ask text, command text, error
message, file name, path, repo, branch, session id, title, tool name, username, host or URL.

1. Adapters read the text, and only ``action`` and ``pair`` see it. They keep enum values, integers,
   booleans and in-memory hashes (``Action``, ``Exchange``); the text is dropped there.
2. ``render`` writes fixed lines from ``TEMPLATES`` and ``PATTERNS``, filling in integers, dates and
   "Session N" labels. It takes no string from a session.
3. ``check_report`` then matches every line against the regexes those same constants build. One
   line that doesn't match refuses the write, and the error names no text.
4. Every error this script prints during a scan is a fixed sentence. An exception's message can hold
   transcript text, so it is never printed, and neither is a traceback.

Tool names can name an internal system, so a tool is only ever a category (``CATEGORY``), by exact
lookup; anything unknown is "other". ``list`` prints local titles, because the user needs them to
recognise a session. They go to the screen and nowhere else. See docs/session-review-guarantee.md
for what this can't catch, and for how each store's format was checked.

**Read-only.** Sessions are opened for reading. No network, nothing spawned, one report file and no
other (hence no bytecode cache for the shared helpers). A session that can't be parsed appears as
"could not read", never as a clean session with no failures.

**Limits** are defaults, set by flag or ``sessionReview.*`` in the Zethus config: ``listLimit``,
``maxSessions``, ``maxReportLines``, ``maxTableRows``, ``stallMinutes``.

Exit codes: 0 listed or written · 1 refused (a path inside a git tree, a stale listing, the check
failed, a report too long for its limit) · 2 usage error.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

sys.dont_write_bytecode = True      # importing _common must not write a .pyc beside the kit
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import UsageError, cfg, find_repo_root, load_config  # noqa: E402

DEFAULTS = {"listLimit": 30, "maxSessions": 30, "maxReportLines": 90, "maxTableRows": 12,
            "stallMinutes": 10}

# ------------------------------------------------------------------------------- normal form

SHELL, READ, EDIT, SEARCH, WEB, OTHER = "shell", "file read", "file edit", "search", "web", "other"
CATEGORIES = (SHELL, READ, EDIT, SEARCH, WEB, OTHER)
TALK = "talk only"

# Exact names only: an MCP tool called "acme-search" must stay "other", so no substring matching.
CATEGORY = {
    **dict.fromkeys(("powershell", "bash", "shell", "pwsh", "cmd", "run_in_terminal", "terminal",
                     "local_shell", "exec_command", "shell_command", "execute", "runinterminal",
                     "read_powershell", "write_powershell", "stop_powershell", "list_powershell",
                     "read_bash", "write_bash", "stop_bash", "list_bash", "get_terminal_output",
                     "bashoutput", "taskoutput", "killshell"), SHELL),
    **dict.fromkeys(("view", "read", "read_file", "readfile", "notebookread", "list_dir", "ls",
                     "get_file_contents", "copilot_readfile", "copilot_listdirectory"), READ),
    **dict.fromkeys(("create", "edit", "write", "multiedit", "notebookedit", "apply_patch",
                     "str_replace", "str_replace_editor", "insert", "write_file", "edit_file",
                     "create_file", "insert_edit_into_file", "replace_string_in_file",
                     "multi_replace_string_in_file", "copilot_createfile", "copilot_replacestring",
                     "copilot_insertedit", "copilot_applypatch"), EDIT),
    **dict.fromkeys(("grep", "glob", "rg", "search", "find", "file_search", "grep_search",
                     "semantic_search", "codebase", "copilot_searchcodebase", "copilot_findfiles",
                     "copilot_findtextinfiles"), SEARCH),
    **dict.fromkeys(("web_fetch", "web_search", "webfetch", "websearch", "fetch", "fetch_webpage",
                     "vscode_fetchwebpage", "copilot_fetchwebpage"), WEB),
}
POLL_TOOLS = {"read_powershell", "read_bash", "bashoutput", "taskoutput", "get_terminal_output"}

OK, FAILED, PARSER, UNKNOWN = "ok", "failed", "parser", "unknown"
QUESTION, CHANGE, RUN, STOP, CORRECTION, UNCLASSIFIED = ("question", "change", "run or check",
                                                         "stop or wait", "correction", "other")
ASK_KINDS = (QUESTION, CHANGE, RUN, STOP, CORRECTION, UNCLASSIFIED)
REPLY, INTERRUPTED, SILENT, OPEN = "reply", "interrupted", "no reply", "open"
READ_OK, READ_UNVERIFIED, READ_PARTLY, READ_NONE, READ_EMPTY = (
    "read", "read, format unverified", "partly read", "could not read", "no exchanges")

# The shells' own wording for a line they refused to run. A program's parse errors don't count.
SHELL_PARSE_RE = re.compile(
    r"ParserError|syntax error near unexpected token|unexpected EOF while looking for matching"
    r"|syntax error: unexpected end of file|Syntax error: .{0,30} unexpected"
    r"|was unexpected at this time", re.I)
# A command that changes or inspects things but proves nothing, for "nothing was run after an edit".
NON_VERIFY_HEADS = {
    "git", "gh", "ls", "dir", "cat", "type", "echo", "cd", "pwd", "mkdir", "rm", "cp", "mv", "del",
    "head", "tail", "grep", "rg", "find", "sed", "awk", "touch", "chmod", "which", "where", "write-output",
    "get-content", "get-childitem", "set-content", "add-content", "test-path", "select-string",
    "copy-item", "move-item", "remove-item", "new-item", "set-location", "write-host",
}
STILL_RUNNING_RE = re.compile(r"still running|<status>running|status: running", re.I)
COPILOT_TRAILER_RE = re.compile(r"<shellId: \S+ completed with exit code (\d+)>")
CODEX_EXIT_RE = re.compile(r"^Exit code: (\d+)|^Process exited with code (\d+)|\"exit_code\":\s*(\d+)", re.M)
DOC_SUFFIXES = {".md", ".txt", ".rst", ".adoc"}


def _fp(*parts: object) -> int:
    """An in-memory comparison key. Salted per process, never written, never printed."""
    return hash(parts)


@dataclass
class Action:
    """One tool call, with the strings already gone."""
    category: str
    outcome: str
    start: float | None
    end: float | None
    tool: int = 0
    call: int = 0
    head: int = 0
    signature: int = 0
    file: int = 0
    before: int = 0
    after: int = 0
    verifies: bool = False
    background: bool = False
    poll: bool = False
    bg_done: bool = False
    doc_only: bool = False


def _heads(command: str) -> list[str]:
    heads = []
    for segment in re.split(r"&&|\|\||;|\n", command):
        words = [w for w in segment.strip().split() if "=" not in w.split("/")[0]]
        if words:
            heads.append(re.split(r"[\\/]", words[0].strip("\"'&"))[-1].lower().removesuffix(".exe"))
    return heads


def action(tool: str, start: float | None, end: float | None = None, command: str | None = None,
           path: str | None = None, output: str = "", exit_code: int | None = None,
           failed: bool | None = None, before: str | None = None, after: str | None = None,
           background: bool = False) -> Action:
    """Reduce one tool call to its ``Action``. This is where its strings stop."""
    name = str(tool or "").lower()
    category = CATEGORY.get(name, OTHER)
    is_failed = bool(failed) or exit_code not in (None, 0)
    if is_failed:
        outcome = PARSER if category == SHELL and SHELL_PARSE_RE.search(output) else FAILED
    else:
        outcome = OK if failed is False or exit_code == 0 else UNKNOWN
    text = " ".join((command or "").split())
    heads = _heads(command or "")
    signature = 0
    if is_failed:
        first = next((ln for ln in output.splitlines() if ln.strip() and not ln.startswith("<shellId")), "")
        signature = _fp(name, heads[0] if heads else "", re.sub(r"\d+", "#", first.strip())) if first else 0
    return Action(
        category=category, outcome=outcome, start=start, end=end, tool=_fp(name),
        call=_fp(name, text or path or ""), head=_fp(heads[0]) if heads else 0, signature=signature,
        file=_fp(path) if path else 0, before=_fp(before) if before is not None else 0,
        after=_fp(after) if after is not None else 0,
        verifies=category == SHELL and outcome != PARSER and any(h not in NON_VERIFY_HEADS for h in heads),
        background=background, poll=name in POLL_TOOLS,
        bg_done=name in POLL_TOOLS and not STILL_RUNNING_RE.search(output),
        doc_only=bool(path) and Path(path).suffix.lower() in DOC_SUFFIXES)


ASK, SAY, ACT, BREAK, TURN_END, BG_DONE = "ask", "say", "act", "interrupt", "turn-end", "bg-done"


@dataclass
class Ev:
    """One entry in an adapter's stream. ``text`` lives only until ``pair`` has read it."""
    kind: str
    ts: float | None = None
    text: str = ""
    act: Action | None = None


@dataclass
class Parsed:
    events: list[Ev] = field(default_factory=list)
    title: str = ""
    malformed: int = 0
    recognised: int = 0
    unrecognised: int = 0


@dataclass
class Exchange:
    """One ask and everything before the next one. Holds no text."""
    ask: str
    start: float | None
    end: float | None
    actions: list[Action] = field(default_factory=list)
    had_say: bool = False
    final_say_len: int = 0
    claims_done: bool = False
    admits_problem: bool = False
    asks_back: bool = False
    ended: str = OPEN
    break_gap: float | None = None
    bg_left_running: bool = False
    stalls: int = 0
    says_before: list[int] = field(default_factory=list)  # longest say before each action


def _ts(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value / 1000 if value > 1e11 else float(value)
    if isinstance(value, str):
        try:
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def _rows(paths: list[Path], parsed: Parsed):
    for path in paths:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    parsed.malformed += 1
                    continue
                if isinstance(row, dict):
                    yield row
                else:
                    parsed.malformed += 1


def _plain(node: object) -> str:
    """Text under a string, a ``text``/``value``/``content`` key, or a list of those."""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "\n".join(t for t in (_plain(n) for n in node) if t)
    if isinstance(node, dict):
        for key in ("text", "value", "content"):
            if key in node:
                return _plain(node[key])
    return ""


def _args(node: object) -> dict:
    if isinstance(node, str):
        try:
            node = json.loads(node)
        except ValueError:
            return {}
    return node if isinstance(node, dict) else {}


def _pick(args: dict, *keys: str) -> str | None:
    for key in keys:
        if isinstance(args.get(key), str):
            return args[key]
    return None


# ------------------------------------------------------------------------------- adapters

COPILOT_IGNORED = ("session.", "system.", "hook.", "subagent.", "skill.", "permission.", "partition.",
                   "assistant.", "user.", "external_tool.", "tool.")


def parse_copilot_events(paths: list[Path]) -> Parsed:
    """``events.jsonl``: checked on a real Copilot CLI session (docs/session-review-guarantee.md).

    ``success`` stays true when a shell command exits nonzero, so ``shellExecution.exitCode`` and
    the ``<shellId: N completed with exit code M>`` trailer are what say it failed.
    """
    parsed = Parsed()
    pending: dict[str, tuple[int, str, dict, float | None]] = {}
    seen_plain_ask = saw_start = False
    other_tool_events = 0
    rendered: list[Ev] = []
    for row in _rows(paths, parsed):
        kind = str(row.get("type") or "")
        data = row.get("data") if isinstance(row.get("data"), dict) else row
        ts = _ts(row.get("timestamp"))
        nested = bool(data.get("parentToolCallId"))
        if kind in ("user.message", "user.message_rendered"):
            parsed.recognised += 1
            if nested:
                continue
            ev = Ev(ASK, ts, _plain(data.get("content") or data.get("text") or data.get("message")))
            if kind == "user.message":
                seen_plain_ask = True
            else:
                rendered.append(ev)
            parsed.events.append(ev)
        elif kind == "assistant.message":
            parsed.recognised += 1
            if nested:
                continue
            text = _plain(data.get("content") or data.get("text"))
            if text.strip():
                parsed.events.append(Ev(SAY, ts, text))
            if not data.get("toolRequests"):
                parsed.events.append(Ev(TURN_END, ts))
        elif kind == "tool.execution_start":
            parsed.recognised += 1
            saw_start = True
            if nested:
                continue
            call_id = str(data.get("toolCallId") or len(pending))
            args = _args(data.get("arguments") or data.get("args"))
            name = str(data.get("toolName") or data.get("name") or "")
            pending[call_id] = (len(parsed.events), name, args, ts)
            parsed.events.append(Ev(ACT, ts, act=_copilot_action(name, args, ts, None, {})))
        elif kind == "tool.execution_complete":
            parsed.recognised += 1
            call_id = str(data.get("toolCallId") or "")
            if call_id in pending:
                index, name, args, start = pending.pop(call_id)
                parsed.events[index].act = _copilot_action(name, args, start, ts, data)
        elif kind == "abort":
            parsed.recognised += 1
            parsed.events.append(Ev(BREAK, ts))
        elif kind == "system.notification":
            parsed.recognised += 1
            note = data.get("kind")
            if isinstance(note, dict) and note.get("type") == "shell_completed":
                parsed.events.append(Ev(BG_DONE, ts))
        elif kind.startswith(COPILOT_IGNORED):
            parsed.recognised += 1
            other_tool_events += kind.startswith("tool.")
        else:
            parsed.unrecognised += 1
    if seen_plain_ask:      # one turn can carry both spellings; the plain one wins
        for ev in rendered:
            ev.kind = "ignored"
    if not saw_start:       # tool events under names this reader doesn't know: it saw none of them
        parsed.unrecognised += other_tool_events
    return parsed


def _copilot_action(name: str, args: dict, start: float | None, end: float | None, data: dict) -> Action:
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    shell = data.get("shellExecution") if isinstance(data.get("shellExecution"), dict) else {}
    error = data.get("error") if isinstance(data.get("error"), dict) else {}
    output = _plain(result.get("content")) or _plain(error.get("message"))
    code = shell.get("exitCode")
    if not isinstance(code, int):
        m = COPILOT_TRAILER_RE.search(output)
        code = int(m.group(1)) if m else None
    return action(
        name, start, end, command=_pick(args, "command"), path=_pick(args, "path"),
        output=output, exit_code=code,
        failed=None if "success" not in data else data.get("success") is False,
        before=_pick(args, "old_str"), after=_pick(args, "new_str", "file_text"),
        background=args.get("mode") == "async")


CLAUDE_NOT_ASKS = ("<command-", "<local-command", "<system-reminder", "Caveat:", "<bash-")


def parse_claude(paths: list[Path]) -> Parsed:
    """``~/.claude/projects/<project>/<id>.jsonl``, checked on a real Claude Code session."""
    parsed = Parsed()
    pending: dict[str, tuple[int, str, dict, float | None]] = {}
    for row in _rows(paths, parsed):
        kind = row.get("type")
        if kind in ("custom-title", "ai-title", "summary"):
            parsed.title = parsed.title or _pick(row, "customTitle", "aiTitle", "summary") or ""
        if kind not in ("user", "assistant") or row.get("isSidechain"):
            parsed.recognised += "sessionId" in row or kind in ("custom-title", "ai-title", "summary")
            continue
        parsed.recognised += 1
        ts = _ts(row.get("timestamp"))
        message = row.get("message") if isinstance(row.get("message"), dict) else {}
        content = message.get("content")
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content
        for block in blocks if isinstance(blocks, list) else []:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text" and kind == "assistant":
                if str(block.get("text") or "").strip():
                    parsed.events.append(Ev(SAY, ts, str(block["text"])))
            elif btype == "text" and not row.get("isMeta"):
                _claude_user_text(parsed, str(block.get("text") or ""), ts)
            elif btype == "tool_use":
                args = _args(block.get("input"))
                name = str(block.get("name") or "")
                pending[str(block.get("id"))] = (len(parsed.events), name, args, ts)
                parsed.events.append(Ev(ACT, ts, act=_claude_action(name, args, ts, None, {})))
            elif btype == "tool_result" and str(block.get("tool_use_id")) in pending:
                index, name, args, start = pending.pop(str(block.get("tool_use_id")))
                parsed.events[index].act = _claude_action(name, args, start, ts, block)
        if message.get("stop_reason") == "end_turn":
            parsed.events.append(Ev(TURN_END, ts))
    return parsed


def _claude_user_text(parsed: Parsed, text: str, ts: float | None) -> None:
    if text.startswith("[Request interrupted"):
        parsed.events.append(Ev(BREAK, ts))
    elif text.startswith("<task-notification"):
        parsed.events.append(Ev(BG_DONE, ts))
    elif text.strip() and not text.startswith(CLAUDE_NOT_ASKS):
        parsed.events.append(Ev(ASK, ts, text))


def _claude_action(name: str, args: dict, start: float | None, end: float | None, block: dict) -> Action:
    return action(
        name, start, end, command=_pick(args, "command"), path=_pick(args, "file_path", "notebook_path"),
        output=_plain(block.get("content")),
        failed=None if "tool_use_id" not in block else bool(block.get("is_error")),
        before=_pick(args, "old_string"), after=_pick(args, "new_string", "content"),
        background=args.get("run_in_background") is True)


CODEX_NOT_ASKS = ("<environment_context", "<user_instructions", "<permissions", "<turn_aborted")
CODEX_PATCH_RE = re.compile(r"^\*\*\* (?:Update|Add|Delete) File: (.+)$", re.M)


def parse_codex(paths: list[Path]) -> Parsed:
    """``rollout-*.jsonl``, checked on a real Codex CLI session. It logs most things twice.

    ``item_completed`` items are the current spelling, ``user_message`` / ``agent_message`` /
    ``exec_command_end`` the older one (third-party notes only), and ``response_item`` the protocol
    log under both. The first of those a file has is the one read, so nothing counts twice.
    """
    parsed = Parsed()
    rows = list(_rows(paths, parsed))
    bodies = [r["payload"] for r in rows if r.get("type") == "event_msg" and isinstance(r.get("payload"), dict)]
    msgs = {str(b.get("type")) for b in bodies}
    items = {str(b["item"].get("type")) for b in bodies if isinstance(b.get("item"), dict)}
    new_items = "UserMessage" in items or "AgentMessage" in items
    has_exec = "CommandExecution" in items or "exec_command_end" in msgs
    pending: dict[str, tuple[int, str, dict, float | None]] = {}
    for row in rows:
        kind, payload = row.get("type"), row.get("payload")
        if kind not in ("event_msg", "response_item", "session_meta", "turn_context") \
                or not isinstance(payload, dict):
            continue
        parsed.recognised += 1
        ts, ptype = _ts(row.get("timestamp")), payload.get("type")
        if kind == "event_msg":
            _codex_event(parsed, ptype, payload, ts, new_items)
        elif kind == "response_item":
            _codex_item(parsed, pending, ptype, payload, ts, new_items, msgs, has_exec)
    return parsed


def _codex_event(parsed: Parsed, ptype: object, payload: dict, ts: float | None, new_items: bool) -> None:
    if ptype == "item_completed" and isinstance(payload.get("item"), dict):
        item = payload["item"]
        itype = item.get("type")
        if itype == "UserMessage":
            text = _plain(item.get("content"))
            if not text.startswith(CODEX_NOT_ASKS):
                parsed.events.append(Ev(ASK, ts, text))
        elif itype == "AgentMessage":
            parsed.events.append(Ev(SAY, ts, _plain(item.get("content"))))
        elif itype == "CommandExecution":
            parsed.events.append(Ev(ACT, ts, act=_codex_command(item, payload, ts)))
    elif ptype == "user_message" and not new_items:
        parsed.events.append(Ev(ASK, ts, _plain(payload.get("message"))))
    elif ptype == "agent_message" and not new_items:
        parsed.events.append(Ev(SAY, ts, _plain(payload.get("message"))))
    elif ptype == "exec_command_end":
        command = payload.get("command")
        text = command[-1] if isinstance(command, list) and command else command
        code = payload.get("exit_code")
        parsed.events.append(Ev(ACT, ts, act=action(
            "exec_command", ts, ts, command=text if isinstance(text, str) else None,
            output=_plain(payload.get("aggregated_output")), exit_code=code if isinstance(code, int) else None)))
    elif ptype == "task_complete":
        parsed.events.append(Ev(TURN_END, ts))
    elif ptype == "turn_aborted":
        parsed.events.append(Ev(BREAK, ts))


def _codex_command(item: dict, payload: dict, ts: float | None) -> Action:
    parsed_cmd = item.get("parsed_cmd")
    command = item.get("command")
    if isinstance(parsed_cmd, list) and parsed_cmd and isinstance(parsed_cmd[0], dict):
        text = "; ".join(str(p.get("cmd") or "") for p in parsed_cmd if isinstance(p, dict))
    else:
        text = command[-1] if isinstance(command, list) and command else str(command or "")
    code = item.get("exit_code")
    start, end = _ts(payload.get("started_at_ms")), _ts(payload.get("completed_at_ms"))
    return action("exec_command", start or ts, end or ts, command=text,
                  output=_plain(item.get("aggregated_output")),
                  exit_code=code if isinstance(code, int) else None,
                  failed=True if item.get("status") == "failed" else None)


def _codex_item(parsed: Parsed, pending: dict, ptype: object, payload: dict, ts: float | None,
                new_items: bool, msgs: set[str], has_exec: bool) -> None:
    if ptype == "message" and not new_items and "user_message" not in msgs:
        text = _plain(payload.get("content"))
        if payload.get("role") == "user" and not text.startswith(CODEX_NOT_ASKS):
            parsed.events.append(Ev(ASK, ts, text))
        elif payload.get("role") == "assistant" and "agent_message" not in msgs:
            parsed.events.append(Ev(SAY, ts, text))
    elif ptype in ("function_call", "custom_tool_call"):
        name = str(payload.get("name") or "")
        if name == "exec" or (has_exec and CATEGORY.get(name.lower()) == SHELL):
            return      # a wrapper or a mirror: the command's own event is the record of it
        args = _args(payload.get("arguments") if ptype == "function_call" else {})
        patched = CODEX_PATCH_RE.search(str(payload.get("input") or ""))
        if patched:
            args["path"] = patched.group(1)
        pending[str(payload.get("call_id"))] = (len(parsed.events), name, args, ts)
        parsed.events.append(Ev(ACT, ts, act=_codex_call(name, args, ts, None, None)))
    elif ptype in ("function_call_output", "custom_tool_call_output"):
        if str(payload.get("call_id")) in pending:
            index, name, args, start = pending.pop(str(payload.get("call_id")))
            parsed.events[index].act = _codex_call(name, args, start, ts, _plain(payload.get("output")))
    elif ptype == "web_search_call":
        parsed.events.append(Ev(ACT, ts, act=action("web_search", ts, ts)))


def _codex_call(name: str, args: dict, start: float | None, end: float | None, output: str | None) -> Action:
    command = args.get("command")
    text = command[-1] if isinstance(command, list) and command else command
    m = CODEX_EXIT_RE.search(output or "")
    code = int(next(g for g in m.groups() if g)) if m else None
    return action(name, start, end, command=text if isinstance(text, str) else _pick(args, "cmd"),
                  path=_pick(args, "path"), output=output or "", exit_code=code)


def _vscode_replay(path: Path) -> dict:
    """The mutation log VS Code writes: kind 0 sets the state, 1 sets a path, 2 pushes, 3 deletes."""
    state: object = None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.strip():
                continue
            entry = json.loads(line)
            kind = entry.get("kind")
            if kind == 0:
                state = entry.get("v")
                continue
            keys = entry.get("k") or []
            node = state
            for key in keys[:-1]:
                node = node[key]
            if kind == 1:
                node[keys[-1]] = entry.get("v")
            elif kind == 2:
                target = node.setdefault(keys[-1], []) if isinstance(node, dict) else node[keys[-1]]
                if entry.get("i") is not None:
                    del target[entry["i"]:]
                target.extend(entry.get("v") or [])
            elif kind == 3:
                if isinstance(node, dict):
                    node.pop(keys[-1], None)
    if not isinstance(state, dict):
        raise ValueError
    return state


def parse_vscode(paths: list[Path]) -> Parsed:
    """``chatSessions/*.json`` or ``.jsonl``, read from VS Code's source, never from a real session.

    Parts have no timestamps of their own, so a stall can't be seen here.
    """
    path = paths[0]
    if path.suffix == ".jsonl":
        state = _vscode_replay(path)
    else:
        with open(path, encoding="utf-8", errors="replace") as fh:
            state = json.load(fh)
    requests = state.get("requests") if isinstance(state, dict) else None
    if not isinstance(requests, list):
        raise ValueError
    parsed = Parsed(title=str(state.get("customTitle") or ""), recognised=len(requests))
    for request in requests:
        if not isinstance(request, dict):
            parsed.malformed += 1
            continue
        ts = _ts(request.get("timestamp"))
        parsed.events.append(Ev(ASK, ts, _plain((request.get("message") or {}))))
        parts = request.get("response")
        text = []
        for part in parts if isinstance(parts, list) else []:
            if not isinstance(part, dict):
                continue
            kind = part.get("kind")
            if kind in (None, "markdownContent", "markdownVuln"):
                text.append(_plain(part))
            elif kind == "toolInvocationSerialized":
                if text:
                    parsed.events.append(Ev(SAY, None, "".join(text)))
                    text = []
                parsed.events.append(Ev(ACT, None, act=_vscode_action(part)))
            elif kind in ("textEditGroup", "notebookEditGroup"):
                parsed.events.append(Ev(ACT, None, act=action("edit", None, None)))
        if "".join(text).strip():
            parsed.events.append(Ev(SAY, None, "".join(text)))
        model_state = request.get("modelState")
        if request.get("isCanceled") or (isinstance(model_state, dict) and model_state.get("value") == 2):
            parsed.events.append(Ev(BREAK, ts))
        else:
            parsed.events.append(Ev(TURN_END, ts))
    return parsed


def _vscode_action(part: dict) -> Action:
    specific = part.get("toolSpecificData") if isinstance(part.get("toolSpecificData"), dict) else {}
    terminal = specific.get("terminalCommandState") if isinstance(specific.get("terminalCommandState"), dict) else {}
    line = specific.get("commandLine")
    code = terminal.get("exitCode")
    return action(str(part.get("toolId") or ""), None, None,
                  command=_pick(line, "original", "userEdited") if isinstance(line, dict) else None,
                  exit_code=code if isinstance(code, int) else None,
                  failed=True if part.get("resultError") else None)


@dataclass
class Candidate:
    store: "Store"
    paths: list[Path]

    @property
    def key(self) -> str:
        return str(self.paths[0])

    @property
    def handle(self) -> str:
        return hashlib.sha256(self.key.encode("utf-8", "replace")).hexdigest()[:8]

    def mtime(self) -> float:
        return max(p.stat().st_mtime for p in self.paths)


def _copilot_roots() -> list[Path]:
    homes = [Path.home() / ".copilot"]
    if os.environ.get("COPILOT_HOME"):
        homes.insert(0, Path(os.environ["COPILOT_HOME"]))
    return homes


def _copilot_find(root: Path) -> list[list[Path]]:
    found = [[p] for p in root.glob("session-state/*/events.jsonl")]
    found += [[p] for p in root.glob("session-state/*.jsonl")]
    found += [[p] for p in root.glob("history-session-state/*.json")]
    return found


def _partition_order(path: Path) -> tuple:
    m = re.search(r"(\d+)", path.stem)
    return (int(m.group(1)) if m else -1, path.name)


def _jetbrains_find(root: Path) -> list[list[Path]]:
    found = []
    for folder in (p for p in root.glob("*") if p.is_dir()):
        files = sorted(folder.glob("*.jsonl"), key=_partition_order)
        if files:
            found.append(files)
    return found


def _vscode_roots() -> list[Path]:
    bases = [Path.home() / "Library" / "Application Support", Path.home() / ".config"]
    if os.environ.get("APPDATA"):
        bases.insert(0, Path(os.environ["APPDATA"]))
    roots = [b / app / "User" for b in bases for app in ("Code", "Code - Insiders", "VSCodium")]
    return roots + [Path.home() / ".vscode-server" / "data" / "User"]


def _vscode_find(root: Path) -> list[list[Path]]:
    found = []
    for pattern in ("workspaceStorage/*/chatSessions/*", "globalStorage/emptyWindowChatSessions/*"):
        found += [[p] for p in root.glob(pattern) if p.suffix in (".json", ".jsonl")]
    return found


def _claude_roots() -> list[Path]:
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return [Path(env)] if env else [Path.home() / ".claude"]


def _codex_roots() -> list[Path]:
    env = os.environ.get("CODEX_HOME")
    return [Path(env)] if env else [Path.home() / ".codex"]


@dataclass(frozen=True)
class Store:
    name: str
    verified: bool           # checked against a real session of this store's host
    roots: object
    find: object
    parse: object


STORES = (
    Store("copilot-cli", True, _copilot_roots, _copilot_find, parse_copilot_events),
    Store("jetbrains", False, lambda: [Path.home() / ".copilot" / "jb"], _jetbrains_find, parse_copilot_events),
    Store("vscode", False, _vscode_roots, _vscode_find, parse_vscode),
    Store("claude-code", True, _claude_roots,
          lambda root: [[p] for p in root.glob("projects/*/*.jsonl") if not p.name.startswith("agent-")],
          parse_claude),
    Store("codex", True, _codex_roots,
          lambda root: [[p] for p in root.glob("sessions/*/*/*/rollout-*.jsonl")], parse_codex),
)


def discover(only: list[str] | None, root_overrides: dict[str, Path]) -> list[Candidate]:
    """Every session on disk, last written first. Reads no session's contents."""
    found: dict[str, Candidate] = {}
    for store in STORES:
        if only and store.name not in only:
            continue
        roots = [root_overrides[store.name]] if store.name in root_overrides else store.roots()
        for root in roots:
            try:
                groups = store.find(root) if root.is_dir() else []
            except OSError:
                groups = []
            for paths in groups:
                candidate = Candidate(store, paths)
                found.setdefault(candidate.key, candidate)

    def order(c: Candidate) -> tuple:
        try:
            return (-c.mtime(), c.handle)
        except OSError:
            return (0.0, c.handle)
    return sorted(found.values(), key=order)


# ------------------------------------------------------------------------------- pairing

STOP_RE = re.compile(r"^\W*(?:please\s+)?(?:stop|wait|hold on|hold off|pause|cancel|abort|don['’]?t do anything"
                     r"|leave it|not yet|never ?mind)\b", re.I)
# Mnemosyne's correction signal (S5), tightened to the start of the ask: mid-sentence "don't" or
# "instead" is mostly an instruction, not a correction.
CORRECTION_RE = re.compile(r"^\W*(?:no\s*[,.!]|nope\b|wrong\b|actually\s*[,:]|that(?:['’]s| is) (?:wrong|not)"
                           r"|not what|you (?:didn['’]?t|broke|missed|forgot)|why did you|undo\b|revert (?:that|this)"
                           r"|don['’]?t\b|do not\b|instead\b)", re.I)
RUN_RE = re.compile(r"^\W*(?:please\s+)?(?:(?:can|could|would|will) you\s+(?:please\s+)?)?"
                    r"(?:run|test|execute|lint|verify|check|try|rerun|re-run|launch|start)\b", re.I)
CHANGE_RE = re.compile(r"^\W*(?:please\s+)?(?:(?:can|could|would|will) you\s+(?:please\s+)?)?"
                       r"(?:fix|add|change|update|implement|remove|delete|rename|refactor|create|write|make"
                       r"|edit|move|replace|build|set up|convert|migrate|bump|apply|commit)\b", re.I)
QUESTION_RE = re.compile(r"^\W*(?:what|why|how|when|where|who|which|explain|tell me)\b", re.I)
DONE_RE = re.compile(r"\b(?:done|finished|completed?|fixed|all set|works? now|working now|passing|passes"
                     r"|tests? pass(?:ed)?|green|succeeded|successfully)\b", re.I)
PROBLEM_RE = re.compile(r"\b(?:fail\w*|error\w*|couldn['’]?t|could not|unable|didn['’]?t|did not|not (?:run|pass\w*)"
                        r"|blocked|stuck|skipp\w*|red)\b", re.I)
DIAGNOSIS_LEN = 80      # a say this long between a failure and a retry may be a diagnosis
STOP_ASK_LEN = 80       # longer than this, "stop" or "wait" is usually part of a larger instruction


def classify_ask(text: str) -> str:
    """Which kind of ask, from its opening words. English only; anything else is "other"."""
    head = " ".join(text.split())[:300]
    if len(head) <= STOP_ASK_LEN and STOP_RE.search(head):
        return STOP
    if CORRECTION_RE.search(head):
        return CORRECTION
    if RUN_RE.search(head):
        return RUN
    if CHANGE_RE.search(head):
        return CHANGE
    if QUESTION_RE.search(head) or text.rstrip().endswith("?"):
        return QUESTION
    return UNCLASSIFIED


def pair(events: list[Ev], stall_seconds: float) -> list[Exchange]:
    """Split the stream into exchanges and classify them. No text survives this function."""
    exchanges: list[Exchange] = []
    current: Exchange | None = None
    last_kind = ""
    prev_ts: float | None = None
    outstanding = 0
    longest_say = 0
    final_text = ""

    def close(next_ask: bool) -> None:
        if current is None:
            return
        if final_text:
            current.final_say_len = len(final_text)
            current.claims_done = bool(DONE_RE.search(final_text))
            current.admits_problem = bool(PROBLEM_RE.search(final_text))
            current.asks_back = final_text.rstrip().endswith("?")
        if current.ended != INTERRUPTED:
            if last_kind == SAY:
                current.ended = REPLY
            elif next_ask and (current.actions or current.had_say):
                current.ended = SILENT
            elif last_kind == ACT or not next_ask:
                current.ended = OPEN

    for ev in events:
        if ev.kind == "ignored":
            continue
        if ev.kind == ASK:
            close(next_ask=True)
            current = Exchange(classify_ask(ev.text), ev.ts, ev.ts)
            exchanges.append(current)
            last_kind, prev_ts, outstanding, longest_say, final_text = ASK, ev.ts, 0, 0, ""
            continue
        if current is None:
            continue
        start = ev.act.start if ev.act else ev.ts
        end = (ev.act.end or ev.act.start) if ev.act else ev.ts
        if prev_ts is not None and start is not None and start - prev_ts > stall_seconds:
            current.stalls += 1
        if ev.act and end is not None and start is not None and end - start > stall_seconds:
            current.stalls += 1
        if ev.kind == SAY:
            current.had_say = True
            final_text = ev.text
            longest_say = max(longest_say, len(ev.text))
            last_kind = SAY
        elif ev.kind == ACT:
            act = ev.act
            current.actions.append(act)
            current.says_before.append(longest_say)
            longest_say = 0
            final_text = ""
            if act.background:
                outstanding += 1
            if act.poll and act.bg_done and outstanding:
                outstanding -= 1
            last_kind = ACT
        elif ev.kind == BG_DONE:
            outstanding = max(0, outstanding - 1)
        elif ev.kind == BREAK:
            current.ended = INTERRUPTED
            if ev.ts is not None and prev_ts is not None:
                current.break_gap = ev.ts - prev_ts
        elif ev.kind == TURN_END:
            if outstanding:
                current.bg_left_running = True
            prev_ts = None
            if ev.ts is not None:
                current.end = ev.ts
            continue
        current.end = end if end is not None else current.end
        prev_ts = end if end is not None else prev_ts
    close(next_ask=False)
    if current is not None and outstanding:
        current.bg_left_running = True
    return exchanges


@dataclass
class Session:
    """What the report may know about one selected session."""
    label: int
    reading: str
    reason: str = ""
    date: dt.date | None = None
    first: float | None = None
    seconds: int = 0
    malformed: int = 0
    exchanges: list[Exchange] = field(default_factory=list)


def _span(events: list[Ev]) -> tuple[float | None, float | None]:
    stamps = [t for ev in events for t in ((ev.act.start, ev.act.end) if ev.act else (ev.ts,)) if t is not None]
    return (min(stamps), max(stamps)) if stamps else (None, None)


def read_session(candidate: Candidate, label: int, stall_seconds: float) -> tuple[Session, str]:
    """A session, and its title for the screen. Nothing here may raise, or print what it read."""
    try:
        parsed = candidate.store.parse(candidate.paths)
    except OSError:
        return Session(label, READ_NONE, "cannot open the file"), ""
    except Exception:       # a parser error's message can quote the file, so it is not kept
        return Session(label, READ_NONE, "not a format this reader knows"), ""
    if parsed.recognised == 0 or parsed.unrecognised > parsed.recognised:
        return Session(label, READ_NONE, "not a format this reader knows"), ""
    try:
        first, last = _span(parsed.events)
        title = next((ev.text for ev in parsed.events if ev.kind == ASK), "")
        title = parsed.title or title
        exchanges = pair(parsed.events, stall_seconds)
    except Exception:
        return Session(label, READ_NONE, "not a format this reader knows"), ""
    if not exchanges:
        reading = READ_PARTLY if parsed.malformed else READ_EMPTY
    elif parsed.malformed or parsed.unrecognised:
        reading = READ_PARTLY
    else:
        reading = READ_OK if candidate.store.verified else READ_UNVERIFIED
    date = dt.datetime.fromtimestamp(first).astimezone().date() if first is not None else None
    seconds = int(last - first) if first is not None and last is not None else 0
    return Session(label, reading, "", date, first, seconds, parsed.malformed, exchanges), title


# ------------------------------------------------------------------------------- patterns

def _acts(s: Session):
    for ex in s.exchanges:
        for i, act in enumerate(ex.actions):
            yield ex, i, act


def d_parser(s: Session) -> int:
    return sum(a.outcome == PARSER for _, _, a in _acts(s))


def d_retry(s: Session) -> int:
    count = 0
    for ex in s.exchanges:
        for i in range(1, len(ex.actions)):
            prev, act = ex.actions[i - 1], ex.actions[i]
            if prev.outcome in (FAILED, PARSER) and not act.poll and prev.tool == act.tool \
                    and (prev.call == act.call or (prev.head and prev.head == act.head)) \
                    and ex.says_before[i] < DIAGNOSIS_LEN:
                count += 1
    return count


def _edit_counts(act: Action) -> bool:
    return act.category == EDIT and not act.doc_only and act.outcome not in (FAILED, PARSER)


def d_unverified(s: Session) -> int:
    count = 0
    for ex in s.exchanges:
        last_edit = max((i for i, a in enumerate(ex.actions) if _edit_counts(a)), default=None)
        if last_edit is not None and ex.ended != INTERRUPTED \
                and not any(a.verifies for a in ex.actions[last_edit + 1:]):
            count += 1
    return count


def d_background(s: Session) -> int:
    return sum(ex.bg_left_running for ex in s.exchanges)


def d_silent(s: Session) -> int:
    return sum(ex.ended == SILENT for ex in s.exchanges)


def d_stall(s: Session) -> int:
    return sum(ex.stalls for ex in s.exchanges)


def d_false_done(s: Session) -> int:
    count = 0
    for ex in s.exchanges:
        shells = [a for a in ex.actions if a.category == SHELL and not a.poll]
        if shells and shells[-1].outcome in (FAILED, PARSER) and ex.claims_done and not ex.admits_problem:
            count += 1
    return count


def _edited(ex: Exchange) -> bool:
    return any(a.category == EDIT for a in ex.actions)


def _ran(ex: Exchange) -> bool:
    return any(a.category == SHELL for a in ex.actions)


def d_question_edit(s: Session) -> int:
    return sum(ex.ask == QUESTION and _edited(ex) for ex in s.exchanges)


def d_change_talk(s: Session) -> int:
    return sum(ex.ask == CHANGE and ex.had_say and not ex.asks_back and not _edited(ex) and not _ran(ex)
               and ex.ended != INTERRUPTED for ex in s.exchanges)


def d_run_not_run(s: Session) -> int:
    return sum(ex.ask == RUN and ex.had_say and not ex.asks_back and not _ran(ex)
               and ex.ended != INTERRUPTED for ex in s.exchanges)


def d_stop_ignored(s: Session) -> int:
    return sum(ex.ask == STOP and (_edited(ex) or any(a.category == SHELL and not a.poll for a in ex.actions))
               for ex in s.exchanges)


def corrections(s: Session) -> list[tuple[str, float | None]]:
    """``(the kind of action before it, seconds since the agent's last move)``, one per occurrence."""
    found: list[tuple[str, float | None]] = []
    for i, ex in enumerate(s.exchanges):
        prior = ex.actions[-1].category if ex.actions else TALK
        if ex.ended == INTERRUPTED:
            found.append((prior, ex.break_gap))
        if ex.ask == CORRECTION and i and s.exchanges[i - 1].ended != INTERRUPTED:
            before = s.exchanges[i - 1]
            gap = ex.start - before.end if ex.start is not None and before.end is not None else None
            found.append((before.actions[-1].category if before.actions else TALK, gap))
    return found


def d_correction(s: Session) -> int:
    return len(corrections(s))


def d_flip(s: Session) -> int:
    count = 0
    seq: dict[int, list[tuple[int, int]]] = {}
    for _, _, a in _acts(s):
        if a.category == EDIT and a.file and a.after:
            pairs = seq.setdefault(a.file, [])
            before = a.before or (pairs[-1][1] if pairs else 0)
            pairs.append((before, a.after))
    for pairs in seq.values():
        i = 0
        while i + 2 < len(pairs):
            if pairs[i][0] == pairs[i + 1][1] and pairs[i][1] == pairs[i + 1][0] and pairs[i + 2] == pairs[i]:
                count += 1
                i += 3
            else:
                i += 1
    return count


@dataclass(frozen=True)
class Pattern:
    key: str
    name: str
    kind: str       # Mnemosyne's vocabulary: "mistake" or "process"
    detect: object
    what: tuple[str, ...]
    read: tuple[str, ...]


# Fixed wording. Every line here is also an allowed report line, so keep them ASCII and under 100
# characters. This is the only place a pattern's text may come from.
PATTERNS = (
    Pattern("parser", "Command failed at the parser", "mistake", d_parser,
            ("What it is: a shell refused the command line, so it never ran.",),
            ("How to read it: heuristic, matched on the shell's own wording. Usually a quoting problem.",
             "It can't see a shell that words this differently, so it undercounts.")),
    Pattern("retry", "Retried straight after its own error", "mistake", d_retry,
            ("What it is: the same tool and command start ran again right after failing, with no",
             "reading or explanation between them."),
            ("How to read it: heuristic. A flaky step can justify a retry, and any long message between",
             "the two calls counts as a diagnosis even if it wasn't one, so it undercounts.")),
    Pattern("unverified", "Files edited, nothing run after", "process", d_unverified,
            ("What it is: code files changed and no command that could test them ran before the",
             "next ask."),
            ("How to read it: heuristic. Documentation edits are left out. It can't tell whether a",
             "command really tested the change, or whether this change could be tested at all.")),
    Pattern("background", "Turn ended with a background command running", "process", d_background,
            ("What it is: the agent stopped while a command it started in the background had not",
             "reported finishing."),
            ("How to read it: heuristic. The agent may have said so and meant to come back. Some",
             "formats don't record background commands, so it undercounts.")),
    Pattern("silent", "Turn ended with no reply", "process", d_silent,
            ("What it is: the last thing before the next ask was a tool call, with no message.",),
            ("How to read it: heuristic. The final exchange of a session isn't counted, because a file",
             "that just ends can't show why. It can't judge whether a message gave a real reason.")),
    Pattern("stall", "Long stall", "process", d_stall,
            ("What it is: a gap with nothing recorded while the agent owed the next move, longer than",
             "the stall limit."),
            ("How to read it: heuristic. It can't separate a hang from a slow command, a waiting",
             "approval prompt or a sleeping machine. Time after a finished turn isn't counted.")),
    Pattern("false_done", "Claimed done after a failed command", "mistake", d_false_done,
            ("What it is: the final message read as finished, and the last command had failed.",),
            ("How to read it: heuristic, from wording. That command may not have mattered, and a",
             "message that also mentions a problem isn't counted, so it undercounts.")),
    Pattern("question_edit", "Question answered with edits", "mistake", d_question_edit,
            ("What it is: the ask read as a question, and files changed before the next ask.",),
            ("How to read it: heuristic, from the ask's opening words. A polite request can read as a",
             "question. English only: other languages are left unclassified and don't count.")),
    Pattern("change_talk", "Change request answered with only talk", "mistake", d_change_talk,
            ("What it is: the ask read as a change, and nothing was edited or run.",),
            ("How to read it: heuristic. A reply ending in a question isn't counted, since it may be a",
             "fair clarification. A plan that was asked for looks the same.")),
    Pattern("run_not_run", "Run request with no command run", "mistake", d_run_not_run,
            ("What it is: the ask read as a run or a check, and no command ran.",),
            ("How to read it: heuristic. Reading the code may have answered a request to check it.",)),
    Pattern("stop_ignored", "Asked to stop or wait, kept acting", "mistake", d_stop_ignored,
            ("What it is: the ask read as stop or wait, and the agent then edited or ran something.",),
            ("How to read it: heuristic. Tidying up after a stop can be right, and it can't tell.",)),
    Pattern("correction", "User corrected or interrupted the agent", "mistake", d_correction,
            ("What it is: the user interrupted, or the next ask opened as a correction.",),
            ("How to read it: heuristic, from the ask's opening words. It says when, not why. A user",
             "can interrupt to add something, and a polite correction won't be seen.")),
    Pattern("flip", "Flip-flopped between two edits", "process", d_flip,
            ("What it is: the same edit was made, reversed and made again in one file.",),
            ("How to read it: heuristic. Only exact reversals count, so it undercounts. It can't see",
             "a choice that went back and forth in words or across different files.")),
    Pattern("recurring", "Same failure in more than one session", "mistake", None,
            ("What it is: a failed command with the same start and first error line in two or more",
             "sessions. The count is how many different failures did this."),
            ("How to read it: heuristic. Numbers are ignored in the comparison, but any other",
             "difference hides the match, so it undercounts.")),
)
PATTERN_BY_KEY = {p.key: p for p in PATTERNS}


def analyse(sessions: list[Session]) -> tuple[dict[str, dict[int, int]], Counter, Counter]:
    """``{pattern: {session label: count}}``, plus the correction breakdowns."""
    results: dict[str, dict[int, int]] = {p.key: {} for p in PATTERNS}
    prior: Counter = Counter()
    soon: Counter = Counter()
    signatures: dict[int, set[int]] = {}
    for s in sessions:
        for p in PATTERNS:
            count = p.detect(s) if p.detect else 0
            if count:
                results[p.key][s.label] = count
        for kind, gap in corrections(s):
            prior[kind] += 1
            bucket = "unknown" if gap is None else "under1" if gap < 60 else "under10" if gap < 600 else "over10"
            soon[bucket] += 1
        for _, _, a in _acts(s):
            if a.signature:
                signatures.setdefault(a.signature, set()).add(s.label)
    recurring = [labels for labels in signatures.values() if len(labels) > 1]
    for labels in recurring:
        for label in labels:
            results["recurring"][label] = results["recurring"].get(label, 0) + 1
    results["recurring_total"] = {0: len(recurring)} if recurring else {}
    return results, prior, soon


# ------------------------------------------------------------------------------- the report

WIDTH = 100
TEMPLATES = {
    "title": "# Agent session review",
    "intro1": "Fixed wording, counts, dates and session labels only. Nothing here came from a transcript.",
    "intro2": "Every pattern below is a heuristic, and a count of zero is not proof of anything.",
    "tally": "Sessions selected: {n}. Read: {n}. Partly read: {n}. Could not read: {n}. No exchanges: {n}.",
    "totals": "Exchanges: {n}. Time in the selected sessions: {dur}.",
    "dates_off": "Dates left out on request.",
    "dates": "Dates: {date} to {date}.",
    "h_sessions": "## Sessions",
    "row_head_d": "| Session | Date | Duration | Exchanges | Reading |",
    "row_rule_d": "|---|---|---|---|---|",
    "row_d": "| Session {n} | {date} | {dur} | {n} | {reading} |",
    "row_nodate_d": "| Session {n} | not known | {dur} | {n} | {reading} |",
    "row_head": "| Session | Duration | Exchanges | Reading |",
    "row_rule": "|---|---|---|---|",
    "row": "| Session {n} | {dur} | {n} | {reading} |",
    "unread": "Could not read, so its failures are unknown, not zero: {sessions}",
    "partly": "Only partly read, so its counts are too low: {sessions}",
    "empty": "No exchanges found, so nothing was checked: {sessions}",
    "unverified": "Read with a format that was not checked on a real session: {sessions}",
    "h_pairing": "## What was asked and what happened",
    "pair_head": "| Asked for | Exchanges | Talk only | Read only | Edited | Ran commands | Verified |",
    "pair_rule": "|---|---|---|---|---|---|---|",
    "pair_row": "| {ask} | {n} | {n} | {n} | {n} | {n} | {n} |",
    "ends": "How turns ended: with a reply {n}, interrupted {n}, no reply {n}, session ended mid-turn {n}.",
    "acts": "Actions: shell {n}, file read {n}, file edit {n}, search {n}, web {n}, other {n}.",
    "h_patterns": "## Failure patterns",
    "none": "No pattern fired in what could be read. These detectors undercount, so that isn't health.",
    "none_read": "Nothing could be read, so nothing can be said about these sessions.",
    "p_head": "### {name} ({kind})",
    "seen": "Count: {n}. Sessions: {sessions}",
    "stall_limit": "Stall limit used: {n} minutes.",
    "after": "After: shell {n}, file read {n}, file edit {n}, search {n}, web {n}, other {n}, talk only {n}.",
    "soon": "How soon: under 1 minute {n}, 1 to 10 minutes {n}, over 10 minutes {n}, not known {n}.",
    "compact": "{name}: count {n}. Sessions: {sessions}",
    "shortened": "Shortened to fit: {n} patterns lost their definitions. Raise the line limit to see them.",
    "not_seen": "Not seen: {names}",
}
_PH = {
    "n": r"\d{1,9}",
    "dur": r"(?:\d+d )?(?:\d+h )?\d+m",
    "date": r"\d{4}-\d{2}-\d{2}",
    "sessions": r"Session \d+(?:, Session \d+)*[,.]",
    "reading": "|".join(re.escape(r) for r in (READ_OK, READ_UNVERIFIED, READ_PARTLY, READ_NONE, READ_EMPTY)),
    "ask": "|".join(re.escape(a) for a in ASK_KINDS),
    "name": "|".join(re.escape(p.name) for p in PATTERNS),
    "kind": "mistake|process",
}
_NAMES = rf"(?:{_PH['name']})(?:; (?:{_PH['name']}))*[;.]"


def _template_regex(template: str, with_dates: bool) -> str | None:
    if "{date}" in template and not with_dates:
        return None
    out, pos = [], 0
    for m in re.finditer(r"\{(\w+)\}", template):
        out.append(re.escape(template[pos:m.start()]))
        out.append(_NAMES if m.group(1) == "names" else f"(?:{_PH[m.group(1)]})")
        pos = m.end()
    return "".join(out) + re.escape(template[pos:])


def allowed_lines(with_dates: bool) -> re.Pattern:
    """The whole vocabulary: fixed lines with typed holes, and nothing else."""
    parts = [r for t in TEMPLATES.values() if (r := _template_regex(t, with_dates))]
    for p in PATTERNS:
        parts += [re.escape(line) for line in (*p.what, *p.read)]
    parts += [_PH["sessions"], _NAMES, ""]
    return re.compile("|".join(f"(?:{p})" for p in parts))


class Refused(Exception):
    """A deliberate refusal, with a fixed message holding nothing from a session."""


class GuaranteeError(Exception):
    """The report failed its own check. The message is fixed, because the text may not be repeated."""


def check_report(text: str, with_dates: bool) -> None:
    """Refuse a report holding anything outside the vocabulary. Names no offending text."""
    allowed = allowed_lines(with_dates)
    if not text.isascii():
        raise GuaranteeError
    for line in text.split("\n"):
        if not allowed.fullmatch(line):
            raise GuaranteeError


def _duration(seconds: int) -> str:
    days, rest = divmod(max(0, seconds) // 60, 1440)
    hours, minutes = divmod(rest, 60)
    return (f"{days}d " if days else "") + (f"{hours}h " if days or hours else "") + f"{minutes}m"


def _fill(key: str, **values) -> str:
    """Fill a template's holes in order; ``n`` and ``date`` may repeat, so they take lists."""
    template = TEMPLATES[key]
    queues = {k: list(v) if isinstance(v, (list, tuple)) else [v] for k, v in values.items()}
    return re.sub(r"\{(\w+)\}", lambda m: str(queues[m.group(1)].pop(0)), template)


def _wrap(prefix_key: str, words: list[str], sep: str, end: str, **values) -> list[str]:
    """A template ending in a list, wrapped at the width, with the list's own separator."""
    hole = "sessions" if "{sessions}" in TEMPLATES[prefix_key] else "names"
    lines, current = [], _fill(prefix_key, **values, **{hole: ""})
    for i, word in enumerate(words):
        piece = word + (end if i == len(words) - 1 else sep.rstrip())
        if len(current) + len(piece) + 1 > WIDTH:
            lines.append(current.rstrip())
            current = ""
        current += piece + (" " if i < len(words) - 1 else "")
    lines.append(current.rstrip())
    return lines


def _session_list(key: str, labels: list[int], **values) -> list[str]:
    return _wrap(key, [f"Session {n}" for n in sorted(labels)], ", ", ".", **values)


def _pattern_block(p: Pattern, counts: dict[int, int], total: int, stall: int,
                   prior: Counter, soon: Counter) -> list[str]:
    lines = ["", _fill("p_head", name=p.name, kind=p.kind)]
    lines += _session_list("seen", list(counts), n=total)
    lines += [*p.what, *p.read]
    if p.key == "stall":
        lines.append(_fill("stall_limit", n=stall))
    if p.key == "correction":
        lines.append(_fill("after", n=[prior[c] for c in (*CATEGORIES, TALK)]))
        lines.append(_fill("soon", n=[soon[b] for b in ("under1", "under10", "over10", "unknown")]))
    return lines


def _pattern_total(key: str, results: dict) -> int:
    if key == "recurring":
        return results["recurring_total"].get(0, 0)
    return sum(results[key].values())


def _head_lines(sessions: list[Session], with_dates: bool, max_rows: int) -> list[str]:
    tally = Counter(s.reading for s in sessions)
    read = tally[READ_OK] + tally[READ_UNVERIFIED]
    seconds = sum(s.seconds for s in sessions)
    lines = [TEMPLATES["title"], "", TEMPLATES["intro1"], TEMPLATES["intro2"], "",
             _fill("tally", n=[len(sessions), read, tally[READ_PARTLY], tally[READ_NONE], tally[READ_EMPTY]]),
             _fill("totals", n=sum(len(s.exchanges) for s in sessions), dur=_duration(seconds))]
    dated = [s.date for s in sessions if s.date]
    if not with_dates:
        lines.append(TEMPLATES["dates_off"])
    elif dated and len(sessions) > max_rows:
        lines.append(_fill("dates", date=[min(dated).isoformat(), max(dated).isoformat()]))
    if len(sessions) <= max_rows:
        lines += ["", TEMPLATES["h_sessions"], ""]
        lines += [TEMPLATES["row_head_d" if with_dates else "row_head"], TEMPLATES["row_rule_d" if with_dates else "row_rule"]]
        for s in sessions:
            nums = [s.label, len(s.exchanges)]
            dur = _duration(s.seconds)
            if with_dates and s.date:
                lines.append(_fill("row_d", n=nums, date=s.date.isoformat(), dur=dur, reading=s.reading))
            elif with_dates:
                lines.append(_fill("row_nodate_d", n=nums, dur=dur, reading=s.reading))
            else:
                lines.append(_fill("row", n=nums, dur=dur, reading=s.reading))
    notes = (("unread", READ_NONE), ("partly", READ_PARTLY), ("empty", READ_EMPTY), ("unverified", READ_UNVERIFIED))
    flagged = [(key, [s.label for s in sessions if s.reading == reading]) for key, reading in notes]
    flagged = [(key, labels) for key, labels in flagged if labels]
    if flagged:
        lines.append("")
        for key, labels in flagged:
            lines += _session_list(key, labels)
    return lines


def _pairing_lines(sessions: list[Session]) -> list[str]:
    exchanges = [ex for s in sessions for ex in s.exchanges]
    lines = ["", TEMPLATES["h_pairing"], "", TEMPLATES["pair_head"], TEMPLATES["pair_rule"]]
    for kind in ASK_KINDS:
        group = [ex for ex in exchanges if ex.ask == kind]
        if group:
            reads = sum(bool(ex.actions) and all(a.category in (READ, SEARCH) for a in ex.actions) for ex in group)
            lines.append(_fill("pair_row", ask=kind, n=[
                len(group), sum(not ex.actions for ex in group), reads, sum(_edited(ex) for ex in group),
                sum(_ran(ex) for ex in group), sum(any(a.verifies for a in ex.actions) for ex in group)]))
    ended = Counter(ex.ended for ex in exchanges)
    categories = Counter(a.category for s in sessions for _, _, a in _acts(s))
    lines += ["", _fill("ends", n=[ended[REPLY], ended[INTERRUPTED], ended[SILENT], ended[OPEN]]),
              _fill("acts", n=[categories[c] for c in CATEGORIES])]
    return lines


def render(sessions: list[Session], stall_minutes: int, with_dates: bool, max_lines: int, max_rows: int) -> str:
    """The report, from fixed lines, integers, dates and session labels. Takes no transcript text."""
    results, prior, soon = analyse(sessions)
    fired = sorted((p for p in PATTERNS if results[p.key]),
                   key=lambda p: -_pattern_total(p.key, results))
    head = _head_lines(sessions, with_dates, max_rows)
    if any(s.exchanges for s in sessions):
        head += _pairing_lines(sessions)
    head += ["", TEMPLATES["h_patterns"]]
    if not fired:
        readable = any(s.reading in (READ_OK, READ_UNVERIFIED, READ_PARTLY) for s in sessions)
        head += ["", TEMPLATES["none" if readable else "none_read"]]
    blocks = [_pattern_block(p, results[p.key], _pattern_total(p.key, results), stall_minutes, prior, soon) for p in fired]
    missing = [p.name for p in PATTERNS if not results[p.key]]
    tail = ["", *_wrap("not_seen", missing, "; ", ".")] if missing and fired else []
    compacted = 0
    compact: list[list[str]] = [[] for _ in fired]
    for i in range(len(fired) - 1, -1, -1):
        used = len(head) + sum(len(b) for b in blocks) + sum(len(c) for c in compact) + len(tail) + (2 if compacted else 0)
        if used <= max_lines:
            break
        p = fired[i]
        blocks[i] = []
        compact[i] = _session_list("compact", list(results[p.key]), name=p.name, n=_pattern_total(p.key, results))
        compacted += 1
    body = list(head)
    for block in blocks:
        body += block
    short_lines = [line for short in compact for line in short]
    if short_lines:
        body += ["", *short_lines, _fill("shortened", n=compacted)]
    return "\n".join(body + tail) + "\n"


# ------------------------------------------------------------------------------- output

def inside_git_tree(path: Path) -> bool:
    return any((folder / ".git").exists() for folder in path.parents)


def default_output() -> Path:
    folder = Path.home() / "session-review-reports"
    target = folder / "session-review.md"
    n = 1
    while target.exists():
        n += 1
        target = folder / f"session-review-{n}.md"
    return target


def write_report(path: Path, text: str, overwrite: bool, default: bool) -> None:
    if default:
        path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w" if overwrite else "x", encoding="ascii", newline="\n") as fh:
        fh.write(text)


# ------------------------------------------------------------------------------- cli

def limits(args: argparse.Namespace) -> dict[str, int]:
    config, _ = load_config(find_repo_root(), args.config)
    out = {}
    for key, default in DEFAULTS.items():
        flag = getattr(args, key, None)
        value = flag if flag is not None else cfg(config, f"sessionReview.{key}", default)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise UsageError(f"{key} must be a positive whole number")
        out[key] = value
    return out


def parse_roots(pairs: list[str] | None) -> dict[str, Path]:
    names = {s.name for s in STORES}
    roots = {}
    for pair_ in pairs or []:
        name, sep, value = pair_.partition("=")
        if not sep or name not in names:
            raise UsageError(f"--root takes STORE=PATH, with STORE one of: {', '.join(sorted(names))}")
        roots[name] = Path(value)
    return roots


def listing_key(found: list[Candidate]) -> str:
    return hashlib.sha256(",".join(c.handle for c in found).encode()).hexdigest()[:8]


def _screen_title(text: str) -> str:
    """One printable line. A title is untrusted text, and may hold terminal escapes."""
    clean = "".join(ch for ch in " ".join(text.split()) if ch.isprintable())
    return clean[:60] + ("..." if len(clean) > 60 else "")


def cmd_list(args: argparse.Namespace) -> int:
    lim = limits(args)
    found = discover(args.store, parse_roots(args.root))
    if not found:
        print("No local sessions found. A cloud-agent session has no local store to read.")
        return 0
    print("On screen only: titles below can name your work, and they never reach the report.")
    print(f"Listing key: {listing_key(found)} (needed only when selecting by number)")
    print(f"{'#':>3}  {'Date':10}  {'Start':5}  {'Duration':8}  {'Exch.':>5}  {'Store':11}  {'Handle':8}  Title")
    for number, candidate in enumerate(found[:lim["listLimit"]], 1):
        session, title = read_session(candidate, number, lim["stallMinutes"] * 60)
        try:
            stamp = dt.datetime.fromtimestamp(candidate.mtime())
            date, start = stamp.date().isoformat(), "-"
        except OSError:
            date, start = "?", "-"
        if session.reading == READ_NONE:
            print(f"{number:>3}  {date:10}  {start:5}  {'-':8}  {'-':>5}  {candidate.store.name:11}  "
                  f"{candidate.handle:8}  (could not read)")
            continue
        if session.first is not None:
            stamp = dt.datetime.fromtimestamp(session.first)
            date, start = stamp.date().isoformat(), stamp.strftime("%H:%M")
        print(f"{number:>3}  {date:10}  {start:5}  {_duration(session.seconds):8}  {len(session.exchanges):>5}  "
              f"{candidate.store.name:11}  {candidate.handle:8}  {_screen_title(title)}")
    if len(found) > lim["listLimit"]:
        print(f"{len(found) - lim['listLimit']} older session(s) not shown; raise --limit to see them.")
    return 0


def select(found: list[Candidate], spec: str, key: str | None) -> list[tuple[int, Candidate]]:
    """Resolve ``--select`` to ``(list number, session)``. Any bad token refuses the whole scan."""
    numbered = list(enumerate(found, 1))
    if not found:
        raise UsageError("no local sessions found, so there is nothing to select")
    if spec.strip().lower() == "all":
        return numbered
    by_handle = {c.handle: (n, c) for n, c in numbered}
    picked: dict[int, Candidate] = {}
    uses_numbers = False
    for token in filter(None, (t.strip() for t in spec.split(","))):
        if re.fullmatch(r"\d+(-\d+)?", token) and token not in by_handle:
            uses_numbers = True
            low, _, high = token.partition("-")
            for n in range(int(low), int(high or low) + 1):
                if not 1 <= n <= len(found):
                    raise UsageError(f"no session numbered {n} in the list")
                picked[n] = found[n - 1]
        elif token in by_handle:
            n, candidate = by_handle[token]
            picked[n] = candidate
        else:
            raise UsageError("--select takes list numbers, ranges like 2-5, handles, or the word all")
    if uses_numbers and key is None:
        raise UsageError("selecting by number needs --listing, with the key the list printed")
    if uses_numbers and key != listing_key(found):
        raise Refused("The sessions changed since that list, so its numbers may not match. "
                      "List them again, or select by handle.")
    if not picked:
        raise UsageError("--select named no session")
    return sorted(picked.items())


def cmd_scan(args: argparse.Namespace) -> int:
    lim = limits(args)
    found = discover(args.store, parse_roots(args.root))
    picked = select(found, args.select, args.listing)
    if len(picked) > lim["maxSessions"]:
        raise Refused(f"{len(picked)} sessions selected, over the limit of {lim['maxSessions']}. "
                      "Raise --max-sessions to scan them all.")
    default = args.output is None
    path = default_output() if default else Path(args.output)
    resolved = path.resolve()
    if inside_git_tree(resolved) and not args.allow_inside_git:
        raise Refused("That report path is inside a git working tree, where it could be committed by "
                      "accident. Pass --output with a path outside one, or --allow-inside-git.")
    if resolved.exists() and not args.overwrite:
        raise Refused("A file is already at that path. Choose another, or pass --overwrite.")
    if not default and not resolved.parent.is_dir():
        raise Refused("The folder for that report path does not exist.")

    stall_seconds = lim["stallMinutes"] * 60
    sessions = []
    mapping = []
    for label, (number, candidate) in enumerate(picked, 1):
        session, _ = read_session(candidate, label, stall_seconds)
        sessions.append(session)
        mapping.append(f"Session {label} = #{number} ({candidate.handle})"
                       + (f": could not read, {session.reason}" if session.reading == READ_NONE else ""))
    text = render(sessions, lim["stallMinutes"], not args.no_date, lim["maxReportLines"], lim["maxTableRows"])
    check_report(text, not args.no_date)
    used = text.count("\n")
    if used > lim["maxReportLines"]:
        raise Refused(f"The report needs {used} lines, over the limit of {lim['maxReportLines']}. "
                      "Raise --max-lines, or select fewer sessions.")
    write_report(resolved, text, args.overwrite, default)
    print("\n".join(mapping))
    print(f"Report written: {resolved}")
    print("Hand over that file as written. Don't summarise it, add to it, or rewrite it.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="session-review", description="List local agent sessions, "
                                     "then scan selected ones into a generic failure-pattern report.")
    sub = parser.add_subparsers(dest="command", required=True)
    store_names = [s.name for s in STORES]
    for name in ("list", "scan"):
        p = sub.add_parser(name)
        p.add_argument("--store", action="append", choices=store_names, help="only this store (repeatable)")
        p.add_argument("--root", action="append", metavar="STORE=PATH", help="read this store from PATH")
        p.add_argument("--config", help="the Zethus config (default: the usual resolution order)")
        p.add_argument("--stall-minutes", dest="stallMinutes", type=int)
    sub.choices["list"].add_argument("--limit", dest="listLimit", type=int, help="how many to show")
    scan = sub.choices["scan"]
    scan.add_argument("--select", required=True, help="numbers, ranges, handles, or the word all")
    scan.add_argument("--listing", help="the key the list printed; required when selecting by number")
    scan.add_argument("--no-date", action="store_true", help="leave every date out of the report")
    scan.add_argument("--output", help="report path (default: a new file in ~/session-review-reports)")
    scan.add_argument("--overwrite", action="store_true", help="replace an existing file at --output")
    scan.add_argument("--allow-inside-git", action="store_true", help="allow a path inside a git working tree")
    scan.add_argument("--max-sessions", dest="maxSessions", type=int)
    scan.add_argument("--max-lines", dest="maxReportLines", type=int)
    scan.add_argument("--max-table-rows", dest="maxTableRows", type=int)
    args = parser.parse_args(argv)
    try:
        return cmd_list(args) if args.command == "list" else cmd_scan(args)
    except UsageError as exc:
        print(f"session-review: {exc}", file=sys.stderr)
        return 2
    except Refused as exc:
        print(f"session-review: {exc}", file=sys.stderr)
        return 1
    except GuaranteeError:
        print("session-review: refused. The report failed its vocabulary check, so nothing was "
              "written. This is a bug in the script; the report is withheld, not repaired.", file=sys.stderr)
        return 1
    except Exception:       # a message or a traceback here could quote a session
        print("session-review: stopped on an internal error. Nothing was written, and the details "
              "are withheld because they could quote a session.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

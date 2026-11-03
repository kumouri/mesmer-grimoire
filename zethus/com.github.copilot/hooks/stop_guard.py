#!/usr/bin/env python3
"""Zethus plugin ``agentStop`` / ``userPromptSubmitted`` hook: refuse an end of turn that isn't a stop.

The agent file says a turn ends only at a listed stop (an approval wall, or a question it can't
answer with a citation), and that such a turn closes with a ``Stopped at / Next / Why`` block. A
finished phase, a commit or a green gate is progress, never a reason to end a turn, yet a model
read it as one anyway. Prose alone didn't hold, so this hook checks the one thing it can see.

What it reads: the session's transcript (``transcriptPath`` on stdin) or a last-message field if
the host sends one. It is a *Zethus turn* when the last assistant message opens with the agent's
header line (``Stage N · …`` or ``Answering your question``). It is a *real stop* when that message
ends with a ``Stopped at:`` line and a ``Why:`` line whose reason names a wall: sign-off, a
decision, an answer, a stale base, a refusal, a stuck branch, a merge, or the work being done.

Modes (the one argument):

- ``stop``  (``agentStop``): a Zethus turn without a real stop is refused with
  ``{"decision": "block", "reason": …}``, which the Copilot CLI turns into a queued user message
  (checked on 1.0.88 and 1.0.106-2, see docs/lessons-capture-spec.md E2). The reason names the next
  action. After ``MAX_REFUSALS`` refusals in a session it lets the turn end, so it can never trap
  one.
- ``prompt`` (``userPromptSubmitted``): the fallback for a host whose stop event can't block. If
  the previous turn ended without a real stop, say so in ``additionalContext`` on the next prompt.

Not known: the transcript's exact shape on every host. An unreadable or unrecognised transcript
means *allow*. Fail-open: any error prints nothing and exits 0.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

MAX_REFUSALS = 2

HEADER_RE = re.compile(r"^\s*(?:\*\*)?(?:Stage \d\b|Answering your question)", re.IGNORECASE)
STOPPED_RE = re.compile(r"^\s*(?:\*\*)?Stopped at:", re.IGNORECASE | re.MULTILINE)
WHY_RE = re.compile(r"^\s*(?:\*\*)?Why:\s*(?P<why>.+)$", re.IGNORECASE | re.MULTILINE)
NEXT_RE = re.compile(r"^\s*(?:\*\*)?Next:\s*(?P<next>.+)$", re.IGNORECASE | re.MULTILINE)
# The reasons the agent file lists for ending a turn. A Why that only reports progress
# ("committed", "gates green", "phase done") names none of these.
WALLS = ("sign-off", "sign off", "signoff", "approval", "approve", "decision", "option", "answer",
         "question", "citation", "cite", "stale", "rebase", "fetch", "refus", "stuck", "merge",
         "waiting for your", "waiting on you", "change is done", "work is done", "goal is complete",
         "no further phase")


def texts(node: object) -> list[str]:
    """Every string under a ``content`` / ``text`` / ``message`` key, depth first."""
    out: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("content", "text", "message", "data") and isinstance(value, str):
                out.append(value)
            else:
                out.extend(texts(value))
    elif isinstance(node, list):
        for item in node:
            out.extend(texts(item))
    return out


def is_assistant(row: dict) -> bool:
    kind = str(row.get("role") or row.get("type") or "").lower()
    return "assistant" in kind and "tool" not in kind


def last_reply(event: dict) -> str:
    """The last assistant message, from a stdin field or the transcript; ``""`` if neither."""
    for key in ("lastAssistantMessage", "last_assistant_message"):
        if isinstance(event.get(key), str) and event[key].strip():
            return event[key]
    path = event.get("transcriptPath") or event.get("transcript_path")
    if not path or not Path(str(path)).is_file():
        return ""
    last = ""
    with open(str(path), encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and is_assistant(row):
                body = "\n".join(t for t in texts(row) if t.strip())
                if body.strip():
                    last = body
    return last


def is_zethus_turn(reply: str) -> bool:
    return any(HEADER_RE.match(line) for line in reply.splitlines()[:6])


def is_real_stop(reply: str) -> bool:
    tail = "\n".join(reply.strip().splitlines()[-12:])
    why = WHY_RE.search(tail)
    return bool(STOPPED_RE.search(tail) and why and any(w in why.group("why").lower() for w in WALLS))


def next_action(reply: str) -> str:
    found = NEXT_RE.findall(reply)
    return found[-1].strip() if found else "the next stage or phase in your plan"


def refusals_file(event: dict) -> Path:
    sid = re.sub(r"[^A-Za-z0-9_.-]", "_", str(event.get("sessionId") or event.get("session_id") or "session"))
    return Path(tempfile.gettempdir()) / f"zethus-stop-guard-{sid}.count"


def refuse(event: dict, reply: str) -> str:
    """The block decision, or ``""`` to let the turn end."""
    if not is_zethus_turn(reply) or is_real_stop(reply):
        return ""
    counter = refusals_file(event)
    try:
        seen = int(counter.read_text(encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        seen = 0
    if seen >= MAX_REFUSALS:
        return ""
    counter.write_text(str(seen + 1), encoding="utf-8")
    reason = (f"Zethus: that turn ended at a progress point, not a stop. A finished phase, a commit or "
              f"a passing gate never ends a turn. Next action: {next_action(reply)}. Do it now, in this "
              "turn, and keep going through everything you can do until the session's goal is complete "
              "or you reach (a) an approval wall the process requires, or (b) a question you can't answer "
              "with a citation. Then list every such item together, ready to act on, close with the "
              "Stopped at / Next / Why block, and carry on with any unblocked work in parallel. "
              f"(Refusal {seen + 1} of {MAX_REFUSALS}; after that the turn is let through.)")
    return json.dumps({"decision": "block", "reason": reason})


def remind(event: dict) -> str:
    """For the next prompt: ``additionalContext`` if the last turn ended without a real stop."""
    reply = last_reply(event)
    if not reply or not is_zethus_turn(reply) or is_real_stop(reply):
        return ""
    text = ("Zethus: your last turn ended at a progress point, not a listed stop. Unless this message "
            f"is a question (answer that first and say plainly that you stopped early), continue with "
            f"{next_action(reply)} before anything else, and keep going until the goal is complete or "
            "you reach an approval wall or a question you can't answer with a citation; then present "
            "all of those together.")
    return json.dumps({"additionalContext": text,
                       "hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                              "additionalContext": text}})


def main(argv: list[str]) -> int:
    try:
        mode = argv[1] if len(argv) > 1 else "stop"
        event = json.loads(sys.stdin.read() or "{}")
        event = event if isinstance(event, dict) else {}
        out = remind(event) if mode == "prompt" else refuse(event, last_reply(event))
    except Exception:
        return 0
    if out:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

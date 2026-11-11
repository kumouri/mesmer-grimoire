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
decision, an answer, a failed fetch, a rebase conflict, a refusal, a stuck branch, a merge, or the
work being done.

Modes (the one argument):

- ``stop``  (``agentStop``): a Zethus turn without a real stop is refused with
  ``{"decision": "block", "reason": …}``, which the Copilot CLI turns into a queued user message
  (checked on 1.0.88 and 1.0.106-2, see docs/lessons-capture-spec.md E2). The reason names the next
  action. After ``MAX_REFUSALS`` refusals in a session it lets the turn end, so it can never trap
  one.
- ``prompt`` (``userPromptSubmitted``): the fallback for a host whose stop event can't block. If
  the previous turn ended without a real stop, say so in ``additionalContext`` on the next prompt.
  A prompt that is the CLI's own shell-completion ``<system_notification>`` gets none: the turn it
  starts is the end of a wait, not a turn after a silent stop.

It also refuses a stop that asks leave to move a failing local gate's remediation into the current
phase (a Stage 3+ turn whose closing lines pair a gate or its tool with fix/remediation, a phase move
and a request for authorization). Every local gate is green before a phase pushes, whatever the plan
says, so there is nothing to ask: the fix is pulled forward. The planning stop (Stage 2) is exempt:
asking for that ruling there is the point. That is the one stop whose reason is allowed to be a wall
and is still refused, because the wall is not real.

A stale base is not a wall either: the agent rebases the branch itself and carries on. A stop whose
``Why:`` is about the branch being stale, behind or needing a rebase is refused with a reason that
says to do the rebase, unless that ``Why:`` names one of the two walls a stale base can still hit: a
failed fetch (no answer from ``base-freshness``) or a conflict the spec and the diff can't settle.
A sign-off or done stop that only mentions a rebase already made is left alone.

A turn that is legitimately waiting on a background command is not a turn that ended: the model is
inside a tool call (the output read), so this hook never sees it. What the hook can see is the report
after the wait bound ran out. That ends the turn at a real stop only if its ``Why:`` says the command is
still running in the background *and* the closing lines give how long was waited ("waited 30
minutes"). "Waiting on the background install" with no duration is the silent stop, and is refused
with a reason that says to block on the output read instead.

The exception is a command the *person* moved to the background. The Copilot CLI then tells the
model not to read it ("moved to background by the user … do NOT call any more tools for this
command"), so the read is shut and ending the turn is the only door left; its completion arrives as
a ``<system_notification>`` that starts the next turn by itself (probed on 1.0.110-1). Refusing that
stop left the model with neither door, and it spun in reasoning with no tool call. So while the
transcript shows a shell the person moved and no completion for it yet, any stop is let through
(:func:`person_moved_wait`), whatever the reply says: the harness asks for no reply about it.

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
STAGE_RE = re.compile(r"^\s*(?:\*\*)?Stage (\d)\b", re.IGNORECASE)
# A closing block asking leave to move a gate's remediation into the phase being pushed. All four
# kinds of word must appear, so a stop about anything else (a sign-off, a merge) is untouched.
GATE_ASK = (re.compile(r"\b(gates?|sonar\w*|lint\w*|quality)\b"),
            re.compile(r"\b(remediat\w*|fix(?:es|ing)?|findings?|issues?|violations?)\b"),
            re.compile(r"\b(phase 0|earlier phase|this phase|current phase|pull(?:ing|ed)? (?:it )?forward"
                       r"|mov(?:e|es|ed|ing))\b"),
            re.compile(r"\b(authori[sz]\w*|approv\w*|permission|may i|should i|ok to|okay to|go-ahead"
                       r"|go ahead)\b"))
# A background command that outlived the wait bound is a stop only with its duration on the page.
BACKGROUND_RE = re.compile(r"\b(in the background|background (?:command|job|shell|install|build|task)"
                           r"|shellid|read_powershell|read_bash)\b")
BACKGROUND_WHY_RE = re.compile(r"\b(?:still running|in the background|background)\b")
# The Copilot CLI's tool results for a shell the person took off the turn, and its shell ids.
PERSON_MOVED_RE = re.compile(r"moved to background by the user|after the user moved it off the main turn"
                             r"|read interrupted by user steering", re.IGNORECASE)
SHELL_ID_RE = re.compile(r"shellId:\s*([^\s>.,)]+)", re.IGNORECASE)
# The prompt the Copilot CLI submits by itself when a background shell finishes.
NOTIFICATION_RE = re.compile(r"<system_notification>[\s\S]*\bshellId\b", re.IGNORECASE)
WAITED_RE = re.compile(r"\bwaited\b[^.\n]{0,40}?\b\d+(?:\.\d+)?\s*"
                       r"(?:s|secs?|seconds?|m|mins?|minutes?|h|hrs?|hours?)\b")
# A Why about a stale base that hands the rebase back. Only a failed fetch or a conflict excuses it.
STALE_WHY_RE = re.compile(r"\b(stale (?:base|branch)|(?:base|branch) is stale|rebas\w*|commits? behind"
                          r"|behind (?:origin|the base|its base|the integration branch))\b")
STALE_WALL_RE = re.compile(r"\b(conflict\w*|hunks?|fetch\w*|no answer"
                           # a Why that only mentions a rebase already done, at another wall
                           r"|sign-?off|goal is complete|change is done|work is done|no further phase)\b")
WALLS = ("sign-off", "sign off", "signoff", "approval", "approve", "decision", "option", "answer",
         "question", "citation", "cite", "conflict", "fetch", "refus", "stuck", "merge",
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


def shell_completed(row: dict, body: str, sid: str) -> bool:
    """The row reports that shell ``sid`` finished: a completion notification or a final read."""
    data = row.get("data") if isinstance(row.get("data"), dict) else row
    kind = data.get("kind") if isinstance(data, dict) else None
    if isinstance(kind, dict) and str(kind.get("shellId")) == sid and "complete" in str(kind.get("type")):
        return True
    return bool(re.search(rf"shellId:\s*{re.escape(sid)}\)?\s+(?:has\s+)?(?:completed|exited|failed)",
                          body, re.IGNORECASE))


def person_moved_wait(event: dict) -> bool:
    """A shell the person moved to the background is still running, so the harness forbids reading it."""
    path = event.get("transcriptPath") or event.get("transcript_path")
    if not path or not Path(str(path)).is_file():
        return False
    moved: set[str] = set()
    call_shell: dict[str, str] = {}  # toolCallId -> the shellId its arguments named
    with open(str(path), encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            data = row.get("data") if isinstance(row.get("data"), dict) else row
            args = data.get("arguments")
            if isinstance(args, dict) and args.get("shellId") is not None and data.get("toolCallId"):
                call_shell[str(data["toolCallId"])] = str(args["shellId"])
            body = "\n".join(texts(row))
            for sid in list(moved):
                if shell_completed(row, body, sid):
                    moved.discard(sid)
            if PERSON_MOVED_RE.search(body):
                # A steered read's result names no shell; its call's arguments do.
                moved.update(SHELL_ID_RE.findall(body)
                             or [call_shell[c] for c in [str(data.get("toolCallId"))] if c in call_shell])
    return bool(moved)


def is_zethus_turn(reply: str) -> bool:
    return any(HEADER_RE.match(line) for line in reply.splitlines()[:6])


def closing_lines(reply: str) -> str:
    return "\n".join(reply.strip().splitlines()[-12:])


def is_real_stop(reply: str) -> bool:
    tail = closing_lines(reply)
    why = WHY_RE.search(tail)
    if not (STOPPED_RE.search(tail) and why):
        return False
    reason = why.group("why").lower()
    return any(w in reason for w in WALLS) or bool(
        BACKGROUND_WHY_RE.search(reason) and WAITED_RE.search(tail.lower()))


def waits_on_background(reply: str) -> bool:
    """The closing lines are about a command still running in the background (a stop or a bare wait)."""
    return bool(BACKGROUND_RE.search(closing_lines(reply).lower()))


def stage_of(reply: str) -> int | None:
    for line in reply.splitlines()[:6]:
        m = STAGE_RE.match(line)
        if m:
            return int(m.group(1))
    return None


def asks_to_defer_gate_fix(reply: str) -> bool:
    """A Stage 3+ turn whose closing lines ask leave to move a failing gate's fix into this phase."""
    stage = stage_of(reply)
    if stage is None or stage < 3:
        return False
    tail = " ".join(reply.strip().splitlines()[-25:]).lower()
    return all(rx.search(tail) for rx in GATE_ASK)


def hands_back_rebase(reply: str) -> bool:
    """The closing ``Why:`` stops for a stale base that the agent should have rebased itself."""
    why = WHY_RE.search(closing_lines(reply))
    if not why:
        return False
    reason = why.group("why").lower()
    return bool(STALE_WHY_RE.search(reason)) and not STALE_WALL_RE.search(reason)


def next_action(reply: str) -> str:
    found = NEXT_RE.findall(reply)
    return found[-1].strip() if found else "the next stage or phase in your plan"


def refusals_file(event: dict) -> Path:
    sid = re.sub(r"[^A-Za-z0-9_.-]", "_", str(event.get("sessionId") or event.get("session_id") or "session"))
    return Path(tempfile.gettempdir()) / f"zethus-stop-guard-{sid}.count"


def refuse(event: dict, reply: str) -> str:
    """The block decision, or ``""`` to let the turn end."""
    if not is_zethus_turn(reply) or person_moved_wait(event):
        return ""
    gate_ask = asks_to_defer_gate_fix(reply)
    rebase_ask = hands_back_rebase(reply)
    if is_real_stop(reply) and not gate_ask and not rebase_ask:
        return ""
    counter = refusals_file(event)
    try:
        seen = int(counter.read_text(encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        seen = 0
    if seen >= MAX_REFUSALS:
        return ""
    counter.write_text(str(seen + 1), encoding="utf-8")
    if gate_ask:
        reason = ("Zethus: don't ask leave to move a failing gate's remediation into this phase. Every "
                  "local gate is green before a phase pushes, whatever the phase plan says, so fix the "
                  "failing gate now, in this phase, with the smallest change that turns it green, then "
                  "re-run `run-local-gates` and push. Say in the phase's report that the fix was pulled "
                  "forward and why. The one exception is a `push-red` ruling already approved in the "
                  "spec's Gate remediation section; the gate script says when one applies. "
                  f"(Refusal {seen + 1} of {MAX_REFUSALS}; after that the turn is let through.)")
        return json.dumps({"decision": "block", "reason": reason})
    if rebase_ask:
        reason = ("Zethus: a stale base is not a stop, and the rebase is not the person's to do. Bring "
                  "the branch up to date yourself, now: rebase onto origin/<base> (a stack from its top "
                  "with --update-refs), resolve any conflicts keeping both sides' intent, re-run "
                  "base-freshness until it reports FRESH, re-run the gates if work was already written, "
                  "and push a rewritten branch with --force-with-lease, saying in the PR that it was "
                  "rebased. Then carry on. Stop only if the fetch fails, or a conflict needs a decision "
                  "the spec and the diff can't make; then name the hunk and why, with the rebase paused "
                  "cleanly or aborted. The steps are in pre-push-gates, \"Bring a stale branch up to date\". "
                  f"(Refusal {seen + 1} of {MAX_REFUSALS}; after that the turn is let through.)")
        return json.dumps({"decision": "block", "reason": reason})
    if waits_on_background(reply):
        reason = ("Zethus: a command running in the background is not a stop. Don't end the turn to wait "
                  "for it: block on the harness's output read for it (`read_powershell` with its shellId "
                  "and delay 600 on the Copilot CLI; it returns as soon as the command exits), again "
                  "and again until it exits, with no narration per wait, then carry on. If it has outlived the wait bound, close with the "
                  "Stopped at / Next / Why block, saying the command is still running in the background "
                  "and how long you waited. "
                  f"(Refusal {seen + 1} of {MAX_REFUSALS}; after that the turn is let through.)")
        return json.dumps({"decision": "block", "reason": reason})
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
    if not reply or not is_zethus_turn(reply) or person_moved_wait(event):
        return ""
    if NOTIFICATION_RE.search(str(event.get("prompt") or "")):
        return ""  # the harness resuming a turn that waited on a command; the wait is over
    if asks_to_defer_gate_fix(reply):
        text = ("Zethus: your last turn asked leave to move a failing gate's remediation into the phase. "
                "Don't wait for it: fix the failing gate in the phase being pushed, as small a fix as "
                "turns it green, re-run `run-local-gates`, and say in the phase's report that the fix "
                "was pulled forward. Unless this message is a question, do that first.")
        return json.dumps({"additionalContext": text,
                           "hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                  "additionalContext": text}})
    if hands_back_rebase(reply):
        text = ("Zethus: your last turn stopped for a stale base, which is not a stop. Unless this "
                "message is a question, rebase the branch yourself first (pre-push-gates, \"Bring a "
                "stale branch up to date\"), re-run base-freshness and the gates, then carry on.")
        return json.dumps({"additionalContext": text,
                           "hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                  "additionalContext": text}})
    if is_real_stop(reply):
        return ""
    if waits_on_background(reply):
        text = ("Zethus: your last turn ended to wait on a background command, which is not a stop. Unless "
                "this message is a question, resume the wait first: block on the harness's output read "
                "for it (`read_powershell` with its shellId and delay 600 on the Copilot CLI) until it "
                "exits, then carry on.")
        return json.dumps({"additionalContext": text,
                           "hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                  "additionalContext": text}})
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

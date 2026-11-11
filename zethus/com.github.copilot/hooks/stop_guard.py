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

Nor is a job the agent can do with its own tools (``docs/do-the-work-yourself.md``). Three more
stops are refused for that reason:

- a ``Why:`` that waits on the person to *do* something (run, re-run, install, regenerate, format,
  fix, update, configure, check…), unless it also names what only the person can give: a
  credential or access, a sign-off, an approval, a merge, a decision;
- a ``Why:`` that names a failed fetch but not the cause left for the person (a credential, the
  network, a VPN…), since the agent retries and diagnoses a failed fetch itself first;
- a done stop whose closing lines report red or failing CI on the PR, which is the agent's to fix.

A turn that is legitimately waiting on a background command is not a turn that ended: the model is
inside a tool call (the output read), so this hook never sees it. What the hook can see is the report
after the wait bound ran out. That ends the turn at a real stop only if its ``Why:`` says the command is
still running in the background *and* the closing lines give how long was waited ("waited 30
minutes"). "Waiting on the background install" with no duration is the silent stop, and is refused
with a reason that says to block on the output read instead.

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
WAITED_RE = re.compile(r"\bwaited\b[^.\n]{0,40}?\b\d+(?:\.\d+)?\s*"
                       r"(?:s|secs?|seconds?|m|mins?|minutes?|h|hrs?|hours?)\b")
# A Why about a stale base that hands the rebase back. Only a failed fetch or a conflict excuses it.
STALE_WHY_RE = re.compile(r"\b(stale (?:base|branch)|(?:base|branch) is stale|rebas\w*|commits? behind"
                          r"|behind (?:origin|the base|its base|the integration branch))\b")
STALE_WALL_RE = re.compile(r"\b(conflict\w*|hunks?|fetch\w*|no answer"
                           # a Why that only mentions a rebase already done, at another wall
                           r"|sign-?off|goal is complete|change is done|work is done|no further phase)\b")
# A Why that waits on the person to do work the agent has the tools for.
HANDOFF_WHY_RE = re.compile(
    r"\b(?:(?:for|on)\s+(?:you|the person|the user|them|someone)\s+to"
    r"|(?:you|the person|the user|someone)\s+(?:needs?|has|have|must|should|will need)\s+to"
    r"|please|over to you(?:\s+to)?|once you|after you|until you)\s+"
    r"(?:re-?run|run|install|re-?generate|regenerate|format|fix|update|rebase|resolve|configure"
    r"|set up|add|create|commit|push|check|verify|retry|restart|migrate|download|apply|enable"
    r"|edit|clean|build|test|paste)\b")
# What only the person can give. A hand-off that names one of these is a real wall.
HUMAN_ONLY_RE = re.compile(
    r"\b(?:credential\w*|tokens?|passwords?|secrets?|2fa|mfa|sso|sign(?:-| )?in|log(?:-| )?in|vpn"
    r"|prox(?:y|ies)|network access|access|permissions?|grant\w*|sign-?off|approv\w*|merg\w*"
    r"|decision|decide|ruling|choice|choose|physical\w*|hardware|device)\b")
# A Why about a failed fetch. Only one that names the cause left for the person is a stop.
FETCH_FAIL_RE = re.compile(r"\b(?:fetch(?:ing)? (?:failed|fails|error\w*)|failed to fetch"
                           r"|(?:could not|couldn't|can't|cannot) fetch|gave no answer|no answer)\b")
FETCH_CAUSE_RE = re.compile(r"\b(?:credential\w*|tokens?|auth\w*|passwords?|permissions?|access"
                            r"|denied|forbidden|401|403|sso|2fa|mfa|vpn|prox(?:y|ies)|network"
                            r"|offline|unreachable|dns|host)\b")
# A done stop over red CI on the PR.
DONE_RE = re.compile(r"\b(?:goal is complete|change is done|work is done|no further phase)\b")
CI_RED_RE = re.compile(r"\b(?:ci|checks?|pipeline|workflow)\b[^.\n]{0,40}?\b(?:red|fail\w*|broken)\b"
                       r"|\b(?:red|failing|failed)\s+(?:ci|checks?|pipeline|workflow)\b")
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


def why_of(reply: str) -> str:
    why = WHY_RE.search(closing_lines(reply))
    return why.group("why").lower() if why else ""


def hands_off_work(reply: str) -> bool:
    """The closing ``Why:`` waits on the person to do work the agent could do itself."""
    reason = why_of(reply)
    return bool(HANDOFF_WHY_RE.search(reason)) and not HUMAN_ONLY_RE.search(reason)


def bare_fetch_stop(reply: str) -> bool:
    """The closing ``Why:`` stops for a failed fetch without naming what is left for the person."""
    reason = why_of(reply)
    return bool(FETCH_FAIL_RE.search(reason)) and not FETCH_CAUSE_RE.search(reason)


def done_over_red_ci(reply: str) -> bool:
    """A done stop whose closing lines report red CI on the PR, not yet fixed."""
    tail = closing_lines(reply).lower()
    return (bool(DONE_RE.search(why_of(reply))) and bool(CI_RED_RE.search(tail))
            and "fixed" not in tail)


HANDOFF_REASON = ("Zethus: that stop hands the person a job you can do with your own tools. Run, "
                  "re-run, install, regenerate, format or fix it yourself, now, then carry on. Stop "
                  "for the person only at what only they can give (a credential or access they "
                  "hold, a sign-off, an approval, a merge, a decision), after doing everything up "
                  "to it, and name that one thing in the Why line (docs/do-the-work-yourself.md). ")
FETCH_REASON = ("Zethus: a failed fetch is yours to diagnose before it is a stop. Retry it once, "
                "read the error, check `git remote -v` and `git ls-remote --heads <remote>`, and fix "
                "a wrong remote or base; then re-run base-freshness. Stop only for what this machine "
                "can't supply, and name it in the Why line: a missing or rejected credential, or a "
                "network or VPN the person must join (pre-push-gates, \"When the fetch fails\"). ")
CI_REASON = ("Zethus: the change isn't done while CI is red on its PR, and fixing it is yours, not "
             "the reviewer's. Read the failing check's log (`gh run view <run-id> --log-failed`), "
             "reproduce it locally, fix it on that phase's branch, re-run `run-local-gates`, push, "
             "and say in a PR comment what failed and what fixed it (zethus-pr-description, step 4). "
             "Only merging, or waiting out or waiving a check, is the person's call. ")


def next_action(reply: str) -> str:
    found = NEXT_RE.findall(reply)
    return found[-1].strip() if found else "the next stage or phase in your plan"


def refusals_file(event: dict) -> Path:
    sid = re.sub(r"[^A-Za-z0-9_.-]", "_", str(event.get("sessionId") or event.get("session_id") or "session"))
    return Path(tempfile.gettempdir()) / f"zethus-stop-guard-{sid}.count"


def refuse(event: dict, reply: str) -> str:
    """The block decision, or ``""`` to let the turn end."""
    if not is_zethus_turn(reply):
        return ""
    gate_ask = asks_to_defer_gate_fix(reply)
    rebase_ask = hands_back_rebase(reply)
    labor = (HANDOFF_REASON if hands_off_work(reply) else FETCH_REASON if bare_fetch_stop(reply)
             else CI_REASON if done_over_red_ci(reply) else "")
    if is_real_stop(reply) and not gate_ask and not rebase_ask and not labor:
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
    if labor:
        reason = labor + f"(Refusal {seen + 1} of {MAX_REFUSALS}; after that the turn is let through.)"
        return json.dumps({"decision": "block", "reason": reason})
    if waits_on_background(reply):
        reason = ("Zethus: a command running in the background is not a stop. Don't end the turn to wait "
                  "for it: block on the harness's output read for it (`read_powershell` with its shellId "
                  "and a long delay on the Copilot CLI), again and again until it exits, with no "
                  "narration per wait, then carry on. If it has outlived the wait bound, close with the "
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
    if not reply or not is_zethus_turn(reply):
        return ""
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
    labor = (HANDOFF_REASON if hands_off_work(reply) else FETCH_REASON if bare_fetch_stop(reply)
             else CI_REASON if done_over_red_ci(reply) else "")
    if labor:
        text = ("Zethus: your last turn stopped for a job that was yours. Unless this message is a "
                "question, do that first. " + labor.split(": ", 1)[1])
        return json.dumps({"additionalContext": text,
                           "hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                  "additionalContext": text}})
    if is_real_stop(reply):
        return ""
    if waits_on_background(reply):
        text = ("Zethus: your last turn ended to wait on a background command, which is not a stop. Unless "
                "this message is a question, resume the wait first: block on the harness's output read "
                "for it (`read_powershell` with its shellId and a long delay on the Copilot CLI) until it "
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

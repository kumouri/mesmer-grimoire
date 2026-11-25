#!/usr/bin/env python3
"""Mnemosyne hook bridge (Claude Code plugin hooks; the same script serves any host that runs
Claude-format or Copilot-format hooks).

Invoked by a hooks file with a mode argument. Reads the hook's JSON event on stdin and drives the
reflexion memory. It is deliberately fail-open: if the `mnemosyne` package isn't installed, or
there's no memory repo to point at, it exits 0 and stays silent so it can never break a session.

Modes:
  prompt         (UserPromptSubmit, userPromptSubmitted) recall lessons for the user's prompt and
                 print the digest. Silent when nothing matches. Also records capture candidates
                 S4/S5 (and S12) and remembers which lessons the digest listed.
  session-start  (SessionStart, sessionStart) git-pull the shared memory so lessons are fresh.
                 Skipped when there is nothing to pull (no remote, no configured store), since
                 sync's git calls cost ~300 ms on Windows; `mnemosyne sync` still does it all.
                 In active mode, prints the recall digest and the count of candidates awaiting triage.
  post-tool      (PostToolUse, PostToolUseFailure, postToolUse) records candidates S6, S8 and S9-S11.
  stop           (Stop, agentStop) logs whether it would block for triage; in active mode it blocks
                 once (the re-fire carries stop_hook_active) so the triage happens.
  pre-compact    (PreCompact, preCompact) logs the spool state before compaction.

Capture runs in SHADOW MODE unless the project config asks otherwise (docs/lessons-capture-spec.md):
candidates are appended to memory/.capture/ in the memory repo and every invocation logs one decision
line, but nothing is stored as a lesson, nothing is asked, and no capture mode prints anything. In
ACTIVE mode (`memory.mode: "active"` or MNEMOSYNE_CAPTURE_MODE=active) the session-start digest and
the stop block appear. Which signals then ask is decided by the engine (`mnemosyne.candidates`,
`signal_status`); `mnemosyne candidate list` and `mnemosyne doctor` show the results.
MNEMOSYNE_CAPTURE=off turns capture off and leaves recall as it was.

HOW CONTEXT REACHES THE MODEL differs by host (spec §4.7.1). Claude Code and Codex inject a hook's
plain stdout. Copilot CLI injected only JSON `{"additionalContext": ...}` and dropped plain stdout,
so on a Copilot host an active-mode digest is printed as that JSON. In shadow mode nothing about the
output changes on any host, so upgrading the package alters no session. The Copilot shape was
observed on the CLI; VS Code and the cloud agent are unverified (VS Code's docs say it ignores a
prompt hook's output), and a host that isn't recognised as Copilot gets plain stdout.

One event can arrive twice, when a host reads both a repo's .github/hooks and ~/.copilot/hooks. The
engine claims each event once, and the run that loses the claim stops without recalling, syncing or
printing a digest. The guard needs the spool, so with capture off each registration runs recall.
Copies of this script (any path, any repo) all share the guard, because it lives in
`mnemosyne.candidates`.

There is no session-end mode: Claude Code discards SessionEnd hook output, so a "remember to
/reflect" reminder there would never be seen. Any other mode (including a stale `session-end`
from an older hooks.json) is a silent no-op.

Point it at a memory repo with $MNEMOSYNE_REPO (else it uses the cwd, and stays silent if
that isn't a memory repo). Optional $MNEMOSYNE_CONFIG selects a config. `--host <name>` after
the mode names the host for the decision log when a registration knows it; otherwise the host
is inferred from the event's shape.
"""
import json
import os
import sys
from pathlib import Path

COPILOT_HOSTS = ("copilot-cli", "copilot")


def _load_event():
    try:
        ev = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError):
        return {}
    return ev if isinstance(ev, dict) else {}


def _mn():
    try:
        import mnemosyne as mn  # noqa: WPS433
        return mn
    except Exception:
        return None


def _capture(mode, event, host):
    """Capture: record candidates and log the decision. Never raises, never prints.
    Returns True if another registration already handled this event."""
    try:
        from mnemosyne import candidates
        rec = candidates.capture_event(mode, event, host=host)
        return bool(rec) and rec.get("decision") == "duplicate"
    except Exception:
        return False  # fail-open: capture must never break a session or the recall beside it


def _emit(text, event, host):
    """Print context for the model in the shape the host injects: JSON `additionalContext` on a
    Copilot host, plain stdout on every other."""
    if not text:
        return
    try:
        from mnemosyne import candidates as cd
        host = host or cd.detect_host(event)
    except Exception:
        host = host or ""
    if host in COPILOT_HOSTS:
        print(json.dumps({"additionalContext": text}))
    else:
        print(text)


def _active(event):
    """True when this project is in active capture mode (spec Phase 1 and 2's visible behaviour)."""
    try:
        from mnemosyne import candidates as cd
        return cd.capture_mode(cd.project_memory_config(Path(str(event.get("cwd") or os.getcwd())))) == "active"
    except Exception:
        return False


def _note_recall(event, digest):
    """Remember which lessons this digest listed, so a correction later in the session can raise
    S12. Best-effort and silent."""
    try:
        from mnemosyne import candidates as cd
        root = Path(str(event.get("cwd") or os.getcwd()))
        repo = cd.spool_repo(root)
        if repo is not None and cd.capture_enabled(cd.project_memory_config(root)):
            cd.note_recall(repo, cd.session_of(event), cd.digest_ids(digest))
    except Exception:
        pass


def do_prompt(event, host):
    mn = _mn()
    if mn is None or _capture("prompt", event, host):
        return 0
    prompt = (event.get("prompt") or "").strip()
    if not prompt:
        return 0
    try:
        digest = mn.recall(prompt, as_text=True)
    except Exception:
        return 0  # fail-open: no memory repo, bad config, etc.
    if not digest or "no reflexion lessons matched" in digest:
        return 0
    _note_recall(event, digest)
    text = ("[Mnemosyne reflexion memory] Relevant prior lessons — apply them and tell the "
            "user which you applied:\n" + digest)
    _emit_prompt(text, event, host)
    return 0


def _is_copilot(event, host):
    try:
        from mnemosyne import candidates as cd
        return (host or cd.detect_host(event)) in COPILOT_HOSTS
    except Exception:
        return False


def _emit_prompt(text, event, host):
    """The prompt digest. Claude Code and Codex inject plain stdout. Copilot is different: the CLI
    dropped plain stdout and injected JSON, but its docs say a prompt hook's output is ignored. So
    on Copilot the JSON form is only used in active mode, and shadow mode prints what it always did."""
    if _is_copilot(event, host) and not _active(event):
        print(text)
        return
    _emit(text, event, host)


def do_session_start(event, host):
    mn = _mn()
    if mn is None or _capture("session-start", event, host):
        return 0
    try:
        from mnemosyne import core, load_config, resolve_repo
        repo = resolve_repo(None)
        cfg = load_config(None, repo)
        if core.sync_has_work(cfg, repo):
            core.sync(cfg, repo)  # best-effort git pull; ignores no-remote / no-git
    except Exception:
        pass  # sync is best-effort; a failure must never stop the digest below
    try:
        _session_digest(mn, event, host)  # a recall digest + pending triage count (active mode)
    except Exception:
        return 0
    return 0


def _session_digest(mn, event, host):
    """In ACTIVE capture mode, print a recall digest for the branch and the count of candidates
    awaiting triage. Silent in shadow mode, so a package upgrade changes nothing until the project
    config opts in. Claude Code and Codex inject SessionStart stdout as context; on Copilot it goes
    out as JSON `additionalContext` (spec §4.7.1)."""
    from mnemosyne import candidates as cd
    root = Path(str(event.get("cwd") or os.getcwd()))
    mem_cfg = cd.project_memory_config(root)
    if cd.capture_mode(mem_cfg) != "active":
        return
    repo = cd.spool_repo(root)
    ctx = cd.project_context(root)
    branch = ctx.get("branch") or ""
    query = " ".join(x for x in (ctx.get("repo"), branch.replace("/", " ").replace("-", " ")) if x)
    pieces = []
    try:
        digest = mn.recall(query, as_text=True) if query else ""
    except Exception:
        digest = ""
    if digest and "no reflexion lessons matched" not in digest:
        pieces.append(digest)
        _note_recall(event, digest)
    if repo is not None:
        try:
            n = cd.untriaged_count(repo, project=ctx.get("repo"), branch=ctx.get("branch") or None,
                                   mem_cfg=mem_cfg)
        except Exception:
            n = 0
        if n:
            pieces.append(f"[Mnemosyne] {n} capture candidate(s) await triage in this project — "
                          f"run the lessons-triage skill (`mnemosyne candidate triage`).")
    if pieces:
        _emit("\n\n".join(pieces), event, host)


def do_stop(event, host):
    """Record the stop event, and in ACTIVE mode block once (the re-fire carries stop_hook_active)
    to force a triage of the pending candidates. In shadow mode it only records (never blocks).
    Claude Code (Stop), Copilot CLI (agentStop) and Codex (Stop) all take this JSON decision."""
    if _mn() is None:
        return 0
    try:
        from mnemosyne import candidates as cd
        rec = cd.capture_event("stop", event, host=host)
    except Exception:
        return 0
    if rec and rec.get("decision") == "block":
        n = rec.get("untriaged", 0)
        reason = (f"{n} capture candidate(s) await triage before this turn ends. Run the "
                  f"lessons-triage skill: triage the spool (`mnemosyne candidate triage`), auto-store "
                  f"the ADR and gate lessons to the local tier, and put every question in one batched "
                  f"question set.")
        print(json.dumps({"decision": "block", "reason": reason}))
    return 0


def _capture_only(mode):
    def run(event, host):
        if _mn() is not None:
            _capture(mode, event, host)
        return 0
    return run


MODES = {"prompt": do_prompt, "session-start": do_session_start,
         "post-tool": _capture_only("post-tool"), "stop": do_stop,
         "pre-compact": _capture_only("pre-compact")}


def main():
    args = sys.argv[1:]
    mode = args[0] if args else "prompt"
    host = args[args.index("--host") + 1] if "--host" in args[:-1] else None
    fn = MODES.get(mode)
    if fn is None:
        return 0
    try:
        return fn(_load_event(), host)
    except Exception:
        return 0  # never let a hook error surface to the user


if __name__ == "__main__":
    sys.exit(main())

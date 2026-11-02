#!/usr/bin/env python3
"""Mnemosyne hook bridge (Claude Code plugin hooks; the same script serves any host that runs
Claude-format hooks).

Invoked by the plugin's hooks.json with a mode argument. Reads the hook's JSON event on
stdin and drives the reflexion memory. It is deliberately fail-open: if the `mnemosyne`
package isn't installed, or there's no memory repo to point at, it exits 0 and stays silent
so it can never break a session.

Modes:
  prompt         (UserPromptSubmit) recall lessons for the user's prompt; print the digest,
                 which Claude Code injects as additional context. Silent when nothing matches.
                 Also records capture candidates S4/S5 (shadow).
  session-start  (SessionStart)     git-pull the shared memory so lessons are fresh. Silent.
                 Skipped when there is nothing to pull (no remote, no configured store), since
                 sync's git calls cost ~300 ms on Windows; `mnemosyne sync` still does it all.
                 Also logs the pending-candidate count (shadow).
  post-tool      (PostToolUse, PostToolUseFailure) records candidates S6, S8 and S9-S11 (shadow).
  stop           (Stop)             logs whether it would block for triage (shadow: never blocks).
  pre-compact    (PreCompact)       logs the spool state before compaction (shadow).

Capture runs in SHADOW MODE (docs/lessons-capture-spec.md, Phase 0): candidates are appended to
memory/.capture/ in the memory repo and every invocation logs one decision line, but nothing is
stored as a lesson, nothing is asked, and no capture mode prints anything. The detection lives
in the engine (`mnemosyne.candidates`); `mnemosyne candidate list` and `mnemosyne doctor` read the
results. MNEMOSYNE_CAPTURE=off turns capture off and leaves recall as it was.

One event can arrive twice, when a host reads both a repo's .github/hooks and ~/.copilot/hooks. The
engine claims each event once, and the run that loses the claim stops without recalling or syncing.
The guard needs the spool, so with capture off each registration runs recall. Copies of this script
(any path, any repo) all share the guard, because it lives in `mnemosyne.candidates`.

There is no session-end mode: Claude Code discards SessionEnd hook output, so a "remember to
/reflect" reminder there would never be seen. Any other mode (including a stale `session-end`
from an older hooks.json) is a silent no-op.

Point it at a memory repo with $MNEMOSYNE_REPO (else it uses the cwd, and stays silent if
that isn't a memory repo). Optional $MNEMOSYNE_CONFIG selects a config. `--host <name>` after
the mode names the host for the decision log when a registration knows it; otherwise the host
is inferred from the event's shape.
"""
import json
import sys


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
    """Shadow capture: record candidates and log the decision. Never raises, never prints.
    Returns True if another registration already handled this event."""
    try:
        from mnemosyne import candidates
        rec = candidates.capture_event(mode, event, host=host)
        return bool(rec) and rec.get("decision") == "duplicate"
    except Exception:
        return False  # fail-open: capture must never break a session or the recall beside it


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
    print("[Mnemosyne reflexion memory] Relevant prior lessons — apply them and tell the "
          "user which you applied:\n" + digest)
    return 0


def do_session_start(event, host):
    mn = _mn()
    if mn is None or _capture("session-start", event, host):
        return 0
    try:
        from mnemosyne import core, load_config, resolve_repo
        repo = resolve_repo(None)
        cfg = load_config(None, repo)
        if not core.sync_has_work(cfg, repo):
            return 0  # local-only memory repo: nothing to pull, so skip sync's git calls
        core.sync(cfg, repo)  # best-effort git pull; ignores no-remote / no-git
    except Exception:
        return 0
    return 0


def _capture_only(mode):
    def run(event, host):
        if _mn() is not None:
            _capture(mode, event, host)
        return 0
    return run


MODES = {"prompt": do_prompt, "session-start": do_session_start,
         "post-tool": _capture_only("post-tool"), "stop": _capture_only("stop"),
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

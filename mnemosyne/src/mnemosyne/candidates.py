"""The lessons-capture candidate spool, in SHADOW MODE (stdlib only; no git, no network, no lock).

Capture hooks detect *signals* (docs/lessons-capture-spec.md §4.2) and append *candidates* here.
Judging a candidate (store it, ask about it, promote it) is a later phase. In shadow mode a
candidate is recorded and every hook invocation logs what it saw and decided, but nothing is ever
stored as a lesson and nothing is asked: the hooks print nothing. The point is a week of data on
how often each signal fires and how often it was worth a lesson (its precision), labelled by hand
with `mnemosyne candidate label`.

FILES   memory/.capture/ in the memory repo. The directory carries its own `.gitignore` of `*`, so
        nothing in it can be committed, even from a memory repo whose .gitignore predates it.
          candidates.jsonl  append-only: {"type": "candidate", ...} lines, and {"type": "label", ...}
                            lines that fold a verdict onto a candidate (the last label wins)
          decisions.jsonl   append-only: one line per hook invocation (`mnemosyne doctor` reads it),
                            rotated to decisions.1.jsonl past DECISION_LOG_MAX bytes
          state.json        tool failures awaiting a matching success, per session (signal S6)
          fired/            one empty marker per recent hook event, the double-fire guard (below)
GUARD   a host that reads two hook files (a repo's .github/hooks and ~/.copilot/hooks) runs the
        bridge twice for one event. The first run claims the event with an O_EXCL marker; the other
        logs decision "duplicate" and stops, and the bridge then skips its recall and sync too. It
        lives here, not in the bridge, so a bridge copy committed to a repo before the guard existed
        is covered for capture as well. The key is the session plus the event's normalized content,
        never a host field name, so a Claude-format and a Copilot-format run of one event still
        match. A marker lasts FIRE_WINDOW seconds, so a real repeat later on counts again. A failed
        claim lets the event through: a double-fire is better than a lost signal. With capture off
        nothing may be written, so the guard doesn't run there.
WRITES  every line is one os.write on an O_APPEND descriptor, without the store lock: a hook must
        never wait on a store write. A torn line (a crash mid-write) is skipped on read.
PRIVACY a candidate carries pointers (signal, path, tool, exit code, a short command head), never
        tool output. The prompt signals keep a short excerpt of the user's own words, with machine
        paths replaced by <path>. Any candidate whose text has a credential shape is dropped, and
        only the shape's name is logged (spec §4.3 rule 1, §4.6).

Signals detected here: S4 and S5 (prompt), S6, S8 and S9-S11 (post-tool). S1-S3 come from Zethus's
scripts and S7 and S12 from triage, all in later phases.
"""
from __future__ import annotations

import datetime as _dt
import fnmatch
import hashlib
import json
import os
import re
import secrets
import time
from pathlib import Path

from . import core
from .core import EngineError

CAPTURE_DIR = ".capture"
CANDIDATES = "candidates.jsonl"
DECISIONS = "decisions.jsonl"
STATE = "state.json"
FIRED = "fired"
DUPLICATE = "duplicate"       # the decision logged by the second run of one event
DECISION_LOG_MAX = 1_000_000  # bytes; the previous log is kept as decisions.1.jsonl
FAILURE_TTL = 3600            # seconds a tool failure waits for its matching success (S6)
FIRE_WINDOW = 10              # seconds a second run counts as the same event, whether the host
                              # runs its hook files together or one after the other
MODES = ("session-start", "prompt", "post-tool", "stop", "pre-compact")
VERDICTS = ("lesson", "noise")

# id -> (name, kind, the outcome Phase 1+ would give it by default). Spec §4.2.
SIGNALS = {
    "S1": ("adr", "decision", "auto"),
    "S2": ("gate-red-green", "mistake", "auto"),
    "S3": ("stale-base", "process", "ignore"),
    "S4": ("explicit-remember", "convention", "auto"),
    "S5": ("correction", "convention", "ask"),
    "S6": ("fail-then-succeed", "mistake", "ask"),
    "S7": ("repeated-answer", "standard", "ask-to-promote"),
    "S8": ("fresh-eyes", "lesson", "ask"),
    "S9-S11": ("watched-path", "decision", "ask"),
    "S12": ("lesson-overridden", "supersede", "ask"),
}

DEFAULT_WATCH = ["docs/adr/", "docs/specs/", "docs/friction-log.md"]
# Where a project's `memory` config block may live, in Zethus's own resolution order.
PROJECT_CONFIGS = (".github/zethus.config.json", "$ZETHUS_CONFIG", ".copilot/zethus.config.json",
                   ".claude/amphion.config.json")

_S4_RE = re.compile(r"\b(remember|always|never|from now on)\b", re.I)
_S5_RE = re.compile(r"(^\s*no\s*[,.!]|\bdon['’]?t\b|\bdo not\b|\binstead\b|"
                    r"\bthat(?:['’]s| is) (?:wrong|not right)\b)", re.I)
_SHELL_TOOLS = {"bash", "powershell", "pwsh", "shell", "cmd", "run_in_terminal", "terminal",
                "local_shell", "exec_command", "shell_command"}
_WRITE_TOOLS = {"write", "edit", "multiedit", "notebookedit", "create", "edit_file", "write_file",
                "str_replace", "str_replace_editor", "str_replace_based_edit_tool", "insert",
                "apply_patch", "replace"}
_PATCH_FILE_RE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+?)\s*$", re.M)
_EXIT_RE = re.compile(r"(?:^Exit code|completed with exit code)\s+(-?\d+)", re.I | re.M)
_OFF = {"0", "off", "false", "no", "disabled"}


# ----------------------------------------------------------------------------- files


def capture_dir(repo: Path) -> Path:
    return Path(repo) / "memory" / CAPTURE_DIR


def ensure_capture_dir(repo: Path) -> Path:
    d = capture_dir(repo)
    d.mkdir(parents=True, exist_ok=True)
    gi = d / ".gitignore"
    if not gi.exists():
        gi.write_text("# lessons-capture spool: per-developer, never committed\n*\n", encoding="utf-8")
    return d


def is_self_ignored(repo: Path) -> bool:
    gi = capture_dir(repo) / ".gitignore"
    try:
        return "*" in [ln.strip() for ln in gi.read_text(encoding="utf-8").splitlines()]
    except OSError:
        return False


def _append(path: Path, obj: dict):
    data = (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o666)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def _read(path: Path) -> list:
    rows = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return rows
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue  # a torn append; skip it
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def new_id() -> str:
    return f"C-{_dt.date.today().strftime('%Y%m%d')}-{secrets.token_hex(3)}"


# ----------------------------------------------------------------------------- spool API


def candidates(repo: Path) -> list:
    """Every candidate, oldest first, each with `verdict` (None while pending) and `note` folded in."""
    out, by_id = [], {}
    for row in _read(capture_dir(repo) / CANDIDATES):
        if row.get("type") == "candidate" and row.get("id"):
            row = dict(row, verdict=None, note=None)
            by_id[row["id"]] = row
            out.append(row)
        elif row.get("type") == "label" and row.get("id") in by_id:
            by_id[row["id"]].update(verdict=row.get("verdict"), note=row.get("note"))
    return out


def add_candidate(repo: Path, signal: str, *, host="cli", event="", session="", context=None,
                  evidence=None) -> dict:
    """Append one candidate for `signal` and return it. Nothing is stored as a lesson."""
    if signal not in SIGNALS:
        raise EngineError(f"unknown signal '{signal}'; known: {', '.join(SIGNALS)}")
    name, kind, default = SIGNALS[signal]
    rec = {"type": "candidate", "id": new_id(), "ts": _now(), "signal": signal, "name": name,
           "kind": kind, "default": default, "mode": "shadow", "host": host, "event": event,
           "session": session or "", "context": context or {}, "evidence": evidence or {}}
    _append(ensure_capture_dir(repo) / CANDIDATES, rec)
    return rec


def label(repo: Path, cid: str, verdict: str, note: str = "") -> dict:
    """Record whether candidate `cid` would have made a worthwhile lesson (precision data)."""
    if verdict not in VERDICTS:
        raise EngineError(f"verdict must be one of {', '.join(VERDICTS)}")
    if cid not in {c["id"] for c in candidates(repo)}:
        raise EngineError(f"no candidate {cid} in the spool")
    rec = {"type": "label", "id": cid, "verdict": verdict, "note": note or "", "ts": _now()}
    _append(ensure_capture_dir(repo) / CANDIDATES, rec)
    return rec


def stats(repo: Path, days=None) -> dict:
    """Per signal: count, lesson, noise, unlabelled and precision (lesson / labelled, or None)."""
    rows = candidates(repo)
    if days:
        cutoff = (_dt.datetime.now() - _dt.timedelta(days=days)).isoformat(timespec="seconds")
        rows = [c for c in rows if c.get("ts", "") >= cutoff]
    per = {}
    for c in rows:
        s = per.setdefault(c["signal"], {"signal": c["signal"], "name": c.get("name", ""),
                                         "count": 0, "lesson": 0, "noise": 0, "unlabelled": 0})
        s["count"] += 1
        s[c["verdict"] if c.get("verdict") in VERDICTS else "unlabelled"] += 1
    for s in per.values():
        labelled = s["lesson"] + s["noise"]
        s["precision"] = round(s["lesson"] / labelled, 2) if labelled else None
    return {"days": days, "total": len(rows), "signals": [per[k] for k in sorted(per)]}


def log_decision(repo: Path, rec: dict):
    d = ensure_capture_dir(repo)
    log = d / DECISIONS
    try:
        if log.stat().st_size > DECISION_LOG_MAX:
            os.replace(str(log), str(d / "decisions.1.jsonl"))
    except OSError:
        pass
    _append(log, rec)


def decisions(repo: Path) -> list:
    d = capture_dir(repo)
    return _read(d / "decisions.1.jsonl") + _read(d / DECISIONS)


def doctor(repo: Path, last: int = 10) -> dict:
    """What the capture hooks have been doing: the last decisions, counts, and spool health."""
    log = decisions(repo)
    cands = candidates(repo)
    by_decision, last_by_mode, slowest = {}, {}, None
    for r in log:
        by_decision[r.get("decision", "?")] = by_decision.get(r.get("decision", "?"), 0) + 1
        last_by_mode[r.get("mode", "?")] = r.get("ts")
        if isinstance(r.get("ms"), (int, float)) and (slowest is None or r["ms"] > slowest["ms"]):
            slowest = {"ms": r["ms"], "mode": r.get("mode"), "ts": r.get("ts")}
    return {"dir": str(capture_dir(repo)), "exists": capture_dir(repo).is_dir(),
            "self_ignored": is_self_ignored(repo), "candidates": len(cands),
            "pending": sum(1 for c in cands if not c.get("verdict")),
            "decisions": len(log), "by_decision": by_decision, "last_by_mode": last_by_mode,
            "slowest": slowest, "recent": log[-last:] if last else []}


# ----------------------------------------------------------------------------- event reading
# Field names differ per host; these were observed on real installs (spec §4.7.1).


def detect_host(ev: dict, env=None) -> str:
    """Best-effort host name from the event's shape, then the environment. A registration that
    knows its host passes --host instead. Env alone can mislead: Codex passes its parent's
    environment through, and Copilot and Cursor both set CLAUDE_PROJECT_DIR."""
    env = os.environ if env is None else env
    if "cursor_version" in ev or "conversation_id" in ev:
        return "cursor"
    if env.get("COPILOT_CLI") or any(k in ev for k in ("sessionId", "toolName", "toolArgs")):
        return "copilot-cli"
    if "turn_id" in ev:
        return "codex"
    if env.get("CLAUDECODE") or env.get("CLAUDE_CODE_ENTRYPOINT"):
        return "claude-code"
    return "unknown"


def _obj(v):
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return {}
    return v if isinstance(v, dict) else {}


def tool_name(ev: dict) -> str:
    return str(ev.get("tool_name") or ev.get("toolName") or "")


def tool_input(ev: dict) -> dict:
    return _obj(ev.get("tool_input") if "tool_input" in ev else ev.get("toolArgs"))


def session_of(ev: dict) -> str:
    return str(ev.get("session_id") or ev.get("sessionId") or ev.get("conversation_id") or "")


def command_head(cmd: str) -> str:
    """The program and its first non-flag argument ("npm test", "python unittest"), so two runs
    of the same command with different flags or paths compare equal. No output, no paths."""
    words = []
    for w in (cmd or "").strip().split():
        if w in ("&&", "||", "|", ";"):
            break
        if w.startswith("-") or (not words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w)):
            continue  # a flag, or a leading VAR=value assignment
        words.append(re.split(r"[\\/]", w.strip("'\""))[-1])
        if len(words) == 2:
            break
    return " ".join(words)[:60]


def tool_outcome(ev: dict):
    """("failure" | "success" | None, exit code or None). None when the host doesn't say (Codex's
    PostToolUse carries only output text)."""
    hen = str(ev.get("hook_event_name") or "").lower()
    if hen == "posttoolusefailure":
        m = _EXIT_RE.search(str(ev.get("error") or ""))
        return "failure", int(m.group(1)) if m else None
    tr = ev.get("toolResult", ev.get("tool_result"))
    tr = _obj(tr) if isinstance(tr, (dict, str)) else {}
    if tr:
        rt = str(tr.get("resultType") or tr.get("result_type") or "").lower()
        m = _EXIT_RE.search(str(tr.get("textResultForLlm") or tr.get("text_result_for_llm") or ""))
        code = int(m.group(1)) if m else None
        if rt in ("failure", "denied") or (code is not None and code != 0):
            return "failure", code
        if code == 0 or rt == "success":
            return "success", code
    if hen == "posttooluse" and isinstance(ev.get("tool_response"), dict):
        return "success", None  # Claude Code fires PostToolUse only for a tool that succeeded
    return None, None


def written_paths(ev: dict) -> list:
    """Paths a file-writing tool call touched (empty for reads and shell commands)."""
    if str(ev.get("hook_event_name") or "").lower() == "afterfileedit" and ev.get("file_path"):
        return [str(ev["file_path"])]
    name = tool_name(ev).lower()
    if name not in _WRITE_TOOLS:
        return []
    inp = tool_input(ev)
    paths = [str(inp[k]) for k in ("file_path", "path", "notebook_path", "filePath") if inp.get(k)]
    for k in ("command", "input", "patch"):
        if isinstance(inp.get(k), str):
            paths += _PATCH_FILE_RE.findall(inp[k])
    return paths


def is_fresh_eyes(ev: dict) -> bool:
    return "skill" in tool_name(ev).lower() and "fresh-eyes-investigation" in json.dumps(tool_input(ev))


def relative_to(path: str, root: str):
    """`path` relative to `root` with forward slashes, or None if it lies outside it."""
    p = path.replace("\\", "/")
    r = root.replace("\\", "/").rstrip("/")
    if not re.match(r"^(?:[A-Za-z]:)?/", p):
        rel = p[2:] if p.startswith("./") else p
        return None if rel == ".." or rel.startswith("../") else rel
    fold = os.name == "nt" or re.match(r"^[A-Za-z]:/", p)
    a, b = (p.casefold(), r.casefold()) if fold else (p, r)
    return p[len(r) + 1:] if r and a.startswith(b + "/") else None


def watch_match(rel: str, watch) -> str | None:
    for w in watch:
        w = str(w).replace("\\", "/")
        if (w.endswith("/") and rel.startswith(w)) or rel == w or fnmatch.fnmatch(rel, w):
            return w
    return None


def prompt_signals(prompt: str) -> list:
    """[(signal, matched phrase, excerpt)] for S4 and S5, at most one each."""
    out = []
    for sig, pat in (("S4", _S4_RE), ("S5", _S5_RE)):
        m = pat.search(prompt or "")
        if m:
            out.append((sig, m.group(0).strip(), excerpt(prompt, m.start(), m.end())))
    return out


def excerpt(text: str, start: int, end: int, width: int = 60) -> str:
    a, b = max(0, start - width), min(len(text), end + width)
    snip = " ".join(text[a:b].split())
    return core.scrub_machine_paths(("..." if a else "") + snip + ("..." if b < len(text) else ""))


# ----------------------------------------------------------------------------- project context


def _git_dir(start: Path):
    p = start
    for _ in range(25):
        g = p / ".git"
        if g.is_dir():
            return p, g
        if g.is_file():
            m = re.match(r"gitdir:\s*(.+)", g.read_text(encoding="utf-8", errors="replace").strip())
            if m:
                gd = Path(m.group(1))
                return p, gd if gd.is_absolute() else (p / gd)
        if p.parent == p:
            break
        p = p.parent
    return None, None


def project_context(root: Path) -> dict:
    """{repo, branch} from the filesystem alone: a hook may not run git."""
    top, gd = _git_dir(root)
    ctx = {"repo": (top or root).name}
    try:
        head = (gd / "HEAD").read_text(encoding="utf-8").strip() if gd else ""
    except OSError:
        head = ""
    if head.startswith("ref: refs/heads/"):
        ctx["branch"] = head[len("ref: refs/heads/"):]
    elif head:
        ctx["branch"] = "(detached)"
    return ctx


def project_memory_config(root: Path) -> dict:
    """The `memory` block of the first project config that has one (spec §4.7), else {}."""
    for name in PROJECT_CONFIGS:
        p = Path(os.environ.get("ZETHUS_CONFIG", "")) if name == "$ZETHUS_CONFIG" else root / name
        if name == "$ZETHUS_CONFIG" and not os.environ.get("ZETHUS_CONFIG"):
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and isinstance(doc.get("memory"), dict):
            return doc["memory"]
    return {}


def capture_enabled(mem_cfg: dict, env=None) -> bool:
    env = os.environ if env is None else env
    if str(env.get("MNEMOSYNE_CAPTURE", "")).strip().lower() in _OFF:
        return False
    return mem_cfg.get("enabled", True) is not False


def spool_repo(root: Path, env=None):
    """The memory repo the spool belongs to: $MNEMOSYNE_REPO, else the project root. None if
    neither has a memory/ directory (then there is nowhere to record, so the hook stays silent)."""
    env = os.environ if env is None else env
    cand = Path(env["MNEMOSYNE_REPO"]).expanduser() if env.get("MNEMOSYNE_REPO") else root
    return cand if (cand / "memory").is_dir() else None


# ----------------------------------------------------------------------------- failure state (S6)


def _load_state(repo: Path) -> dict:
    try:
        st = json.loads((capture_dir(repo) / STATE).read_text(encoding="utf-8"))
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(repo: Path, st: dict):
    now = time.time()
    st = {s: [f for f in fails if now - f.get("t", 0) < FAILURE_TTL] for s, fails in st.items()}
    st = {s: fails[-10:] for s, fails in st.items() if fails}
    core.atomic_write_text(ensure_capture_dir(repo) / STATE, json.dumps(st))


# ----------------------------------------------------------------------------- double-fire guard


def fire_key(mode: str, ev: dict, root: Path) -> str:
    """One event's identity across registrations: the session (the project, if the host sends
    none) and the mode, with the fields that tell two real events apart. Normalized, so the tool's
    name is left out: 1.0.88 of the Copilot CLI calls one tool `powershell` and `Bash` (spec §4.7.1)."""
    parts = [mode, session_of(ev) or os.path.normcase(str(root)), str(ev.get("prompt") or ""),
             tool_input(ev), tool_outcome(ev), bool(ev.get("stop_hook_active")),
             str(ev.get("source") or ""), str(ev.get("trigger") or "")]
    text = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def first_fire(repo: Path, mode: str, ev: dict, root: Path) -> bool:
    """Claim this event. False if another run claimed it in the last FIRE_WINDOW seconds. Expired
    markers go first, so the folder stays small and a later repeat claims afresh."""
    try:
        d = ensure_capture_dir(repo) / FIRED
        d.mkdir(exist_ok=True)
        cutoff = time.time() - FIRE_WINDOW
        for entry in os.scandir(d):
            try:
                if entry.stat().st_mtime < cutoff:
                    os.unlink(entry.path)
            except OSError:
                continue  # another run got there first
    except OSError:
        return True
    try:
        os.close(os.open(str(d / fire_key(mode, ev, root)), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        return False
    except OSError:
        pass
    return True


# ----------------------------------------------------------------------------- the hook entry


def capture_event(mode: str, ev: dict, *, host=None, env=None, root=None):
    """Run one capture hook invocation in shadow mode. Returns the decision record it logged, or
    None if capture is off or there is no memory repo to record into. Never prints, never stores a
    lesson, never asks; the caller prints nothing for any capture mode."""
    t0 = time.perf_counter()
    env = os.environ if env is None else env
    ev = ev if isinstance(ev, dict) else {}
    root = Path(root or ev.get("cwd") or os.getcwd())
    repo = spool_repo(root, env)
    mem_cfg = project_memory_config(root)
    if repo is None or not capture_enabled(mem_cfg, env):
        return None
    host = host or detect_host(ev, env)
    session = session_of(ev)
    ctx = project_context(root)
    event = str(ev.get("hook_event_name") or mode)
    rec = {"ts": _now(), "mode": mode, "host": host, "event": event, "session": session,
           "context": ctx, "decision": "no-signal", "signals": [], "candidates": []}

    if mode in MODES and not first_fire(repo, mode, ev, root):
        rec.update(decision=DUPLICATE, detail="another registration already handled this event",
                   ms=round((time.perf_counter() - t0) * 1000, 2))
        log_decision(repo, rec)
        return rec

    def add(signal, evidence):
        c = add_candidate(repo, signal, host=host, event=event, session=session, context=ctx,
                          evidence=evidence)
        rec["signals"].append(signal)
        rec["candidates"].append(c["id"])
        rec["decision"] = "candidate"

    if mode == "prompt":
        prompt = str(ev.get("prompt") or "")
        hits = prompt_signals(prompt)
        shape = core.find_secret(prompt) if hits else None
        if shape:
            rec.update(decision="dropped", detail=f"credential shape ({shape}); nothing recorded",
                       signals=[h[0] for h in hits])
        for sig, phrase, snip in ([] if shape else hits):
            add(sig, {"match": phrase, "excerpt": snip})

    elif mode == "post-tool":
        name = tool_name(ev)
        if is_fresh_eyes(ev):
            add("S8", {"tool": name, "skill": "fresh-eyes-investigation"})
        watch = mem_cfg.get("watch") if isinstance(mem_cfg.get("watch"), list) else DEFAULT_WATCH
        for path in written_paths(ev):
            rel = relative_to(path, str(root))
            hit = watch_match(rel, watch) if rel else None
            if hit:
                add("S9-S11", {"tool": name, "path": core.scrub_machine_paths(rel), "watch": hit})
        if name.lower() in _SHELL_TOOLS:
            head = command_head(str(tool_input(ev).get("command") or ""))
            outcome, code = tool_outcome(ev)
            if head and core.find_secret(head):
                head = ""
            head = core.scrub_machine_paths(head)
            st = _load_state(repo) if head and outcome else {}
            fails = st.get(session, [])
            if outcome == "failure" and head:
                fails.append({"head": head, "exit": code, "t": time.time(), "ts": _now()})
                st[session] = fails
                _save_state(repo, st)
                if rec["decision"] == "no-signal":
                    rec.update(decision="noted-failure", detail=f"{head!r} exit {code}")
            elif outcome == "success" and head:
                match = next((f for f in reversed(fails) if f.get("head") == head), None)
                if match:
                    fails.remove(match)
                    st[session] = fails
                    _save_state(repo, st)
                    add("S6", {"tool": name, "head": head, "failed_exit": match.get("exit"),
                               "failed_at": match.get("ts")})
            elif outcome is None and rec["decision"] == "no-signal":
                rec["detail"] = "the host reports no tool outcome; S6 can't be seen here"

    elif mode in ("stop", "pre-compact", "session-start"):
        pending = [c for c in candidates(repo) if not c.get("verdict")]
        mine = [c for c in pending if session and c.get("session") == session]
        rec.update(pending=len(pending), pending_session=len(mine))
        if mode == "stop":
            rec["stop_hook_active"] = bool(ev.get("stop_hook_active"))
            if mine:
                rec.update(decision="would-block",
                           detail=f"{len(mine)} candidate(s) from this session; shadow mode never blocks")
            else:
                rec["decision"] = "nothing-pending"
        elif mode == "pre-compact":
            rec.update(decision="flushed", detail="appends are written immediately; nothing buffered")
        else:
            rec["decision"] = "session-start"

    else:
        return None

    rec["ms"] = round((time.perf_counter() - t0) * 1000, 2)
    log_decision(repo, rec)
    return rec

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
          instructions/     hash-only, repo/session/full-line S4 claims (no event-window expiry)
          fired/            one empty marker per recent hook event, the double-fire guard (below)
          *.lock            empty files to lock, never the data itself: see WRITES, and _rotate
GUARD   a host that reads two hook files (a repo's .github/hooks and ~/.copilot/hooks) runs the
        bridge twice for one event. The first run claims the event with an O_EXCL marker; the other
        logs decision "duplicate" and stops, and the bridge then skips its recall and sync too. It
        lives here, not in the bridge, so a bridge copy committed to a repo before the guard existed
        is covered for capture as well. The key is the session plus the event's normalized content,
        never a host field name, so a Claude-format and a Copilot-format run of one event still
        match. A marker lasts FIRE_WINDOW seconds, so a real repeat later on counts again. A failed
        claim lets the event through: a double-fire is better than a lost signal. With capture off
        nothing may be written, so the guard doesn't run there.
WRITES  concurrent hooks must not lose a line, and a hook must never wait on a store write, so
        appends skip the store lock. O_APPEND isn't enough on its own: the Windows C runtime seeks
        and then writes, and it isn't atomic on 9p (WSL's /mnt/c) or NFS either, so racing writers
        land on one offset and overwrite each other.
        Windows: one WriteFile on a handle opened with FILE_APPEND_DATA alone. The kernel picks the
        offset, so there is no lock, no wait and no timeout. `_winapi` is private, but subprocess
        has already loaded it by this point; ctypes would add about 20 ms to every hook.
        POSIX: one O_APPEND write, atomic by itself on a local filesystem, under a flock on
        <file>.lock. The lock is for the filesystems above and costs microseconds on the others.
        A run that waits SPOOL_LOCK_WAIT, or can't lock at all, writes anyway with "contended" set
        on the line, which `doctor` counts: a line that might race beats a line never written.
        Not covered: on 9p an append is slow enough that three or more writers at once can outlast
        the wait, and a line that races there can still be lost (a lost line takes its mark with
        it, so `doctor` undercounts). A Windows process and a WSL process appending to one file on
        /mnt/c don't share a lock at all, because flock doesn't reach the Windows side.
        A torn line (a crash mid-write, or a spool from before this fix) is skipped on read.
PRIVACY a candidate carries pointers (signal, path, tool, exit code, a short command head), never
        tool output. The prompt signals keep a short excerpt of the user's own words, with machine
        paths replaced by <path>. Any candidate whose text has a credential shape is dropped, and
        only the shape's name is logged (spec §4.3 rule 1, §4.6).

Signals detected here: S4 and S5 (prompt), S6, S8 and S9-S11 (post-tool), and S12 (a correction in a
session that had recalled a lesson). Their rules are in `detect.py`. S1-S3 come from Zethus's
scripts and S7 from triage, in later phases.

PHASE 2 ASK  Phase 1 auto-stores S1 and S2 and asked about nothing else it could not measure. Phase 2
        turns the rest into ask outcomes, one batched question set per checkpoint (`triage`), but
        only for signals that have earned it (`signal_status`): the deterministic facts S8 and
        S9-S11 ask; the keyword and heuristic signals S4, S5, S6 and S12 stay in SHADOW, recorded and
        never asked, until at least ASK_MIN_LABELLED of their candidates from the current detectors
        are labelled and ASK_MIN_PRECISION of them were worth a lesson, or a project opts one in
        with memory.ask.signals. A skip is remembered as a negative fingerprint, and "never ask
        about this kind" mutes a kind for good.
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

from . import core, detect
from .core import EngineError

CAPTURE_DIR = ".capture"
CANDIDATES = "candidates.jsonl"
DECISIONS = "decisions.jsonl"
ROTATE_LOCK = "decisions.rotate.lock"
STATE = "state.json"
GATES = "gates.json"          # per-branch last status of each named gate, for S2 (red -> green)
FIRED = "fired"
DUPLICATE = "duplicate"       # the decision logged by the second run of one event
DECISION_LOG_MAX = 1_000_000  # bytes; the previous log is kept as decisions.1.jsonl
SPOOL_LOCK_WAIT = 0.15        # seconds a POSIX append waits for its lock before writing anyway
_SPOOL_LOCK_POLL = 0.001
_FILE_APPEND_DATA = 0x4       # Windows: open for appending only, so the kernel picks the offset
_SHARE_ALL = 0x7              # read, write and delete: readers and a rotation are never refused
_OPEN_ALWAYS = 4
FAILURE_TTL = 3600            # seconds a tool failure waits for its matching success (S6)
FIRE_WINDOW = 10              # seconds a second run counts as the same event, whether the host
                              # runs its hook files together or one after the other
GATE_TTL = 7 * 86400         # seconds a recorded gate FAIL waits for its matching PASS (S2)
MODES = ("session-start", "prompt", "post-tool", "stop", "pre-compact")
VERDICTS = ("lesson", "noise")           # precision labels (Phase 0 shadow measurement)
RESOLUTIONS = ("stored", "asked", "skipped", "dropped", "never")  # triage outcomes ("never" also mutes the kind)
DETECTOR = 2                  # bumped when a signal's detection changes; older candidates never count
                              # towards a signal's measured precision and are never asked about
RECALLED = "recalled.json"    # per session: the lesson ids recall printed, for S12
WATCHED = "watched"           # one marker per (session, watched path): a path is a candidate once
RECALL_TTL = 86400            # seconds a session's recalled ids are remembered

# Which signals Phase 1 auto-stores (spec §5 Phase 1 + the shadow-data ruling): only the two
# deterministic, script-emitted signals. The keyword/prompt signals (S4/S5/S6) stayed too noisy in
# the shadow week to auto-store — they route to ask until their detection is tightened (Phase 2).
AUTO_SIGNALS = ("S1", "S2")

# Phase 2 ask eligibility. The facts a hook saw (a skill ran, a watched file was written) ask from the
# start, but are UNMEASURED: no shadow data exists for them yet. The signals that depend on guessing
# at words or retries ask only once their own labelled candidates show they are worth the question.
DETERMINISTIC_ASK = ("S8", "S9-S11")
MEASURED_ASK = ("S4", "S5", "S6", "S12")
ASK_MIN_LABELLED = 10         # labelled candidates (current detectors) before a signal's precision counts
ASK_MIN_PRECISION = 0.5       # lesson / labelled needed to leave shadow

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
# "adr" -> "S1", "gate-red-green" -> "S2", ... (the memory.autoStore.signals config uses names).
SIGNAL_BY_NAME = {name: sig for sig, (name, _k, _d) in SIGNALS.items()}

# Where a project's `memory` config block may live, in Zethus's own resolution order.
PROJECT_CONFIGS = (".github/zethus.config.json", "$ZETHUS_CONFIG", ".copilot/zethus.config.json",
                   ".claude/amphion.config.json")

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


def _line(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


if os.name == "nt":
    import _winapi

    def _append(path: Path, obj: dict):
        handle = _winapi.CreateFile(str(path), _FILE_APPEND_DATA, _SHARE_ALL, _winapi.NULL,
                                    _OPEN_ALWAYS, 0, _winapi.NULL)
        try:
            _winapi.WriteFile(handle, _line(obj))
        finally:
            _winapi.CloseHandle(handle)
else:
    def _wait_for_lock(fd: int) -> bool:
        deadline = time.monotonic() + SPOOL_LOCK_WAIT
        while not core._try_os_lock(fd):
            if time.monotonic() >= deadline:
                return False
            time.sleep(_SPOOL_LOCK_POLL)
        return True

    def _append(path: Path, obj: dict):
        lock = None
        try:
            lock = os.open(f"{path}.lock", os.O_RDWR | os.O_CREAT, 0o666)
            locked = _wait_for_lock(lock)
        except OSError:
            locked = False  # a filesystem without flock
        try:
            fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o666)
            try:
                os.write(fd, _line(obj if locked else dict(obj, contended=True)))
            finally:
                os.close(fd)
        finally:
            if lock is not None:
                os.close(lock)  # closing drops the flock


def _read(path: Path) -> list:
    rows = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
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


def _fold(repo: Path):
    """One pass over the spool: (every candidate, oldest first, with its `verdict` and `resolution`
    folded in; the kinds muted for good). The last label and the last resolution of a candidate win.
    `verdict` is None until labelled and `resolution` None until triaged: the two are independent
    (Phase 0 measures precision; Phase 1 triages). Callers that need several views take one fold,
    because the spool is read whole and a hook may only spend a few milliseconds."""
    out, by_id, muted = [], {}, set()
    for row in _read(capture_dir(repo) / CANDIDATES):
        kind = row.get("type")
        if kind == "candidate" and row.get("id"):
            row = dict(row, verdict=None, note=None, resolution=None, resolved_lesson=None)
            by_id[row["id"]] = row
            out.append(row)
        elif kind == "label" and row.get("id") in by_id:
            by_id[row["id"]].update(verdict=row.get("verdict"), note=row.get("note"))
        elif kind == "resolution" and row.get("id") in by_id:
            by_id[row["id"]].update(resolution=row.get("as"), resolved_lesson=row.get("lesson") or None)
        elif kind == "mute" and row.get("kind"):
            muted.add(str(row["kind"]))
    return out, muted


def candidates(repo: Path) -> list:
    """Every candidate, oldest first, with its `verdict` and `resolution` folded in."""
    return _fold(repo)[0]


def muted_kinds(repo: Path) -> set:
    return _fold(repo)[1]


def kind_of(c: dict) -> str:
    """What "never ask about this kind" mutes: the signal, narrowed by the watched-path kind."""
    sub = (c.get("evidence") or {}).get("kind")
    return f"{c.get('signal')}:{sub}" if sub else str(c.get("signal"))


def fingerprint(signal: str, context: dict, key) -> str | None:
    """A salted-by-project hash of what makes two candidates "the same thing" (a standing clause,
    a command head, a path, the lessons overridden), so a skipped candidate isn't asked twice. It
    holds no text, only the hash. None when the signal has no such identity."""
    if not key:
        return None
    text = json.dumps([signal, (context or {}).get("repo", ""), str(key)])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def add_candidate(repo: Path, signal: str, *, host="cli", event="", session="", context=None,
                  evidence=None, fp_key=None) -> dict:
    """Append one candidate for `signal` and return it. Nothing is stored as a lesson. `det` is the
    detector generation that produced it, and `fp` its fingerprint, if it has one."""
    if signal not in SIGNALS:
        raise EngineError(f"unknown signal '{signal}'; known: {', '.join(SIGNALS)}")
    name, kind, default = SIGNALS[signal]
    rec = {"type": "candidate", "id": new_id(), "ts": _now(), "signal": signal, "name": name,
           "kind": kind, "default": default, "mode": "shadow", "host": host, "event": event,
           "session": session or "", "context": context or {}, "evidence": evidence or {},
           "det": DETECTOR}
    fp = fingerprint(signal, context, fp_key)
    if fp:
        rec["fp"] = fp
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


def resolve(repo: Path, cid: str, as_: str, lesson: str = "", note: str = "") -> dict:
    """Record a triage outcome for candidate `cid`, so it leaves the untriaged set (spec §4.3).

    `stored` (auto-stored or asked-then-saved; `lesson` is the new lesson id), `asked`, `skipped`
    (a negative fingerprint: the same thing isn't asked again), `dropped`, or `never` ("never ask
    about this kind": the candidate is skipped and its kind muted). The last resolution wins."""
    if as_ not in RESOLUTIONS:
        raise EngineError(f"resolution must be one of {', '.join(RESOLUTIONS)}")
    by_id = {c["id"]: c for c in candidates(repo)}
    if cid not in by_id:
        raise EngineError(f"no candidate {cid} in the spool")
    d = ensure_capture_dir(repo) / CANDIDATES
    if as_ == "never":
        _append(d, {"type": "mute", "kind": kind_of(by_id[cid]), "ts": _now()})
        as_, note = "skipped", note or f"never ask about {kind_of(by_id[cid])}"
    rec = {"type": "resolution", "id": cid, "as": as_, "lesson": lesson or "",
           "note": note or "", "ts": _now()}
    _append(d, rec)
    return rec


def signal_status(repo: Path, mem_cfg: dict = None, cands=None) -> dict:
    """Per signal: whether triage auto-stores it, asks about it, or leaves it in shadow, and why.

    S1 and S2 auto-store. S8 and S9-S11 are facts a hook saw, so they ask (unmeasured: the shadow
    data has none of them). S4, S5, S6 and S12 depend on guessing at words or retries: they ask
    only after ASK_MIN_LABELLED of their candidates from the current detectors are labelled and
    ASK_MIN_PRECISION of those were worth a lesson (`candidate label`), or when the project opts
    one in with memory.ask.signals. Everything else stays in shadow and says so."""
    cands = candidates(repo) if cands is None else cands
    names = ((mem_cfg or {}).get("ask") or {}).get("signals")
    optin = {SIGNAL_BY_NAME.get(str(n), str(n)) for n in names} if isinstance(names, list) else set()
    out = {}
    for sig in SIGNALS:
        if sig in AUTO_SIGNALS:
            out[sig] = {"status": "auto", "why": "a deterministic script signal"}
        elif sig in DETERMINISTIC_ASK:
            out[sig] = {"status": "ask", "why": "a fact a hook saw; unmeasured so far"}
        elif sig in MEASURED_ASK:
            if sig in optin:
                out[sig] = {"status": "ask", "why": "opted in by memory.ask.signals"}
                continue
            lab = [c for c in cands if c.get("signal") == sig and c.get("det", 1) >= DETECTOR
                   and c.get("verdict") in VERDICTS]
            good = sum(1 for c in lab if c["verdict"] == "lesson")
            if len(lab) >= ASK_MIN_LABELLED and good / len(lab) >= ASK_MIN_PRECISION:
                out[sig] = {"status": "ask", "why": f"measured: {good} of {len(lab)} labelled were lessons"}
            else:
                have = f"{good} of {len(lab)} labelled were lessons" if lab else "none labelled"
                out[sig] = {"status": "shadow", "why": f"shadow, recorded but never asked: {have}; needs "
                            f"{ASK_MIN_LABELLED}+ labelled at {ASK_MIN_PRECISION:.0%}+ (or memory.ask.signals)"}
        else:
            out[sig] = {"status": "shadow", "why": "not emitted yet"}
    return out


def _suppressed(c: dict, status: dict, muted: set, seen_fp: set, adr_paths: set):
    """Why an unresolved candidate is not in the triage set, or None if it is."""
    sig = c.get("signal")
    st = status.get(sig, {}).get("status", "shadow")
    if st == "shadow":
        return "shadow"
    if sig in MEASURED_ASK and c.get("det", 1) < DETECTOR:
        return "stale"
    if kind_of(c) in muted:
        return "muted"
    if c.get("fp") and c["fp"] in seen_fp:
        return "seen"
    ev, ctx = c.get("evidence") or {}, c.get("context") or {}
    if sig == "S9-S11" and ev.get("kind") == "adr" and (ctx.get("repo"), ev.get("path")) in adr_paths:
        return "covered"      # the ADR script already raised S1 for this file
    return None


def _triage_pool(fold, mem_cfg, project, branch, repo):
    cands, muted = fold
    status = signal_status(repo, mem_cfg, cands)
    seen_fp = {c["fp"] for c in cands if c.get("fp") and c.get("resolution") in ("skipped", "stored")}
    adr_paths = {((c.get("context") or {}).get("repo"), (c.get("evidence") or {}).get("path"))
                 for c in cands if c.get("signal") == "S1"}
    items, counts = [], {}
    for c in cands:
        if c.get("resolution"):
            continue
        ctx = c.get("context") or {}
        if project is not None and ctx.get("repo") != project:
            continue
        if branch is not None and ctx.get("branch") != branch:
            continue
        why = _suppressed(c, status, muted, seen_fp, adr_paths)
        if why:
            counts[why] = counts.get(why, 0) + 1
        else:
            items.append(c)
    return items, counts, status


def untriaged(repo: Path, project=None, branch=None, mem_cfg=None, *, raw=False, fold=None) -> list:
    """Candidates a triage checkpoint should deal with, oldest first: unresolved, and not
    suppressed (a signal still in shadow, a detector older than the current one, a muted kind, a
    fingerprint already skipped or stored, an ADR the script already raised). Scoped to a project
    (context.repo) and optionally a branch, because one memory repo holds the spools of every
    project on the machine, so a checkpoint must only surface the work in front of the agent.
    `raw=True` is every unresolved candidate, suppressed or not."""
    fold = fold or _fold(repo)
    if raw:
        out = []
        for c in fold[0]:
            ctx = c.get("context") or {}
            if c.get("resolution") or (project is not None and ctx.get("repo") != project) \
                    or (branch is not None and ctx.get("branch") != branch):
                continue
            out.append(c)
        return out
    return _triage_pool(fold, mem_cfg, project, branch, repo)[0]


def auto_signals(mem_cfg: dict) -> set:
    """The signals this phase will auto-store. The configured memory.autoStore.signals, intersected
    with the signals Phase 1 actually implements (AUTO_SIGNALS). A config that also lists
    `explicit-remember` (S4) does not get it auto-stored here: its shadow precision was too low."""
    names = (mem_cfg.get("autoStore", {}) or {}).get("signals")
    if not isinstance(names, list):
        return set(AUTO_SIGNALS)
    want = {SIGNAL_BY_NAME.get(str(n), str(n)) for n in names}
    return {s for s in AUTO_SIGNALS if s in want}


def auto_budget(mem_cfg: dict) -> int:
    try:
        return max(0, int((mem_cfg.get("autoStore", {}) or {}).get("perSession", 5)))
    except (TypeError, ValueError):
        return 5


OPTIONS = (
    ("save", "Save it as proposed (the local tier, in my words)"),
    ("edit", "Save it, edited (you give the wording)"),
    ("skip", "Skip it (don't ask about the same thing again)"),
    ("never", "Never ask about this kind"),
)
# The category an accepted candidate is filed under unless the person says otherwise.
ASK_CATEGORY = {"S4": "convention", "S5": "convention", "S6": "mistake", "S8": "process",
                "S9-S11": "decision", "S12": "convention"}
_KIND_CATEGORY = {"friction": "process"}


def ask_category(c: dict) -> str:
    sub = (c.get("evidence") or {}).get("kind")
    return _KIND_CATEGORY.get(sub) or ASK_CATEGORY.get(c.get("signal"), "convention")


def ask_question(c: dict) -> str:
    """The one-line question for a candidate. It points at what was seen and quotes at most the
    person's own short words (S4, S5); it never carries tool output or a transcript."""
    sig, ev = c.get("signal"), c.get("evidence") or {}
    if sig in ("S4", "S5"):
        what = "asked me to remember something" if sig == "S4" else "corrected me"
        return f"You {what} (\"{ev.get('match', '')}\": \"{ev.get('excerpt', '')}\"). Is there a lesson to keep?"
    if sig == "S6":
        return (f"`{ev.get('head', '')}` failed (exit {ev.get('failed_exit')}) and then passed. "
                f"Is there a lesson in what changed?")
    if sig == "S8":
        return "A fresh-eyes investigation was needed (stuck twice). What should be remembered next time?"
    if sig == "S9-S11":
        sub = ev.get("kind") or "path"
        what = {"spec": "A spec was written", "friction": "A friction-log entry was written",
                "ledger": "The phase ledger was written", "adr": "An ADR file was written"}.get(
                    sub, "A watched file was written")
        return f"{what} ({ev.get('path', '')}). Is there a decision or lesson in it to keep?"
    if sig == "S12":
        ids = ", ".join(ev.get("lessons") or [])
        return f"You corrected me after lesson(s) {ids} were recalled. Should a new lesson replace one?"
    return f"{c.get('name', sig)}: is there a lesson to keep?"


def triage(repo: Path, mem_cfg: dict = None, *, project=None, branch=None) -> dict:
    """The triage plan for the untriaged candidates of one project: the rule table's outcome
    (spec §4.3) for each, `auto` for an auto signal within the per-session budget, else `ask`. This
    is read-only: it stores nothing. The lessons-triage skill reads it, writes the lesson text, and
    calls `capture --captured-by hook:<signal> --candidate <id>` for the auto ones (the engine then
    applies the Q2 refusals).

    `questions` is the one batched question set for the ask items: each has the four options of
    spec §4.3. `suppressed` counts what was left out and why (a signal still in shadow, a muted kind,
    a fingerprint already skipped) and `signals` says each signal's status, so a quiet checkpoint
    explains itself."""
    mem_cfg = mem_cfg or {}
    auto = auto_signals(mem_cfg)
    budget = auto_budget(mem_cfg)
    items, suppressed, status = _triage_pool(_fold(repo), mem_cfg, project, branch, repo)
    plan, questions, auto_count = [], [], 0
    for c in items:
        sig = c.get("signal")
        name, kind, _d = SIGNALS.get(sig, (c.get("name"), c.get("kind"), "ask"))
        if sig in auto and auto_count < budget:
            outcome, reason = "auto", f"{sig} auto-stores to the local tier (confirm the lesson text)"
            auto_count += 1
        elif sig in auto:
            outcome, reason = "ask", f"auto budget ({budget}) spent this triage — ask instead"
        else:
            outcome, reason = "ask", f"{sig} asks: {status.get(sig, {}).get('why', 'triage judges it')}"
        plan.append({"id": c["id"], "signal": sig, "name": name, "kind": kind, "outcome": outcome,
                     "reason": reason, "evidence": c.get("evidence") or {},
                     "context": c.get("context") or {}})
        if outcome == "ask":
            questions.append({"id": c["id"], "signal": sig, "kind": kind_of(c),
                              "category": ask_category(c), "question": ask_question(c),
                              "supersede": sig == "S12",
                              "options": [{"key": k, "label": lab} for k, lab in OPTIONS]})
    return {"project": project, "branch": branch, "budget": budget, "auto_signals": sorted(auto),
            "untriaged": len(items), "auto": auto_count, "ask": len(items) - auto_count,
            "items": plan, "questions": questions, "suppressed": suppressed,
            "signals": {s: v for s, v in status.items() if s in MEASURED_ASK}}


def render_questions(plan: dict) -> str:
    """The ask items as one numbered question set, for a host with no question tool. Each question
    is numbered, its options 1-4, and the person answers with the pair ("1.1 2.4"), any clear
    wording, or "skip all"."""
    qs = plan.get("questions") or []
    if not qs:
        return ""
    lines = [f"Lessons triage: {len(qs)} question(s). Answer with question.option (for example 1.1 2.3), "
             f"or any clear wording; \"skip all\" skips every one."]
    for n, q in enumerate(qs, 1):
        lines.append(f"{n}. [{q['signal']}] {q['question']}")
        lines += [f"   {n}.{i}  {o['label']}" for i, o in enumerate(q["options"], 1)]
    return "\n".join(lines)


def stats(repo: Path, days=None, current=False) -> dict:
    """Per signal: count, lesson, noise, unlabelled and precision (lesson / labelled, or None).
    `current` keeps only candidates from the current detectors, the ones a signal's status counts."""
    rows = candidates(repo)
    if current:
        rows = [c for c in rows if c.get("det", 1) >= DETECTOR]
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


def _rotate(d: Path, log: Path):
    """Keep a full log as decisions.1.jsonl. Two runs past the limit must not both rotate, or the
    second moves a near-empty log over the one just kept. So the size is checked again under a
    lock, and a run that can't get the lock leaves the rotation to the next run, without waiting."""
    try:
        if log.stat().st_size <= DECISION_LOG_MAX:
            return
        fd = os.open(str(d / ROTATE_LOCK), os.O_RDWR | os.O_CREAT, 0o666)
    except OSError:
        return
    try:
        if core._try_os_lock(fd):
            try:
                if log.stat().st_size > DECISION_LOG_MAX:
                    os.replace(str(log), str(d / "decisions.1.jsonl"))
            finally:
                core._os_unlock(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def log_decision(repo: Path, rec: dict):
    d = ensure_capture_dir(repo)
    log = d / DECISIONS
    _rotate(d, log)
    _append(log, rec)


def decisions(repo: Path) -> list:
    d = capture_dir(repo)
    return _read(d / "decisions.1.jsonl") + _read(d / DECISIONS)


def doctor(repo: Path, last: int = 10, mem_cfg: dict = None) -> dict:
    """What the capture hooks have been doing: the last decisions, counts, and spool health.
    `untriaged` is what a checkpoint would deal with (every project); `unresolved` also counts the
    candidates of signals still in shadow, which no checkpoint asks about."""
    log = decisions(repo)
    fold = _fold(repo)
    cands = fold[0]
    status = signal_status(repo, mem_cfg, cands)
    contended = sum(1 for r in log + cands if r.get("contended"))
    by_decision, last_by_mode, slowest = {}, {}, None
    for r in log:
        by_decision[r.get("decision", "?")] = by_decision.get(r.get("decision", "?"), 0) + 1
        last_by_mode[r.get("mode", "?")] = r.get("ts")
        if isinstance(r.get("ms"), (int, float)) and (slowest is None or r["ms"] > slowest["ms"]):
            slowest = {"ms": r["ms"], "mode": r.get("mode"), "ts": r.get("ts")}
    return {"dir": str(capture_dir(repo)), "exists": capture_dir(repo).is_dir(),
            "self_ignored": is_self_ignored(repo), "candidates": len(cands),
            "pending": sum(1 for c in cands if not c.get("verdict")),
            "untriaged": len(untriaged(repo, mem_cfg=mem_cfg, fold=fold)),
            "unresolved": sum(1 for c in cands if not c.get("resolution")),
            "signals": {s: v for s, v in status.items() if v["status"] != "shadow" or s in MEASURED_ASK},
            "decisions": len(log), "by_decision": by_decision, "last_by_mode": last_by_mode,
            "slowest": slowest, "contended": contended, "recent": log[-last:] if last else []}


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


def failure_text(ev: dict) -> str:
    """The text a host gives for a failed tool call, used only to classify the failure (a parse or
    quoting error) and never stored."""
    tr = ev.get("toolResult", ev.get("tool_result"))
    tr = _obj(tr) if isinstance(tr, (dict, str)) else {}
    return str(ev.get("error") or tr.get("textResultForLlm") or tr.get("text_result_for_llm") or "")[:2000]


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
    """[(signal, matched phrase, excerpt)] for S4 and S5, at most one each. The shape rules are in
    `detect`; whether the prompt is a brief is the caller's question (`detect.looks_like_brief`)."""
    out = []
    for sig, find in (("S4", detect.s4_matches), ("S5", detect.s5_matches)):
        hits = find(prompt or "")
        if hits:
            phrase, start, end = hits[0]
            out.append((sig, phrase.strip(), excerpt(prompt, start, end)))
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


def capture_mode(mem_cfg: dict, env=None) -> str:
    """'off' | 'shadow' | 'active'. Default 'shadow' (Phase 0: record, print nothing, block nothing).
    'active' turns on Phase 1's visible behaviour — the session-start recall digest and the stop
    triage block. It is opt-in, via the project config's memory.mode or MNEMOSYNE_CAPTURE_MODE, so
    upgrading the package never changes a machine's behaviour until the config asks for it."""
    env = os.environ if env is None else env
    if not capture_enabled(mem_cfg, env):
        return "off"
    m = str(env.get("MNEMOSYNE_CAPTURE_MODE", "") or mem_cfg.get("mode", "") or "shadow").strip().lower()
    return "active" if m == "active" else "shadow"


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


# ----------------------------------------------------------------------------- recalled lessons (S12)

_RECALLED_ID = re.compile(r"^- ([A-Z]{1,6}-\d+)\s+\[", re.M)


def digest_ids(digest: str) -> list:
    """The lesson ids a recall digest listed (its `- L-0001 [category/...] title` lines)."""
    return _RECALLED_ID.findall(digest or "")


def note_recall(repo: Path, session: str, ids) -> None:
    """Remember which lessons recall printed in `session`, so a later correction in the same session
    can raise S12. A small state file beside the spool, like the S6 failures; fail-open."""
    if not session or not ids:
        return
    try:
        path = capture_dir(repo) / RECALLED
        try:
            st = json.loads(path.read_text(encoding="utf-8"))
            st = st if isinstance(st, dict) else {}
        except (OSError, ValueError):
            st = {}
        now = time.time()
        st = {s: v for s, v in st.items() if now - v.get("t", 0) < RECALL_TTL}
        seen = list(dict.fromkeys((st.get(session) or {}).get("ids", []) + list(ids)))[-20:]
        st[session] = {"ids": seen, "t": now}
        core.atomic_write_text(ensure_capture_dir(repo) / RECALLED, json.dumps(dict(list(st.items())[-30:])))
    except OSError:
        pass


def recalled_in(repo: Path, session: str) -> list:
    try:
        st = json.loads((capture_dir(repo) / RECALLED).read_text(encoding="utf-8"))
        v = st.get(session) or {}
        return list(v.get("ids", [])) if time.time() - v.get("t", 0) < RECALL_TTL else []
    except (OSError, ValueError, AttributeError):
        return []


# ----------------------------------------------------------------------------- watched paths (S9-S11)

# kind -> the default path it watches. A kind names what a write there means: a spec (an As built
# deviation, S9), a friction-log entry with a workaround (S10), the phase ledger (flag-or-fix and
# other outcomes, S11), an ADR written by hand.
DEFAULT_WATCH_KINDS = {"adr": "docs/adr/", "spec": "docs/specs/", "friction": "docs/friction-log.md"}
DEFAULT_WATCH = list(DEFAULT_WATCH_KINDS.values())
SUBSIGNAL = {"spec": "S9", "adr": "S9", "friction": "S10", "ledger": "S11"}


def _kind_of_path(path: str) -> str:
    low = path.casefold()
    for kind in ("friction", "ledger", "adr", "spec"):
        if kind in low:
            return kind
    return "ledger" if "progress" in low else "path"


def _first_config(root: Path, names) -> dict:
    for name in names:
        p = Path(os.environ.get("ZETHUS_CONFIG", "")) if name == "$ZETHUS_CONFIG" else root / name
        if name == "$ZETHUS_CONFIG" and not os.environ.get("ZETHUS_CONFIG"):
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict):
            return doc
    return {}


def _dir(path: str) -> str:
    p = str(path).replace("\\", "/").strip()
    return p if not p or p.endswith("/") or "." in p.rsplit("/", 1)[-1] else p + "/"


def watch_entries(root: Path, mem_cfg: dict) -> list:
    """[(pattern, kind)] of the paths whose writes become S9-S11 candidates (spec §4.2).

    `memory.watch`, when the project sets it, is the whole list (each entry a path or glob, or
    {"path", "kind"}). Otherwise the list comes from the project's own config, so a kit's watched
    paths are the keys it already has: Zethus's `spec.dir` and `adr.dir`, Amphion's
    `frictionLog.markdown.path` and `ledger.path`. Any kind the config doesn't name falls back to
    its DEFAULT_WATCH_KINDS path, so a bare repo still watches the conventional places."""
    explicit = mem_cfg.get("watch")
    if isinstance(explicit, list):
        out = []
        for w in explicit:
            if isinstance(w, dict) and w.get("path"):
                out.append((_dir(w["path"]), str(w.get("kind") or _kind_of_path(str(w["path"])))))
            elif isinstance(w, str):
                out.append((_dir(w), _kind_of_path(w)))
        return out
    found = {}
    zethus = _first_config(root, PROJECT_CONFIGS[:3])
    amphion = _first_config(root, PROJECT_CONFIGS[3:])
    for kind, key in (("spec", "spec"), ("adr", "adr")):
        d = (zethus.get(key) or {}).get("dir") if isinstance(zethus.get(key), dict) else None
        if d:
            found[kind] = _dir(d)
    fl = amphion.get("frictionLog") if isinstance(amphion.get("frictionLog"), dict) else {}
    md = fl.get("markdown") if isinstance(fl.get("markdown"), dict) else {}
    if md.get("path") and fl.get("sink", "markdown") == "markdown":
        found["friction"] = _dir(md["path"])
    led = amphion.get("ledger") if isinstance(amphion.get("ledger"), dict) else {}
    if led.get("path"):
        found["ledger"] = _dir(led["path"])
    for kind, default in DEFAULT_WATCH_KINDS.items():
        found.setdefault(kind, default)
    return [(path, kind) for kind, path in found.items()]


def claim_once(repo: Path, bucket: str, key: str) -> bool:
    """True the first time `key` is seen in `bucket`, False after. A marker file holding no text.
    Fails open (True), so an unwritable spool costs a repeat candidate, never a lost one."""
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
    try:
        d = ensure_capture_dir(repo) / bucket
        d.mkdir(exist_ok=True)
        os.close(os.open(str(d / digest), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        return False
    except OSError:
        pass
    return True


# ----------------------------------------------------------------------------- Zethus-script signals
# S1 and S2 do not come from a lifecycle hook: Zethus's own scripts call these after they act, so
# the signal reaches the agent on every host (spec §4.7 channel 1). Both are fail-open: a script
# imports mnemosyne only if it is installed and does nothing otherwise, so Zethus stays stdlib-only.


def _spool_for(root: Path, env):
    """(repo, mem_cfg) if a script may record here, else (None, {}): capture on and a memory repo."""
    repo = spool_repo(Path(root), env)
    mem_cfg = project_memory_config(Path(root))
    if repo is None or not capture_enabled(mem_cfg, env):
        return None, {}
    return repo, mem_cfg


def record_adr(root, adr_id, path="", *, env=None):
    """Zethus's new-adr.py calls this after writing an ADR: append one S1 (decision) candidate.
    Pointers only (the id and a scrubbed repo-relative path), never the ADR's text."""
    env = os.environ if env is None else env
    repo, _ = _spool_for(root, env)
    if repo is None:
        return None
    ev = {"adr": str(adr_id)}
    if path:
        ev["path"] = core.scrub_machine_paths(str(path))
    return add_candidate(repo, "S1", host="zethus-script", event="new-adr",
                         context=project_context(Path(root)), evidence=ev)


def _load_gates(repo: Path) -> dict:
    try:
        g = json.loads((capture_dir(repo) / GATES).read_text(encoding="utf-8"))
        return g if isinstance(g, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_gates(repo: Path, state: dict):
    now = time.time()
    state = {k: {n: s for n, s in gates.items() if now - s.get("t", 0) < GATE_TTL}
             for k, gates in state.items()}
    state = {k: gates for k, gates in state.items() if gates}
    core.atomic_write_text(ensure_capture_dir(repo) / GATES, json.dumps(state))


def record_gate_results(root, results, *, env=None):
    """Zethus's run-local-gates.py calls this with [(gate_name, status), ...] after a run. Emit one
    S2 (mistake) candidate for each gate that FAILED on an earlier run within this branch and now
    PASSES (spec §4.2 S2). The per-branch last status of each gate lives in the spool (gitignored),
    keyed by the git toplevel plus the branch, so "within a phase" is scoped by the branch."""
    env = os.environ if env is None else env
    repo, _ = _spool_for(root, env)
    if repo is None:
        return []
    ctx = project_context(Path(root))
    top, _gd = _git_dir(Path(root))
    key = os.path.normcase(str(top or root)) + "@" + str(ctx.get("branch", ""))
    state = _load_gates(repo)
    gates = state.setdefault(key, {})
    out, now = [], time.time()
    for name, status in results or []:
        st = str(status or "").upper()
        if st not in ("PASS", "FAIL"):
            continue
        prev = gates.get(name) or {}
        if st == "PASS" and prev.get("status") == "fail" and now - prev.get("t", 0) < GATE_TTL:
            out.append(add_candidate(repo, "S2", host="zethus-script", event="run-local-gates",
                                     context=ctx,
                                     evidence={"gate": str(name), "failed_at": prev.get("ts")}))
        gates[name] = {"status": st.lower(), "t": now, "ts": _now()}
    _save_gates(repo, state)
    return out


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


# ----------------------------------------------------------------------------- instruction candidate guard


def instruction_repeat(repo: Path, root: Path, session: str, prompt: str, sig: str = "S4"):
    """Suppress only an identical instruction line (S4, or S5 with `sig`), never an arbitrary excerpt.

    Own-repo standing files are authoritative even in a new session. Otherwise a host-provided
    session id scopes an exclusive content marker. Missing ids and IO errors fail open. Markers
    contain only hashes, not instruction text; they are separate from expiring event claims.
    This suppresses candidates only: the bridge's duplicate-event recall contract stays intact.
    A standing rule that arrives inside a brief never gets this far (`detect.looks_like_brief`).
    """
    hits = (detect.s4_matches if sig == "S4" else detect.s5_matches)(prompt)
    if not hits:
        return None
    match_start, match_end = hits[0][1], hits[0][2]
    start = prompt.rfind("\n", 0, match_start) + 1
    end = prompt.find("\n", match_end)
    instruction = " ".join(prompt[start:end if end >= 0 else len(prompt)].split()).casefold()
    top, _ = _git_dir(root)
    project = top or root
    for name in ("AGENTS.md", "CLAUDE.md", ".github/copilot-instructions.md"):
        try:
            path = project / name
            if path.stat().st_size > 262144:
                continue
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        if any(" ".join(line.split()).casefold() == instruction for line in lines):
            return "instruction already present in this repo's standing instructions"
    if not session:
        return None
    parts = [os.path.normcase(str(project.resolve())), session, instruction] + ([sig] if sig != "S4" else [])
    key = hashlib.sha256(json.dumps(parts).encode("utf-8")).hexdigest()
    try:
        directory = ensure_capture_dir(repo) / "instructions"
        directory.mkdir(exist_ok=True)
    except OSError:
        return None
    try:
        os.close(os.open(str(directory / key), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        return "instruction already candidated in this session and repo"
    except OSError:
        pass
    return None


# ----------------------------------------------------------------------------- the hook entry


def capture_event(mode: str, ev: dict, *, host=None, env=None, root=None):
    """Run one capture hook invocation. Returns the decision record it logged, or None if capture is
    off or there is no memory repo to record into. Never stores a lesson and never asks: it records
    candidates and decides whether `stop` should block for a triage. What reaches the model (a
    session-start digest, the stop block's reason) is the bridge's to print, and only in active mode."""
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
    mode_str = capture_mode(mem_cfg, env)  # shadow (record only) vs active (Phase 1 may block)
    event = str(ev.get("hook_event_name") or mode)
    rec = {"ts": _now(), "mode": mode, "host": host, "event": event, "session": session,
           "context": ctx, "decision": "no-signal", "signals": [], "candidates": []}

    if mode in MODES and not first_fire(repo, mode, ev, root):
        rec.update(decision=DUPLICATE, detail="another registration already handled this event",
                   ms=round((time.perf_counter() - t0) * 1000, 2))
        log_decision(repo, rec)
        return rec

    def add(signal, evidence, fp_key=None):
        c = add_candidate(repo, signal, host=host, event=event, session=session, context=ctx,
                          evidence=evidence, fp_key=fp_key)
        rec["signals"].append(signal)
        rec["candidates"].append(c["id"])
        rec["decision"] = "candidate"
        return c

    if mode == "prompt":
        prompt = str(ev.get("prompt") or "")
        hits = prompt_signals(prompt)
        shape = core.find_secret(prompt) if hits else None
        if shape:
            rec.update(decision="dropped", detail=f"credential shape ({shape}); nothing recorded",
                       signals=[h[0] for h in hits])
        elif hits and detect.looks_like_brief(prompt):
            # A task brief, a pasted document or a quoted instruction file: its imperatives are the
            # brief's, not a person teaching the agent something (spec §5.1, §5.2).
            rec.update(decision="brief", detail="a brief or pasted document, not a direct instruction; "
                       "nothing recorded", signals=[h[0] for h in hits])
        else:
            for sig, phrase, snip in hits:
                repeat = instruction_repeat(repo, root, session, prompt, sig)
                if repeat:
                    # Do not return DUPLICATE: that label also suppresses auto-recall in the bridge.
                    rec.update(decision="duplicate-instruction", detail=repeat)
                    rec["signals"].append(sig)
                    continue
                find = detect.s4_matches if sig == "S4" else detect.s5_matches
                clause = detect.standing_clause(prompt, find(prompt)[0][1])
                c = add(sig, {"match": phrase, "excerpt": snip}, fp_key=clause)
                recalled = recalled_in(repo, session) if sig == "S5" else []
                if recalled:
                    # S12: the user corrected the agent in a session that had recalled lessons.
                    add("S12", {"lessons": recalled[:5], "correction": c["id"]},
                        fp_key=",".join(sorted(recalled[:5])))

    elif mode == "post-tool":
        name = tool_name(ev)
        if is_fresh_eyes(ev):
            add("S8", {"tool": name, "skill": "fresh-eyes-investigation"})
        paths = written_paths(ev)
        entries = watch_entries(root, mem_cfg) if paths else []   # config files are read only for a write
        for path in paths:
            rel = relative_to(path, str(root))
            hit = next(((w, k) for w, k in entries if watch_match(rel, [w])), None) if rel else None
            if not hit:
                continue
            shown = core.scrub_machine_paths(rel)
            if claim_once(repo, WATCHED, f"{session or root}|{shown}"):   # a path is one candidate a session
                add("S9-S11", {"tool": name, "path": shown, "watch": hit[0], "kind": hit[1],
                               "sub": SUBSIGNAL.get(hit[1], "S9")}, fp_key=shown)
            elif rec["decision"] == "no-signal":
                rec.update(decision="watched-repeat", detail="this path already raised a candidate this session")
        if name.lower() in _SHELL_TOOLS:
            cmd = str(tool_input(ev).get("command") or "")
            head = command_head(cmd)
            outcome, code = tool_outcome(ev)
            if head and core.find_secret(head):
                head = ""
            head = core.scrub_machine_paths(head)
            st = _load_state(repo) if head and outcome else {}
            fails = st.get(session, [])
            digest = hashlib.sha256(cmd.encode("utf-8")).hexdigest()[:12]
            if outcome == "failure" and head:
                why = detect.s6_exclusion(head, code, cmd, failure_text(ev))
                if why:
                    # Not a lesson however it ends: a watchdog kill, navigation or a plain read, a
                    # heredoc or quoting retry. It is never tracked, so its success never pairs up.
                    if rec["decision"] == "no-signal":
                        rec.update(decision="excluded-failure", detail=f"S6 not tracked: {why}")
                else:
                    fails.append({"head": head, "exit": code, "t": time.time(), "ts": _now(), "cmd": digest})
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
                    if match.get("cmd") and match["cmd"] == digest:
                        # The same command, run again, passed: a flake or a transient, not a lesson.
                        if rec["decision"] == "no-signal":
                            rec.update(decision="excluded-retry", detail="S6 not recorded: unchanged re-run")
                    else:
                        add("S6", {"tool": name, "head": head, "failed_exit": match.get("exit"),
                                   "failed_at": match.get("ts")}, fp_key=head)
            elif outcome is None and rec["decision"] == "no-signal":
                rec["detail"] = "the host reports no tool outcome; S6 can't be seen here"

    elif mode in ("stop", "pre-compact", "session-start"):
        fold = _fold(repo)
        pending = [c for c in fold[0] if not c.get("verdict")]
        mine = [c for c in pending if session and c.get("session") == session]
        # The triage checkpoint is scoped to the project (one memory repo holds every project's
        # spool), and counts untriaged candidates — which includes the script-emitted S1/S2 that
        # carry no host session, so session-scoping alone would miss them.
        untr = untriaged(repo, project=ctx.get("repo"), branch=ctx.get("branch"), mem_cfg=mem_cfg, fold=fold)
        rec.update(pending=len(pending), pending_session=len(mine), untriaged=len(untr))
        if mode == "stop":
            rec["stop_hook_active"] = bool(ev.get("stop_hook_active"))
            if untr and mode_str == "active" and not ev.get("stop_hook_active"):
                # Phase 1: block once (the re-fire carries stop_hook_active) to force a triage.
                rec.update(decision="block",
                           detail=f"{len(untr)} candidate(s) await triage in {ctx.get('repo')}")
            elif untr:
                rec.update(decision="would-block",
                           detail=f"{len(untr)} candidate(s) await triage in {ctx.get('repo')}; "
                                  + ("already re-fired after a block" if ev.get("stop_hook_active")
                                     else "shadow mode never blocks"))
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

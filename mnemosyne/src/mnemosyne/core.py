"""Mnemosyne reflexion memory — the engine (stdlib only).

Git is the store and the distribution mechanism; this module is the brain. It implements
the Reflexion loop (Shinn et al., 2023): recall durable lessons into new work, and reflect
feedback into new lessons so the same miss never happens twice.

Everything domain-specific (the recall axes, weights, vocabulary, lifecycle stages) is read
from a `Config` (see config.py). The functions here take a `cfg` and a repo `Path` and return
structured results; all human/JSON formatting lives in cli.py, so the same logic backs the
CLI, the MCP server, and the importable API.

TIERS
  local   memory/local.jsonl     gitignored, per-developer, instant capture (promote -> PR -> shared)
  shared  memory/lessons.jsonl   committed, PR-reviewed, team-wide truth (the distribution channel)
  stores  broader shared repos declared in config.stores (e.g. team/enterprise) — federated in at
          recall time and written up to via `export`/`promote --to`. See stores.py.

SOURCE OF TRUTH = the JSONL. memory/LESSONS.md is a generated human view (regenerated on write).

DURABILITY  every rewrite of a store file goes through atomic_write_text: a temp file in the same
          directory, fsynced, then os.replace'd over the original. A crash mid-save leaves the old
          file intact (plus at worst a stray `.<name>.*.tmp`), never a truncated store.
LOCKING   every read-modify-write of a repo's store files runs under store_lock(repo), an OS lock
          on memory/.store.lock, so two processes saving at once serialise instead of one losing
          the other's update. The OS drops the lock when its holder dies, so a crash never wedges it.
"""
from __future__ import annotations

import datetime as _dt
import errno
import fnmatch
import json
import os
import re
import secrets
import stat
import subprocess
import tempfile
import threading
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path

from .config import BUNDLED_DIR, Config

# ----------------------------------------------------------------------------- errors


class EngineError(Exception):
    """A user-facing error (bad input, missing lesson, etc.). CLI maps to exit 2."""

    def __init__(self, message: str, code: int = 2):
        super().__init__(message)
        self.code = code


class LowValueError(EngineError):
    """Refused to bank a missing-deliverable / transient failure. CLI maps to exit 3."""

    def __init__(self, matched: str):
        super().__init__(
            f"this reads as a missing-deliverable / transient failure (matched: '{matched}'). "
            f"That's a process retry, not a durable lesson — re-run the stage instead. "
            f"Use force=true if it really is a reusable lesson.",
            code=3,
        )
        self.matched = matched


class LockTimeout(EngineError):
    """Another process held a store lock for longer than the bounded wait. CLI maps to exit 4."""

    def __init__(self, path, waited: float, holder: dict):
        who = f"pid {holder['pid']}" if holder.get("pid") else "another process"
        since = f" since {holder['since']}" if holder.get("since") else ""
        super().__init__(
            f"timed out after {waited:g}s waiting for the store lock {path} (last taken by {who}{since}). "
            f"Another mnemosyne write is still running: retry, or raise MNEMOSYNE_LOCK_TIMEOUT.",
            code=4,
        )
        self.path = str(path)
        self.holder = holder


# ----------------------------------------------------------------------------- hygiene constants
# These are domain-neutral, so they stay in code rather than config.

# (A) missing-deliverable / transient-failure guard — process retries, not durable lessons.
_DELIVERABLE = (r"(deliverable|artifact|file|output|report|document|doc|spec|pr|pull request|"
                r"commit|branch|test|testcase|fixture|scaffold|stub|diagram|screenshot|build)")
LOW_VALUE_FAILURE_RE = re.compile("|".join([
    rf"\b{_DELIVERABLE}s?\b[^.]{{0,40}}\b(missing|absent|empty|not found|not present|never (created|written|produced|generated|run))",
    rf"\b(missing|no|empty|absent)\s+{_DELIVERABLE}",
    r"\b(did ?n'?t|didn'?t|did not|was ?n'?t|wasn'?t|were ?n'?t|is ?n'?t|are ?n'?t|failed to|forgot to|never|not yet|not)\s+(been\s+)?(create[ds]?|writ(e|ten)|wrote|produce[ds]?|generate[ds]?|run|ran|save[ds]?|commit(ted)?|push(ed)?|scaffold(ed)?)\b",
    r"\bno output\b", r"\bproduced nothing\b", r"\bempty (output|result|response|file)\b",
    r"\btimed?\s*out\b", r"\btimeout\b", r"\bflak(e|y)\b", r"\btransient\b",
    r"\b(re-?run|retry|rerun)\b[^.]{0,20}(fixed|worked|passed|succeeded|resolved)",
    r"\benvironment(al)?\s+(issue|error|problem|failure|flake|glitch)", r"\bmount\b", r"\btruncat",
    r"\bnetwork\s+(error|issue|blip|timeout|glitch)", r"\brate.?limit", r"\bconnection\s+(refused|reset|timed?\s*out)",
    r"\bskipped a step\b", r"\bstub (left|remained|not filled|wasn'?t filled)",
]), re.I)

# (B) dedup token stoplist for title+lesson Jaccard.
_DEDUP_STOP = set((
    "the a an of to for and or in on at is are be by with from as it this that you we our your they do "
    "does did not no none new use used using next time always must should when where which what if then so"
).split())

USAGE_SIDECAR = "usage.local.json"


# ----------------------------------------------------------------------------- small helpers


def today() -> str:
    return _dt.date.today().isoformat()


def csv(val):
    if not val:
        return []
    if isinstance(val, list):
        return [str(v).strip() for v in val if str(v).strip()]
    return [v.strip() for v in str(val).split(",") if v.strip()]


def _tokens(text: str):
    return set(re.findall(r"[a-z0-9][a-z0-9\-]+", (text or "").lower()))


def resolve_repo(arg_repo=None) -> Path:
    cand = arg_repo or os.environ.get("MNEMOSYNE_REPO") or str(Path.cwd())
    repo = Path(cand).expanduser().resolve()
    if not (repo / "memory").is_dir():
        raise EngineError(
            f"no memory/ under {repo} — pass repo=, set MNEMOSYNE_REPO, or run from a memory repo "
            f"(mnemosyne init creates one)")
    return repo


def shared_path(repo: Path) -> Path:
    return repo / "memory" / "lessons.jsonl"


def local_path(repo: Path) -> Path:
    return repo / "memory" / "local.jsonl"


def usage_path(repo: Path) -> Path:
    return repo / "memory" / USAGE_SIDECAR


def read_jsonl(p: Path):
    out = []
    if not p.exists():
        return out
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise EngineError(f"{p.name}:{i} invalid JSON: {e}")
    return out


_REPLACE_RETRIES = 5


def _fsync_dir(d: Path):
    """Persist a rename on POSIX by fsyncing its directory. Windows has no directory handle to sync."""
    if os.name == "nt":
        return
    try:
        fd = os.open(str(d), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_text(p: Path, text: str):
    """Replace `p` with `text` so a crash leaves the old file or the new one, never a torn mix.

    Writes a temp file beside `p` (os.replace is only atomic within one filesystem), fsyncs it,
    keeps `p`'s permission bits, then swaps it in. On any failure the temp file is removed and `p`
    is untouched. On Windows a reader holding `p` open briefly blocks the swap, so the replace is
    retried a few times before giving up."""
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.chmod(str(tmp), stat.S_IMODE(p.stat().st_mode))
        except OSError:
            pass  # no existing file (keep the umask default) or a filesystem without modes
        for attempt in range(_REPLACE_RETRIES):
            try:
                os.replace(str(tmp), str(p))
                break
            except PermissionError:
                if os.name != "nt" or attempt == _REPLACE_RETRIES - 1:
                    raise
                time.sleep(0.05 * (attempt + 1))
    except BaseException:
        try:
            os.unlink(str(tmp))
        except OSError:
            pass
        raise
    _fsync_dir(p.parent)


def write_jsonl(p: Path, lessons):
    lessons = sorted(lessons, key=lambda l: l.get("id", ""))
    atomic_write_text(p, "".join(
        json.dumps(l, ensure_ascii=False, separators=(",", ":")) + "\n" for l in lessons))


# ----------------------------------------------------------------------------- store lock
# Atomic writes stop a torn file; they don't stop two writers each reading the store, adding a
# lesson and replacing it, so the second replace drops the first one's lesson. store_lock
# serialises that read-modify-write per repo. It is a kernel lock (flock on POSIX, msvcrt byte-range
# lock on Windows) on memory/.store.lock rather than "the lockfile exists": the OS releases it when
# the holder exits or crashes, so there is no stale-lock cleanup to race over. The lockfile is never
# deleted (deleting it would let two processes lock two different inodes) and records the last
# holder's pid only for the timeout message.

LOCK_NAME = ".store.lock"
LOCK_TIMEOUT = 10.0  # seconds; MNEMOSYNE_LOCK_TIMEOUT overrides
_LOCK_POLL = 0.02
_WIN_LOCK_OFFSET = 1 << 30  # lock a byte far past the holder record so readers can still see it

_held = {}            # lock path -> [fd, depth]: re-entry by the holding thread doesn't re-lock
_thread_locks = {}    # lock path -> RLock: threads in one process take turns before the OS lock
_registry = threading.Lock()

if os.name == "nt":
    import msvcrt

    def _try_os_lock(fd) -> bool:
        os.lseek(fd, _WIN_LOCK_OFFSET, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as e:
            if e.errno in (errno.EACCES, errno.EDEADLOCK):
                return False
            raise
        return True

    def _os_unlock(fd):
        os.lseek(fd, _WIN_LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _try_os_lock(fd) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES):
                return False
            raise
        return True

    def _os_unlock(fd):
        fcntl.flock(fd, fcntl.LOCK_UN)


def lock_path(repo: Path) -> Path:
    return Path(repo).resolve() / "memory" / LOCK_NAME


def _lock_timeout() -> float:
    try:
        return max(0.0, float(os.environ.get("MNEMOSYNE_LOCK_TIMEOUT", LOCK_TIMEOUT)))
    except ValueError:
        return LOCK_TIMEOUT


def lock_holder(path) -> dict:
    """The holder record ({"pid", "since"}) last written into a lockfile, or {} if unreadable."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {}


def _os_lock(path: str, timeout: float) -> int:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o666)
    try:
        deadline = time.monotonic() + timeout
        while not _try_os_lock(fd):
            if time.monotonic() >= deadline:
                raise LockTimeout(path, timeout, lock_holder(path))
            time.sleep(_LOCK_POLL)
        rec = json.dumps({"pid": os.getpid(), "since": _dt.datetime.now().isoformat(timespec="seconds")})
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, rec.encode("utf-8"))
    except BaseException:
        os.close(fd)
        raise
    return fd


@contextmanager
def _lock_one(path: str, timeout: float):
    with _registry:
        tl = _thread_locks.setdefault(path, threading.RLock())
    if not tl.acquire(timeout=timeout):
        raise LockTimeout(path, timeout, lock_holder(path))
    try:
        held = _held.get(path)
        if held:
            held[1] += 1
        else:
            held = _held[path] = [_os_lock(path, timeout), 1]
        try:
            yield
        finally:
            held[1] -= 1
            if not held[1]:
                del _held[path]
                try:
                    _os_unlock(held[0])
                finally:
                    os.close(held[0])
    finally:
        tl.release()


@contextmanager
def store_lock(*repos, timeout=None):
    """Hold the write lock of each repo's store for the duration of a read-modify-write.

    Waits up to `timeout` seconds (default MNEMOSYNE_LOCK_TIMEOUT, else LOCK_TIMEOUT) per lock, then
    raises LockTimeout. Re-entrant: an engine call that already holds a repo's lock can call another
    that takes it again. Several repos are locked in sorted path order, so two writers spanning the
    same repos can't each hold one and wait on the other."""
    timeout = _lock_timeout() if timeout is None else timeout
    with ExitStack() as stack:
        for path in sorted({str(lock_path(r)) for r in repos}):
            stack.enter_context(_lock_one(path, timeout))
        yield


def load_all(repo: Path):
    """Return (lessons, tier_by_id). Shared shadows local on id collision.

    The one legitimate overlap is a promoted lesson: its local copy is kept until the review PR
    merges, then retired. The reviewed shared record is the authority, so it wins; an overlap that
    isn't a promoted copy is an id collision, which `validate` reports."""
    shared = read_jsonl(shared_path(repo))
    local = read_jsonl(local_path(repo))
    tier = {}
    by_id = {}
    for l in local:
        by_id[l["id"]] = l
        tier[l["id"]] = "local"
    for l in shared:
        by_id[l["id"]] = l
        tier[l["id"]] = "shared"
    return list(by_id.values()), tier


def load_federated(cfg: Config, repo: Path, *, pull_remotes=False, notes=None):
    """Return (lessons, tier, origin, source_repo) across the primary repo + all configured stores.

    Thin wrapper over stores.federated_load (imported lazily to avoid a top-level import cycle).
    With no stores configured this is load_all plus trivial origin/source maps, so every
    store-aware caller degenerates to today's two-tier behavior."""
    from . import stores
    return stores.federated_load(cfg, repo, pull_remotes=pull_remotes, notes=notes)


def next_id(cfg: Config, lessons, prefix=None, taken=()) -> str:
    """The next `<prefix>-NNNN` above every id in `lessons` and in `taken` (ids seen elsewhere,
    e.g. on review branches or the merged default branch; see committed_lessons)."""
    prefix = prefix or cfg.id_prefix
    mx = 0
    pat = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
    for lid in [l.get("id", "") for l in lessons] + list(taken):
        m = pat.match(lid or "")
        if m:
            mx = max(mx, int(m.group(1)))
    return f"{prefix}-{mx + 1:04d}"


def git(repo: Path, *args, check=False, env=None):
    """Run git in `repo`; return (returncode, stdout, stderr), stripped.

    stdin is always DEVNULL. Under the MCP server our own stdin is the JSON-RPC channel, and a git
    child that inherits it holds that channel so, on Windows, the tool's reply never arrives."""
    run_env = None
    if env:
        run_env = dict(os.environ)
        run_env.update(env)
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, env=run_env)
    except FileNotFoundError:
        return 127, "", "git not found"
    if check and r.returncode != 0:
        raise EngineError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def git_sha(repo: Path) -> str:
    code, out, _ = git(repo, "rev-parse", "--short", "HEAD")
    return out if code == 0 else "no-git"


def banner(repo: Path) -> str:
    return f"reflexion memory @ {repo.name} ({git_sha(repo)})"


# ----------------------------------------------------------------------------- committed tiers
# A memory repo's shared tier exists in more places than its working tree: on the default branch
# (where merged reviews land) and on every review branch. Ids must be unique across all of them,
# and "merged" means "on the default branch", so these read lessons straight out of git.

_REVIEW_BRANCH = "reflexion/"


def is_git_repo(repo: Path) -> bool:
    return git(repo, "rev-parse", "--is-inside-work-tree")[0] == 0


def default_ref(repo: Path, branch=None):
    """The ref holding the repo's merged shared tier: origin's `branch` if given, else origin/HEAD,
    else HEAD (unless HEAD is a review branch). None outside git or before the first commit."""
    cands = [f"refs/remotes/origin/{branch}", branch] if branch else []
    cands.append("refs/remotes/origin/HEAD")
    if not git(repo, "branch", "--show-current")[1].startswith(_REVIEW_BRANCH):
        cands.append("HEAD")
    for ref in cands:
        if git(repo, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}")[0] == 0:
            return ref
    return None


def lessons_at(repo: Path, ref) -> list:
    """The shared tier as committed at `ref` (`[]` if absent). Unparseable lines are skipped."""
    code, out, _ = git(repo, "show", f"{ref}:./memory/lessons.jsonl")
    rows = []
    if code == 0:
        for line in out.splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def _id_refs(repo: Path) -> list:
    """HEAD, the remote default branches and every local or remote review branch."""
    code, out, _ = git(repo, "for-each-ref", "--format=%(refname)",
                       f"refs/heads/{_REVIEW_BRANCH}", "refs/remotes/")
    refs = ["HEAD"]
    for ref in out.splitlines() if code == 0 else []:
        tail = ref.split("/", 3)[-1] if ref.startswith("refs/remotes/") else ""
        if ref.startswith("refs/heads/") or tail.startswith(_REVIEW_BRANCH) or tail == "HEAD":
            refs.append(ref)
    return refs


def committed_lessons(repo: Path) -> dict:
    """{id: lesson} across every committed copy of the shared tier: HEAD, the remote default
    branches and all review branches (first seen wins). `{}` outside git."""
    if not is_git_repo(repo):
        return {}
    out = {}
    for ref in _id_refs(repo):
        for l in lessons_at(repo, ref):
            out.setdefault(l.get("id"), l)
    out.pop(None, None)
    return out


def jsonl_text(lessons) -> str:
    lessons = sorted(lessons, key=lambda l: l.get("id", ""))
    return "".join(json.dumps(l, ensure_ascii=False, separators=(",", ":")) + "\n" for l in lessons)


# ----------------------------------------------------------------------------- scrub
# Nothing leaves the local tier carrying the machine it was captured on: promote, export and
# capture --shared run every outgoing lesson through scrub_lesson. The login name never becomes
# the author, absolute paths become repo-relative or are dropped, and home-directory, drive, UNC
# and WSL paths in free text become <path>. A clean scrub is not clearance to publish: the review
# PR stays the gate.

NEUTRAL_AUTHOR = "unknown"
_URL_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.I)
_ABS_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/)")
_LINE_SUFFIX_RE = re.compile(r"^(.*?)((?::\d+)+)?$", re.S)
_MACHINE_PATH_RE = re.compile(
    r"(?<![\w.])(?:[A-Za-z]:[\\/]|\\\\[^\s\\/\"'<>|]+[\\/]|/(?:home|Users|root|mnt/[a-z])(?=[/\s]|$))"
    r"[^\s\"'<>|]*")


def _login_names() -> set:
    names = {os.environ.get(k) for k in ("USER", "USERNAME", "LOGNAME")}
    try:
        import getpass
        names.add(getpass.getuser())
    except Exception:  # noqa: BLE001 - no login is fine; there is nothing to scrub then
        pass
    names.discard(None)
    names.discard("")
    names.discard(os.environ.get("MNEMOSYNE_AUTHOR"))  # an explicit choice is not a leak
    return names


def _roots(repo: Path) -> list:
    """Directories an absolute path may be made relative to: the memory repo, its git toplevel
    and the current git toplevel, each in its given and resolved form, longest first."""
    cands = [Path(repo)]
    for where in (repo, Path.cwd()):
        code, top, _ = git(where, "rev-parse", "--show-toplevel")
        if code == 0 and top:
            cands.append(Path(top))
    forms = set()
    for c in cands:
        for form in (c, c.resolve()):
            s = str(form).replace("\\", "/").rstrip("/")
            if s:
                forms.add(s)
    return sorted(forms, key=len, reverse=True)


def _relative(path: str, roots) -> str | None:
    p = path.replace("\\", "/")
    fold = os.name == "nt" or re.match(r"^[A-Za-z]:/", p)
    for root in roots:
        a, b = (p.casefold(), root.casefold()) if fold else (p, root)
        if a == b:
            return "."
        if a.startswith(b + "/"):
            return p[len(root) + 1:]
    return None


def scrub_anchor(anchor: str, roots) -> str | None:
    """A repo-relative form of a file anchor, a URL unchanged, or None if it can't be made safe."""
    anchor = (anchor or "").strip()
    if not anchor or _URL_RE.match(anchor):
        return anchor or None
    path, suffix = _LINE_SUFFIX_RE.match(anchor).groups()
    if _ABS_RE.match(path) or path.startswith("~"):
        rel = _relative(path, roots)
        return rel + (suffix or "") if rel is not None else None
    rel = path.replace("\\", "/")
    if rel == ".." or rel.startswith("../") or "/../" in rel:
        return None
    return rel + (suffix or "")


def scrub_text(text, roots):
    """Free text with repo paths made relative and other machine paths replaced by <path>."""
    if not text:
        return text
    for root in roots:
        pat = r"[\\/]".join(re.escape(part) for part in re.split(r"/", root))
        text = re.sub(pat + r"[\\/]([^\s\"'<>|]*)", lambda m: m.group(1).replace("\\", "/"),
                      text, flags=re.I if os.name == "nt" else 0)
    return _MACHINE_PATH_RE.sub("<path>", text)


def scrub_lesson(lesson: dict, repo: Path) -> dict:
    """A copy of `lesson` that is safe to leave the local tier (see the section comment)."""
    out = json.loads(json.dumps(lesson))
    logins = _login_names()
    if not out.get("author") or out["author"] in logins:
        out["author"] = NEUTRAL_AUTHOR
    rv = out.get("review")
    if isinstance(rv, dict) and rv.get("approved_by") in logins:
        rv["approved_by"] = NEUTRAL_AUTHOR
    roots = _roots(repo)
    for key in ("title", "lesson", "rationale"):
        if out.get(key):
            out[key] = scrub_text(out[key], roots)
    src = out.get("source")
    if isinstance(src, dict):
        if src.get("anchors"):
            src["anchors"] = [a for a in (scrub_anchor(x, roots) for x in src["anchors"]) if a]
            if not src["anchors"]:
                del src["anchors"]
        if src.get("reflection_of"):
            src["reflection_of"] = scrub_text(src["reflection_of"], roots)
    return out


# ----------------------------------------------------------------------------- context + scoring


def empty_context(cfg: Config) -> dict:
    ctx = {"query": "", "stage": ""}
    for ax in cfg.axes:
        ctx.setdefault(ax["context"], [])
    return ctx


def extract_context(cfg: Config, text: str) -> dict:
    """Heuristically pull recall context from free text / a research brief, per axis extract rules."""
    ctx = empty_context(cfg)
    ctx["query"] = text or ""
    low = (text or "").lower()
    for ax in cfg.axes:
        ex = ax.get("extract")
        if not ex:
            continue
        cxt = ax["context"]
        found = set(ctx.get(cxt) or [])
        if ex.get("from") == "vocab":
            for v in cfg.vocab:
                vl = v.lower()
                if vl in low or vl.replace("-", " ") in low:
                    found.add(v)
        elif ex.get("from") == "enum":
            aliases = ex.get("aliases", {}) or {}
            for val in ax.get("enum", []) or []:
                terms = [val, val.replace("-", " ")] + list(aliases.get(val, []))
                if any(t.lower() in low for t in terms):
                    found.add(val)
        for pat in ex.get("regex", []) or []:
            for m in re.findall(pat, text or ""):
                tok = m if isinstance(m, str) else (m[0] if m else "")
                if tok:
                    found.add(tok.lower())
        if ex.get("allcaps"):
            for tok in re.findall(r"\b[A-Z][A-Z0-9_]{2,}\b", text or ""):
                if tok.upper() not in cfg.stopwords and not re.fullmatch(r"[A-Z]\d", tok):
                    found.add(tok)
        ctx[cxt] = sorted(found)
    return ctx


def score(cfg: Config, lesson: dict, ctx: dict):
    """Return (score, matched_reasons[]) for a lesson against a recall context, axis-driven."""
    if lesson.get("status") != "active":
        return 0.0, []
    trig = lesson.get("trigger", {}) or {}
    s = 0.0
    why = []

    for ax in cfg.axes:
        name, w, label, match, cxt = ax["name"], ax["weight"], ax["label"], ax["match"], ax["context"]
        tvals = trig.get(name) or []
        if match == "set":
            a = set(x.lower() for x in (ctx.get(cxt) or []))
            b = set(x.lower() for x in tvals)
            hit = a & b
            if hit:
                s += w * len(hit)
                why.append(f"{label}:{','.join(sorted(hit))}")
        elif match == "glob":
            cvals = [x.lower() for x in (ctx.get(cxt) or [])]
            tl = [str(x).lower() for x in tvals]
            hits = [c for c in cvals if any(fnmatch.fnmatch(c, t) or fnmatch.fnmatch(t, c) for t in tl)]
            if hits:
                s += w * len(set(hits))
                why.append(f"{label}:" + ",".join(sorted(set(hits))))
        elif match == "glob_scalar":
            cv = ctx.get(cxt) or ""
            if isinstance(cv, list):
                cv = cv[0] if cv else ""
            if cv:
                up = str(cv).upper()
                for pat in tvals:
                    if fnmatch.fnmatch(up, str(pat).upper()):
                        s += w
                        why.append(f"{label}:{pat}")
                        break

    # lifecycle stage: boost a lesson whose trigger.stages includes the current stage.
    cstage = (ctx.get("stage") or "").lower()
    lstages = [x.lower() for x in (trig.get("stages") or [])]
    if cstage and lstages and cstage in lstages:
        s += cfg.stage_weight
        why.append(f"stage:{cstage}")

    # free-text query keywords appearing in title/lesson/tags
    q = _tokens(ctx.get("query", ""))
    if q:
        tagvals = trig.get("tags", []) or []
        hay = _tokens(lesson.get("title", "") + " " + lesson.get("lesson", "") + " " + " ".join(tagvals))
        kw = q & hay
        kw -= set(x.lower() for x in tagvals)
        if kw:
            s += cfg.query_weight * min(len(kw), 4)

    # an empty trigger means "always worth a glance"
    trigger_keys = set(cfg.axis_names) | {"stages"}
    if s == 0 and not any(trig.get(k) for k in trigger_keys):
        s = 0.5

    s *= cfg.confidence.get(lesson.get("confidence", "medium"), 0.85)
    return round(s, 2), why


# ----------------------------------------------------------------------------- usage sidecar


def read_usage(repo: Path) -> dict:
    p = usage_path(repo)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except (json.JSONDecodeError, OSError):
        return {}


def bump_usage(repo: Path, ids):
    """Record that these lessons were surfaced. Best-effort + gitignored (reads never churn the JSONL)."""
    ids = [i for i in (ids or []) if i]
    if not ids:
        return
    try:
        with store_lock(repo):
            usage = read_usage(repo)
            now = today()
            for i in ids:
                rec = usage.setdefault(i, {})
                rec["uses"] = int(rec.get("uses", 0)) + 1
                rec["last_recalled"] = now
            atomic_write_text(usage_path(repo), json.dumps(usage, ensure_ascii=False, indent=0))
    except (OSError, LockTimeout):
        pass  # usage tracking is a nicety; never fail a recall over it


def total_uses(lesson: dict, usage: dict) -> int:
    return int(lesson.get("uses", 0)) + int((usage.get(lesson.get("id"), {}) or {}).get("uses", 0))


# ----------------------------------------------------------------------------- dedup / prune


def is_low_value_failure(text: str):
    """(bool, matched_snippet) — True if text is a missing-deliverable / transient / environmental failure."""
    if not text:
        return (False, "")
    m = LOW_VALUE_FAILURE_RE.search(text)
    return (bool(m), m.group(0).strip() if m else "")


def _dedup_tokens(*texts):
    out = set()
    for t in texts:
        out |= set(re.findall(r"[a-z0-9]+", (t or "").lower()))
    return out - _DEDUP_STOP


def lesson_similarity(a: dict, b: dict) -> float:
    """0..1: title+lesson token Jaccard (0.7) blended with trigger.tags Jaccard (0.3)."""
    ta = _dedup_tokens(a.get("title"), a.get("lesson"))
    tb = _dedup_tokens(b.get("title"), b.get("lesson"))
    if not ta or not tb:
        return 0.0
    jac = len(ta & tb) / len(ta | tb)
    ga = set(x.lower() for x in ((a.get("trigger", {}) or {}).get("tags", []) or []))
    gb = set(x.lower() for x in ((b.get("trigger", {}) or {}).get("tags", []) or []))
    tagj = (len(ga & gb) / len(ga | gb)) if (ga | gb) else 0.0
    return round(0.7 * jac + 0.3 * tagj, 3)


def find_duplicate(cfg: Config, lesson: dict, lessons):
    """Best active, same-category near-duplicate at/above cfg.dup_threshold, else (None, 0.0)."""
    best_id, best = None, 0.0
    for l in lessons:
        if l.get("status") != "active" or l.get("id") == lesson.get("id"):
            continue
        if l.get("category") != lesson.get("category"):
            continue
        sc = lesson_similarity(lesson, l)
        if sc >= cfg.dup_threshold and sc > best:
            best_id, best = l["id"], sc
    return best_id, best


def prune_value(lesson: dict, uses: int, today_d) -> float:
    conf = {"high": 3.0, "medium": 1.5, "low": 0.5}.get(lesson.get("confidence", "medium"), 1.5)
    try:
        age = (today_d - _dt.date.fromisoformat(lesson.get("created", today_d.isoformat()))).days
    except ValueError:
        age = 0
    recency = max(0.0, 1.0 - age / 365.0)
    return uses * 2.0 + int(lesson.get("reinforced", 0)) * 1.5 + conf + recency


def prune_candidates(lessons, usage, cap, max_age_days, today_d) -> dict:
    """Return {id: reason} of ACTIVE lessons to retire: aged never-used noise, then lowest-value over cap."""
    active = [l for l in lessons if l.get("status") == "active"]

    def U(l):
        return total_uses(l, usage)

    cands = {}
    for l in active:
        try:
            age = (today_d - _dt.date.fromisoformat(l.get("created", today_d.isoformat()))).days
        except ValueError:
            age = 0
        if (U(l) == 0 and int(l.get("reinforced", 0)) == 0
                and l.get("confidence") in ("low", "medium") and age > max_age_days):
            cands[l["id"]] = f"aged-noise (age {age}d, 0 uses, {l.get('confidence')} confidence)"
    remaining = [l for l in active if l["id"] not in cands]
    if cap and len(remaining) > cap:
        ranked = sorted(remaining, key=lambda l: prune_value(l, U(l), today_d))
        need = len(remaining) - cap
        for l in ranked:
            if need <= 0:
                break
            if l.get("confidence") == "high" or U(l) > 0:
                continue  # protect proven and high-confidence lessons from the cap sweep
            cands[l["id"]] = f"over-cap (cap {cap}; lowest value {round(prune_value(l, U(l), today_d), 2)})"
            need -= 1
    return cands


# ----------------------------------------------------------------------------- rendering


def render_digest(cfg: Config, ranked, repo, tier, fmt, budget) -> str:
    if fmt == "json":
        return json.dumps({
            "applied": [l["id"] for l, _, _ in ranked],
            "source": banner(repo),
            "lessons": [{
                "id": l["id"], "title": l["title"], "category": l["category"],
                "confidence": l["confidence"], "tier": tier.get(l["id"], "shared"),
                "lesson": l["lesson"], "matched": why, "score": sc,
                "source": l.get("source", {}),
            } for l, sc, why in ranked],
        }, indent=2)

    if not ranked:
        return "RECALL: no reflexion lessons matched this context. (Proceeding with no prior lessons applied.)"

    ids = ", ".join(l["id"] for l, _, _ in ranked)
    head = f"RECALL: {len(ranked)} reflexion lesson(s) applied to this context ({ids}). Source: {banner(repo)}."
    lines = [head, ""]
    for l, sc, why in ranked:
        t = tier.get(l["id"], "shared")
        flag = "  [LOW-CONFIDENCE — confirm before relying on it]" if l["confidence"] == "low" else ""
        src = l.get("source", {})
        srcbits = []
        if src.get("spec_id"):
            srcbits.append(src["spec_id"])
        if src.get("anchors"):
            srcbits.append(src["anchors"][0])
        srctxt = (" — from " + "; ".join(srcbits)) if srcbits else ""
        stg = (l.get("trigger", {}) or {}).get("stages") or []
        stgtxt = ("/" + "+".join(stg)) if stg else ""
        lines.append(f"- {l['id']} [{l['category']}{stgtxt}/{t}] {l['title']}{flag}")
        lines.append(f"    APPLY: {l['lesson']}")
        if why:
            lines.append(f"    matched: {' | '.join(why)}{srctxt}")
        elif srctxt:
            lines.append(f"    {srctxt.strip(' —')}")
    out = "\n".join(lines)
    if budget and len(out) > budget:
        kept, total = [lines[0], ""], len(lines[0]) + 2
        block = []
        shown = 0
        for ln in lines[2:]:
            if ln.startswith("- ") and block:
                if total + sum(len(x) + 1 for x in block) > budget:
                    break
                kept += block
                total += sum(len(x) + 1 for x in block)
                shown += 1
                block = [ln]
            else:
                block.append(ln)
        if block and total + sum(len(x) + 1 for x in block) <= budget:
            kept += block
            shown += 1
        if shown < len(ranked):
            kept.append(f"  (+{len(ranked) - shown} more — raise budget or lower top to see them)")
        out = "\n".join(kept)
    return out


def render_lessons_md(cfg: Config, repo: Path):
    with store_lock(repo):
        return _render_lessons_md(cfg, repo)


def _render_lessons_md(cfg: Config, repo: Path):
    lessons, tier = load_all(repo)
    text = render_lessons_text(cfg, lessons, tier, git_sha(repo))
    atomic_write_text(repo / "memory" / "LESSONS.md", text)
    return repo / "memory" / "LESSONS.md"


def render_lessons_text(cfg: Config, lessons, tier: dict, sha: str) -> str:
    """The LESSONS.md text for `lessons` (tier: id -> tier label; sha: the baseline shown)."""
    lessons = sorted(lessons, key=lambda l: l["id"])
    active = [l for l in lessons if l.get("status") == "active"]
    by_cat = {c: [l for l in active if l["category"] == c] for c in cfg.categories}
    trig_keys = ["stages"] + cfg.axis_names
    out = [
        "# Reflexion Lessons (generated — do not edit by hand)",
        "",
        f"Source of truth is `memory/lessons.jsonl` (+ local `memory/local.jsonl`). Regenerate with "
        f"`mnemosyne render`. Baseline `{sha}`. Config `{cfg.name}`.",
        "",
        f"**{len(active)} active lesson(s)** across {sum(1 for c in by_cat if by_cat[c])} categories. "
        f"Authored only via the mnemosyne engine.",
        "",
    ]
    for c in cfg.categories:
        items = by_cat[c]
        if not items:
            continue
        out.append(f"## {c} ({len(items)})")
        out.append("")
        for l in items:
            t = tier.get(l["id"], "shared")
            out.append(f"### {l['id']} — {l['title']}")
            out.append("")
            out.append(f"- **Apply:** {l['lesson']}")
            if l.get("rationale"):
                out.append(f"- **Why:** {l['rationale']}")
            trig = l.get("trigger", {}) or {}
            tbits = []
            for k in trig_keys:
                if trig.get(k):
                    tbits.append(f"{k}={','.join(str(x) for x in trig[k])}")
            if tbits:
                # code-span each bit so glob patterns like `POST *` don't parse as markdown emphasis
                out.append("- **When:** " + " · ".join(f"`{b}`" for b in tbits))
            src = l.get("source", {}) or {}
            sb = []
            if src.get("spec_id"):
                sb.append(src["spec_id"])
            sb += src.get("anchors", []) or []
            if src.get("reflection_of"):
                sb.append(f"reflection-of: {src['reflection_of']}")
            meta = [f"confidence={l['confidence']}", f"tier={t}", f"memory={l.get('memory_type', 'semantic')}",
                    f"review={l.get('review', {}).get('state', '?')}"]
            if (l.get("source", {}) or {}).get("stage"):
                meta.append("learned-in=" + l["source"]["stage"])
            if l.get("related"):
                meta.append("related=" + " ".join(f"[[{r}]]" for r in l["related"]))
            out.append(f"- **Source:** {'; '.join(sb) if sb else '—'}")
            out.append(f"- _{' · '.join(meta)}_")
            out.append("")
    return "\n".join(out).rstrip("\n") + "\n"  # single trailing newline; no MD012 at EOF


# ----------------------------------------------------------------------------- validation


def load_schema(repo: Path):
    p = repo / "schema" / "lesson.schema.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    b = BUNDLED_DIR / "schema" / "lesson.schema.json"
    return json.loads(b.read_text(encoding="utf-8")) if b.exists() else None


def validate_record(cfg: Config, l: dict, schema, valid_prefixes=None):
    errs = []
    prefixes = valid_prefixes or [cfg.id_prefix]
    req = (schema or {}).get("required", ["id", "title", "category", "lesson", "trigger", "status", "confidence", "review", "created"])
    for k in req:
        if k not in l or l[k] in (None, "", [], {}):
            errs.append(f"missing required '{k}'")
    if l.get("category") and l["category"] not in cfg.categories:
        errs.append(f"bad category '{l['category']}'")
    if l.get("confidence") and l["confidence"] not in cfg.confidence_levels:
        errs.append(f"bad confidence '{l['confidence']}'")
    if l.get("status") and l["status"] not in ("active", "superseded", "retired"):
        errs.append(f"bad status '{l['status']}'")
    if l.get("memory_type") and l["memory_type"] not in cfg.memory_types:
        errs.append(f"bad memory_type '{l['memory_type']}'")
    trig = l.get("trigger", {}) or {}
    for st in trig.get("stages", []) or []:
        if st not in cfg.stages:
            errs.append(f"bad trigger.stage '{st}'")
    for ax in cfg.axes:
        allowed = ax.get("enum")
        if allowed:
            for v in trig.get(ax["name"], []) or []:
                if v not in allowed:
                    errs.append(f"bad trigger.{ax['name']} '{v}'")
    src_stage = (l.get("source", {}) or {}).get("stage")
    if src_stage and src_stage not in cfg.stages:
        errs.append(f"bad source.stage '{src_stage}'")
    lid = l.get("id", "")
    if not any(re.match(rf"^{re.escape(p)}-\d{{4}}$", lid) for p in prefixes):
        errs.append(f"bad id '{lid}'")
    rv = l.get("review", {})
    if not isinstance(rv, dict) or rv.get("state") not in cfg.review_states:
        errs.append(f"bad review.state '{rv.get('state') if isinstance(rv, dict) else rv}'")
    return errs


def _is_promoted_copy(local: dict, shared_id: str) -> bool:
    exp = (local.get("source", {}) or {}).get("exported_to") or {}
    return exp.get("tier") == "shared" and exp.get("remote_id") == shared_id


def id_collisions(repo: Path) -> list:
    """Problems for ids used twice in one tier file, or by an active local lesson and a different
    shared lesson (in the working tree, on the default branch or on a review branch). load_all
    shows only the shared one, so without this check the local lesson silently disappears."""
    problems = []
    tiers = {"shared": read_jsonl(shared_path(repo)), "local": read_jsonl(local_path(repo))}
    for name, rows in tiers.items():
        seen = {}
        for l in rows:
            seen[l.get("id")] = seen.get(l.get("id"), 0) + 1
        problems += [f"{i}: duplicate id ({n}x in the {name} tier)" for i, n in seen.items() if n > 1]
    shared = {**committed_lessons(repo), **{l.get("id"): l for l in tiers["shared"]}}
    for l in tiers["local"]:
        other = shared.get(l.get("id"))
        if other is None or l.get("status") != "active" or _is_promoted_copy(l, l["id"]):
            continue
        problems.append(
            f"{l['id']}: id collision: local \"{l.get('title', '')}\" and shared \"{other.get('title', '')}\" "
            f"share an id, so only the shared one is visible. Re-capture the local lesson with --force "
            f"(it gets a fresh id), then delete the old line from memory/local.jsonl.")
    return problems


def validate(cfg: Config, repo: Path) -> dict:
    schema = load_schema(repo)
    lessons, tier, _origin, _src = load_federated(cfg, repo, pull_remotes=False)
    valid_prefixes = [cfg.id_prefix] + [s["prefix"] for s in cfg.stores]
    problems = []
    for l in lessons:
        for e in validate_record(cfg, l, schema, valid_prefixes):
            problems.append(f"{l.get('id', '?')}: {e}")
    problems += id_collisions(repo)
    by_id = {l["id"]: l for l in lessons}
    for l in lessons:
        sb = l.get("superseded_by")
        if sb and sb not in by_id:
            problems.append(f"{l['id']}: superseded_by {sb} not found")
        if sb and l.get("status") == "active":
            problems.append(f"{l['id']}: has superseded_by but status=active")
        for r in l.get("related", []) + l.get("supersedes", []):
            if r not in by_id:
                problems.append(f"{l['id']}: dangling ref {r}")
    md = repo / "memory" / "LESSONS.md"
    stale = False
    with store_lock(repo):  # the render-and-restore must not overwrite a concurrent save's render
        if md.exists():
            cur = md.read_text(encoding="utf-8")
            render_lessons_md(cfg, repo)
            if md.read_text(encoding="utf-8") != cur:
                stale = True
                atomic_write_text(md, cur)  # restore; don't mutate during validate
    by_tier = {}
    for t in tier.values():
        by_tier[t] = by_tier.get(t, 0) + 1
    return {
        "ok": not problems and not stale, "repo": str(repo), "sha": git_sha(repo),
        "counts": {"total": len(lessons),
                   "shared": by_tier.get("shared", 0), "local": by_tier.get("local", 0),
                   "by_tier": by_tier},
        "problems": problems, "render_stale": stale,
    }


# ----------------------------------------------------------------------------- recall (hot path)


def recall(cfg: Config, repo: Path, ctx: dict, top=None, min_score=None, bump=True, notes=None):
    """Score every active lesson against ctx; return (ranked, tier). ranked = [(lesson, score, why)].

    Federates over the primary repo + configured stores (read-only — recall never pulls, so an
    unreachable remote never blocks it; any skipped store is reported via the `notes` list)."""
    top = cfg.recall_top if top is None else top
    min_score = cfg.recall_min_score if min_score is None else min_score
    lessons, tier, _origin, _src = load_federated(cfg, repo, pull_remotes=False, notes=notes)
    scored = []
    for l in lessons:
        sc, why = score(cfg, l, ctx)
        if sc >= min_score and sc > 0:
            scored.append((l, sc, why))
    scored.sort(key=lambda t: (-t[1], t[0]["id"]))
    # (E) hygiene: collapse near-identical lessons so one digest never shows two ~dupes.
    collapsed = []
    for cand in scored:
        if any(keep[0].get("category") == cand[0].get("category")
               and lesson_similarity(cand[0], keep[0]) >= cfg.dup_threshold for keep in collapsed):
            continue
        collapsed.append(cand)
    ranked = collapsed[:top]
    if bump:
        bump_usage(repo, [l["id"] for l, _, _ in ranked])
    return ranked, tier


def build_recall_context(cfg: Config, *, from_text=None, query=None, axes=None, stage=None):
    """Assemble a recall context from a brief/query plus explicit per-axis values (dict axis->list/scalar)."""
    if from_text is not None:
        ctx = extract_context(cfg, from_text)
    else:
        ctx = empty_context(cfg)
        ctx["query"] = query or ""
        if query:
            ext = extract_context(cfg, query)
            for ax in cfg.axes:
                cxt = ax["context"]
                if isinstance(ctx.get(cxt), list):
                    ctx[cxt] = sorted(set(ctx.get(cxt) or []) | set(ext.get(cxt) or []))
    for name, val in (axes or {}).items():
        ax = cfg.axis(name)
        cxt = ax["context"] if ax else name
        if ax and ax["match"] == "glob_scalar":
            ctx[cxt] = val if isinstance(val, str) else (val[0] if val else "")
        else:
            vals = csv(val)
            ctx[cxt] = sorted(set(ctx.get(cxt) or []) | set(vals))
    if stage:
        ctx["stage"] = stage
    return ctx


# ----------------------------------------------------------------------------- capture / reflect


def build_lesson(cfg: Config, lessons, fields: dict, category_default, memory_default, taken=()):
    l = dict(fields.get("base") or {})
    if fields.get("title"):
        l.setdefault("title", fields["title"])
    if fields.get("lesson"):
        l.setdefault("lesson", fields["lesson"])
    if not l.get("title") or not l.get("lesson"):
        raise EngineError("a lesson needs a title and a lesson (or a base JSON object with them)")
    l.setdefault("category", fields.get("category") or category_default)
    l.setdefault("memory_type", fields.get("memory_type") or memory_default)
    l.setdefault("confidence", fields.get("confidence") or "medium")
    if fields.get("rationale"):
        l.setdefault("rationale", fields["rationale"])

    trig = l.setdefault("trigger", {})
    for name, v in (fields.get("trigger") or {}).items():
        vals = csv(v)
        if vals and not trig.get(name):
            trig[name] = vals

    stages_arg = csv(fields.get("stages"))
    stage = fields.get("stage")
    if not stages_arg and stage and stage != cfg.recall_also_stage:
        stages_arg = sorted({stage, cfg.recall_also_stage}) if cfg.recall_also_stage else [stage]
    if stages_arg and not trig.get("stages"):
        trig["stages"] = stages_arg

    src = l.setdefault("source", {})
    if fields.get("spec"):
        src.setdefault("spec_id", fields["spec"])
    if stage:
        src.setdefault("stage", stage)
    if fields.get("anchors"):
        src.setdefault("anchors", csv(fields["anchors"]))
    if fields.get("reflection_of"):
        src.setdefault("reflection_of", fields["reflection_of"])
    if fields.get("related"):
        l.setdefault("related", csv(fields["related"]))
    if fields.get("supersedes"):
        l.setdefault("supersedes", csv(fields["supersedes"]))

    l["id"] = next_id(cfg, lessons, taken=taken)
    l.setdefault("status", "active")
    l["created"] = today()
    l["updated"] = today()
    # Never the OS login: it's a machine identifier, and lessons are built to be shared.
    l.setdefault("author", os.environ.get("MNEMOSYNE_AUTHOR") or NEUTRAL_AUTHOR)
    l.setdefault("uses", 0)
    l.setdefault("reinforced", 0)
    shared = bool(fields.get("shared"))
    l["review"] = {"state": "approved" if shared else "local"}
    if shared:
        l["review"]["approved_by"] = l["author"]
    return l, shared


def capture(cfg: Config, repo: Path, fields: dict, *, category_default="decision",
            memory_default="semantic", force=False, supersede=None) -> dict:
    """Build + save a lesson to local (or shared). Returns a result dict describing what happened.

    The whole read (next id, dedup) through write runs under the repo's store lock."""
    with store_lock(repo):
        return _capture(cfg, repo, fields, category_default=category_default,
                        memory_default=memory_default, force=force, supersede=supersede)


def _capture(cfg: Config, repo: Path, fields: dict, *, category_default, memory_default, force,
             supersede) -> dict:
    lessons, tier = load_all(repo)
    taken = [l.get("id") for l in read_jsonl(local_path(repo))] + list(committed_lessons(repo))
    lesson, shared = build_lesson(cfg, lessons, fields, category_default, memory_default, taken)
    if shared:
        lesson = scrub_lesson(lesson, repo)

    # (A) hygiene: refuse a missing-deliverable / transient failure (only for failure-shaped captures).
    if lesson.get("category") == cfg.failure_category and not force:
        sig = " ".join(x for x in [(lesson.get("source", {}) or {}).get("reflection_of"),
                                   lesson.get("title"), lesson.get("lesson")] if x)
        bad, matched = is_low_value_failure(sig)
        if bad:
            raise LowValueError(matched)

    # (B0) hygiene: warn if a broader store (team/enterprise) already carries this lesson. We
    # never silently reinforce a remote store on a plain local capture (it isn't ours to mutate,
    # and its usage sidecar is read-only) — surface it and let the author promote/skip instead.
    if cfg.stores and not force and not supersede:
        fed, _tier, origin, _src = load_federated(cfg, repo, pull_remotes=False)
        store_lessons = [l for l in fed if origin.get(l["id"], "primary") != "primary"]
        sdup_id, sdup_sc = find_duplicate(cfg, lesson, store_lessons)
        if sdup_id:
            return {"action": "cross_store_duplicate", "dup_id": sdup_id,
                    "tier": origin.get(sdup_id), "similarity": round(sdup_sc, 2),
                    "threshold": cfg.dup_threshold}

    # (B) hygiene: a near-duplicate reinforces the existing lesson instead of adding noise.
    if not force and not supersede:
        dup_id, dup_sc = find_duplicate(cfg, lesson, lessons)
        if dup_id:
            for tf in (shared_path(repo), local_path(repo)):
                rows = read_jsonl(tf)
                changed = False
                for r in rows:
                    if r["id"] == dup_id and r.get("status") == "active":
                        r["reinforced"] = int(r.get("reinforced", 0)) + 1
                        r["last_used"] = today()
                        r["updated"] = today()
                        if r["reinforced"] >= 3 and r.get("confidence") != "high":
                            r["confidence"] = "high" if r.get("confidence") == "medium" else "medium"
                        changed = True
                if changed:
                    write_jsonl(tf, rows)
                    break
            render_lessons_md(cfg, repo)
            return {"action": "reinforced", "dup_id": dup_id, "similarity": round(dup_sc, 2),
                    "threshold": cfg.dup_threshold}

    if supersede:
        by_id = {l["id"]: l for l in lessons}
        if supersede not in by_id:
            raise EngineError(f"supersede {supersede}: not found")
        lesson.setdefault("supersedes", []).append(supersede)

    tierfile = shared_path(repo) if shared else local_path(repo)
    existing = read_jsonl(tierfile)
    existing.append(lesson)
    write_jsonl(tierfile, existing)

    if supersede:
        for tf in (shared_path(repo), local_path(repo)):
            rows = read_jsonl(tf)
            ch = False
            for r in rows:
                if r["id"] == supersede:
                    r["status"] = "superseded"
                    r["superseded_by"] = lesson["id"]
                    r["updated"] = today()
                    ch = True
            if ch:
                write_jsonl(tf, rows)
    render_lessons_md(cfg, repo)

    return {"action": "saved", "id": lesson["id"], "title": lesson["title"],
            "category": lesson["category"], "memory_type": lesson["memory_type"],
            "tier": "shared" if shared else "local", "shared": shared,
            "superseded": supersede}


def reflect(cfg: Config, repo: Path, fields: dict, *, force=False, supersede=None) -> dict:
    if not fields.get("reflection_of") and not fields.get("base"):
        raise EngineError('reflect needs reflection_of ("what went wrong" — the feedback that triggered this)')
    return capture(cfg, repo, fields, category_default=cfg.failure_category, memory_default="episodic",
                   force=force, supersede=supersede)


# ----------------------------------------------------------------------------- promote / sync / prune


# Promotion never touches a working tree. The review branch is built with git plumbing from the
# target repo's default branch plus exactly the promoted lessons, so nothing else that happens to be
# uncommitted in lessons.jsonl rides along, the developer stays on their branch, and a store's
# cached clone stays on its default branch, where `sync` sees the merge. The commit carries
# review.state=approved: merging the review PR is the approval, and nothing else has to flip it.


def _review_commit(cfg: Config, repo: Path, branch: str, base: str, lessons, message: str) -> str:
    """Create refs/heads/<branch> as `base` plus `lessons` appended to its shared tier, with
    LESSONS.md rendered to match. Raises EngineError if the branch exists or git fails."""
    if git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{branch}")[0] == 0:
        raise EngineError(f"branch {branch} already exists in {repo}: push or delete it, then retry")
    top = git(repo, "rev-parse", "--show-toplevel", check=True)[1]
    prefix = git(repo, "rev-parse", "--show-prefix", check=True)[1]
    rows = lessons_at(repo, base) + list(lessons)
    files = {
        f"{prefix}memory/lessons.jsonl": jsonl_text(rows),
        f"{prefix}memory/LESSONS.md": render_lessons_text(
            cfg, rows, {l["id"]: "shared" for l in rows}, git(repo, "rev-parse", "--short", base)[1]),
    }
    with tempfile.TemporaryDirectory(prefix="mnemosyne-review-") as td:
        env = {"GIT_INDEX_FILE": str(Path(td) / "index")}
        git(top, "read-tree", base, env=env, check=True)
        for i, (path, text) in enumerate(files.items()):
            blob = Path(td) / f"blob{i}"
            blob.write_bytes(text.encode("utf-8"))
            oid = git(top, "hash-object", "-w", "--path", path, str(blob), check=True)[1]
            git(top, "update-index", "--add", "--cacheinfo", f"100644,{oid},{path}", env=env, check=True)
        tree = git(top, "write-tree", env=env, check=True)[1]
    commit = git(top, "commit-tree", tree, "-p", base, "-m", message, check=True)[1]
    git(top, "update-ref", f"refs/heads/{branch}", commit, "", check=True)
    return commit


def stage_review_pr(cfg: Config, repo: Path, branch: str, message: str, lessons, *,
                    base_branch=None) -> dict:
    """Commit `lessons`, and nothing else, on review branch `branch` cut from the repo's default
    branch (see default_ref). The working tree and the current branch are left alone.

    Returns {"branch", "is_git", "base", "commands", "pushed", "error"}. `commands` are the steps
    left to run by hand (push, open the PR), returned so every surface (CLI, MCP, API) relays the
    same thing; push_review_pr runs the push. Outside git nothing is committed and `commands` is
    empty. Opening and merging the PR stays with a human; nothing here merges."""
    out = {"branch": branch, "is_git": is_git_repo(repo), "base": None, "commands": [],
           "pushed": False, "error": None}
    if not out["is_git"]:
        return out
    base = default_ref(repo, base_branch)
    if base is None:
        raise EngineError(f"{repo} has no commit to cut a review branch from: commit it first")
    _review_commit(cfg, repo, branch, base, lessons, message)
    out["base"] = base
    out["commands"] = [f'git -C "{repo}" push -u origin {branch} && gh pr create --fill --head {branch}']
    return out


def push_review_pr(repo: Path, pr: dict) -> dict:
    """Push a staged review branch to origin; record `pushed`, or the failure in `error`."""
    rc, _, err = git(repo, "push", "-u", "origin", pr["branch"])
    if rc == 0:
        pr["pushed"] = True
    else:
        pr["error"] = f"git push failed: {err}"
    return pr


def _promote_problem(lesson, lesson_id):
    """Why `lesson` (the local record for `lesson_id`, or None) can't be promoted, or None."""
    if lesson is None:
        return f"{lesson_id} is not in the local tier (only local lessons can be promoted)"
    exp = (lesson.get("source", {}) or {}).get("exported_to")
    if exp:
        return (f"{lesson_id} was already promoted to {exp.get('tier')} as {exp.get('remote_id')}; "
                f"its review PR decides it")
    if lesson.get("status") != "active":
        return f"{lesson_id} is {lesson.get('status')}; only active lessons can be promoted"
    return None


def _outgoing_copy(lesson: dict, repo: Path, new_id: str, *, approved: bool) -> dict:
    """The scrubbed copy of a local lesson that a promotion or export writes to a shared tier."""
    copy = scrub_lesson(lesson, repo)
    copy["id"] = new_id
    copy["review"] = {"state": "approved" if approved else "proposed"}
    copy["updated"] = today()
    copy["status"] = "active"
    copy.pop("superseded_by", None)
    if new_id != lesson["id"]:
        copy.setdefault("source", {})["exported_from"] = lesson["id"]
    return copy


def _mark_exported(lesson: dict, tier: str, remote_id: str):
    """Keep the local original, marked proposed, until its review PR merges (sync retires it)."""
    lesson["review"] = {"state": "proposed"}
    lesson["updated"] = today()
    lesson.setdefault("source", {})["exported_to"] = {"tier": tier, "remote_id": remote_id}


def promote(cfg: Config, repo: Path, lesson_id: str, *, push=False) -> dict:
    """Propose a local lesson for this repo's shared tier through a review PR.

    In a git repo the lesson is committed alone on `reflexion/<id>` (stage_review_pr), and the local
    copy is KEPT, marked proposed with `source.exported_to`, until the PR merges; the next `sync`
    retires it. So its id stays taken everywhere and is never reused. The shared copy keeps the
    local id unless a different lesson already holds it on a committed branch, in which case it
    gets a fresh one. Outside git there is no review to wait for, so the lesson moves straight into
    the shared tier as proposed. Whatever leaves the local tier is scrubbed (scrub_lesson).

    The result's `pr` is stage_review_pr's report; push=True also pushes the branch."""
    if not is_git_repo(repo):
        return _promote_in_place(cfg, repo, lesson_id)
    with store_lock(repo):
        local = read_jsonl(local_path(repo))
        lesson = {l["id"]: l for l in local}.get(lesson_id)
        problem = _promote_problem(lesson, lesson_id)
        if problem:
            raise EngineError(problem)
        working = read_jsonl(shared_path(repo))
        held = set(committed_lessons(repo)) | {l["id"] for l in working}
        shared_id = next_id(cfg, working + local, taken=held) if lesson_id in held else lesson_id
        branch = f"{_REVIEW_BRANCH}{shared_id}"
        pr = stage_review_pr(cfg, repo, branch, f"reflexion: promote {shared_id} — {lesson['title']}",
                             [_outgoing_copy(lesson, repo, shared_id, approved=True)])
        _mark_exported(lesson, "shared", shared_id)
        write_jsonl(local_path(repo), local)
        render_lessons_md(cfg, repo)
    if push:
        push_review_pr(repo, pr)
    return {"id": lesson_id, "shared_id": shared_id, "title": lesson["title"], "branch": branch,
            "is_git": True, "pr": pr}


def _promote_in_place(cfg: Config, repo: Path, lesson_id: str) -> dict:
    """Promote in a repo that isn't under git: move the lesson to the shared tier as proposed."""
    with store_lock(repo):
        local = read_jsonl(local_path(repo))
        lesson = {l["id"]: l for l in local}.get(lesson_id)
        problem = _promote_problem(lesson, lesson_id)
        if problem:
            raise EngineError(problem)
        copy = _outgoing_copy(lesson, repo, lesson_id, approved=False)
        write_jsonl(shared_path(repo), read_jsonl(shared_path(repo)) + [copy])
        write_jsonl(local_path(repo), [l for l in local if l["id"] != lesson_id])
        render_lessons_md(cfg, repo)
    pr = {"branch": None, "is_git": False, "base": None, "commands": [], "pushed": False, "error": None}
    return {"id": lesson_id, "shared_id": lesson_id, "title": lesson["title"], "branch": None,
            "is_git": False, "pr": pr}


def export(cfg: Config, repo: Path, lesson_ids, to_tier: str, *, push=False) -> dict:
    """Promote chosen local lessons UP to a broader shared store (team/enterprise, etc.).

    Each exported lesson is scrubbed and copied under a NEW id in the store's own prefix. In a git
    store the copies are committed together, and alone, on one review branch in the STORE repo
    (stage_review_pr), marked approved because merging that PR is the approval; push=True also
    pushes it. A store that isn't under git has no review, so the copies are written into it as
    proposed. Either way the local original is KEPT, marked proposed with a back-reference
    (`source.exported_to`), and the next `sync` after the merge retires it. Unlike recall, export is
    a WRITE: it clones a store that isn't cached yet, and fails loudly if it can't reach it."""
    from . import stores as _stores

    if to_tier in (None, "shared"):
        # default path: same-repo local -> shared, one entry per id
        return {"tier": "shared", "same_repo": True,
                "results": [promote(cfg, repo, lid, push=push) for lid in lesson_ids]}

    st = _stores.resolve_store(cfg, to_tier)
    if st is None:
        known = ", ".join(s["tier"] for s in cfg.stores) or "(none configured)"
        raise EngineError(f"no store tier '{to_tier}' in config.stores — known tiers: {known}")
    if st.readonly:
        raise EngineError(f"store '{to_tier}' is read-only (config.stores[].readonly) — cannot export to it")
    store_repo, note = _stores.ensure_cloned(st)
    if store_repo is None:
        raise EngineError(f"cannot reach store '{to_tier}' to export: {note}")
    store_git = is_git_repo(store_repo)

    pr = None
    with store_lock(store_repo, repo):
        local = read_jsonl(local_path(repo))
        local_by_id = {l["id"]: l for l in local}
        store_lessons = read_jsonl(shared_path(store_repo))
        taken = list(committed_lessons(store_repo))

        exported, skipped, copies = [], [], []
        for lid in lesson_ids:
            problem = _promote_problem(local_by_id.get(lid), lid)
            if problem:
                skipped.append({"id": lid, "reason": problem})
                continue
            remote_id = _stores.next_store_id(st, store_lessons + copies, taken)
            copy = _outgoing_copy(local_by_id[lid], repo, remote_id, approved=store_git)
            copy["created"] = today()
            copies.append(copy)
            exported.append({"local_id": lid, "remote_id": remote_id, "title": copy.get("title", "")})

        remote_ids = [e["remote_id"] for e in exported]
        branch = (f"{_REVIEW_BRANCH}{remote_ids[0]}" if len(remote_ids) == 1
                  else f"{_REVIEW_BRANCH}export-{to_tier}-{'-'.join(remote_ids)}") if remote_ids else None
        if exported:
            pr = stage_review_pr(cfg, store_repo, branch, f"reflexion: export to {to_tier} ({branch})",
                                 copies, base_branch=st.branch)
            if not store_git:
                write_jsonl(shared_path(store_repo), store_lessons + copies)
                render_lessons_md(cfg, store_repo)
            for e in exported:
                _mark_exported(local_by_id[e["local_id"]], to_tier, e["remote_id"])
            write_jsonl(local_path(repo), local)
            render_lessons_md(cfg, repo)

    if pr and push and store_git:
        push_review_pr(store_repo, pr)
    return {"tier": to_tier, "same_repo": False, "store_repo": str(store_repo),
            "exported": exported, "skipped": skipped, "branch": branch,
            "is_git": store_git, "pr": pr}


def _merged_tiers(cfg: Config, repo: Path) -> dict:
    """{tier: ({id: lesson}, merge_is_approval)} for this repo's shared tier and each cached store.

    In git a lesson counts once it is on the default branch (default_ref), where presence means
    the review PR merged, which is the approval, AND in the working tree recall reads. So a pull
    that failed never retires a local copy before its replacement is visible. A store outside git
    has no merge, so it counts only lessons whose review.state is approved."""
    from . import stores as _stores

    out = {}
    targets = [("shared", repo, None)] + [
        (st.tier, d, st.branch) for st in _stores.resolve_stores(cfg)
        for d in [_stores.cached(st)[0]] if d is not None]
    for tier, d, branch in targets:
        working = {l["id"]: l for l in read_jsonl(shared_path(d))}
        if is_git_repo(d):
            ref = default_ref(d, branch)
            merged = {l["id"] for l in lessons_at(d, ref)} if ref else set()
            out[tier] = ({i: l for i, l in working.items() if i in merged}, True)
        elif tier != "shared":
            out[tier] = (working, False)
    return out


def _retire_merged_locked(repo: Path, merged: dict) -> list:
    """Retire every kept original whose promoted or exported copy has merged. Returns their ids."""
    retired = []
    for tf in (shared_path(repo), local_path(repo)):
        rows = read_jsonl(tf)
        changed = False
        for r in rows:
            exp = (r.get("source", {}) or {}).get("exported_to")
            if not exp or r.get("status") != "active":
                continue
            by_id, merge_is_approval = merged.get(exp.get("tier"), ({}, False))
            remote_id = exp.get("remote_id")
            remote = by_id.get(remote_id)
            if not remote:
                continue
            if not merge_is_approval and (remote.get("review", {}) or {}).get("state") != "approved":
                continue
            how = "its review PR merged" if merge_is_approval else "approved upstream"
            r["status"] = "retired"
            r["retired_reason"] = f"promoted to {exp.get('tier')} as {remote_id}; {how}"
            if remote_id != r["id"]:
                r["superseded_by"] = remote_id
            r["updated"] = today()
            changed = True
            retired.append(r["id"])
        if changed:
            write_jsonl(tf, rows)
    return retired


def sync(cfg: Config, repo: Path) -> dict:
    """Pull this repo and every store (the only place recall's data is fetched), then retire the
    local originals of promotions and exports whose review PRs have merged."""
    from . import stores as _stores
    if is_git_repo(repo):
        # LESSONS.md is generated, and it also lists the local tier, so it is nearly always
        # modified (or untracked, in a store that never committed one). Put it back as committed so
        # a pull that touches it can fast-forward; it's re-rendered below.
        md = repo / "memory" / "LESSONS.md"
        if git(repo, "ls-files", "--error-unmatch", "memory/LESSONS.md")[0] == 0:
            git(repo, "checkout", "--quiet", "HEAD", "--", "memory/LESSONS.md")
        elif md.exists():
            md.unlink()
    code, out, err = git(repo, "pull", "--ff-only")
    if code == 127:
        raise EngineError("git not found")
    # A primary pull failure (e.g. a remote-less local memory repo) must NOT block store syncing
    # or retire-on-merge — those depend on the stores' state, not the primary's remote.
    primary_ok = code == 0
    primary_err = None if primary_ok else (err or out)
    if not primary_ok and is_git_repo(repo):
        git(repo, "fetch", "--quiet", "origin")  # a branch with no upstream still learns of merges
    store_status = []
    for st in _stores.resolve_stores(cfg):
        d, note = _stores.pull(st)
        store_status.append({"tier": st.tier, "ok": d is not None and not note,
                             "note": note, "sha": git_sha(d) if d else None})
    with store_lock(repo):
        retired = _retire_merged_locked(repo, _merged_tiers(cfg, repo))
    render_lessons_md(cfg, repo)
    return {"ok": primary_ok, "error": primary_err, "sha": git_sha(repo),
            "out": out.splitlines()[-1] if out else "already current",
            "stores": store_status, "retired": retired}


def prune(cfg: Config, repo: Path, *, apply=False, cap=None, max_age_days=None) -> dict:
    cap = cfg.prune_cap if cap is None else cap
    max_age_days = cfg.prune_max_age_days if max_age_days is None else max_age_days
    if not apply:
        return _prune(cfg, repo, False, cap, max_age_days)
    with store_lock(repo):
        return _prune(cfg, repo, True, cap, max_age_days)


def _prune(cfg: Config, repo: Path, apply, cap, max_age_days) -> dict:
    lessons, tier = load_all(repo)
    usage = read_usage(repo)
    today_d = _dt.date.today()
    cands = prune_candidates(lessons, usage, cap, max_age_days, today_d)
    by_id = {l["id"]: l for l in lessons}
    detail = {lid: {"category": by_id[lid]["category"], "tier": tier.get(lid, "shared"),
                    "title": by_id[lid]["title"], "reason": reason}
              for lid, reason in cands.items()}
    shared_touched = False
    if apply and cands:
        for tf in (shared_path(repo), local_path(repo)):
            rows = read_jsonl(tf)
            changed = False
            for r in rows:
                if r["id"] in cands and r.get("status") == "active":
                    r["status"] = "retired"
                    r["retired_reason"] = cands[r["id"]]
                    r["updated"] = today()
                    changed = True
                    if tf == shared_path(repo):
                        shared_touched = True
            if changed:
                write_jsonl(tf, rows)
        render_lessons_md(cfg, repo)
    return {"applied": apply, "candidates": detail, "count": len(cands),
            "shared_touched": shared_touched, "cap": cap, "max_age_days": max_age_days,
            "active": sum(1 for l in lessons if l.get("status") == "active")}


def hygiene(cfg: Config, repo: Path, *, cap=None, max_age_days=None) -> dict:
    cap = cfg.prune_cap if cap is None else cap
    max_age_days = cfg.prune_max_age_days if max_age_days is None else max_age_days
    lessons, tier, _origin, _src = load_federated(cfg, repo, pull_remotes=False)
    usage = read_usage(repo)
    today_d = _dt.date.today()
    active = [l for l in lessons if l.get("status") == "active"]
    dups = []
    for i in range(len(active)):
        for j in range(i + 1, len(active)):
            if active[i].get("category") == active[j].get("category"):
                sc = lesson_similarity(active[i], active[j])
                if sc >= cfg.dup_threshold:
                    dups.append((active[i]["id"], active[j]["id"], sc))
    dups.sort(key=lambda t: -t[2])
    never = [l["id"] for l in active if total_uses(l, usage) == 0]
    cands = prune_candidates(lessons, usage, cap, max_age_days, today_d)
    return {"active": len(active), "total": len(lessons), "sha": git_sha(repo),
            "cap": cap, "max_age_days": max_age_days, "over": len(active) - cap,
            "never_recalled": never, "duplicate_pairs": dups, "prune_candidates": len(cands)}


def stats(cfg: Config, repo: Path) -> dict:
    lessons, tier, _origin, _src = load_federated(cfg, repo, pull_remotes=False)
    usage = read_usage(repo)
    by_cat = {}
    for l in lessons:
        by_cat[l["category"]] = by_cat.get(l["category"], 0) + 1
    by_tier = {}
    for t in tier.values():
        by_tier[t] = by_tier.get(t, 0) + 1

    def _u(l):
        return total_uses(l, usage)

    top = [l for l in sorted(lessons, key=_u, reverse=True)[:5] if _u(l)]
    reinf = sorted((l for l in lessons if l.get("reinforced", 0)),
                   key=lambda l: l.get("reinforced", 0), reverse=True)[:5]
    return {"total": len(lessons), "sha": git_sha(repo),
            "active": sum(1 for l in lessons if l.get("status") == "active"),
            "retired": sum(1 for l in lessons if l.get("status") == "retired"),
            "shared": by_tier.get("shared", 0), "local": by_tier.get("local", 0),
            "by_tier": by_tier,
            "by_category": by_cat,
            "most_used": [(l["id"], _u(l)) for l in top],
            "most_reinforced": [(l["id"], l.get("reinforced", 0)) for l in reinf]}


def list_lessons(cfg: Config, repo: Path, *, category=None, status=None, tier_filter=None,
                 store_filter=None):
    lessons, tier, origin, _src = load_federated(cfg, repo, pull_remotes=False)
    lessons.sort(key=lambda l: l["id"])
    rows = []
    for l in lessons:
        if category and l["category"] != category:
            continue
        if status and l.get("status") != status:
            continue
        if tier_filter and tier.get(l["id"]) != tier_filter:
            continue
        if store_filter and origin.get(l["id"], "primary") != store_filter:
            continue
        rows.append((l, tier.get(l["id"], "shared")))
    return rows


def show(cfg: Config, repo: Path, lesson_id: str) -> dict:
    lessons, _ = load_all(repo)
    by_id = {l["id"]: l for l in lessons}
    if lesson_id not in by_id:
        raise EngineError(f"{lesson_id} not found")
    return by_id[lesson_id]


def init_repo(repo: Path, cfg_name: str | None = None) -> dict:
    """Scaffold a memory repo: memory/ dir, empty lessons.jsonl, .gitignore, optional config."""
    (repo / "memory").mkdir(parents=True, exist_ok=True)
    sp = shared_path(repo)
    if not sp.exists():
        sp.write_text("", encoding="utf-8")
    gi = repo / "memory" / ".gitignore"
    if not gi.exists():
        gi.write_text("local.jsonl\nusage.local.json\n.*.tmp\n.store.lock\n", encoding="utf-8")
    wrote_cfg = False
    if cfg_name:
        from .config import BUNDLED_DIR as _BD
        src = _BD / f"{cfg_name}.config.json"
        if not src.exists():
            raise EngineError(f"no bundled config named '{cfg_name}'")
        dest = repo / "mnemosyne.config.json"
        if not dest.exists():
            dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            wrote_cfg = True
    return {"repo": str(repo), "wrote_config": wrote_cfg}

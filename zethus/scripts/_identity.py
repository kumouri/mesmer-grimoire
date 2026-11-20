"""Who Zethus is working for: resolve the person, so no doc ever records a placeholder.

Specs, ADRs, constitutions, PR bodies and gate rulings all record who asked for, approved or
decided something. Zethus has no built-in way to know who that is, so before this module it wrote
``TBD`` or a stand-in like "Requester". Every script and hook that needs the name calls
:func:`resolve` instead. The decision record is ``docs/identity-of-the-person.md``.

**Resolution order.** The first source that yields a name or a handle wins, whole: fields are
never mixed across sources, so the result always traces to one place.

1. **Config**, ``identity.name`` and ``identity.handle``. The person's own choice, so it beats
   everything. Unlike every other key, identity is read from *every* config candidate, most
   personal first: ``--config``, ``$ZETHUS_CONFIG``, ``.copilot/zethus.config.json``,
   ``~/.copilot/zethus/config.json``, then the shared ``.github/zethus.config.json`` and
   ``.claude/amphion.config.json``. A team's committed config holds the team's answers, and it
   must not stop each person's own file from naming them.
2. **Git**, ``git config user.name`` in the repo being worked in (repo, global and system scopes,
   as git itself resolves them). ``user.email`` is deliberately not used: it would publish an
   address in every committed record.
3. **The forge account**, ``gh api user`` (its ``name``, else its ``login``), for a GitHub or
   GitHub Enterprise remote. It is tried only when config and git both gave nothing, so a
   normal run makes no network call. ``ZETHUS_IDENTITY_FORGE=off`` or ``forge=False`` skips it.
4. **Nothing found:** :class:`Identity` comes back unresolved. The caller then asks the person
   once, at the start of the session, and offers to save the answer with
   ``identity.py --save``. It never writes a placeholder.

**Names are recorded as the person wrote them:** no case change, no ``@`` added, no splitting.

**The run log.** Every resolution writes one line per step to the run log: which source was
tried, what it gave (``name present``, ``not set``, the error), which source won, and the steps
not tried. Values are never logged, only whether they were present: the log is a debugging aid and
must not become a second copy of personal data. The values go to the caller, which shows them to
the person. The log is ``~/.copilot/zethus/logs/identity.log`` unless ``--log`` or
``$ZETHUS_IDENTITY_LOG`` names another; ``off`` turns it off. Each line is flushed as it is
written, so it survives a crash, and each run's lines carry that run's id.

Stdlib only. The one subprocess besides git is ``gh``, with a timeout, and only at step 3.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import subprocess
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from _common import CONFIG_ENV, UsageError, rel, user_home

LOG_ENV = "ZETHUS_IDENTITY_LOG"
FORGE_ENV = "ZETHUS_IDENTITY_FORGE"
FORGE_TIMEOUT = 8          # seconds; the sessionStart hook has 10 in all and skips the forge
AGENT = "Zethus (AI agent)"  # who wrote the text: never the approver, never the decider

# Values that stand in for a person rather than name one. Matched whole, case-insensitively,
# after trimming. A team or a role that someone actually wrote ("Payments team") is a real answer.
PLACEHOLDERS = frozenset({
    "", "-", "—", "–", "?", "tbd", "tba", "todo", "unknown", "n/a", "na", "none", "nobody",
    "someone", "anyone", "requester", "the requester", "requestor", "user", "the user",
    "person", "the person", "approver", "the approver", "decider", "deciders", "owner",
    "the owner", "author", "the author", "me", "you", "human", "the human",
})
_TEMPLATE_RE = re.compile(r"^(<[^>]*>|\{\{[^}]*\}\}|\[[^\]]*\]|…|\.\.\.)$")


def is_placeholder(value: str | None) -> bool:
    """True when ``value`` stands in for a person instead of naming one."""
    text = (value or "").strip()
    return text.lower() in PLACEHOLDERS or bool(_TEMPLATE_RE.match(text))


@dataclass
class Identity:
    """The resolved person, or an unresolved result with the trace of what was tried."""

    name: str = ""
    handle: str = ""
    source: str = ""                    # e.g. "config ~/.copilot/zethus/config.json"
    step: int = 0                       # 1 config · 2 git · 3 forge · 0 unresolved
    trace: list[str] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        return bool(self.display)

    @property
    def display(self) -> str:
        """The name to write in a doc: the name as written, else the handle as written."""
        return self.name or self.handle

    def as_dict(self) -> dict:
        return {"resolved": self.resolved, "display": self.display, "name": self.name,
                "handle": self.handle, "source": self.source, "step": self.step,
                "agent": AGENT, "trace": self.trace}


class RunLog:
    """A line-buffered run log. Never raises: a log that can't be written must not cost a run."""

    def __init__(self, path: Path | None):
        self.path = path
        self.run_id = f"{_dt.datetime.now().strftime('%Y%m%dT%H%M%S')}-{os.getpid()}"
        self._fh = None
        self.error = ""
        if path is not None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                self._fh = open(path, "a", encoding="utf-8", buffering=1, newline="\n")
            except OSError as exc:
                self.error = f"run log not written ({path.name}: {exc.strerror or exc})"

    def __call__(self, message: str) -> None:
        if self._fh is None:
            return
        stamp = _dt.datetime.now().isoformat(timespec="seconds")
        try:
            self._fh.write(f"{stamp} [{self.run_id}] {message}\n")
            self._fh.flush()
        except OSError:
            pass

    def close(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None


def log_path(explicit: str | None = None) -> Path | None:
    """Where the run log goes: ``--log``, else ``$ZETHUS_IDENTITY_LOG``, else the user home.
    ``off`` (either way) means no log file."""
    value = explicit if explicit is not None else os.environ.get(LOG_ENV, "").strip()
    if value.lower() == "off":
        return None
    if value:
        return Path(value).expanduser()
    return user_home() / "logs" / "identity.log"


def identity_config_candidates(repo: Path, explicit: str | None = None) -> list[Path]:
    """Every config that may hold ``identity``, most personal first (see the module docstring)."""
    paths: list[Path] = []
    if explicit:
        paths.append(Path(explicit) if Path(explicit).is_absolute() else repo / explicit)
    env = os.environ.get(CONFIG_ENV, "").strip()
    if env:
        paths.append(Path(env) if Path(env).is_absolute() else repo / env)
    paths += [repo / ".copilot" / "zethus.config.json",
              user_home() / "config.json",
              repo / ".github" / "zethus.config.json",
              repo / ".claude" / "amphion.config.json"]
    seen, unique = set(), []
    for path in paths:
        key = str(path.resolve()) if path.exists() else str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _present(label: str, value: str) -> str:
    return f"{label} present" if value else f"{label} not set"


def _from_config(repo: Path, explicit: str | None, log: RunLog, trace: list[str]):
    for path in identity_config_candidates(repo, explicit):
        where = rel(path, repo)
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            line = f"1 config {where}: unreadable, skipped ({type(exc).__name__}: {exc})"
            log(line)
            trace.append(line)
            continue
        ident = data.get("identity") if isinstance(data, dict) else None
        if not isinstance(ident, dict):
            line = f"1 config {where}: no identity key"
            log(line)
            trace.append(line)
            continue
        name, handle = _text(ident.get("name")), _text(ident.get("handle"))
        for label, value in (("identity.name", name), ("identity.handle", handle)):
            if value and is_placeholder(value):
                line = f"1 config {where}: {label} is a placeholder, ignored"
                log(line)
                trace.append(line)
        name = "" if is_placeholder(name) else name
        handle = "" if is_placeholder(handle) else handle
        line = (f"1 config {where}: {_present('identity.name', name)}, "
                f"{_present('identity.handle', handle)}")
        log(line)
        trace.append(line)
        if name or handle:
            return name, handle, f"config {where}"
    line = "1 config: no config holds identity.name or identity.handle"
    log(line)
    trace.append(line)
    return None


def _from_git(repo: Path, log: RunLog, trace: list[str]):
    try:
        proc = subprocess.run(["git", "-C", str(repo), "config", "--get", "user.name"],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=FORGE_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        line = f"2 git: could not run git ({type(exc).__name__}: {exc})"
        log(line)
        trace.append(line)
        return None
    name = proc.stdout.strip() if proc.returncode == 0 else ""
    if name and is_placeholder(name):
        line = "2 git user.name: a placeholder, ignored"
        log(line)
        trace.append(line)
        return None
    line = f"2 git user.name: {'present' if name else 'not set'}"
    log(line)
    trace.append(line)
    return (name, "", "git config user.name") if name else None


def _forge_host(repo: Path) -> str:
    """The GitHub host for ``gh``: ``$GH_HOST``, else ``origin``'s host, else github.com."""
    host = os.environ.get("GH_HOST", "").strip()
    if host:
        return host
    try:
        proc = subprocess.run(["git", "-C", str(repo), "remote", "get-url", "origin"],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=FORGE_TIMEOUT)
        url = proc.stdout.strip() if proc.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        url = ""
    match = re.match(r"^(?:[a-z+]+://)?(?:[^@/]+@)?([^/:]+)", url)
    return match.group(1) if match else "github.com"


def _from_forge(repo: Path, log: RunLog, trace: list[str]):
    host = _forge_host(repo)
    if "github" not in host.lower():
        line = f"3 forge: origin is on {host}, not a GitHub host gh can ask; skipped"
        log(line)
        trace.append(line)
        return None
    try:
        proc = subprocess.run(["gh", "api", "user", "--hostname", host],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=FORGE_TIMEOUT)
    except FileNotFoundError:
        line = "3 forge: gh is not installed; skipped"
        log(line)
        trace.append(line)
        return None
    except (OSError, subprocess.SubprocessError) as exc:
        line = f"3 forge gh api user ({host}): failed ({type(exc).__name__}: {exc})"
        log(line)
        trace.append(line)
        return None
    if proc.returncode != 0:
        first = (proc.stderr.strip().splitlines() or ["no output"])[0][:200]
        line = f"3 forge gh api user ({host}): exit {proc.returncode} ({first})"
        log(line)
        trace.append(line)
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        line = f"3 forge gh api user ({host}): not JSON ({exc})"
        log(line)
        trace.append(line)
        return None
    name = _text(data.get("name")) if isinstance(data, dict) else ""
    login = _text(data.get("login")) if isinstance(data, dict) else ""
    line = f"3 forge gh api user ({host}): {_present('name', name)}, {_present('login', login)}"
    log(line)
    trace.append(line)
    return (name, login, f"forge account ({host}, gh api user)") if (name or login) else None


def forge_enabled(forge: bool | None) -> bool:
    if forge is not None:
        return forge
    return os.environ.get(FORGE_ENV, "").strip().lower() not in {"off", "0", "false", "no"}


def resolve(repo: Path, *, config: str | None = None, forge: bool | None = None,
            log: RunLog | None = None) -> Identity:
    """Resolve the person Zethus works for. Never raises; an error is a traced, skipped step."""
    own_log = log is None
    log = log or RunLog(None)
    trace: list[str] = []
    use_forge = forge_enabled(forge)
    log(f"identity: start repo={rel(repo, repo) or '.'} forge={'on' if use_forge else 'off'} "
        f"config_candidates={[rel(p, repo) for p in identity_config_candidates(repo, config)]}")
    def forge_off():
        line = f"3 forge: off ({FORGE_ENV}=off or --no-forge)"
        log(line)
        trace.append(line)

    steps = [(1, lambda: _from_config(repo, config, log, trace)),
             (2, lambda: _from_git(repo, log, trace)),
             (3, (lambda: _from_forge(repo, log, trace)) if use_forge else forge_off)]
    result = Identity(trace=trace)
    for number, step in steps:
        if result.resolved:
            line = f"{number}: not tried (an earlier source won)"
            log(line)
            trace.append(line)
            continue
        try:
            found = step()
        except Exception as exc:   # a step's bug must not cost the run: trace it, try the next
            line = f"{number}: error ({type(exc).__name__}: {exc})"
            log(line + "\n" + traceback.format_exc().rstrip())
            trace.append(line)
            found = None
        if found:
            result.name, result.handle, result.source = found
            result.step = number
    if result.resolved:
        log(f"identity: resolved from {result.source} (step {result.step})")
    else:
        log("identity: unresolved after config, git and forge; the caller asks the person once")
    if own_log:
        log.close()
    return result


def save(target: Path, name: str, handle: str, log: RunLog) -> list[str]:
    """Merge ``identity`` into the JSON config at ``target``; return the keys written.

    Never clobbers: other keys stay as they were, and a file that isn't a JSON object is refused.
    The write goes through a temp file and a rename, so a crash leaves the old file intact.
    """
    name, handle = name.strip(), handle.strip()
    for label, value in (("--name", name), ("--handle", handle)):
        if value and is_placeholder(value):
            raise UsageError(f"{label} {value!r} is a placeholder, not a name; save the person's "
                             "name as they write it")
    if not (name or handle):
        raise UsageError("--save needs --name or --handle")
    data: dict = {}
    if target.is_file():
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise UsageError(f"{target.name} is not valid JSON ({exc}); not touching it") from exc
        if not isinstance(data, dict):
            raise UsageError(f"{target.name} must hold a JSON object; not touching it")
    ident = data.get("identity") if isinstance(data.get("identity"), dict) else {}
    written = []
    for key, value in (("name", name), ("handle", handle)):
        if value:
            ident[key] = value
            written.append(f"identity.{key}")
    data["identity"] = ident
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, target)
    log(f"identity: saved {', '.join(written)} to {target.name} (values not logged)")
    return written


def require(explicit: str | None, what: str, repo: Path, *, config: str | None = None,
            log: RunLog | None = None) -> tuple[str, str]:
    """The value to write for ``what`` ("who decided", "who owns this spec", …), and its source.

    An explicit value wins, unless it is a placeholder. Otherwise :func:`resolve`. Nothing found
    raises :class:`UsageError`, so a script writes no file rather than a stand-in.
    """
    if explicit is not None:
        if is_placeholder(explicit):
            raise UsageError(
                f"{what}: {explicit!r} is a placeholder, not a name. Leave the flag off and the "
                "person Zethus works for is resolved (identity.py), or name the real person or "
                "team as they write it.")
        if log:
            log(f"{what}: given explicitly; resolution not needed")
        return explicit.strip(), "given explicitly"
    found = resolve(repo, config=config, log=log)
    if not found.resolved:
        raise UsageError(
            f"{what}: not known. Tried {'; '.join(found.trace)}. Ask the person once for the name "
            "they want recorded (the harness's question tool), offer to save it with "
            "`identity.py --save --name \"<their name>\"`, then re-run. Not writing a placeholder.")
    return found.display, found.source

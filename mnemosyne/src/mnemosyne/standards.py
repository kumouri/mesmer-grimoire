"""Context fingerprints, standards (S7) and their promotion (docs/lessons-capture-spec.md section 4.4,
Phase 3). Stdlib only; no network.

A lesson that keeps coming back is a **standard candidate**. Whether it keeps coming back across
*different work*, rather than over and over in one task, is what the fingerprints are for.

CONTEXT   A context is a spec or ticket (Q5): two pieces of work in one repo are two contexts, and
          one long ticket counts once however many sessions it spans. The reference is, in order,
          an explicit spec or ticket id, a ticket key found in the branch name, then the branch
          itself. The fingerprint stored on a lesson is a *salted hash* of the repo's identity plus
          that reference, so a shared tier can count distinct contexts without learning repo,
          ticket or branch names. Nothing here ever stores the reference itself on a lesson.
          The raw reference stays in the local spool candidate that raised it, which is gitignored.
SALT      $MNEMOSYNE_CONTEXT_SALT, else a random per-memory-repo salt kept in the spool directory
          (`memory/.capture/salt`, which ignores itself). Hashes only compare under one salt, so a
          team that wants one count across machines sets the same variable on each of them. A
          hash is not a secret from someone who holds the salt and guesses ticket ids; it is a
          scrub, and the review PR remains the gate (spec 4.6).
LESSON    Every capture or reinforce appends `{ctx, stage, date, signal}` to `lesson["contexts"]`.
          A decision lesson also carries `{"class", "option"}` (the question class and the chosen
          option its ADR recorded), and a reinforce matches on that pair whatever the wording.
RULE      Three occurrences across at least two distinct contexts within 180 days (Q4), counted
          from the fingerprints inside the window: `memory.standard` {minOccurrences, minContexts,
          windowDays}. What counts as a context is not configurable.
ASK       When a lesson reaches the rule it raises one S7 candidate, once, ever: a later skip or a
          "never ask about this kind" is remembered, and a lesson already promoted, retired or
          proposed is not raised. The candidate is asked in the one batched triage question set
          (`candidates.triage`), never answered by the engine.
PROMOTE   A "yes" is `standard promote <id> --to <tier>`: the engine's ordinary promote or export
          (a review PR, after scrub) with the copy shaped as a standard: a `convention`, procedural,
          confidence high, carrying the `standard` marker and its context hashes. Where the tiers
          are is not decided here: the shared tier, or any store in `config.stores` (Q3). A store
          with `scope: "external"` also loses the spec, repo and anchor provenance.
CONFIG    A lesson may carry `config_default: {"key", "value"}`: the config key its answer maps to
          (a gate command, `branchModel.maxBehind`, a commit trailer). Promotion prints that as a
          **proposal**, a JSON snippet. It is never written anywhere: a config file is the
          project's to edit, and an upgrade changes nothing by itself.
OPT-IN    The CLI records fingerprints and raises S7 only in active capture mode
          (`memory.mode: "active"`, or MNEMOSYNE_CAPTURE_MODE); in shadow mode `capture` behaves
          as it did before this phase. `standard list`, `scan`, `promote` and `config` are explicit
          commands and run in any mode.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import secrets
from pathlib import Path

from . import candidates as cd
from . import core
from .core import EngineError

SIGNAL = "S7"
DEFAULTS = {"minOccurrences": 3, "minContexts": 2}
SALT_FILE = "salt"
SALT_ENV = "MNEMOSYNE_CONTEXT_SALT"
TEXT_MAX = 200                      # chars of a decision's question class or option
_TICKET_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9]{1,9}-\d{1,6})(?!\d)")
_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")


# ----------------------------------------------------------------------------- settings


def settings(cfg, mem_cfg: dict = None) -> dict:
    """{minOccurrences, minContexts, windowDays} from `memory.standard`; the Q4 ruling by default,
    and the window is the config's `prune_max_age_days` (180) unless set."""
    raw = ((mem_cfg or {}).get("standard") or {})
    raw = raw if isinstance(raw, dict) else {}

    def num(key, default):
        try:
            return max(1, int(raw.get(key, default)))
        except (TypeError, ValueError):
            return default

    return {"minOccurrences": num("minOccurrences", DEFAULTS["minOccurrences"]),
            "minContexts": num("minContexts", DEFAULTS["minContexts"]),
            "windowDays": num("windowDays", cfg.prune_max_age_days)}


def is_active(mem_cfg: dict, env=None) -> bool:
    """Phase 3 records and raises only when capture is active (opt-in; shadow is the default)."""
    return cd.capture_mode(mem_cfg or {}, env) == "active"


# ----------------------------------------------------------------------------- context identity


def salt(repo: Path, env=None) -> str:
    """The salt context hashes are made under (see SALT in the module docstring). Fails open to ''."""
    env = os.environ if env is None else env
    if env.get(SALT_ENV):
        return str(env[SALT_ENV])
    path = cd.capture_dir(repo) / SALT_FILE
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    try:
        value = secrets.token_hex(16)
        cd.ensure_capture_dir(repo)
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return path.read_text(encoding="utf-8").strip()
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(value + "\n")
        return value
    except OSError:
        return ""


def _origin_url(gitdir: Path) -> str:
    """The origin URL read from the git config on disk (a hook may not run git)."""
    candidates = [gitdir / "config"]
    try:
        common = (gitdir / "commondir").read_text(encoding="utf-8").strip()
        candidates.insert(0, (gitdir / common).resolve() / "config")
    except OSError:
        pass
    for conf in candidates:
        try:
            text = conf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = re.search(r'\[remote "origin"\][^\[]*?\burl\s*=\s*(\S+)', text)
        if m:
            return m.group(1)
    return ""


def repo_identity(root: Path) -> str:
    """A stable name for the repo that survives a re-clone: its origin URL without scheme, login or
    `.git`, else the folder name. Only ever hashed, never stored."""
    top, gitdir = cd._git_dir(Path(root))
    url = _origin_url(gitdir) if gitdir else ""
    if url:
        url = re.sub(r"^[a-z][a-z0-9+.-]*://", "", url, flags=re.I)
        url = re.sub(r"^[^@/]*@", "", url).replace(":", "/")
        return re.sub(r"(?:\.git)?/*$", "", url).casefold()
    return (top or Path(root)).name.casefold()


def ticket_in(branch: str):
    """A ticket key (ABC-123) in a branch name, upper-cased, else None."""
    m = _TICKET_RE.search(branch or "")
    return m.group(1).upper() if m else None


def context_ref(spec=None, branch=None):
    """(kind, reference) of the context a piece of work belongs to, or None when nothing names one:
    a spec or ticket id, else a ticket key in the branch, else the branch (Q5)."""
    spec = (spec or "").strip()
    if spec:
        return ("spec", spec.upper() if _TICKET_RE.fullmatch(spec) else spec)
    ticket = ticket_in(branch or "")
    if ticket:
        return ("ticket", ticket)
    branch = (branch or "").strip()
    if branch and branch != "(detached)":
        return ("branch", branch)
    return None


def context_hash(repo: Path, ident: str, ref: str, env=None) -> str:
    text = "\0".join((salt(repo, env), ident, str(ref).casefold()))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def project_ref(repo: Path, root: Path, *, spec=None, branch=None, env=None):
    """{ref, kind, ctx} for the work in `root`, or None if no context can be named."""
    if branch is None:
        branch = cd.project_context(Path(root)).get("branch")
    found = context_ref(spec, branch)
    if not found:
        return None
    kind, ref = found
    return {"ref": ref, "kind": kind, "ctx": context_hash(repo, repo_identity(Path(root)), ref, env)}


def entry_for(ctx_hash: str, *, stage=None, signal="", key=None) -> dict:
    """One fingerprint, as stored on a lesson. `key` (a candidate id) is hashed into `k`, so the
    same candidate run twice is not counted twice, and the id itself is not stored."""
    entry = {"ctx": ctx_hash, "date": core.today(), "signal": signal or "manual"}
    if stage:
        entry["stage"] = stage
    if key:
        entry["k"] = hashlib.sha256(str(key).encode("utf-8")).hexdigest()[:8]
    return entry


# ----------------------------------------------------------------------------- counting


def _date(text):
    try:
        return _dt.date.fromisoformat(str(text)[:10])
    except ValueError:
        return None


def counts(lesson: dict, st: dict, today=None) -> dict:
    """{occurrences, contexts} from the fingerprints inside the rolling window."""
    today = today or _dt.date.today()
    oldest = today - _dt.timedelta(days=st["windowDays"])
    inside = [e for e in lesson.get("contexts") or []
              if isinstance(e, dict) and e.get("ctx") and (_date(e.get("date")) or today) >= oldest]
    return {"occurrences": len(inside), "contexts": len({e["ctx"] for e in inside})}


def qualifies(lesson: dict, st: dict, today=None) -> bool:
    """True when `lesson` meets the Q4 rule and is not already a standard, proposed or retired."""
    if lesson.get("status") != "active" or isinstance(lesson.get("standard"), dict):
        return False
    if (lesson.get("source") or {}).get("exported_to"):
        return False
    c = counts(lesson, st, today)
    return c["occurrences"] >= st["minOccurrences"] and c["contexts"] >= st["minContexts"]


# ----------------------------------------------------------------------------- capture inputs


def decision_fields(cls, option):
    """The `{"class", "option"}` a decision lesson records, or None when neither was given."""
    cls, option = str(cls or "").strip(), str(option or "").strip()
    if not cls and not option:
        return None
    if not cls or not option:
        raise EngineError("a decision needs both a question class and the chosen option")
    return {"class": cls[:TEXT_MAX], "option": option[:TEXT_MAX]}


def parse_config_value(text):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text


def config_default_fields(key, value):
    """The `{"key", "value"}` a lesson records for a config default, or None when no key was given."""
    key = str(key or "").strip()
    if not key:
        return None
    if not _KEY_RE.match(key):
        raise EngineError(f"config key '{key}' is not a dotted name such as branchModel.maxBehind")
    return {"key": key, "value": value}


def capture_fields(repo: Path, mem_cfg: dict, *, candidate=None, spec=None, stage=None, signal="",
                   cwd=None, env=None, **explicit) -> dict:
    """What Phase 3 adds to a capture's fields: `decision`, `config_default` and `context`.

    Explicit values (decision_class, decision_option, config_key, config_value) win over the
    candidate's. The context fingerprint is recorded only in active mode, and only when something
    names a context (a spec or ticket, then a ticket in the branch, then the branch)."""
    active = is_active(mem_cfg, env)
    # What a candidate carries (an ADR's question class and option, its config key) counts only in
    # active mode, so a shadow-mode capture is the capture it was before this phase. A value given
    # on the command line is always honoured: the person asked for it.
    ev = ((candidate or {}).get("evidence") or {}) if active else {}
    cctx = (candidate or {}).get("context") or {}
    out = {}
    decision = decision_fields(explicit.get("decision_class") or ev.get("qclass"),
                               explicit.get("decision_option") or ev.get("option"))
    if decision:
        out["decision"] = decision
    key = explicit.get("config_key") or ev.get("config_key")
    if key:
        value = explicit.get("config_value")
        value = parse_config_value(value if value is not None else ev.get("config_value"))
        out["config_default"] = config_default_fields(key, value)
    if active:
        if cctx.get("ctx") and not spec:
            ctx_hash = cctx["ctx"]      # the script that raised it already knew the work
        else:
            found = project_ref(repo, Path(cwd or os.getcwd()), spec=spec or cctx.get("ref"),
                                branch=cctx.get("branch"), env=env)
            ctx_hash = found["ctx"] if found else None
        if ctx_hash:
            sig = (candidate or {}).get("signal") or signal
            out["context"] = entry_for(ctx_hash, stage=stage, signal=sig,
                                       key=(candidate or {}).get("id"))
    return out


# ----------------------------------------------------------------------------- raising S7


def _title(lesson: dict) -> str:
    return core.scrub_machine_paths(str(lesson.get("title") or ""))[:120]


def raise_candidate(cfg, repo: Path, lesson: dict, mem_cfg: dict, project_ctx: dict = None):
    """The one S7 candidate for `lesson`, or None if it doesn't qualify or was already raised.

    Raised once per lesson, ever: any earlier S7 candidate for it, answered or not, stops another.
    That is what keeps "three ADRs across two specs" to exactly one question, and a skip final."""
    st = settings(cfg, mem_cfg)
    if not qualifies(lesson, st):
        return None
    if any(c.get("signal") == SIGNAL and (c.get("evidence") or {}).get("lesson") == lesson["id"]
           for c in cd.candidates(repo)):
        return None
    n = counts(lesson, st)
    cfgdef = lesson.get("config_default") or {}
    evidence = {"lesson": lesson["id"], "title": _title(lesson), "occurrences": n["occurrences"],
                "contexts": n["contexts"], "windowDays": st["windowDays"],
                "decision": bool(lesson.get("decision")), "config": str(cfgdef.get("key") or "")}
    return cd.add_candidate(repo, SIGNAL, host="cli", event="standard", context=project_ctx or {},
                            evidence=evidence, fp_key=lesson["id"])


def lessons_of(cfg, repo: Path) -> list:
    return core.load_all(repo)[0]


def after_capture(cfg, repo: Path, lesson_id: str, mem_cfg: dict, project_ctx: dict = None):
    """Called after a capture lands: raise S7 if the lesson it landed on now qualifies. Active only."""
    if not lesson_id or not is_active(mem_cfg):
        return None
    lesson = next((l for l in lessons_of(cfg, repo) if l.get("id") == lesson_id), None)
    return raise_candidate(cfg, repo, lesson, mem_cfg, project_ctx) if lesson else None


def scan(cfg, repo: Path, mem_cfg: dict, project_ctx: dict = None) -> list:
    """Raise S7 for every lesson that qualifies and hasn't been raised: the catch-up for lessons
    captured before this phase, or by a path that doesn't call `after_capture`."""
    return [c for c in (raise_candidate(cfg, repo, l, mem_cfg, project_ctx) for l in lessons_of(cfg, repo)) if c]


def report(cfg, repo: Path, mem_cfg: dict) -> list:
    """One row per active lesson that carries fingerprints, for `standard list`."""
    st = settings(cfg, mem_cfg)
    raised = {(c.get("evidence") or {}).get("lesson"): c for c in cd.candidates(repo)
              if c.get("signal") == SIGNAL}
    rows = []
    for l in lessons_of(cfg, repo):
        if l.get("status") != "active" or not l.get("contexts"):
            continue
        n = counts(l, st)
        c = raised.get(l["id"])
        rows.append({"id": l["id"], "title": l.get("title", ""), **n,
                     "standard": isinstance(l.get("standard"), dict),
                     "qualifies": qualifies(l, st),
                     "asked": (c.get("resolution") or "pending") if c else None,
                     "config": (l.get("config_default") or {}).get("key") or ""})
    return rows


# ----------------------------------------------------------------------------- the question


def offer_tiers(cfg, mem_cfg: dict = None) -> list:
    """The tiers a standard can be promoted to, in the order they are offered: the repo's shared
    tier and every writable store in `config.stores` (Q3). `memory.offerTier` moves one first; empty
    leaves the federation's own order. An unknown name is ignored rather than trusted."""
    tiers = ["shared"] + [s["tier"] for s in cfg.stores if not s.get("readonly")]
    first = str((mem_cfg or {}).get("offerTier") or "").strip()
    if first in tiers:
        tiers.remove(first)
        tiers.insert(0, first)
    return tiers


def question_text(c: dict) -> str:
    ev = c.get("evidence") or {}
    text = (f"{ev.get('lesson')} \"{ev.get('title', '')}\" has come up {ev.get('occurrences')} times across "
            f"{ev.get('contexts')} specs or tickets in {ev.get('windowDays')} days. Promote it to a standard?")
    if ev.get("config"):
        text += f" Its answer maps to the config key {ev['config']}: I can propose that default too."
    return text


def options(c: dict, tiers) -> list:
    """The batched question's options for an S7 candidate: one per tier, then skip and never."""
    out = []
    for tier in tiers or ["shared"]:
        label = ("Promote to the project's shared tier as a standard (a review PR here)" if tier == "shared"
                 else f"Promote to the '{tier}' store as a standard (a review PR in that store's repo)")
        out.append({"key": f"promote:{tier}", "label": label})
    out += [{"key": k, "label": lab} for k, lab in cd.OPTIONS if k in ("skip", "never")]
    return out


# ----------------------------------------------------------------------------- promotion


def config_proposal(lesson: dict):
    """The config default a lesson proposes, as a JSON snippet to merge by hand, or None. It is a
    proposal and is never written to any file."""
    cdef = lesson.get("config_default") or {}
    key = str(cdef.get("key") or "")
    if not key or not _KEY_RE.match(key):
        return None
    value = cdef.get("value")
    if core.find_secret(json.dumps(value)):
        return None
    snippet = value
    for part in reversed(key.split(".")):
        snippet = {part: snippet}
    return {"key": key, "value": value, "snippet": snippet,
            "note": "merge into the project's config by hand (zethus.config.json or amphion.config.json); "
                    "nothing was written"}


def standard_shape(cfg, st: dict, n: dict):
    """The edit that makes an outgoing copy a standard: a procedural convention at high confidence
    carrying the `standard` marker (spec 4.1). The local original is left as it was."""
    def shape(copy):
        if "convention" in cfg.categories:
            copy["category"] = "convention"
        if "procedural" in cfg.memory_types:
            copy["memory_type"] = "procedural"
        if "high" in cfg.confidence_levels:
            copy["confidence"] = "high"
        copy["standard"] = {"since": core.today(), "occurrences": n["occurrences"],
                            "contexts": n["contexts"], "windowDays": st["windowDays"]}
    return shape


def promote(cfg, repo: Path, lesson_id: str, to_tier: str, mem_cfg: dict = None, *, push=False,
            force=False) -> dict:
    """Promote a recurring local lesson as a standard to the shared tier or a configured store: the
    engine's ordinary promote or export (a review PR, after scrub) with the copy shaped as a
    standard. Refuses a lesson that hasn't met the rule unless `force`, because the threshold is a
    ruling and the person, not the engine, may override it."""
    st = settings(cfg, mem_cfg)
    local = {l["id"]: l for l in core.read_jsonl(core.local_path(repo))}
    lesson = local.get(lesson_id)
    if lesson is None:
        raise EngineError(f"{lesson_id} is not in the local tier (only local lessons can be promoted)")
    n = counts(lesson, st)
    if not force and not qualifies(lesson, st):
        raise EngineError(
            f"{lesson_id} has not met the standard rule ({n['occurrences']} occurrence(s) across "
            f"{n['contexts']} context(s) in {st['windowDays']} days; needs {st['minOccurrences']} across "
            f"{st['minContexts']}), is already a standard, or is already proposed; --force overrides")
    res = core.export(cfg, repo, [lesson_id], to_tier or "shared", push=push,
                      shape=standard_shape(cfg, st, n))
    res["standard"] = {"lesson": lesson_id, **n}
    res["config_proposal"] = config_proposal(lesson)
    return res

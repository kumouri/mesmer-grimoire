#!/usr/bin/env python3
"""Phase -1: survey the untouched base's gates, and check that Phase -1's fix stays a fix.

The rule this serves: the person's change starts from green. Before any planned change, every
local gate runs on the untouched base, and whatever already fails is fixed in Phase -1, in its own
branch and PR (or its own commit series), before Phase 0. See ``docs/phase-minus-one.md``.

    python <kit root>/scripts/baseline-gates.py survey      # Stage 0, before any edit
    python <kit root>/scripts/baseline-gates.py scope       # Phase -1, before its push

``survey`` runs every gate ``run-local-gates --list`` shows, with the same discovery and the same
runner, on a working tree with no tracked changes (it refuses one that has them: that is not an
untouched base). The verdict for each gate is its exit code. For a failed gate it then reads the
output for findings, each a gate, a tracked file and a rule: checkstyle, ruff and flake8, ESLint
(unix, compact and stylish), javac and ``git diff --check`` shapes. A failure it can't place is
recorded once with file ``—`` and its exit code, so nothing is dropped.

- All green: one line, Phase -1 has nothing to do. Exit 0.
- Anything red: a table to paste into the spec's ``## Pre-existing gate failures`` section, each
  row marked ``fix`` (change it to ``ask`` only for a failure that can't be fixed safely), then the
  failed gates' output tails. Exit 1.
- Nothing red but a gate skipped or manual: not a full survey. Exit 3.

The survey's record goes to ``zethus/baseline-gates.json`` under the worktree's git directory
(``git rev-parse --git-path``), so it is never committed and each worktree keeps its own;
``--record`` names another path.

``scope`` reads that record and the change since the surveyed commit (committed, staged, unstaged
and untracked). It fails (exit 1) when Phase -1 touched a file no finding names, other than the
spec directory and files named with ``--also``, or when a file whose findings are all layout rules
(line endings, trailing whitespace, tabs, a final newline, indentation) changed in more than
whitespace. It lists each finding as changed or untouched, and adds that to the record. The gate
run at Stage 6 is what proves them fixed.

**The run log.** Logging is this script's first deliverable: each run writes the config it
started with, the tree state and commit, each gate's command, result, time and exit, every
finding, the record written, the scope decision for each file and finding, the verdict and exit
code, and the full traceback of anything unexpected, one flushed line at a time with the run's
id. The log is ``~/.copilot/zethus/logs/baseline-gates.log`` unless ``--log`` or
``$ZETHUS_BASELINE_LOG`` names another; ``off`` turns it off. It holds gate names, paths in the
repo and commit ids, nothing personal.

Exit codes: 0 green (survey) or in scope (scope) · 1 pre-existing failures (survey) or out of scope
(scope) · 2 usage error (not a git repo, tracked changes, no gates, no record) · 3 nothing failed
but the survey is incomplete.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import importlib.util
import json
import re
import sys
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (RunLog, UsageError, cfg, find_repo_root, git, load_config, rel,  # noqa: E402
                     run_log_path)

LOG_ENV = "ZETHUS_BASELINE_LOG"
LOG_NAME = "baseline-gates.log"
RECORD_NAME = "zethus/baseline-gates.json"
NO_FILE = "—"
MAX_RULE = 80

# A path with an extension, optionally absolute (a leading slash or a Windows drive letter), then an
# optional line: ``a/b.java:12``, ``/abs/b.java:[12,5]``, ``b.py(12)``.
LOC_RE = re.compile(r"(?P<path>(?:[A-Za-z]:)?[\\/]?(?:[\w.@~+-]+[\\/])*[\w@~+-][\w.@~+-]*\.[A-Za-z0-9]+)"
                    r"(?:(?::\[?|\()(?P<line>\d+))?")
STYLISH_RE = re.compile(r"^\s+(?P<line>\d+):\d+\s+(?:error|warning)\s+(?P<msg>.*?)\s{2,}(?P<rule>\S+)\s*$")
RULE_PATTERNS = (
    re.compile(r"\[(?P<rule>[A-Za-z][\w.-]*)\]\s*$"),                 # checkstyle: ... [RegexpMultiline]
    re.compile(r"\((?:[\w-]+)\)\s+(?P<rule>[A-Z]\w+):"),              # maven checkstyle: (regexp) RegexpMultiline:
    re.compile(r"\((?P<rule>[a-z@][\w/@.-]*)\)\s*$"),                 # eslint compact: ... (no-unused-vars)
    re.compile(r"^[\s:,\]\d]*(?P<rule>[A-Z]{1,4}\d{2,5})\b"),          # ruff / flake8: E501
    re.compile(r"\b(?P<rule>[A-Z][a-z]+(?:[A-Z][a-z0-9]*)+):"),        # CamelCaseRule:
)
NOISE_RE = re.compile(r"^\s*\[(?:INFO|DEBUG)\]")
SEVERITY_RE = re.compile(r"^[\s:,\]\[\d]*(?:\[?(?:error|warn(?:ing)?|fatal)\]?\s*[:-]?\s*)?", re.I)
LAYOUT_RE = re.compile(r"(?i)crlf|line.?ending|\beol\b|newline|new line|whitespace|trailing"
                       r"|\btab\b|tabs\b|tabcharacter\b|indent")


@dataclass
class Finding:
    gate: str
    file: str
    rule: str
    line: int | None = None
    count: int = 1
    text: str = ""

    @property
    def layout(self) -> bool:
        return bool(LAYOUT_RE.search(self.rule) or LAYOUT_RE.search(self.text))


def _load_gates_module():
    path = Path(__file__).resolve().parent / "run-local-gates.py"
    name = "run_local_gates_for_baseline"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod      # a dataclass needs its module registered while it is defined
    spec.loader.exec_module(mod)
    return mod


def tracked_files(repo: Path) -> set[str]:
    proc = git(repo, "ls-files", "-z")
    if proc is None or proc.returncode != 0:
        return set()
    return {p for p in proc.stdout.split("\0") if p}


def _repo_relative(raw: str, repo: Path) -> str:
    raw = raw.replace("\\", "/")
    path = Path(raw)
    if path.is_absolute() or re.match(r"^[A-Za-z]:/", raw):
        try:
            return Path(raw).resolve().relative_to(repo.resolve()).as_posix()
        except (ValueError, OSError):
            return ""
    return raw[2:] if raw.startswith("./") else raw


def _rule_of(rest: str) -> str:
    for rx in RULE_PATTERNS:
        m = rx.search(rest)
        if m:
            return m.group("rule")
    text = SEVERITY_RE.sub("", rest).strip(" :-")
    return (text[:MAX_RULE].rstrip() + "…") if len(text) > MAX_RULE else (text or "see output")


def extract(gate_name: str, output: str, repo: Path, tracked: set[str]) -> list[Finding]:
    """Findings in a failed gate's output: one per (file, rule), counted, tracked files only."""
    found: dict[tuple[str, str], Finding] = {}
    current = ""   # ESLint's stylish format names the file on a line of its own
    for line in output.splitlines():
        if not line.strip() or NOISE_RE.match(line):
            continue
        stylish = STYLISH_RE.match(line)
        if stylish and current:
            key = (current, stylish.group("rule"))
            hit = found.get(key)
            if hit:
                hit.count += 1
            else:
                found[key] = Finding(gate_name, current, stylish.group("rule"),
                                     int(stylish.group("line")), 1, stylish.group("msg")[:MAX_RULE])
            continue
        whole = _repo_relative(line.strip(), repo)
        if whole in tracked:
            current = whole
            continue
        for m in LOC_RE.finditer(line):
            path = _repo_relative(m.group("path"), repo)
            if path not in tracked:
                continue
            rest = line[m.end():]
            rule = _rule_of(rest)
            key = (path, rule)
            hit = found.get(key)
            if hit:
                hit.count += 1
            else:
                found[key] = Finding(gate_name, path, rule,
                                     int(m.group("line")) if m.group("line") else None, 1,
                                     SEVERITY_RE.sub("", rest).strip(" :-")[:MAX_RULE])
            break
    return list(found.values())


def record_path(repo: Path, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    proc = git(repo, "rev-parse", "--git-path", RECORD_NAME)
    if proc is None or proc.returncode != 0 or not proc.stdout.strip():
        raise UsageError("not a git work tree: the survey record lives beside the git metadata")
    path = Path(proc.stdout.strip())
    return path if path.is_absolute() else (repo / path).resolve()


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|")


def spec_rows(findings: list[Finding]) -> list[str]:
    rows = ["| Gate | File | Rule | Phase -1 |", "|---|---|---|---|"]
    for f in findings:
        where = NO_FILE if f.file == NO_FILE else f"`{_cell(f.file)}`"
        times = f" (×{f.count})" if f.count > 1 else ""
        rows.append(f"| {_cell(f.gate)} | {where} | {_cell(f.rule)}{times} | fix |")
    return rows


# --------------------------------------------------------------------------- survey


def survey(args, log: RunLog) -> int:
    repo = Path(args.repo).resolve() if args.repo else find_repo_root()
    config, config_path = load_config(repo, args.config)
    log(f"  config: {rel(config_path, repo) if config_path else 'none (repository evidence only)'}")
    status = git(repo, "status", "--porcelain")
    if status is None or status.returncode != 0:
        raise UsageError("not a git work tree: Phase -1 surveys a commit, and needs git to name it")
    lines = [ln for ln in status.stdout.splitlines() if ln.strip()]
    changed = [ln for ln in lines if not ln.startswith("??")]
    untracked = len(lines) - len(changed)
    if changed:
        log(f"  refused: {len(changed)} tracked change(s): {', '.join(ln[3:] for ln in changed[:10])}")
        raise UsageError(f"not an untouched base: {len(changed)} tracked file(s) changed. Phase -1 "
                         "surveys the base before any edit: run it right after the branch is cut or "
                         "rebased, or stash the change first (git stash push)")
    head = (git(repo, "rev-parse", "HEAD").stdout or "").strip()
    branch = (git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout or "").strip()
    log(f"  tree: clean ({untracked} untracked) at {head[:12] or '?'} on {branch or '?'}")

    mod = _load_gates_module()
    gates = mod.gates_from_config(config)
    source = rel(config_path, repo) if gates and config_path else ""
    if not gates:
        gates, evidence = mod.discover(repo)
        source = "auto-discovered from " + (", ".join(evidence) or "nothing")
    log(f"  gates from: {source}: {', '.join(g.name for g in gates) or 'none'}")
    if not gates:
        print("baseline-gates: no gates found, so there is nothing to survey. Configure gates.steps from "
              "the CI config (pre-push-gates, step 1) and re-run. No gates is not a green base.")
        return 2

    tracked = tracked_files(repo)
    findings: list[Finding] = []
    for g in gates:
        log(f"  gate {g.name}: run `{g.display}` ({g.source})")
        mod.run_gate(g, repo, args.timeout)
        secs = f"{g.seconds:.1f}s" if g.seconds is not None else "-"
        log(f"  gate {g.name}: {g.status} in {secs}" + (f" ({g.note})" if g.note else ""))
        if g.status == "FAIL":
            mine = extract(g.name, g.output, repo, tracked)
            if not mine:
                mine = [Finding(g.name, NO_FILE, g.note or "failed", None, 1, "see the gate's output")]
                log(f"  gate {g.name}: no file or rule found in {len(g.output.splitlines())} output "
                    "line(s); recorded as one gate-level failure")
            for f in mine:
                log(f"  finding: {f.gate} | {f.file}" + (f":{f.line}" if f.line else "")
                    + f" | {f.rule} (x{f.count})" + (" [layout]" if f.layout else ""))
            findings += mine

    failed = [g for g in gates if g.status == "FAIL"]
    unchecked = [g for g in gates if g.status in ("SKIP", "MANUAL")]
    record = {
        "version": 1, "runId": log.run_id, "date": _dt.datetime.now().isoformat(timespec="seconds"),
        "head": head, "branch": branch, "untracked": untracked, "gatesFrom": source,
        "gates": [{"name": g.name, "command": g.display, "status": g.status,
                   "seconds": round(g.seconds, 1) if g.seconds is not None else None, "note": g.note}
                  for g in gates],
        "findings": [asdict(f) for f in findings],
    }
    path = record_path(repo, args.record)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        log(f"  record: wrote {len(findings)} finding(s) to {rel(path, repo)}")
    except OSError as exc:
        log(f"  record: not written ({exc.strerror or exc})")
        print(f"baseline-gates: the record was not written ({exc.strerror or exc}); scope can't run "
              "without it", file=sys.stderr)

    short = head[:7] or "HEAD"
    if not failed and not unchecked:
        log(f"  verdict: GREEN, {len(gates)} gate(s); Phase -1 is a no-op")
        print(f"Phase -1: nothing to remediate — all {len(gates)} gate(s) green on the untouched base "
              f"({short}); write `None — every local gate is green on the untouched base ({short}).` "
              "in the spec's Pre-existing gate failures section, and start Phase 0.")
        return 0

    out = [f"baseline-gates — survey of the untouched base {short} on {branch or 'HEAD'}"
           + (f" ({untracked} untracked file(s) present)" if untracked else ""),
           f"Gates from: {source}", ""]
    for g in gates:
        secs = f"{g.seconds:.1f}s" if g.seconds is not None else "–"
        out.append(f"- {g.name}: {g.status} ({secs})" + (f" — {g.note}" if g.note else ""))
    if failed:
        out += ["", f"Pre-existing gate failures ({len(findings)} finding(s) in {len(failed)} gate(s)); "
                    "paste into the spec's `## Pre-existing gate failures` section:", "",
                *spec_rows(findings), ""]
        out.append("Phase -1 fixes each `fix` row before Phase 0, in its own branch and PR (rebase, "
                   "pr-later: its own commit series), as small as turns the gates green, never mixed "
                   "with the planned change. Change a row to `ask` only for a failure that can't be "
                   "fixed safely (a failing test whose fix needs a decision, a gate needing a "
                   "credential): give it a Gate remediation row, Remediation phase `Phase -1`, and ask "
                   "it once, at sign-off.")
    if unchecked:
        out.append("")
        out.append("Not a full survey: " + ", ".join(f"{g.name} ({g.status})" for g in unchecked)
                   + ". For a SKIP, install the missing toolchain and re-run; for a MANUAL gate, judge "
                     "its output against its expect.")
    for g in failed:
        tail = g.output.rstrip().splitlines()[-mod.TAIL_LINES:]
        if tail:
            out += ["", f"--- {g.name} (last {len(tail)} lines) ---", *tail]
    print("\n".join(out))
    code = 1 if failed else 3
    log(f"  verdict: {'RED' if failed else 'INCOMPLETE'}: {len(failed)} failed, {len(unchecked)} not checked")
    return code


# --------------------------------------------------------------------------- scope


def _changed_files(repo: Path, since: str) -> set[str]:
    out: set[str] = set()
    diff = git(repo, "diff", "--name-only", since)
    if diff is None or diff.returncode != 0:
        raise UsageError(f"can't diff against {since[:12]}: {(diff.stderr if diff else 'git missing').strip()}")
    out.update(p for p in diff.stdout.splitlines() if p.strip())
    new = git(repo, "ls-files", "--others", "--exclude-standard")
    if new is not None and new.returncode == 0:
        out.update(p for p in new.stdout.splitlines() if p.strip())
    return out


def _beyond_whitespace(repo: Path, since: str, path: str) -> bool:
    proc = git(repo, "diff", "--ignore-all-space", "--ignore-blank-lines", "--ignore-cr-at-eol",
               since, "--", path)
    if proc is None or proc.returncode != 0:
        return True
    return any(ln.startswith("@@") for ln in proc.stdout.splitlines())


def scope(args, log: RunLog) -> int:
    repo = Path(args.repo).resolve() if args.repo else find_repo_root()
    config, _ = load_config(repo, args.config)
    path = record_path(repo, args.record)
    if not path.is_file():
        raise UsageError(f"no survey record at {rel(path, repo)}: run `baseline-gates.py survey` on the "
                         "untouched base first")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UsageError(f"the survey record {rel(path, repo)} is unreadable: {exc}") from exc
    since = args.since or record.get("head") or ""
    if not since:
        raise UsageError("the record names no surveyed commit; pass --since")
    findings = [Finding(**{k: v for k, v in f.items() if k in Finding.__dataclass_fields__})
                for f in record.get("findings", [])]
    spec_dir = str(cfg(config, "spec.dir", "docs/specs")).strip("/") + "/"
    also = {re.sub(r"^\./", "", a.replace("\\", "/")) for a in (args.also or [])}
    log(f"  scope: since {since[:12]} (survey run {record.get('runId', '?')}), {len(findings)} "
        f"finding(s), spec dir {spec_dir}, also {sorted(also) or '-'}")
    changed = _changed_files(repo, since)
    named = {f.file for f in findings if f.file != NO_FILE}
    problems: list[str] = []
    for p in sorted(changed):
        if p in named:
            why = "named by a finding"
        elif p.startswith(spec_dir):
            why = "the spec directory"
        elif p in also:
            why = "named with --also"
        else:
            why = ""
            problems.append(f"{p}: no finding names it. Phase -1 is only the fix; the planned change "
                            "goes in Phase 0. If the fix truly needs this file, pass --also and list "
                            "it under As built")
        log(f"  file {p}: {'in scope, ' + why if why else 'OUT OF SCOPE'}")
    for p in sorted(named & changed):
        mine = [f for f in findings if f.file == p]
        if mine and all(f.layout for f in mine) and _beyond_whitespace(repo, since, p):
            problems.append(f"{p}: its findings are layout rules ({', '.join(sorted({f.rule for f in mine}))}), "
                            "but it changed in more than whitespace. Keep the layout fix alone")
            log(f"  file {p}: layout-only findings, but the diff is more than whitespace")
    report = []
    for f in findings:
        state = ("gate-level" if f.file == NO_FILE else "changed" if f.file in changed else "untouched")
        report.append({"gate": f.gate, "file": f.file, "rule": f.rule, "state": state})
        log(f"  finding {f.gate} | {f.file} | {f.rule}: {state}")
    record["scope"] = {"runId": log.run_id, "since": since, "changed": sorted(changed),
                       "findings": report, "problems": problems}
    try:
        path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        log(f"  record: scope not saved ({exc.strerror or exc})")

    out = [f"baseline-gates — Phase -1 scope since {since[:7]}: {len(changed)} file(s) changed", "",
           "| Gate | File | Rule | Phase -1 changed it |", "|---|---|---|---|"]
    for r in report:
        where = NO_FILE if r["file"] == NO_FILE else f"`{_cell(r['file'])}`"
        out.append(f"| {_cell(r['gate'])} | {where} | {_cell(r['rule'])} | {r['state']} |")
    if problems:
        out += ["", "OUT OF SCOPE — Phase -1 holds the fix alone:", *(f"- {p}" for p in problems)]
    else:
        out += ["", "IN SCOPE — every changed file is a finding's, the spec's or named with --also. "
                    "The Stage 6 gate run proves the findings fixed; a finding still untouched is an "
                    "`ask` row, or not yet fixed."]
    print("\n".join(out))
    log(f"  verdict: {'OUT OF SCOPE' if problems else 'IN SCOPE'} ({len(problems)} problem(s))")
    return 1 if problems else 0


# --------------------------------------------------------------------------- cli


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="baseline-gates", description=__doc__.split("\n\n")[0])
    p.add_argument("--repo", help="repository root (default: nearest .git ancestor of cwd)")
    p.add_argument("--config", help="config file")
    p.add_argument("--record", help=f"survey record path (default: the git directory's {RECORD_NAME})")
    p.add_argument("--log", help=f"run log path, or 'off' (default: ${LOG_ENV}, else "
                                 f"~/.copilot/zethus/logs/{LOG_NAME})")
    sub = p.add_subparsers(dest="mode", required=True)
    s = sub.add_parser("survey", help="run every gate on the untouched base and record each failure")
    s.add_argument("--timeout", type=float, default=None, help="per-gate timeout in seconds")
    c = sub.add_parser("scope", help="check Phase -1 changed only what its findings name")
    c.add_argument("--since", help="the surveyed commit (default: the record's)")
    c.add_argument("--also", action="append", metavar="PATH",
                   help="a file the fix truly needs that no finding names (repeatable)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log = RunLog(run_log_path(args.log, LOG_ENV, LOG_NAME))
    log(f"baseline-gates: start mode={args.mode} repo={Path(args.repo).name if args.repo else '(cwd)'} "
        f"config={args.config or '(resolved)'} record={args.record or '(git dir)'}")
    try:
        code = survey(args, log) if args.mode == "survey" else scope(args, log)
    except UsageError as exc:
        log(f"  usage error: {exc}")
        log("baseline-gates: exit 2")
        log.close()
        print(f"baseline-gates: {exc}", file=sys.stderr)
        return 2
    except Exception:
        log("baseline-gates: unexpected error\n" + traceback.format_exc().rstrip())
        log.close()
        raise
    log(f"baseline-gates: exit {code}")
    log.close()
    return code


if __name__ == "__main__":
    sys.exit(main())

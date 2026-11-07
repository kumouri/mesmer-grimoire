#!/usr/bin/env python3
"""Run a repository's lint / build / test gates locally and print a PASS/FAIL table.

The rule this serves: every gate CI would run goes green on your machine before you push. CI's
job is to prove a *different* machine agrees, not to be where you first learn a gate is red.

Where the gates come from, in order:

1. ``gates.steps`` in the config — an ordered list of ``{"name", "command"}``; ``command`` is a
   string or an argv list. An optional ``"exitCode"`` sets the expected exit code (default 0).
2. The Amphion-shaped keys ``gates.lint`` / ``gates.build`` / ``gates.test`` (run in that order),
   plus ``gates.mandatedChecks[]``. A mandated check with no ``exitCode`` has only a prose
   ``expect``, which a script cannot judge — it is listed as MANUAL, and counted as not checked.
3. Discovery from repo evidence: ``package.json`` scripts, ``Makefile`` targets, Python
   (ruff / pytest / unittest), Gradle, Maven, .NET, Go, Cargo. A Maven or Gradle wrapper in the
   repo (``mvnw.cmd`` / ``gradlew.bat`` on Windows, ``mvnw`` / ``gradlew`` elsewhere) is preferred
   over the tool on PATH, because CI usually runs the wrapper's pinned version.

The config is the first one found of ``.github/zethus.config.json``, ``$ZETHUS_CONFIG``,
``.copilot/zethus.config.json``, ``.claude/amphion.config.json`` and ``~/.copilot/zethus/config.json``.

Rules it keeps, because each one is a way a local run lies:

- **It checks the working tree on disk, not HEAD.** The header says how many files are modified
  or untracked, so "green" is never mistaken for "green on what I committed".
- **A skipped gate is not a passed gate.** A missing toolchain is SKIP with the reason; the
  verdict says in words that the run was incomplete, and the exit code differs from a full green.
- **The verdict is the command's exit code.** Output is never parsed to decide PASS/FAIL.
- **No shell.** Commands run as argv lists; a config string is split with ``shlex``.
- **Windows wrappers resolve like a shell would.** A bare ``mvn`` or ``./mvnw`` finds ``mvn.cmd`` /
  ``mvnw.cmd`` through ``PATHEXT``. An extensionless file (the POSIX ``mvnw`` script beside
  ``mvnw.cmd``) is never picked on Windows, because Windows can't execute it.

- **Every gate is green before a phase pushes, whatever the plan says.** A red gate is fixed in the
  phase being pushed, even when the plan put its remediation in a later phase; the RED verdict
  says so. The one exception is a ``push-red`` ruling the person approved in a signed-off spec's
  ``## Gate remediation`` section (see ``_gate_rulings.py``): that gate may stay red, the table
  marks it, and the exit code is 4 so it can't pass for a full green.

Exit codes: 0 every gate ran and passed (or the ``--only`` selection did) · 1 a gate failed ·
2 usage error or no gates found · 3 nothing failed but some gates did not run · 4 every failure
is a gate the approved plan lets stay red, and everything else passed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import UsageError, cfg, find_repo_root, git, load_config, rel  # noqa: E402
from _gate_rulings import active_rulings  # noqa: E402

TAIL_LINES = 40


@dataclass
class Gate:
    name: str
    argv: list[str]
    source: str
    expect_exit: int = 0
    manual: str | None = None          # prose expectation a script can't judge
    status: str = "PENDING"            # PASS | FAIL | SKIP | MANUAL
    seconds: float | None = None
    note: str = ""
    output: str = field(default="", repr=False)

    @property
    def display(self) -> str:
        # The table gets pasted into PRs: show "python", never this machine's interpreter path.
        argv = ["python" if a == sys.executable else a for a in self.argv]
        return " ".join(shlex.quote(a) if " " in a else a for a in argv)


# --------------------------------------------------------------------------- discovery


def _split(command) -> list[str]:
    if isinstance(command, list):
        if not command or not all(isinstance(a, str) for a in command):
            raise UsageError("a gate command list must be non-empty strings")
        return list(command)
    if isinstance(command, str) and command.strip():
        return _split_windows(command) if os.name == "nt" else shlex.split(command)
    raise UsageError(f"gate command must be a string or list, got {command!r}")


def _split_windows(command: str) -> list[str]:
    # shlex(posix=False) keeps the quotes; strip one matched pair per token.
    return [t[1:-1] if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'" else t
            for t in shlex.split(command, posix=False)]


def gates_from_config(config: dict) -> list[Gate]:
    gates: list[Gate] = []
    steps = cfg(config, "gates.steps")
    if steps:
        if not isinstance(steps, list):
            raise UsageError("gates.steps must be a list")
        for i, step in enumerate(steps):
            if not isinstance(step, dict) or "command" not in step:
                raise UsageError(f"gates.steps[{i}] needs a 'command'")
            name = str(step.get("name") or f"step-{i + 1}")
            gates.append(Gate(name, _split(step["command"]), "config",
                              expect_exit=int(step.get("exitCode", 0))))
        return gates
    for key in ("lint", "build", "test"):
        command = cfg(config, f"gates.{key}")
        if command:
            gates.append(Gate(key, _split(command), "config"))
    for i, check in enumerate(cfg(config, "gates.mandatedChecks", []) or []):
        if not isinstance(check, dict) or "command" not in check:
            raise UsageError(f"gates.mandatedChecks[{i}] needs a 'command'")
        name = str(check.get("name") or f"mandated-{i + 1}")
        if "exitCode" in check:
            gates.append(Gate(name, _split(check["command"]), "config",
                              expect_exit=int(check["exitCode"])))
        else:
            gates.append(Gate(name, _split(check["command"]), "config",
                              manual=str(check.get("expect") or "see config")))
    return gates


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _wrapper(repo: Path, name: str) -> str | None:
    """``./mvnw.cmd`` (Windows) or ``./mvnw`` (elsewhere) if the repo ships that wrapper.

    Returned repo-relative with ``./`` so the table pasted into a PR never shows a host path.
    """
    for candidate in ((f"{name}.cmd", f"{name}.bat") if os.name == "nt" else (name,)):
        if (repo / candidate).is_file():
            return "./" + candidate
    return None


def discover(repo: Path) -> tuple[list[Gate], list[str]]:
    """Gates inferred from build files. Returns ``(gates, evidence_files)``."""
    gates: list[Gate] = []
    evidence: list[str] = []
    py = sys.executable or "python"

    pkg = repo / "package.json"
    if pkg.is_file():
        try:
            scripts = json.loads(_read(pkg)).get("scripts", {}) or {}
        except (json.JSONDecodeError, AttributeError):
            scripts = {}
        pm = ("pnpm" if (repo / "pnpm-lock.yaml").exists() else
              "yarn" if (repo / "yarn.lock").exists() else
              "bun" if (repo / "bun.lockb").exists() or (repo / "bun.lock").exists() else "npm")
        found = [k for k in ("lint", "typecheck", "build", "test") if k in scripts]
        for key in found:
            gates.append(Gate(key, [pm, "run", key], "package.json"))
        if found:
            evidence.append("package.json")

    makefile = repo / "Makefile"
    if makefile.is_file():
        targets = set(re.findall(r"^(lint|check|build|test)\s*:", _read(makefile), re.M))
        ordered = [t for t in ("lint", "check", "build", "test") if t in targets]
        for t in ordered:
            gates.append(Gate(f"make {t}", ["make", t], "Makefile"))
        if ordered:
            evidence.append("Makefile")

    pyproject = _read(repo / "pyproject.toml")
    py_markers = [p for p in ("pyproject.toml", "setup.py", "setup.cfg") if (repo / p).is_file()]
    tests_dir = repo / "tests"
    has_py_tests = tests_dir.is_dir() and any(tests_dir.rglob("test*.py"))
    if py_markers or has_py_tests:
        if "[tool.ruff" in pyproject or (repo / "ruff.toml").is_file() or (repo / ".ruff.toml").is_file():
            gates.append(Gate("ruff", ["ruff", "check", "."], "python"))
        pytest_hint = ("pytest" in pyproject or (repo / "pytest.ini").is_file()
                       or (repo / "conftest.py").is_file() or "pytest" in _read(repo / "setup.cfg")
                       or "pytest" in _read(repo / "tox.ini"))
        if pytest_hint:
            gates.append(Gate("pytest", [py, "-m", "pytest"], "python"))
        elif has_py_tests:
            gates.append(Gate("unittest", [py, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                              "python"))
        evidence.extend(py_markers or ["tests/"])

    gradlew = _wrapper(repo, "gradlew")
    if gradlew:
        gates.append(Gate("gradle check", [gradlew, "check"], "gradle"))
        evidence.append(gradlew[2:])
    elif (repo / "pom.xml").is_file():
        mvnw = _wrapper(repo, "mvnw")
        gates.append(Gate("maven verify", [mvnw or "mvn", "-B", "verify"], "maven"))
        evidence.append("pom.xml" + (f" + {mvnw[2:]}" if mvnw else ""))

    if any(repo.glob("*.sln")) or any(repo.glob("*.csproj")):
        gates.append(Gate("dotnet build", ["dotnet", "build"], "dotnet"))
        gates.append(Gate("dotnet test", ["dotnet", "test", "--no-build"], "dotnet"))
        evidence.append("*.sln/*.csproj")

    if (repo / "go.mod").is_file():
        gates.append(Gate("go vet", ["go", "vet", "./..."], "go"))
        gates.append(Gate("go test", ["go", "test", "./..."], "go"))
        evidence.append("go.mod")

    if (repo / "Cargo.toml").is_file():
        gates.append(Gate("cargo test", ["cargo", "test"], "cargo"))
        evidence.append("Cargo.toml")

    return gates, evidence


# --------------------------------------------------------------------------- running


def _pathext() -> list[str]:
    raw = os.environ.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD"
    return [e.lower() for e in raw.split(";") if e.strip()]


def _windows_candidates(base: Path) -> list[Path]:
    """What ``cmd.exe`` would try for ``base``: as given if it has a PATHEXT suffix, else each
    PATHEXT suffix in order. An extensionless file is never a candidate: CreateProcess can't run
    it, and in a Maven checkout ``mvnw`` (a POSIX script) sits right beside ``mvnw.cmd``."""
    exts = _pathext()
    if base.suffix.lower() in exts:
        return [base]
    return [base.with_name(base.name + ext) for ext in exts]


def resolve(argv0: str, repo: Path, *, windows: bool | None = None,
            path: str | None = None) -> str | None:
    """Find the executable for ``argv0`` the way a shell would, without using one.

    ``windows`` and ``path`` exist so tests can exercise the Windows rules on any OS.
    """
    windows = (os.name == "nt") if windows is None else windows
    has_dir = "/" in argv0 or os.sep in argv0 or (windows and "\\" in argv0)
    if has_dir:
        base = Path(argv0) if Path(argv0).is_absolute() else repo / argv0
        candidates = _windows_candidates(base) if windows else [base]
        return next((str(c) for c in candidates if c.is_file()), None)
    if not windows:
        return shutil.which(argv0, path=path)
    # An explicit PATHEXT walk rather than shutil.which: its Windows rules have changed across
    # Python versions, and ``mvn`` beside ``mvn.cmd`` in Maven's bin/ is exactly the trap.
    search = os.environ.get("PATH", "") if path is None else path
    for folder in filter(None, search.split(os.pathsep)):
        for candidate in _windows_candidates(Path(folder) / argv0):
            if candidate.is_file():
                return str(candidate)
    return None


def run_gate(gate: Gate, repo: Path, timeout: float | None) -> None:
    if gate.manual is not None:
        gate.status, gate.note = "MANUAL", f"expect: {gate.manual}"
        return
    exe = resolve(gate.argv[0], repo)
    if exe is None:
        gate.status, gate.note = "SKIP", f"`{gate.argv[0]}` not found on PATH"
        return
    start = time.monotonic()
    try:
        proc = subprocess.run([exe, *gate.argv[1:]], cwd=repo, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        gate.seconds = time.monotonic() - start
        gate.status, gate.note = "FAIL", f"timed out after {timeout:g}s"
        out = exc.output or ""
        gate.output = out if isinstance(out, str) else out.decode("utf-8", "replace")
        return
    except OSError as exc:
        gate.seconds = time.monotonic() - start
        gate.status, gate.note = "FAIL", f"could not start: {exc.strerror or exc}"
        return
    gate.seconds = time.monotonic() - start
    gate.output = proc.stdout or ""
    if proc.returncode == gate.expect_exit:
        gate.status = "PASS"
        if gate.expect_exit:
            gate.note = f"exit {proc.returncode} (expected)"
    else:
        gate.status = "FAIL"
        gate.note = f"exit {proc.returncode}" + (f", expected {gate.expect_exit}" if gate.expect_exit else "")


def tree_state(repo: Path) -> str:
    proc = git(repo, "status", "--porcelain")
    if proc is None or proc.returncode != 0:
        return "not a git work tree — checked files on disk"
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    untracked = sum(1 for ln in lines if ln.startswith("??"))
    modified = len(lines) - untracked
    if not lines:
        return "working tree clean — checks HEAD's content"
    return (f"checks the working tree on disk, not HEAD "
            f"({modified} modified, {untracked} untracked)")


def verdict(gates: list[Gate], selected: bool, waivers: dict | None = None) -> tuple[str, int]:
    """``waivers`` maps lower-cased gate names to approved ``push-red`` rulings."""
    waivers = waivers or {}
    failed = [g.name for g in gates if g.status == "FAIL" and g.name.lower() not in waivers]
    allowed = [g.name for g in gates if g.status == "FAIL" and g.name.lower() in waivers]
    unchecked = [g.name for g in gates if g.status in ("SKIP", "MANUAL")]
    if failed:
        return ("RED — fix before pushing: " + ", ".join(failed)
                + ". Fix each in the phase being pushed, as small a fix as turns it green, even if the "
                  "plan puts its remediation in a later phase; don't stop to ask, and say in the "
                  "phase's report that it was pulled forward and why"), 1
    if allowed:
        note = "; ".join(f"{waivers[n.lower()].gate} ({waivers[n.lower()].spec})" for n in allowed)
        tail = f"push-red approved in the plan for: {note}. Say in the PR that these gates are red"
        if unchecked:
            return (f"GREEN on what ran, but {len(unchecked)} gate(s) NOT checked: "
                    + ", ".join(unchecked) + f" — not a full run. {tail}"), 3
        return f"GREEN except gate(s) the approved plan lets stay red: {', '.join(allowed)} — {tail}", 4
    if unchecked:
        return (f"GREEN on what ran, but {len(unchecked)} gate(s) NOT checked: "
                + ", ".join(unchecked) + " — not a full run; say so in the PR"), 3
    if selected:
        return f"GREEN on the {len(gates)} selected gate(s) — not a full run", 0
    return "GREEN — every gate ran and passed", 0


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def render(gates: list[Gate], header: str, source: str, verbose: bool) -> str:
    out = [f"run-local-gates — {header}", f"Gates from: {source}", "",
           "| Gate | Result | Time | Command | Note |", "|---|---|---|---|---|"]
    for g in gates:
        secs = f"{g.seconds:.1f}s" if g.seconds is not None else "–"
        out.append(f"| {_cell(g.name)} | {g.status} | {secs} | `{_cell(g.display)}` | {_cell(g.note)} |")
    counts = {s: sum(1 for g in gates if g.status == s) for s in ("PASS", "FAIL", "SKIP", "MANUAL")}
    out += ["", f"{counts['PASS']} passed, {counts['FAIL']} failed, {counts['SKIP']} skipped, "
                f"{counts['MANUAL']} manual (of {len(gates)})"]
    for g in gates:
        if g.output and (verbose or g.status == "FAIL"):
            lines = g.output.rstrip().splitlines()
            shown = lines if verbose else lines[-TAIL_LINES:]
            label = "output" if verbose or len(lines) <= TAIL_LINES else f"last {TAIL_LINES} lines"
            out += ["", f"--- {g.name} ({label}) ---", *shown]
    return "\n".join(out)


# --------------------------------------------------------------------------- cli


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="run-local-gates",
                                description="Run the repo's gates locally; print a PASS/FAIL table.")
    p.add_argument("--repo", help="repository root (default: nearest .git ancestor of cwd)")
    p.add_argument("--config", help="config file (default: the first of .github/zethus.config.json, "
                                    "$ZETHUS_CONFIG, .copilot/zethus.config.json, "
                                    ".claude/amphion.config.json, ~/.copilot/zethus/config.json)")
    p.add_argument("--only", action="append", metavar="GATE", help="run only this gate (repeatable)")
    p.add_argument("--list", action="store_true", help="list the gates and exit")
    p.add_argument("--timeout", type=float, default=None, help="per-gate timeout in seconds")
    p.add_argument("-v", "--verbose", action="store_true", help="print every gate's full output")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repo = Path(args.repo).resolve() if args.repo else find_repo_root()
        config, config_path = load_config(repo, args.config)
        gates = gates_from_config(config)
        if gates:
            source = rel(config_path, repo)
        else:
            gates, evidence = discover(repo)
            source = "auto-discovered from " + (", ".join(evidence) or "nothing")
        if not gates:
            print("run-local-gates: no gates found. Add gates.steps to .github/zethus.config.json, "
                  "or to an untracked .copilot/zethus.config.json (see zethus.config.example.json). "
                  "No gates is not a green run.")
            return 2
        if args.only:
            names = {g.name for g in gates}
            unknown = [n for n in args.only if n not in names]
            if unknown:
                raise UsageError(f"unknown gate(s): {', '.join(unknown)}; have: {', '.join(sorted(names))}")
            gates = [g for g in gates if g.name in args.only]
        if args.list:
            for g in gates:
                print(f"{g.name}\t{g.display}\t({g.source})")
            return 0
        for g in gates:
            run_gate(g, repo, args.timeout)
        waivers = {k: r for k, r in active_rulings(repo, cfg(config, "spec.dir", "docs/specs")).items()
                   if r.waives}
        for g in gates:
            if g.status == "FAIL" and g.name.lower() in waivers:
                g.note = (g.note + "; " if g.note else "") + f"red allowed by the plan ({waivers[g.name.lower()].spec})"
        text, code = verdict(gates, selected=bool(args.only), waivers=waivers)
        print(render(gates, tree_state(repo), source, args.verbose))
        print()
        print(text)
        return code
    except UsageError as exc:
        print(f"run-local-gates: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

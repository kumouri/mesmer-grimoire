#!/usr/bin/env python3
"""Check that a spec states, prominently and answerably, any gate its plan leaves for a later phase.

The rule this serves: every local gate (SonarQube, lint, a type check, anything in ``gates.steps``)
is green before a phase pushes. A plan that schedules a remediation phase for what a gate checks
would leave phase 0 unable to push, so that fact must sit in the plan the person signs, in a
``## Gate remediation`` section, with the person's ruling recorded where a later phase and a later
session can read it. ``run-local-gates`` reads the same section. Prose alone didn't make a plan
state this, so this check does.

    python <kit root>/scripts/gate-remediation-check.py docs/specs/my-change.md
    python <kit root>/scripts/gate-remediation-check.py            # every live spec in spec.dir

It fails (exit 1) when:

* a spec has no ``## Gate remediation`` section (``None — …`` is a complete answer);
* the section says ``None`` but a Phases row reads like remediation of what a gate checks;
* a table row has an unreadable ruling, or ``other`` with no text;
* the spec is ``SIGNED-OFF`` / ``PARTIAL`` / ``BUILT`` and a row is still ``PENDING``, or names a
  gate that is not one of the repo's gates (when the gates can be listed).

A ``DRAFT`` spec may carry ``PENDING`` rows: that is the question waiting for the person.
``MEMO`` specs build nothing and are skipped. Exit codes: 0 fine · 1 problems · 2 usage error.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _gate_rulings as gr  # noqa: E402
from _common import UsageError, cfg, find_repo_root, load_config, rel  # noqa: E402


def gate_names(repo: Path, config: dict) -> set[str] | None:
    """The repo's gate names, or ``None`` if they can't be listed (then names aren't checked)."""
    try:
        path = Path(__file__).resolve().parent / "run-local-gates.py"
        spec = importlib.util.spec_from_file_location("run_local_gates", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        gates = mod.gates_from_config(config) or mod.discover(repo)[0]
        return {g.name.lower() for g in gates} or None
    except Exception:
        return None


def check_spec(text: str, names: set[str] | None) -> list[str]:
    status = gr.status_of(text)
    if status == "MEMO":
        return []
    problems: list[str] = []
    rows, has_section, says_none = gr.parse(text)
    if not has_section:
        return ["no `## Gate remediation` section: add it, with `None — …` if no phase remediates "
                "anything a local gate checks"]
    remediation = gr.remediation_phase_rows(text)
    if says_none and remediation:
        problems.append("the section says None, but a phase reads like gate remediation: "
                        + remediation[0][:100])
    if not says_none and not rows:
        problems.append("the section is neither `None — …` nor a table with a row")
    settled = status != "DRAFT" and status != ""
    for r in rows:
        if not r.kind:
            problems.append(f"{r.gate}: ruling `{r.detail}` is not one of {', '.join(gr.RULINGS)}")
        elif r.kind == "other" and not r.detail:
            problems.append(f"{r.gate}: ruling `other` must name the equivalent, as `other: <what>`")
        if settled and not r.approved:
            problems.append(f"{r.gate}: spec is {status} but the ruling is not approved "
                            "(`yes — who, when`)")
        if names is not None and r.gate.lower() not in names:
            problems.append(f"{r.gate}: not one of this repo's gates ({', '.join(sorted(names))})")
    return problems


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="gate-remediation-check", description=__doc__.split("\n\n")[0])
    p.add_argument("specs", nargs="*", help="spec files (default: every spec in spec.dir)")
    p.add_argument("--repo", help="repository root (default: nearest .git ancestor of cwd)")
    p.add_argument("--config", help="config file")
    args = p.parse_args(argv)
    try:
        repo = Path(args.repo).resolve() if args.repo else find_repo_root()
        config, _ = load_config(repo, args.config)
        files = [Path(s) if Path(s).is_absolute() else Path.cwd() / s for s in args.specs]
        if not files:
            folder = repo / cfg(config, "spec.dir", "docs/specs")
            live = ("DRAFT", "SIGNED-OFF", "PARTIAL")   # a BUILT or MEMO spec has nothing left to decide
            files = [f for f in sorted(folder.rglob("*.md")) if folder.is_dir()
                     and gr.status_of(f.read_text(encoding="utf-8", errors="replace")).startswith(live)]
        if not files:
            print("gate-remediation-check: no specs found")
            return 0
        names = gate_names(repo, config)
        bad = 0
        for f in files:
            if not f.is_file():
                raise UsageError(f"no such file: {f}")
            problems = check_spec(f.read_text(encoding="utf-8", errors="replace"), names)
            label = rel(f.resolve(), repo)
            if problems:
                bad += 1
                print(f"FAIL {label}")
                for item in problems:
                    print(f"  - {item}")
            else:
                print(f"ok   {label}")
        return 1 if bad else 0
    except UsageError as exc:
        print(f"gate-remediation-check: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

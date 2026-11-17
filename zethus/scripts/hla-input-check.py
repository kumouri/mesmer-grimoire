#!/usr/bin/env python3
"""Check the target High-Level Architecture (HLA) document is supplied, before Stage 2 (Spec).

**Decided (2026-09-28, `docs/batch-modernization.md`):** there is no hardcoded default
keep/wrap/port disposition for a stored procedure. A target HLA document is a **required pipeline
input**, and the default disposition for a procedure with no procedure-specific rule is read from
it. **If no HLA is supplied, the pipeline stops before Stage 2 and asks for one** — this script is
that stop, built the same way ``base-freshness.py`` gates Stage 0: one exit code, no guessing.

The HLA is free-form prose except for one required line, anywhere in the document, of this shape
(case-insensitive throughout; the disposition word must still be one of the three allowed words):

    Default stored-procedure disposition: keep|wrap|port

A recovered business rule can still override that default for one specific procedure; this script
only checks that a *pipeline-level* default exists and is one of the three allowed words — it says
nothing about any one procedure's override, which lives in the rule ledger instead.

Exit codes: 0 HLA found with a parseable default · 1 no HLA configured, or found but the default
line is missing/unparseable — don't assume · 2 usage error. On 1 the agent does the lookup
itself: a missing or moved HLA is searched for in the repo (the message lists the candidates), and
only the disposition, which is the person's decision, is asked, and then written into the HLA by
the agent.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import UsageError, cfg, find_repo_root, hla_lookup, load_config, rel  # noqa: E402

DISPOSITIONS = ("keep", "wrap", "port")
DEFAULT_LINE_RE = re.compile(
    r"^\s*Default stored-procedure disposition\s*:\s*(?P<disposition>\w+)\s*$", re.I | re.M,
)


def find_default_disposition(text: str) -> str | None:
    m = DEFAULT_LINE_RE.search(text)
    if not m:
        return None
    word = m.group("disposition").lower()
    return word if word in DISPOSITIONS else None


def check(repo: Path, config: dict, explicit: str | None) -> tuple[int, str]:
    hla = explicit or cfg(config, "modernization.hlaDoc")
    if not hla:
        return 1, hla_lookup(repo, "no HLA document configured (modernization.hlaDoc, or --hla); "
                                   "Stage 2 can't start without one.")
    path = Path(hla) if Path(hla).is_absolute() else repo / hla
    if not path.is_file():
        return 1, hla_lookup(repo, f"modernization.hlaDoc points at {hla!r}, but no such file "
                                   "exists; it may have moved.")
    text = path.read_text(encoding="utf-8", errors="replace")
    disposition = find_default_disposition(text)
    if disposition is None:
        return 1, (f"{rel(path, repo)} exists but has no parseable "
                   "'Default stored-procedure disposition: keep|wrap|port' line. The disposition "
                   "is the person's decision: ask it with the question tool (keep, wrap or port, "
                   "your recommendation from the HLA's own prose first), then write the line into "
                   "the HLA yourself and re-run. Not assuming one.")
    return 0, (f"HLA input satisfied: {rel(path, repo)}, default stored-procedure disposition "
              f"= {disposition}. Recovered rules may still override this per procedure.")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="hla-input-check",
                                description="Require a target HLA doc with a default disposition "
                                            "before Stage 2 can start.")
    p.add_argument("--repo", help="repository root (default: nearest .git ancestor of cwd)")
    p.add_argument("--config", help="config file")
    p.add_argument("--hla", help="override modernization.hlaDoc")
    args = p.parse_args(argv)
    try:
        repo = Path(args.repo).resolve() if args.repo else find_repo_root()
        config, _ = load_config(repo, args.config)
        code, message = check(repo, config, args.hla)
    except UsageError as exc:
        print(f"hla-input-check: {exc}", file=sys.stderr)
        return 2
    print(f"hla-input-check: {message}")
    return code


if __name__ == "__main__":
    sys.exit(main())

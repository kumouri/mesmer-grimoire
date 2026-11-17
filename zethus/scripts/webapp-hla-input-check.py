#!/usr/bin/env python3
"""Check the target HLA document names a frontend and an auth strategy, before Stage 2 (Spec), for
the legacy web-app modernization extension. Sibling to ``hla-input-check.py`` (the batch extension's
stored-procedure-disposition gate) — same HLA document, two more required lines, checked
independently so a missing frontend doesn't hide a missing auth answer or vice versa.

**Decided (2026-09-28, `docs/webapp-modernization.md`, Telegram pickers):**

- **Frontend has no hardcoded default** (not React+Vite, not Next.js). It is read from the HLA; if
  the HLA names none, this script stops and asks. The frontend line is free text — any name the HLA
  gives is honored, including Angular for the hybrid target shape this build's readers understand.
- **Auth strategy has no hardcoded default either.** It is read from the HLA as one of two words,
  ``shim`` or ``replace``; if the HLA doesn't say, this script stops and asks, and that ask
  *recommends* ``shim`` (preserve exact legacy authz behind an interface; replacing the mechanism
  with OAuth2/OIDC is a later, separately decided phase) — a recommendation in the message, never a
  silently assumed value.

Required lines, anywhere in the document (case-insensitive labels; the auth word must still be one
of the two allowed words):

    Frontend: <any name>
    Auth strategy: shim|replace

Exit codes: 0 both fields found and parseable · 1 no HLA configured, or one or both fields missing/
unparseable — don't assume · 2 usage error. On 1 a missing or moved HLA is the agent's to find
(the message lists candidate docs in the repo); a missing frontend or auth answer is the person's
decision, asked with the question tool and then written into the HLA by the agent.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import UsageError, cfg, find_repo_root, hla_lookup, load_config, rel  # noqa: E402

AUTH_STRATEGIES = ("shim", "replace")
FRONTEND_LINE_RE = re.compile(r"^\s*Frontend\s*:\s*(?P<frontend>\S.*?)\s*$", re.I | re.M)
AUTH_LINE_RE = re.compile(r"^\s*Auth strategy\s*:\s*(?P<strategy>\w+)\s*$", re.I | re.M)


def find_frontend(text: str) -> str | None:
    m = FRONTEND_LINE_RE.search(text)
    return m.group("frontend").strip() if m else None


def find_auth_strategy(text: str) -> str | None:
    m = AUTH_LINE_RE.search(text)
    if not m:
        return None
    word = m.group("strategy").lower()
    return word if word in AUTH_STRATEGIES else None


def _hla_path(repo: Path, config: dict, explicit: str | None) -> Path | None:
    hla = explicit or cfg(config, "modernization.hlaDoc")
    if not hla:
        return None
    return Path(hla) if Path(hla).is_absolute() else repo / hla


def check(repo: Path, config: dict, explicit: str | None) -> tuple[int, list[str]]:
    hla = explicit or cfg(config, "modernization.hlaDoc")
    if not hla:
        return 1, [hla_lookup(repo, "no HLA document configured (modernization.hlaDoc, or --hla); "
                                    "Stage 2 can't start without one.")]
    path = _hla_path(repo, config, explicit)
    if not path.is_file():
        return 1, [hla_lookup(repo, f"modernization.hlaDoc points at {hla!r}, but no such file "
                                    "exists; it may have moved.")]
    text = path.read_text(encoding="utf-8", errors="replace")
    gaps: list[str] = []
    frontend = find_frontend(text)
    if frontend is None:
        gaps.append(f"{rel(path, repo)} names no frontend ('Frontend: <name>' line missing). "
                   "There is no hardcoded default (not React+Vite, not Next.js): ask the person with "
                   "the question tool, then write the line into the HLA yourself and re-run.")
    strategy = find_auth_strategy(text)
    if strategy is None:
        gaps.append(f"{rel(path, repo)} has no parseable 'Auth strategy: shim|replace' line. "
                   "Not assuming either: ask the person with the question tool, then write the "
                   "line into the HLA yourself and re-run. Recommend: shim first — preserve the "
                   "exact legacy authz behaviour behind an interface; replacing the mechanism with "
                   "OAuth2/OIDC is a later, separately decided phase.")
    if gaps:
        return 1, gaps
    return 0, [f"webapp HLA input satisfied: {rel(path, repo)} — frontend = {frontend!r}, "
              f"auth strategy = {strategy}. A recovered rule can still override the auth default "
              "for one specific check."]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="webapp-hla-input-check",
                                description="Require a target HLA doc naming a frontend and an "
                                            "auth strategy before Stage 2 can start.")
    p.add_argument("--repo", help="repository root (default: nearest .git ancestor of cwd)")
    p.add_argument("--config", help="config file")
    p.add_argument("--hla", help="override modernization.hlaDoc")
    args = p.parse_args(argv)
    try:
        repo = Path(args.repo).resolve() if args.repo else find_repo_root()
        config, _ = load_config(repo, args.config)
        code, messages = check(repo, config, args.hla)
    except UsageError as exc:
        print(f"webapp-hla-input-check: {exc}", file=sys.stderr)
        return 2
    for m in messages:
        print(f"webapp-hla-input-check: {m}")
    return code


if __name__ == "__main__":
    sys.exit(main())

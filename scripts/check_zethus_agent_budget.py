#!/usr/bin/env python3
"""Keep Zethus's Copilot agent file well under Copilot's limit, so an edit can't silently cross it.

GitHub's custom-agent reference caps an agent's prompt at 30,000 characters. This check holds the
agent file to a stricter budget so there is always room to edit it:

* over ``--max`` (default 28,000) it fails;
* over ``--warn`` (default 24,000) it passes and prints a warning: move detail out before adding.

It counts ``len()`` of the whole file as text, frontmatter included. The reference doesn't say
whether frontmatter is part of "the prompt", so counting it is the stricter reading.

With no paths it checks both copies in this repo: the canonical
``zethus/com.github.copilot/agents/zethus.agent.md`` and its generated IntelliJ mirror
``zethus/agents/zethus.agent.md`` (whose header makes it a little longer). Pass paths to check any
other copy, such as your own edited one. ``ZETHUS_AGENT_MAX_CHARS`` and ``ZETHUS_AGENT_WARN_CHARS``
change the defaults; the flags beat them. ``tests/test_zethus_agent_budget.py`` runs it in CI.
Where the detail goes instead: ``zethus/docs/agent-file-budget.md``.

    python scripts/check_zethus_agent_budget.py
    python scripts/check_zethus_agent_budget.py path/to/zethus.agent.md --max 29000 --warn 26000

Exit codes: 0 within budget (warnings allowed) · 1 over budget, or a file is missing · 2 usage error.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
AGENT_FILES = (REPO / "zethus" / "com.github.copilot" / "agents" / "zethus.agent.md",
               REPO / "zethus" / "agents" / "zethus.agent.md")
COPILOT_LIMIT = 30_000
DEFAULT_MAX = 28_000
DEFAULT_WARN = 24_000


def limits(env: dict[str, str] | None = None) -> tuple[int, int]:
    """The (max, warn) defaults, after any environment override."""
    env = os.environ if env is None else env
    return (int(env.get("ZETHUS_AGENT_MAX_CHARS", DEFAULT_MAX)),
            int(env.get("ZETHUS_AGENT_WARN_CHARS", DEFAULT_WARN)))


def measure(path: Path) -> int:
    return len(path.read_text(encoding="utf-8"))


def verdict(size: int, max_chars: int, warn_chars: int) -> str:
    """``over``, ``warn`` or ``ok``."""
    if size > max_chars:
        return "over"
    return "warn" if size > warn_chars else "ok"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("paths", nargs="*", type=Path, help="agent files (default: both repo copies)")
    parser.add_argument("--max", type=int, dest="max_chars", help="fail above this many characters")
    parser.add_argument("--warn", type=int, dest="warn_chars", help="warn above this many characters")
    try:
        args = parser.parse_args(argv)
        env_max, env_warn = limits()
    except ValueError as exc:
        print(f"check_zethus_agent_budget: bad environment value: {exc}", file=sys.stderr)
        return 2
    except SystemExit as exc:
        return 0 if exc.code == 0 else 2
    max_chars = env_max if args.max_chars is None else args.max_chars
    warn_chars = env_warn if args.warn_chars is None else args.warn_chars
    if not 0 < warn_chars <= max_chars:
        print(f"check_zethus_agent_budget: need 0 < --warn ({warn_chars}) <= --max ({max_chars})",
              file=sys.stderr)
        return 2

    worst = 0
    for path in args.paths or AGENT_FILES:
        if not path.is_file():
            print(f"missing: {path}", file=sys.stderr)
            worst = 1
            continue
        size = measure(path)
        state = verdict(size, max_chars, warn_chars)
        line = (f"{path}: {size:,} characters (budget {max_chars:,}, warn {warn_chars:,}, "
                f"Copilot's limit {COPILOT_LIMIT:,}; {max_chars - size:,} to the budget)")
        if state == "over":
            print(f"OVER BUDGET  {line}", file=sys.stderr)
            worst = 1
        elif state == "warn":
            print(f"warning      {line}: move detail out before adding more", file=sys.stderr)
        else:
            print(f"ok           {line}")
    return worst


if __name__ == "__main__":
    sys.exit(main())

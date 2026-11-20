#!/usr/bin/env python3
"""Say who Zethus is working for, or save the name the person gave.

    python .github/zethus/scripts/identity.py                  # resolve and report
    python .github/zethus/scripts/identity.py --field display  # just the name to write
    python .github/zethus/scripts/identity.py --json
    python .github/zethus/scripts/identity.py --save --name "Alex Example" [--handle alexex] [--to repo]

Every doc Zethus writes that records who asked for, approved or decided something uses this name,
as the person wrote it. The agent runs it at Stage 0 (Orient). The plugin's ``sessionStart`` hook
announces its answer too, without the forge step, so the session starts knowing.

**Resolution order** (detail in ``_identity.py``): config ``identity.name`` / ``identity.handle``,
most personal config first; then ``git config user.name``; then the forge account (``gh api user``),
tried only when both gave nothing; then nothing. Each step goes to the run log with what it gave
and which source won; values are never logged.

**When nothing is found** it exits 1 and says so. The agent then asks the person once, with the
harness's question tool, for the name they want recorded, offers to save it, and on a yes runs
``--save``. It never writes a placeholder instead.

**--save** merges ``identity`` into a config without touching its other keys: ``--to user`` (the
default) writes ``~/.copilot/zethus/config.json``, read in every repo; ``--to repo`` writes this
repo's untracked ``.copilot/zethus.config.json``. Neither writes the committed
``.github/zethus.config.json``: a team's shared config must not name one person. A placeholder
(``TBD``, ``Requester``, ``<name>`` …) is refused.

Exit codes: 0 resolved, or saved · 1 not resolved: ask the person · 2 usage error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import UsageError, find_repo_root, rel, user_home  # noqa: E402
from _identity import AGENT, RunLog, log_path, resolve, save  # noqa: E402

STEP_NAMES = {1: "config", 2: "git", 3: "forge account"}


def report(found, log: RunLog) -> str:
    lines = []
    if found.resolved:
        extra = f" (handle: {found.handle})" if found.name and found.handle else ""
        lines.append(f"Working for: {found.display}{extra}. Source: {found.source} "
                     f"(step {found.step} of 3, {STEP_NAMES[found.step]}).")
    else:
        lines.append("Working for: not resolved. Config, git and the forge account gave no name.")
    lines += [f"  {line}" for line in found.trace]
    if found.resolved:
        lines.append(f"Write \"{found.display}\", exactly as written, wherever a doc records who "
                     "asked for, approved or decided something. The text's author is recorded "
                     f"apart, as {AGENT}; the agent is never the approver or the decider.")
    else:
        lines.append("Ask the person once, with the question tool, for the name they want "
                     "recorded, and offer to save it: identity.py --save --name \"<their name>\". "
                     "Never write a placeholder such as TBD or Requester instead.")
    if log.path is not None:
        lines.append(f"Run log: {rel(log.path, Path.cwd())}" + (f" ({log.error})" if log.error else ""))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="identity", description="Resolve or save who Zethus works for.")
    p.add_argument("--field", choices=("display", "name", "handle", "source"),
                   help="print only this field (exit 1, nothing printed, if unresolved)")
    p.add_argument("--json", action="store_true", help="print the result as JSON")
    p.add_argument("--no-forge", action="store_true",
                   help="skip step 3 (gh api user), e.g. where no network call may be made")
    p.add_argument("--save", action="store_true", help="save --name/--handle into a config")
    p.add_argument("--name", default="", help="with --save: the name, as the person writes it")
    p.add_argument("--handle", default="", help="with --save: their handle, as they write it")
    p.add_argument("--to", choices=("user", "repo"), default="user",
                   help="with --save: ~/.copilot/zethus/config.json (user, default) or this "
                        "repo's untracked .copilot/zethus.config.json (repo)")
    p.add_argument("--log", help="run log path, or 'off' (default: $ZETHUS_IDENTITY_LOG, else "
                                 "~/.copilot/zethus/logs/identity.log)")
    p.add_argument("--repo", help="repository root (default: nearest .git ancestor of cwd)")
    p.add_argument("--config", help="a config file to read first")
    args = p.parse_args(argv)
    log = RunLog(log_path(args.log))
    try:
        repo = Path(args.repo).resolve() if args.repo else find_repo_root()
        given = sys.argv[1:] if argv is None else argv
        log(f"identity.py: start flags={[a for a in given if a.startswith('--')]} "
            "(values not logged)")
        if args.save:
            target = (user_home() / "config.json" if args.to == "user"
                      else repo / ".copilot" / "zethus.config.json")
            written = save(target, args.name, args.handle, log)
            print(f"saved {', '.join(written)} to {rel(target, repo)}")
            if args.to == "repo":
                print("Keep it out of git with the clone's exclude file, not .gitignore: add "
                      "`.copilot/` to the file `git rev-parse --git-path info/exclude` prints.")
            return 0
        if args.name or args.handle:
            raise UsageError("--name and --handle only go with --save")
        found = resolve(repo, config=args.config, forge=False if args.no_forge else None, log=log)
        if args.json:
            print(json.dumps(found.as_dict(), indent=2, ensure_ascii=False))
        elif args.field:
            if found.resolved:
                print(getattr(found, args.field))
        else:
            print(report(found, log))
        return 0 if found.resolved else 1
    except UsageError as exc:
        log(f"identity.py: usage error: {exc}")
        print(f"identity: {exc}", file=sys.stderr)
        return 2
    finally:
        log.close()


if __name__ == "__main__":
    sys.exit(main())

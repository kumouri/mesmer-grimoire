#!/usr/bin/env python3
"""Zethus plugin ``sessionStart`` hook: put the working agreement in front of the model.

Plugins can't ship always-on instructions (the Copilot CLI doesn't load a plugin's ``rules/``), so
this prints ``copilot-instructions.md`` as ``additionalContext``, with ``<kit root>`` filled in and
a closing note saying where the kit's scripts and templates live. Nothing expands a variable inside
a skill's text, so that note is how a skill finds them. The JSON carries both shapes: the bare key
is what the Copilot CLI read, ``hookSpecificOutput`` is what VS Code documents.

An install.py copy already delivers all of this, so the hook steps aside rather than say it twice:

- a repo with the kit in ``.github/zethus/`` has its own instructions and skills: print nothing;
- a user-mode copy in ``~/.copilot`` has loaded the agreement and shadows this plugin's skills:
  print only how to remove it.

Fail-open: any error prints nothing and exits 0, so it can never break a session.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def repo_has_kit(cwd: str) -> bool:
    """The session's folder, or a parent up to its git root, holds a repo-mode install."""
    if not cwd:
        return False
    here = Path(cwd).resolve()
    for folder in (here, *here.parents):
        if (folder / ".github" / "zethus" / "scripts" / "run-local-gates.py").is_file():
            return True
        if (folder / ".git").exists():
            return False
    return False


def user_copy() -> bool:
    return (Path.home() / ".copilot" / "instructions" / "zethus.instructions.md").is_file()


def agreement() -> str:
    root = ROOT.as_posix()
    text = (ROOT / "copilot-instructions.md").read_text(encoding="utf-8")
    text = text.replace("<kit root>", root).replace("`.github/skills/`", f"`{root}/skills/`")
    return (f"{text}\n\n## Where the Zethus kit is\n\n"
            f"Zethus kit root: `{root}`. Scripts: `{root}/scripts/`. Templates: `{root}/templates/`. "
            "Wherever a skill or the agent writes `<kit root>`, use this path. Config is the first "
            "found of `.github/zethus.config.json`, `$ZETHUS_CONFIG`, `.copilot/zethus.config.json`, "
            "`.claude/amphion.config.json` and `~/.copilot/zethus/config.json`.")


def context(event: dict) -> str:
    if repo_has_kit(str(event.get("cwd") or "")):
        return ""
    if user_copy():
        return ("Zethus is installed twice: this plugin, and a user-mode copy in ~/.copilot whose "
                "skills shadow the plugin's. Tell the user once, and that this removes the copy: "
                f"python {ROOT.as_posix()}/install.py --user --migrate-to-plugin")
    return agreement()


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
        text = context(event if isinstance(event, dict) else {})
    except Exception:
        return 0
    if text:
        print(json.dumps({"additionalContext": text,
                          "hookSpecificOutput": {"hookEventName": "SessionStart",
                                                 "additionalContext": text}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

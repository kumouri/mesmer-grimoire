#!/usr/bin/env python3
"""Install Amphion's skills, and the shared core they sit on, for Claude Code (or Copilot).

    python amphion/install.py --user                    # ~/.claude/skills, for every project
    python amphion/install.py --target path/to/repo     # .claude/skills + .claude/amphion.config.json
    python amphion/install.py --user --platform copilot # ~/.copilot/skills instead
    python amphion/install.py --user --dry-run          # the plan only
    python amphion/install.py --user --uninstall

This is the repo-root installer with ``--bundle amphion`` and, unless you pass one, ``--platform
claude``: every other flag goes through unchanged, so ``python install.py --help`` documents them.
Amphion needs the shared core (``flag-or-fix``, ``resume-interrupted-phase`` and ``pr-description``
are the core's), and the core needs Mnemosyne, so those come too and each hook registers once. The
plugin (``claude plugin install amphion@mesmer-grimoire``) is the other way in, and the installer
copies no skills beside it.

Exit codes are the root installer's: 0 done, 1 conflict or failure, 2 usage error.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT_INSTALLER = Path(__file__).resolve().parent.parent / "install.py"


def load_root():
    module = sys.modules.get("grimoire_install")
    if module is None:
        spec = importlib.util.spec_from_file_location("grimoire_install", ROOT_INSTALLER)
        module = importlib.util.module_from_spec(spec)
        sys.modules["grimoire_install"] = module
        spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not ROOT_INSTALLER.is_file():
        print("install: amphion/install.py needs install.py in the folder above amphion/ (run this "
              "from a mesmer-grimoire clone)", file=sys.stderr)
        return 2
    if not any(a == "--platform" or a.startswith("--platform=") for a in args):
        args = ["--platform", "claude", *args]
    return load_root().main(["--bundle", "amphion", *args])


if __name__ == "__main__":
    sys.exit(main())

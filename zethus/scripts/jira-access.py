#!/usr/bin/env python3
"""Detect what Jira access this environment offers, without contacting Jira.

    python .github/zethus/scripts/jira-access.py

Three tiers exist for reaching Jira; this script can only see two of them:

1. **An Atlassian/Jira MCP tool.** Whether one is available is a fact about the calling agent's
   own session (its tool list), not about the operating system, so no stdlib script can detect it.
   The skill checks this itself, first, before running this script.
2. **A CLI on `PATH`** — `acli` (the Atlassian CLI) or `jira`. Detected with ``shutil.which``,
   which only sees the file name. Two tools install a binary called `jira`, go-jira and
   `ankitpokhrel/jira-cli`, and this script can't tell them apart. The `jira-cli` skill documents
   the second; its setup step is where a reader finds out which one is installed.
3. **REST, via an API token in the environment** — a base URL, an email, and a token, each read
   from an env var name that config may override (``jira.baseUrlEnv``, ``jira.emailEnv``,
   ``jira.tokenEnvVars``; defaults ``JIRA_BASE_URL``, ``JIRA_EMAIL``, ``JIRA_API_TOKEN`` /
   ``JIRA_TOKEN``).

If none of the three is available, the skill degrades to asking the person to paste the story's
text. This script never prints a token's value, only which env var held it.

Config (optional; the first Zethus config found, see ``_common.py``): ``jira.cli`` (list, default
``["acli", "jira"]``), ``jira.baseUrlEnv``, ``jira.emailEnv``, ``jira.tokenEnvVars`` (list).

Exit codes: 0 a CLI or REST token was found · 1 neither — degrade to pasted input · 2 usage error.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import UsageError, cfg, find_repo_root, load_config  # noqa: E402

DEFAULT_CLI = ["acli", "jira"]
DEFAULT_BASE_URL_ENV = "JIRA_BASE_URL"
DEFAULT_EMAIL_ENV = "JIRA_EMAIL"
DEFAULT_TOKEN_ENVS = ["JIRA_API_TOKEN", "JIRA_TOKEN"]


def detect_cli(candidates: list[str], which=None) -> str | None:
    which = which or shutil.which   # resolved at call time, so patching shutil.which is honoured
    for name in candidates:
        if which(name):
            return name
    return None


def detect_rest(env: dict, base_url_env: str, email_env: str,
                 token_envs: list[str]) -> dict | None:
    base_url = env.get(base_url_env, "").strip()
    email = env.get(email_env, "").strip()
    token_var = next((v for v in token_envs if env.get(v, "").strip()), None)
    if base_url and email and token_var:
        return {"baseUrl": base_url, "email": email, "tokenVar": token_var}
    return None


def detect(config: dict, env: dict, which=None) -> dict:
    """Return ``{"mode": "cli" | "rest" | "none", "detail": ...}``. Never raises."""
    cli_candidates = cfg(config, "jira.cli", DEFAULT_CLI)
    cli = detect_cli(cli_candidates, which)
    if cli:
        return {"mode": "cli", "detail": cli}
    rest = detect_rest(
        env,
        cfg(config, "jira.baseUrlEnv", DEFAULT_BASE_URL_ENV),
        cfg(config, "jira.emailEnv", DEFAULT_EMAIL_ENV),
        cfg(config, "jira.tokenEnvVars", DEFAULT_TOKEN_ENVS),
    )
    if rest:
        return {"mode": "rest", "detail": rest}
    return {"mode": "none", "detail": None}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="jira-access",
        description="Detect a Jira CLI or REST token in this environment. An available "
                     "Jira/Atlassian MCP tool is checked by the calling skill, not this script.",
    )
    p.add_argument("--repo", help="repository root (default: nearest .git ancestor of cwd)")
    p.add_argument("--config", help="config file")
    args = p.parse_args(argv)
    try:
        repo = Path(args.repo).resolve() if args.repo else find_repo_root()
        config, _ = load_config(repo, args.config)
    except UsageError as exc:
        print(f"jira-access: {exc}", file=sys.stderr)
        return 2
    result = detect(config, dict(os.environ))
    if result["mode"] == "cli":
        print(f"cli: {result['detail']} found on PATH")
        return 0
    if result["mode"] == "rest":
        detail = result["detail"]
        print(f"rest: {detail['baseUrl']} as {detail['email']} (token from ${detail['tokenVar']})")
        return 0
    print("none: no Jira CLI on PATH and no REST token in the environment. "
          "Degrade to pasted story text, unless an MCP tool is available in this session.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

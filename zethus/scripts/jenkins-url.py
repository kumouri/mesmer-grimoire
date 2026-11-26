#!/usr/bin/env python3
"""Resolve this repository's Jenkins base URL, and say where it came from.

    python .github/zethus/scripts/jenkins-url.py

Resolution order, first hit wins:

1. **Config**, ``jenkins.baseUrl``: the repository's own controller, in the first Zethus config
   found (see ``_common.py``). A committed ``.github/zethus.config.json`` shares it with the team.
2. **The environment**, in the variable named by ``jenkins.baseUrlEnv`` (default ``JENKINS_URL``,
   the name ``jenkins-cli.jar`` itself reads).
3. **Nothing.** The script exits 1 and the caller asks the person once. It never guesses a URL,
   never derives one from a remote, a Jenkinsfile or a build log, and never reuses one seen
   earlier in a conversation.

``jenkins.jobPath`` (optional) is the folder path to this repository's job on the controller,
written as slash-separated names (``team/app``). It is turned into the ``/job/team/job/app``
form Jenkins' URLs need, so a skill never has to build that by hand. Config only: an env var for
a folder path would be one more thing to drift.

The output names the source it used, so a skill can say which one it read. A token is never read
here: credentials stay in the environment, ``JENKINS_USER`` and ``JENKINS_API_TOKEN``.

Exit codes: 0 resolved · 1 no URL in config or environment, ask the person · 2 usage error or a
value that is not an http(s) URL.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import UsageError, cfg, find_repo_root, load_config  # noqa: E402

DEFAULT_BASE_URL_ENV = "JENKINS_URL"


def clean_url(value: object, where: str) -> str:
    """A trimmed http(s) URL with no trailing slash, or ``UsageError`` naming ``where``."""
    text = str(value).strip().rstrip("/")
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise UsageError(f"{where} must be an http(s) URL, got {text!r}")
    return text


def job_path_segments(value: object) -> list[str]:
    """``team/app`` -> ``["team", "app"]``; empty or missing -> ``[]``."""
    if value is None:
        return []
    if not isinstance(value, str):
        raise UsageError("jenkins.jobPath must be a string like 'team/app'")
    return [s for s in value.replace("\\", "/").split("/") if s.strip()]


def job_url(base_url: str, segments: list[str]) -> str:
    """``base`` + ``/job/<seg>`` per folder level, each segment percent-encoded."""
    return base_url + "".join(f"/job/{quote(s.strip(), safe='')}" for s in segments)


def resolve(config: dict, env: dict) -> dict:
    """Return ``{"source", "baseUrl", "jobPath", "jobUrl"}``, or ``{"source": "none"}``.

    ``source`` is ``"config"`` (``jenkins.baseUrl``) or ``"env"`` (the variable named in
    ``detail``). Raises ``UsageError`` for a value that is not an http(s) URL; an empty or
    missing value counts as unset and falls through to the next source.
    """
    segments = job_path_segments(cfg(config, "jenkins.jobPath"))
    configured = cfg(config, "jenkins.baseUrl")
    env_name = cfg(config, "jenkins.baseUrlEnv", DEFAULT_BASE_URL_ENV)
    if configured is not None and str(configured).strip():
        base, source, detail = clean_url(configured, "jenkins.baseUrl"), "config", "jenkins.baseUrl"
    elif env.get(env_name, "").strip():
        base, source, detail = clean_url(env[env_name], f"${env_name}"), "env", f"${env_name}"
    else:
        return {"source": "none", "baseUrl": None, "jobPath": None, "jobUrl": None,
                "detail": f"jenkins.baseUrl is not set in config and ${env_name} is empty"}
    return {"source": source, "detail": detail, "baseUrl": base,
            "jobPath": "/".join(s.strip() for s in segments) or None,
            "jobUrl": job_url(base, segments) if segments else None}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="jenkins-url",
        description="Resolve this repository's Jenkins base URL: config first, then the "
                    "environment, never a guess.",
    )
    p.add_argument("--repo", help="repository root (default: nearest .git ancestor of cwd)")
    p.add_argument("--config", help="config file")
    p.add_argument("--json", action="store_true", help="print the result as JSON")
    args = p.parse_args(argv)
    try:
        repo = Path(args.repo).resolve() if args.repo else find_repo_root()
        config, _ = load_config(repo, args.config)
        result = resolve(config, dict(os.environ))
    except UsageError as exc:
        print(f"jenkins-url: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
    elif result["source"] == "none":
        print(f"none: {result['detail']}. Ask the person for it once; never guess a URL.")
    else:
        print(f"{result['source']}: {result['baseUrl']} (from {result['detail']})")
        if result["jobUrl"]:
            print(f"job: {result['jobUrl']} (jenkins.jobPath {result['jobPath']})")
    return 1 if result["source"] == "none" else 0


if __name__ == "__main__":
    sys.exit(main())

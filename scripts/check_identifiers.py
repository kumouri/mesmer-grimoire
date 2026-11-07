#!/usr/bin/env python3
"""CI guard: no machine-specific identifier may be committed to this public repo.

**This repository is public. Every byte committed here is published.** This
check is the cheap, always-on tripwire for the class of leak that is easiest to
commit by accident: an absolute path from the machine the work was done on.

Guiding rule: **scrub the machine, keep the author.**

The guard works by SHAPE, not by a list of secret strings
=========================================================
Every rule below describes the *form* of a machine identifier. The forms are
public knowledge -- everyone knows Windows home directories look like
``<drive>:\\Users\\<name>``. What is private is the *name that appears in that
slot*, and this file never needs to know it in order to reject it.

That is deliberate and it is the whole design. A guard built the obvious way --
a denylist of the private terms to forbid -- would have to *contain* those terms,
and committing it here would publish the very thing it was written to protect.
If you are ever about to add a term to this file, apply this test: **would you
be comfortable seeing that term on the repo's GitHub page?** If not, it does not
belong here; express it as a shape instead, or leave it to the private sweep
described under "What this guard cannot see".

What this guard CANNOT see  (read this before trusting it)
==========================================================
This check has **no knowledge of the private denylist** -- the real names of
clients, businesses, projects and workspace trees that must never be published.
Those live only in a private scrub workspace outside this repository, and they
are deliberately not reproduced here.

Therefore:

*   A green run here means "no identifier of a *known shape* was found."
    It does **not** mean "this repo is free of private information."
*   The pre-release gate remains the private sweep::

        pii_sweep.py --repo <path-to-this-repo> --history --denylist <private denylist>

    That tool matches literal private terms, and it scans **git history** as
    well as the working tree. This check scans **only the current working tree**
    via ``git ls-files`` -- it will never notice something already committed and
    later deleted.
*   This check is a cheap always-on **subset** of that sweep, not a replacement
    for it. Do not read a green tick here as clearance to publish.

What this guard deliberately does NOT flag
==========================================
Ceryce's name, her ``@kumouri`` handle, and the portfolio attribution lines in
``README.md`` and ``AGENTS.md`` are **deliberate attribution** -- this is her
signed portfolio repo and the signature is the point. No rule targets them, by
design: a rule against the author's own name in her own portfolio would be
nothing but false positives, and "fixing" it would be the wrong repair. Her
contact address is likewise sanctioned, via ``ALLOWED_EMAILS`` below, so that
the email rule still catches any *other* address that appears.

Usage
=====
Scan the whole tracked tree from the repo root (what CI runs)::

    python scripts/check_identifiers.py

Scan specific files instead -- useful for confirming the rules actually fire::

    python scripts/check_identifiers.py /tmp/scratch.md

Exits 0 and prints a one-line clean summary when nothing matched; exits 1 and
prints ``path:line: <what matched>`` plus a one-line reason for every hit.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# Sanctioned placeholders
# --------------------------------------------------------------------------
# Names that may legitimately stand in the user slot of a home-directory path,
# because they obviously denote "some user" rather than a real account. Docs and
# docstrings that need to show the shape of a path must use one of these.
# Compared case-insensitively.
PLACEHOLDER_NAMES = {
    # Angle-bracket placeholders. `<` and `>` are illegal in Windows paths, so
    # these cannot be mistaken for a real path.
    "<user>", "<username>", "<name>", "<you>", "<your-name>",
    # RFC-style example personas.
    "alice", "bob", "carol", "dave",
    # Generic literals and unexpanded environment variables.
    "user", "username", "youruser", "your-user", "example",
    "%username%", "%userprofile%", "$user", "$home", "${user}",
    # GitHub Actions runners really do live at /home/runner. That is a CI
    # service account, not a person, so it is not a machine identifier.
    "runner",
}

# Reserved example domains (RFC 2606). Safe by definition -- they cannot route.
EXAMPLE_DOMAINS = {"example.com", "example.org", "example.net", "example.edu"}

# The one GitHub org this project actually lives under. Not a secret: it is on
# the repo's own URL. Pinning it turns a dead-link defect into a CI failure.
CANONICAL_ORG = "kumouri"
REPO_SLUG = "mesmer-grimoire"
# Former names of this repo. GitHub redirects them today, but a redirect is
# only as durable as nobody reusing the old name -- and a link to the old name
# advertises a repo that no longer exists. Any URL still using one is stale.
RETIRED_SLUGS = ("claude-grimoire",)

# --------------------------------------------------------------------------
# Allowlist -- deliberate attribution that a rule would otherwise flag
# --------------------------------------------------------------------------
# Every entry must be safe to publish and carry a comment saying why.
ALLOWED_EMAILS = {
    # Ceryce's published contact address. This repo is her signed portfolio and
    # this address is deliberate attribution: it is the `authors` field of three
    # pyproject.toml files and the `author.email` of three plugin.json manifests,
    # i.e. the metadata that would appear on PyPI if these packages ship. It is
    # already public in exactly those places. Allowlisting it -- rather than
    # dropping the email rule -- keeps the rule live for every OTHER address.
    "ceryce.c.armstrong@gmail.com",
}

# --------------------------------------------------------------------------
# Files not worth scanning
# --------------------------------------------------------------------------
SKIP_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".svg", ".pdf",
    ".zip", ".gz", ".tar", ".jar", ".exe", ".dll", ".so", ".dylib", ".pyc",
    ".woff", ".woff2", ".ttf", ".otf", ".mp4", ".mp3", ".wav",
}

# This guard's own tests contain deliberately synthetic bad shapes.
SKIP_PATHS = {"scripts/test_check_identifiers.py"}

# --------------------------------------------------------------------------
# Shape rules
# --------------------------------------------------------------------------
# A drive letter only counts when it is not the tail of a longer word -- without
# this, the "p:/" inside "http://" reads as a drive path.
_DRIVE = r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]{1,2}"
# Path separators may be single (C:\Users) or doubled (a Python/JSON string
# literal, C:\\Users). Both forms leak identically.
_SEG = r"[^\\/\s\"'`,;:*?<>|)\]}]+"

# Rule 1 -- Windows user-profile path. The captured group is the account name.
WINDOWS_USER_PATH = re.compile(_DRIVE + r"Users[\\/]{1,2}(" + _SEG + r")", re.IGNORECASE)

# Rule 2 -- any other drive-absolute Windows path. Repo content should be
# repo-relative; an absolute path is by definition a path on somebody's machine,
# and a personal workspace tree is exactly what tends to sit at one. `Users`
# paths are excluded here because rule 1 owns them (and honours placeholders).
WINDOWS_ABS_PATH = re.compile(
    _DRIVE + r"(?!Users[\\/])(" + _SEG + r")[\\/]", re.IGNORECASE
)

# Rule 3 -- POSIX home directories. `/home` and `/Users` are matched
# case-sensitively on purpose: a lowercase `/users/` is far more likely to be a
# REST route (`/users/{id}`) than a macOS home directory.
POSIX_HOME_PATH = re.compile(r"(?<![A-Za-z0-9._-])/(?:home|Users)/(" + _SEG + r")")

# Rule 4 -- a Windows drive seen through WSL. Same leak, different spelling.
# Requires a single-letter segment, so /mnt/data and /mnt/storage do not match.
WSL_MOUNT_PATH = re.compile(r"(?<![A-Za-z0-9._-])(/mnt/[a-z]/)(?![a-z0-9])", re.IGNORECASE)

# Rule 5 -- this project's own GitHub URL under the wrong org, or under a
# retired repo name. Catches the dead-link defect where published package
# metadata points at a nonexistent org or at the repo's pre-rename slug.
REPO_URL_ORG = re.compile(
    r"github\.com[:/]([A-Za-z0-9_.-]+)/("
    + "|".join(re.escape(s) for s in (REPO_SLUG, *RETIRED_SLUGS))
    + r")(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)

# Rule 6 -- email addresses. Personal contact details are identifiers; the
# allowlist above carries the sanctioned author address.
EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+-])([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})"
)


def _is_placeholder(name: str) -> bool:
    # Trailing separators and sentence punctuation are not part of the name:
    # prose that ends a sentence with "...lives at /home/runner." must still
    # recognise `runner` as the sanctioned placeholder it is.
    return name.lower().rstrip("\\/.!") in PLACEHOLDER_NAMES


def scan_line(line: str):
    """Yield ``(matched_text, reason)`` for every identifier shape in *line*."""
    for m in WINDOWS_USER_PATH.finditer(line):
        if not _is_placeholder(m.group(1)):
            yield m.group(0), (
                "Windows user-profile path: leaks the machine's OS account name. "
                "Use a placeholder such as C:" + chr(92) + "Users" + chr(92) + "<user>."
            )

    for m in WINDOWS_ABS_PATH.finditer(line):
        yield m.group(0), (
            "Drive-absolute Windows path: names a location on one machine. "
            "Use a repo-relative path, or a documented placeholder."
        )

    for m in POSIX_HOME_PATH.finditer(line):
        if not _is_placeholder(m.group(1)):
            yield m.group(0), (
                "POSIX home directory: leaks the machine's account name. "
                "Use /home/<user> or another sanctioned placeholder."
            )

    for m in WSL_MOUNT_PATH.finditer(line):
        yield m.group(0), (
            "WSL mount of a Windows drive: a machine-absolute path in disguise."
        )

    for m in REPO_URL_ORG.finditer(line):
        if m.group(2).lower() != REPO_SLUG:
            yield m.group(0), (
                "Retired repo name: this project was renamed to "
                f"github.com/{CANONICAL_ORG}/{REPO_SLUG}. The old URL only "
                "works while GitHub's redirect holds."
            )
        elif m.group(1).lower() != CANONICAL_ORG:
            yield m.group(0), (
                "Wrong GitHub org for this project: it lives at "
                f"github.com/{CANONICAL_ORG}/{REPO_SLUG}. Published package "
                "metadata pointing elsewhere is a dead link."
            )

    for m in EMAIL.finditer(line):
        local, domain = m.group(1), m.group(2)
        # SCP-style git remotes (git@host:org/repo.git) are URLs, not addresses.
        if local == "git" and line[m.end():m.end() + 1] == ":":
            continue
        if domain.lower() in EXAMPLE_DOMAINS:
            continue
        if m.group(0).lower() in ALLOWED_EMAILS:
            continue
        yield m.group(0), (
            "Email address: a personal identifier. If this is deliberate, "
            "sanctioned attribution, add it to ALLOWED_EMAILS with a comment "
            "explaining why it is safe to publish."
        )


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "-c", "core.fsmonitor=false", "-C", str(root), "ls-files", "-z"],
        capture_output=True,
        check=True,
    )
    return [p for p in out.stdout.decode("utf-8", "replace").split("\0") if p]


def scan_file(path: Path, label: str) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    hits = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for matched, reason in scan_line(line):
            hits.append(f"  {label}:{lineno}: {matched}\n      {reason}")
    return hits


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parents[1]

    if argv:
        targets = [(Path(a), a) for a in argv]
    else:
        targets = [
            (root / rel, rel)
            for rel in tracked_files(root)
            if rel not in SKIP_PATHS and Path(rel).suffix.lower() not in SKIP_SUFFIXES
        ]

    hits: list[str] = []
    for path, label in targets:
        hits.extend(scan_file(path, label))

    if hits:
        print("Machine identifiers found (this repo is public -- every byte ships):")
        for h in hits:
            print(h)
        print()
        print(
            f"{len(hits)} hit(s). Replace machine paths with repo-relative paths or a "
            "sanctioned placeholder;\nsee the rules and the allowlist in "
            "scripts/check_identifiers.py."
        )
        return 1

    print(f"identifier check: clean ({len(targets)} files scanned)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

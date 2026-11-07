#!/usr/bin/env python3
"""Check that Markdown pointers resolve, and list docs a change may have made stale.

Two jobs, one pass over the repo's Markdown:

**1. Pointers must resolve (blocking).** Every relative link — ``[text](path)``, ``![img](path)``
and ``[ref]: path`` definitions — must name a file or directory that exists, *with that exact
case* (a link that works on a case-insensitive laptop and 404s on the Linux CI box and on GitHub
is still broken), and must not escape the repository. URLs, ``#anchors``, and links inside fenced
code blocks or inline code are not checked. ``--code-spans`` also checks backticked
``path/like/this.ext`` tokens; it is off by default because prose code spans are often example
paths, and a check that cries wolf gets switched off.

**2. Docs that describe changed code (report-only).** With ``--sync-base REF``, every entry in
the config's ``docSync.map`` (``{"doc": ..., "describes": [globs]}``) whose described paths
changed since the merge-base with ``REF``, but
whose doc did not, is listed as REVIEW. That is a prompt to re-read the doc, not proof it is wrong,
so it never changes the exit code. If ``REF`` can't be resolved the section says so — "no answer",
never a guess.

Exit codes: 0 every pointer resolves · 1 at least one broken pointer · 2 usage error.
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import UsageError, cfg, find_repo_root, git, load_config, rel  # noqa: E402

FENCE_RE = re.compile(r"^\s{0,3}(```|~~~)")
INLINE_CODE_RE = re.compile(r"(`+)(.+?)\1")
LINK_RE = re.compile(r"!?\[(?:[^\]\\]|\\.)*\]\(\s*<?([^)\s>]+)>?(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)")
REFDEF_RE = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s|$)")
SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")
CODE_PATH_RE = re.compile(r"^(?:\.{0,2}/)?[\w.\-]+(?:/[\w.\-]+)+/?(?::\d+(?:-\d+)?)?$")
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"}


@dataclass
class Finding:
    file: str
    line: int
    target: str
    reason: str


def markdown_files(repo: Path, explicit: list[str]) -> list[Path]:
    if explicit:
        files: list[Path] = []
        for item in explicit:
            path = (repo / item) if not Path(item).is_absolute() else Path(item)
            if path.is_dir():
                files.extend(sorted(p for p in path.rglob("*.md") if not SKIP_DIRS & set(p.parts)))
            elif path.is_file():
                files.append(path)
            else:
                raise UsageError(f"no such file or directory: {item}")
        return files
    proc = git(repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "*.md")
    if proc is not None and proc.returncode == 0:
        return sorted(repo / p for p in proc.stdout.split("\0") if p and (repo / p).is_file())
    return sorted(p for p in repo.rglob("*.md")
                  if not SKIP_DIRS & set(p.relative_to(repo).parts))


def exists_exact(path: Path, repo: Path) -> str | None:
    """``None`` when ``path`` exists inside ``repo`` with exact case; else the reason it doesn't."""
    # normpath, not resolve(): on a case-insensitive filesystem resolve() rewrites the path to the
    # on-disk case, which would hide exactly the mismatch this check exists to catch.
    root = Path(os.path.normpath(os.path.abspath(repo)))
    try:
        parts = Path(os.path.normpath(os.path.abspath(path))).relative_to(root).parts
    except ValueError:
        return "points outside the repository"
    current = root
    for part in parts:
        try:
            names = os.listdir(current)
        except OSError:
            return "does not exist"
        if part not in names:
            if part.lower() in (n.lower() for n in names):
                return "case mismatch (breaks on case-sensitive filesystems)"
            return "does not exist"
        current = current / part
    return None


def _target_path(raw: str, md_file: Path, repo: Path) -> Path | None:
    if SCHEME_RE.match(raw) or raw.startswith(("#", "//")) or "{{" in raw or "${" in raw:
        return None
    target = unquote(raw.split("#", 1)[0].split("?", 1)[0])
    if not target:
        return None
    return (repo / target.lstrip("/")) if target.startswith("/") else (md_file.parent / target)


def scan_file(md_file: Path, repo: Path, code_spans: bool) -> tuple[list[Finding], int]:
    findings: list[Finding] = []
    checked = 0
    in_fence = None
    shown = rel(md_file, repo)
    text = md_file.read_text(encoding="utf-8", errors="replace")
    for lineno, line in enumerate(text.splitlines(), 1):
        fence = FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            if in_fence is None:
                in_fence = marker
            elif marker == in_fence:
                in_fence = None
            continue
        if in_fence:
            continue
        spans = [m.group(2).strip() for m in INLINE_CODE_RE.finditer(line)]
        prose = INLINE_CODE_RE.sub(" ", line)
        targets = [m.group(1) for m in LINK_RE.finditer(prose)]
        ref = REFDEF_RE.match(prose)
        if ref:
            targets.append(ref.group(1))
        for raw in targets:
            path = _target_path(raw, md_file, repo)
            if path is None:
                continue
            checked += 1
            reason = exists_exact(path, repo)
            if reason:
                findings.append(Finding(shown, lineno, raw, reason))
        if code_spans:
            for span in spans:
                looks_like_file = "." in span.rsplit("/", 1)[-1] or span.endswith("/")
                if not CODE_PATH_RE.match(span) or not looks_like_file:
                    continue
                target = re.sub(r":\d+(?:-\d+)?$", "", span)
                checked += 1
                candidates = [repo / target.lstrip("/"), md_file.parent / target]
                if all(exists_exact(c, repo) for c in candidates):
                    findings.append(Finding(shown, lineno, f"`{span}`", "code-span path does not exist"))
    return findings, checked


def changed_since(repo: Path, base: str) -> tuple[set[str] | None, str]:
    mb = git(repo, "merge-base", base, "HEAD")
    if mb is None:
        return None, "git is not available"
    if mb.returncode != 0:
        return None, f"could not resolve a merge-base with {base!r}"
    sha = mb.stdout.strip()
    diff = git(repo, "diff", "--name-only", sha)          # committed + staged + unstaged
    untracked = git(repo, "ls-files", "--others", "--exclude-standard")
    names = set()
    for proc in (diff, untracked):
        if proc is not None and proc.returncode == 0:
            names.update(ln.strip() for ln in proc.stdout.splitlines() if ln.strip())
    return names, f"merge-base {sha[:10]} with {base}"


def sync_report(config: dict, changed: set[str]) -> list[str]:
    lines = []
    for entry in cfg(config, "docSync.map", []) or []:
        if not isinstance(entry, dict) or "doc" not in entry:
            continue
        doc = str(entry["doc"])
        globs = [str(g) for g in entry.get("describes", []) or []]
        hits = sorted(f for f in changed if any(fnmatch.fnmatchcase(f, g) for g in globs))
        if not hits:
            continue
        if doc in changed:
            lines.append(f"UPDATED  {doc} (describes {len(hits)} changed path(s); it changed too)")
        else:
            shown = ", ".join(hits[:5]) + (f", +{len(hits) - 5} more" if len(hits) > 5 else "")
            lines.append(f"REVIEW   {doc} — describes changed: {shown}")
    return lines


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="docs-pointer-check",
                                description="Check Markdown pointers resolve; list docs to review.")
    p.add_argument("paths", nargs="*", help="files/dirs to scan (default: all Markdown in the repo)")
    p.add_argument("--repo", help="repository root (default: nearest .git ancestor of cwd)")
    p.add_argument("--config", help="config file")
    p.add_argument("--ignore", action="append", default=[], metavar="GLOB",
                   help="skip Markdown files matching this repo-relative glob (repeatable)")
    p.add_argument("--code-spans", action="store_true", help="also check backticked paths")
    p.add_argument("--sync-base", metavar="REF", help="report docSync.map docs whose code changed "
                                                      "since the merge-base with REF")
    args = p.parse_args(argv)
    try:
        repo = Path(args.repo).resolve() if args.repo else find_repo_root()
        config, _ = load_config(repo, args.config)
        ignores = list(args.ignore) + list(cfg(config, "docs.pointerIgnore", []) or [])
        files = [f for f in markdown_files(repo, args.paths)
                 if not any(fnmatch.fnmatchcase(rel(f, repo), g) for g in ignores)]
        findings: list[Finding] = []
        checked = 0
        for md in files:
            found, n = scan_file(md, repo, args.code_spans)
            findings.extend(found)
            checked += n
        for f in findings:
            print(f"{f.file}:{f.line}: broken pointer -> {f.target} ({f.reason})")
        print(f"{len(files)} Markdown file(s), {checked} pointer(s) checked, {len(findings)} broken")
        if args.sync_base:
            changed, how = changed_since(repo, args.sync_base)
            print()
            if changed is None:
                print(f"docs sync: no answer — {how}")
            elif not cfg(config, "docSync.map"):
                print("docs sync: no docSync.map in config — nothing maps docs to code")
            else:
                report = sync_report(config, changed)
                print(f"docs sync ({how}, {len(changed)} changed path(s)) — report-only:")
                print("\n".join(report) if report else "no mapped doc describes a changed path")
        return 1 if findings else 0
    except UsageError as exc:
        print(f"docs-pointer-check: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

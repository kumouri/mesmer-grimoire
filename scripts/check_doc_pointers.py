#!/usr/bin/env python3
"""CI check: every pointer in this repo's Markdown must still resolve.

Docs drift in many ways, and only one of them is mechanical: a doc that names a file which was
renamed or deleted. This check catches exactly that class, and it can never "fix" anything by
appending. It is the mechanical half of the "detail in the leaf, routers stay routers" rule in
``AGENTS.md``; the other half (keeping behaviour descriptions true) is the job of whoever changes
the behaviour, in the same change.

What counts as a pointer
========================
1. **Links.** ``[text](target)``, ``![alt](target)`` and ``[ref]: target`` definitions. A target
   that is not a URL (no ``scheme:``), not a bare ``#anchor`` and not a template placeholder must
   name a tracked file or directory, *with that exact case*, inside the repository. It is
   resolved from the linking file's directory, or from the repo root if it starts with ``/``. The
   ``#anchor`` part is not checked.
2. **Backticked repo paths.** An inline code span shaped like a path to a file
   (``dir/name.ext``, optionally ``:line`` or ``:start-end``) or a directory (``dir/sub/``). It
   must resolve against the file's directory, any ancestor directory up to the repo root, or as the
   tail of a tracked path (so ``src/mnemosyne/stores.py`` in the root doc finds
   ``mnemosyne/src/mnemosyne/stores.py``). A path the repo's ``.gitignore`` rules cover also
   resolves: it names a runtime or generated file (``memory/local.jsonl``), which is never tracked.

Fenced code blocks are never checked: they hold commands and examples, not pointers.

What is deliberately not a pointer
==================================
Precision matters more than recall here. A check that cries wolf gets switched off, and a naive
version of this lint elsewhere reported 77 findings of which 2 were real. So a code span is skipped
when it is:

* an install destination on a user's machine or in a consuming repo: its first segment is one of
  ``HOST_DIRS`` (``.claude/``, ``.copilot/``, ...), or it starts with ``~``;
* in a file listed in ``EXAMPLE_DOCS``: skill bodies, templates and worked examples that are run or
  installed *inside another project*, so every path in them is that project's;
* a path in *the consuming project* that a kit's README or design doc describes: see
  ``CONSUMER_PATHS``, which is scoped per kit directory;
* anything with a placeholder or glob character (``<``, ``{``, ``*``, ``$``, ``%``), a domain
  (``github.com/...``), or no file extension and no trailing slash (``origin/develop`` is a git
  ref, not a path).

A **point-in-time** document (an assessment or a retrospective) cites code as it stood when it was
written, and removing that code must not break it. Such a file opts out of the code-span check
(its links are still checked) with this line anywhere in it::

    <!-- doc-pointers: point-in-time -->

Usage
=====
::

    python scripts/check_doc_pointers.py            # every tracked (and new, unignored) *.md
    python scripts/check_doc_pointers.py a.md docs  # only these files / directories

Exits 0 when every pointer resolves, 1 with ``path:line: <pointer> (<reason>)`` per broken one,
2 on a usage error. Stdlib only.
"""
from __future__ import annotations

import fnmatch
import posixpath
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

# --------------------------------------------------------------------------
# What is not a repo path
# --------------------------------------------------------------------------
# First segments that name an agent host's own directory. In this repo's docs these are always
# install destinations (a user's home or a consuming repo), never files here.
HOST_DIRS = {
    ".claude", ".copilot", ".agents", ".codex", ".cursor", ".vscode", ".mesmer-grimoire", ".git",
}

# Markdown whose code spans are all paths in *another* project: the one a skill runs in, or the
# repo a template or instruction file is installed into. Links in them are still checked.
# Each entry is (glob of the Markdown files, why it is safe). fnmatch: `*` also matches `/`.
EXAMPLE_DOCS = [
    ("amphion/plugin/skills/*",
     "Amphion's skills and stack references describe the project the skill is run in."),
    ("zethus/skills/*",
     "Zethus's skills and their worked examples run inside a consuming repo."),
    ("zethus/templates/*",
     "Templates are filled in inside a consuming repo; their paths are placeholders."),
    ("zethus/com.github.copilot/agents/*",
     "The agent runs inside a consuming repo, from the plugin or its .github/agents/."),
    ("zethus/com.github.copilot/rules/*",
     "Path-scoped instructions apply inside a consuming repo."),
    ("zethus/copilot-instructions.md",
     "Installed as a consuming repo's standing rules."),
]

# Paths that a kit's README or design docs use to describe *the project it is installed into*.
# Each entry is (glob of the Markdown files, glob of the code span, why it is safe).
CONSUMER_PATHS = [
    ("zethus/*", ".github/*",
     "Zethus installs into a consuming repo's .github/; its docs describe that layout."),
    ("zethus/*", "docs/*",
     "Zethus creates specs, ADRs and stories under a consuming repo's docs/."),
    ("amphion/*", "docs/*",
     "Amphion's config examples (ledger, friction log) live in the consuming repo's docs/."),
    ("amphion/*", "src/*",
     "Amphion's examples describe a consuming project's source tree."),
    ("mnemosyne/*", ".github/*",
     "A shared-tier memory repo's own PR template, which the lesson checklist is copied into."),
]

POINT_IN_TIME_MARKER = "<!-- doc-pointers: point-in-time -->"

# --------------------------------------------------------------------------
# Markdown shapes
# --------------------------------------------------------------------------
FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
INLINE_CODE_RE = re.compile(r"(`+)(.+?)\1")
LINK_RE = re.compile(
    r"!?\[(?:[^\]\\]|\\.)*\]\(\s*(<[^>]*>|[^)\s]+)(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)"
)
REFDEF_RE = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(<[^>]*>|\S+)")
SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")
CODE_PATH_RE = re.compile(
    r"^(?P<path>(?:\./|(?:\.\./)+)?[\w.@+-]+(?:/[\w.@+-]+)*(?P<slash>/)?)(?::\d+(?:-\d+)?)?$"
)
DOMAIN_RE = re.compile(r"^[\w-]+(?:\.[\w-]+)*\.(?:com|org|net|io|dev|ai|app|md)$", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    pointer: str
    reason: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.pointer} ({self.reason})"


class Tree:
    """The set of repo paths a pointer may name: tracked plus new, unignored files, and their dirs.

    Built from git rather than the filesystem so that ignored local clutter (``__pycache__/``, a
    build output) never makes a dangling pointer look fine, and so that case is exact even on a
    case-insensitive filesystem.
    """

    def __init__(self, files: set[str], ignored=lambda path: False):
        self.files = set(files)
        self.ignored = ignored
        self.dirs: set[str] = {""}
        for f in self.files:
            parts = f.split("/")
            for i in range(1, len(parts)):
                self.dirs.add("/".join(parts[:i]))
        self.suffixes: set[str] = set()
        for p in self.files | self.dirs:
            parts = p.split("/")
            for i in range(1, len(parts)):
                self.suffixes.add("/".join(parts[i:]))

    def has(self, path: str, want_dir: bool = False) -> bool:
        return path in self.dirs if want_dir else (path in self.files or path in self.dirs)


def git_files(repo: Path) -> set[str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"check_doc_pointers: cannot list files with git: {exc}")
    names = proc.stdout.decode("utf-8", "surrogateescape").split("\0")
    # A tracked file deleted in the working tree is gone as far as a reader is concerned.
    return {n for n in names if n and (repo / n).exists()}


def normalize(base_dir: str, target: str) -> str | None:
    """Repo-relative POSIX path of ``target`` seen from ``base_dir``; None if it escapes the repo."""
    joined = posixpath.normpath(posixpath.join(base_dir, target)) if base_dir else posixpath.normpath(target)
    if joined == ".":
        return ""
    if joined == ".." or joined.startswith("../"):
        return None
    return joined


def is_example_doc(md_rel: str) -> bool:
    return any(fnmatch.fnmatchcase(md_rel, doc) for doc, _why in EXAMPLE_DOCS)


def git_ignored(repo: Path):
    """A cached predicate: does a repo-relative path fall under the repo's ignore rules?"""
    cache: dict[str, bool] = {}

    def ignored(path: str) -> bool:
        if path not in cache:
            try:
                proc = subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", "--no-index", path],
                                      capture_output=True)
                cache[path] = proc.returncode == 0
            except OSError:
                cache[path] = False
        return cache[path]

    return ignored


def is_consumer_path(md_rel: str, span: str) -> bool:
    return any(fnmatch.fnmatchcase(md_rel, doc) and fnmatch.fnmatchcase(span, pat)
               for doc, pat, _why in CONSUMER_PATHS)


def check_link(raw: str, md_rel: str, tree: Tree) -> str | None:
    """None when the link resolves (or is not a repo link); else the reason it doesn't."""
    target = raw[1:-1].strip() if raw.startswith("<") and raw.endswith(">") else raw
    if (not target or SCHEME_RE.match(target) or target.startswith(("#", "//"))
            or "{{" in target or "${" in target):
        return None
    path = unquote(target.split("#", 1)[0].split("?", 1)[0])
    if not path:
        return None
    base = "" if path.startswith("/") else posixpath.dirname(md_rel)
    resolved = normalize(base, path.lstrip("/"))
    if resolved is None:
        return "points outside the repository"
    if tree.has(resolved):
        return None
    lowered = resolved.lower()
    if any(p.lower() == lowered for p in tree.files | tree.dirs):
        return "case mismatch: breaks on case-sensitive filesystems and on GitHub"
    return "no such file or directory"


def code_span_target(span: str) -> tuple[str, bool] | None:
    """(path, is_dir) if ``span`` is shaped like a repo path we should check, else None."""
    m = CODE_PATH_RE.match(span)
    if not m:
        return None
    path, is_dir = m.group("path"), bool(m.group("slash"))
    if "/" not in path.rstrip("/") and not is_dir:
        return None
    first = path.split("/", 1)[0]
    if first in HOST_DIRS or DOMAIN_RE.match(first):
        return None
    last = path.rstrip("/").rsplit("/", 1)[-1]
    if not is_dir and "." not in last.strip("."):
        return None
    return path.rstrip("/"), is_dir


def check_code_span(path: str, is_dir: bool, md_rel: str, tree: Tree) -> str | None:
    doc_dir = posixpath.dirname(md_rel)
    bases = [doc_dir]
    while doc_dir:
        doc_dir = posixpath.dirname(doc_dir)
        bases.append(doc_dir)
    for base in bases:
        resolved = normalize(base, path)
        if resolved is not None and tree.has(resolved, want_dir=is_dir):
            return None
    if not path.startswith(("./", "../")) and path in tree.suffixes:
        return None
    for base in bases:
        resolved = normalize(base, path)
        if resolved and tree.ignored(resolved):
            return None
    return "backticked path does not exist"


def scan(text: str, md_rel: str, tree: Tree) -> list[Finding]:
    findings: list[Finding] = []
    spans_checked = POINT_IN_TIME_MARKER not in text and not is_example_doc(md_rel)
    fence: str | None = None
    for lineno, line in enumerate(text.splitlines(), 1):
        m = FENCE_RE.match(line)
        if m:
            marker = m.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            continue
        if fence:
            continue
        spans = [s.group(2).strip() for s in INLINE_CODE_RE.finditer(line)]
        prose = INLINE_CODE_RE.sub(" ", line)
        links = [l.group(1) for l in LINK_RE.finditer(prose)]
        ref = REFDEF_RE.match(prose)
        if ref:
            links.append(ref.group(1))
        for raw in links:
            reason = check_link(raw, md_rel, tree)
            if reason:
                findings.append(Finding(md_rel, lineno, raw, reason))
        if not spans_checked:
            continue
        for span in spans:
            target = code_span_target(span)
            if target is None or is_consumer_path(md_rel, target[0]):
                continue
            reason = check_code_span(*target, md_rel, tree)
            if reason:
                findings.append(Finding(md_rel, lineno, f"`{span}`", reason))
    return findings


def select(repo: Path, tree: Tree, args: list[str]) -> list[str]:
    markdown = sorted(f for f in tree.files if f.endswith(".md"))
    if not args:
        return markdown
    chosen: list[str] = []
    for arg in args:
        try:
            rel = Path(arg).resolve().relative_to(repo.resolve()).as_posix()
        except ValueError:
            raise ValueError(f"outside the repository: {arg}") from None
        rel = "" if rel == "." else rel
        if not tree.has(rel):
            raise ValueError(f"not a tracked file or directory: {arg}")
        chosen += [f for f in markdown if f == rel or rel == "" or f.startswith(rel + "/")]
    return sorted(set(chosen))


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if any(a in ("-h", "--help") for a in args):
        print(__doc__)
        return 0
    repo = Path(__file__).resolve().parent.parent
    tree = Tree(git_files(repo), git_ignored(repo))
    try:
        files = select(repo, tree, args)
    except ValueError as exc:
        print(f"check_doc_pointers: {exc}", file=sys.stderr)
        return 2
    findings: list[Finding] = []
    for rel in files:
        text = (repo / rel).read_text(encoding="utf-8", errors="replace")
        findings += scan(text, rel, tree)
    for f in findings:
        print(f)
    if findings:
        print(f"\n{len(findings)} broken pointer(s) in {len(files)} Markdown file(s). Fix the pointer, "
              "or, if the text is a deliberate example of a consuming project's path, see "
              "CONSUMER_PATHS in scripts/check_doc_pointers.py.")
        return 1
    print(f"doc pointers: {len(files)} Markdown file(s), every pointer resolves.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

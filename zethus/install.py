#!/usr/bin/env python3
"""Install the Zethus kit into a repository's ``.github/``, or once for your user account.

    python zethus/install.py --target path/to/your-repo            # repo mode: commit it
    python zethus/install.py --target path/to/your-repo --dry-run  # show the plan only
    python zethus/install.py --user                                # user mode: every repo, no commit
    python zethus/install.py --user --dry-run
    python zethus/install.py --user --uninstall                    # remove what --user installed
    python zethus/install.py --user --jetbrains-legacy             # + JetBrains' older global file
    python zethus/install.py --user --with-mnemosyne               # + Mnemosyne (memory + hooks)

**Repo mode** (``--target``) — what goes where, all under the target's ``.github/``:

    copilot-instructions.md        -> copilot-instructions.md
    instructions/*.instructions.md -> instructions/
    agents/*.agent.md              -> agents/
    skills/<name>/                 -> skills/<name>/
    templates/*.md                 -> zethus/templates/
    scripts/*.py                   -> zethus/scripts/
    zethus.config.example.json     -> zethus.config.json   (only if absent; never overwritten)

Two files belong to the repo, not the kit, and are never clobbered:

- If the repo already has a ``copilot-instructions.md``, the kit's rules go into
  ``instructions/zethus.instructions.md`` with ``applyTo: "**"``. Copilot combines the two, so
  the repo keeps its own file untouched.
- An existing ``zethus.config.json`` is left alone, even with ``--force``.

Any other file that already exists is a conflict. Without ``--force`` the installer lists every
conflict and writes **nothing**, so a repo is never left half-installed.

**User mode** (``--user``) — the user-level locations Copilot reads (see the README's support
table for which clients read which):

    copilot-instructions.md        -> ~/.copilot/instructions/zethus.instructions.md (applyTo "**")
    instructions/docs.*            -> ~/.copilot/instructions/zethus-docs.instructions.md
    agents/*.agent.md              -> ~/.copilot/agents/
    skills/<name>/                 -> ~/.copilot/skills/<name>/
    templates/*.md                 -> ~/.copilot/zethus/templates/
    scripts/*.py                   -> ~/.copilot/zethus/scripts/
    zethus.config.example.json     -> ~/.copilot/zethus/config.example.json (reference only)

Current JetBrains builds read ``~/.copilot/instructions``, ``~/.copilot/agents`` and
``~/.copilot/skills`` like the other clients, so user mode writes nothing JetBrains-specific.
Only ``--jetbrains-legacy`` also writes the working agreement to JetBrains' single
``global-copilot-instructions.md`` (Windows/macOS, only if absent), for older plugin builds.

The Markdown is rewritten on the way: every ``.github/zethus/...`` path becomes the absolute path
of the user-level copy, and every mention of the repo config names the full resolution order.
No ``config.json`` is created — a user default with example gates would override discovery in
every repo. Every file written is recorded, with its hash, in
``~/.copilot/zethus/install-manifest.json``. A file that exists and isn't in that manifest is
yours: it is never overwritten, even with ``--force``. A kit file you edited is a conflict unless
you pass ``--force``. ``--uninstall`` removes only manifest files you haven't edited (``--force``
removes edited ones too), then the empty folders it made.

**``--with-mnemosyne``** (either mode) then calls ``mnemosyne/install.py`` from the same clone,
passing on ``--target``, ``--dry-run``, ``--uninstall`` and ``--mnemosyne-repo`` (as its
``--repo``). That installer sets up the package, a local git memory repo, ``MNEMOSYNE_REPO`` and the
hooks; its docstring says what goes where. It runs only after the Zethus step succeeds (an
uninstall runs both), and the exit code is the worse of the two. Without the flag nothing about
this installer changes.

Exit codes: 0 installed / uninstalled (or dry run) · 1 conflicts or nothing to uninstall,
nothing written · 2 usage error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

KIT = Path(__file__).resolve().parent
FALLBACK_INSTRUCTIONS = Path("instructions") / "zethus.instructions.md"
FALLBACK_FRONTMATTER = (
    "---\n"
    "name: Zethus working agreement\n"
    "description: Standing delivery rules installed by the Zethus kit.\n"
    'applyTo: "**"\n'
    "---\n\n"
)
PLATFORM = sys.platform            # tests patch this to exercise each client's paths


def plan(target_github: Path) -> list[tuple[Path | None, Path, str]]:
    """Return ``(source, dest, action)``; action is create | overwrite-candidate | keep | adapt."""
    items: list[tuple[Path | None, Path]] = []
    for src in sorted((KIT / "instructions").glob("*.instructions.md")):
        items.append((src, Path("instructions") / src.name))
    for src in sorted((KIT / "agents").glob("*.agent.md")):
        items.append((src, Path("agents") / src.name))
    for skill in sorted(p for p in (KIT / "skills").iterdir() if p.is_dir()):
        for src in sorted(f for f in skill.rglob("*") if f.is_file()):
            items.append((src, Path("skills") / skill.name / src.relative_to(skill)))
    for src in sorted((KIT / "templates").glob("*.md")):
        items.append((src, Path("zethus") / "templates" / src.name))
    for src in sorted((KIT / "scripts").glob("*.py")):
        items.append((src, Path("zethus") / "scripts" / src.name))

    steps: list[tuple[Path | None, Path, str]] = []
    instructions = KIT / "copilot-instructions.md"
    if (target_github / "copilot-instructions.md").exists():
        dest = FALLBACK_INSTRUCTIONS
        steps.append((instructions, dest, "conflict" if (target_github / dest).exists() else "adapt"))
    else:
        steps.append((instructions, Path("copilot-instructions.md"), "create"))
    for src, dest in items:
        steps.append((src, dest, "conflict" if (target_github / dest).exists() else "create"))
    config = Path("zethus.config.json")
    steps.append((KIT / "zethus.config.example.json", config,
                  "keep" if (target_github / config).exists() else "create"))
    return steps


def install_repo(args) -> int:
    target = Path(args.target).resolve()
    if not target.is_dir():
        print(f"install: target is not a directory: {args.target}", file=sys.stderr)
        return 2
    github = target / ".github"
    steps = plan(github)
    conflicts = [d for _, d, a in steps if a == "conflict"]
    if conflicts and not args.force:
        print("install: these files already exist; nothing was written. Re-run with --force to "
              "overwrite them:")
        for dest in conflicts:
            print(f"  .github/{dest.as_posix()}")
        return 1

    for src, dest, action in steps:
        label = {"create": "create", "adapt": "create", "conflict": "overwrite", "keep": "keep"}[action]
        note = ""
        if action == "adapt":
            note = "  (repo has its own copilot-instructions.md; installed as path-scoped instructions)"
        if action == "keep":
            note = "  (existing config left untouched)"
        print(f"{label:9} .github/{dest.as_posix()}{note}")
        if args.dry_run or action == "keep" or src is None:
            continue
        out = github / dest
        out.parent.mkdir(parents=True, exist_ok=True)
        if action == "adapt" or (action == "conflict" and dest == FALLBACK_INSTRUCTIONS):
            text = src.read_text(encoding="utf-8")
            with open(out, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(FALLBACK_FRONTMATTER + text)
        else:
            shutil.copyfile(src, out)
    if args.dry_run:
        print("dry run: nothing written")
    else:
        print("installed. Next: edit .github/zethus.config.json (gates.steps first), then run "
              "python .github/zethus/scripts/run-local-gates.py --list")
    return 0


# --------------------------------------------------------------------------- user mode


def copilot_home() -> Path:
    """``~/.copilot``. Deliberately not ``$COPILOT_HOME``: only the CLI honours that variable,
    so a kit installed there would be invisible to VS Code and JetBrains."""
    return Path.home() / ".copilot"


def jetbrains_dir() -> Path | None:
    """Where older JetBrains Copilot builds read ``global-copilot-instructions.md`` (used only by
    ``--jetbrains-legacy``); ``None`` where GitHub documents no location (Linux)."""
    if PLATFORM.startswith("win"):
        local = os.environ.get("LOCALAPPDATA")
        return (Path(local) if local else Path.home() / "AppData" / "Local") / "github-copilot" / "intellij"
    if PLATFORM == "darwin":
        return Path.home() / ".config" / "github-copilot" / "intellij"
    return None


def manifest_path() -> Path:
    return copilot_home() / "zethus" / "install-manifest.json"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def show(path: Path) -> str:
    """``~/``-relative for display, so pasted output never carries a user name."""
    try:
        return "~/" + path.resolve().relative_to(Path.home().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def user_rewrites() -> list[tuple[str, str]]:
    home = copilot_home()
    zhome = (home / "zethus").as_posix()
    return [
        ("`.github/zethus.config.json`",
         f"the Zethus config (the first of `.github/zethus.config.json`, `$ZETHUS_CONFIG`, "
         f"`.copilot/zethus.config.json`, `.claude/amphion.config.json`, `{zhome}/config.json`)"),
        ("`.github/copilot-instructions.md`",
         f"`{(home / 'instructions' / 'zethus.instructions.md').as_posix()}`"),
        ("`.github/skills/`", f"`{(home / 'skills').as_posix()}/`"),
        (".github/zethus/", zhome + "/"),
    ]


def rewrite(text: str) -> str:
    for old, new in user_rewrites():
        text = text.replace(old, new)
    return text


@dataclass
class Step:
    dest: Path
    data: bytes
    action: str = "create"      # create | update | same | conflict | foreign | keep | remove
    note: str = ""


def user_payloads() -> list[tuple[Path, bytes, bool]]:
    """``(dest, content, optional)``. ``optional`` files are skipped, not conflicts, if present."""
    home = copilot_home()

    def md(src: Path, prefix: str = "") -> bytes:
        return (prefix + rewrite(src.read_text(encoding="utf-8"))).encode("utf-8")

    out: list[tuple[Path, bytes, bool]] = []
    agreement = KIT / "copilot-instructions.md"
    out.append((home / "instructions" / "zethus.instructions.md", md(agreement, FALLBACK_FRONTMATTER), False))
    for src in sorted((KIT / "instructions").glob("*.instructions.md")):
        name = src.name if src.name.startswith("zethus") else "zethus-" + src.name
        out.append((home / "instructions" / name, md(src), False))
    for src in sorted((KIT / "agents").glob("*.agent.md")):
        out.append((home / "agents" / src.name, md(src), False))
    for skill in sorted(p for p in (KIT / "skills").iterdir() if p.is_dir()):
        for src in sorted(f for f in skill.rglob("*") if f.is_file()):
            data = md(src) if src.suffix == ".md" else src.read_bytes()
            out.append((home / "skills" / skill.name / src.relative_to(skill), data, False))
    for src in sorted((KIT / "templates").glob("*.md")):
        out.append((home / "zethus" / "templates" / src.name, src.read_bytes(), False))
    for src in sorted((KIT / "scripts").glob("*.py")):
        out.append((home / "zethus" / "scripts" / src.name, src.read_bytes(), False))
    out.append((home / "zethus" / "config.example.json",
                (KIT / "zethus.config.example.json").read_bytes(), False))
    return out


def read_manifest() -> dict[str, str]:
    path = manifest_path()
    if not path.is_file():
        return {}
    try:
        files = json.loads(path.read_text(encoding="utf-8")).get("files", {})
    except (json.JSONDecodeError, AttributeError):
        return {}
    return files if isinstance(files, dict) else {}


def write_manifest(files: dict[str, str]) -> None:
    path = manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"_readme": "Files the Zethus user install wrote, with their SHA-256. "
                       "install.py --user --uninstall removes the unedited ones.",
            "version": 1, "files": dict(sorted(files.items()))}
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(body, fh, indent=2)
        fh.write("\n")


def current_hash(path: Path) -> str | None:
    return sha256(path.read_bytes()) if path.is_file() else None


def user_plan(jetbrains_legacy: bool) -> list[Step]:
    manifest = read_manifest()
    payloads = user_payloads()
    if jetbrains_legacy and (jb := jetbrains_dir()) is not None:
        payloads.append((jb / "global-copilot-instructions.md",
                         rewrite((KIT / "copilot-instructions.md").read_text(encoding="utf-8")).encode("utf-8"),
                         True))
    steps: list[Step] = []
    for dest, data, optional in payloads:
        step = Step(dest, data)
        have = current_hash(dest)
        recorded = manifest.get(dest.as_posix())
        if have is None:
            step.action = "create"
        elif have == sha256(data):
            step.action = "same"         # identical content is ours to track, whoever wrote it
        elif recorded is None:
            step.action = "keep" if optional else "foreign"
            step.note = "not installed by Zethus; left untouched" if optional else "not installed by Zethus"
        elif have == recorded:
            step.action = "update"
        else:
            step.action = "conflict"
            step.note = "edited since install"
        steps.append(step)
    planned = {s.dest.as_posix() for s in steps}
    for stale, recorded in sorted(manifest.items()):
        if stale not in planned and current_hash(Path(stale)) == recorded:
            steps.append(Step(Path(stale), b"", "remove", "no longer part of the kit"))
    return steps


def prune(start: Path, stop: set[Path]) -> None:
    """Remove empty folders from ``start`` upward, never touching ``stop`` or anything above it."""
    here = start
    while here not in stop and any(root in here.parents for root in stop):
        try:
            here.rmdir()
        except OSError:
            return                       # not empty: something else lives here
        here = here.parent


def prune_roots() -> set[Path]:
    home = copilot_home()
    roots = {home, home / "agents", home / "skills", home / "instructions", Path.home()}
    jb = jetbrains_dir()
    if jb is not None:
        roots.add(jb)
    return roots


def install_user(args) -> int:
    steps = user_plan(jetbrains_legacy=args.jetbrains_legacy)
    foreign = [s for s in steps if s.action == "foreign"]
    edited = [s for s in steps if s.action == "conflict"]
    if foreign or (edited and not args.force):
        print("install: nothing was written. These files already exist:")
        for s in foreign:
            print(f"  {show(s.dest)}  (not installed by Zethus: never overwritten, even with --force)")
        for s in edited:
            print(f"  {show(s.dest)}  (a Zethus file you edited: --force overwrites it)")
        return 1

    manifest = read_manifest()
    labels = {"create": "create", "update": "update", "same": "same", "conflict": "overwrite",
              "keep": "keep", "remove": "remove"}
    for s in steps:
        note = f"  ({s.note})" if s.note else ""
        print(f"{labels[s.action]:9} {show(s.dest)}{note}")
        if args.dry_run:
            continue
        if s.action == "remove":
            s.dest.unlink()
            manifest.pop(s.dest.as_posix(), None)
            prune(s.dest.parent, prune_roots())
        elif s.action in ("create", "update", "conflict"):
            s.dest.parent.mkdir(parents=True, exist_ok=True)
            s.dest.write_bytes(s.data)
            manifest[s.dest.as_posix()] = sha256(s.data)
        elif s.action == "same":
            manifest[s.dest.as_posix()] = sha256(s.data)
    if args.jetbrains_legacy and jetbrains_dir() is None:
        print("skip      JetBrains global-copilot-instructions.md (GitHub documents no location "
              "on Linux)")
    if args.dry_run:
        print("dry run: nothing written")
        return 0
    write_manifest(manifest)
    zhome = (copilot_home() / "zethus").as_posix()
    print(f"installed for your user account. Next, in any repo: python {zhome}/scripts/"
          "run-local-gates.py --list. To pin gates without committing, write "
          ".copilot/zethus.config.json and add `.copilot/` to .git/info/exclude.")
    return 0


def uninstall_user(args) -> int:
    manifest = read_manifest()
    if not manifest:
        print(f"uninstall: no Zethus user install found ({show(manifest_path())} is missing)")
        return 1
    kept = 0
    roots = prune_roots()
    for key, recorded in sorted(manifest.items()):
        path = Path(key)
        have = current_hash(path)
        if have is None:
            print(f"gone      {show(path)}")
            continue
        if have != recorded and not args.force:
            kept += 1
            print(f"keep      {show(path)}  (edited since install; --force removes it)")
            continue
        print(f"remove    {show(path)}")
        if not args.dry_run:
            path.unlink()
            prune(path.parent, roots)
    print(f"remove    {show(manifest_path())}")
    if args.dry_run:
        print("dry run: nothing removed")
        return 0
    manifest_path().unlink()
    prune(manifest_path().parent, roots)
    print("uninstalled." + (f" {kept} edited file(s) kept." if kept else "")
          + " Your own files (e.g. ~/.copilot/zethus/config.json) were not touched.")
    return 0


# --------------------------------------------------------------------------- --with-mnemosyne


MNEMOSYNE_INSTALLER = KIT.parent / "mnemosyne" / "install.py"


def mnemosyne_argv(args) -> list[str]:
    """Zethus's flags, translated for mnemosyne/install.py. ``--force`` is deliberately not passed:
    there it would repoint ``MNEMOSYNE_REPO``, which deserves its own explicit run."""
    argv = ["--target", args.target] if args.target else []
    if args.mnemosyne_repo:
        argv += ["--repo", args.mnemosyne_repo]
    if args.dry_run:
        argv.append("--dry-run")
    if args.uninstall:
        argv.append("--uninstall")
    return argv


def run_mnemosyne(argv: list[str]) -> int:
    """Call Mnemosyne's own installer in-process (one implementation, not a copy of it)."""
    if not MNEMOSYNE_INSTALLER.is_file():
        print(f"install: --with-mnemosyne needs {MNEMOSYNE_INSTALLER.parent.name}/install.py beside "
              "zethus/ (run this from a mesmer-grimoire clone)", file=sys.stderr)
        return 2
    module = sys.modules.get("mnemosyne_install")
    if module is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("mnemosyne_install", MNEMOSYNE_INSTALLER)
        module = importlib.util.module_from_spec(spec)
        sys.modules["mnemosyne_install"] = module
        spec.loader.exec_module(module)
    print(f"\nmnemosyne: install.py {' '.join(argv)}".rstrip())
    return module.main(argv)


# --------------------------------------------------------------------------- cli


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="install", description="Install the Zethus kit into a repo "
                                "(--target) or for your user account (--user).")
    where = p.add_mutually_exclusive_group(required=True)
    where.add_argument("--target", help="root of the repository to install into")
    where.add_argument("--user", action="store_true",
                       help="install into ~/.copilot/ for every repo; touches no repository")
    p.add_argument("--force", action="store_true", help="overwrite existing kit files")
    p.add_argument("--dry-run", action="store_true", help="print the plan; write nothing")
    p.add_argument("--uninstall", action="store_true",
                   help="with --user: remove the files the user install wrote")
    p.add_argument("--jetbrains-legacy", action="store_true",
                   help="with --user: also write JetBrains' global-copilot-instructions.md, for "
                        "older plugin builds that don't read ~/.copilot/instructions")
    p.add_argument("--with-mnemosyne", action="store_true",
                   help="then run mnemosyne/install.py: the package, a local memory repo, "
                        "MNEMOSYNE_REPO and its hooks (with --target, also that repo's Copilot hooks)")
    p.add_argument("--mnemosyne-repo", metavar="PATH",
                   help="with --with-mnemosyne: the memory repo (default ~/repos/mnemosyne-local)")
    args = p.parse_args(argv)
    if not args.user and (args.uninstall or args.jetbrains_legacy):
        p.error("--uninstall and --jetbrains-legacy need --user (a repo install is removed with git)")
    if args.mnemosyne_repo and not args.with_mnemosyne:
        p.error("--mnemosyne-repo needs --with-mnemosyne")
    if args.user:
        code = uninstall_user(args) if args.uninstall else install_user(args)
    else:
        code = install_repo(args)
    if not args.with_mnemosyne or (code != 0 and not args.uninstall):
        return code                      # a refused install wrote nothing; stop there too
    return max(code, run_mnemosyne(mnemosyne_argv(args)))


if __name__ == "__main__":
    sys.exit(main())

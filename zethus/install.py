#!/usr/bin/env python3
"""Install the Zethus kit into a repository's ``.github/``, or once for your user account.

The Copilot plugin (``zethus@mesmer-grimoire``, see the README) is the default for VS Code, IntelliJ
and the CLI on one machine. This script is for repo mode, and so for the cloud agent, which never
loads a user's plugins, and for user mode where a plugin can't be used.

    python zethus/install.py --target path/to/your-repo            # repo mode: commit it
    python zethus/install.py --target path/to/your-repo --dry-run  # show the plan only
    python zethus/install.py --user                                # user mode: every repo, no commit
    python zethus/install.py --user --dry-run
    python zethus/install.py --user --uninstall                    # remove what --user installed
    python zethus/install.py --user --jetbrains-legacy             # + JetBrains' older global file
    python zethus/install.py --user --with-mnemosyne               # + Mnemosyne (memory + hooks)
    python zethus/install.py --user --migrate-to-plugin            # drop --user's copy for the plugin
                                                                   # (keeps the agent: add --drop-agent)

**Repo mode** (``--target``) — what goes where, all under the target's ``.github/``:

    copilot-instructions.md        -> copilot-instructions.md
    com.github.copilot/rules/      -> instructions/   (zethus-docs.* as docs.*)
    com.github.copilot/agents/     -> agents/
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
    com.github.copilot/rules/      -> ~/.copilot/instructions/zethus-docs.instructions.md
    com.github.copilot/agents/     -> ~/.copilot/agents/
    skills/<name>/                 -> ~/.copilot/skills/<name>/
    templates/*.md                 -> ~/.copilot/zethus/templates/
    scripts/*.py                   -> ~/.copilot/zethus/scripts/
    zethus.config.example.json     -> ~/.copilot/zethus/config.example.json (reference only)

Current JetBrains builds read ``~/.copilot/instructions``, ``~/.copilot/agents`` and
``~/.copilot/skills`` like the other clients, so user mode writes nothing JetBrains-specific.
Only ``--jetbrains-legacy`` also writes the working agreement to JetBrains' single
``global-copilot-instructions.md`` (Windows/macOS, only if absent), for older plugin builds.

The kit's Markdown says ``<kit root>``, because a plugin can live anywhere. Both modes rewrite it on
the way: repo mode to ``.github/zethus/``, and user mode to the absolute path of the user-level
copy, where every mention of the repo config also names the full resolution order.
No ``config.json`` is created — a user default with example gates would override discovery in
every repo. Every file written is recorded, with its hash, in
``~/.copilot/zethus/install-manifest.json``. A file that exists and isn't in that manifest is
yours: it is never overwritten, even with ``--force``. A kit file you edited is a conflict unless
you pass ``--force``. ``--uninstall`` removes only manifest files you haven't edited (``--force``
removes edited ones too), then the empty folders it made.

**Beside the plugin.** Personal and project skills silently beat a plugin's skills of the same
name, so a user-mode copy would shadow the plugin. ``--user`` finds a plugin the Copilot CLI
recorded (``enabledPlugins`` in ``settings.json``, or a copy under ``installed-plugins/``, in
``~/.copilot`` and ``$COPILOT_HOME``), writes nothing and says so; ``--force`` installs anyway.
``--user --migrate-to-plugin`` removes a prior user-mode copy, as ``--uninstall`` does, except the
agent file in ``~/.copilot/agents/`` (``--drop-agent`` removes that too): the script sees only a
plugin the CLI recorded, and IntelliJ lists the agent from that folder or from a plugin installed
in IntelliJ itself, so removing it could leave IntelliJ with no Zethus agent. It prints the commands
that add the plugin if it can't find one. Edited files stay and still shadow, so they
are named and the exit code is 1. A repo install beside the plugin only gets a note: the committed
copy wins in that repo, and the plugin's hook stays quiet there. A plugin that VS Code or IntelliJ
installed itself may not be recorded where this looks; the plugin's hook catches that case and
has the agent offer to run the migration for you.

**``--with-mnemosyne``** (either mode) then calls ``mnemosyne/install.py`` from the same clone,
passing on ``--target`` or ``--user``, ``--dry-run``, ``--uninstall``, ``--mnemosyne-repo`` (as its
``--repo``) and ``--mnemosyne-copilot-hooks-dir`` (as its ``--copilot-hooks-dir``). That installer
sets up the package, a local git memory repo, ``MNEMOSYNE_REPO`` and the hooks, including, in user
mode, Copilot's in ``~/.copilot/hooks``; its docstring says what goes where. It runs only after the
Zethus step succeeds (an uninstall or a ``--migrate-to-plugin`` runs both), and the exit code is the
worse of the two. Without the flag nothing about
this installer changes.

Exit codes: 0 installed / uninstalled / skipped for the plugin (or dry run) · 1 conflicts, nothing
to uninstall, or a migration that left edited files · 2 usage error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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
AGENTS = KIT / "com.github.copilot" / "agents"
RULES = KIT / "com.github.copilot" / "rules"
KIT_ROOT_NOTE = re.compile(r"^> `<kit root>` is the folder[^\n]*\n\n", re.M)
MARKETPLACE_ENTRY = "kumouri/mesmer-grimoire#main"
PLUGIN_NAME = "zethus"
PLATFORM = sys.platform            # tests patch this to exercise each client's paths


def repo_text(src: Path) -> str:
    """A kit Markdown file as a repo install has it: ``<kit root>`` is ``.github/zethus``, so the
    note defining it goes, and the agent's links lose the plugin's extra folder."""
    text = KIT_ROOT_NOTE.sub("", src.read_text(encoding="utf-8"))
    text = text.replace("<kit root>/copilot-instructions.md", ".github/copilot-instructions.md")
    text = text.replace("<kit root>/", ".github/zethus/")
    return text.replace("](../../", "](../") if src.parent == AGENTS else text


def plan(target_github: Path) -> list[tuple[Path | None, Path, str]]:
    """Return ``(source, dest, action)``; action is create | overwrite-candidate | keep | adapt."""
    items: list[tuple[Path | None, Path]] = []
    for src in sorted(RULES.glob("*.instructions.md")):
        items.append((src, Path("instructions") / src.name.removeprefix("zethus-")))
    for src in sorted(AGENTS.glob("*.agent.md")):
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
        if src.suffix == ".md":
            head = FALLBACK_FRONTMATTER if dest == FALLBACK_INSTRUCTIONS else ""
            with open(out, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(head + repo_text(src))
        else:
            shutil.copyfile(src, out)
    if (plugin := find_plugin()) is not None:
        print(f"note      Copilot plugin {plugin} is installed too: in this repo the committed copy "
              "wins, and the plugin's hook stays quiet")
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


def find_plugin() -> str | None:
    """The plugin's id if the Copilot CLI has it installed, else ``None``. ``$COPILOT_HOME`` counts
    here, unlike in ``copilot_home``: this reads what the CLI wrote, and the CLI honours it."""
    homes = [copilot_home()]
    if os.environ.get("COPILOT_HOME"):
        homes.append(Path(os.environ["COPILOT_HOME"]))
    for home in homes:
        try:
            enabled = json.loads((home / "settings.json").read_text(encoding="utf-8"))["enabledPlugins"]
            found = [k for k, on in enabled.items() if on and k.split("@")[0] == PLUGIN_NAME]
        except (OSError, ValueError, KeyError, AttributeError, TypeError):
            found = []
        if found:
            return found[0]
        for copied in sorted((home / "installed-plugins").glob(f"*/{PLUGIN_NAME}/plugin.json")):
            return f"{PLUGIN_NAME}@{copied.parent.parent.name}"
    return None


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
        return (prefix + rewrite(repo_text(src))).encode("utf-8")

    out: list[tuple[Path, bytes, bool]] = []
    agreement = KIT / "copilot-instructions.md"
    out.append((home / "instructions" / "zethus.instructions.md", md(agreement, FALLBACK_FRONTMATTER), False))
    for src in sorted(RULES.glob("*.instructions.md")):
        out.append((home / "instructions" / src.name, md(src), False))
    for src in sorted(AGENTS.glob("*.agent.md")):
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
                         rewrite(repo_text(KIT / "copilot-instructions.md")).encode("utf-8"),
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
    plugin = find_plugin()
    if plugin is not None and not args.force:
        print(f"skip      user-mode install: Copilot plugin {plugin} is installed, and a copy in "
              f"{show(copilot_home())} would shadow its skills. --force installs it anyway.")
        if read_manifest():
            print("offer     a user-mode copy is already there. Remove it with: "
                  "python zethus/install.py --user --migrate-to-plugin")
        return 0
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


def uninstall_user(args, keep_agents: bool = False) -> int:
    """Remove what ``--user`` wrote. ``keep_agents`` (a migration) leaves the agent files and the
    manifest entries for them, so a later ``--uninstall`` still finds them."""
    manifest = read_manifest()
    if not manifest:
        print(f"uninstall: no Zethus user install found ({show(manifest_path())} is missing)")
        return 1
    kept = 0
    roots = prune_roots()
    agents_dir = (copilot_home() / "agents").as_posix() + "/"
    held: dict[str, str] = {}
    for key, recorded in sorted(manifest.items()):
        path = Path(key)
        have = current_hash(path)
        if have is None:
            print(f"gone      {show(path)}")
            continue
        if keep_agents and key.startswith(agents_dir):
            held[key] = recorded
            print(f"keep      {show(path)}  (the agent stays: IntelliJ may not have the plugin)")
            continue
        if have != recorded and not args.force:
            kept += 1
            print(f"keep      {show(path)}  (edited since install; --force removes it)")
            continue
        print(f"remove    {show(path)}")
        if not args.dry_run:
            path.unlink()
            prune(path.parent, roots)
    if held:
        if args.dry_run:
            print("dry run: nothing removed")
            return 0
        write_manifest(held)
        return 0
    print(f"remove    {show(manifest_path())}")
    if args.dry_run:
        print("dry run: nothing removed")
        return 0
    manifest_path().unlink()
    prune(manifest_path().parent, roots)
    print("uninstalled." + (f" {kept} edited file(s) kept." if kept else "")
          + " Your own files (e.g. ~/.copilot/zethus/config.json) were not touched.")
    return 0


def migrate_to_plugin(args) -> int:
    """Remove the user-mode copy so the plugin's skills load. Safe to run twice."""
    keep_agents = not args.drop_agent
    if read_manifest():
        uninstall_user(args, keep_agents=keep_agents)
    else:
        print(f"migrate: no user-mode copy to remove ({show(manifest_path())} is missing)")
    plugin = find_plugin()
    if plugin is None:
        print("migrate: no Zethus plugin found. Add it with:\n"
              f"  copilot plugin marketplace add {MARKETPLACE_ENTRY}\n"
              f"  copilot plugin install {PLUGIN_NAME}@mesmer-grimoire\n"
              "  (in VS Code or IntelliJ, add the same marketplace entry in the plugin settings)")
    else:
        print(f"migrate: Copilot plugin {plugin} takes over.")
    if keep_agents and (copilot_home() / "agents" / "zethus.agent.md").is_file():
        print("migrate: the zethus agent file stays in " + show(copilot_home() / "agents") + ". "
              "The Copilot CLI plugin install is invisible to IntelliJ, which lists the agent only "
              "from this folder or from a plugin installed in IntelliJ itself. If the agent shows "
              "twice, re-run with --drop-agent.")
    left = [] if args.dry_run else [s.name for s in sorted((KIT / "skills").iterdir()) if s.is_dir()
                                    and (copilot_home() / "skills" / s.name / "SKILL.md").exists()]
    if left:
        print(f"migrate: {len(left)} skill(s) stay in {show(copilot_home() / 'skills')} and still "
              "shadow the plugin's: " + ", ".join(left))
    return 1 if left else 0


# --------------------------------------------------------------------------- --with-mnemosyne


MNEMOSYNE_INSTALLER = KIT.parent / "mnemosyne" / "install.py"


def mnemosyne_argv(args) -> list[str]:
    """Zethus's flags, translated for mnemosyne/install.py. ``--force`` is deliberately not passed:
    there it would repoint ``MNEMOSYNE_REPO``, which deserves its own explicit run."""
    argv = ["--target", args.target] if args.target else ["--user"]
    if args.mnemosyne_repo:
        argv += ["--repo", args.mnemosyne_repo]
    if args.mnemosyne_copilot_hooks_dir:
        argv += ["--copilot-hooks-dir", args.mnemosyne_copilot_hooks_dir]
    if args.dry_run:
        argv.append("--dry-run")
    if args.uninstall:
        argv.append("--uninstall")
    if args.migrate_to_plugin:
        argv.append("--migrate-to-plugin")
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
    p.add_argument("--migrate-to-plugin", action="store_true",
                   help="with --user: remove the user-mode copy so the Copilot plugin's skills "
                        "aren't shadowed (--force removes edited files too)")
    p.add_argument("--drop-agent", action="store_true",
                   help="with --migrate-to-plugin: also remove the user-level agent file, which a "
                        "migration keeps for IntelliJ")
    p.add_argument("--with-mnemosyne", action="store_true",
                   help="then run mnemosyne/install.py: the package, a local memory repo, "
                        "MNEMOSYNE_REPO and its hooks (with --target, that repo's Copilot hooks; "
                        "with --user, ~/.copilot/hooks)")
    p.add_argument("--mnemosyne-repo", metavar="PATH",
                   help="with --with-mnemosyne: the memory repo (default ~/repos/mnemosyne-local)")
    p.add_argument("--mnemosyne-copilot-hooks-dir", metavar="PATH",
                   help="with --with-mnemosyne: write the user-level Copilot hook files here "
                        "instead of ~/.copilot/hooks")
    args = p.parse_args(argv)
    if not args.user and (args.uninstall or args.jetbrains_legacy or args.migrate_to_plugin):
        p.error("--uninstall, --jetbrains-legacy and --migrate-to-plugin need --user (a repo install "
                "is removed with git)")
    if args.drop_agent and not args.migrate_to_plugin:
        p.error("--drop-agent needs --migrate-to-plugin (--uninstall already removes the agent)")
    if args.migrate_to_plugin and args.uninstall:
        p.error("--migrate-to-plugin already uninstalls the user-mode copy; use one or the other")
    if (args.mnemosyne_repo or args.mnemosyne_copilot_hooks_dir) and not args.with_mnemosyne:
        p.error("--mnemosyne-repo and --mnemosyne-copilot-hooks-dir need --with-mnemosyne")
    if args.mnemosyne_copilot_hooks_dir and (args.uninstall or args.migrate_to_plugin):
        p.error("--uninstall and --migrate-to-plugin take no --mnemosyne-copilot-hooks-dir (the "
                "manifest knows what was written)")
    if args.mnemosyne_repo and args.migrate_to_plugin:
        p.error("--migrate-to-plugin takes no --mnemosyne-repo: it changes no memory repo")
    if args.user:
        action = (migrate_to_plugin if args.migrate_to_plugin
                  else uninstall_user if args.uninstall else install_user)
        code = action(args)
    else:
        code = install_repo(args)
    if not args.with_mnemosyne or (code != 0 and not (args.uninstall or args.migrate_to_plugin)):
        return code                      # a refused install wrote nothing; stop there too
    return max(code, run_mnemosyne(mnemosyne_argv(args)))


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Install Mnemosyne for your user account: the package, a local memory repo, ``MNEMOSYNE_REPO``
and the hooks, in one step.

    python mnemosyne/install.py                         # everything; memory repo ~/repos/mnemosyne-local
    python mnemosyne/install.py --dry-run               # show the plan only
    python mnemosyne/install.py --repo ~/notes/memory   # another memory repo
    python mnemosyne/install.py --target path/to/repo   # + Copilot hook files in that repo
    python mnemosyne/install.py --user                  # + Copilot hook files in ~/.copilot/hooks
    python mnemosyne/install.py --copilot-hooks-dir DIR # + the same, in a folder of your choosing
    python mnemosyne/install.py --uninstall             # undo it; the memory repo is never removed

It is a script beside the package rather than a ``mnemosyne install`` subcommand because its first
job is installing that package: it has to run from a clone before ``mnemosyne`` exists, and the
plugin it installs lives in the clone, not in the wheel. ``zethus/install.py --with-mnemosyne``
calls ``main()`` here rather than repeating any of it.

**What it does, in order.** Each step prints one line, and a re-run prints ``same`` or ``keep`` for
whatever is already in place:

1. **Package.** ``python -m pip install`` of this folder, for the Python the hooks run. The plugin's
   hooks call ``python``, so that is the default (then ``python3``, then this interpreter);
   ``--python`` picks another.
2. **Memory repo.** The default is ``$MNEMOSYNE_REPO`` if it already names a memory repo, else
   ``~/repos/mnemosyne-local``. A new one gets the engine's own init (``memory/`` and its
   ``.gitignore``), ``git init`` and a first commit, and no remote. An existing memory repo is kept
   as it is: nothing in it is written.
3. **MNEMOSYNE_REPO, persistently.** On Windows it goes in ``HKCU\\Environment``, which every
   process started afterwards inherits. Elsewhere it goes in a managed block in your shell's rc
   file: ``~/.zshrc``, ``~/.bashrc`` (``~/.bash_profile`` on macOS), fish's ``config.fish``, else
   ``~/.profile``.
4. **Claude Code plugin.** It copies ``plugin/`` into a local marketplace at
   ``~/.mnemosyne/claude-marketplace``, then runs ``claude plugin marketplace add`` and
   ``claude plugin install mnemosyne@mesmer-grimoire-local``. Where ``claude`` isn't on PATH it
   prints those two commands instead. It leaves a ``mnemosyne@...`` plugin from any other
   marketplace alone, so the hooks never fire twice.
5. **Copilot hooks in a repo (``--target`` only).** ``.github/hooks/mnemosyne.json`` (Copilot's
   format, generated from ``plugin/hooks/hooks.json``) and a copy of the bridge,
   ``.github/hooks/mnemosyne_hook.py``. Both are meant to be committed: the commands are
   repo-relative and fail open where Mnemosyne isn't installed. The Copilot CLI ran this format in
   the lessons-capture spec's §4.7.1 (E2); VS Code and the cloud agent read the same file but are
   unverified. They are skipped when the repo's ``.claude/settings.json`` already registers the
   bridge, because the Copilot CLI would then fire twice.
6. **Copilot hooks for your account (``--user`` or ``--copilot-hooks-dir`` only).** The same two
   files in ``~/.copilot/hooks``, or in the folder ``--copilot-hooks-dir`` names instead (which
   implies ``--user``). The IntelliJ Copilot plugin reads ``~/.copilot/hooks``; no other host has
   been checked (spec §4.7), and no host has run this file yet. This file fires in every repo, so
   its commands name the script by absolute path where the repo's are relative, and it is written
   for one machine: never commit it. ``--python`` sets the interpreter it calls, and otherwise it
   calls ``python3`` / ``python`` as the repo's does. A repo that also has its own copy doesn't
   double-fire, because the engine claims each event once (``mnemosyne.candidates``).

**Safety.** Everything is checked before anything is written, so a refused install writes nothing:

- a ``--repo`` folder that exists, isn't empty and has no ``memory/`` is refused, even with ``--force``;
- ``MNEMOSYNE_REPO`` already set to another folder, and not by this installer, is a conflict;
  ``--force`` repoints it (the old folder is not touched);
- a ``--target`` hook file that differs from the kit's is a conflict; ``--force`` overwrites it;
- a file in the plugin copy or the Copilot user hooks that you edited is a conflict; ``--force``
  overwrites it;
- a file in a Copilot user-hooks folder that this installer didn't write is never overwritten, even
  with ``--force``; one already identical to the kit's is left in place and stays yours.

Everything installed is recorded in ``~/.mnemosyne/install-manifest.json``. ``--uninstall``
reverses it: the plugin and its marketplace, the plugin copy and the Copilot user hooks (unedited
files; ``--force`` removes edited ones too) and any folder made for them that is now empty,
``MNEMOSYNE_REPO`` if it still holds the value set here, the rc block, and the package if this
installer was what installed it. The memory repo is never removed. Hook files in a ``--target``
repo are committed files, so they are removed with git, as Zethus's repo install is.

Exit codes: 0 done (or dry run) · 1 conflicts, a failed step, or nothing to uninstall · 2 usage error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent
PLUGIN = KIT / "plugin"
PACKAGE = "mnemosyne-reflexion"
ENV_NAME = "MNEMOSYNE_REPO"
MARKETPLACE = "mesmer-grimoire-local"
PLUGIN_ID = "mnemosyne@" + MARKETPLACE
BLOCK_START = "# >>> mnemosyne (managed by mnemosyne/install.py) >>>"
BLOCK_END = "# <<< mnemosyne <<<"
BRIDGE = "mnemosyne_hook.py"
# Claude Code event -> Copilot event (spec §4.7). PostToolUseFailure has no Copilot twin: there,
# postToolUse fires for failures too.
COPILOT_EVENTS = {"SessionStart": "sessionStart", "UserPromptSubmit": "userPromptSubmitted",
                  "PostToolUse": "postToolUse", "Stop": "agentStop", "PreCompact": "preCompact"}
PLATFORM = sys.platform            # tests patch this to exercise each OS's branch


# --------------------------------------------------------------------------- seams (tests patch)


def run(cmd: list, cwd: Path | None = None) -> tuple[int, str, str]:
    """Run a command; return (returncode, stdout, stderr), stripped. 127 if it isn't found."""
    try:
        r = subprocess.run([str(c) for c in cmd], cwd=cwd, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True)
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def which(name: str) -> str | None:
    return shutil.which(name)


def win_env_get() -> str | None:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            return str(winreg.QueryValueEx(key, ENV_NAME)[0])
    except OSError:
        return None


def win_env_set(value: str | None) -> None:
    """Set (or, with None, delete) the user variable, then tell running apps it changed."""
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
        if value is None:
            try:
                winreg.DeleteValue(key, ENV_NAME)
            except OSError:
                pass
        else:
            winreg.SetValueEx(key, ENV_NAME, 0, winreg.REG_SZ, value)
    try:
        import ctypes
        # WM_SETTINGCHANGE "Environment" to every top-level window, so Explorer (and anything it
        # starts from now on) picks the change up without a sign-out.
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, "Environment", 0x2, 2000, None)
    except Exception:
        pass


# --------------------------------------------------------------------------- small helpers


def is_windows() -> bool:
    return PLATFORM.startswith("win")


def home() -> Path:
    return Path.home()


def state_dir() -> Path:
    """``~/.mnemosyne``, the engine's own home (its store cache defaults to ``stores/`` here)."""
    return home() / ".mnemosyne"


def manifest_path() -> Path:
    return state_dir() / "install-manifest.json"


def marketplace_dir() -> Path:
    return state_dir() / "claude-marketplace"


def default_repo_path() -> Path:
    return home() / "repos" / "mnemosyne-local"


def copilot_user_dir() -> Path:
    """``~/.copilot/hooks``. Deliberately not under ``$COPILOT_HOME``, as in zethus/install.py:
    only the CLI honours that variable."""
    return home() / ".copilot" / "hooks"


def show(path) -> str:
    """``~/``-relative for display, so pasted output never carries a user name."""
    p = Path(path)
    try:
        return "~/" + p.resolve().relative_to(home().resolve()).as_posix()
    except (ValueError, OSError):
        return p.as_posix()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def current_hash(path: Path) -> str | None:
    return sha256(path.read_bytes()) if path.is_file() else None


def same_path(a, b) -> bool:
    if not a or not b:
        return False
    norm = lambda p: os.path.normcase(str(Path(p).expanduser().resolve()))  # noqa: E731
    return norm(a) == norm(b)


def say(label: str, what: str, note: str = "") -> None:
    print(f"{label:9} {what}" + (f"  ({note})" if note else ""))


def prune(start: Path, stop: Path) -> None:
    """Remove empty folders from ``start`` upward, never ``stop`` or anything above it."""
    here = start
    while here != stop and stop in here.parents:
        try:
            here.rmdir()
        except OSError:
            return
        here = here.parent


# --------------------------------------------------------------------------- manifest


def read_manifest() -> dict:
    try:
        doc = json.loads(manifest_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def write_manifest(doc: dict) -> None:
    path = manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"_readme": "What mnemosyne/install.py set up. install.py --uninstall reverses it; "
                       "the memory repo is never removed.", "version": 1}
    body.update({k: doc[k] for k in sorted(doc) if k not in body})
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(body, fh, indent=2)
        fh.write("\n")


# --------------------------------------------------------------------------- MNEMOSYNE_REPO


def rc_file() -> Path:
    shell = Path(os.environ.get("SHELL", "")).name
    if shell == "zsh":
        return home() / ".zshrc"
    if shell == "bash":
        return home() / (".bash_profile" if PLATFORM == "darwin" else ".bashrc")
    if shell == "fish":
        return home() / ".config" / "fish" / "config.fish"
    return home() / ".profile"


_BLOCK = re.compile(re.escape(BLOCK_START) + r"\n(.*?)\n" + re.escape(BLOCK_END) + r"\n?", re.S)


def rc_block(path: Path, value: str) -> str:
    if path.name == "config.fish":
        line = f"set -gx {ENV_NAME} {shlex.quote(value)}"
    else:
        line = f"export {ENV_NAME}={shlex.quote(value)}"
    return f"{BLOCK_START}\n{line}\n{BLOCK_END}\n"


def rc_value(path: Path) -> str | None:
    try:
        m = _BLOCK.search(path.read_text(encoding="utf-8"))
    except OSError:
        return None
    if not m:
        return None
    line = re.sub(r"^export (\w+)=", r"\1 ", m.group(1).strip())   # fish's line needs no change
    words = shlex.split(line)
    return words[-1] if words else None


def rc_write(path: Path, value: str | None) -> None:
    """Put our block in ``path`` (replacing an older one), or take it out with None."""
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if value is None:
        text = _BLOCK.sub("", text)
    elif _BLOCK.search(text):
        text = _BLOCK.sub(lambda _m: rc_block(path, value), text)
    else:
        text += ("\n" if text and not text.endswith("\n") else "") + rc_block(path, value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def env_where() -> str:
    return "HKCU\\Environment" if is_windows() else show(rc_file())


def env_persisted() -> str | None:
    return win_env_get() if is_windows() else rc_value(rc_file())


def env_current() -> str | None:
    """What a new session would see: the persisted value, else one set some other way."""
    return env_persisted() or os.environ.get(ENV_NAME) or None


def env_store(value: str | None, where: str | None = None) -> None:
    if is_windows():
        win_env_set(value)
    else:
        rc_write(Path(where) if where else rc_file(), value)


# --------------------------------------------------------------------------- payloads


def plugin_payloads() -> list[tuple[Path, bytes]]:
    """The plugin copied into the local marketplace, plus the marketplace's own manifest."""
    dest = marketplace_dir() / "plugins" / "mnemosyne"
    out = []
    for src in sorted(p for p in PLUGIN.rglob("*") if p.is_file()):
        rel = src.relative_to(PLUGIN)
        if "__pycache__" in rel.parts or src.suffix in (".pyc", ".pyo"):
            continue
        out.append((dest / rel, src.read_bytes()))
    version = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
    market = {"name": MARKETPLACE, "owner": {"name": "mesmer-grimoire"},
              "metadata": {"description": "Local marketplace written by mnemosyne/install.py. "
                                          "Re-run the installer to refresh it."},
              "plugins": [{"name": "mnemosyne", "source": "./plugins/mnemosyne", "version": version,
                           "description": "Reflexion memory: recall on prompt, sync on session "
                                          "start, lessons capture in shadow mode."}]}
    out.append((marketplace_dir() / ".claude-plugin" / "marketplace.json",
                (json.dumps(market, indent=2) + "\n").encode("utf-8")))
    return out


def ps_quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def copilot_hooks(user_dir: Path | None = None, python: str | None = None) -> bytes:
    """``mnemosyne.json``, generated from the plugin's hooks.json so the registrations can't
    drift: one entry per mode, no ``--host`` (the bridge infers it, and the CLI, VS Code and the
    cloud agent all read this one file).

    Without ``user_dir`` it is the repo's copy: repo-relative, run from the repo root. With it, the
    file fires wherever a session happens to be, so a relative path would find no script and fail
    silently: the script is named absolutely, and no ``cwd`` is set."""
    claude = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    hooks = {}
    for event, copilot_event in COPILOT_EVENTS.items():
        (entry,) = claude[event][0]["hooks"]
        mode = entry["command"].split()[-1]
        if user_dir is None:
            script = f".github/hooks/{BRIDGE} {mode}"
            hook = {"type": "command", "bash": f"python3 {script}",
                    "powershell": f"python {script}", "cwd": "."}
        else:
            script = (user_dir / BRIDGE).as_posix()
            sh, ps = (shlex.quote(python), f"& {ps_quote(python)}") if python else ("python3", "python")
            hook = {"type": "command", "bash": f"{sh} {shlex.quote(script)} {mode}",
                    "powershell": f"{ps} {ps_quote(script)} {mode}"}
        if "timeout" in entry:
            hook["timeoutSec"] = entry["timeout"]
        hooks[copilot_event] = [hook]
    return (json.dumps({"version": 1, "hooks": hooks}, indent=2) + "\n").encode("utf-8")


def target_payloads(target: Path) -> list[tuple[Path, bytes]]:
    hooks = target / ".github" / "hooks"
    return [(hooks / "mnemosyne.json", copilot_hooks()),
            (hooks / BRIDGE, (PLUGIN / "hooks" / BRIDGE).read_bytes())]


def user_hook_payloads(hooks: Path, python: str | None) -> list[tuple[Path, bytes]]:
    return [(hooks / "mnemosyne.json", copilot_hooks(hooks, python)),
            (hooks / BRIDGE, (PLUGIN / "hooks" / BRIDGE).read_bytes())]


def claude_settings_has_bridge(target: Path) -> bool:
    for name in ("settings.json", "settings.local.json"):
        try:
            if BRIDGE in (target / ".claude" / name).read_text(encoding="utf-8"):
                return True
        except OSError:
            continue
    return False


# --------------------------------------------------------------------------- host probes


def installed_plugins(claude: str) -> list[str]:
    code, out, _ = run([claude, "plugin", "list", "--json"])
    try:
        rows = json.loads(out) if code == 0 else []
    except ValueError:
        return []
    return [r.get("id", "") for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def known_marketplaces(claude: str) -> list[str]:
    code, out, _ = run([claude, "plugin", "marketplace", "list", "--json"])
    try:
        rows = json.loads(out) if code == 0 else []
    except ValueError:
        return []
    return [r.get("name", "") for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def hook_python(arg: str | None) -> str:
    return arg or which("python") or which("python3") or sys.executable


def engine():
    """The engine from this clone, for its own ``init``."""
    src = str(KIT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    from mnemosyne import core
    return core


# --------------------------------------------------------------------------- install


def repo_state(repo: Path) -> str:
    if (repo / "memory").is_dir():
        return "keep"
    if repo.exists() and (not repo.is_dir() or any(repo.iterdir())):
        return "refuse"
    return "create"


def file_action(dest: Path, data: bytes, recorded: str | None) -> str:
    have = current_hash(dest)
    if have is None:
        return "create"
    if have == sha256(data):
        return "same"
    if recorded is None:
        return "foreign"
    return "update" if have == recorded else "conflict"


def create_repo(repo: Path) -> str:
    """mnemosyne's own init, then ``git init`` and a first commit, no remote. Returns a note."""
    engine().init_repo(repo)
    if run(["git", "init", "-q", str(repo)])[0] != 0:
        return "git not found: created without git"
    run(["git", "-C", str(repo), "add", "-A"])
    code, _, err = run(["git", "-C", str(repo), "commit", "-q", "-m", "Initialize Mnemosyne memory repo"])
    if code != 0:
        return "git init done; first commit skipped (set git user.name and user.email, then commit)"
    return "mnemosyne init + git init, no remote"


def install(args) -> int:
    manifest = read_manifest()
    files: dict = dict(manifest.get("files", {}))
    py = hook_python(args.python)
    current = env_current()
    if args.repo:
        repo = Path(args.repo).expanduser().resolve()
    elif current and (Path(current).expanduser() / "memory").is_dir():
        repo = Path(current).expanduser().resolve()
    else:
        repo = default_repo_path().resolve()
    target = Path(args.target).resolve() if args.target else None

    # ---- plan everything, then refuse before writing anything
    state = repo_state(repo)
    recorded_env = (manifest.get("env") or {}).get("value")
    if same_path(current, repo):
        env_action = "same"
    elif not current:
        env_action = "create"
    elif same_path(current, recorded_env) or args.force:
        env_action = "update"
    else:
        env_action = "conflict"

    claude = which("claude")
    plugins = installed_plugins(claude) if claude else []
    others = [p for p in plugins if p.startswith("mnemosyne@") and p != PLUGIN_ID]
    plugin_steps = [] if others else [
        (dest, data, file_action(dest, data, files.get(dest.as_posix())))
        for dest, data in plugin_payloads()]
    target_skip = target is not None and claude_settings_has_bridge(target)
    target_steps = []
    if target is not None and not target_skip:
        for dest, data in target_payloads(target):
            have = current_hash(dest)
            action = "create" if have is None else "same" if have == sha256(data) else "conflict"
            target_steps.append((dest, data, action))
    hook_record = manifest.get("copilot_hooks") or {}
    hook_files: dict = dict(hook_record.get("files", {}))
    hook_steps = []
    if args.user or args.copilot_hooks_dir:
        user_dir = (Path(args.copilot_hooks_dir).expanduser().resolve() if args.copilot_hooks_dir
                    else copilot_user_dir())
        hook_steps = [(dest, data, file_action(dest, data, hook_files.get(dest.as_posix())))
                      for dest, data in user_hook_payloads(user_dir, args.python)]

    refused, conflicts = [], []
    if state == "refuse":
        refused.append(f"{show(repo)}  (exists and isn't a memory repo: pick another --repo; "
                       "never written into, even with --force)")
    if env_action == "conflict":
        conflicts.append(f"{ENV_NAME}  (already {show(current)}; --force repoints it to "
                         f"{show(repo)} and leaves that folder untouched)")
    for dest, _, action in plugin_steps + hook_steps:
        if action == "foreign":
            refused.append(f"{show(dest)}  (not written by this installer: never overwritten)")
        elif action == "conflict":
            conflicts.append(f"{show(dest)}  (edited since install: --force overwrites it)")
    for dest, _, action in target_steps:
        if action == "conflict":
            conflicts.append(f"{show(dest)}  (differs from the kit's: --force overwrites it)")
    if refused or (conflicts and not args.force):
        print("install: nothing was written. These need a decision first:")
        for line in refused + conflicts:
            print(f"  {line}")
        return 1

    dry = args.dry_run
    changed = False
    try:
        # 1. package
        pkg = manifest.get("package") or {}
        present = run([py, "-m", "pip", "show", PACKAGE])[0] == 0
        say("update" if present else "install", f"{PACKAGE} for {show(py)}",
            f"pip install from {show(KIT)}")
        if not dry:
            code, out, err = run([py, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                                  "--force-reinstall", "--no-deps", str(KIT)])
            if code != 0:
                print(f"install: pip failed for {show(py)}:\n  " + (err or out).replace("\n", "\n  "))
                print("  (An externally managed Python refuses pip: pass --python with an "
                      "interpreter you can install into, and put it first on PATH as `python`.)")
                return 1
            same_py = same_path(pkg.get("python"), py)
            manifest["package"] = {"python": py,
                                   "preexisting": pkg.get("preexisting", present) if same_py else present}
            changed = True

        # 2. memory repo
        old = manifest.get("repo") or {}
        if state == "keep":
            say("keep", show(repo), "an existing memory repo: nothing in it is touched")
            created = bool(old.get("created")) and same_path(old.get("path"), repo)
        else:
            say("create", show(repo), create_repo(repo) if not dry else "mnemosyne init + git init, no remote")
            created = True
        if not dry:
            manifest["repo"] = {"path": str(repo), "created": created}

        # 3. MNEMOSYNE_REPO
        label = {"same": "same", "create": "set", "update": "update"}[env_action]
        say(label, f"{ENV_NAME}={show(repo)}", f"in {env_where()}")
        if not dry:
            if env_action != "same":
                env_store(str(repo))
            manifest["env"] = {"value": str(repo),
                               "where": "windows-user" if is_windows() else str(rc_file())}
            changed = True

        # 4. Claude Code plugin
        if others:
            say("keep", f"Claude Code plugin {others[0]}",
                "already installed from another marketplace; left alone so hooks fire once")
        else:
            refreshed = False
            for dest, data, action in plugin_steps:
                if action == "same":
                    files[dest.as_posix()] = sha256(data)
                    continue
                say({"create": "create", "update": "update", "conflict": "overwrite"}[action], show(dest))
                if not dry:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(data)
                    files[dest.as_posix()] = sha256(data)
                    refreshed = True
            if not plugin_steps or all(a == "same" for _, _, a in plugin_steps):
                say("same", show(marketplace_dir()), "plugin copy is current")
            if not dry:
                manifest["files"] = files
                changed = True
            if claude is None:
                say("skip", "Claude Code plugin", "`claude` isn't on PATH. Later, run: claude plugin "
                    f"marketplace add {show(marketplace_dir())} && claude plugin install {PLUGIN_ID}")
            elif PLUGIN_ID in plugins:
                if refreshed:
                    say("update", f"Claude Code plugin {PLUGIN_ID}", "restart Claude Code to load it")
                    if not dry:
                        run([claude, "plugin", "marketplace", "update", MARKETPLACE])
                        run([claude, "plugin", "update", PLUGIN_ID])
                else:
                    say("same", f"Claude Code plugin {PLUGIN_ID}")
                if not dry:
                    manifest["claude_plugin"] = PLUGIN_ID
            else:
                say("install", f"Claude Code plugin {PLUGIN_ID}", "user scope")
                if not dry:
                    if MARKETPLACE not in known_marketplaces(claude):
                        code, out, err = run([claude, "plugin", "marketplace", "add", str(marketplace_dir())])
                        if code != 0:
                            print(f"install: claude plugin marketplace add failed: {err or out}")
                            return 1
                    code, out, err = run([claude, "plugin", "install", PLUGIN_ID, "--scope", "user"])
                    if code != 0:
                        print(f"install: claude plugin install failed: {err or out}")
                        return 1
                    manifest["claude_plugin"] = PLUGIN_ID

        # 5. Copilot hooks in a repo
        if target_skip:
            say("skip", f"{show(target / '.github' / 'hooks')}",
                "the repo's .claude/settings.json already runs the bridge; a Copilot copy would "
                "fire twice on the Copilot CLI")
        for dest, data, action in target_steps:
            say({"create": "create", "same": "same", "conflict": "overwrite"}[action], show(dest),
                "commit it" if action != "same" else "")
            if not dry and action != "same":
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)

        # 6. Copilot hooks for the user account
        made = list(hook_record.get("dirs", []))
        for dest, data, action in hook_steps:
            if action == "same":
                ours = dest.as_posix() in hook_files
                say("same" if ours else "keep", show(dest),
                    "" if ours else "identical, but not written here: --uninstall leaves it")
                continue
            say({"create": "create", "update": "update", "conflict": "overwrite"}[action], show(dest))
            if not dry:
                made += [str(p) for p in (dest.parent, *dest.parent.parents) if not p.exists()]
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                hook_files[dest.as_posix()] = sha256(data)
                manifest["copilot_hooks"] = {"files": hook_files, "dirs": made}
                changed = True
    finally:
        if changed and not dry:
            write_manifest(manifest)

    if dry:
        print("dry run: nothing written")
        return 0
    where = ("new terminals and apps" if is_windows()
             else f"new shells (or `source {show(rc_file())}` now)")
    print(f"installed. {ENV_NAME} is visible to {where}; start a new agent session to load the "
          "hooks. Check with: mnemosyne doctor")
    return 0


# --------------------------------------------------------------------------- uninstall


def uninstall(args) -> int:
    manifest = read_manifest()
    if not manifest:
        print(f"uninstall: no Mnemosyne install found ({show(manifest_path())} is missing)")
        return 1
    dry = args.dry_run
    failed = False

    if manifest.get("claude_plugin"):
        claude = which("claude")
        if claude is None:
            say("skip", f"Claude Code plugin {PLUGIN_ID}", "`claude` isn't on PATH. Later, run: "
                f"claude plugin uninstall {PLUGIN_ID} && claude plugin marketplace remove {MARKETPLACE}")
        else:
            say("remove", f"Claude Code plugin {PLUGIN_ID}")
            if not dry:
                code, out, err = run([claude, "plugin", "uninstall", PLUGIN_ID, "--scope", "user"])
                if code != 0 and PLUGIN_ID in installed_plugins(claude):
                    print(f"uninstall: claude plugin uninstall failed: {err or out}")
                    failed = True
                if MARKETPLACE in known_marketplaces(claude):
                    run([claude, "plugin", "marketplace", "remove", MARKETPLACE])

    kept = 0
    hook_record = manifest.get("copilot_hooks") or {}
    tracked = {**(manifest.get("files") or {}), **hook_record.get("files", {})}
    for key, recorded in sorted(tracked.items()):
        path = Path(key)
        have = current_hash(path)
        if have is None:
            say("gone", show(path))
            continue
        if have != recorded and not args.force:
            kept += 1
            say("keep", show(path), "edited since install; --force removes it")
            continue
        say("remove", show(path))
        if not dry:
            path.unlink()
            prune(path.parent, state_dir())
    for folder in sorted(hook_record.get("dirs", []), key=len, reverse=True):
        if not dry:
            try:
                Path(folder).rmdir()
            except OSError:
                pass                     # it holds something that isn't ours: leave it

    env = manifest.get("env") or {}
    if env.get("value"):
        where = env.get("where")
        posix_where = None if where == "windows-user" else where
        now = win_env_get() if where == "windows-user" else (rc_value(Path(where)) if where else None)
        shown = "HKCU\\Environment" if where == "windows-user" else show(where or "")
        if same_path(now, env["value"]):
            say("unset", ENV_NAME, f"in {shown}")
            if not dry:
                if where == "windows-user":
                    win_env_set(None)
                else:
                    rc_write(Path(posix_where), None)
        else:
            say("keep", ENV_NAME, f"changed since install; left as {show(now) if now else 'unset'}")

    pkg = manifest.get("package") or {}
    if pkg.get("python") and not pkg.get("preexisting"):
        say("remove", f"{PACKAGE} from {show(pkg['python'])}")
        if not dry:
            code, out, err = run([pkg["python"], "-m", "pip", "uninstall", "-y", "--quiet", PACKAGE])
            if code != 0:
                print(f"uninstall: pip uninstall failed: {err or out}")
                failed = True
    elif pkg.get("python"):
        say("keep", f"{PACKAGE} in {show(pkg['python'])}", "it was installed before this installer ran")

    repo = (manifest.get("repo") or {}).get("path")
    if repo:
        say("keep", show(repo), "your memory repo is never removed")
    say("remove", show(manifest_path()))
    if dry:
        print("dry run: nothing removed")
        return 0
    if failed:
        print("uninstall: incomplete; the manifest is kept so a re-run can finish it")
        return 1
    manifest_path().unlink()
    prune(manifest_path().parent, home())
    print("uninstalled." + (f" {kept} edited file(s) kept." if kept else ""))
    return 0


# --------------------------------------------------------------------------- cli


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="install", description="Install Mnemosyne for your user "
                                "account: package, local memory repo, MNEMOSYNE_REPO and hooks.")
    p.add_argument("--repo", metavar="PATH", help="the memory repo (default: $MNEMOSYNE_REPO if it "
                   "already names one, else ~/repos/mnemosyne-local)")
    p.add_argument("--target", metavar="DIR", help="also write Copilot hook files into this "
                   "repository's .github/hooks/")
    p.add_argument("--user", action="store_true", help="also write Copilot hook files for your "
                   "account, into ~/.copilot/hooks/")
    p.add_argument("--copilot-hooks-dir", metavar="PATH", help="like --user, but into this folder "
                   "instead of ~/.copilot/hooks/")
    p.add_argument("--python", metavar="PATH", help="the interpreter the hooks run (default: "
                   "`python` on PATH)")
    p.add_argument("--force", action="store_true", help="repoint MNEMOSYNE_REPO and overwrite "
                   "edited or differing files")
    p.add_argument("--dry-run", action="store_true", help="print the plan; write nothing")
    p.add_argument("--uninstall", action="store_true", help="remove what this installer set up "
                   "(never the memory repo)")
    args = p.parse_args(argv)
    if args.uninstall and (args.repo or args.target or args.copilot_hooks_dir):
        p.error("--uninstall takes no --repo, --target or --copilot-hooks-dir (the manifest knows "
                "what was written; a repo's hook files are removed with git)")
    if args.target and not Path(args.target).is_dir():
        print(f"install: target is not a directory: {args.target}", file=sys.stderr)
        return 2
    if args.copilot_hooks_dir:
        if Path(args.copilot_hooks_dir).expanduser().is_file():
            print(f"install: --copilot-hooks-dir is a file: {args.copilot_hooks_dir}", file=sys.stderr)
            return 2
        if args.target and same_path(args.copilot_hooks_dir, Path(args.target) / ".github" / "hooks"):
            p.error("--copilot-hooks-dir can't be the --target repo's .github/hooks: that file is "
                    "committed, and this one holds a path for one machine")
    return uninstall(args) if args.uninstall else install(args)


if __name__ == "__main__":
    sys.exit(main())

"""CI coverage for mnemosyne/install.py, the one-step Mnemosyne installer.

Every test runs against a throwaway home. pip and the ``claude`` CLI are faked (``FakeHost``)
because a real run would install into the test's interpreter and the developer's Claude Code;
git runs for real, so the memory repo it creates is a real repository. The Windows registry is a
dict, so both the Windows and the POSIX branch run on every OS.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
INSTALLER = REPO / "mnemosyne" / "install.py"


def load_installer():
    """Load under the name zethus/install.py uses, so both see one module (and one set of fakes)."""
    if "mnemosyne_install" in sys.modules:
        return sys.modules["mnemosyne_install"]
    spec = importlib.util.spec_from_file_location("mnemosyne_install", INSTALLER)
    module = importlib.util.module_from_spec(spec)
    sys.modules["mnemosyne_install"] = module
    spec.loader.exec_module(module)
    return module


mi = load_installer()


class FakeHost:
    """Stands in for pip, ``claude`` and the registry; passes git through to the real one."""

    def __init__(self, claude=True, package_present=False, plugins=(), pip_fails=False):
        self.calls: list[list[str]] = []
        self.claude = claude
        self.package_present = package_present
        self.plugins = list(plugins)
        self.marketplaces: list[str] = []
        self.pip_fails = pip_fails
        self.registry: dict[str, str] = {}

    def which(self, name):
        if name == "claude":
            return "claude" if self.claude else None
        return {"python": "/usr/bin/python"}.get(name)

    def run(self, cmd, cwd=None):
        cmd = [str(c) for c in cmd]
        if cmd[0] == "git":
            r = subprocess.run(cmd, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True)
            return r.returncode, r.stdout.strip(), r.stderr.strip()
        self.calls.append(cmd)
        if cmd[1:4] == ["-m", "pip", "show"]:
            return (0 if self.package_present else 1), "", ""
        if cmd[1:4] == ["-m", "pip", "install"]:
            if self.pip_fails:
                return 1, "", "error: externally-managed-environment"
            self.package_present = True
            return 0, "", ""
        if cmd[1:4] == ["-m", "pip", "uninstall"]:
            self.package_present = False
            return 0, "", ""
        if cmd[0] == "claude":
            rest = cmd[1:]
            if rest == ["plugin", "list", "--json"]:
                return 0, json.dumps([{"id": p} for p in self.plugins]), ""
            if rest == ["plugin", "marketplace", "list", "--json"]:
                return 0, json.dumps([{"name": m} for m in self.marketplaces]), ""
            if rest[:3] == ["plugin", "marketplace", "add"]:
                self.marketplaces.append(mi.MARKETPLACE)
            elif rest[:3] == ["plugin", "marketplace", "remove"]:
                self.marketplaces.remove(rest[3])
            elif rest[:2] == ["plugin", "install"]:
                self.plugins.append(rest[2])
            elif rest[:2] == ["plugin", "uninstall"]:
                self.plugins.remove(rest[2])
            return 0, "", ""
        raise AssertionError(f"unexpected command {cmd}")

    def mutating(self):
        """The calls that change something (pip show and the list commands only read)."""
        return [c for c in self.calls if "show" not in c and "list" not in c]

    def win_get(self):
        return self.registry.get(mi.ENV_NAME)

    def win_set(self, value):
        if value is None:
            self.registry.pop(mi.ENV_NAME, None)
        else:
            self.registry[mi.ENV_NAME] = value


class InstallerCase(unittest.TestCase):
    platform = "linux"
    shell = "/bin/bash"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / "home"
        self.home.mkdir()
        env = {k: v for k, v in os.environ.items() if k not in (mi.ENV_NAME, "COPILOT_HOME")}
        env.update(HOME=str(self.home), USERPROFILE=str(self.home), SHELL=self.shell,
                   GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
        for patcher in (mock.patch.dict(os.environ, env, clear=True),
                        mock.patch.object(mi, "PLATFORM", self.platform)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.host = self.fake()

    def fake(self, **kw):
        host = FakeHost(**kw)
        for name, fn in (("run", host.run), ("which", host.which),
                         ("win_env_get", host.win_get), ("win_env_set", host.win_set)):
            patcher = mock.patch.object(mi, name, fn)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.host = host
        return host

    def install(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = mi.main(list(argv))
        return code, out.getvalue() + err.getvalue()

    @property
    def repo(self):
        return self.home / "repos" / "mnemosyne-local"

    @property
    def market(self):
        return self.home / ".mnemosyne" / "claude-marketplace"

    def manifest(self):
        return json.loads((self.home / ".mnemosyne" / "install-manifest.json").read_text(encoding="utf-8"))

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, text=True,
                              stdin=subprocess.DEVNULL).stdout.strip()

    def tree(self):
        return sorted(p.relative_to(self.home).as_posix() for p in self.home.rglob("*"))


class PosixInstall(InstallerCase):
    def test_dry_run_writes_nothing(self):
        code, out = self.install("--dry-run")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.tree(), [])
        self.assertEqual(self.host.mutating(), [])
        for line in ("install   mnemosyne-reflexion", "create    ~/repos/mnemosyne-local",
                     "set       MNEMOSYNE_REPO=~/repos/mnemosyne-local  (in ~/.bashrc)",
                     f"install   Claude Code plugin {mi.PLUGIN_ID}", "dry run: nothing written"):
            self.assertIn(line, out)

    def test_installs_every_piece(self):
        code, out = self.install()
        self.assertEqual(code, 0, out)
        # the memory repo: the engine's init, a git repo with one commit, and no remote
        self.assertTrue((self.repo / "memory" / "lessons.jsonl").is_file())
        self.assertIn(".store.lock", (self.repo / "memory" / ".gitignore").read_text(encoding="utf-8"))
        self.assertEqual(self.git("rev-list", "--count", "HEAD"), "1")
        self.assertEqual(self.git("remote"), "")
        # MNEMOSYNE_REPO in the shell's rc file
        rc = (self.home / ".bashrc").read_text(encoding="utf-8")
        self.assertIn(f"export MNEMOSYNE_REPO={self.repo.resolve()}", rc.replace("'", ""))
        self.assertEqual(mi.rc_value(self.home / ".bashrc"), str(self.repo.resolve()))
        # the plugin, copied into a local marketplace and installed through the claude CLI
        self.assertTrue((self.market / "plugins/mnemosyne/hooks/hooks.json").is_file())
        self.assertTrue((self.market / "plugins/mnemosyne/.claude-plugin/plugin.json").is_file())
        self.assertFalse(any("__pycache__" in p for p in self.tree()))
        market = json.loads((self.market / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
        self.assertEqual(market["name"], mi.MARKETPLACE)
        self.assertEqual(market["plugins"][0]["source"], "./plugins/mnemosyne")
        pip, add, inst = self.host.mutating()
        self.assertEqual(pip[:3], ["/usr/bin/python", "-m", "pip"])
        self.assertEqual(pip[-1], str(mi.KIT))
        self.assertEqual(add[:4], ["claude", "plugin", "marketplace", "add"])
        self.assertEqual(inst, ["claude", "plugin", "install", mi.PLUGIN_ID, "--scope", "user"])
        m = self.manifest()
        self.assertEqual(m["claude_plugin"], mi.PLUGIN_ID)
        self.assertEqual(m["package"], {"python": "/usr/bin/python", "preexisting": False})
        self.assertEqual(m["env"]["where"], str(self.home / ".bashrc"))

    def test_rerun_is_idempotent(self):
        self.install()
        rc_before = (self.home / ".bashrc").read_bytes()
        head = self.git("rev-parse", "HEAD")
        self.host.calls.clear()
        code, out = self.install()
        self.assertEqual(code, 0, out)
        self.assertIn("keep      ~/repos/mnemosyne-local", out)
        self.assertIn("same      MNEMOSYNE_REPO", out)
        self.assertIn(f"same      Claude Code plugin {mi.PLUGIN_ID}", out)
        self.assertEqual((self.home / ".bashrc").read_bytes(), rc_before)
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        # only the package is refreshed from the clone; no claude command runs again
        self.assertEqual([c[:4] for c in self.host.mutating()],
                         [["/usr/bin/python", "-m", "pip", "install"]])
        self.assertTrue(self.manifest()["repo"]["created"])

    def test_rc_block_is_replaced_not_appended(self):
        rc = self.home / ".bashrc"
        rc.write_text("alias ll='ls -l'\n", encoding="utf-8")
        self.install()
        other = self.home / "elsewhere"
        self.install("--repo", str(other))
        text = rc.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("alias ll='ls -l'\n"))
        self.assertEqual(text.count(mi.BLOCK_START), 1)
        self.assertEqual(mi.rc_value(rc), str(other.resolve()))

    def test_existing_memory_repo_is_kept_untouched(self):
        mine = self.home / "notes" / "memory-repo"
        (mine / "memory").mkdir(parents=True)
        (mine / "memory" / "lessons.jsonl").write_text('{"id": "L-0001"}\n', encoding="utf-8")
        (mine / "README.md").write_text("mine", encoding="utf-8")
        before = {p: p.read_bytes() for p in mine.rglob("*") if p.is_file()}
        code, out = self.install("--repo", str(mine))
        self.assertEqual(code, 0, out)
        self.assertIn("keep      ~/notes/memory-repo", out)
        self.assertEqual({p: p.read_bytes() for p in mine.rglob("*") if p.is_file()}, before)
        self.assertFalse((mine / ".git").exists())     # no git init in someone else's repo
        self.assertFalse(self.manifest()["repo"]["created"])

    def test_default_follows_an_existing_memory_repo_in_the_environment(self):
        mine = self.home / "memory-elsewhere"
        (mine / "memory").mkdir(parents=True)
        with mock.patch.dict(os.environ, {mi.ENV_NAME: str(mine)}):
            code, out = self.install("--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn("keep      ~/memory-elsewhere", out)
        self.assertNotIn("repos/mnemosyne-local", out)

    def test_a_folder_that_isnt_a_memory_repo_is_refused_even_with_force(self):
        self.repo.mkdir(parents=True)
        (self.repo / "notes.txt").write_text("not a memory repo", encoding="utf-8")
        code, out = self.install("--force")
        self.assertEqual(code, 1)
        self.assertIn("isn't a memory repo", out)
        self.assertEqual(self.tree(), ["repos", "repos/mnemosyne-local", "repos/mnemosyne-local/notes.txt"])
        self.assertEqual(self.host.mutating(), [])

    def test_a_different_mnemosyne_repo_is_a_conflict_until_forced(self):
        with mock.patch.dict(os.environ, {mi.ENV_NAME: str(self.home / "old-memory")}):
            code, out = self.install()
            self.assertEqual(code, 1)
            self.assertIn("MNEMOSYNE_REPO  (already ~/old-memory", out)
            self.assertEqual(self.tree(), [])
            code, out = self.install("--force")
        self.assertEqual(code, 0, out)
        self.assertIn("update    MNEMOSYNE_REPO=~/repos/mnemosyne-local", out)
        self.assertFalse((self.home / "old-memory").exists())

    def test_without_claude_the_plugin_is_staged_and_the_commands_printed(self):
        self.fake(claude=False)
        code, out = self.install()
        self.assertEqual(code, 0, out)
        self.assertIn("skip      Claude Code plugin", out)
        self.assertIn(f"claude plugin install {mi.PLUGIN_ID}", out)
        self.assertTrue((self.market / ".claude-plugin/marketplace.json").is_file())
        self.assertNotIn("claude_plugin", self.manifest())

    def test_a_mnemosyne_plugin_from_another_marketplace_is_left_alone(self):
        self.fake(plugins=["mnemosyne@mnemosyne-local"])
        code, out = self.install()
        self.assertEqual(code, 0, out)
        self.assertIn("keep      Claude Code plugin mnemosyne@mnemosyne-local", out)
        self.assertFalse(self.market.exists())
        self.assertFalse([c for c in self.host.mutating() if c[0] == "claude"])

    def test_an_edited_plugin_file_is_a_conflict(self):
        self.install()
        skill = self.market / "plugins/mnemosyne/skills/reflexion-memory/SKILL.md"
        skill.write_text("my edit", encoding="utf-8")
        code, out = self.install()
        self.assertEqual(code, 1)
        self.assertIn("edited since install", out)
        self.assertEqual(skill.read_text(encoding="utf-8"), "my edit")
        code, out = self.install("--force")
        self.assertEqual(code, 0, out)
        self.assertNotEqual(skill.read_text(encoding="utf-8"), "my edit")
        self.assertIn(f"update    Claude Code plugin {mi.PLUGIN_ID}", out)

    def test_pip_failure_stops_before_anything_else(self):
        self.fake(pip_fails=True)
        code, out = self.install()
        self.assertEqual(code, 1)
        self.assertIn("externally-managed-environment", out)
        self.assertFalse(self.repo.exists())
        self.assertFalse((self.home / ".bashrc").exists())

    def test_uninstall_reverses_everything_but_the_memory_repo(self):
        self.install()
        (self.repo / "memory" / "local.jsonl").write_text('{"id": "L-0001"}\n', encoding="utf-8")
        self.host.calls.clear()
        code, out = self.install("--uninstall")
        self.assertEqual(code, 0, out)
        self.assertIn("keep      ~/repos/mnemosyne-local  (your memory repo is never removed)", out)
        self.assertTrue((self.repo / "memory" / "local.jsonl").is_file())
        self.assertFalse((self.home / ".mnemosyne").exists())
        self.assertIsNone(mi.rc_value(self.home / ".bashrc"))
        self.assertEqual(self.host.plugins, [])
        self.assertEqual(self.host.marketplaces, [])
        self.assertFalse(self.host.package_present)
        self.assertEqual(self.install("--uninstall")[0], 1)       # nothing left to uninstall

    def test_uninstall_keeps_what_it_did_not_install_or_no_longer_owns(self):
        self.fake(package_present=True)
        self.install()
        mi.rc_write(self.home / ".bashrc", str(self.home / "repointed"))
        code, out = self.install("--uninstall")
        self.assertEqual(code, 0, out)
        self.assertIn("keep      mnemosyne-reflexion", out)
        self.assertIn("keep      MNEMOSYNE_REPO  (changed since install", out)
        self.assertTrue(self.host.package_present)
        self.assertEqual(mi.rc_value(self.home / ".bashrc"), str(self.home / "repointed"))

    def test_uninstall_dry_run_removes_nothing(self):
        self.install()
        before = self.tree()
        code, out = self.install("--uninstall", "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn("dry run: nothing removed", out)
        self.assertEqual(self.tree(), before)

    def test_usage_errors(self):
        for argv in (["--uninstall", "--repo", "x"], ["--uninstall", "--target", "x"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit) as cm:
                self.install(*argv)
            self.assertEqual(cm.exception.code, 2)
        self.assertEqual(self.install("--target", str(self.home / "missing"))[0], 2)


class ShellRcFiles(InstallerCase):
    def test_each_shell_gets_its_own_file_and_syntax(self):
        cases = [("/bin/zsh", "linux", ".zshrc"), ("/bin/bash", "darwin", ".bash_profile"),
                 ("/usr/bin/fish", "linux", ".config/fish/config.fish"), ("/bin/sh", "linux", ".profile")]
        for shell, platform, rel in cases:
            with self.subTest(shell=shell, platform=platform), \
                    mock.patch.dict(os.environ, {"SHELL": shell}), mock.patch.object(mi, "PLATFORM", platform):
                self.assertEqual(mi.rc_file(), self.home / rel)
                mi.rc_write(mi.rc_file(), "/srv/my memory")
                self.assertEqual(mi.rc_value(mi.rc_file()), "/srv/my memory")
                line = mi.rc_file().read_text(encoding="utf-8").splitlines()[1]
                self.assertEqual(line, "set -gx MNEMOSYNE_REPO '/srv/my memory'" if shell.endswith("fish")
                                 else "export MNEMOSYNE_REPO='/srv/my memory'")


class WindowsInstall(InstallerCase):
    platform = "win32"

    def test_sets_the_user_environment_and_writes_no_rc_file(self):
        code, out = self.install()
        self.assertEqual(code, 0, out)
        self.assertIn("(in HKCU\\Environment)", out)
        self.assertEqual(self.host.registry[mi.ENV_NAME], str(self.repo.resolve()))
        self.assertFalse(any(p.endswith(("rc", "profile")) for p in self.tree()))
        self.assertEqual(self.manifest()["env"]["where"], "windows-user")
        self.assertIn("new terminals and apps", out)

    def test_an_existing_registry_value_is_respected(self):
        mine = self.home / "workspace" / "memory"
        (mine / "memory").mkdir(parents=True)
        self.host.registry[mi.ENV_NAME] = str(mine)
        code, out = self.install()
        self.assertEqual(code, 0, out)
        self.assertIn("keep      ~/workspace/memory", out)
        self.assertIn("same      MNEMOSYNE_REPO=~/workspace/memory", out)
        self.assertFalse(self.repo.exists())

    def test_uninstall_unsets_only_its_own_value(self):
        self.install()
        self.assertEqual(self.install("--uninstall")[0], 0)
        self.assertNotIn(mi.ENV_NAME, self.host.registry)


class CopilotHooksInARepo(InstallerCase):
    def setUp(self):
        super().setUp()
        self.target = Path(self._tmp.name) / "project"
        self.target.mkdir()
        self.hooks = self.target / ".github" / "hooks"

    def test_writes_a_copilot_hook_file_and_the_bridge(self):
        code, out = self.install("--target", str(self.target))
        self.assertEqual(code, 0, out)
        doc = json.loads((self.hooks / "mnemosyne.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["version"], 1)
        modes = {event: entry[0]["powershell"].split()[-1] for event, entry in doc["hooks"].items()}
        self.assertEqual(modes, {"sessionStart": "session-start", "userPromptSubmitted": "prompt",
                                 "postToolUse": "post-tool", "agentStop": "stop", "preCompact": "pre-compact"})
        for (entry,) in doc["hooks"].values():
            self.assertTrue(entry["bash"].startswith("python3 .github/hooks/mnemosyne_hook.py "))
            self.assertNotIn("--host", entry["bash"])      # one file serves CLI, VS Code and cloud agent
        self.assertEqual((self.hooks / "mnemosyne_hook.py").read_bytes(),
                         (mi.PLUGIN / "hooks" / "mnemosyne_hook.py").read_bytes())
        self.assertEqual(self.install("--target", str(self.target))[1].count("same      "), 5)

    def test_a_differing_hook_file_is_a_conflict(self):
        self.hooks.mkdir(parents=True)
        (self.hooks / "mnemosyne.json").write_text("{}", encoding="utf-8")
        code, out = self.install("--target", str(self.target))
        self.assertEqual(code, 1)
        self.assertIn("differs from the kit's", out)
        self.assertEqual((self.hooks / "mnemosyne.json").read_text(encoding="utf-8"), "{}")
        self.assertEqual(self.install("--target", str(self.target), "--force")[0], 0)

    def test_skipped_when_claude_settings_already_run_the_bridge(self):
        (self.target / ".claude").mkdir()
        (self.target / ".claude" / "settings.json").write_text(
            '{"hooks": {"SessionStart": [{"hooks": [{"command": "python mnemosyne_hook.py session-start"}]}]}}',
            encoding="utf-8")
        code, out = self.install("--target", str(self.target))
        self.assertEqual(code, 0, out)
        self.assertIn("fire twice", out)
        self.assertFalse(self.hooks.exists())

    def test_the_bridge_copy_runs_from_the_repo_root(self):
        self.install("--target", str(self.target))
        env = dict(os.environ, PYTHONPATH=str(REPO / "mnemosyne" / "src"), MNEMOSYNE_REPO=str(self.repo))
        proc = subprocess.run([sys.executable, ".github/hooks/mnemosyne_hook.py", "prompt"],
                              input=json.dumps({"prompt": "from now on rebase", "cwd": str(self.target)}),
                              capture_output=True, text=True, cwd=self.target, env=env)
        self.assertEqual((proc.returncode, proc.stdout), (0, ""), proc.stderr)
        self.assertTrue((self.repo / "memory" / ".capture" / "candidates.jsonl").is_file())


class CopilotHooksForTheUser(InstallerCase):
    def setUp(self):
        super().setUp()
        self.hooks = self.home / ".copilot" / "hooks"

    def hook_file(self, folder=None):
        return json.loads(((folder or self.hooks) / "mnemosyne.json").read_text(encoding="utf-8"))

    def test_nothing_is_written_without_asking(self):
        code, out = self.install()
        self.assertEqual(code, 0, out)
        self.assertFalse((self.home / ".copilot").exists())
        self.assertNotIn("copilot_hooks", self.manifest())

    def test_dry_run_lists_the_files_and_writes_nothing(self):
        code, out = self.install("--user", "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn("create    ~/.copilot/hooks/mnemosyne.json", out)
        self.assertIn("create    ~/.copilot/hooks/mnemosyne_hook.py", out)
        self.assertEqual(self.tree(), [])

    def test_same_events_as_the_repo_file_but_an_absolute_script(self):
        code, out = self.install("--user")
        self.assertEqual(code, 0, out)
        doc = self.hook_file()
        repo_doc = json.loads(mi.copilot_hooks())
        self.assertEqual(doc["version"], repo_doc["version"])
        self.assertEqual(list(doc["hooks"]), list(repo_doc["hooks"]))
        script = (self.hooks / "mnemosyne_hook.py").as_posix()
        for event, (entry,) in doc["hooks"].items():
            mode = repo_doc["hooks"][event][0]["bash"].split()[-1]
            self.assertIn(script, entry["bash"])
            self.assertIn(script, entry["powershell"])
            self.assertTrue(entry["bash"].endswith(f" {mode}"))
            self.assertTrue(entry["powershell"].endswith(f" {mode}"))
            self.assertEqual(entry.get("timeoutSec"), repo_doc["hooks"][event][0].get("timeoutSec"))
            self.assertNotIn(".github", entry["bash"])     # that path exists only in a repo
            self.assertNotIn("cwd", entry)
        self.assertEqual((self.hooks / "mnemosyne_hook.py").read_bytes(),
                         (mi.PLUGIN / "hooks" / "mnemosyne_hook.py").read_bytes())

    def test_the_commands_run_from_a_repo_with_no_bridge_of_its_own(self):
        """Through the shell the host uses, from a folder with a space, in an unrelated project."""
        folder = self.home / "my hooks's folder"
        code, out = self.install("--copilot-hooks-dir", str(folder), "--python", sys.executable)
        self.assertEqual(code, 0, out)
        project = self.home / "some project"
        project.mkdir()
        (entry,) = self.hook_file(folder)["hooks"]["userPromptSubmitted"]
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if os.name == "nt":
            cmd = [shell, "-NoProfile", "-Command", entry["powershell"]]
        else:
            cmd = ["/bin/sh", "-c", entry["bash"]]
        env = dict(os.environ, PYTHONPATH=str(REPO / "mnemosyne" / "src"), MNEMOSYNE_REPO=str(self.repo))
        proc = subprocess.run(cmd, input=json.dumps({"prompt": "from now on rebase", "cwd": str(project),
                                                     "sessionId": "s"}),
                              capture_output=True, text=True, cwd=project, env=env)
        self.assertEqual((proc.returncode, proc.stdout), (0, ""), proc.stderr)
        self.assertTrue((self.repo / "memory" / ".capture" / "candidates.jsonl").is_file())

    def test_the_powershell_form_runs_where_powershell_exists(self):
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if shell is None:
            self.skipTest("no PowerShell here")
        folder = self.home / "my hooks's folder"
        self.install("--copilot-hooks-dir", str(folder), "--python", sys.executable)
        (entry,) = self.hook_file(folder)["hooks"]["sessionStart"]
        env = dict(os.environ, PYTHONPATH=str(REPO / "mnemosyne" / "src"), MNEMOSYNE_REPO=str(self.repo))
        proc = subprocess.run([shell, "-NoProfile", "-Command", entry["powershell"]], input="{}",
                              capture_output=True, text=True, cwd=self.home, env=env)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue((self.repo / "memory" / ".capture" / "decisions.jsonl").is_file())

    def test_rerun_is_safe(self):
        self.install("--user")
        before = (self.hooks / "mnemosyne.json").read_bytes()
        code, out = self.install("--user")
        self.assertEqual(code, 0, out)
        self.assertIn("same      ~/.copilot/hooks/mnemosyne.json", out)
        self.assertIn("same      ~/.copilot/hooks/mnemosyne_hook.py", out)
        self.assertEqual((self.hooks / "mnemosyne.json").read_bytes(), before)

    def test_a_rerun_without_user_keeps_the_record(self):
        self.install("--user")
        self.assertEqual(self.install()[0], 0)
        self.install("--uninstall")
        self.assertFalse((self.home / ".copilot").exists())

    def test_a_new_kit_updates_an_unedited_file(self):
        self.install("--user")
        (self.hooks / "mnemosyne_hook.py").write_bytes(b"# an older bridge\n")
        doc = self.manifest()
        doc["copilot_hooks"]["files"][(self.hooks / "mnemosyne_hook.py").as_posix()] = mi.sha256(b"# an older bridge\n")
        mi.write_manifest(doc)
        code, out = self.install("--user")
        self.assertEqual(code, 0, out)
        self.assertIn("update    ~/.copilot/hooks/mnemosyne_hook.py", out)

    def test_an_edited_hook_file_is_a_conflict(self):
        self.install("--user")
        (self.hooks / "mnemosyne.json").write_text("{}", encoding="utf-8")
        code, out = self.install("--user")
        self.assertEqual(code, 1)
        self.assertIn("edited since install", out)
        self.assertEqual((self.hooks / "mnemosyne.json").read_text(encoding="utf-8"), "{}")
        self.assertEqual(self.install("--user", "--force")[0], 0)
        self.assertIn("hooks", self.hook_file())

    def test_a_hook_file_it_did_not_write_is_never_overwritten(self):
        self.hooks.mkdir(parents=True)
        (self.hooks / "mnemosyne.json").write_text("mine", encoding="utf-8")
        code, out = self.install("--user", "--force")
        self.assertEqual(code, 1)
        self.assertIn("not written by this installer", out)
        self.assertEqual((self.hooks / "mnemosyne.json").read_text(encoding="utf-8"), "mine")
        self.assertFalse((self.hooks / "mnemosyne_hook.py").exists())
        self.assertFalse((self.home / ".mnemosyne").exists())

    def test_uninstall_removes_only_what_it_wrote(self):
        self.hooks.mkdir(parents=True)
        (self.hooks / "other-tool.json").write_text("{}", encoding="utf-8")
        self.install("--user")
        code, out = self.install("--uninstall")
        self.assertEqual(code, 0, out)
        self.assertIn("remove    ~/.copilot/hooks/mnemosyne.json", out)
        self.assertEqual([p.name for p in self.hooks.iterdir()], ["other-tool.json"])

    def test_uninstall_leaves_an_identical_file_it_did_not_write(self):
        self.hooks.mkdir(parents=True)
        for dest, data in mi.user_hook_payloads(self.hooks, None):
            dest.write_bytes(data)
        code, out = self.install("--user")
        self.assertEqual(code, 0, out)
        self.assertIn("keep      ~/.copilot/hooks/mnemosyne.json", out)
        self.assertEqual(self.install("--uninstall")[0], 0)
        self.assertTrue((self.hooks / "mnemosyne.json").is_file())

    def test_uninstall_removes_the_folders_it_made_and_no_others(self):
        (self.home / ".copilot").mkdir()
        self.install("--user")
        self.install("--uninstall")
        self.assertFalse(self.hooks.exists())
        self.assertTrue((self.home / ".copilot").is_dir())

    def test_uninstall_keeps_an_edited_file(self):
        self.install("--user")
        (self.hooks / "mnemosyne.json").write_text("{}", encoding="utf-8")
        code, out = self.install("--uninstall", "--dry-run")
        self.assertIn("keep      ~/.copilot/hooks/mnemosyne.json", out)
        self.assertTrue((self.hooks / "mnemosyne_hook.py").is_file())
        self.assertEqual(self.install("--uninstall")[0], 0)
        self.assertEqual([p.name for p in self.hooks.iterdir()], ["mnemosyne.json"])

    def test_a_custom_folder_replaces_the_default_and_expands_the_home(self):
        code, out = self.install("--copilot-hooks-dir", "~/deep/er/hooks")
        self.assertEqual(code, 0, out)
        folder = self.home / "deep" / "er" / "hooks"
        self.assertTrue((folder / "mnemosyne.json").is_file())
        self.assertFalse((self.home / ".copilot").exists())
        self.assertIn(folder.resolve().as_posix(), self.hook_file(folder)["hooks"]["agentStop"][0]["bash"])
        self.install("--uninstall")
        self.assertFalse((self.home / "deep").exists())

    def test_uninstall_covers_every_folder_ever_used(self):
        self.install("--user")
        self.install("--copilot-hooks-dir", str(self.home / "other"))
        self.install("--uninstall")
        self.assertFalse(self.hooks.exists())
        self.assertFalse((self.home / "other").exists())

    def test_python_picks_the_interpreter_in_both_shells(self):
        self.install("--user", "--python", "/opt/my py/python")
        (entry,) = self.hook_file()["hooks"]["sessionStart"]
        self.assertTrue(entry["bash"].startswith("'/opt/my py/python' "))
        self.assertTrue(entry["powershell"].startswith("& '/opt/my py/python' "))

    def test_usage_errors(self):
        target = self.home / "project"
        target.mkdir()
        (self.home / "a-file").write_text("x", encoding="utf-8")
        self.assertEqual(self.install("--copilot-hooks-dir", str(self.home / "a-file"))[0], 2)
        for argv in (["--uninstall", "--copilot-hooks-dir", "x"],
                     ["--target", str(target), "--copilot-hooks-dir", str(target / ".github" / "hooks")]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit) as cm:
                self.install(*argv)
            self.assertEqual(cm.exception.code, 2)

    def test_uninstall_accepts_user_as_zethus_passes_it(self):
        self.install("--user")
        self.assertEqual(self.install("--user", "--uninstall")[0], 0)
        self.assertFalse((self.home / ".copilot").exists())

    def test_user_and_repo_files_can_coexist(self):
        target = self.home / "project"
        target.mkdir()
        code, out = self.install("--user", "--target", str(target))
        self.assertEqual(code, 0, out)
        self.assertTrue((target / ".github" / "hooks" / "mnemosyne.json").is_file())
        self.assertTrue((self.hooks / "mnemosyne.json").is_file())


class CopilotPluginBesideTheHooks(InstallerCase):
    def setUp(self):
        super().setUp()
        self.hooks = self.home / ".copilot" / "hooks"

    def enable(self, folder=None):
        folder = folder or self.home / ".copilot"
        folder.mkdir(parents=True, exist_ok=True)
        doc = {"enabledPlugins": {"mnemosyne@mesmer-grimoire": True}}
        (folder / "settings.json").write_text(json.dumps(doc), encoding="utf-8")

    def test_finds_the_plugin_in_settings_copilot_home_or_a_copy(self):
        self.assertIsNone(mi.copilot_plugin())
        self.enable(self.home / "elsewhere")
        self.assertIsNone(mi.copilot_plugin())
        os.environ["COPILOT_HOME"] = str(self.home / "elsewhere")
        self.assertEqual(mi.copilot_plugin(), "mnemosyne@mesmer-grimoire")
        del os.environ["COPILOT_HOME"]
        copied = self.home / ".copilot" / "installed-plugins" / "other" / "mnemosyne"
        copied.mkdir(parents=True)
        (copied / "plugin.json").write_text("{}", encoding="utf-8")
        self.assertEqual(mi.copilot_plugin(), "mnemosyne@other")

    def test_a_disabled_plugin_or_bad_settings_is_not_the_plugin(self):
        self.enable()
        settings = self.home / ".copilot" / "settings.json"
        for text in ('{"enabledPlugins": {"mnemosyne@x": false}}', "{not json", "[]"):
            settings.write_text(text, encoding="utf-8")
            self.assertIsNone(mi.copilot_plugin(), text)

    def test_user_hooks_are_skipped_beside_the_plugin_and_the_rest_installs(self):
        self.enable()
        code, out = self.install("--user")
        self.assertEqual(code, 0, out)
        self.assertIn("mnemosyne@mesmer-grimoire carries them", out)
        self.assertFalse(self.hooks.exists())
        self.assertTrue((self.home / "repos" / "mnemosyne-local" / "memory").is_dir())

    def test_force_writes_user_hooks_beside_the_plugin(self):
        self.enable()
        self.assertEqual(self.install("--user", "--force")[0], 0)
        self.assertTrue((self.hooks / "mnemosyne.json").is_file())

    def test_a_target_repo_still_gets_its_files_with_one_note(self):
        self.enable()
        target = self.home / "repo"
        target.mkdir()
        code, out = self.install("--target", str(target))
        self.assertEqual(code, 0, out)
        self.assertEqual(out.count("runs these hooks too"), 1)
        self.assertTrue((target / ".github" / "hooks" / "mnemosyne.json").is_file())

    def test_a_rerun_beside_the_plugin_offers_the_migration(self):
        self.assertEqual(self.install("--user")[0], 0)
        self.enable()
        self.assertIn("--migrate-to-plugin", self.install("--user")[1])

    def test_migration_removes_only_the_hook_files(self):
        self.assertEqual(self.install("--user")[0], 0)
        (self.hooks / "mine.json").write_text("{}", encoding="utf-8")
        self.enable()
        code, out = self.install("--migrate-to-plugin")
        self.assertEqual(code, 0, out)
        self.assertIn("takes over", out)
        self.assertFalse((self.hooks / "mnemosyne.json").exists())
        self.assertTrue((self.hooks / "mine.json").is_file())
        manifest = mi.read_manifest()
        self.assertNotIn("copilot_hooks", manifest)
        self.assertIn("package", manifest, "the package and repo stay installed")

    def test_migration_says_how_to_add_a_missing_plugin_and_is_safe_twice(self):
        self.assertEqual(self.install("--user")[0], 0)
        self.assertIn("copilot plugin marketplace add", self.install("--migrate-to-plugin")[1])
        code, out = self.install("--migrate-to-plugin")
        self.assertEqual(code, 0, out)
        self.assertIn("no user-level Copilot hook files", out)

    def test_migration_keeps_an_edited_file_until_forced(self):
        self.assertEqual(self.install("--user")[0], 0)
        edited = self.hooks / "mnemosyne.json"
        edited.write_text("{}", encoding="utf-8")
        code, out = self.install("--migrate-to-plugin")
        self.assertEqual(code, 1, out)
        self.assertTrue(edited.is_file())
        self.assertEqual(self.install("--migrate-to-plugin", "--force")[0], 0)
        self.assertFalse(edited.exists())

    def test_migration_dry_run_touches_nothing(self):
        self.assertEqual(self.install("--user")[0], 0)
        code, out = self.install("--migrate-to-plugin", "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertTrue((self.hooks / "mnemosyne.json").is_file())
        self.assertIn("copilot_hooks", mi.read_manifest())

    def test_uninstall_still_finds_what_migration_left(self):
        self.assertEqual(self.install("--user")[0], 0)
        (self.hooks / "mnemosyne.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.install("--migrate-to-plugin")[0], 1)
        self.assertEqual(self.install("--uninstall", "--force")[0], 0)
        self.assertFalse((self.hooks / "mnemosyne.json").exists())

    def test_migration_refuses_install_flags(self):
        for argv in (("--uninstall",), ("--repo", "x"), ("--target", "."), ("--copilot-hooks-dir", "x")):
            with self.assertRaises(SystemExit) as caught, redirect_stderr(io.StringIO()):
                self.install("--migrate-to-plugin", *argv)
            self.assertEqual(caught.exception.code, 2, argv)

    def test_the_copilot_half_stays_out_of_the_claude_copy(self):
        self.assertEqual(self.install()[0], 0)
        copy = self.home / ".mnemosyne" / "claude-marketplace" / "plugins" / "mnemosyne"
        self.assertTrue((copy / ".claude-plugin" / "plugin.json").is_file())
        self.assertFalse((copy / "plugin.json").exists())
        self.assertFalse((copy / "com.github.copilot").exists())


if __name__ == "__main__":
    unittest.main()

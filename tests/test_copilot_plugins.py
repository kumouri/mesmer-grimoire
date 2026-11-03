"""CI coverage for the Copilot plugin packaging: the two marketplaces, the plugin manifests, Zethus's
``sessionStart`` hook, and how ``zethus/install.py`` behaves beside an installed plugin.

Whether a real Copilot CLI loads all this is a live check no CI here can run (it needs a Copilot
login). The result is in zethus/README.md; these tests hold the shapes that check depended on.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
ZETHUS = REPO / "zethus"
PLUGIN = REPO / "mnemosyne" / "plugin"
HOOK = ZETHUS / "com.github.copilot" / "hooks" / "session_start.py"
SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MANIFEST_FIELDS = {"$schema", "name", "version", "description", "author", "homepage", "repository",
                   "license", "keywords", "extensions"}
ALL_SKILLS = [*ZETHUS.glob("skills/*/SKILL.md"), *PLUGIN.glob("skills/*/SKILL.md"),
              *REPO.glob("amphion/plugin/skills/*/SKILL.md")]


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


zi = load(ZETHUS / "install.py", "zethus_install_plugins")
sync = load(REPO / "scripts" / "sync_zethus_plugin_root.py", "sync_zethus_plugin_root")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def entries(path: str) -> dict:
    return {e["name"]: e for e in read_json(REPO / path)["plugins"]}


class Marketplaces(unittest.TestCase):
    def test_each_client_sees_only_its_own_catalogue(self):
        self.assertEqual(set(entries(".github/plugin/marketplace.json")), {"zethus", "mnemosyne"})
        self.assertEqual(set(entries(".claude-plugin/marketplace.json")), {"amphion", "mnemosyne"})

    def test_a_marketplace_has_the_required_top_level_fields(self):
        for path in (".github/plugin/marketplace.json", ".claude-plugin/marketplace.json"):
            doc = read_json(REPO / path)
            self.assertRegex(doc["name"], r"^[a-z0-9]+(-[a-z0-9]+)*$")
            self.assertTrue(doc["owner"]["name"], path)

    def test_copilot_entries_match_a_1_0_manifest(self):
        for name, entry in entries(".github/plugin/marketplace.json").items():
            manifest = read_json(REPO / entry["source"] / "plugin.json")
            self.assertEqual(manifest["$schema"], SCHEMA, name)
            self.assertEqual(manifest["name"], name)
            self.assertEqual(manifest["version"], entry["version"], name)
            self.assertLessEqual(set(manifest), MANIFEST_FIELDS, "the 1.0 schema is closed")
            self.assertRegex(name, r"^[a-z0-9][a-z0-9.-]{0,62}[a-z0-9]$")

    def test_claude_entries_match_their_manifest(self):
        for name, entry in entries(".claude-plugin/marketplace.json").items():
            manifest = read_json(REPO / entry["source"] / ".claude-plugin" / "plugin.json")
            self.assertEqual(manifest["name"], name)
            self.assertEqual(manifest["version"], entry["version"], name)

    def test_mnemosyne_has_one_version_everywhere(self):
        with open(REPO / "mnemosyne" / "pyproject.toml", "rb") as fh:
            version = tomllib.load(fh)["project"]["version"]
        self.assertEqual(read_json(PLUGIN / "plugin.json")["version"], version)
        self.assertEqual(read_json(PLUGIN / ".claude-plugin" / "plugin.json")["version"], version)


class PluginLayout(unittest.TestCase):
    def test_skill_frontmatter_is_valid_yaml_on_every_client(self):
        # The Copilot CLI drops a skill whose frontmatter doesn't parse, and says so only in its log.
        for path in ALL_SKILLS:
            head = path.read_text(encoding="utf-8").split("---")[1]
            for line in head.splitlines():
                m = re.match(r"[\w-]+: (.*)", line)
                if m and not m[1].startswith(('"', "'", ">", "|")):
                    self.assertNotIn(": ", m[1], f"{path}: an unquoted colon breaks YAML")

    def test_skills_sit_where_the_1_0_layout_finds_them(self):
        for root in (ZETHUS, PLUGIN):
            for path in root.glob("skills/*/SKILL.md"):
                self.assertRegex(path.read_text(encoding="utf-8"), rf"(?m)^name: {path.parent.name}$")

    def test_zethus_agent_and_hook_are_where_each_host_reads_them(self):
        """The CLI reads a 1.0-schema plugin's agents and hooks only under com.github.copilot/.
        IntelliJ's language server reads them only at the root: it listed the skills and no agent
        or hook until the root mirror existed. See scripts/sync_zethus_plugin_root.py."""
        for root in (ZETHUS / "com.github.copilot", ZETHUS):
            self.assertEqual([p.name for p in root.glob("agents/*.agent.md")], ["zethus.agent.md"], root)
            self.assertEqual(set(read_json(root / "hooks" / "hooks.json")["hooks"]), {"sessionStart", "userPromptSubmitted", "agentStop"}, root)
        self.assertFalse((ZETHUS / "hooks.json").exists(), "the language server reads it before hooks/")
        self.assertEqual([p.name for p in (ZETHUS / "hooks").iterdir()], ["hooks.json"], "one script, in one place")

    def test_zethus_root_mirror_is_in_step(self):
        self.assertEqual(sync.stale(), [], "run: python scripts/sync_zethus_plugin_root.py")
        self.assertEqual(sync.main(["--check"]), 0)

    def test_zethus_root_mirror_links_resolve(self):
        mirror = ZETHUS / "agents" / "zethus.agent.md"
        links = re.findall(r"\]\((\.\./[^)#]+)", mirror.read_text(encoding="utf-8"))
        self.assertGreater(len(links), 10)
        for link in links:
            self.assertTrue((mirror.parent / link).resolve().is_file(), link)

    def test_zethus_mirror_rewrites_only_the_depth(self):
        canon = "---\nname: x\n---\n\n> note: else two folders above this file's folder.\n\n[a](../../skills/a/SKILL.md)\n"
        out = sync.mirror_agent(canon, "x.agent.md")
        self.assertTrue(out.startswith("---\nname: x\n---\n\n<!-- Generated from com.github.copilot/agents/x.agent.md"))
        self.assertIn("else the folder above this file's folder.", out)
        self.assertIn("[a](../skills/a/SKILL.md)", out)
        self.assertNotIn("../../", out)
        with self.assertRaises(ValueError):
            sync.mirror_agent("no frontmatter", "y.agent.md")

    def test_zethus_text_is_root_agnostic(self):
        shipped = [ZETHUS / "copilot-instructions.md", *ZETHUS.glob("com.github.copilot/**/*.md"),
                   *ZETHUS.glob("agents/*.md"), *ZETHUS.glob("skills/**/*.md")]
        self.assertGreater(len(shipped), 20)
        for path in shipped:
            self.assertNotIn(".github/zethus/", path.read_text(encoding="utf-8"), path)

    def test_a_skill_using_the_kit_root_defines_it(self):
        for path in [*ZETHUS.glob("skills/*/SKILL.md"), *ZETHUS.glob("com.github.copilot/agents/*.md"),
                     *ZETHUS.glob("agents/*.md")]:
            text = path.read_text(encoding="utf-8")
            if "<kit root>" in text:
                self.assertRegex(text, zi.KIT_ROOT_NOTE, f"{path}: works alone only with the note")

    def test_zethus_hook_runs_the_script_it_names(self):
        hooks = read_json(ZETHUS / "com.github.copilot" / "hooks" / "hooks.json")["hooks"]
        (entry,) = hooks["sessionStart"]
        for shell in ("bash", "powershell"):
            self.assertIn("${PLUGIN_ROOT}/com.github.copilot/hooks/session_start.py", entry[shell])

    def test_mnemosyne_plugin_hooks_mirror_the_claude_registration(self):
        """Two hand-kept registrations of one bridge: every Claude event has its Copilot twin, in
        the same mode, with the same timeout. PostToolUseFailure has none (postToolUse covers it)."""
        mi = load(REPO / "mnemosyne" / "install.py", "mnemosyne_install_plugins")
        claude = read_json(PLUGIN / "hooks" / "hooks.json")["hooks"]
        copilot = read_json(PLUGIN / "com.github.copilot" / "hooks" / "hooks.json")
        self.assertEqual(copilot["version"], 1)
        self.assertEqual(set(copilot["hooks"]), set(mi.COPILOT_EVENTS.values()))
        self.assertEqual(set(claude) - set(mi.COPILOT_EVENTS), {"PostToolUseFailure"})
        for event, name in mi.COPILOT_EVENTS.items():
            (want,) = claude[event][0]["hooks"]
            (have,) = copilot["hooks"][name]
            script = f'"${{PLUGIN_ROOT}}/hooks/{mi.BRIDGE}" {want["command"].split()[-1]}'
            self.assertEqual(have["bash"], f"python3 {script}")
            self.assertEqual(have["powershell"], f"python {script}")
            self.assertEqual(have.get("timeoutSec"), want.get("timeout"))


class SessionStartHook(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.home = self.tmp / "home"
        self.home.mkdir()

    def fire(self, stdin: str) -> str:
        env = {**os.environ, "HOME": str(self.home), "USERPROFILE": str(self.home)}
        r = subprocess.run([sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True,
                           env=env, cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def project(self, *parts) -> Path:
        path = self.tmp.joinpath("project", *parts)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def context(self, cwd: Path) -> str:
        doc = json.loads(self.fire(json.dumps({"cwd": str(cwd)})))
        self.assertEqual(doc["additionalContext"], doc["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(doc["hookSpecificOutput"]["hookEventName"], "SessionStart")
        return doc["additionalContext"]

    def test_injects_the_agreement_and_says_where_the_kit_is(self):
        text = self.context(self.project())
        root = ZETHUS.as_posix()
        self.assertIn("Never work on a stale base", text)
        self.assertIn(f"python {root}/scripts/base-freshness.py", text)
        self.assertIn(f"Zethus kit root: `{root}`", text)
        self.assertIn(f"Scripts: `{root}/scripts/`", text)
        self.assertIn(f"Templates: `{root}/templates/`", text)
        self.assertNotIn("<kit root>/", text)

    def test_a_repo_install_silences_it_from_any_subfolder(self):
        scripts = self.project(".github", "zethus", "scripts")
        (scripts / "run-local-gates.py").write_text("", encoding="utf-8")
        (self.project() / ".git").mkdir()
        self.assertEqual(self.fire(json.dumps({"cwd": str(self.project())})), "")
        self.assertEqual(self.fire(json.dumps({"cwd": str(self.project("a", "b"))})), "")

    def test_a_kit_above_the_git_root_is_not_this_repos(self):
        scripts = self.project(".github", "zethus", "scripts")
        (scripts / "run-local-gates.py").write_text("", encoding="utf-8")
        (self.project("inner") / ".git").mkdir()
        self.assertIn("Zethus kit root", self.context(self.project("inner")))

    def test_a_user_mode_copy_gets_the_migration_line_and_no_second_agreement(self):
        copy = self.home / ".copilot" / "instructions"
        copy.mkdir(parents=True)
        (copy / "zethus.instructions.md").write_text("rules", encoding="utf-8")
        text = self.context(self.project())
        self.assertIn(f"python {ZETHUS.as_posix()}/install.py --user --migrate-to-plugin", text)
        self.assertNotIn("Never work on a stale base", text)

    def test_bad_input_fails_open(self):
        self.assertEqual(self.fire("not json"), "")
        self.assertIn("Zethus kit root", json.loads(self.fire("[]"))["additionalContext"])


class InstallerBesidePlugin(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name).resolve()
        self.copilot = self.home / ".copilot"
        for patcher in (mock.patch.object(Path, "home", return_value=self.home),
                        mock.patch.dict(os.environ),
                        mock.patch.object(zi, "PLATFORM", "linux")):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ.pop("COPILOT_HOME", None)

    def run_install(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = zi.main(list(argv))
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue() + err.getvalue()

    def enable(self, home: Path, doc: dict | None = None):
        home.mkdir(parents=True, exist_ok=True)
        doc = {"enabledPlugins": {"zethus@mesmer-grimoire": True}} if doc is None else doc
        (home / "settings.json").write_text(json.dumps(doc), encoding="utf-8")

    def test_finds_a_plugin_in_settings(self):
        self.assertIsNone(zi.find_plugin())
        self.enable(self.copilot)
        self.assertEqual(zi.find_plugin(), "zethus@mesmer-grimoire")

    def test_finds_a_plugin_under_copilot_home(self):
        self.enable(self.home / "elsewhere")
        self.assertIsNone(zi.find_plugin())
        os.environ["COPILOT_HOME"] = str(self.home / "elsewhere")
        self.assertEqual(zi.find_plugin(), "zethus@mesmer-grimoire")

    def test_finds_a_copied_plugin(self):
        copied = self.copilot / "installed-plugins" / "somewhere" / "zethus"
        copied.mkdir(parents=True)
        (copied / "plugin.json").write_text("{}", encoding="utf-8")
        self.assertEqual(zi.find_plugin(), "zethus@somewhere")

    def test_a_disabled_or_unrelated_plugin_or_bad_settings_is_not_a_plugin(self):
        for doc in ({"enabledPlugins": {"zethus@x": False}}, {"enabledPlugins": {"zethusian@x": True}},
                    {"enabledPlugins": ["zethus@x"]}, []):
            self.enable(self.copilot, doc)
            self.assertIsNone(zi.find_plugin(), doc)
        (self.copilot / "settings.json").write_text("{not json", encoding="utf-8")
        self.assertIsNone(zi.find_plugin())

    def test_user_mode_skips_rather_than_shadow(self):
        self.enable(self.copilot)
        code, out = self.run_install("--user")
        self.assertEqual(code, 0, out)
        self.assertIn("zethus@mesmer-grimoire", out)
        self.assertFalse((self.copilot / "skills").exists())

    def test_force_installs_beside_the_plugin_and_then_offers_the_migration(self):
        self.enable(self.copilot)
        self.assertEqual(self.run_install("--user", "--force")[0], 0)
        self.assertTrue((self.copilot / "skills" / "test-plan" / "SKILL.md").is_file())
        self.assertIn("--migrate-to-plugin", self.run_install("--user")[1])

    def test_migration_removes_the_copy_and_keeps_your_files(self):
        self.assertEqual(self.run_install("--user")[0], 0)
        mine = self.copilot / "zethus" / "config.json"
        mine.write_text("{}", encoding="utf-8")
        self.enable(self.copilot)
        code, out = self.run_install("--user", "--migrate-to-plugin")
        self.assertEqual(code, 0, out)
        self.assertIn("zethus@mesmer-grimoire takes over", out)
        self.assertEqual(list((self.copilot / "skills").iterdir()), [])
        self.assertEqual(list((self.copilot / "instructions").iterdir()), [])
        self.assertTrue(mine.is_file())

    def test_migration_says_how_to_add_a_missing_plugin_and_is_safe_twice(self):
        self.assertEqual(self.run_install("--user")[0], 0)
        self.assertIn("copilot plugin marketplace add kumouri/mesmer-grimoire#main",
                      self.run_install("--user", "--migrate-to-plugin")[1])
        code, out = self.run_install("--user", "--migrate-to-plugin")
        self.assertEqual(code, 0, out)
        self.assertIn("no user-mode copy to remove", out)

    def test_migration_reports_an_edited_skill_that_still_shadows(self):
        self.assertEqual(self.run_install("--user")[0], 0)
        skill = self.copilot / "skills" / "test-plan" / "SKILL.md"
        skill.write_text("mine", encoding="utf-8")
        code, out = self.run_install("--user", "--migrate-to-plugin")
        self.assertEqual(code, 1, out)
        self.assertIn("still shadow", out)
        self.assertIn("test-plan", out)
        self.assertEqual(skill.read_text(encoding="utf-8"), "mine")

    def test_migration_force_removes_edited_files(self):
        self.assertEqual(self.run_install("--user")[0], 0)
        skill = self.copilot / "skills" / "test-plan" / "SKILL.md"
        skill.write_text("mine", encoding="utf-8")
        self.assertEqual(self.run_install("--user", "--migrate-to-plugin", "--force")[0], 0)
        self.assertFalse(skill.exists())

    def test_migration_dry_run_touches_nothing(self):
        self.assertEqual(self.run_install("--user")[0], 0)
        code, out = self.run_install("--user", "--migrate-to-plugin", "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertTrue((self.copilot / "skills" / "test-plan" / "SKILL.md").is_file())
        self.assertTrue(zi.manifest_path().is_file())

    def test_migration_reaches_mnemosyne_too(self):
        args = zi.argparse.Namespace(target=None, mnemosyne_repo=None, mnemosyne_copilot_hooks_dir=None,
                                     dry_run=False, uninstall=False, migrate_to_plugin=True)
        self.assertEqual(zi.mnemosyne_argv(args), ["--user", "--migrate-to-plugin"])

    def test_a_failed_migration_still_runs_mnemosyne(self):
        self.assertEqual(self.run_install("--user")[0], 0)
        (self.copilot / "skills" / "test-plan" / "SKILL.md").write_text("mine", encoding="utf-8")
        with mock.patch.object(zi, "run_mnemosyne", return_value=0) as called:
            code, out = self.run_install("--user", "--migrate-to-plugin", "--with-mnemosyne")
        self.assertEqual(code, 1, out)
        called.assert_called_once_with(["--user", "--migrate-to-plugin"])

    def test_migration_needs_user_mode_and_is_not_an_uninstall(self):
        self.assertEqual(self.run_install("--target", ".", "--migrate-to-plugin")[0], 2)
        self.assertEqual(self.run_install("--user", "--migrate-to-plugin", "--uninstall")[0], 2)
        self.assertEqual(self.run_install("--user", "--migrate-to-plugin", "--with-mnemosyne",
                                          "--mnemosyne-repo", "x")[0], 2)

    def test_a_repo_install_beside_the_plugin_is_written_and_noted(self):
        self.enable(self.copilot)
        target = self.home / "repo"
        target.mkdir()
        code, out = self.run_install("--target", str(target))
        self.assertEqual(code, 0, out)
        self.assertIn("committed copy wins", out)
        self.assertTrue((target / ".github" / "agents" / "zethus.agent.md").is_file())

    def test_repo_install_makes_the_kit_root_concrete(self):
        target = self.home / "repo"
        target.mkdir()
        self.assertEqual(self.run_install("--target", str(target))[0], 0)
        github = target / ".github"
        for path in github.rglob("*.md"):
            self.assertNotIn("<kit root>", path.read_text(encoding="utf-8"), path)
        agent = (github / "agents" / "zethus.agent.md").read_text(encoding="utf-8")
        self.assertIn("python .github/zethus/scripts/base-freshness.py", agent)
        self.assertIn("`.github/copilot-instructions.md`", agent)
        self.assertIn("](../skills/test-plan/SKILL.md)", agent)
        self.assertTrue((github / "instructions" / "docs.instructions.md").is_file())


if __name__ == "__main__":
    unittest.main()

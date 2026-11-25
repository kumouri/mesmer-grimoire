"""The grimoire installer (``install.py``), end to end, on throwaway homes and repos.

Nothing here touches the machine it runs on. ``tests.test_mnemosyne_install`` supplies the fakes: a
temp ``HOME``, a fake pip, a fake ``claude`` and a dict for the Windows registry, while git runs for
real. The properties this file holds:

* **each hook registers once** however many kits ask for it, in whatever order, and however often the
  installer runs;
* **an existing install keeps working**: an *older* Zethus installer re-run over a new install, and
  an upgrade of an existing install, lose, duplicate and rename no skill, hook or config key;
* the installer **calls** the kits' own installers and never copies them.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from tests.test_mnemosyne_install import FakeHost, InstallerCase, mi
from tests.test_shared_core import REPO, grimoire

FROZEN = REPO / "tests" / "fixtures" / "zethus_install_pre_phase4.py"
CLAUDE_EVENTS = {"SessionStart", "UserPromptSubmit", "PostToolUse", "PostToolUseFailure", "Stop", "PreCompact"}
COPILOT_EVENTS = {"sessionStart", "userPromptSubmitted", "postToolUse", "agentStop", "preCompact"}
ZETHUS_SKILLS = {p.name for p in (REPO / "zethus" / "skills").iterdir() if p.is_dir()}
CORE_SKILLS = {"flag-or-fix", "pr-description", "resume-interrupted-phase"}
AMPHION_OWN = {"initialize-ci", "load-context", "log-friction"}


def registrations(*roots: Path) -> Counter:
    """How many times the bridge is registered for each event, over every JSON hook file below."""
    count: Counter = Counter()
    for root in roots:
        for path in sorted(root.rglob("*.json")):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            hooks = doc.get("hooks") if isinstance(doc, dict) else None
            if not isinstance(hooks, dict):
                continue
            for event, entries in hooks.items():
                for entry in entries if isinstance(entries, list) else []:
                    for hook in entry.get("hooks") or [entry]:
                        if "mnemosyne_hook.py" in json.dumps(hook):
                            count[event] += 1
    return count


def snap(*roots: Path) -> dict[str, str]:
    """Every file below the roots, by path, with its hash."""
    out = {}
    for root in roots:
        for p in sorted(root.rglob("*")):
            if p.is_file():
                out[f"{root.name}/{p.relative_to(root).as_posix()}"] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def load_frozen(kit: Path):
    spec = importlib.util.spec_from_file_location("zethus_install_frozen", kit / "install.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["zethus_install_frozen"] = module      # @dataclass looks its own module up by name
    spec.loader.exec_module(module)
    return module


class GrimoireCase(InstallerCase):
    """A temp home and repo, the kit installers' fakes, and one ``run`` for the installer under test."""

    def setUp(self):
        super().setUp()
        self.target = Path(self._tmp.name) / "repo"
        self.target.mkdir()
        self.zethus = grimoire.delegate("zethus")
        for name, value in (("PLATFORM", "linux"),):
            patcher = mock.patch.object(self.zethus, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        import os
        os.environ.pop("ZETHUS_CONFIG", None)
        os.environ["ZETHUS_IDENTITY_FORGE"] = "off"

    def run_install(self, *argv: str) -> tuple[int, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = grimoire.main(list(argv))
            except SystemExit as exc:
                code = int(exc.code or 0)
        return code, out.getvalue() + err.getvalue()

    def skills(self, folder: Path) -> list[str]:
        return sorted(p.name for p in folder.iterdir() if p.is_dir()) if folder.is_dir() else []

    def everything(self) -> dict[str, str]:
        return snap(self.home, self.target)


class EachHookRegistersOnce(GrimoireCase):
    def assert_once(self):
        found = registrations(self.home, self.target)
        self.assertEqual(set(found), CLAUDE_EVENTS | COPILOT_EVENTS, found)
        self.assertEqual(set(found.values()), {1}, found)
        self.assertEqual(self.host.plugins.count(mi.PLUGIN_ID), 1)

    def test_both_kits_into_a_repo_register_each_hook_once(self):
        code, out = self.run_install("--platform", "all", "--target", str(self.target),
                                     "--bundle", "zethus,amphion")
        self.assertEqual(code, 0, out)
        self.assert_once()
        self.assertTrue((self.target / ".github/hooks/mnemosyne.json").is_file())
        self.assertFalse((self.target / ".claude/settings.json").exists())

    def test_both_kits_for_the_user_register_each_hook_once(self):
        code, out = self.run_install("--platform", "all", "--user", "--bundle", "zethus,amphion")
        self.assertEqual(code, 0, out)
        self.assert_once()
        self.assertTrue((self.home / ".copilot/hooks/mnemosyne.json").is_file())

    def one_at_a_time(self, *order: str):
        for bundle in order:
            code, out = self.run_install("--platform", "all", "--target", str(self.target), "--bundle", bundle)
            self.assertEqual(code, 0, out)
        self.assert_once()
        self.assertEqual(self.skills(self.target / ".github/skills"),
                         sorted(ZETHUS_SKILLS | AMPHION_OWN | CORE_SKILLS))
        self.assertEqual(self.skills(self.target / ".claude/skills"), sorted(AMPHION_OWN | CORE_SKILLS))

    def test_zethus_then_amphion_registers_each_hook_once(self):
        self.one_at_a_time("zethus", "amphion")

    def test_amphion_then_zethus_registers_each_hook_once(self):
        self.one_at_a_time("amphion", "zethus")

    def test_running_it_twice_changes_nothing(self):
        args = ("--platform", "all", "--user", "--bundle", "zethus,amphion")
        self.assertEqual(self.run_install(*args)[0], 0)
        first = self.everything()
        code, out = self.run_install(*args)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.everything(), first)
        self.assert_once()
        self.assertNotIn("create    ", out.replace("create    ~/repos", ""), out)

    def test_zethus_with_mnemosyne_first_then_the_installer_is_still_once(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = self.zethus.main(["--user", "--with-mnemosyne"])
        self.assertEqual(code, 0, out.getvalue())
        self.assertEqual(self.run_install("--platform", "all", "--user", "--bundle", "zethus,amphion")[0], 0)
        self.assert_once()

    def test_zethus_with_core_registers_once_even_with_mnemosyne_asked_too(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = self.zethus.main(["--user", "--with-core", "--with-mnemosyne"])
        self.assertEqual(code, 0, out.getvalue())
        found = registrations(self.home)
        self.assertEqual(set(found.values()), {1}, found)
        self.assertEqual(self.host.plugins.count(mi.PLUGIN_ID), 1)
        self.assertEqual(self.skills(self.home / ".copilot/skills"), sorted(ZETHUS_SKILLS | CORE_SKILLS))

    def test_amphion_alone_registers_the_claude_hooks_once_and_no_copilot_file(self):
        code, out = self.run_install("--platform", "claude", "--target", str(self.target),
                                     "--bundle", "amphion")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.host.plugins.count(mi.PLUGIN_ID), 1)
        found = registrations(self.home, self.target)
        self.assertEqual(set(found), CLAUDE_EVENTS)
        self.assertEqual(set(found.values()), {1})
        self.assertFalse((self.target / ".github").exists())


class WhatLands(GrimoireCase):
    def test_a_repo_install_for_both_hosts_puts_each_kit_in_its_own_place(self):
        code, out = self.run_install("--platform", "all", "--target", str(self.target),
                                     "--bundle", "zethus,amphion")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.skills(self.target / ".claude/skills"), sorted(AMPHION_OWN | CORE_SKILLS))
        self.assertEqual(self.skills(self.target / ".github/skills"),
                         sorted(ZETHUS_SKILLS | AMPHION_OWN | CORE_SKILLS))
        self.assertTrue((self.target / ".github/zethus.config.json").is_file())
        self.assertTrue((self.target / ".claude/amphion.config.json").is_file())

    def test_no_skill_is_renamed_and_both_pr_skills_exist(self):
        self.run_install("--platform", "copilot", "--user", "--bundle", "zethus,amphion")
        names = self.skills(self.home / ".copilot/skills")
        self.assertIn("pr-description", names)
        self.assertIn("zethus-pr-description", names)
        self.assertEqual(len(names), len(set(names)))

    def test_skill_files_are_the_cores_bytes_not_a_rewrite(self):
        self.run_install("--platform", "claude", "--user", "--bundle", "amphion")
        for src in (REPO / "core/skills").rglob("*"):
            if src.is_file():
                dest = self.home / ".claude/skills" / src.relative_to(REPO / "core/skills")
                self.assertEqual(dest.read_bytes(), src.read_bytes(), dest)

    def test_the_copilot_only_kit_is_skipped_on_claude_with_a_note(self):
        code, out = self.run_install("--platform", "all", "--user", "--bundle", "zethus")
        self.assertEqual(code, 0, out)
        self.assertIn("skip      zethus on claude", out)
        self.assertFalse((self.home / ".claude").exists(), "zethus needs core, but core is copied for Copilot only here")

    def test_asking_for_a_host_that_cannot_run_the_bundle_is_a_usage_error(self):
        code, out = self.run_install("--platform", "claude", "--user", "--bundle", "zethus")
        self.assertEqual(code, 2, out)
        self.assertEqual(self.everything(), {})

    def test_codex_and_cursor_are_refused_until_they_are_built(self):
        for host in ("codex", "cursor"):
            code, out = self.run_install("--platform", host, "--user")
            self.assertEqual(code, 2, out)
            self.assertIn("not built yet", out)
        self.assertEqual(self.everything(), {})

    def test_the_amphion_config_is_written_once_and_never_over_yours(self):
        cfg = self.target / ".claude/amphion.config.json"
        cfg.parent.mkdir(parents=True)
        mine = json.dumps({"memory": {"mode": "active"}, "my_own_key": 1})
        cfg.write_text(mine, encoding="utf-8")
        code, out = self.run_install("--platform", "all", "--target", str(self.target),
                                     "--bundle", "amphion", "--force")
        self.assertEqual(code, 0, out)
        self.assertEqual(cfg.read_text(encoding="utf-8"), mine)
        self.assertIn("keep", out)

    def test_a_user_install_writes_no_default_config(self):
        self.run_install("--platform", "all", "--user", "--bundle", "amphion")
        self.assertFalse(any(self.home.rglob("amphion.config.json")))

    def test_the_manifest_of_a_repo_install_names_no_machine(self):
        self.run_install("--platform", "claude", "--target", str(self.target), "--bundle", "amphion")
        text = (self.target / ".mesmer-grimoire/install-manifest.json").read_text(encoding="utf-8")
        doc = json.loads(text)
        self.assertTrue(all(not k.startswith(("/", "C:", "c:")) and ":" not in k for k in doc["files"]), doc["files"])
        self.assertNotIn(self._tmp.name.replace("\\", "/"), text)
        self.assertEqual(doc["bundles"], {"claude": ["amphion"]})


class NothingIsWrittenOnARefusalOrADryRun(GrimoireCase):
    def test_a_dry_run_writes_nothing_and_runs_no_mutating_command(self):
        code, out = self.run_install("--platform", "all", "--user", "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.everything(), {})
        self.assertEqual(self.host.mutating(), [])
        self.assertIn("dry run: nothing written", out)
        for must in ("== mnemosyne", "== core", "== amphion", "== zethus"):
            self.assertIn(must, out)

    def test_an_edited_skill_refuses_the_whole_install_until_force(self):
        self.run_install("--platform", "claude", "--user", "--bundle", "amphion")
        edited = self.home / ".claude/skills/flag-or-fix/SKILL.md"
        edited.write_text("mine\n", encoding="utf-8")
        before = self.everything()
        code, out = self.run_install("--platform", "all", "--user", "--bundle", "zethus,amphion")
        self.assertEqual(code, 1, out)
        self.assertIn("flag-or-fix/SKILL.md", out)
        self.assertEqual(self.everything(), before, "a refusal must write nothing, in any bundle")
        code, out = self.run_install("--platform", "all", "--user", "--bundle", "zethus,amphion", "--force")
        self.assertEqual(code, 0, out)
        self.assertEqual(edited.read_bytes(), (REPO / "core/skills/flag-or-fix/SKILL.md").read_bytes())

    def test_a_file_it_did_not_write_is_never_overwritten_even_with_force(self):
        theirs = self.home / ".claude/skills/load-context/SKILL.md"
        theirs.parent.mkdir(parents=True)
        theirs.write_text("someone else's skill\n", encoding="utf-8")
        for extra in ((), ("--force",)):
            code, out = self.run_install("--platform", "claude", "--user", "--bundle", "amphion", *extra)
            self.assertEqual(code, 1, out)
            self.assertIn("never overwritten", out)
            self.assertEqual(theirs.read_text(encoding="utf-8"), "someone else's skill\n")
        self.assertFalse((self.home / ".mesmer-grimoire").exists())

    def test_a_delegate_that_would_refuse_stops_everything_first(self):
        gh = self.target / ".github"
        gh.mkdir()
        (gh / "skills").mkdir()
        (gh / "skills/test-plan").mkdir()
        (gh / "skills/test-plan/SKILL.md").write_text("repo's own\n", encoding="utf-8")
        before = self.everything()
        code, out = self.run_install("--platform", "copilot", "--target", str(self.target),
                                     "--bundle", "zethus,amphion")
        self.assertEqual(code, 1, out)
        self.assertIn("zethus: its installer would refuse", out)
        self.assertEqual(self.everything(), before)
        self.assertEqual(self.host.mutating(), [])

    def test_beside_the_amphion_plugin_claude_gets_no_copy_until_force(self):
        self.host.plugins.append("amphion@mesmer-grimoire")
        code, out = self.run_install("--platform", "claude", "--user", "--bundle", "amphion")
        self.assertEqual(code, 0, out)
        self.assertIn("carries them", out)
        self.assertFalse((self.home / ".claude/skills").exists())
        code, out = self.run_install("--platform", "claude", "--user", "--bundle", "amphion", "--force")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.skills(self.home / ".claude/skills"), sorted(AMPHION_OWN | CORE_SKILLS))

    def test_a_broken_catalog_stops_before_any_write(self):
        with mock.patch.object(grimoire, "check", return_value=["catalog.json: broken"]):
            code, out = self.run_install("--platform", "all", "--user")
        self.assertEqual(code, 1)
        self.assertIn("nothing was written", out)
        self.assertEqual(self.everything(), {})


class AnOlderZethusInstallerOverANewInstall(GrimoireCase):
    """``tests/fixtures/zethus_install_pre_phase4.py`` is zethus/install.py as it stood before this
    phase. Run beside a copy of the kit, it is what a person gets by re-running an old checkout."""

    def old_kit(self) -> Path:
        kit = Path(self._tmp.name) / "old-checkout" / "zethus"
        shutil.copytree(REPO / "zethus", kit, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(FROZEN, kit / "install.py")
        return kit

    def run_old(self, kit: Path, *argv: str) -> tuple[int, str]:
        old = load_frozen(kit)
        old.PLATFORM = "linux"
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out):
            code = old.main(list(argv))
        return code, out.getvalue()

    def test_the_frozen_installer_is_the_one_before_the_change(self):
        text = FROZEN.read_text(encoding="utf-8")
        self.assertNotIn("--with-core", text)
        self.assertIn("--with-mnemosyne", text)

    def test_it_loses_duplicates_and_renames_nothing(self):
        self.assertEqual(self.run_install("--platform", "all", "--user", "--bundle", "zethus,amphion")[0], 0)
        before = self.everything()
        manifest_before = json.loads((self.home / ".copilot/zethus/install-manifest.json").read_text(encoding="utf-8"))
        code, out = self.run_old(self.old_kit(), "--user")
        self.assertEqual(code, 0, out)
        after = self.everything()
        self.assertEqual(after, before, "an older installer re-run changed, removed or added a file")
        self.assertEqual(json.loads((self.home / ".copilot/zethus/install-manifest.json").read_text(encoding="utf-8")),
                         manifest_before)
        self.assertEqual(self.skills(self.home / ".copilot/skills"), sorted(ZETHUS_SKILLS | AMPHION_OWN | CORE_SKILLS))
        found = registrations(self.home)
        self.assertEqual(set(found.values()), {1}, found)

    def test_it_never_lists_or_removes_the_cores_files(self):
        self.run_install("--platform", "all", "--user", "--bundle", "zethus,amphion")
        zethus_manifest = json.loads((self.home / ".copilot/zethus/install-manifest.json").read_text(encoding="utf-8"))["files"]
        for key in zethus_manifest:
            self.assertNotIn("/skills/flag-or-fix/", key)
            self.assertNotIn("/skills/pr-description/", key)
            self.assertNotIn("/skills/initialize-ci/", key)
        code, out = self.run_old(self.old_kit(), "--user", "--uninstall")
        self.assertEqual(code, 0, out)
        left = self.skills(self.home / ".copilot/skills")
        self.assertEqual(left, sorted(AMPHION_OWN | CORE_SKILLS), "the old uninstall took more than Zethus's own")
        self.assertTrue((self.home / ".mesmer-grimoire/install-manifest.json").is_file())

    def test_a_repo_install_by_the_old_installer_is_refused_whole_and_then_kept_whole(self):
        """A repo install has no manifest, so re-running over it is a conflict by design (it was
        before this phase too). The new installer must refuse without writing a byte, and with
        --force must lose nothing and change no kit file."""
        self.assertEqual(self.run_old(self.old_kit(), "--target", str(self.target))[0], 0)
        before = self.everything()
        code, out = self.run_install("--platform", "copilot", "--target", str(self.target), "--bundle", "zethus")
        self.assertEqual(code, 1, out)
        self.assertEqual(self.everything(), before, "a refusal wrote something")
        code, out = self.run_install("--platform", "copilot", "--target", str(self.target),
                                     "--bundle", "zethus", "--force")
        self.assertEqual(code, 0, out)
        after = self.everything()
        self.assertEqual({k for k in before if k not in after}, set())
        self.assertEqual({k for k in before if before[k] != after[k]}, set())
        self.assertEqual(self.skills(self.target / ".github/skills"), sorted(ZETHUS_SKILLS | CORE_SKILLS))


class UpgradingAnExistingInstall(GrimoireCase):
    def existing(self) -> dict:
        """An install as it was before this phase: the old Zethus installer, then Mnemosyne's."""
        old = AnOlderZethusInstallerOverANewInstall.old_kit(self)
        code, out = AnOlderZethusInstallerOverANewInstall.run_old(self, old, "--user")
        self.assertEqual(code, 0, out)
        code, out = self.mnemosyne("--user")
        self.assertEqual(code, 0, out)
        config = self.home / ".copilot/zethus/config.json"
        config.write_text(json.dumps({"branchModel": {"base": "main"}, "memory": {"mode": "active"},
                                      "my_own_key": [1, 2]}), encoding="utf-8")
        return {"files": self.everything(), "config": config.read_bytes(),
                "zethus": json.loads((self.home / ".copilot/zethus/install-manifest.json").read_text(encoding="utf-8")),
                "mnemosyne": json.loads((self.home / ".mnemosyne/install-manifest.json").read_text(encoding="utf-8"))}

    def mnemosyne(self, *argv: str) -> tuple[int, str]:
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out):
            return mi.main(list(argv)), out.getvalue()

    # the old-kit helpers above are written for that class; borrow them
    old_kit = AnOlderZethusInstallerOverANewInstall.old_kit
    run_old = AnOlderZethusInstallerOverANewInstall.run_old

    def test_an_upgrade_adds_the_core_and_amphion_and_loses_nothing(self):
        before = self.existing()
        code, out = self.run_install("--platform", "all", "--user", "--bundle", "zethus,amphion")
        self.assertEqual(code, 0, out)
        after = self.everything()
        for key, digest in before["files"].items():
            if key.endswith(("install-manifest.json",)):
                continue
            self.assertEqual(after.get(key), digest, f"{key} was lost or changed by the upgrade")
        added = {k for k in after if k not in before["files"]}
        self.assertTrue(all("/skills/" in k or ".mesmer-grimoire" in k or ".claude/" in k or ".mnemosyne" in k
                            for k in added), sorted(added))
        self.assertEqual(self.skills(self.home / ".copilot/skills"), sorted(ZETHUS_SKILLS | AMPHION_OWN | CORE_SKILLS))

    def test_no_config_key_is_lost_or_renamed(self):
        before = self.existing()
        self.run_install("--platform", "all", "--user", "--bundle", "zethus,amphion")
        self.assertEqual((self.home / ".copilot/zethus/config.json").read_bytes(), before["config"])

    def test_zethus_and_mnemosyne_manifests_keep_every_entry_and_gain_none_of_the_cores(self):
        before = self.existing()
        self.run_install("--platform", "all", "--user", "--bundle", "zethus,amphion")
        zethus = json.loads((self.home / ".copilot/zethus/install-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(zethus["files"], before["zethus"]["files"])
        mnemosyne = json.loads((self.home / ".mnemosyne/install-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(mnemosyne["copilot_hooks"], before["mnemosyne"]["copilot_hooks"])
        self.assertEqual(mnemosyne["files"], before["mnemosyne"]["files"])
        self.assertEqual(mnemosyne["claude_plugin"], before["mnemosyne"]["claude_plugin"])

    def test_the_hooks_stay_registered_exactly_once(self):
        self.existing()
        self.run_install("--platform", "all", "--user", "--bundle", "zethus,amphion")
        found = registrations(self.home)
        self.assertEqual(set(found), CLAUDE_EVENTS | COPILOT_EVENTS)
        self.assertEqual(set(found.values()), {1}, found)
        self.assertEqual(self.host.plugins.count(mi.PLUGIN_ID), 1)

    def test_an_edited_zethus_file_survives_a_refused_upgrade(self):
        self.existing()
        edited = self.home / ".copilot/skills/test-plan/SKILL.md"
        edited.write_text("my version of this skill\n", encoding="utf-8")
        before = self.everything()
        code, out = self.run_install("--platform", "all", "--user", "--bundle", "zethus,amphion")
        self.assertEqual(code, 1, out)
        self.assertEqual(self.everything(), before)
        self.assertEqual(edited.read_text(encoding="utf-8"), "my version of this skill\n")

    def test_a_skill_the_user_added_beside_ours_is_untouched(self):
        self.existing()
        mine = self.home / ".copilot/skills/my-own/SKILL.md"
        mine.parent.mkdir(parents=True)
        mine.write_text("---\nname: my-own\ndescription: x\n---\n", encoding="utf-8")
        self.run_install("--platform", "all", "--user", "--bundle", "zethus,amphion")
        self.assertTrue(mine.is_file())
        self.run_install("--platform", "all", "--user", "--uninstall")
        self.assertTrue(mine.is_file(), "an uninstall removed a skill nobody installed")


class Uninstall(GrimoireCase):
    def both(self, scope=("--user",)):
        code, out = self.run_install("--platform", "all", *scope, "--bundle", "zethus,amphion")
        self.assertEqual(code, 0, out)

    def test_removing_amphion_keeps_the_core_zethus_still_needs(self):
        self.both()
        code, out = self.run_install("--platform", "all", "--user", "--uninstall", "--bundle", "amphion")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.skills(self.home / ".copilot/skills"), sorted(ZETHUS_SKILLS | CORE_SKILLS))
        self.assertFalse((self.home / ".claude/skills").exists(), "nothing on Claude needs the core now")
        self.assertTrue((self.home / ".copilot/zethus/install-manifest.json").is_file())
        found = registrations(self.home)
        self.assertEqual(set(found.values()), {1}, "the hooks stay: the core still needs them")

    def test_removing_everything_leaves_only_what_was_not_ours(self):
        mine = self.home / ".claude/skills/mine/SKILL.md"
        mine.parent.mkdir(parents=True)
        mine.write_text("keep\n", encoding="utf-8")
        self.both()
        code, out = self.run_install("--platform", "all", "--user", "--uninstall")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.skills(self.home / ".copilot/skills"), [])
        self.assertEqual(self.skills(self.home / ".claude/skills"), ["mine"])
        self.assertTrue(mine.is_file())
        self.assertFalse((self.home / ".mesmer-grimoire").exists())
        self.assertFalse((self.home / ".copilot/zethus/install-manifest.json").exists())
        self.assertFalse((self.home / ".mnemosyne/install-manifest.json").exists())
        self.assertEqual(registrations(self.home), Counter())
        self.assertEqual(self.host.plugins, [])
        self.assertTrue((self.home / "repos/mnemosyne-local/memory").is_dir(), "the memory repo is never removed")

    def test_an_edited_file_is_kept_and_force_removes_it(self):
        self.both()
        edited = self.home / ".copilot/skills/load-context/SKILL.md"
        edited.write_text("mine\n", encoding="utf-8")
        code, out = self.run_install("--platform", "all", "--user", "--uninstall", "--bundle", "amphion")
        self.assertEqual(code, 1, out)
        self.assertIn("edited since install", out)
        self.assertTrue(edited.is_file())
        code, out = self.run_install("--platform", "all", "--user", "--uninstall", "--bundle", "amphion", "--force")
        self.assertEqual(code, 0, out)
        self.assertFalse(edited.exists())

    def test_a_repo_uninstall_removes_the_skills_and_leaves_committed_kit_files_to_git(self):
        self.both(("--target", str(self.target)))
        code, out = self.run_install("--platform", "all", "--target", str(self.target), "--uninstall")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.skills(self.target / ".claude/skills"), [])
        self.assertEqual(self.skills(self.target / ".github/skills"), sorted(ZETHUS_SKILLS))
        self.assertIn("removed with git", out)
        self.assertFalse((self.target / ".mesmer-grimoire").exists())

    def test_uninstall_with_nothing_recorded_says_so(self):
        code, out = self.run_install("--platform", "all", "--user", "--uninstall")
        self.assertEqual(code, 1, out)
        self.assertIn("no install recorded", out)

    def test_a_dry_run_uninstall_removes_nothing(self):
        self.both()
        before = self.everything()
        code, out = self.run_install("--platform", "all", "--user", "--uninstall", "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.everything(), before)
        self.assertIn("dry run: nothing removed", out)


class AHostileOrDamagedManifest(GrimoireCase):
    """A repo's manifest is committed, so it is input, not a record to obey."""

    def test_a_key_outside_the_repo_is_never_removed(self):
        victim = Path(self._tmp.name) / "outside.txt"
        victim.write_text("precious", encoding="utf-8")
        sha = hashlib.sha256(victim.read_bytes()).hexdigest()
        self.run_install("--platform", "claude", "--target", str(self.target), "--bundle", "amphion")
        manifest = self.target / ".mesmer-grimoire/install-manifest.json"
        doc = json.loads(manifest.read_text(encoding="utf-8"))
        doc["files"]["../outside.txt"] = {"sha256": sha, "bundle": "amphion", "host": "claude"}
        manifest.write_text(json.dumps(doc), encoding="utf-8")
        code, out = self.run_install("--platform", "claude", "--target", str(self.target), "--uninstall")
        self.assertEqual(code, 0, out)
        self.assertEqual(victim.read_text(encoding="utf-8"), "precious")
        self.assertIn("outside this install's folder", out)

    def test_a_manifest_that_is_not_the_right_shape_is_tolerated(self):
        manifest = self.target / ".mesmer-grimoire/install-manifest.json"
        manifest.parent.mkdir()
        manifest.write_text(json.dumps({"bundles": {"claude": "amphion", "copilot": [1, "core"]},
                                        "files": ["x"]}), encoding="utf-8")
        code, out = self.run_install("--platform", "claude", "--target", str(self.target), "--bundle", "amphion")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["bundles"],
                         {"copilot": ["core"], "claude": ["amphion"]})

    def test_an_unreadable_manifest_is_the_same_as_none(self):
        manifest = self.target / ".mesmer-grimoire/install-manifest.json"
        manifest.parent.mkdir()
        manifest.write_text("{not json", encoding="utf-8")
        code, out = self.run_install("--platform", "claude", "--target", str(self.target), "--bundle", "amphion")
        self.assertEqual(code, 0, out)


class TheKitsOwnEntryPoints(GrimoireCase):
    def test_amphion_install_py_is_the_root_installer_for_amphion(self):
        spec = importlib.util.spec_from_file_location("amphion_install", REPO / "amphion/install.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out):
            code = mod.main(["--user"])
        self.assertEqual(code, 0, out.getvalue())
        self.assertEqual(self.skills(self.home / ".claude/skills"), sorted(AMPHION_OWN | CORE_SKILLS))
        self.assertFalse((self.home / ".copilot/skills").exists())
        self.assertEqual(set(registrations(self.home).values()), {1})

    def test_amphion_install_py_takes_a_platform(self):
        spec = importlib.util.spec_from_file_location("amphion_install2", REPO / "amphion/install.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out):
            code = mod.main(["--user", "--platform", "copilot"])
        self.assertEqual(code, 0, out.getvalue())
        self.assertFalse((self.home / ".claude/skills").exists())
        self.assertEqual(self.skills(self.home / ".copilot/skills"), sorted(AMPHION_OWN | CORE_SKILLS))

    def test_zethus_with_core_is_zethus_plus_the_core(self):
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out):
            code = self.zethus.main(["--target", str(self.target), "--with-core"])
        self.assertEqual(code, 0, out.getvalue())
        self.assertEqual(self.skills(self.target / ".github/skills"), sorted(ZETHUS_SKILLS | CORE_SKILLS))
        self.assertEqual(set(registrations(self.home, self.target).values()), {1})

    def test_zethus_with_core_uninstall_takes_the_core_out_again(self):
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out):
            self.assertEqual(self.zethus.main(["--user", "--with-core"]), 0)
            code = self.zethus.main(["--user", "--with-core", "--uninstall"])
        self.assertEqual(code, 0, out.getvalue())
        self.assertEqual(self.skills(self.home / ".copilot/skills"), [])
        self.assertEqual(registrations(self.home), Counter())

    def test_with_core_and_migrate_are_not_combined(self):
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            self.zethus.main(["--user", "--with-core", "--migrate-to-plugin"])

    def test_zethus_without_the_new_flag_behaves_as_before(self):
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out):
            code = self.zethus.main(["--user"])
        self.assertEqual(code, 0, out.getvalue())
        self.assertEqual(self.skills(self.home / ".copilot/skills"), sorted(ZETHUS_SKILLS))
        self.assertEqual(registrations(self.home), Counter())
        self.assertFalse((self.home / ".mesmer-grimoire").exists())


class UsageErrors(GrimoireCase):
    def test_uninstall_needs_a_scope(self):
        self.assertEqual(self.run_install("--platform", "all", "--uninstall")[0], 2)

    def test_user_and_target_are_exclusive(self):
        self.assertEqual(self.run_install("--user", "--target", str(self.target))[0], 2)

    def test_a_target_that_is_not_a_directory(self):
        code, out = self.run_install("--platform", "all", "--target", str(self.target / "nope"))
        self.assertEqual(code, 2, out)

    def test_an_unknown_bundle_or_platform(self):
        self.assertEqual(self.run_install("--user", "--bundle", "nope")[0], 2)
        self.assertEqual(self.run_install("--user", "--platform", "nope")[0], 2)

    def test_no_flags_is_a_usage_error(self):
        self.assertEqual(self.run_install()[0], 2)


if __name__ == "__main__":
    unittest.main()

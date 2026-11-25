"""The shared core (``core/``) and the catalog that names it (``catalog.json``), as ``install.py
--check`` reads them.

What must hold: the core is the one source of the memory hook script, its registrations and the
skills both kits share; the plugin folders carry byte copies and can never drift from it; the
catalog agrees with the marketplaces and plugin manifests; both kits' example configs satisfy the
core's ``memory`` schema; and none of this moved a file an existing install reads.
"""
from __future__ import annotations

import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


grimoire = load(REPO / "install.py", "grimoire_install")
CATALOG = grimoire.load_catalog(REPO)


def run(*argv: str) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = grimoire.main(list(argv))
        except SystemExit as exc:               # argparse usage errors
            code = int(exc.code or 0)
    return code, out.getvalue() + err.getvalue()


def copy_repo(dest: Path) -> Path:
    """Just the files ``--check`` reads, so a test can break one without touching the checkout."""
    for rel in ("catalog.json", "core", "amphion", "mnemosyne/plugin", ".claude-plugin", ".github/plugin",
                "zethus/plugin.json", "zethus/zethus.config.example.json"):
        src = REPO / rel
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, out, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copyfile(src, out)
    for rel in ("zethus/install.py", "mnemosyne/install.py"):     # --check only needs them to exist
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        (dest / rel).write_text("# stand-in\n", encoding="utf-8")
    return dest


class TheCatalog(unittest.TestCase):
    def test_the_real_repo_passes_check(self):
        code, out = run("--check")
        self.assertEqual(code, 0, out)

    def test_requires_resolve_dependencies_first_and_once(self):
        self.assertEqual(grimoire.closure(CATALOG, ["zethus", "amphion"]),
                         ["mnemosyne", "core", "zethus", "amphion"])
        self.assertEqual(grimoire.closure(CATALOG, ["mnemosyne"]), ["mnemosyne"])
        self.assertEqual(grimoire.closure(CATALOG, ["amphion"]), ["mnemosyne", "core", "amphion"])

    def test_a_loop_in_requires_is_refused(self):
        looped = json.loads(json.dumps(CATALOG))
        looped["bundles"]["mnemosyne"]["requires"] = ["zethus"]
        with self.assertRaises(ValueError):
            grimoire.closure(looped, ["zethus"])

    def test_every_bundle_lists_only_hosts_that_are_built(self):
        built = {h for h, v in CATALOG["hosts"].items() if v["built"]}
        self.assertEqual(built, {"claude", "copilot"})
        for name, b in CATALOG["bundles"].items():
            self.assertTrue(set(b["hosts"]) <= built, name)

    def test_list_names_every_bundle_and_the_unbuilt_hosts(self):
        code, out = run("--list")
        self.assertEqual(code, 0)
        for name in CATALOG["bundles"]:
            self.assertIn(name, out)
        self.assertIn("not built yet: codex, cursor", out)

    def test_no_flag_is_a_usage_error(self):
        self.assertEqual(run()[0], 2)


class TheCoreIsTheOneSource(unittest.TestCase):
    def test_every_copy_is_byte_identical_to_its_source(self):
        pairs = grimoire.mirror_pairs(CATALOG, REPO)
        self.assertGreaterEqual(len(pairs), 9)         # 3 hook files + the 3 skills' files
        for src, dst in pairs:
            with self.subTest(dst.relative_to(REPO).as_posix()):
                self.assertTrue(dst.is_file())
                self.assertEqual(src.read_bytes(), dst.read_bytes())

    def test_the_paths_existing_installs_read_are_still_where_they_were(self):
        """mnemosyne/install.py copies ``plugin/``; Claude Code and Copilot read the hook files from
        the plugin folder; Amphion's plugin carries its skills. The core moved none of them."""
        for rel in ("mnemosyne/plugin/hooks/mnemosyne_hook.py", "mnemosyne/plugin/hooks/hooks.json",
                    "mnemosyne/plugin/com.github.copilot/hooks/hooks.json",
                    "amphion/plugin/skills/flag-or-fix/SKILL.md",
                    "amphion/plugin/skills/pr-description/SKILL.md",
                    "amphion/plugin/skills/resume-interrupted-phase/SKILL.md",
                    "amphion/plugin/skills/resume-interrupted-phase/runbook.md"):
            self.assertTrue((REPO / rel).is_file(), rel)

    def test_the_core_holds_the_hook_script_its_two_registrations_and_the_skills(self):
        for rel in ("core/hooks/mnemosyne_hook.py", "core/hooks/hooks.json",
                    "core/hooks/com.github.copilot/hooks.json", "core/memory.schema.json",
                    "core/skills/flag-or-fix/SKILL.md", "core/skills/pr-description/SKILL.md",
                    "core/skills/resume-interrupted-phase/SKILL.md"):
            self.assertTrue((REPO / rel).is_file(), rel)

    def test_every_registration_calls_the_one_script(self):
        claude = json.loads((REPO / "core/hooks/hooks.json").read_text(encoding="utf-8"))["hooks"]
        copilot = json.loads((REPO / "core/hooks/com.github.copilot/hooks.json").read_text(encoding="utf-8"))["hooks"]
        for events in (claude, copilot):
            for entries in events.values():
                text = json.dumps(entries)
                self.assertIn("mnemosyne_hook.py", text)
        self.assertEqual(len(claude), 6)
        self.assertEqual(len(copilot), 5)               # PostToolUseFailure has no Copilot twin

    def test_amphion_carries_exactly_its_own_skills_and_the_cores(self):
        have = {p.name for p in (REPO / "amphion/plugin/skills").iterdir() if p.is_dir()}
        want = set(CATALOG["bundles"]["amphion"]["skills"]) | set(CATALOG["bundles"]["core"]["skills"])
        self.assertEqual(have, want)

    def test_zethus_keeps_its_own_pr_skill_name(self):
        """D8, ruled: Zethus's is zethus-pr-description. The shared core's pr-description is the
        general one; installing both leaves two names, never a rename of either."""
        self.assertTrue((REPO / "zethus/skills/zethus-pr-description/SKILL.md").is_file())
        self.assertFalse((REPO / "zethus/skills/pr-description").exists())


class DriftIsCaught(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = copy_repo(Path(self._tmp.name))

    def check(self) -> list[str]:
        return grimoire.check(self.root)

    def test_a_clean_copy_passes(self):
        self.assertEqual(self.check(), [])

    def test_an_edited_copy_of_the_hook_script_is_named(self):
        path = self.root / "mnemosyne/plugin/hooks/mnemosyne_hook.py"
        path.write_bytes(path.read_bytes() + b"# drift\n")
        problems = self.check()
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("mnemosyne/plugin/hooks/mnemosyne_hook.py", problems[0])
        self.assertIn("--sync-core", problems[0])

    def test_an_edit_to_the_source_leaves_every_copy_stale_until_synced(self):
        src = self.root / "core/skills/flag-or-fix/SKILL.md"
        src.write_bytes(src.read_bytes() + b"\nnew line\n")
        self.assertEqual(len(self.check()), 1)
        changed = grimoire.sync_core(grimoire.load_catalog(self.root), self.root)
        self.assertEqual(changed, ["amphion/plugin/skills/flag-or-fix/SKILL.md"])
        self.assertEqual(self.check(), [])
        self.assertEqual(grimoire.sync_core(grimoire.load_catalog(self.root), self.root), [])

    def test_a_missing_copy_is_written_by_sync(self):
        (self.root / "amphion/plugin/skills/pr-description/SKILL.md").unlink()
        self.assertTrue(any("pr-description" in p for p in self.check()))
        grimoire.sync_core(grimoire.load_catalog(self.root), self.root)
        self.assertEqual(self.check(), [])

    def test_a_copy_with_no_source_is_found_and_removed(self):
        stray = self.root / "amphion/plugin/skills/flag-or-fix/old-notes.md"
        stray.write_text("left over\n", encoding="utf-8")
        self.assertTrue(any("old-notes.md" in p for p in self.check()))
        grimoire.sync_core(grimoire.load_catalog(self.root), self.root)
        self.assertFalse(stray.exists())

    def test_a_skill_in_the_plugin_that_no_bundle_lists_is_named(self):
        extra = self.root / "amphion/plugin/skills/stray"
        extra.mkdir()
        (extra / "SKILL.md").write_text("---\nname: stray\ndescription: x\n---\n", encoding="utf-8")
        self.assertTrue(any("stray" in p and "no bundle" in p for p in self.check()))

    def test_a_marketplace_version_that_differs_from_the_manifest_is_named(self):
        path = self.root / ".claude-plugin/marketplace.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["plugins"][0]["version"] = "9.9.9"
        path.write_text(json.dumps(doc), encoding="utf-8")
        self.assertTrue(any("9.9.9" in p for p in self.check()))

    def test_a_plugin_missing_from_the_catalog_is_named(self):
        path = self.root / ".github/plugin/marketplace.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["plugins"].append({"name": "extra", "source": "./extra", "version": "1.0.0"})
        path.write_text(json.dumps(doc), encoding="utf-8")
        self.assertTrue(any("extra is in the marketplace but not in the catalog" in p for p in self.check()))

    def test_a_bundle_that_requires_nothing_real_is_named(self):
        path = self.root / "catalog.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["bundles"]["amphion"]["requires"] = ["nonesuch"]
        path.write_text(json.dumps(doc), encoding="utf-8")
        self.assertTrue(any("nonesuch" in p for p in self.check()))

    def test_a_host_that_is_not_built_cannot_be_listed(self):
        path = self.root / "catalog.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["bundles"]["zethus"]["hosts"].append("cursor")
        path.write_text(json.dumps(doc), encoding="utf-8")
        self.assertTrue(any("cursor" in p and "not built" in p for p in self.check()))

    def test_a_bad_memory_block_in_a_kit_example_is_named(self):
        path = self.root / "zethus/zethus.config.example.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["memory"] = {"mode": "loud", "autoStore": {"perSession": -1}, "typo": 1}
        path.write_text(json.dumps(doc), encoding="utf-8")
        problems = " ".join(self.check())
        for needle in ("loud", "below 0", "unknown key 'typo'"):
            self.assertIn(needle, problems)

    def test_check_exits_1_and_lists_each_problem(self):
        (self.root / "core/hooks/hooks.json").write_text("{}\n", encoding="utf-8")
        code, out = run("--root", str(self.root), "--check")
        self.assertEqual(code, 1)
        self.assertIn("mnemosyne/plugin/hooks/hooks.json", out)
        self.assertIn("problem(s)", out)


class TheMemorySchema(unittest.TestCase):
    schema = json.loads((REPO / "core/memory.schema.json").read_text(encoding="utf-8"))

    def problems(self, block) -> list[str]:
        return grimoire.schema_problems(block, self.schema, "memory")

    def test_both_kits_example_configs_carry_a_valid_memory_block(self):
        for rel in ("zethus/zethus.config.example.json", "amphion/amphion.config.example.json"):
            block = json.loads((REPO / rel).read_text(encoding="utf-8")).get("memory")
            self.assertIsInstance(block, dict, rel)
            self.assertEqual(self.problems(block), [], rel)

    def test_the_full_block_from_the_spec_is_valid(self):
        block = {"enabled": True, "mode": "shadow", "repo": "",
                 "autoStore": {"signals": ["adr", "gate-red-green", "explicit-remember"], "perSession": 5},
                 "ask": {"signals": []},
                 "watch": ["docs/adr/", {"path": "docs/specs/", "kind": "spec"}],
                 "standard": {"minOccurrences": 3, "minContexts": 2, "windowDays": 180},
                 "offerTier": ""}
        self.assertEqual(self.problems(block), [])

    def test_every_key_is_optional(self):
        self.assertEqual(self.problems({}), [])

    def test_what_it_refuses(self):
        for block, needle in (({"mode": "loud"}, "not one of"),
                              ({"enabled": "yes"}, "expected boolean"),
                              ({"autoStore": {"perSession": True}}, "expected integer"),
                              ({"standard": {"windowDays": 0}}, "below 1"),
                              ({"watch": [{"kind": "spec"}]}, "matches none"),
                              ({"watch": "docs/"}, "expected array"),
                              ({"nonsense": 1}, "unknown key")):
            with self.subTest(block=block):
                self.assertIn(needle, " ".join(self.problems(block)))

    def test_every_key_the_engine_reads_is_in_the_schema(self):
        """The schema is derived from what ``mnemosyne.candidates`` and ``standards`` read."""
        engine = REPO / "mnemosyne/src/mnemosyne"
        text = (engine / "candidates.py").read_text(encoding="utf-8") + \
            (engine / "standards.py").read_text(encoding="utf-8")
        for key in ("enabled", "mode", "watch", "autoStore", "standard", "offerTier", "perSession"):
            self.assertIn(f'"{key}"', text, key)
            top = self.schema["properties"]
            nested = {k for v in top.values() for k in v.get("properties", {})}
            self.assertIn(key, set(top) | nested)


if __name__ == "__main__":
    unittest.main()

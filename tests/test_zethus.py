"""CI coverage for the Zethus Copilot process kit.

Covers the five stdlib scripts (run-local-gates, new-adr, new-spec, docs-pointer-check,
base-freshness), the installer, and the kit's own contract: every skill's frontmatter is valid for Copilot, the minimum
spec stays a strict subset of the full one, and the kit's Markdown has no broken pointers.

Each script is loaded from its file (the names are hyphenated, so they aren't importable modules)
and driven through ``main(argv)`` against a throwaway temp repo.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
KIT = REPO / "zethus"
SCRIPTS = KIT / "scripts"

REQUIRED_SKILLS = {
    "research-existing-code", "write-spec-full", "write-spec-minimum", "write-adr",
    "fresh-eyes-investigation", "implement-phase", "test-plan", "pre-push-gates",
    "zethus-pr-description", "docs-sync-check",
}


def load(path: Path):
    name = "zethus_" + path.stem.replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module          # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


gates_mod = load(SCRIPTS / "run-local-gates.py")
adr_mod = load(SCRIPTS / "new-adr.py")
spec_mod = load(SCRIPTS / "new-spec.py")
pointer_mod = load(SCRIPTS / "docs-pointer-check.py")
fresh_mod = load(SCRIPTS / "base-freshness.py")
install_mod = load(KIT / "install.py")


def run(module, *argv: str) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = module.main(list(argv))
    return code, out.getvalue() + err.getvalue()


def py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}
    fields = {}
    for line in m.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and not line.startswith(" "):
            fields[key.strip()] = value.strip().strip('"')
    return fields


def headings(path: Path) -> list[str]:
    return [ln[3:].strip() for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.startswith("## ")]


def isolate_home(test: unittest.TestCase, home: Path) -> None:
    """Point ``Path.home()`` at ``home`` and clear ``$ZETHUS_CONFIG``, so a developer's own
    ``~/.copilot/zethus/config.json`` can never leak into a test."""
    env = {"HOME": str(home), "USERPROFILE": str(home),
           "LOCALAPPDATA": str(home / "AppData" / "Local")}
    patcher = mock.patch.dict(os.environ, env)
    patcher.start()
    test.addCleanup(patcher.stop)
    os.environ.pop("ZETHUS_CONFIG", None)       # restored by the patcher on cleanup


class TempRepo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        isolate_home(self, self.repo / "_home")

    def tearDown(self):
        self._tmp.cleanup()

    def config(self, data: dict, where: str = ".github/zethus.config.json") -> None:
        path = self.repo / where
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def write(self, rel: str, text: str = "") -> Path:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


class RunLocalGates(TempRepo):
    def gates(self, *argv):
        return run(gates_mod, "--repo", str(self.repo), *argv)

    def test_all_pass_is_full_green(self):
        self.config({"gates": {"steps": [{"name": "a", "command": py("pass")},
                                         {"name": "b", "command": py("pass")}]}})
        code, out = self.gates()
        self.assertEqual(code, 0, out)
        self.assertIn("| a | PASS |", out)
        self.assertIn("GREEN — every gate ran and passed", out)

    def test_failure_is_red_and_shows_output_tail(self):
        self.config({"gates": {"steps": [
            {"name": "ok", "command": py("pass")},
            {"name": "broken", "command": py("print('boom-marker'); raise SystemExit(3)")},
        ]}})
        code, out = self.gates()
        self.assertEqual(code, 1, out)
        self.assertIn("| broken | FAIL |", out)
        self.assertIn("exit 3", out)
        self.assertIn("RED — fix before pushing: broken", out)
        self.assertIn("boom-marker", out)

    def test_missing_tool_is_skip_not_green(self):
        self.config({"gates": {"steps": [
            {"name": "ok", "command": py("pass")},
            {"name": "ghost", "command": "zethus-no-such-tool-xyz --check"},
        ]}})
        code, out = self.gates()
        self.assertEqual(code, 3, out)
        self.assertIn("| ghost | SKIP |", out)
        self.assertIn("NOT checked: ghost", out)
        self.assertNotIn("every gate ran", out)

    def test_expected_nonzero_exit_passes(self):
        self.config({"gates": {"steps": [
            {"name": "grep-none", "command": py("raise SystemExit(1)"), "exitCode": 1}]}})
        code, out = self.gates()
        self.assertEqual(code, 0, out)
        self.assertIn("exit 1 (expected)", out)

    def test_amphion_config_is_read_and_prose_checks_are_manual(self):
        self.config({"gates": {"test": py("pass"), "mandatedChecks": [
            {"name": "no-todo", "command": "git grep TODO", "expect": "0 hits"}]}},
            where=".claude/amphion.config.json")
        code, out = self.gates()
        self.assertEqual(code, 3, out)
        self.assertIn(".claude/amphion.config.json", out)
        self.assertIn("| test | PASS |", out)
        self.assertIn("| no-todo | MANUAL |", out)
        self.assertIn("expect: 0 hits", out)

    def test_zethus_config_wins_over_amphion(self):
        self.config({"gates": {"steps": [{"name": "mine", "command": py("pass")}]}})
        self.config({"gates": {"test": py("raise SystemExit(1)")}}, where=".claude/amphion.config.json")
        code, out = self.gates()
        self.assertEqual(code, 0, out)
        self.assertIn("| mine | PASS |", out)

    def test_no_gates_is_not_green(self):
        code, out = self.gates()
        self.assertEqual(code, 2)
        self.assertIn("no gates found", out)

    def test_only_selects_and_says_partial(self):
        self.config({"gates": {"steps": [{"name": "a", "command": py("pass")},
                                         {"name": "b", "command": py("raise SystemExit(1)")}]}})
        code, out = self.gates("--only", "a")
        self.assertEqual(code, 0, out)
        self.assertIn("not a full run", out)
        self.assertNotIn("| b |", out)

    def test_only_unknown_gate_is_usage_error(self):
        self.config({"gates": {"steps": [{"name": "a", "command": py("pass")}]}})
        code, out = self.gates("--only", "nope")
        self.assertEqual(code, 2)
        self.assertIn("unknown gate", out)

    def test_invalid_config_is_usage_error(self):
        self.write(".github/zethus.config.json", "{not json")
        code, out = self.gates()
        self.assertEqual(code, 2)
        self.assertIn("not valid JSON", out)

    def test_discovers_package_json_scripts_with_lockfile_manager(self):
        self.write("package.json", json.dumps({"scripts": {"test": "x", "lint": "y", "dev": "z"}}))
        self.write("yarn.lock")
        code, out = self.gates("--list")
        self.assertEqual(code, 0, out)
        names = [ln.split("\t")[0] for ln in out.strip().splitlines()]
        self.assertEqual(names, ["lint", "test"])
        self.assertIn("yarn run lint", out)

    def test_discovers_python_unittest_or_pytest(self):
        self.write("tests/test_x.py", "")
        _, out = self.gates("--list")
        self.assertIn("python -m unittest", out)
        self.assertNotIn(sys.executable, out, "interpreter path would leak into pasted tables")
        self.write("pyproject.toml", "[tool.pytest.ini_options]\n")
        _, out = self.gates("--list")
        self.assertIn("pytest", out)
        self.assertNotIn("unittest", out)

    def test_header_reports_tree_state(self):
        self.config({"gates": {"steps": [{"name": "a", "command": py("pass")}]}})
        _, out = self.gates()
        first = out.splitlines()[0]
        self.assertTrue("not a git work tree" in first or "working tree" in first, first)


class NewAdr(TempRepo):
    def adr(self, *argv):
        return run(adr_mod, "--repo", str(self.repo), *argv)

    def test_creates_date_keyed_record_and_index(self):
        code, out = self.adr("Use the outbox pattern", "--date", "2026-01-15", "--deciders", "Team A")
        self.assertEqual(code, 0, out)
        path = self.repo / "docs/adr/2026-01-15-use-the-outbox-pattern.md"
        text = path.read_text(encoding="utf-8")
        self.assertIn("# 2026-01-15-use-the-outbox-pattern: Use the outbox pattern", text)
        self.assertIn("| Status | Proposed |", text)
        self.assertIn("| Deciders | Team A |", text)
        self.assertNotIn("{{", text)
        index = (self.repo / "docs/adr/README.md").read_text(encoding="utf-8")
        self.assertIn("| ID | Title | Status | Date |", index)
        self.assertIn("[2026-01-15-use-the-outbox-pattern](2026-01-15-use-the-outbox-pattern.md)", index)

    def test_second_record_appends_and_escapes_pipes(self):
        self.adr("First", "--date", "2026-01-15")
        self.adr("Pick A | B", "--date", "2026-01-16", "--status", "Accepted")
        index = (self.repo / "docs/adr/README.md").read_text(encoding="utf-8")
        self.assertEqual(index.count("| ID | Title |"), 1)
        self.assertIn("| Pick A \\| B | Accepted | 2026-01-16 |", index)

    def test_refuses_to_overwrite(self):
        self.adr("Same", "--date", "2026-01-15")
        path = self.repo / "docs/adr/2026-01-15-same.md"
        path.write_text("hand edited", encoding="utf-8")
        code, out = self.adr("Same", "--date", "2026-01-15")
        self.assertEqual(code, 2)
        self.assertIn("refusing to overwrite", out)
        self.assertEqual(path.read_text(encoding="utf-8"), "hand edited")

    def test_rejects_bad_date_and_empty_title(self):
        self.assertEqual(self.adr("X", "--date", "15/01/2026")[0], 2)
        self.assertEqual(self.adr("X", "--date", "2026-02-30")[0], 2)
        self.assertEqual(self.adr("!!!")[0], 2)
        self.assertFalse((self.repo / "docs").exists())

    def test_config_dir_and_no_index(self):
        self.config({"adr": {"dir": "decisions"}})
        code, _ = self.adr("Thing", "--date", "2026-01-15", "--no-index")
        self.assertEqual(code, 0)
        self.assertTrue((self.repo / "decisions/2026-01-15-thing.md").is_file())
        self.assertFalse((self.repo / "decisions/README.md").exists())


class NewSpec(TempRepo):
    def spec(self, *argv):
        return run(spec_mod, "--repo", str(self.repo), *argv)

    def test_full_and_minimum_are_created_as_draft(self):
        for kind in ("full", "minimum"):
            code, out = self.spec(kind, f"Retry webhooks {kind}", "--owner", "Payments",
                                  "--date", "2026-01-15")
            self.assertEqual(code, 0, out)
            text = (self.repo / f"docs/specs/retry-webhooks-{kind}.md").read_text(encoding="utf-8")
            self.assertIn(f"# Retry webhooks {kind}", text)
            self.assertIn("**Status:** DRAFT", text)
            self.assertIn("**Owner:** Payments", text)
            self.assertNotIn("{{", text)

    def test_refuses_to_overwrite(self):
        self.spec("minimum", "Thing")
        code, out = self.spec("full", "Thing")
        self.assertEqual(code, 2)
        self.assertIn("refusing to overwrite", out)

    def test_config_dir(self):
        self.config({"spec": {"dir": "design"}})
        self.assertEqual(self.spec("minimum", "Thing")[0], 0)
        self.assertTrue((self.repo / "design/thing.md").is_file())


class DocsPointerCheck(TempRepo):
    def check(self, *argv):
        return run(pointer_mod, "--repo", str(self.repo), *argv)

    def test_clean_links_pass(self):
        self.write("docs/guide.md", "# Guide\n")
        self.write("README.md", "See [the guide](docs/guide.md#setup), [site](https://example.com), "
                                "[top](#readme) and [dir](docs/).\n")
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("0 broken", out)

    def test_broken_link_reported_with_line(self):
        self.write("README.md", "# T\n\nSee [gone](docs/missing.md).\n")
        code, out = self.check()
        self.assertEqual(code, 1)
        self.assertIn("README.md:3: broken pointer -> docs/missing.md (does not exist)", out)

    def test_case_mismatch_is_broken(self):
        self.write("docs/Guide.md", "# Guide\n")
        self.write("README.md", "[g](docs/guide.md)\n")
        code, out = self.check()
        self.assertEqual(code, 1)
        self.assertIn("case mismatch", out)

    def test_code_is_ignored(self):
        self.write("README.md", "```\n[x](nope.md)\n```\n\n`[y](nope2.md)`\n\n~~~md\n[z](n.md)\n~~~\n")
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_reference_definitions_and_escape(self):
        self.write("sub/a.md", "[ref]: ../missing.md\n\n[out](../../outside.md)\n")
        code, out = self.check()
        self.assertEqual(code, 1)
        self.assertIn("missing.md (does not exist)", out)
        self.assertIn("points outside the repository", out)

    def test_code_spans_opt_in(self):
        self.write("src/app.py", "")
        self.write("README.md", "Edit `src/app.py:10` not `src/gone.py`, e.g. `npm run lint`.\n")
        self.assertEqual(self.check()[0], 0)
        code, out = self.check("--code-spans")
        self.assertEqual(code, 1)
        self.assertIn("`src/gone.py`", out)
        self.assertNotIn("app.py", out.split("broken pointer")[-1].split("\n")[0])

    def test_ignore_glob(self):
        self.write("CHANGELOG.md", "[old](gone.md)\n")
        self.assertEqual(self.check("--ignore", "CHANGELOG.md")[0], 0)

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_sync_base_reports_stale_docs(self):
        def git(*args):
            subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=t",
                            "-c", "user.email=t@example.com", *args],
                           check=True, capture_output=True)
        git("init", "-q", "-b", "base")
        self.write("README.md", "# App\n")
        self.write("api/README.md", "# API\n")
        self.write("api/handler.py", "x = 1\n")
        self.write("cli/main.py", "y = 1\n")
        self.config({"docSync": {"map": [
            {"doc": "README.md", "describes": ["cli/*"]},
            {"doc": "api/README.md", "describes": ["api/*.py"]}]}})
        git("add", "-A")
        git("commit", "-q", "-m", "init")
        git("checkout", "-q", "-b", "work")
        self.write("api/handler.py", "x = 2\n")
        self.write("cli/main.py", "y = 2\n")
        self.write("README.md", "# App v2\n")
        code, out = self.check("--sync-base", "base")
        self.assertEqual(code, 0, out)
        self.assertIn("REVIEW   api/README.md — describes changed: api/handler.py", out)
        self.assertIn("UPDATED  README.md", out)

        code, out = self.check("--sync-base", "no-such-ref")
        self.assertEqual(code, 0)
        self.assertIn("docs sync: no answer", out)


@unittest.skipUnless(shutil.which("git"), "git not installed")
class BaseFreshness(TempRepo):
    """A real bare "origin" and a clone of it, so fetch, rev-list and merge-base run for real."""

    def setUp(self):
        super().setUp()
        self.origin = self.repo / "_origin.git"
        self.seed = self.repo / "_seed"
        self.work = self.repo / "work"
        self.git(self.repo, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.git(self.repo, "clone", "-q", str(self.origin), str(self.seed))
        self.commit(self.seed, "a.txt", "init")
        self.git(self.seed, "push", "-q", "origin", "HEAD:main", "HEAD:develop")
        self.git(self.repo, "clone", "-q", str(self.origin), str(self.work))
        self.git(self.work, "checkout", "-q", "-b", "feature/x", "origin/develop")
        self.commit(self.work, "mine.txt", "my change")

    def git(self, where: Path, *args: str) -> str:
        return subprocess.run(["git", "-C", str(where), "-c", "user.name=t",
                               "-c", "user.email=t@example.com", *args],
                              check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, where: Path, name: str, text: str) -> None:
        (where / name).write_text(text + "\n", encoding="utf-8")
        self.git(where, "add", name)
        self.git(where, "commit", "-q", "-m", text)

    def land_on_base(self, n: int, branch: str = "develop") -> None:
        """Someone else merges ``n`` commits into the base on the remote."""
        self.git(self.seed, "fetch", "-q", "origin")
        self.git(self.seed, "checkout", "-q", "-B", branch, f"origin/{branch}")
        for i in range(n):
            self.commit(self.seed, f"theirs-{branch}-{i}-{os.urandom(3).hex()}.txt", f"theirs {i}")
        self.git(self.seed, "push", "-q", "origin", branch)

    def set_config(self, branch_model: dict) -> None:
        path = self.work / ".copilot/zethus.config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"branchModel": branch_model}), encoding="utf-8")
        exclude = self.git(self.work, "rev-parse", "--git-path", "info/exclude")
        with open(self.work / exclude, "a", encoding="utf-8") as fh:
            fh.write(".copilot/\n")

    def check(self, *argv):
        return run(fresh_mod, "--repo", str(self.work), *argv)

    def test_fresh_branch_passes_and_names_the_merge_base(self):
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("style branch-per-change · base origin/develop", out)
        self.assertIn("behind   0 commit(s)", out)
        self.assertIn("ahead    1 commit(s)", out)
        mb = self.git(self.work, "merge-base", "HEAD", "origin/develop")
        self.assertIn(f"diff base (merge-base) {mb[:12]}", out)
        self.assertIn("FRESH", out)

    def test_any_commit_behind_is_stale_by_default_and_the_fetch_finds_it(self):
        self.land_on_base(1)
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("STALE — 1 commit(s) behind origin/develop", out)
        self.assertIn("Rebase before doing anything else", out)
        self.assertIn("or cut a fresh branch from it", out, "branch-per-change advice")

    def test_no_fetch_reports_the_last_fetch_and_says_so(self):
        self.land_on_base(2)
        code, out = self.check("--no-fetch")
        self.assertEqual(code, 0, out)
        self.assertIn("NOT fetched", out)

    def test_max_behind_is_the_threshold(self):
        self.land_on_base(2)
        self.set_config({"maxBehind": 2})
        self.assertEqual(self.check()[0], 0)
        self.land_on_base(1)
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("(allowed: 2)", out)
        self.assertEqual(self.check("--max-behind", "5")[0], 0, "the flag overrides config")

    def test_rebase_style_advice_and_rewritten_branch(self):
        self.set_config({"style": "rebase"})
        self.git(self.work, "push", "-q", "-u", "origin", "feature/x")
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("style rebase", out)
        self.assertIn("upstream origin/feature/x — contained in HEAD", out)

        self.land_on_base(1)
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("git rebase origin/develop, re-run the gates, then git push "
                      "--force-with-lease", out)

        self.git(self.work, "rebase", "-q", "origin/develop")
        code, out = self.check()
        self.assertEqual(code, 0, out)
        new_base = self.git(self.work, "rev-parse", "origin/develop")
        self.assertIn(f"diff base (merge-base) {new_base[:12]}", out, "the base moved with it")
        self.assertIn("rewritten since the last push", out)

    def test_base_resolution(self):
        self.set_config({"base": "main"})
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("base origin/main", out)
        self.assertIn("base origin/develop", self.check("--base", "develop")[1])
        code, out = self.check("--base", "no-such-branch")
        self.assertEqual(code, 2)
        self.assertIn("origin/no-such-branch does not exist", out)

    def test_without_develop_the_remote_default_branch_is_the_base(self):
        self.git(self.work, "push", "-q", "origin", "--delete", "develop")
        self.git(self.work, "remote", "set-head", "origin", "main")
        code, out = self.check()
        self.assertIn("base origin/main", out)

    def test_bad_branch_model_is_a_usage_error(self):
        for bad in ({"style": "git-flow"}, {"maxBehind": -1}, {"maxBehind": "3"},
                    {"maxBehind": True}):
            self.set_config(bad)
            code, out = self.check("--no-fetch")
            self.assertEqual(code, 2, (bad, out))
            self.assertIn("branchModel.", out)

    def test_failed_fetch_is_no_answer_not_fresh(self):
        self.git(self.work, "remote", "set-url", "origin", str(self.repo / "_gone.git"))
        code, out = self.check()
        self.assertEqual(code, 3, out)
        self.assertIn("NO ANSWER", out)
        self.assertNotIn("FRESH", out)

    def test_merge_base_only_prints_the_diff_base_and_never_gates(self):
        mb = self.git(self.work, "merge-base", "HEAD", "origin/develop")
        code, out = self.check("--merge-base-only")
        self.assertEqual(code, 0, out)
        self.assertIn(f"diff base (merge-base) {mb[:12]}", out)
        self.assertIn("base origin/develop", out)
        self.assertNotIn("FRESH", out)

        self.land_on_base(3)                        # three commits behind: stale for the gate
        self.assertEqual(self.check()[0], 1, "the gating form still stops")
        code, out = self.check("--merge-base-only")
        self.assertEqual(code, 0, f"the merge-base is never a gate: {out}")
        self.assertIn("no gate", out)
        self.assertNotIn("STALE", out)

    def test_merge_base_only_falls_back_to_the_last_fetch_instead_of_no_answer(self):
        self.git(self.work, "remote", "set-url", "origin", str(self.repo / "_gone.git"))
        self.assertEqual(self.check()[0], 3, "the gating form refuses to guess")
        code, out = self.check("--merge-base-only")
        self.assertEqual(code, 0, out)
        self.assertIn("could not fetch", out)
        self.assertIn("NOT fetched", out)
        self.assertIn("diff base (merge-base)", out)

    def test_merge_base_only_still_reports_a_usage_error(self):
        self.set_config({"maxBehind": -1})
        code, out = self.check("--merge-base-only", "--no-fetch")
        self.assertEqual(code, 2, out)
        self.assertIn("branchModel.", out)

    def test_not_a_git_repo_is_a_usage_error(self):
        plain = self.repo / "plain"
        plain.mkdir()
        code, out = run(fresh_mod, "--repo", str(plain), "--no-fetch")
        self.assertEqual(code, 2, out)
        self.assertIn("not a git repository", out)


class Installer(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.target = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def install(self, *argv):
        return run(install_mod, "--target", str(self.target), *argv)

    def test_installs_every_piece_to_its_copilot_location(self):
        code, out = self.install()
        self.assertEqual(code, 0, out)
        gh = self.target / ".github"
        self.assertTrue((gh / "copilot-instructions.md").is_file())
        self.assertTrue((gh / "agents/zethus.agent.md").is_file())
        self.assertTrue((gh / "instructions/docs.instructions.md").is_file())
        for skill in REQUIRED_SKILLS:
            self.assertTrue((gh / "skills" / skill / "SKILL.md").is_file(), skill)
        for tpl in ("spec-full.md", "spec-minimum.md", "adr.md", "pr.md"):
            self.assertTrue((gh / "zethus/templates" / tpl).is_file(), tpl)
        self.assertTrue((gh / "zethus/scripts/run-local-gates.py").is_file())
        self.assertTrue((gh / "zethus/scripts/base-freshness.py").is_file())
        self.assertTrue((gh / "zethus.config.json").is_file())

    def test_installed_scripts_find_installed_templates(self):
        self.install()
        saved_common, saved_path = sys.modules.pop("_common", None), list(sys.path)
        try:
            installed = load(self.target / ".github/zethus/scripts/new-spec.py")
            self.assertEqual(Path(sys.modules["_common"].TEMPLATES_DIR).resolve(),
                             (self.target / ".github/zethus/templates").resolve())
            code, out = run(installed, "--repo", str(self.target), "minimum", "Thing")
        finally:
            sys.modules["_common"] = saved_common
            sys.path[:] = saved_path
        self.assertEqual(code, 0, out)
        self.assertTrue((self.target / "docs/specs/thing.md").is_file())

    def test_conflicts_write_nothing_without_force(self):
        self.install()
        agent = self.target / ".github/agents/zethus.agent.md"
        agent.write_text("local edit", encoding="utf-8")
        (self.target / ".github/skills/test-plan/SKILL.md").unlink()
        code, out = self.install()
        self.assertEqual(code, 1)
        self.assertIn(".github/agents/zethus.agent.md", out)
        self.assertEqual(agent.read_text(encoding="utf-8"), "local edit")
        self.assertFalse((self.target / ".github/skills/test-plan/SKILL.md").exists())

    def test_existing_repo_files_are_never_clobbered(self):
        gh = self.target / ".github"
        gh.mkdir()
        (gh / "copilot-instructions.md").write_text("repo rules", encoding="utf-8")
        (gh / "zethus.config.json").write_text("{}", encoding="utf-8")
        code, out = self.install("--force")
        self.assertEqual(code, 0, out)
        self.assertEqual((gh / "copilot-instructions.md").read_text(encoding="utf-8"), "repo rules")
        self.assertEqual((gh / "zethus.config.json").read_text(encoding="utf-8"), "{}")
        fallback = gh / "instructions/zethus.instructions.md"
        self.assertEqual(frontmatter(fallback).get("applyTo"), "**")

    def test_dry_run_writes_nothing(self):
        code, out = self.install("--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("dry run", out)
        self.assertFalse((self.target / ".github").exists())


class KitContract(unittest.TestCase):
    """What Copilot requires of the kit's files, per its customization docs (see zethus/README.md)."""

    def test_every_required_skill_exists_with_valid_frontmatter(self):
        # >=, not ==: the optional modernization extension (docs/modernization-shared.md) installs
        # further, pluggable skills alongside these ten core ones. See test_zethus_modernization.py
        # for its own frontmatter and cross-link contract.
        found = {p.name for p in (KIT / "skills").iterdir() if p.is_dir()}
        self.assertTrue(REQUIRED_SKILLS <= found, REQUIRED_SKILLS - found)
        for name in found:
            fm = frontmatter(KIT / "skills" / name / "SKILL.md")
            self.assertEqual(fm.get("name"), name, f"{name}: name must match its directory")
            self.assertRegex(fm["name"], r"^[a-z0-9]+(-[a-z0-9]+)*$")
            self.assertLessEqual(len(fm["name"]), 64)
            self.assertTrue(fm.get("description"), f"{name}: description is required")
            self.assertLessEqual(len(fm["description"]), 1024, name)

    def test_agent_frontmatter(self):
        path = KIT / "agents/zethus.agent.md"
        fm = frontmatter(path)
        self.assertTrue(fm.get("description"))
        self.assertEqual(fm.get("name"), "zethus")
        self.assertRegex(path.name, r"^[A-Za-z0-9._-]+$")
        self.assertLess(len(path.read_text(encoding="utf-8")), 30000)
        tools = json.loads(fm["tools"])
        self.assertTrue(set(tools) <= {"read", "search", "edit", "execute", "web", "todo", "agent"})

    def test_agent_links_every_skill(self):
        text = (KIT / "agents/zethus.agent.md").read_text(encoding="utf-8")
        for name in REQUIRED_SKILLS:
            self.assertIn(f"../skills/{name}/SKILL.md", text)

    def test_path_instructions_have_apply_to(self):
        for path in (KIT / "instructions").glob("*.instructions.md"):
            self.assertTrue(frontmatter(path).get("applyTo"), path.name)

    def test_minimum_spec_headings_are_a_strict_ordered_subset_of_full(self):
        full = headings(KIT / "templates/spec-full.md")
        minimum = headings(KIT / "templates/spec-minimum.md")
        self.assertTrue(set(minimum) < set(full), set(minimum) - set(full))
        self.assertEqual(minimum, [h for h in full if h in minimum], "same relative order")
        self.assertEqual(full[full.index("Phases") - 1], "Design")

    def test_pr_template_keeps_the_headings_other_stages_file_under(self):
        pr = headings(KIT / "templates/pr.md")
        for h in ("Evidence", "What was not checked", "Not in this PR (intentional)",
                  "Noticed but out of scope", "Decisions needed from the reviewer"):
            self.assertIn(h, pr)

    def test_example_config_is_valid_and_its_gates_parse(self):
        config = json.loads((KIT / "zethus.config.example.json").read_text(encoding="utf-8"))
        gates = gates_mod.gates_from_config(config)
        self.assertEqual([g.name for g in gates], ["lint", "typecheck", "test", "build"])

    def test_example_config_branch_model_is_valid_and_defaults_to_branch_per_change(self):
        config = json.loads((KIT / "zethus.config.example.json").read_text(encoding="utf-8"))
        self.assertEqual(fresh_mod.branch_model(config), ("branch-per-change", 0))
        self.assertEqual(fresh_mod.branch_model({}), ("branch-per-change", 0),
                         "no config keeps today's behaviour")

    def test_the_freshness_gate_runs_at_two_checkpoints_and_no_others(self):
        """Stage 0 and the pre-push gates: the two points where staleness costs something.

        It used to run at the start of all seven stages, and again inside four skills, each of
        which can stop the work for a rebase (``maxBehind`` defaults to 0) — see
        ``zethus/docs/base-freshness-cadence.md``. A third gating call is that cadence creeping
        back, so this test names the two files allowed to make one.
        """
        agent = (KIT / "agents/zethus.agent.md").read_text(encoding="utf-8")
        gates = (KIT / "skills/pre-push-gates/SKILL.md").read_text(encoding="utf-8")
        for text in (agent, gates):
            self.assertIn("python .github/zethus/scripts/base-freshness.py", text)
        self.assertIn("## Check the base at two points, not at every stage", agent)
        self.assertIn("two freshness checkpoints", gates)

        # A gating call is the script without --merge-base-only on the same line.
        offenders = []
        for path in sorted((KIT / "skills").glob("*/SKILL.md")):
            if path.parent.name == "pre-push-gates":
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                if "scripts/base-freshness.py" in line and "--merge-base-only" not in line:
                    offenders.append(f"{path.parent.name}: {line.strip()[:80]}")
        self.assertEqual(offenders, [], "only Stage 0 (the agent file) and pre-push-gates may gate "
                                        "on freshness; a stage that needs the diff base uses "
                                        "--merge-base-only")

        readme = (KIT / "README.md").read_text(encoding="utf-8")
        for key in ("branchModel.style", "branchModel.maxBehind", "--merge-base-only"):
            self.assertIn(key, readme)
        instructions = (KIT / "copilot-instructions.md").read_text(encoding="utf-8")
        for rule in ("Stage 0", "--merge-base-only", "don't re-run it"):
            self.assertIn(rule, instructions)

    def test_the_visible_plan_is_a_rule_with_a_fallback_and_an_exit_condition(self):
        agent = (KIT / "agents/zethus.agent.md").read_text(encoding="utf-8")
        self.assertIn('"todo"', frontmatter(KIT / "agents/zethus.agent.md")["tools"])
        for rule in ("## Keep the plan visible",
                     "Exactly one step is in progress at a time",
                     "When the plan changes, change the list in the same turn",
                     "A stage isn't exited with open steps",
                     "You have no todo-list tool",
                     "- [ ] ▶ ",
                     "plan.checklist",
                     "Start each reply with the current stage and step",
                     '"Skip the todo list, just do it"'):
            self.assertIn(rule, agent)
        config = json.loads((KIT / "zethus.config.example.json").read_text(encoding="utf-8"))
        self.assertEqual(config["plan"]["checklist"], "auto")
        self.assertIn("plan.checklist", (KIT / "README.md").read_text(encoding="utf-8"))

    def test_commits_are_signed_before_the_trailer_block_alongside_the_trailer(self):
        agent = (KIT / "agents/zethus.agent.md").read_text(encoding="utf-8")
        for rule in ("## Sign your commits", "commits.signature", "commits.aiTrailer",
                     "never instead of it", '`commits.signature: ""` means no signature line'):
            self.assertIn(rule, agent)
        # The example commit in the agent file: signature, then the trailer as the last paragraph.
        example = agent.split("## Sign your commits", 1)[1].split("```text\n", 1)[1]
        lines = example.split("\n```", 1)[0].splitlines()
        sig, trailer = lines.index("— Zethus"), lines.index(
            "Co-authored-by: <the commits.aiTrailer value>")
        self.assertEqual(trailer, len(lines) - 1, "the trailer block stays last")
        self.assertEqual(lines[sig - 1:trailer], ["", "— Zethus", ""],
                         "the signature is its own paragraph, just before the trailer")
        config = json.loads((KIT / "zethus.config.example.json").read_text(encoding="utf-8"))
        self.assertEqual(config["commits"]["signature"], "— Zethus")
        self.assertIn("aiTrailer", config["commits"], "the signature never replaces the trailer")
        for doc in ("README.md", "copilot-instructions.md", "skills/implement-phase/SKILL.md",
                    "skills/zethus-pr-description/SKILL.md", "templates/pr.md"):
            self.assertIn("commits.signature", (KIT / doc).read_text(encoding="utf-8"), doc)

    def test_kit_markdown_has_no_broken_pointers(self):
        code, out = run(pointer_mod, "--repo", str(REPO), "zethus")
        self.assertEqual(code, 0, out)


class FakeHome(unittest.TestCase):
    """A throwaway home directory: ``Path.home()`` reads USERPROFILE on Windows, HOME elsewhere."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / "home"
        self.home.mkdir()
        isolate_home(self, self.home)
        self.copilot = self.home / ".copilot"


class UserInstaller(FakeHome):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(install_mod, "PLATFORM", "linux")
        patcher.start()
        self.addCleanup(patcher.stop)

    def install(self, *argv):
        return run(install_mod, "--user", *argv)

    def manifest(self) -> dict:
        path = self.copilot / "zethus/install-manifest.json"
        return json.loads(path.read_text(encoding="utf-8"))["files"]

    def test_installs_every_piece_to_its_user_location(self):
        code, out = self.install()
        self.assertEqual(code, 0, out)
        c = self.copilot
        self.assertEqual(frontmatter(c / "instructions/zethus.instructions.md").get("applyTo"), "**")
        self.assertTrue((c / "instructions/zethus-docs.instructions.md").is_file())
        self.assertTrue((c / "agents/zethus.agent.md").is_file())
        for skill in REQUIRED_SKILLS:
            self.assertTrue((c / "skills" / skill / "SKILL.md").is_file(), skill)
        for tpl in ("spec-full.md", "spec-minimum.md", "adr.md", "pr.md"):
            self.assertTrue((c / "zethus/templates" / tpl).is_file(), tpl)
        self.assertTrue((c / "zethus/scripts/run-local-gates.py").is_file())
        self.assertTrue((c / "zethus/config.example.json").is_file())
        self.assertFalse((c / "zethus/config.json").exists(), "a user default would override discovery")
        written = {Path(k) for k in self.manifest()}
        on_disk = {p for p in c.rglob("*") if p.is_file() and p.name != "install-manifest.json"}
        self.assertEqual({p.resolve() for p in written}, {p.resolve() for p in on_disk})
        plan = [ln for ln in out.splitlines() if not ln.startswith("installed")]
        plan = " ".join(plan)
        for form in (str(self.home), self.home.as_posix()):
            self.assertNotIn(form, plan, "the plan shows ~/ paths, never the home directory")

    def test_markdown_points_at_the_user_install_not_dot_github(self):
        self.install()
        zhome = (self.copilot / "zethus").as_posix()
        for md in self.copilot.rglob("*.md"):
            if "templates" in md.parts:
                continue
            text = md.read_text(encoding="utf-8")
            self.assertNotIn(".github/zethus/", text, md)
            self.assertNotIn("`.github/copilot-instructions.md`", text, md)
        gates_skill = (self.copilot / "skills/pre-push-gates/SKILL.md").read_text(encoding="utf-8")
        self.assertIn(f"python {zhome}/scripts/run-local-gates.py", gates_skill)
        self.assertIn(".copilot/zethus.config.json", gates_skill)
        for cited in re.findall(re.escape(zhome) + r"/scripts/[\w./-]+", gates_skill):
            self.assertTrue(Path(cited).is_file(), cited)

    def test_installed_scripts_find_installed_templates(self):
        self.install()
        saved_common, saved_path = sys.modules.pop("_common", None), list(sys.path)
        try:
            installed = load(self.copilot / "zethus/scripts/new-spec.py")
            self.assertEqual(Path(sys.modules["_common"].TEMPLATES_DIR).resolve(),
                             (self.copilot / "zethus/templates").resolve())
        finally:
            sys.modules["_common"] = saved_common
            sys.path[:] = saved_path

    def test_a_file_it_did_not_install_is_never_overwritten_even_with_force(self):
        mine = self.copilot / "skills/zethus-pr-description/SKILL.md"
        mine.parent.mkdir(parents=True)
        mine.write_text("my own skill", encoding="utf-8")
        code, out = self.install("--force")
        self.assertEqual(code, 1, out)
        self.assertIn("~/.copilot/skills/zethus-pr-description/SKILL.md", out)
        self.assertEqual(mine.read_text(encoding="utf-8"), "my own skill")
        self.assertFalse((self.copilot / "agents").exists(), "nothing written on a conflict")

    def test_edited_kit_file_needs_force_and_reinstall_is_idempotent(self):
        self.install()
        agent = self.copilot / "agents/zethus.agent.md"
        original = agent.read_bytes()
        code, out = self.install()
        self.assertEqual(code, 0, out)
        self.assertIn("same", out)
        agent.write_text("local edit", encoding="utf-8")
        code, out = self.install()
        self.assertEqual(code, 1, out)
        self.assertEqual(agent.read_text(encoding="utf-8"), "local edit")
        code, out = self.install("--force")
        self.assertEqual(code, 0, out)
        self.assertEqual(agent.read_bytes(), original)

    def test_unedited_old_version_is_updated(self):
        self.install()
        agent = self.copilot / "agents/zethus.agent.md"
        agent.write_text("an older kit release", encoding="utf-8")
        manifest = json.loads((self.copilot / "zethus/install-manifest.json").read_text(encoding="utf-8"))
        manifest["files"][agent.as_posix()] = install_mod.sha256(agent.read_bytes())
        (self.copilot / "zethus/install-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        code, out = self.install()
        self.assertEqual(code, 0, out)
        self.assertIn("update", out)
        self.assertNotEqual(agent.read_text(encoding="utf-8"), "an older kit release")

    def test_dry_run_writes_nothing(self):
        code, out = self.install("--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn("dry run", out)
        self.assertFalse(self.copilot.exists())

    def test_uninstall_removes_only_what_it_installed(self):
        own_agent = self.copilot / "agents/mine.agent.md"
        own_agent.parent.mkdir(parents=True)
        own_agent.write_text("mine", encoding="utf-8")
        self.install()
        extra = self.copilot / "skills/test-plan/notes.md"
        extra.write_text("my notes", encoding="utf-8")
        edited = self.copilot / "skills/write-adr/SKILL.md"
        edited.write_text("edited", encoding="utf-8")
        user_config = self.copilot / "zethus/config.json"
        user_config.write_text("{}", encoding="utf-8")

        code, out = self.install("--uninstall", "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertTrue((self.copilot / "agents/zethus.agent.md").exists())

        code, out = self.install("--uninstall")
        self.assertEqual(code, 0, out)
        self.assertFalse((self.copilot / "agents/zethus.agent.md").exists())
        self.assertFalse((self.copilot / "skills/implement-phase").exists(), "empty skill dir pruned")
        self.assertFalse((self.copilot / "zethus/scripts").exists())
        self.assertFalse((self.copilot / "zethus/install-manifest.json").exists())
        self.assertEqual(own_agent.read_text(encoding="utf-8"), "mine")
        self.assertEqual(extra.read_text(encoding="utf-8"), "my notes")
        self.assertFalse((self.copilot / "skills/test-plan/SKILL.md").exists())
        self.assertEqual(edited.read_text(encoding="utf-8"), "edited")
        self.assertEqual(user_config.read_text(encoding="utf-8"), "{}")

        code, out = self.install("--uninstall")
        self.assertEqual(code, 1, out)

    def test_uninstall_needs_user_mode(self):
        with self.assertRaises(SystemExit) as ctx, redirect_stderr(io.StringIO()):
            install_mod.main(["--target", str(self.home), "--uninstall"])
        self.assertEqual(ctx.exception.code, 2)

    def test_jetbrains_gets_the_shared_user_folders_by_default(self):
        """Current JetBrains builds read ~/.copilot/instructions; the legacy file is opt-in."""
        for platform in ("win32", "darwin", "linux"):
            with self.subTest(platform=platform), mock.patch.object(install_mod, "PLATFORM", platform):
                code, out = self.install("--dry-run")
                self.assertEqual(code, 0, out)
                self.assertIn("~/.copilot/instructions/zethus.instructions.md", out)
                self.assertNotIn("global-copilot-instructions.md", out)
        with mock.patch.object(install_mod, "PLATFORM", "win32"):
            self.assertEqual(self.install()[0], 0)
            self.assertFalse((self.home / "AppData/Local/github-copilot").exists())
            self.assertTrue((self.copilot / "instructions/zethus.instructions.md").is_file())

    def test_jetbrains_legacy_global_instructions_on_windows(self):
        with mock.patch.object(install_mod, "PLATFORM", "win32"):
            jb = self.home / "AppData/Local/github-copilot/intellij/global-copilot-instructions.md"
            code, out = self.install("--jetbrains-legacy")
            self.assertEqual(code, 0, out)
            self.assertTrue(jb.is_file())
            self.assertNotIn(".github/zethus/", jb.read_text(encoding="utf-8"))
            self.assertEqual(self.install("--uninstall")[0], 0)
            self.assertFalse(jb.exists())
            jb.parent.mkdir(parents=True, exist_ok=True)
            jb.write_text("my global rules", encoding="utf-8")
            code, out = self.install("--jetbrains-legacy")
            self.assertEqual(code, 0, out)
            self.assertIn("keep", out)
            self.assertEqual(jb.read_text(encoding="utf-8"), "my global rules")

    def test_jetbrains_legacy_on_linux_is_said_plainly(self):
        code, out = self.install()
        self.assertEqual(code, 0, out)
        self.assertNotIn("JetBrains", out)
        code, out = self.install("--jetbrains-legacy")
        self.assertEqual(code, 0, out)
        self.assertIn("no location on Linux", out)

    def test_jetbrains_legacy_needs_user_mode(self):
        with self.assertRaises(SystemExit) as ctx, redirect_stderr(io.StringIO()):
            install_mod.main(["--target", str(self.home), "--jetbrains-legacy"])
        self.assertEqual(ctx.exception.code, 2)


class ConfigResolution(FakeHome):
    def setUp(self):
        super().setUp()
        self.repo = Path(self._tmp.name) / "repo"
        (self.repo / ".git").mkdir(parents=True)

    def put(self, where: Path, name: str) -> None:
        where.parent.mkdir(parents=True, exist_ok=True)
        where.write_text(json.dumps({"gates": {"steps": [{"name": name, "command": py("pass")}]}}),
                         encoding="utf-8")

    def winner(self) -> str:
        config, _ = sys.modules["_common"].load_config(self.repo)
        return config["gates"]["steps"][0]["name"] if config else "discovery"

    def test_resolution_order(self):
        self.assertEqual(self.winner(), "discovery")
        self.put(self.copilot / "zethus/config.json", "user")
        self.assertEqual(self.winner(), "user")
        self.put(self.repo / ".claude/amphion.config.json", "amphion")
        self.assertEqual(self.winner(), "amphion")
        self.put(self.repo / ".copilot/zethus.config.json", "untracked")
        self.assertEqual(self.winner(), "untracked")
        self.put(self.repo / "elsewhere.json", "env")
        with mock.patch.dict(os.environ, {"ZETHUS_CONFIG": "elsewhere.json"}):
            self.assertEqual(self.winner(), "env")
            self.put(self.repo / ".github/zethus.config.json", "committed")
            self.assertEqual(self.winner(), "committed")

    def test_user_default_drives_gates_and_is_shown_without_the_home_path(self):
        self.put(self.copilot / "zethus/config.json", "user")
        code, out = run(gates_mod, "--repo", str(self.repo))
        self.assertEqual(code, 0, out)
        self.assertIn("Gates from: ~/.copilot/zethus/config.json", out)
        self.assertIn("| user | PASS |", out)


class WindowsCommandResolution(unittest.TestCase):
    """The Windows rules are exercised on every OS through ``resolve(windows=True)``."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.bin = self.root / "maven" / "bin"
        self.bin.mkdir(parents=True)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        patcher = mock.patch.dict(os.environ, {"PATHEXT": ".COM;.EXE;.BAT;.CMD"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def touch(self, path: Path) -> Path:
        path.write_text("", encoding="utf-8")
        return path

    def resolve(self, argv0: str):
        return gates_mod.resolve(argv0, self.repo, windows=True, path=str(self.bin))

    def test_bare_command_finds_the_cmd_wrapper_not_the_posix_script(self):
        self.touch(self.bin / "mvn")               # Maven's bin/ ships both
        cmd = self.touch(self.bin / "mvn.cmd")
        self.assertEqual(Path(self.resolve("mvn")), cmd)

    def test_bat_is_found_and_pathext_order_wins(self):
        bat = self.touch(self.bin / "tool.bat")
        self.assertEqual(Path(self.resolve("tool")), bat)
        exe = self.touch(self.bin / "tool.exe")
        self.assertEqual(Path(self.resolve("tool")), exe)

    def test_explicit_extension_is_taken_as_given(self):
        cmd = self.touch(self.bin / "mvn.cmd")
        self.assertEqual(Path(self.resolve("mvn.cmd")), cmd)

    def test_extensionless_only_is_not_runnable(self):
        self.touch(self.bin / "mvn")
        self.assertIsNone(self.resolve("mvn"))

    def test_repo_relative_wrapper_resolves_through_pathext(self):
        self.touch(self.repo / "mvnw")
        cmd = self.touch(self.repo / "mvnw.cmd")
        self.assertEqual(Path(self.resolve("./mvnw")), cmd)
        self.assertEqual(Path(self.resolve("./mvnw.cmd")), cmd)

    def test_posix_rules_are_unchanged(self):
        self.touch(self.repo / "mvnw")
        self.assertEqual(Path(gates_mod.resolve("./mvnw", self.repo, windows=False)), self.repo / "mvnw")

    def test_maven_discovery_prefers_the_wrapper(self):
        self.touch(self.repo / "pom.xml")
        gates, evidence = gates_mod.discover(self.repo)
        self.assertEqual(gates[0].argv, ["mvn", "-B", "verify"])
        wrapper = "mvnw.cmd" if os.name == "nt" else "mvnw"
        self.touch(self.repo / wrapper)
        gates, evidence = gates_mod.discover(self.repo)
        self.assertEqual(gates[0].argv, ["./" + wrapper, "-B", "verify"])
        self.assertIn("pom.xml + " + wrapper, evidence)
        self.assertEqual(gates[0].display, f"./{wrapper} -B verify", "no host path in the PR table")

    @unittest.skipUnless(os.name == "nt", "runs a real .cmd file")
    def test_configured_bare_command_runs_a_cmd_wrapper(self):
        (self.bin / "zethusgate.cmd").write_text("@exit /b 0\r\n", encoding="utf-8")
        (self.repo / ".github").mkdir()
        (self.repo / ".github/zethus.config.json").write_text(
            json.dumps({"gates": {"steps": [{"name": "mvn", "command": "zethusgate verify"}]}}),
            encoding="utf-8")
        with mock.patch.dict(os.environ, {"PATH": str(self.bin) + os.pathsep + os.environ["PATH"]}):
            code, out = run(gates_mod, "--repo", str(self.repo))
        self.assertEqual(code, 0, out)
        self.assertIn("| mvn | PASS |", out)


if __name__ == "__main__":
    unittest.main()

"""The Zethus agent file and its mirror stay under a character budget, so the limit can't creep back.

GitHub caps an agent's prompt at 30,000 characters. ``scripts/check_zethus_agent_budget.py`` fails
above 28,000 and warns above 24,000 by default; ``ZETHUS_AGENT_MAX_CHARS`` and
``ZETHUS_AGENT_WARN_CHARS`` change both, here and in the script. Why: ``zethus/docs/agent-file-budget.md``.
"""
from __future__ import annotations

import importlib.util
import io
import re
import sys
import tempfile
import unittest
import warnings
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
KIT = REPO / "zethus"
SCRIPT = REPO / "scripts" / "check_zethus_agent_budget.py"

spec = importlib.util.spec_from_file_location("check_zethus_agent_budget", SCRIPT)
budget = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = budget
spec.loader.exec_module(budget)


def run(*argv: str, env: dict[str, str] | None = None) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict("os.environ", env or {}, clear=False), redirect_stdout(out), redirect_stderr(err):
        code = budget.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class TheAgentFilesAreWithinBudget(unittest.TestCase):
    def test_both_copies_are_under_the_budget_and_warn_near_it(self):
        max_chars, warn_chars = budget.limits()
        self.assertEqual(len(budget.AGENT_FILES), 2)
        for path in budget.AGENT_FILES:
            size = budget.measure(path)
            with self.subTest(copy=path.relative_to(REPO).as_posix(), size=size):
                self.assertLessEqual(size, max_chars,
                                     f"{path.name} is {size:,} characters, over the {max_chars:,} budget: "
                                     "move detail into skills/zethus-conduct (docs/agent-file-budget.md)")
                self.assertLess(size, budget.COPILOT_LIMIT)
                if size > warn_chars:
                    warnings.warn(f"{path.relative_to(REPO).as_posix()} is {size:,} characters, over the "
                                  f"{warn_chars:,} warning level: move detail out before adding more")

    def test_the_defaults_are_the_documented_ones(self):
        self.assertEqual((budget.DEFAULT_MAX, budget.DEFAULT_WARN, budget.COPILOT_LIMIT),
                         (28_000, 24_000, 30_000))
        self.assertEqual(budget.limits({}), (28_000, 24_000))
        record = (KIT / "docs" / "agent-file-budget.md").read_text(encoding="utf-8")
        for phrase in ("28,000", "24,000", "30,000", "paraphrased"):
            self.assertIn(phrase, record)
        self.assertNotIn("\n> ", record, "a public record paraphrases; no block quote")
        readme = (KIT / "README.md").read_text(encoding="utf-8")
        self.assertIn("scripts/check_zethus_agent_budget.py", readme)

    def test_the_repo_check_passes(self):
        code, out, _ = run()
        self.assertEqual(code, 0)
        self.assertEqual(len(re.findall(r"characters \(budget", out + _)), 2, "both copies measured")


class TheCheck(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def agent(self, chars: int) -> Path:
        path = self.dir / f"a{chars}.agent.md"
        path.write_text("x" * chars, encoding="utf-8")
        return path

    def test_verdicts_at_the_edges(self):
        self.assertEqual(budget.verdict(24_000, 28_000, 24_000), "ok")
        self.assertEqual(budget.verdict(24_001, 28_000, 24_000), "warn")
        self.assertEqual(budget.verdict(28_000, 28_000, 24_000), "warn")
        self.assertEqual(budget.verdict(28_001, 28_000, 24_000), "over")

    def test_counts_characters_not_bytes(self):
        path = self.dir / "u.agent.md"
        path.write_text("—▶✓", encoding="utf-8")
        self.assertEqual(budget.measure(path), 3)

    def test_over_budget_fails(self):
        code, _, err = run(str(self.agent(28_001)))
        self.assertEqual(code, 1)
        self.assertIn("OVER BUDGET", err)

    def test_over_the_warning_level_passes_with_a_warning(self):
        code, _, err = run(str(self.agent(24_001)))
        self.assertEqual(code, 0)
        self.assertIn("warning", err)

    def test_flags_and_environment_change_the_limits(self):
        small = str(self.agent(1_000))
        self.assertEqual(run(small, "--max", "999", "--warn", "500")[0], 1)
        self.assertEqual(run(small, env={"ZETHUS_AGENT_MAX_CHARS": "999", "ZETHUS_AGENT_WARN_CHARS": "500"})[0], 1)
        self.assertEqual(run(small, "--max", "2000", env={"ZETHUS_AGENT_MAX_CHARS": "999",
                                                          "ZETHUS_AGENT_WARN_CHARS": "500"})[0], 0,
                         "a flag beats the environment")

    def test_a_missing_file_fails_and_bad_limits_are_usage_errors(self):
        self.assertEqual(run(str(self.dir / "nope.agent.md"))[0], 1)
        self.assertEqual(run("--max", "100", "--warn", "200")[0], 2)
        self.assertEqual(run(env={"ZETHUS_AGENT_MAX_CHARS": "lots"})[0], 2)
        self.assertEqual(run("--bogus")[0], 2)


class TheDetailMovedToALinkedSkill(unittest.TestCase):
    def test_every_conduct_anchor_the_agent_links_exists(self):
        conduct = (KIT / "skills" / "zethus-conduct" / "SKILL.md").read_text(encoding="utf-8")
        anchors = {re.sub(r"[^a-z0-9 -]", "", h.lower()).replace(" ", "-")
                   for h in re.findall(r"(?m)^## (.+)$", conduct)}
        for path in budget.AGENT_FILES:
            links = re.findall(r"zethus-conduct/SKILL\.md#([a-z0-9-]+)", path.read_text(encoding="utf-8"))
            with self.subTest(copy=path.parent.parent.name):
                self.assertGreaterEqual(len(links), 6)
                self.assertEqual(sorted(set(links) - anchors), [])


if __name__ == "__main__":
    unittest.main()

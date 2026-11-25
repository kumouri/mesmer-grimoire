"""Zethus has a third path for one-off work, beside the minimum and full spec.

Ceryce's ask, 2026-11-24 (paraphrased; a public repo, so nothing of hers is quoted): Zethus needs a
mode for one-off work — run a job in Kubernetes, restart or scale something, tail logs, a query —
that doesn't need an ADR and a signed-off spec. These tests pin that mode's invariants: the agent
file (both copies) carries the one-off section and routes to it from its description; the path is
picked from what the work leaves behind, not from what it's called, so a tracked-file change can't
skip the spec by calling itself a one-off; the ``run-one-off`` skill carries the light procedure and
a worked Kubernetes example with generic names; and the stop guard leaves a one-off turn alone,
since it is not a staged ``Stage N`` turn and adds no new wall.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KIT = REPO / "zethus"
CANONICAL = KIT / "com.github.copilot" / "agents" / "zethus.agent.md"
MIRROR = KIT / "agents" / "zethus.agent.md"
AGREEMENT = KIT / "copilot-instructions.md"
SKILL = KIT / "skills" / "run-one-off" / "SKILL.md"
README = KIT / "README.md"
CONFIG = KIT / "zethus.config.example.json"
GUARD = KIT / "com.github.copilot" / "hooks" / "stop_guard.py"
SECTION_HEADING = "## One-off work: the third path"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


guard = load("stop_guard_one_off", GUARD)


def frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    fields: dict[str, str] = {}
    for line in (m.group(1).splitlines() if m else []):
        key, sep, value = line.partition(":")
        if sep and not line.startswith(" "):
            fields[key.strip()] = value.strip().strip('"')
    return fields


def section(text: str, heading: str) -> str:
    return text.split(heading, 1)[1].split("\n## ", 1)[0] if heading in text else ""


class TheAgentFileCarriesTheThirdPath(unittest.TestCase):
    def test_both_copies_have_the_one_off_section_and_route_to_it(self):
        for path, link in ((CANONICAL, "../../skills/run-one-off/SKILL.md"),
                           (MIRROR, "../skills/run-one-off/SKILL.md")):
            text = path.read_text(encoding="utf-8")
            with self.subTest(copy=path.parent.parent.name):
                self.assertIn(SECTION_HEADING, text)
                self.assertIn(link, text, "the section links the run-one-off skill")
                # The description routes one-offs to the agent.
                desc = frontmatter(path)["description"].lower()
                self.assertIn("one-off", desc)
                self.assertRegex(desc, r"no (spec|sign-off).*(sign-off|pr|gate)")

    def test_the_section_pins_the_dividing_line_and_the_light_must_haves(self):
        body = re.sub(r"\s+", " ", section(CANONICAL.read_text(encoding="utf-8"), SECTION_HEADING).lower())
        for phrase in (
            "action or an answer",          # the one-off side of the line
            "leaves no tracked change",     # what makes it a one-off
            "never a one-off",              # a tracked-file change is never one
            "from what the work leaves behind, not what it's called",  # the test is the output
            "the person's word wins",       # the user's word wins either direction
            "switch to the staged path",    # if a tracked edit is needed, switch
            "host's permission prompts",    # no new confirmation of its own
            "check the real result",        # verify the real outcome
            "how to undo",                  # report what it left behind and cleanup
        ):
            self.assertIn(phrase, body, phrase)

    def test_the_loophole_cannot_let_a_code_change_skip_the_spec(self):
        """Naming a tracked-file change a one-off must not skip the spec (the refusal table)."""
        text = CANONICAL.read_text(encoding="utf-8")
        body = section(text, SECTION_HEADING).lower()
        self.assertIn("doesn't make it one", body)
        # The refusal table has a row that declines the skip (not the work) for a tracked change.
        refuse = text.split("## What you refuse", 1)[1].split("\n## ", 1)[0].lower()
        self.assertIn("one-off", refuse)
        self.assertRegex(refuse, r"changes tracked code, config or docs")
        self.assertRegex(refuse, r"takes the spec")

    def test_a_one_off_turn_is_not_a_staged_turn(self):
        """The reply opens with One-off ·, not Stage N, so the stage rules and stop table don't bind."""
        body = section(CANONICAL.read_text(encoding="utf-8"), SECTION_HEADING)
        self.assertIn("`One-off ·", body)
        self.assertIn("not `Stage N`", body)

    def test_the_agreement_also_describes_the_one_off_path(self):
        text = AGREEMENT.read_text(encoding="utf-8").lower()
        self.assertIn("one-off", text)
        self.assertIn("leaving no tracked change", text)
        self.assertIn("run-one-off", text)


class TheSkillCarriesTheProcedure(unittest.TestCase):
    def test_frontmatter_is_valid_for_copilot(self):
        fm = frontmatter(SKILL)
        self.assertEqual(fm.get("name"), "run-one-off")
        self.assertRegex(fm["name"], r"^[a-z0-9]+(-[a-z0-9]+)*$")
        self.assertTrue(fm.get("description"))
        self.assertLessEqual(len(fm["description"]), 1024)
        # The description has a colon-space, so it must be quoted or the Copilot CLI drops the skill.
        raw = SKILL.read_text(encoding="utf-8").split("---", 2)[1]
        desc_line = next(l for l in raw.splitlines() if l.startswith("description:"))
        self.assertTrue(desc_line.split(":", 1)[1].strip().startswith('"'), "quoted description")

    def test_the_light_must_haves_are_all_present(self):
        text = SKILL.read_text(encoding="utf-8").lower()
        for phrase in (
            "find the repo's or team's own way first",  # use the established way
            "in one line, then run it",                 # state target + command, then run
            "wait for the real result",                 # verify the real outcome
            "exit code",                                # ... the concrete signals
            "how to undo it",                           # report what it left behind + cleanup
            "investigated, not retried",                # a failure is read-only, not a silent loop
            "optional:",                                # a note in the log is optional, not required
            "never a new required artifact",
            "switch to",                                # switch to the spec if a tracked edit is needed
        ):
            self.assertIn(phrase, text)
        # It is explicitly the third path, beside the two specs.
        self.assertIn("../write-spec-minimum/SKILL.md", SKILL.read_text(encoding="utf-8"))
        self.assertIn("../write-spec-full/SKILL.md", SKILL.read_text(encoding="utf-8"))

    def test_the_worked_kubernetes_example_uses_generic_names(self):
        text = SKILL.read_text(encoding="utf-8")
        example = text.split("## Worked example: run a Kubernetes job", 1)[1]
        self.assertIn("kubectl", example)
        self.assertIn("--for=condition=complete", example, "it checks the job actually completed")
        self.assertIn("delete job", example.lower(), "it gives the undo command")
        # Generic, placeholder-style names only — no real-looking host, domain or email.
        self.assertIn("staging-use1", example)
        self.assertIn("batch", example)
        self.assertNotRegex(example, r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "no email")
        self.assertNotRegex(example, r"https?://(?!\s)", "no real URLs in the example")


class TheStopGuardLeavesAOneOffTurnAlone(unittest.TestCase):
    """A one-off turn isn't a staged Stage N turn, so the guard adds no wall (the brief: no new
    refusals beyond the host's own permission prompts)."""

    def one_off_reply(self) -> str:
        return (
            "One-off · run the nightly reconciliation job in staging\n\n"
            "context staging-use1, namespace batch → kubectl -n batch create -f deploy/jobs/reconcile.yaml\n\n"
            "Job `reconcile-nightly` completed in 6m, exit 0, logs show 412 rows reconciled. It left "
            "one Job object and its pod in `batch`. Undo: `kubectl -n batch delete job reconcile-nightly`."
        )

    def test_it_is_not_recognised_as_a_staged_turn(self):
        self.assertFalse(guard.is_zethus_turn(self.one_off_reply()))

    def test_refuse_lets_the_one_off_turn_end(self):
        self.assertEqual(guard.refuse({"sessionId": "one-off-test"}, self.one_off_reply()), "")

    def test_remind_says_nothing_after_a_one_off_turn(self):
        event = {"sessionId": "one-off-test", "lastAssistantMessage": self.one_off_reply(),
                 "prompt": "thanks"}
        self.assertEqual(guard.remind(event), "")


class TheConfigAndDocsDocumentTheSetting(unittest.TestCase):
    def test_the_example_config_has_one_off_confirm_off_by_default(self):
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertIn("oneOff", config)
        self.assertEqual(config["oneOff"].get("confirm"), False)

    def test_the_readme_documents_the_path_and_the_setting(self):
        text = README.read_text(encoding="utf-8")
        self.assertIn("skills/run-one-off/SKILL.md", text)
        self.assertIn("`oneOff.confirm`", text)
        self.assertIn("one-off", text.lower())


if __name__ == "__main__":
    unittest.main()

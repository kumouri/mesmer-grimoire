"""Logging is the first deliverable of anything Zethus builds, added at creation.

Ceryce's ruling, 2026-11-19 (paraphrased; ``zethus/docs/log-from-the-start.md``): always add
logging from the start, because it finds and fixes errors faster. The kit already let Phase 0
"instrument, log, measure or report"; that made logging a kind of Phase 0, not part of every
phase's code. These tests pin the standing rule wherever Zethus says how to build (implement-phase,
the agent and its mirror, the working agreement, the spec skills and templates), what the log has
to hold, and that the Phase 0 line was extended rather than duplicated.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KIT = REPO / "zethus"
IMPLEMENT = KIT / "skills" / "implement-phase" / "SKILL.md"
CANONICAL = KIT / "com.github.copilot" / "agents" / "zethus.agent.md"
MIRROR = KIT / "agents" / "zethus.agent.md"
AGREEMENT = KIT / "copilot-instructions.md"
RECORD = KIT / "docs" / "log-from-the-start.md"
WHY = "docs/log-from-the-start.md"
SECTION = "## Logging is the first deliverable, in every phase"


def flat(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


class ImplementPhase(unittest.TestCase):
    def test_the_rule_is_its_own_section_and_says_when_and_what(self):
        text = IMPLEMENT.read_text(encoding="utf-8")
        self.assertIn(SECTION, text)
        body = re.sub(r"\s+", " ", text.split(SECTION, 1)[1].split("\n## ", 1)[0])
        self.assertIn("**in the same commit that creates it**", body)
        self.assertIn("never later when debugging", body)
        for held in ("configuration the run started with", "decisions it made",
                     "state changes that matter", "full errors", "stack trace"):
            self.assertIn(held, body)
        self.assertIn("survives a crash", body)
        self.assertIn("Never log a secret's value", body)
        self.assertIn("add the log first, then reproduce, then form a theory", body)
        self.assertIn(WHY, body)

    def test_phase_0_is_extended_not_duplicated(self):
        text = flat(IMPLEMENT)
        self.assertIn("It only instruments, logs, measures, reports", text, "the old line stays")
        self.assertIn("A Phase 0 that only adds logging is a valid Phase 0, but logging isn't only "
                      "Phase 0's job", text)
        self.assertIn("(#logging-is-the-first-deliverable-in-every-phase)", text)
        self.assertEqual(text.count(SECTION), 1)

    def test_the_procedure_steps_keep_their_numbers(self):
        """Other docs cite step 4's table and step 6; the rule didn't renumber them."""
        text = IMPLEMENT.read_text(encoding="utf-8")
        self.assertRegex(text, r"\n4\. \*\*Stay inside the phase\.\*\*")
        self.assertRegex(text, r"\n6\. \*\*Update the spec\*\*")


class EverywhereZethusSaysHowToBuild(unittest.TestCase):
    def test_the_agent_and_its_mirror(self):
        for path in (CANONICAL, MIRROR):
            text = flat(path)
            with self.subTest(where=path.parent.parent.name):
                self.assertIn("**Log from the start.** Logging ships in the commit that creates the "
                              "code, not when debugging", text)
                self.assertIn("#logging-is-the-first-deliverable-in-every-phase", text)

    def test_the_working_agreement(self):
        text = AGREEMENT.read_text(encoding="utf-8")
        self.assertIn("## Log from the start", text)
        self.assertIn("Logging is the first deliverable of any script, tool or feature",
                      flat(AGREEMENT))
        self.assertIn(WHY, text)

    def test_the_spec_skills_and_templates(self):
        for rel in ("skills/write-spec-full/SKILL.md", "skills/write-spec-minimum/SKILL.md",
                    "templates/spec-full.md", "templates/spec-minimum.md"):
            text = flat(KIT / rel)
            with self.subTest(doc=rel):
                self.assertIn("ogs what it builds", text)
                self.assertIn("starting config, decisions, state changes, full errors", text)
        for rel in ("templates/spec-full.md", "templates/spec-minimum.md"):
            self.assertIn("| 0 | Instrument / log / report only |", (KIT / rel).read_text(encoding="utf-8"))


class Record(unittest.TestCase):
    def test_the_record_paraphrases_and_is_routed_to(self):
        text = RECORD.read_text(encoding="utf-8")
        self.assertIn("| Date | 2026-11-19 |", text)
        self.assertIn("Ceryce's ruling, paraphrased", text)
        self.assertNotIn("\n> ", text, "a public record paraphrases; no block quote")
        self.assertIn(WHY, (KIT / "README.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
